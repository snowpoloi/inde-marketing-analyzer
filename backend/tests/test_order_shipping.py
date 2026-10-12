from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.api.routes.orders import router
from app.db.session import get_db
from app.models import IntegrationSetting, OpenCartOrder, OpenCartOrderProduct, ProductCatalog, SupplierCatalogFeed, SupplierCatalogProduct
from app.schemas.order_shipping import ShippingEstimateRequest, ShippingSettings
from app.services.order_shipping import (area_candidates, carrier_estimate, estimate_order_shipping,
                                        destination_zone, order_defaults, order_manifest, public_settings,
                                        save_shipping_settings, shipping_context)


def rates():
    # Synthetic prices: private customer contracts are not test fixtures.
    return ShippingSettings.model_validate({"vat_percent": 24,
        "mytrans": {"version": "Test freight", "valid_from": "2026-06-01", "valid_to": "2027-05-31",
            "waybill": ".20", "small_pickup": 5, "cod_local": 2, "cod_minimum": 3, "cod_percent": ".6",
            "zones": [{"code": "zone", "label": "Test freight zone", "minimum": 10,
                       "small_parcel": 3, "medium_parcel": 7, "per_m3": 40}]},
        "speedex": {"version": "Test courier", "valid_from": "2026-10-12", "base_10kg": 4,
            "base_20kg": 6, "cod_local": 1, "remote": 3, "saturday": 2, "timed": 1,
            "max_side_cm": 175, "fuel_percent": {"2026-10": 10},
            "zones": [{"code": "zone", "label": "Test courier zone", "extra_kg": 2, "sea": ".40"}]}})


def request(**patch):
    return ShippingEstimateRequest.model_validate({"shipping_date": "2026-10-12", "manifest_confirmed": True,
        "parcels": [{"key": "1", "label": "Box one", "width_cm": 10, "length_cm": 10,
                     "height_cm": 10, "weight_kg": 6}], "mytrans_zone": "zone", "speedex_zone": "zone",
        "mytrans_area_confirmed": True, "mytrans_remote_extra": 0, "small_pickup": False,
        "speedex_remote": False, "cod": False, **patch})


def test_speedex_separate_base_and_sea_charge_for_every_parcel():
    value = request(parcels=request().model_dump()["parcels"] + [
        {"key": "2", "label": "Box two", "width_cm": 10, "length_cm": 10, "height_cm": 10, "weight_kg": 6}])
    result = carrier_estimate(rates(), value, "speedex")
    assert [row["base_net"] for row in result["parcels"]] == [Decimal(4), Decimal(4)]
    assert result["net"] == Decimal("9.60")  # 8 base + .8 fuel + .8 sea
    assert result["vat"] == Decimal("2.30") and result["gross"] == Decimal("11.90")


def test_speedex_uses_larger_actual_or_volumetric_weight_per_parcel():
    value = request(parcels=[{"key": "1", "label": "Box", "width_cm": 50, "length_cm": 40,
                             "height_cm": 30, "weight_kg": 3}])
    result = carrier_estimate(rates(), value, "speedex")
    assert result["parcels"][0]["volume_m3"] == Decimal(".06")
    assert result["parcels"][0]["billable_kg"] == Decimal(12)
    assert result["parcels"][0]["base_net"] == Decimal(6)


@pytest.mark.parametrize("length,eligible", [(175, True), (175.01, False), (176, False)])
def test_speedex_175_limit_is_longest_side_not_dimension_sum(length, eligible):
    value = request(parcels=[{"key": "1", "label": "Box", "width_cm": 50, "length_cm": length,
                             "height_cm": 50, "weight_kg": 10}])
    result = carrier_estimate(rates(), value, "speedex")
    assert (result["gross"] is not None) is eligible
    if not eligible:
        assert result["status"] == "not_eligible"
        assert any("not eligible" in issue for issue in result["issues"])


