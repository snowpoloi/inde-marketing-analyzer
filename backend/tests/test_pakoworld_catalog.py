import io
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from sqlalchemy import func, select

from app.connectors import supplier_catalog as connector
from app.models import ProductCatalog, SupplierCatalogProduct, SupplierProductCost
from app.schemas.supplier_catalog import SupplierCatalogFeedInput
from app.services import supplier_catalog_service as service


URL = "https://www.pakoworld.com/?route=feed&token=fixture-private-token"


def xml(model="123-000001", extra=""):
    return f"""<pakoworld><products><product id="55"><model>{model}</model>
    <ean>5207351018882</ean><name>Garden cabinet</name><quantity>102</quantity>
    <net_price>57.1</net_price><stock_price>57.1</stock_price><has_net_price>0</has_net_price>
    <retail_price_with_vat>90.00</retail_price_with_vat><sell_step>2</sell_step>
    <main_image>https://www.pakoworld.com/image/cabinet.jpg</main_image>
    <width>37</width><length>80</length><height>123</height><volume>0.089</volume>
    <attributes><attribute id="4">Package: 123x40x18</attribute></attributes>
    <categories><category id="145">Storage</category></categories>
    <component_1>001-000002</component_1><pieces_1>2</pieces_1>{extra}
    </product></products></pakoworld>""".encode()


def rows():
    return connector.parse_pakoworld_catalog(io.BytesIO(xml()))


def test_pakoworld_fields_do_not_infer_costs_tax_or_shipping():
    row = rows()[0]
    assert row["supplier_code"] == "123-000001" and row["supplier_sku"] is None
    assert row["ean"] == "5207351018882" and row["quantity"] == 102
    assert row["retail_price_gross"] == "90.00" and row["wholesale_price_net"] is None
    assert row["details"]["net_price"] == "57.1" and row["details"]["has_net_price"] == "0"
    assert row["details"]["sell_step"] == "2"
    assert row["details"]["comb_width_cm"] is None
    assert row["details"]["attributes"] == [{"id": "4", "value": "Package: 123x40x18"}]
    assert row["details"]["components"] == [{"model": "001-000002", "pieces": "2"}]
    assert row["details"]["categories"] == [{"id": "145", "name": "Storage"}]
    assert "net_unit_cost" not in row and "shipping_net" not in row


def test_pakoworld_extracts_each_shipping_box_from_attributes():
    from app.services.supplier_catalog_settings import package_metrics
    source = xml().decode().replace("Package: 123x40x18", "Package: 47x188x10 - 49x131x15")
    source = source.replace('<attributes>', '<attributes><attribute id="2">Boxes: 2</attribute>')
    details = connector.parse_pakoworld_catalog(io.BytesIO(source.encode()))[0]["details"]
    assert details["packages_per_item"] == "2"
    assert details["sell_step"] == "2"
    metrics = package_metrics(details, 5000)
    assert len(metrics["packages"]) == 2
    assert metrics["packages"][0]["length_cm"] == "47"
    assert metrics["packages"][0]["width_cm"] == "188"
    assert metrics["packages"][0]["height_cm"] == "10"
    assert metrics["packages"][0]["volume_m3"] == Decimal("0.08836")
    assert metrics["packages"][0]["volumetric_kg"] == Decimal("17.672")
    assert metrics["packages"][1]["volume_m3"] == Decimal("0.096285")
    assert metrics["packages"][1]["volumetric_kg"] == Decimal("19.257")
    assert metrics["volume_total_m3"] == Decimal("0.184645")
    assert metrics["volumetric_total_kg"] == Decimal("36.929")


@pytest.mark.parametrize("count", range(1, 7))
def test_pakoworld_box_count_is_not_sale_quantity_or_assembled_dimensions(count):
    from app.services.supplier_catalog_settings import package_metrics
    details = connector.pakoworld_package_details({
        "sell_step": "4", "length": "200", "width": "100", "height": "80", "volume": "1.6",
        "attributes": [{"id": "2", "value": f"Boxes: {count}"},
                       {"id": "4", "value": "Package: " + " - ".join("20x30x40" for _ in range(count))}],
    })
    assert details["packages_per_item"] == str(count)
    assert len(details["packages"]) == count
    assert package_metrics(details, 5000)["volume_total_m3"] == Decimal("0.024") * count
    assert package_metrics(details, 6000)["volumetric_total_kg"] == Decimal("4") * count


@pytest.mark.parametrize("text", ["47,5 x 188 x 10;49x131x15", "47.5X188X10 | 49X131X15 cm",
                                  "47.5\u00d7188\u00d710-49\u00d7131\u00d715"])
