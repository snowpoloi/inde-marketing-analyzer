import io
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from xml.etree import ElementTree as ET

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from sqlalchemy import func, select

from app.connectors import supplier_catalog as connector
from app.connectors.supplier_catalog_profiles import category_details, category_profiles, parse_profile_catalog
from app.connectors.supplier_formats import FORMATS
from app.schemas.supplier_catalog import SupplierCatalogFeedInput
from app.services import supplier_catalog_service as service
from app.services.supplier_catalog_pricing import sale_quantity
from app.models import ProductCatalog, SupplierCatalogProduct, SupplierProductCost


def xml(adapter, *, changes=None, duplicate=False):
    spec = FORMATS[adapter]
    root = ET.Element(spec["root"])
    parent = root
    for tag in spec["path"][1:-1]:
        parent = ET.SubElement(parent, tag)
    fields = {spec["code"]: "001-ABC", spec["sku"]: "001-ABC", spec["name"]: "Fixture product",
              category_profiles()[adapter]["category_field"]: "Fixture category"}
    for field, value in [(spec["stock"], "8"), (spec["retail"], "124"),
                         (spec.get("wholesale"), "50"), (spec.get("step"), "1"),
                         (spec.get("model"), "001-ABC"), (spec["ean"], "5200000000001")]:
        if field:
            fields[field] = value
    fields.update(changes or {})
    for _ in range(2 if duplicate else 1):
        item = ET.SubElement(parent, spec["path"][-1])
        for field, value in fields.items():
            if value is None:
                continue
            if field.startswith("@"):
                item.set(field[1:], value)
            else:
                ET.SubElement(item, field).text = value
    return ET.tostring(root, encoding="utf-8")


def parse(adapter, **kwargs):
    return parse_profile_catalog(io.BytesIO(xml(adapter, **kwargs)), adapter)


@pytest.mark.parametrize("adapter", FORMATS)
def test_each_audited_schema_preserves_identity_and_never_creates_cost(adapter):
    row = parse(adapter)[0]
    assert row["supplier_code"] == "001-ABC"
    assert row["supplier_sku"] == "001-ABC"
    assert row["details"]["shop_model"] == FORMATS[adapter]["prefix"] + "001-ABC"
    assert row["details"]["shop_sku"] == "001-ABC"
    assert row["details"]["packages"] == []
    assert row["wholesale_price_net"] == ("50" if adapter == "daisat" else None)
    assert row["retail_price_gross"] == ("124" if FORMATS[adapter]["retail"] else None)
    assert "net_unit_cost" not in str(row)
    assert row["quantity"] == (8 if FORMATS[adapter]["stock"] else None)
    url = "https://" + sorted(FORMATS[adapter]["hosts"])[0] + "/fixture.xml"
    assert SupplierCatalogFeedInput(code=adapter, name=adapter, adapter=adapter, url=url).adapter == adapter


@pytest.mark.parametrize("adapter", FORMATS)
def test_new_adapter_hosts_are_isolated(adapter):
    for url in ["https://127.0.0.1/", "https://megapap.com/private", "http://" + next(iter(FORMATS[adapter]["hosts"])),
                "https://" + next(iter(FORMATS[adapter]["hosts"])) + ".evil.test/", "https://user:pass@" + next(iter(FORMATS[adapter]["hosts"])) + ":444/"]:
        with pytest.raises(ValueError):
            connector.validate_feed_url(url, adapter)


def test_excluded_adapters_stay_unsupported():
    for adapter in ["metaxakis", "liberta"]:
        with pytest.raises(ValueError):
            SupplierCatalogFeedInput(code=adapter, name=adapter, adapter=adapter)


def test_daisat_merges_only_category_memberships():
    rows = parse("daisat", duplicate=True)
    assert len(rows) == 1 and rows[0]["quantity"] == 8
    assert rows.diagnostics["merged_category_rows"] == 1
    root = ET.fromstring(xml("daisat", duplicate=True))
    root[1].find("category_name").text = "Second category"
    rows = parse_profile_catalog(io.BytesIO(ET.tostring(root)), "daisat")
    assert rows[0]["details"]["source_categories"] == ["Fixture category", "Second category"]
    root[1].find("price_wholesale_untaxed").text = "51"
    with pytest.raises(ValueError, match="conflicting"):
        parse_profile_catalog(io.BytesIO(ET.tostring(root)), "daisat")


@pytest.mark.parametrize("adapter", [a for a in FORMATS if a != "daisat"])
def test_unapproved_duplicate_records_fail_the_snapshot(adapter):
    with pytest.raises(ValueError, match="Duplicate"):
        parse(adapter, duplicate=True)


def test_header_non_product_and_unnamed_records_are_distinct():
    with pytest.raises(ValueError, match="no products"):
        parse("anthemidis", changes={"product_sku": "product_sku", "product_name": "product_name"})
    with pytest.raises(ValueError, match="no products"):
        parse("anthemidis", changes={"product_name": "", "Web_price": None, "pricewithouttax": None, "product_in_stock": "unavailable"})
    row = parse("kanellopoulos", changes={"Name_el": ""})[0]
    assert row["name"] == "001-ABC" and row["details"]["missing_name"]
    with pytest.raises(ValueError, match="no products"):
        parse("arlight", changes={"Sku": "", "Title": "Credit"})
    with pytest.raises(ValueError, match="valid code"):
        parse("arlight", changes={"Sku": "", "Title": "Real product"})