def test_mytrans_minimum_once_remote_is_additional_without_pickup_charge():
    value = request(parcels=request().model_dump()["parcels"] + [
        {"key": "2", "label": "Box two", "width_cm": 10, "length_cm": 10, "height_cm": 10, "weight_kg": 6}],
        mytrans_remote_extra=18)
    result = carrier_estimate(rates(), value, "mytrans")
    assert result["net"] == Decimal("28.20")  # max(3+3,10) + .2 + 18; owner-confirmed no small-pickup fee
    assert not any("Pickup" in row["label"] for row in result["charges"])


def test_pickup_is_always_no_including_requests_that_omit_the_field():
    payload = request().model_dump()
    payload.pop("small_pickup")
    value = ShippingEstimateRequest.model_validate(payload)
    assert value.small_pickup is False
    assert carrier_estimate(rates(), value, "mytrans")["net"] == Decimal("10.20")


def test_mytrans_uses_volume_for_large_parcels_not_courier_divisor():
    value = request(parcels=[{"key": "1", "label": "Box", "width_cm": 100, "length_cm": 100,
                             "height_cm": 100, "weight_kg": 50}])
    assert carrier_estimate(rates(), value, "mytrans")["net"] == Decimal("40.20")


def test_mytrans_compact_heavy_parcel_requires_quote():
    value = request(parcels=[{"key": "1", "label": "Box", "width_cm": 10, "length_cm": 10,
                             "height_cm": 10, "weight_kg": 21}])
    assert carrier_estimate(rates(), value, "mytrans")["net"] is None


@pytest.mark.parametrize("height,weight,base", [(10, 15, 3), (10, 16, 7), (18, 20, 7), (18.01, 20, "7.204")])
def test_mytrans_exact_volume_and_weight_boundaries(height, weight, base):
    value = request(parcels=[{"key": "1", "label": "Box", "width_cm": 100, "length_cm": 100,
                             "height_cm": height, "weight_kg": weight}])
    assert carrier_estimate(rates(), value, "mytrans")["parcels"][0]["base_net"] == Decimal(str(base)).quantize(Decimal(".01"))


@pytest.mark.parametrize("patch", [{"manifest_confirmed": False}, {"cod": None}, {"speedex_zone": "unknown"},
    {"speedex_remote": None}, {"shipping_date": "2026-09-01"}, {"shipping_date": "2026-11-01"}])
def test_speedex_missing_confirmations_dates_or_monthly_fuel_never_become_zero(patch):
    result = carrier_estimate(rates(), request(**patch), "speedex")
    assert result["issues"] and result["net"] is None and result["gross"] is None


def test_missing_weight_or_dimension_blocks_both_carriers():
    for field in ("weight_kg", "width_cm"):
        parcel = request().model_dump()["parcels"][0]
        parcel[field] = None
        for carrier in ("mytrans", "speedex"):
            assert carrier_estimate(rates(), request(parcels=[parcel]), carrier)["gross"] is None


def test_cod_is_not_applied_to_all_speedex_parcels_unless_confirmed():
    value = request(cod=True, mytrans_cod_allowed=True, mytrans_local_cod=False, cod_amount=1000,
                    speedex_cod_parcels=1)
    assert carrier_estimate(rates(), value, "mytrans")["net"] == Decimal("16.20")
    assert carrier_estimate(rates(), value, "speedex")["net"] == Decimal("5.80")
    assert carrier_estimate(rates(), request(cod=True), "speedex")["net"] is None
    assert carrier_estimate(rates(), request(cod=True, mytrans_cod_allowed=False), "mytrans")["net"] is None


def test_customer_shipping_comparison_only_when_net_amount_confirmed():
    assert carrier_estimate(rates(), request(), "speedex")["shipping_balance_net"] is None
    assert carrier_estimate(rates(), request(customer_shipping_net=0), "speedex")["shipping_balance_net"] == Decimal("-4.80")


def test_same_postcode_different_localities_preserves_different_remote_rates():
    settings = rates().model_dump()
    settings["mytrans_areas"] = [
        {"postcode": "85200", "locality": "Place A", "status": "active"},
        {"postcode": "85200", "locality": "Place B", "status": "remote", "extra_net": 18},
        {"postcode": "85200", "locality": "Place C", "status": "remote_rate", "extra_net": 23}]
    settings = ShippingSettings.model_validate(settings)
    assert len(area_candidates(settings, "852 00", "Unknown")["rows"]) == 3
    exact = area_candidates(settings, "85200", "PLACE C")
    assert exact["exact_locality"] and exact["rows"][0]["extra_net"] == "23"