def test_pakoworld_package_separator_and_decimal_formats(text):
    details = connector.pakoworld_package_details({"attributes": [
        {"id": "2", "value": "2"}, {"id": "4", "value": "Package: " + text}]})
    assert details["packages"][0]["length_cm"] == "47.5"
    assert details["packages"][1]["length_cm"] == "49"
    assert details["package_dimensions_complete"] is True


@pytest.mark.parametrize("count,dimensions", [("3", "47x188x10 - 49x131x15"),
    ("1", "47x188x10 - 49x131x15"), ("2", "47x188x10 - unknown"),
    ("2", "47x188x10 mm - 49x131x15"), ("2", "0x188x10 - 49x131x15"),
    ("unknown", "47x188x10 - 49x131x15")])
def test_incomplete_or_conflicting_packaging_does_not_fabricate_totals(count, dimensions):
    from app.services.supplier_catalog_settings import package_metrics
    details = connector.pakoworld_package_details({"attributes": [
        {"id": "2", "value": count}, {"id": "4", "value": "Package: " + dimensions}]})
    assert package_metrics(details, 5000)["volume_total_m3"] is None
    assert package_metrics(details, 5000)["volumetric_total_kg"] is None


def test_stored_pakoworld_details_are_normalized_without_mutation():
    raw = {"packages": [], "attributes": [{"id": "2", "value": "Boxes: 2"},
           {"id": "4", "value": "Package: 47x188x10 - 49x131x15"}]}
    normalized = connector.pakoworld_package_details(raw)
    assert raw["packages"] == [] and "packages_per_item" not in raw
    assert connector.pakoworld_package_details(normalized) == normalized
    assert len(normalized["packages"]) == 2
    assert connector.pakoworld_package_details({"sell_step": "4", "length": "200", "volume": "0.2"})["packages"] == []


def test_conflicting_box_counts_do_not_assume_dimension_list_is_complete():
    from app.services.supplier_catalog_settings import package_metrics
    details = connector.pakoworld_package_details({"attributes": [
        {"id": "2", "value": "Boxes: 2"}, {"id": "2", "value": "Boxes: 3"},
        {"id": "4", "value": "Package: 47x188x10 - 49x131x15"}]})
    assert len(details["packages"]) == 2
    assert package_metrics(details, 5000)["volume_total_m3"] is None


def test_product_detail_restores_existing_pakoworld_boxes_without_resync(db):
    from app.api.routes.supplier_catalog import product
    from app.models import SupplierCatalogFeed
    feed = SupplierCatalogFeed(code="BOX-FIXTURE", name="Boxes", adapter="pakoworld", encrypted_url="test-unused")
    db.add(feed); db.flush()
    stored = {"packages": [], "attributes": [{"id": "2", "value": "Boxes: 2"},
              {"id": "4", "value": "Package: 47x188x10 - 49x131x15"}]}
    row = SupplierCatalogProduct(feed_id=feed.id, supplier_code="box-fixture", name="Cabinet",
                                 details=stored, last_seen_at=datetime.now(timezone.utc))
    db.add(row); db.flush()
    result = product(row.id, _=SimpleNamespace(is_admin=True), db=db)
    assert result["details"]["packages_per_item"] == "2"
    assert len(result["packages"]) == 2
    assert result["volume_total_m3"] == Decimal("0.184645")
    assert row.details == stored and row.details["packages"] == []
    feed.adapter = "megapap"
    assert product(row.id, _=SimpleNamespace(is_admin=True), db=db)["packages"] == []


@pytest.mark.parametrize("adapter, url", [
    ("megapap", URL), ("pakoworld", "https://www.megapap.com/feed"),
    ("pakoworld", "http://pakoworld.com/feed"), ("pakoworld", "https://pakoworld.com.evil.test/"),
    ("pakoworld", "https://user:secret@pakoworld.com/"), ("pakoworld", "https://127.0.0.1/"),
    ("pakoworld", "https://pakoworld.com:9000/"), ("pakoworld", "https://pakoworld.com/feed#fragment"),
])
def test_schema_binds_url_to_adapter(adapter, url):
    with pytest.raises(ValueError):
        SupplierCatalogFeedInput(code="PAKOWORLD", name="Pakketo", adapter=adapter, url=url)


def test_pakoworld_schema_and_optional_url():
    payload = SupplierCatalogFeedInput(code="AADE_800749270", name="Pakketo", url=URL, adapter="pakoworld")
    assert payload.url == URL
    assert SupplierCatalogFeedInput(code="PAKOWORLD", name="Pakketo", adapter="pakoworld", url=" ").url is None
    with pytest.raises(ValueError):
        SupplierCatalogFeedInput(code="OTHER", name="Other", adapter="arbitrary", url=URL)


