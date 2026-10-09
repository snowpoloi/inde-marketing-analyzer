"""Read-only adapters for the schemas audited with the owner's live profiles."""

import html
import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from defusedxml import ElementTree

from app.connectors.supplier_formats import FORMATS, SOURCE_FIELDS


class ParsedCatalog(list):
    def __init__(self):
        super().__init__()
        self.diagnostics = {"ignored_non_product_rows": 0, "merged_category_rows": 0, "unnamed_products": 0}


@lru_cache(maxsize=1)
def category_profiles():
    return json.loads(Path(__file__).with_name("supplier_category_profiles.json").read_text(encoding="utf-8"))


def category_key(value):
    return re.sub(r"\s*([>|])\s*", r"\1", html.unescape(value or "")).strip()


def category_details(adapter, value):
    profile = category_profiles()[adapter]
    transformed = value or ""
    for operation in profile["category_transforms"]:
        operand = html.unescape(operation["value"])
        if operation["op"] == "prepend":
            transformed = operand + transformed
        elif operation["op"] == "remove":
            transformed = transformed.replace(operand, "")
        elif operation["op"] == "replace":
            transformed = transformed.replace(operand, html.unescape(operation["replacement"]))
    keys = [category_key(transformed), category_key(value)]
    options = [profile["categories"][key] for key in dict.fromkeys(keys) if key in profile["categories"]]
    ambiguous = any(key in profile["category_conflicts"] for key in keys) or (bool(options) and any(option != options[0] for option in options))
    # Conflicting original/transformed bindings require review, not their union.
    ids = options[0] if options and not ambiguous else []
    return {"source_categories": [value] if value else [], "inde_category_ids": ids,
            "category_mapping_status": "ambiguous" if ambiguous else "mapped" if ids else "unmapped",
            "profile": profile["profile"]}


def parse_profile_catalog(source, adapter):
    from app.connectors.supplier_catalog import MAX_PRODUCTS, _media_url, _number

    spec = FORMATS[adapter]
    products, seen, stack = ParsedCatalog(), {}, []
    records = 0
    for event, node in ElementTree.iterparse(source, events=("start", "end"), forbid_dtd=True):
        if event == "start":
            stack.append(node)
            if len(stack) == 1 and node.tag != spec["root"]:
                raise ValueError("This XML does not match the selected supplier format.")
            continue
        if tuple(element.tag for element in stack) != spec["path"]:
            stack.pop()
            continue
        records += 1
        if records > MAX_PRODUCTS * 2:
            raise ValueError("Supplier XML exceeds the record limit.")

        def text(field, limit=1000):
            if not field:
                return None
            value = node.get(field[1:]) if field.startswith("@") else node.findtext(field)
            return (value or "").strip()[:limit] or None

        code, sku = text(spec["code"], 256), text(spec["sku"], 256)
        name = text(spec["name"], 500)
        skip = (adapter == "anthemidis" and (code == "product_sku" or (not name and not any(
            _number(text(field)) is not None for field in ("Web_price", "pricewithouttax", "product_in_stock"))))) or (
            adapter == "arlight" and not code and name in {"Offer", "Credit"})
        if skip:
            products.diagnostics["ignored_non_product_rows"] += 1
        if not skip:
            if not code or not sku or len(code) > 255 or len(sku) > 255:
                raise ValueError("A supplier product is missing a valid code, SKU or name.")
            raw_model = text(spec.get("model", spec["sku"]), 256)
            if not raw_model or len(spec["prefix"] + raw_model) > 255:
                raise ValueError("A supplier product is missing a valid shop model.")
            category = text(category_profiles()[adapter]["category_field"])
            quantity = _number(text(spec["stock"]))
            step = _number(text(spec.get("step"))) if spec.get("step") else "1"
            if adapter == "anthemidis":
                step = "1" if text("min_order_level") in (None, "", "1", "1.0") else None
            if adapter == "gloria" and node.find("./set/product_code") is not None:
                step = None
            details = {
                **category_details(adapter, category), "shop_model": spec["prefix"] + raw_model,
                "shop_sku": sku, "sale_quantity": step,
                "missing_name": not bool(name),
                "description": text(spec["description"], 50000),
                "availability": text("availability") or text("Availability") or text("StockStatus") or text("ProductAvailability"),
                "source_fields": {field: text(field, 2000) for field in SOURCE_FIELDS[adapter]},
                "packages": [], "filters": [],
            }
            row = {"supplier_code": code, "supplier_sku": sku, "ean": text(spec["ean"], 64),
                "name": name or code, "category": category, "image_url": _media_url(text(spec["image"], 2000), spec["hosts"]),
                "quantity": int(Decimal(quantity)) if quantity is not None and Decimal(quantity) == Decimal(quantity).to_integral_value() else None,
                "wholesale_price_net": _number(text(spec.get("wholesale"))),
                "retail_price_gross": _number(text(spec["retail"])), "details": details}
            key = code.casefold()
            if key in seen:
                previous = seen[key]
                # Daisat repeats products per category. Only identical product
                # data can merge memberships; never sum stock or prices.
                def economic(value):
                    return {**{k: v for k, v in value.items() if k not in {"category", "details"}},
                        "details": {k: v for k, v in value["details"].items() if k not in {
                            "source_categories", "inde_category_ids", "category_mapping_status"}}}
                if adapter != "daisat" or economic(previous) != economic(row):
                    raise ValueError("Duplicate supplier codes contain conflicting or unsupported records.")
                for field in ("source_categories", "inde_category_ids"):
                    previous["details"][field] = sorted(set(previous["details"][field] + details[field]))
                products.diagnostics["merged_category_rows"] += 1
            else:
                products.append(row)
                products.diagnostics["unnamed_products"] += not bool(name)
                seen[key] = row
                if len(products) > MAX_PRODUCTS:
                    raise ValueError("Supplier XML exceeds the product limit.")
        stack[-2].remove(node)
        node.clear()
        stack.pop()
    if not products:
        raise ValueError("Supplier XML contains no products; the previous catalog was retained.")
    return products