@pytest.mark.parametrize("patch", [{"parcels": []}, {"parcels": request().model_dump()["parcels"] * 2},
    {"cod_amount": "NaN"}, {"cod_amount": -1}, {"speedex_cod_parcels": 2}, {"small_pickup": True}, {"small_pickup": None}])
def test_invalid_request_is_rejected(patch):
    with pytest.raises(ValidationError):
        request(**patch)


def seed_order(db, *, step="1", boxes=2, country="Greece"):
    own = ProductCatalog(sku="SHIP-SKU", product_id="123", name="Product")
    feed = SupplierCatalogFeed(code="SHIP", name="Test", adapter="pakoworld", encrypted_url="not-a-real-url")
    db.add_all([own, feed]); db.flush()
    supplier = SupplierCatalogProduct(feed_id=feed.id, supplier_code="SUPPLIER-SHIP", name="Product",
        product_catalog_id=own.id, match_method="sku", last_seen_at=datetime.now(timezone.utc),
        details={"sell_step": step, "gross_weight": "30", "packages_per_item": str(boxes),
                 "packages": [{"width_cm": "10", "length_cm": "20", "height_cm": "30"} for _ in range(boxes)]})
    order = OpenCartOrder(order_id=f"shipping-{uuid4()}", date_added=datetime.now(timezone.utc), shipping_country=country,
                          shipping_city="City", shipping_postcode="11111", shipping=Decimal(12), currency_code="EUR")
    order.products.append(OpenCartOrderProduct(product_id="123", sku="SHIP-SKU", name="Product", quantity=2))
    db.add_all([supplier, order]); db.flush()
    return order, supplier


def test_manifest_resolves_stored_identity_and_does_not_split_total_weight(db):
    order, _ = seed_order(db)
    result = order_manifest(db, order)
    assert len(result["parcels"]) == 4
    assert all(row["weight_kg"] is None for row in result["parcels"])


def test_manifest_excludes_explicit_shipping_charge_but_not_products_with_similar_names(db):
    order, _ = seed_order(db)
    order.products.append(OpenCartOrderProduct(model="custom_shipping_method", name="Shipping charge", quantity=1))
    db.flush()
    result = order_manifest(db, order)
    assert len(result["parcels"]) == 4 and not result["warnings"]
    order.products.append(OpenCartOrderProduct(model="REAL-PRODUCT", name="Shipping charge", quantity=1))
    db.flush()
    assert len(order_manifest(db, order)["parcels"]) == 5


def test_manifest_sale_step_is_not_the_box_count_and_requires_confirmation(db):
    order, _ = seed_order(db, step="4", boxes=2)
    result = order_manifest(db, order)
    assert len(result["parcels"]) == 4  # Unknown packing: placeholders, not 16 invented cartons.
    assert all(row["width_cm"] is None and row["weight_kg"] is None for row in result["parcels"])
    assert any("sell step 4" in warning for warning in result["warnings"])


@pytest.mark.parametrize("quantity", [1, 2, 4])
def test_manifest_pakoworld_four_chairs_per_carton_is_one_box_per_inde_set(db, quantity):
    order, supplier = seed_order(db, step="4", boxes=1)
    order.products[0].quantity = quantity
    supplier.details = {**supplier.details, "gross_weight": "3.875", "attributes": [
        {"id": "2", "value": "Boxes: 1.000"}, {"id": "11", "value": "Pieces per carton: 4"}],
        "packages": [{"length_cm": "78", "width_cm": "43", "height_cm": "26"}]}
    db.flush()
    original = dict(supplier.details)
    result = order_manifest(db, order)
    assert len(result["parcels"]) == quantity
    assert all(row["weight_kg"] == Decimal("15.5") for row in result["parcels"])
    assert all(row["width_cm"] == 43 and row["length_cm"] == 78 and row["height_cm"] == 26
               for row in result["parcels"])
    assert supplier.details == original and "pieces_per_package" not in supplier.details
    assert not db.dirty
    value = request(parcels=result["parcels"])
    quote = carrier_estimate(rates(), value, "speedex")
    assert len(quote["parcels"]) == quantity
    assert all(row["billable_kg"] == Decimal("17.4408") for row in quote["parcels"])