def test_wrong_roots_empty_duplicate_and_entities_are_rejected():
    with pytest.raises(ValueError, match="PAKOWORLD"):
        connector.parse_pakoworld_catalog(io.BytesIO(b"<megapap/>"))
    with pytest.raises(ValueError, match="MEGAPAP"):
        connector.parse_megapap_catalog(io.BytesIO(xml()))
    with pytest.raises(ValueError, match="no products"):
        connector.parse_pakoworld_catalog(io.BytesIO(b"<pakoworld/>"))
    product = xml().decode().split("<products>")[1].split("</products>")[0]
    with pytest.raises(ValueError, match="Duplicate"):
        connector.parse_pakoworld_catalog(io.BytesIO(f"<pakoworld><products>{product}{product}</products></pakoworld>".encode()))
    with pytest.raises(DefusedXmlException):
        connector.parse_pakoworld_catalog(io.BytesIO(b'<!DOCTYPE x [<!ENTITY y "data">]><pakoworld>&y;</pakoworld>'))


def test_media_cannot_point_to_other_suppliers_or_token_urls():
    row = connector.parse_pakoworld_catalog(io.BytesIO(xml(extra="""<images>
        <image>https://www.megapap.com/image.jpg</image><image>https://www.pakoworld.com/image.jpg?token=private</image>
        <image>https://www.pakoworld.com/safe.jpg</image></images>""")))[0]
    assert row["details"]["images"] == ["https://www.pakoworld.com/safe.jpg"]


def test_pakoworld_model_checks_own_sku_but_conflicts_never_choose_arbitrarily():
    first, second = uuid4(), uuid4()
    def own(id, sku, ean=None):
        return SimpleNamespace(id=id, sku=sku, model=None, mpn=None, ean=ean, upc=None)
    index = service.build_catalog_index([own(first, "123-000001")])
    assert service.match_supplier_product(rows()[0], index, "pakoworld") == (first, "exact_identifiers")
    assert service.match_supplier_product(rows()[0], index, "megapap") == (None, "unmatched")
    index = service.build_catalog_index([own(first, "123-000001"), own(second, "Other", "5207351018882")])
    assert service.match_supplier_product(rows()[0], index, "pakoworld") == (None, "ambiguous")


def test_fetch_get_only_streaming_size_limit_and_cross_supplier_redirect(monkeypatch):
    client_class = httpx.Client
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, content=xml())
    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    assert connector.fetch_pakoworld_catalog(URL)[0]["supplier_code"] == "123-000001"
    assert calls == ["GET"]
    monkeypatch.setattr(connector, "PAKOWORLD_MAX_FEED_BYTES", 32)
    with pytest.raises(ValueError, match="size or time"):
        connector.fetch_pakoworld_catalog(URL)
    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://www.megapap.com/feed"})
    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(redirect), **kwargs))
    with pytest.raises(ValueError, match="HTTPS"):
        connector.fetch_pakoworld_catalog(URL)


def test_worker_dispatch_encryption_and_no_financial_mutations(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "secret_key", "isolated-pakoworld-test-key")
    own = ProductCatalog(sku="123-000001", name="Our cabinet", quantity=7, price=99)
    db.add(own); db.flush()
    saved = service.save_feed(db, SupplierCatalogFeedInput(code="AADE_800749270", name="Pakketo",
                                                         adapter="pakoworld", url=URL))
    assert "fixture-private-token" not in saved.encrypted_url
    assert "fixture-private-token" not in str(service.feed_response(saved))
    def wrong_fetch(url):
        pytest.fail("Pakoworld must not use the MEGAPAP adapter")
    monkeypatch.setattr(service, "fetch_megapap_catalog", wrong_fetch)
    monkeypatch.setattr(service, "fetch_pakoworld_catalog", lambda url: rows())
    assert service.process_supplier_catalog(db)["matched"] == 1
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    db.refresh(own)
    assert own.price == 99 and own.quantity == 7 and own.name == "Our cabinet"
    service.save_feed(db, SupplierCatalogFeedInput(code=saved.code, name="Pakketo", adapter="pakoworld"), saved.id)
    with pytest.raises(ValueError, match="megapap"):
        service.save_feed(db, SupplierCatalogFeedInput(code=saved.code, name="Pakketo", adapter="megapap"), saved.id)
    service.queue_feed(db, saved.id)
    monkeypatch.setattr(service, "fetch_pakoworld_catalog", lambda url: (_ for _ in ()).throw(RuntimeError(url)))
    assert service.process_supplier_catalog(db) == {"failed": True}
    assert "fixture-private-token" not in saved.error
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct).where(SupplierCatalogProduct.is_current)) == 1
