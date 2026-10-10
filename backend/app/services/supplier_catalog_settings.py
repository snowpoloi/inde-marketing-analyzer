from decimal import Decimal

from sqlalchemy import select

from app.models import IntegrationSetting, Supplier
from app.schemas.supplier_catalog import SupplierCatalogPricingInput


def pricing_settings(db):
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "supplier_catalog"))
    return (row.config or {}) if row else {}


def save_pricing_settings(db, payload, user):
    suppliers = db.scalars(select(Supplier).where(Supplier.id.in_(payload.piece_supplier_ids))).all()
    if len(suppliers) != len(set(payload.piece_supplier_ids)):
        raise ValueError("Unknown supplier in unit confirmations.")
    row = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "supplier_catalog").with_for_update())
    if row is None:
        row = IntegrationSetting(provider="supplier_catalog", display_name="Supplier catalog")
        db.add(row)
    row.config = {**payload.model_dump(mode="json"), "authorized_by": str(user.id)}
    row.is_enabled = payload.automatic_costs
    db.commit()
    return public_pricing_settings(db)


def public_pricing_settings(db):
    return SupplierCatalogPricingInput.model_validate(pricing_settings(db)).model_dump(mode="json")


def package_metrics(details, divisor):
    packages = []
    for row in details.get("packages", []):
        dimensions = [Decimal(row[key]) if row.get(key) else None for key in ("width_cm", "length_cm", "height_cm")]
        cubic_cm = dimensions[0] * dimensions[1] * dimensions[2] if all(value is not None and value > 0 for value in dimensions) else None
        packages.append({**row, "volume_m3": cubic_cm / Decimal("1000000") if cubic_cm else None,
                         "volumetric_kg": cubic_cm / Decimal(str(divisor)) if cubic_cm else None})
    complete = (bool(packages) and details.get("package_dimensions_complete", True)
                and all(row["volume_m3"] is not None for row in packages))
    declared = details.get("packages_per_item")
    if declared is not None and Decimal(str(declared)) != len(packages):
        complete = False
    return {"packages": packages, "volumetric_divisor": divisor,
            "volume_total_m3": sum(row["volume_m3"] for row in packages) if complete else None,
            "volumetric_total_kg": sum(row["volumetric_kg"] for row in packages) if complete else None}