def test_manifest_pakoworld_keeps_distinct_boxes_for_each_physical_item(db):
    order, supplier = seed_order(db, step="2", boxes=2)
    supplier.details = {**supplier.details, "attributes": [{"id": "11", "value": "Pieces per carton: 1"}],
        "packages": [{"length_cm": "47", "width_cm": "188", "height_cm": "10"},
                     {"length_cm": "49", "width_cm": "131", "height_cm": "15"}]}
    result = order_manifest(db, order)
    assert len(result["parcels"]) == 8
    assert [row["length_cm"] for row in result["parcels"]] == [Decimal(47), Decimal(49)] * 4
    assert all(row["weight_kg"] is None for row in result["parcels"])


@pytest.mark.parametrize("pieces,boxes", [("invalid", 1), ("0", 1), ("1.5", 1), ("4", 2)])
def test_manifest_ambiguous_carton_contents_require_manual_parcels(db, pieces, boxes):
    order, supplier = seed_order(db, step="4", boxes=boxes)
    supplier.details = {**supplier.details, "attributes": [{"id": "11", "value": pieces}]}
    result = order_manifest(db, order)
    assert all(row["width_cm"] is None and row["weight_kg"] is None for row in result["parcels"])
    assert any("actual parcels" in warning for warning in result["warnings"])
    assert carrier_estimate(rates(), request(parcels=result["parcels"]), "speedex")["gross"] is None


def test_manifest_partial_carton_keeps_full_outer_dimensions_but_not_full_weight(db):
    order, supplier = seed_order(db, step="3", boxes=1)
    supplier.details = {**supplier.details, "attributes": [{"id": "11", "value": "4"}]}
    result = order_manifest(db, order)
    assert len(result["parcels"]) == 2  # Six pieces: one full carton, one needing confirmation.
    assert result["parcels"][0]["weight_kg"] == 120
    assert result["parcels"][1]["weight_kg"] is None
    assert any("last carton" in warning for warning in result["warnings"])


def test_manifest_megapap_minimum_and_multibox_packaging_remain_separate(db):
    order, supplier = seed_order(db, boxes=3)
    feed = db.get(SupplierCatalogFeed, supplier.feed_id)
    feed.adapter = "megapap"
    supplier.details = {**supplier.details, "minimum": "2", "weight_item": "40"}
    db.flush()
    result = order_manifest(db, order)
    assert len(result["parcels"]) == 12
    assert all(row["weight_kg"] is None for row in result["parcels"])


def test_manifest_single_box_can_use_total_gross_weight(db):
    order, _ = seed_order(db, boxes=1)
    assert all(row["weight_kg"] == 30 for row in order_manifest(db, order)["parcels"])


def test_manifest_no_fuzzy_names_or_fallback_from_wrong_explicit_id(db):
    order, _ = seed_order(db, boxes=1)
    order.products[0].product_id = "different"
    db.flush()
    result = order_manifest(db, order)
    assert all(row["width_cm"] is None for row in result["parcels"])


def test_manifest_can_use_archived_confirmed_mapping(db):
    order, supplier = seed_order(db, boxes=1)
    supplier.is_current = False; db.flush()
    result = order_manifest(db, order)
    assert result["parcels"][0]["width_cm"] == 10 and any("archived" in item for item in result["warnings"])


def test_calculation_does_not_change_order_or_import_financial_data(db):
    order, _ = seed_order(db)
    save_shipping_settings(db, rates())
    original = (order.shipping, order.total, dict(order.raw))
    result = estimate_order_shipping(db, order.order_id, request())
    assert result["kind"] == "estimate_not_actual_expense"
    assert (order.shipping, order.total, order.raw) == original
    assert not db.new and not db.dirty and not db.deleted


