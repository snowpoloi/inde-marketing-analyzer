"""Outbound shipping estimates only; never writes orders, invoices or COGS."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
import unicodedata
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models import IntegrationSetting, OpenCartOrder, ProductCatalog, SupplierCatalogFeed, SupplierCatalogProduct
from app.schemas.order_shipping import ShippingEstimateRequest, ShippingSettings
from app.services.supplier_catalog_pricing import sale_quantity

PROVIDER = "order_shipping"
ZERO = Decimal(0)


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def positive(value):
    try:
        value = Decimal(str(value))
        return value if value.is_finite() and 0 < value <= 10000 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def normalize(value):
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return " ".join("".join(c if c.isalnum() else " " for c in text if not unicodedata.combining(c)).split())


def shipping_settings(db):
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == PROVIDER))
    return ShippingSettings.model_validate(row.config) if row and row.is_enabled else None


def public_settings(settings):
    if settings is None:
        return {"configured": False}
    return {"configured": True, **settings.model_dump(mode="json", exclude={
                "mytrans_areas": True, "speedex_areas": True,
                "mytrans": {"destination_rules"}, "speedex": {"destination_rules"}}),
            "mytrans_area_rows": len(settings.mytrans_areas), "speedex_area_rows": len(settings.speedex_areas)}


def save_shipping_settings(db, settings):
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == PROVIDER).with_for_update())
    if row is None:
        row = IntegrationSetting(provider=PROVIDER, display_name="Order shipping")
        db.add(row)
    row.is_enabled = True
    row.config = settings.model_dump(mode="json")
    db.commit()
    return public_settings(settings)


def area_candidates(settings, postcode, locality, carrier="mytrans"):
    postcode = "".join(str(postcode or "").split())
    rows = [row for row in getattr(settings, f"{carrier}_areas") if row.postcode == postcode]
    exact = [row for row in rows if normalize(row.locality) == normalize(locality)]
    return {"rows": [row.model_dump(mode="json") for row in (exact or rows)],
            "exact_locality": bool(exact)}


def destination_zone(tariff, region, locality, postcode):
    def region_key(value):
        key = normalize(value)
        for prefix in ("\u03bd\u03bf\u03bc\u03bf\u03c3 ", "\u03bd\u03bf\u03bc\u03bf\u03c5 ", "\u03bd ", "prefecture of "):
            if key.startswith(prefix):
                return key[len(prefix):]
        return key

    known_postcode_rules = [rule for rule in tariff.destination_rules if postcode in rule.postcodes and rule.regions]
    if known_postcode_rules and not any(region_key(region) in {region_key(value) for value in rule.regions}
                                       for rule in known_postcode_rules):
        return {}
    matches = []
    for rule in tariff.destination_rules:
        if rule.regions and region_key(region) not in {region_key(value) for value in rule.regions}:
            continue
        if rule.localities and normalize(locality) not in {normalize(value) for value in rule.localities}:
            continue
        if rule.postcodes and postcode not in rule.postcodes:
            continue
        specificity = 4 * bool(rule.postcodes) + 2 * bool(rule.localities) + bool(rule.regions)
        matches.append((specificity, rule))
    if not matches:
        return {}
    best = [rule for score, rule in matches if score == max(score for score, _ in matches)]
    zones = {rule.zone_code for rule in best}
    if len(zones) != 1:
        return {}
    basis = " + ".join(label for key, label in (("regions", "region"), ("localities", "city"), ("postcodes", "postcode"))
                       if any(getattr(rule, key) for rule in best))
    values = {"zone_code": next(iter(zones)), "basis": f"Order {basis}"}
    for field in ("local_cod", "remote_extra_net", "cod_allowed"):
        choices = {getattr(rule, field) for rule in best}
        if len(choices) == 1 and None not in choices:
            values[field] = next(iter(choices))
    return values


def area_defaults(candidates, carrier):
    groups = {}
    for row in candidates["rows"]:
        groups.setdefault(normalize(row["locality"]), []).append(row)
    classifications = []
    for rows in groups.values():
        statuses = {row["status"] for row in rows}
        if carrier == "speedex":
            classifications.append({"speedex_remote": statuses == {"remote"}} if len(statuses) == 1 else {})
            continue
        values = {Decimal(str(row["extra_net"])) for row in rows if row["extra_net"] is not None
                  and row["status"] in {"remote", "remote_rate"}}
        extra = next(iter(values)) if len(values) == 1 else ZERO if statuses == {"active"} else None
        if not values and "active" in statuses and "remote" not in statuses and "remote_rate" not in statuses:
            extra = ZERO
        cod = False if "no_cod" in statuses else True if statuses & {"active", "remote", "remote_rate"} else None
        classifications.append({"mytrans_remote_extra": extra, "mytrans_cod_allowed": cod})
    defaults = {}
    for field in ("speedex_remote",) if carrier == "speedex" else ("mytrans_remote_extra", "mytrans_cod_allowed"):
        values = {row.get(field) for row in classifications}
        if len(values) == 1 and None not in values:
            defaults[field] = next(iter(values))
    if "mytrans_remote_extra" in defaults:
        defaults["mytrans_area_confirmed"] = True
    return defaults


def order_cod(order):
    code, method = normalize(order.payment_code), normalize(order.payment_method)
    positive_cod = code in {"cod", "cod cod"} or "cash on delivery" in method or any(
        word.startswith("\u03b1\u03bd\u03c4\u03b9\u03ba\u03b1\u03c4\u03b1\u03b2\u03bf\u03bb") for word in method.split())
    non_cod = code in {"bank transfer", "bank transfer bank transfer", "banktransfer", "cheque", "pp standard", "paypal",
                       "free checkout", "credit card", "card", "iris"} or method in {
                           "bank transfer", "credit card", "debit card", "paypal", "iris",
                           "\u03c4\u03c1\u03b1\u03c0\u03b5\u03b6\u03b9\u03ba\u03b7 \u03ba\u03b1\u03c4\u03b1\u03b8\u03b5\u03c3\u03b7"}
    return None if positive_cod == non_cod else positive_cod


def order_defaults(settings, order):
    defaults, matched = {}, {}
    cod = order_cod(order)
    if cod is not None:
        defaults["cod"] = cod
        matched["cod"] = "Stored order payment method"
    postcode = "".join(str(order.shipping_postcode or "").split())
    if settings is None or len(postcode) != 5 or not postcode.isascii() or not postcode.isdigit() or not greek_destination(order):
        return {"defaults": defaults, "matched_fields": matched}
    for carrier in ("mytrans", "speedex"):
        rule = destination_zone(getattr(settings, carrier), order.shipping_zone, order.shipping_city, postcode)
        fields = {"zone_code": f"{carrier}_zone"}
        if carrier == "mytrans":
            fields.update(local_cod="mytrans_local_cod", remote_extra_net="mytrans_remote_extra", cod_allowed="mytrans_cod_allowed")
        for key, field in fields.items():
            if key in rule:
                defaults[field] = rule[key]
                matched[field] = f"{rule['basis']} / carrier tariff mapping"
        if "mytrans_remote_extra" in defaults:
            defaults["mytrans_area_confirmed"] = True
            matched["mytrans_area_confirmed"] = matched["mytrans_remote_extra"]
        candidates = area_candidates(settings, postcode, order.shipping_city, carrier)
        values = area_defaults(candidates, carrier)
        if carrier == "mytrans" and "mytrans_remote_extra" not in values and any(
                row["status"] in {"remote", "remote_rate"} for row in candidates["rows"]):
            for field in ("mytrans_remote_extra", "mytrans_area_confirmed"):
                defaults.pop(field, None)
                matched.pop(field, None)
        defaults.update(values)
        basis = "City + postcode" if candidates["exact_locality"] else "All localities in this postcode have the same classification"
        source = getattr(settings, f"{carrier}_area_source") or f"{carrier.title()} area list"
        matched.update({field: f"{basis} / {source}" for field in values})
    return {"defaults": defaults, "matched_fields": matched}


def greek_destination(order):
    return normalize(order.shipping_country) in {
        "greece", "gr", "grc", normalize("\u0395\u03bb\u03bb\u03ac\u03b4\u03b1"), normalize("\u0395\u03bb\u03bb\u03ac\u03c2")}


def stored_order(db, order_id):
    order = db.scalar(select(OpenCartOrder).options(selectinload(OpenCartOrder.products))
                      .where(OpenCartOrder.order_id == order_id))
    if order is None:
        raise LookupError("Order not found.")
    return order


def order_manifest(db, order):
    # OpenCart's custom shipping charge is stored alongside physical order lines.
    lines = [line for line in order.products if line.model != "custom_shipping_method" or line.sku]
    ids = {line.product_id for line in lines if line.product_id}
    skus = {line.sku for line in lines if not line.product_id and line.sku}
    models = {line.model for line in lines if not line.product_id and not line.sku and line.model}
    own = db.scalars(select(ProductCatalog).where(or_(ProductCatalog.product_id.in_(ids),
        ProductCatalog.sku.in_(skus), ProductCatalog.model.in_(models)))).all() if lines else []
    suppliers = db.execute(select(SupplierCatalogProduct, SupplierCatalogFeed.adapter)
        .join(SupplierCatalogFeed, SupplierCatalogFeed.id == SupplierCatalogProduct.feed_id)
        .where(SupplierCatalogProduct.product_catalog_id.in_([row.id for row in own]),
               SupplierCatalogProduct.match_method.notin_(["ambiguous", "unmatched"]))).all() if own else []
    parcels, warnings = [], []
    for line in lines:
        matches = [row for row in own if row.product_id == line.product_id] if line.product_id else [
            row for row in own if (row.sku == line.sku if line.sku else bool(line.model) and row.model == line.model)]
        candidates = [(row, adapter) for row, adapter in suppliers
                      if len(matches) == 1 and row.product_catalog_id == matches[0].id]
        current = [(row, adapter) for row, adapter in candidates if row.is_current]
        candidates = current or candidates
        product, adapter = candidates[0] if len(candidates) == 1 else (None, None)
        details = product.details or {} if product else {}
        step = sale_quantity(adapter, details.get("sell_step" if adapter == "pakoworld" else "minimum"))
        supported = adapter in {"megapap", "pakoworld"}
        packages = details.get("packages") or [] if supported else []
        declared = positive(details.get("packages_per_item"))
        complete = (packages and details.get("package_dimensions_complete", True)
                    and (declared is None or declared == len(packages)))
        if not complete:
            warnings.append(f"{line.name}: missing or incomplete supplier parcel dimensions; confirm the actual manifest.")
            count = int(declared) if declared and declared == int(declared) and declared <= 30 else 1
            packages = [{} for _ in range(count)]
        if step is None or step > 1:
            warnings.append(f"{line.name}: verify XML pieces per INDE sale unit and parcel count (sell step {step or 'unknown'}).")
        if product and not product.is_current:
            warnings.append(f"{line.name}: archived XML packaging, last seen {product.last_seen_at.date()}.")
        copies = max(0, line.quantity) * int(step or 1)
        if copies * len(packages) + len(parcels) > 200:
            raise ValueError("More than 200 parcels; calculate this shipment in separate batches.")
        # A product's total gross weight is not split equally between its boxes.
        total_weight = positive(details.get("weight_item") if adapter == "megapap" else details.get("gross_weight"))
        for copy in range(copies):
            for index, package in enumerate(packages):
                parcels.append({"key": f"{line.id}:{copy}:{index}",
                    "label": f"{line.name} / {copy + 1}.{index + 1}",
                    **{key: positive(package.get(key)) for key in ("width_cm", "length_cm", "height_cm")},
                    "weight_kg": positive(package.get("weight_kg")) or (total_weight if len(packages) == 1 else None)})
    return {"parcels": parcels, "warnings": warnings}


def shipping_context(db, order_id):
    order = stored_order(db, order_id)
    settings = shipping_settings(db)
    return {"order_id": order.order_id, "shipping_date": datetime.now(ZoneInfo("Europe/Athens")).date(),
        "origin": "Athens", "destination": {"country": order.shipping_country, "region": order.shipping_zone,
            "city": order.shipping_city, "postcode": order.shipping_postcode},
        "order_shipping": order.shipping, "order_total": order.total, "payment_method": order.payment_method,
        "currency": order.currency_code or "EUR", "settings": public_settings(settings),
        "mytrans_areas": area_candidates(settings, order.shipping_postcode, order.shipping_city) if settings else None,
        **order_defaults(settings, order), **order_manifest(db, order)}


def carrier_estimate(settings, request, carrier):
    tariff = getattr(settings, carrier)
    issues, warnings, charges = [], [], []
    ineligible = False
    zone_code = getattr(request, f"{carrier}_zone")
    zone = next((zone for zone in tariff.zones if zone.code == zone_code), None)
    if zone is None:
        issues.append("Select a verified destination zone.")
    if request.shipping_date < tariff.valid_from or (tariff.valid_to and request.shipping_date > tariff.valid_to):
        issues.append("No applicable tariff for the selected shipping date.")
    if not request.manifest_confirmed:
        issues.append("Confirm all parcels and pieces per sale unit.")
    if request.cod is None:
        issues.append("Confirm whether this shipment has cash on delivery.")

    def add(label, value):
        charges.append({"label": label, "net": money(value)})

    bases = []
    parcel_rows = []
    for parcel in request.parcels:
        dimensions = [parcel.width_cm, parcel.length_cm, parcel.height_cm]
        volume = dimensions[0] * dimensions[1] * dimensions[2] / Decimal(1000000) if all(dimensions) else None
        volumetric = volume * Decimal(1000000) / settings.volumetric_divisor if volume else None
        billable = max(parcel.weight_kg, volumetric) if parcel.weight_kg and volumetric else None
        base = None
        if volume is None:
            issues.append(f"{parcel.label}: missing parcel dimensions.")
        if parcel.weight_kg is None:
            issues.append(f"{parcel.label}: missing actual parcel weight.")
        if carrier == "speedex":
            if tariff.max_side_cm is None and tariff.max_sum_cm is None:
                issues.append("Confirm the Speedex 175 cm dimension rule before calculating.")
            if all(dimensions) and ((tariff.max_side_cm and max(dimensions) > tariff.max_side_cm)
                    or (tariff.max_sum_cm and sum(dimensions) > tariff.max_sum_cm)):
                issues.append(f"{parcel.label}: exceeds Speedex dimension limit; not eligible.")
                ineligible = True
            if billable and zone:
                # Whole started kilos above the band; explicitly labelled as an estimate.
                base = (tariff.base_10kg if billable <= 10 else tariff.base_20kg if billable <= 20
                        else tariff.base_20kg + (billable - 20).to_integral_value(rounding=ROUND_CEILING) * zone.extra_kg)
        elif volume and parcel.weight_kg and zone:
            if volume <= Decimal("0.10") and parcel.weight_kg <= 15:
                base = zone.small_parcel
            elif volume <= Decimal("0.18") and parcel.weight_kg <= 20:
                base = zone.medium_parcel
            elif volume > Decimal("0.18"):
                base = volume * zone.per_m3
            else:
                issues.append(f"{parcel.label}: compact heavy parcel needs a Mytrans quote.")
        if base is not None:
            bases.append(base)
        parcel_rows.append({"key": parcel.key, "volume_m3": volume, "volumetric_kg": volumetric,
                            "billable_kg": billable, "base_net": money(base) if base is not None else None})

    if carrier == "speedex":
        month = request.shipping_date.strftime("%Y-%m")
        fuel = tariff.fuel_percent.get(month)
        if fuel is None:
            issues.append(f"Missing Speedex fuel surcharge for {month}.")
        if request.speedex_remote is None:
            issues.append("Confirm Speedex remote-area classification; Mytrans lists do not apply.")
        if len(bases) == len(request.parcels):
            add("Parcel base charges", sum(bases, ZERO))
            if fuel is not None:
                add(f"Fuel {fuel}% (base service only)", sum((money(base * fuel / 100) for base in bases), ZERO))
            if zone:
                add("Sea surcharge / parcel", zone.sea * len(request.parcels))
        if request.speedex_remote:
            add("Remote / parcel", tariff.remote * len(request.parcels))
        if request.saturday:
            add("Saturday / parcel", tariff.saturday * len(request.parcels))
        if request.timed:
            add("Timed service / parcel", tariff.timed * len(request.parcels))
        if request.cod:
            if request.speedex_cod_parcels is None:
                issues.append("Confirm how many parcels carry a COD collection.")
            else:
                add("COD parcels", tariff.cod_local * request.speedex_cod_parcels)
        warnings.append("Standard domestic service, not express air. Started kilos above 20 are rounded up; verify final carrier billing and parcel acceptance.")
    else:
        if len(bases) == len(request.parcels) and zone:
            add("Parcel charges / shipment minimum", max(zone.minimum, sum(bases, ZERO)))
        add("Waybill / shipment", tariff.waybill)
        if not request.mytrans_area_confirmed or request.mytrans_remote_extra is None:
            issues.append("Confirm locality and the additional Mytrans remote charge (0 for a verified active area).")
        else:
            add("Remote surcharge / shipment", request.mytrans_remote_extra)
        if request.cod:
            if request.mytrans_cod_allowed is not True:
                issues.append("Mytrans COD unavailable or destination eligibility not confirmed.")
            if request.mytrans_local_cod is None:
                issues.append("Confirm Attica / Thessaloniki COD zone.")
            elif request.mytrans_local_cod:
                add("COD", tariff.cod_local)
            elif request.cod_amount is None:
                issues.append("Enter the amount to collect for COD.")
            else:
                add("COD", max(tariff.cod_minimum, request.cod_amount * tariff.cod_percent / 100))
        warnings.append("Curbside delivery from Athens. Parcel charges are summed before the shipment minimum; verify mixed-parcel and heavy-item acceptance with Mytrans.")
    total = sum((row["net"] for row in charges), ZERO) if not issues else None
    vat = money(total * settings.vat_percent / 100) if total is not None else None
    return {"carrier": carrier, "tariff_version": tariff.version,
        "status": "not_eligible" if ineligible else "needs_confirmation" if issues else "estimate",
        "issues": list(dict.fromkeys(issues)), "warnings": warnings, "parcels": parcel_rows, "charges": charges,
        "net": total, "vat": vat, "gross": total + vat if total is not None else None,
        "shipping_balance_net": money(request.customer_shipping_net - total)
            if total is not None and request.customer_shipping_net is not None else None}


def estimate_order_shipping(db, order_id, request: ShippingEstimateRequest):
    order = stored_order(db, order_id)
    settings = shipping_settings(db)
    if settings is None:
        raise ValueError("Shipping tariffs have not been configured.")
    if not greek_destination(order):
        raise ValueError("These tariffs require a confirmed destination in Greece.")
    if order.currency_code and order.currency_code != "EUR":
        raise ValueError("These tariffs apply to EUR orders only.")
    localities = area_candidates(settings, order.shipping_postcode, order.shipping_city)
    mytrans_request = request
    if request.cod and localities["exact_locality"] and any(row["status"] == "no_cod" for row in localities["rows"]):
        mytrans_request = request.model_copy(update={"mytrans_cod_allowed": False})
    return {"order_id": order.order_id, "shipping_date": request.shipping_date, "origin": settings.origin,
        "kind": "estimate_not_actual_expense", "carriers": [carrier_estimate(settings, request, name)
            if name == "speedex" else carrier_estimate(settings, mytrans_request, name)
            for name in ("mytrans", "speedex")]}