def test_no_guessed_stock_prices_shipping_or_sale_quantity():
    row = parse("gloria", changes={"availability": "In stock", "priceWholesale": "12.40", "dimension_x": "0"})[0]
    assert row["quantity"] is None and row["wholesale_price_net"] is None
    assert row["details"]["packages"] == []
    for value in ["0", "0.5", "bad", None]:
        row = parse("kanellopoulos", changes={"minimum_quantity": value})[0]
        assert sale_quantity("kanellopoulos", row["details"]["sale_quantity"]) is None
    assert sale_quantity("kanellopoulos", "4") == Decimal(4)
    assert sale_quantity("gloria", None) is None
    assert sale_quantity("megapap", None) == 1
    assert parse("anthemidis", changes={"min_order_level": "4"})[0]["details"]["sale_quantity"] is None


def test_gloria_product_id_and_supplier_code_remain_separate():
    row = parse("gloria", changes={"@id": "00987", "code": "ABC-001"})[0]
    assert row["supplier_code"] == row["supplier_sku"] == "ABC-001"
    assert row["details"]["shop_model"] == "GL.00987"
    assert row["details"]["shop_sku"] == "ABC-001"


def test_unrelated_personal_metadata_and_unsafe_images_are_not_retained():
    row = parse("arlight", changes={"AuthorEmail": "fixture@example.test", "AuthorUsername": "fixture-person",
                                   "ImageURL": "https://unapproved.test/fixture.jpg"})[0]
    assert "fixture-person" not in str(row) and "fixture@example.test" not in str(row)
    assert row["image_url"] is None


def test_schema_empty_and_dtd_fail_closed():
    for data in [b"<store/>", b"<products><product/></products>"]:
        with pytest.raises(ValueError):
            parse_profile_catalog(io.BytesIO(data), "printezis")
    with pytest.raises(DefusedXmlException):
        parse_profile_catalog(io.BytesIO(b'<!DOCTYPE products [<!ENTITY x "bad">]><products>&x;</products>'), "printezis")


def test_profile_prefix_cannot_fall_back_to_foreign_bare_sku_or_ean():
    own, foreign = uuid4(), uuid4()
    def item(id, model, sku, ean=None):
        return SimpleNamespace(id=id, model=model, sku=sku, ean=ean, mpn=None, upc=None)
    row = parse("spm")[0]
    index = service.build_catalog_index([item(foreign, "foreign", "001-ABC", row["ean"])])
    assert service.match_supplier_product(row, index, "spm") == (None, "unmatched")
    index = service.build_catalog_index([item(own, "sp.001-ABC", "001-ABC")])
    assert service.match_supplier_product(row, index, "spm") == (own, "profile_identifiers")
    index = service.build_catalog_index([item(own, "sp.001-ABC", "001-ABC"), item(foreign, "foreign", "001-ABC")])
    assert service.match_supplier_product(row, index, "spm") == (None, "ambiguous")


def test_category_bindings_preserve_conflicts_and_profile_versions():
    profiles = category_profiles()
    assert "liberta" not in profiles and "metaxakis" not in profiles
    assert profiles["kanellopoulos"]["profile"] == "KANELLOPOULOS_NEW_30_5_25"
    for adapter, p in profiles.items():
        for label, ids in p["categories"].items():
            result = category_details(adapter, label)
            if label in p["category_conflicts"]:
                assert result["category_mapping_status"] == "ambiguous" and not result["inde_category_ids"]
            else:
                assert result["inde_category_ids"] == ids
    assert category_details("gloria", "unmapped fixture")["inde_category_ids"] == []


def test_anthemidis_auth_is_get_only_and_cannot_leak_via_redirect(monkeypatch):
    url = "https://fixture-user:fixture-password@www.anthemidis.gr/fixture.xml"
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=xml("anthemidis"))
    client = httpx.Client
    monkeypatch.setattr(connector.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    assert len(connector.fetch_supplier_catalog(url, "anthemidis")) == 1
    assert calls[0].method == "GET" and calls[0].headers.get("authorization", "").startswith("Basic ")
    assert "fixture-password" not in str(calls[0].url)
    for location in ["https://anthemidis.gr/other", "https://evil.test/", "http://www.anthemidis.gr/", "https://injected:password@www.anthemidis.gr/next"]:
        calls.clear()
        def redirect(request):
            calls.append(request)
            return httpx.Response(302, headers={"Location": location})
        monkeypatch.setattr(connector.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(redirect), **kw))
        with pytest.raises(ValueError):
            connector.fetch_supplier_catalog(url, "anthemidis")
        assert len(calls) == 1
    with pytest.raises(ValueError):
        connector.validate_feed_url(url, "megapap")


@pytest.mark.parametrize("adapter", FORMATS)
def test_profile_catalog_worker_and_atomic_rollback(db, monkeypatch, adapter):
    from app.core.config import settings
    monkeypatch.setattr(settings, "secret_key", "isolated-profile-test-key")
    own = ProductCatalog(sku="001-ABC", model=FORMATS[adapter]["prefix"] + "001-ABC", name="Shop", price=124, quantity=3)
    db.add(own); db.flush()
    feed = service.save_feed(db, SupplierCatalogFeedInput(code=adapter.upper(), name=adapter, adapter=adapter,
                                                       url="https://" + sorted(FORMATS[adapter]["hosts"])[0] + "/fixture"))
    monkeypatch.setattr(service, "fetch_supplier_catalog", lambda url, adapter: parse(adapter))
    assert service.process_supplier_catalog(db)["matched"] == 1
    db.refresh(own)
    assert own.price == 124 and own.quantity == 3 and own.name == "Shop"
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    service.queue_feed(db, feed.id)
    def fail(url, adapter):
        raise RuntimeError("https://user:private-secret@www.gloria.gr/token")
    monkeypatch.setattr(service, "fetch_supplier_catalog", fail)
    assert service.process_supplier_catalog(db) == {"failed": True}
    assert "private-secret" not in feed.error
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct).where(SupplierCatalogProduct.is_current)) == 1