def test_known_mytrans_no_cod_locality_cannot_be_overridden_but_speedex_is_independent(db):
    order, _ = seed_order(db)
    settings = rates().model_dump()
    settings["mytrans_areas"] = [{"postcode": "11111", "locality": "City", "status": "no_cod"}]
    save_shipping_settings(db, ShippingSettings.model_validate(settings))
    value = request(cod=True, mytrans_cod_allowed=True, mytrans_local_cod=True, speedex_cod_parcels=1)
    result = estimate_order_shipping(db, order.order_id, value)
    assert result["carriers"][0]["gross"] is None
    assert result["carriers"][1]["gross"] is not None


def test_disabled_tariffs_context_and_calculation_do_not_enable_them(db):
    order, _ = seed_order(db)
    assert shipping_context(db, order.order_id)["settings"] == {"configured": False}
    with pytest.raises(ValueError, match="not been configured"):
        estimate_order_shipping(db, order.order_id, request())
    assert not db.new and not db.dirty


def test_api_admin_validation_private_settings_and_missing_orders(db):
    order, _ = seed_order(db)
    app = FastAPI(); app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
    with TestClient(app) as client:
        assert client.put("/api/orders/shipping/settings", json=rates().model_dump(mode="json")).status_code == 200
        settings = client.get("/api/orders/shipping/settings").json()["data"]
        assert settings["configured"] and "mytrans_areas" not in settings
        assert client.get(f"/api/orders/detail/{order.order_id}/shipping").status_code == 200
        url = f"/api/orders/detail/{order.order_id}/shipping"
        assert client.post(url, json=request().model_dump(mode="json")).status_code == 200
        assert client.post(url, json=request().model_dump(mode="json") | {"parcels": []}).status_code == 422
        assert client.get("/api/orders/detail/not-existing/shipping").status_code == 404
        order.shipping_country = "Italy"; db.flush()
        assert client.post(url, json=request().model_dump(mode="json")).status_code == 422
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
        for method, path in ((client.get, url), (client.post, url),
                             (client.get, "/api/orders/shipping/settings"), (client.put, "/api/orders/shipping/settings")):
            kwargs = {"json": request().model_dump(mode="json")} if method == client.post else {
                "json": rates().model_dump(mode="json")} if method == client.put else {}
            assert method(path, **kwargs).status_code == 403


def destination_rates(**patch):
    settings = rates().model_dump()
    for carrier in ("mytrans", "speedex"):
        settings[carrier]["destination_rules"] = [{"zone_code": "zone", "regions": ["Region"]}]
    settings["mytrans_areas"] = [{"postcode": "11111", "locality": "City", "status": "active"}]
    settings["speedex_areas"] = [{"postcode": "11111", "locality": "City", "status": "remote"}]
    settings.update(patch)
    return ShippingSettings.model_validate(settings)


def address_order(**patch):
    return SimpleNamespace(**{"shipping_country": "Greece", "shipping_zone": "Region", "shipping_city": "City",
                              "shipping_postcode": "11111", "payment_code": "bank_transfer",
                              "payment_method": "Bank transfer", **patch})


def test_order_destination_prefills_each_carrier_independently_with_provenance():
    result = order_defaults(destination_rates(), address_order(shipping_postcode="111 11"))
    assert result["defaults"] == {"cod": False, "mytrans_zone": "zone", "speedex_zone": "zone",
        "mytrans_remote_extra": Decimal(0), "mytrans_area_confirmed": True,
        "mytrans_cod_allowed": True, "speedex_remote": True}
    assert all(field in result["matched_fields"] for field in result["defaults"])


def test_area_name_normalization_preserves_locality_identity():
    settings = destination_rates(mytrans_areas=[
        {"postcode": "11111", "locality": "Cit\u00fd - North", "status": "remote_rate", "extra_net": 18},
        {"postcode": "11111", "locality": "Other", "status": "remote_rate", "extra_net": 23}])
    values = order_defaults(settings, address_order(shipping_city="CITY NORTH"))["defaults"]
    assert values["mytrans_remote_extra"] == 18 and values["mytrans_area_confirmed"]


def test_ambiguous_postcode_leaves_surcharge_and_confirmation_unresolved():
    settings = destination_rates(mytrans_areas=[
        {"postcode": "11111", "locality": "City", "status": "active"},
        {"postcode": "11111", "locality": "Island", "status": "remote_rate", "extra_net": 23}])
    values = order_defaults(settings, address_order(shipping_city="Unknown"))["defaults"]
    assert "mytrans_remote_extra" not in values and "mytrans_area_confirmed" not in values


def test_unambiguous_postcode_does_not_require_exact_city_spelling():
    settings = destination_rates(mytrans_areas=[
        {"postcode": "11111", "locality": "A", "status": "remote_rate", "extra_net": 18},
        {"postcode": "11111", "locality": "B", "status": "remote_rate", "extra_net": 18}])
    result = order_defaults(settings, address_order(shipping_city="Unknown"))
    assert result["defaults"]["mytrans_remote_extra"] == 18
    assert "All localities" in result["matched_fields"]["mytrans_remote_extra"]


def test_speedex_mixed_remote_classification_is_not_assumed_active():
    settings = destination_rates(speedex_areas=[
        {"postcode": "11111", "locality": "City", "status": "active"},
        {"postcode": "11111", "locality": "Village", "status": "remote"}])
    assert "speedex_remote" not in order_defaults(settings, address_order(shipping_city="Unknown"))["defaults"]
    assert order_defaults(settings, address_order())["defaults"]["speedex_remote"] is False


def test_unknown_postcode_does_not_invent_free_remote_or_cod_eligibility():
    values = order_defaults(destination_rates(), address_order(shipping_postcode="99999"))["defaults"]
    assert "speedex_remote" not in values and "mytrans_remote_extra" not in values and "mytrans_cod_allowed" not in values


def test_no_cod_list_overrides_active_area_and_is_not_applied_to_speedex():
    settings = destination_rates(mytrans_areas=[
        {"postcode": "11111", "locality": "City", "status": "active"},
        {"postcode": "11111", "locality": "City", "status": "no_cod"}])
    values = order_defaults(settings, address_order())["defaults"]
    assert values["mytrans_cod_allowed"] is False and values["mytrans_remote_extra"] == 0
    assert values["speedex_remote"] is True


def test_partial_postcode_no_cod_match_is_not_assumed_for_all_localities():
    settings = destination_rates(mytrans_areas=[
        {"postcode": "11111", "locality": "City", "status": "active"},
        {"postcode": "11111", "locality": "Village", "status": "active"},
        {"postcode": "11111", "locality": "Village", "status": "no_cod"}])
    values = order_defaults(settings, address_order(shipping_city="Unknown"))["defaults"]
    assert "mytrans_cod_allowed" not in values and values["mytrans_remote_extra"] == 0


def test_remote_list_without_price_blocks_city_rule_zero_surcharge():
    settings = destination_rates().model_dump()
    settings["mytrans"]["destination_rules"][0].update(remote_extra_net=0, cod_allowed=True, local_cod=True)
    settings["mytrans_areas"] = [{"postcode": "11111", "locality": "City", "status": "remote"}]
    values = order_defaults(ShippingSettings.model_validate(settings), address_order())["defaults"]
    assert "mytrans_remote_extra" not in values and "mytrans_area_confirmed" not in values


def test_city_tariff_rule_can_cover_postcode_absent_from_remote_workbook():
    settings = destination_rates(mytrans_areas=[]).model_dump()
    settings["mytrans"]["destination_rules"][0].update(postcodes=["11111"], remote_extra_net=0, cod_allowed=True, local_cod=True)
    values = order_defaults(ShippingSettings.model_validate(settings), address_order())["defaults"]
    assert values["mytrans_remote_extra"] == 0 and values["mytrans_area_confirmed"] and values["mytrans_local_cod"]


def test_postcode_rule_overrides_prefecture_only_without_dependence_on_rule_order():
    settings = destination_rates().model_dump()
    settings["speedex"]["zones"].append({"code": "island", "label": "Island", "extra_kg": 3})
    settings["speedex"]["destination_rules"].append({"zone_code": "island", "regions": ["Region"], "postcodes": ["11111"]})
    tariff = ShippingSettings.model_validate(settings).speedex
    assert destination_zone(tariff, "REGION", "City", "11111")["zone_code"] == "island"
    assert destination_zone(tariff, "Prefecture of Region", "City", "11111")["zone_code"] == "island"
    assert destination_zone(tariff, "Different region", "City", "11111") == {}


def test_conflicting_equally_specific_rules_require_manual_zone():
    settings = destination_rates().model_dump()
    settings["mytrans"]["zones"].append({**settings["mytrans"]["zones"][0], "code": "other"})
    settings["mytrans"]["destination_rules"].append({"zone_code": "other", "regions": ["Region"]})
    values = order_defaults(ShippingSettings.model_validate(settings), address_order())["defaults"]
    assert "mytrans_zone" not in values


def test_known_postcode_conflicting_with_order_prefecture_does_not_use_broad_region_rule():
    settings = destination_rates().model_dump()
    settings["speedex"]["destination_rules"].append({"zone_code": "zone", "regions": ["Different region"], "postcodes": ["11111"]})
    values = order_defaults(ShippingSettings.model_validate(settings), address_order())["defaults"]
    assert "speedex_zone" not in values


@pytest.mark.parametrize("patch", [{"shipping_country": "Italy"}, {"shipping_country": None},
                                  {"shipping_postcode": "1111"}, {"shipping_postcode": "bad"}])
def test_unknown_country_or_invalid_postcode_never_gets_domestic_defaults(patch):
    assert order_defaults(destination_rates(), address_order(**patch))["defaults"] == {"cod": False}


@pytest.mark.parametrize("code,method,expected", [("cod", "", True), ("cod.cod", None, True),
    ("bank_transfer", "Bank transfer", False), ("unknown", "Cash on delivery", True),
    (None, "\u0391\u03bd\u03c4\u03b9\u03ba\u03b1\u03c4\u03b1\u03b2\u03bf\u03bb\u03ae", True),
    ("bank_transfer", "Cash on delivery", None), (None, "Unknown payment", None)])
def test_payment_defaults_only_recognize_known_nonconflicting_methods(code, method, expected):
    values = order_defaults(destination_rates(), address_order(payment_code=code, payment_method=method))["defaults"]
    assert values.get("cod") is expected
    if expected is None:
        assert "cod" not in values


@pytest.mark.parametrize("rule", [{"zone_code": "missing", "regions": ["Region"]},
    {"zone_code": "zone"}, {"zone_code": "zone", "postcodes": ["123"]}, {"zone_code": "zone", "localities": [""]}])
def test_invalid_destination_rules_are_rejected(rule):
    settings = rates().model_dump()
    settings["mytrans"]["destination_rules"] = [rule]
    with pytest.raises(ValidationError):
        ShippingSettings.model_validate(settings)


def test_carrier_address_datasets_and_rules_are_not_leaked_in_settings_summary():
    settings = public_settings(destination_rates())
    assert "mytrans_areas" not in settings and "speedex_areas" not in settings
    assert "destination_rules" not in settings["mytrans"] and "destination_rules" not in settings["speedex"]
    assert settings["speedex_area_rows"] == 1


def test_reading_order_defaults_does_not_change_stored_address_or_payment(db):
    order, _ = seed_order(db)
    order.shipping_zone = "Region"
    order.payment_code = "cod"
    save_shipping_settings(db, destination_rates())
    original = (order.shipping_zone, order.shipping_city, order.shipping_postcode, order.payment_code)
    result = shipping_context(db, order.order_id)
    assert result["defaults"]["cod"] is True and result["defaults"]["mytrans_zone"] == "zone"
    assert original == (order.shipping_zone, order.shipping_city, order.shipping_postcode, order.payment_code)
    assert not db.dirty and not db.new
