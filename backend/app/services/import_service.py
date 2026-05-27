import csv
import io
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AADEDocument,
    AADESummaryMetric,
    CampaignDailyMetric,
    GA4DailyMetric,
    MerchantProductMetric,
    OpenCartOrder,
    OpenCartOrderChange,
    OpenCartOrderProduct,
    ProductCatalog,
    SearchConsoleDailyMetric,
    ShoplySale,
)
from app.services.parsing import as_date, as_datetime, as_decimal, as_int


def _action_value(actions: list[dict[str, Any]] | None, action_type: str) -> int:
    if not actions:
        return 0
    for action in actions:
        if _action_matches(action.get("action_type"), action_type):
            return as_int(action.get("value"))
    return 0


def _money_action_value(actions: list[dict[str, Any]] | None, action_type: str):
    if not actions:
        return as_decimal(0)
    for action in actions:
        if _action_matches(action.get("action_type"), action_type):
            return as_decimal(action.get("value"))
    return as_decimal(0)


def _action_matches(actual: Any, expected: str) -> bool:
    value = str(actual or "")
    return value == expected or value.endswith(f".{expected}") or value.endswith(f"_{expected}")


def import_google_ads_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date") or row.get("day"), fallback_date) for row in rows} or {fallback_date}
    db.execute(
        delete(CampaignDailyMetric).where(
            CampaignDailyMetric.source == "google_ads",
            CampaignDailyMetric.metric_date.in_(touched_dates),
        )
    )

    for row in rows:
        metric_date = as_date(row.get("date") or row.get("day"), fallback_date)
        cost = as_decimal(row.get("cost"))
        conversion_value = as_decimal(row.get("conversion_value") or row.get("conversions_value"))
        conversions = as_decimal(row.get("conversions"))
        roas = as_decimal(row.get("roas"))
        if not conversion_value and roas and cost:
            conversion_value = roas * cost
        db.add(
            CampaignDailyMetric(
                source="google_ads",
                metric_date=metric_date,
                campaign_id=str(row.get("campaign_id") or "") or None,
                campaign_name=str(row.get("campaign_name") or "Unknown campaign"),
                campaign_type=row.get("campaign_type"),
                cost=cost,
                clicks=as_int(row.get("clicks")),
                impressions=as_int(row.get("impressions")),
                conversions=conversions,
                conversion_value=conversion_value,
                purchases=conversions,
                purchase_value=conversion_value,
                avg_cpc=as_decimal(row.get("avg_cpc")),
                cpc=as_decimal(row.get("avg_cpc") or row.get("cpc")),
                cost_per_conversion=as_decimal(row.get("cost_per_conversion")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


_GOOGLE_ADS_HEADER_ALIASES = {
    "date": "date",
    "day": "date",
    "ημερα": "date",
    "ημερομηνια": "date",
    "campaign": "campaign_name",
    "campaign name": "campaign_name",
    "campaign_name": "campaign_name",
    "καμπανια": "campaign_name",
    "campaign id": "campaign_id",
    "campaign_id": "campaign_id",
    "id καμπανιας": "campaign_id",
    "αναγνωριστικο καμπανιας": "campaign_id",
    "campaign type": "campaign_type",
    "campaign_type": "campaign_type",
    "τυπος καμπανιας": "campaign_type",
    "cost": "cost",
    "κοστος": "cost",
    "clicks": "clicks",
    "κλικ": "clicks",
    "impr.": "impressions",
    "impressions": "impressions",
    "εμφ.": "impressions",
    "εμφανισεις": "impressions",
    "conversions": "conversions",
    "conv.": "conversions",
    "μετατρ.": "conversions",
    "μετατροπες": "conversions",
    "conversion value": "conversion_value",
    "conv. value": "conversion_value",
    "conversions value": "conversion_value",
    "conversion_value": "conversion_value",
    "τιμη μετατρ.": "conversion_value",
    "αξια μετατρ.": "conversion_value",
    "roas": "roas",
    "conv. value / cost": "roas",
    "conversion value / cost": "roas",
    "value / cost": "roas",
    "τιμη μετατρ./κοστος": "roas",
    "αξια συνολικων μετατρ. / κοστος": "roas",
    "avg. cpc": "avg_cpc",
    "average cpc": "avg_cpc",
    "μεσο cpc": "avg_cpc",
    "cost / conv.": "cost_per_conversion",
    "cost/conv.": "cost_per_conversion",
    "cost per conversion": "cost_per_conversion",
    "κοστος/μετατρ.": "cost_per_conversion",
}

_GOOGLE_ADS_NUMERIC_FIELDS = {
    "cost",
    "clicks",
    "impressions",
    "conversions",
    "conversion_value",
    "roas",
    "avg_cpc",
    "cost_per_conversion",
}

_GOOGLE_ADS_MONTHS = {
    "jan": 1,
    "january": 1,
    "ιαν": 1,
    "ιανουαριου": 1,
    "feb": 2,
    "february": 2,
    "φεβ": 2,
    "φεβρουαριου": 2,
    "mar": 3,
    "march": 3,
    "μαρ": 3,
    "μαρτιου": 3,
    "apr": 4,
    "april": 4,
    "απρ": 4,
    "απριλιου": 4,
    "may": 5,
    "μαι": 5,
    "μαιου": 5,
    "jun": 6,
    "june": 6,
    "ιουν": 6,
    "ιουνιου": 6,
    "jul": 7,
    "july": 7,
    "ιουλ": 7,
    "ιουλιου": 7,
    "aug": 8,
    "august": 8,
    "αυγ": 8,
    "αυγουστου": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "σεπ": 9,
    "σεπτεμβριου": 9,
    "oct": 10,
    "october": 10,
    "οκτ": 10,
    "οκτωβριου": 10,
    "nov": 11,
    "november": 11,
    "νοε": 11,
    "νοεμβριου": 11,
    "dec": 12,
    "december": 12,
    "δεκ": 12,
    "δεκεμβριου": 12,
}


def _normalize_csv_key(value: Any) -> str:
    text = str(value or "").replace("\ufeff", "").replace("\u00a0", " ").strip().lower()
    normalized = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        char
        for char in normalized
        if not unicodedata.combining(char) and unicodedata.category(char) not in {"Cc", "Cf"}
    )
    return re.sub(r"\s+", " ", without_marks)


def _google_ads_number(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    if text in {"", "-", "--", "—"}:
        return ""
    text = text.replace("€", "").replace("%", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    return text


def _parse_google_ads_date(value: Any, fallback: date) -> date:
    text = str(value or "").replace("\ufeff", "").strip()
    if not text or text in {"-", "--", "—"}:
        return fallback
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    match = re.search(r"(\d{1,2})\s+([^\s,]+)\s+(\d{4})", text)
    if match:
        day = int(match.group(1))
        month_key = _normalize_csv_key(match.group(2).strip("."))
        month = _GOOGLE_ADS_MONTHS.get(month_key)
        if month:
            return date(int(match.group(3)), month, day)
    return fallback


def _google_ads_report_date(lines: list[str], fallback: date) -> date:
    for line in lines[:5]:
        parts = [part.strip() for part in re.split(r"\s+-\s+", line) if part.strip()]
        if len(parts) == 2:
            start = _parse_google_ads_date(parts[0], fallback)
            end = _parse_google_ads_date(parts[1], fallback)
            if start == end:
                return start
    return fallback


def _google_ads_header_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if "," not in line:
            continue
        try:
            columns = next(csv.reader([line]))
        except csv.Error:
            continue
        fields = {_google_ads_field_for_header(column) for column in columns}
        fields.discard(None)
        if {"campaign_name", "cost"} <= fields:
            return index

        keys = {_normalize_csv_key(column) for column in columns}
        if {"campaign", "campaign name", "campaign_name", "καμπανια"} & keys and {"cost", "κοστος"} & keys:
            return index
    return 0


def _google_ads_field_for_header(header: Any) -> str | None:
    key = _normalize_csv_key(header)
    exact = _GOOGLE_ADS_HEADER_ALIASES.get(key)
    if exact:
        return exact
    if key in {"ημερα", "ημερομηνια"} or key.endswith(" ημερα"):
        return "date"
    if key in {"καμπανια", "campaign"} or key.endswith(" campaign"):
        return "campaign_name"
    if "αναγνωριστικο" in key and "καμπανια" in key:
        return "campaign_id"
    if key == "τυπος καμπανιας" or key == "campaign type":
        return "campaign_type"
    if key == "κοστος" or key == "cost":
        return "cost"
    if key == "κλικ" or key == "clicks":
        return "clicks"
    if key in {"εμφ.", "εμφανισεις", "impr.", "impressions"}:
        return "impressions"
    if key in {"μετατρ.", "μετατροπες", "conv.", "conversions"}:
        return "conversions"
    if key in {"τιμη μετατρ.", "αξια μετατρ.", "conv. value", "conversion value"}:
        return "conversion_value"
    if key in {"τιμη μετατρ./κοστος", "αξια συνολικων μετατρ. / κοστος", "conv. value / cost", "conversion value / cost"}:
        return "roas"
    if key in {"μεσο cpc", "avg. cpc", "average cpc"}:
        return "avg_cpc"
    if key in {"κοστος/μετατρ.", "cost / conv.", "cost/conv.", "cost per conversion"}:
        return "cost_per_conversion"
    return None


def _normalize_google_ads_csv_row(row: dict[str, Any], fallback_date: date) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    raw = {str(key or ""): value for key, value in row.items()}
    for header, value in raw.items():
        field = _google_ads_field_for_header(header)
        if not field:
            continue
        if field == "date":
            normalized["date"] = _parse_google_ads_date(value, fallback_date).isoformat()
        elif field in _GOOGLE_ADS_NUMERIC_FIELDS:
            normalized[field] = _google_ads_number(value)
        else:
            normalized[field] = str(value or "").strip()

    if not normalized.get("date"):
        normalized["date"] = fallback_date.isoformat()
    normalized["raw_csv"] = raw
    return normalized


def _google_ads_csv_rows(text: str, fallback_date: date) -> list[dict[str, Any]]:
    lines = text.splitlines()
    header_index = _google_ads_header_index(lines)
    report_date = _google_ads_report_date(lines[:header_index], fallback_date)
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[header_index:]))))
    normalized_rows = [_normalize_google_ads_csv_row(row, report_date) for row in rows]
    imported_rows = [
        row
        for row in normalized_rows
        if row.get("campaign_name")
        and _normalize_csv_key(row.get("campaign_name")) not in {"-", "--", "—"}
        and not _normalize_csv_key(row.get("campaign_name")).startswith(("total", "συνολο"))
    ]
    if not imported_rows and rows:
        headers = [str(header or "").strip() for header in rows[0].keys()]
        raise ValueError(
            "No Google Ads campaign rows were recognized. "
            f"Detected CSV columns: {', '.join(headers[:12])}"
        )
    return imported_rows


def import_google_ads_csv(db: Session, text: str, fallback_date: date) -> int:
    rows = _google_ads_csv_rows(text, fallback_date)
    return import_google_ads_rows(db, rows, fallback_date)


def import_meta_ads_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date") or row.get("date_start"), fallback_date) for row in rows} or {fallback_date}
    db.execute(
        delete(CampaignDailyMetric).where(
            CampaignDailyMetric.source == "meta_ads",
            CampaignDailyMetric.metric_date.in_(touched_dates),
        )
    )

    for row in rows:
        actions = row.get("actions") if isinstance(row.get("actions"), list) else None
        action_values = row.get("action_values") if isinstance(row.get("action_values"), list) else None
        purchases = as_decimal(row.get("purchases") or _action_value(actions, "purchase"))
        purchase_value = as_decimal(row.get("purchase_value") or _money_action_value(action_values, "purchase"))
        db.add(
            CampaignDailyMetric(
                source="meta_ads",
                metric_date=as_date(row.get("date") or row.get("date_start"), fallback_date),
                campaign_id=str(row.get("campaign_id") or "") or None,
                campaign_name=str(row.get("campaign_name") or "Unknown campaign"),
                adset_id=str(row.get("adset_id") or "") or None,
                adset_name=row.get("adset_name"),
                ad_id=str(row.get("ad_id") or "") or None,
                ad_name=row.get("ad_name"),
                cost=as_decimal(row.get("spend") or row.get("cost")),
                impressions=as_int(row.get("impressions")),
                reach=as_int(row.get("reach")),
                frequency=as_decimal(row.get("frequency")),
                link_clicks=as_int(row.get("link_clicks") or row.get("inline_link_clicks") or _action_value(actions, "link_click")),
                landing_page_views=as_int(row.get("landing_page_views") or _action_value(actions, "landing_page_view")),
                add_to_cart=as_int(row.get("add_to_cart") or _action_value(actions, "add_to_cart")),
                initiate_checkout=as_int(row.get("initiate_checkout") or _action_value(actions, "initiate_checkout")),
                purchases=purchases,
                purchase_value=purchase_value,
                conversions=purchases,
                conversion_value=purchase_value,
                cpc=as_decimal(row.get("cpc")),
                cpm=as_decimal(row.get("cpm")),
                ctr=as_decimal(row.get("ctr")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def import_meta_ads_csv(db: Session, text: str, fallback_date: date) -> int:
    rows = list(csv.DictReader(io.StringIO(text)))
    return import_meta_ads_rows(db, rows, fallback_date)


def import_ga4_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date"), fallback_date) for row in rows} or {fallback_date}
    db.execute(delete(GA4DailyMetric).where(GA4DailyMetric.metric_date.in_(touched_dates)))
    for row in rows:
        db.add(
            GA4DailyMetric(
                metric_date=as_date(row.get("date"), fallback_date),
                channel_group=row.get("channel_group") or row.get("sessionDefaultChannelGroup"),
                source_medium=row.get("source_medium") or row.get("sessionSourceMedium"),
                sessions=as_int(row.get("sessions")),
                users=as_int(row.get("users") or row.get("totalUsers")),
                purchases=as_decimal(row.get("purchases")),
                purchase_revenue=as_decimal(row.get("purchase_revenue") or row.get("purchaseRevenue")),
                conversions=as_decimal(row.get("conversions")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def import_merchant_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date"), fallback_date) for row in rows} or {fallback_date}
    db.execute(delete(MerchantProductMetric).where(MerchantProductMetric.metric_date.in_(touched_dates)))
    for row in rows:
        db.add(
            MerchantProductMetric(
                metric_date=as_date(row.get("date"), fallback_date),
                item_id=str(row.get("item_id") or row.get("id") or row.get("offer_id") or ""),
                title=row.get("title") or row.get("name"),
                brand=row.get("brand"),
                category=row.get("category") or row.get("google_product_category") or row.get("product_type"),
                availability=row.get("availability"),
                price=as_decimal(row.get("price")),
                sale_price=as_decimal(row.get("sale_price")),
                clicks=as_int(row.get("clicks")),
                impressions=as_int(row.get("impressions")),
                ctr=as_decimal(row.get("ctr")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def import_search_console_rows(db: Session, rows: list[dict[str, Any]], fallback_date: date) -> int:
    touched_dates = {as_date(row.get("date"), fallback_date) for row in rows} or {fallback_date}
    touched_sites = {
        str(row.get("site_url") or row.get("site") or "").strip()
        for row in rows
        if str(row.get("site_url") or row.get("site") or "").strip()
    }
    query = delete(SearchConsoleDailyMetric).where(SearchConsoleDailyMetric.metric_date.in_(touched_dates))
    if touched_sites:
        query = query.where(SearchConsoleDailyMetric.site_url.in_(touched_sites))
    db.execute(query)

    for row in rows:
        db.add(
            SearchConsoleDailyMetric(
                metric_date=as_date(row.get("date"), fallback_date),
                site_url=str(row.get("site_url") or row.get("site") or ""),
                query=row.get("query"),
                page=row.get("page"),
                country=row.get("country"),
                device=row.get("device"),
                clicks=as_int(row.get("clicks")),
                impressions=as_int(row.get("impressions")),
                ctr=as_decimal(row.get("ctr")),
                position=as_decimal(row.get("position")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)


def import_aade_payload(db: Session, payload: dict[str, Any], fallback_date: date) -> int:
    documents = payload.get("documents") if isinstance(payload, dict) else []
    summary_rows = payload.get("summary_rows") if isinstance(payload, dict) else []
    if not isinstance(documents, list):
        documents = []
    if not isinstance(summary_rows, list):
        summary_rows = []

    touched_summary_dates = {
        as_date(row.get("metric_date") or row.get("date"), fallback_date)
        for row in summary_rows
        if isinstance(row, dict)
    } or {fallback_date}
    touched_summary_sources = {
        str(row.get("source_endpoint") or "summary")
        for row in summary_rows
        if isinstance(row, dict)
    }
    summary_delete = delete(AADESummaryMetric).where(AADESummaryMetric.metric_date.in_(touched_summary_dates))
    if touched_summary_sources:
        summary_delete = summary_delete.where(AADESummaryMetric.source_endpoint.in_(touched_summary_sources))
    db.execute(summary_delete)

    count = 0
    for row in documents:
        if not isinstance(row, dict):
            continue
        document_count = as_int(row.get("document_count")) or 1
        issue_date = as_date(row.get("issue_date"), fallback_date)
        source_endpoint = str(row.get("source_endpoint") or "unknown")
        identity_key = str(
            row.get("identity_key")
            or row.get("mark")
            or row.get("uid")
            or f"{source_endpoint}:{issue_date.isoformat()}:{row.get('series') or ''}:{row.get('aa') or ''}:{row.get('gross_value') or 0}"
        )
        values = {
            "source_endpoint": source_endpoint,
            "identity_key": identity_key,
            "mark": _text_or_none(row.get("mark")),
            "uid": _text_or_none(row.get("uid")),
            "issuer_vat": _text_or_none(row.get("issuer_vat")),
            "counterpart_vat": _text_or_none(row.get("counterpart_vat")),
            "issue_date": issue_date,
            "document_direction": str(row.get("document_direction") or "unknown"),
            "invoice_type": _text_or_none(row.get("invoice_type")),
            "series": _text_or_none(row.get("series")),
            "aa": _text_or_none(row.get("aa")),
            "currency": _text_or_none(row.get("currency")) or "EUR",
            "net_value": as_decimal(row.get("net_value")),
            "vat_amount": as_decimal(row.get("vat_amount")),
            "gross_value": as_decimal(row.get("gross_value")),
            "is_cancelled": bool(row.get("is_cancelled")),
            "cancelled_by_mark": _text_or_none(row.get("cancelled_by_mark")),
            "raw": row.get("raw") if isinstance(row.get("raw"), dict) else row,
        }
        existing = db.scalar(select(AADEDocument).where(AADEDocument.identity_key == identity_key))
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            db.add(existing)
        else:
            db.add(AADEDocument(**values))
        count += document_count

    for row in summary_rows:
        if not isinstance(row, dict):
            continue
        db.add(
            AADESummaryMetric(
                metric_date=as_date(row.get("metric_date") or row.get("date"), fallback_date),
                source_endpoint=str(row.get("source_endpoint") or "summary"),
                metric_name=str(row.get("metric_name") or "unknown"),
                amount=as_decimal(row.get("amount")),
                quantity=as_int(row.get("quantity")),
                raw=row.get("raw") if isinstance(row.get("raw"), dict) else row,
            )
        )

    db.commit()
    return count + len(summary_rows)


def _normalize_opencart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows or any(isinstance(row.get("products"), list) for row in rows):
        return rows
    if not any("product_id" in row or "product_name" in row for row in rows):
        return rows

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        order_id = str(row.get("order_id") or row.get("id") or "")
        if not order_id:
            continue
        order = grouped.setdefault(
            order_id,
            {
                **row,
                "shipping": row.get("shipping") or row.get("shipping_value"),
                "products": [],
            },
        )
        if row.get("product_id") or row.get("product_name"):
            order["products"].append(
                {
                    "product_id": row.get("product_id"),
                    "model": row.get("product_model"),
                    "sku": row.get("product_sku") or row.get("product_model"),
                    "name": row.get("product_name"),
                    "manufacturer": row.get("manufacturer") or row.get("brand"),
                    "brand": row.get("brand") or row.get("manufacturer"),
                    "category": row.get("category"),
                    "quantity": row.get("product_quantity"),
                    "price": row.get("product_price"),
                    "total": row.get("product_total"),
                    "mpn": row.get("product_mpn"),
                    "weight": row.get("product_weight"),
                }
            )
    return list(grouped.values())


def _lookup_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime_or_none(value: Any):
    if value is None or value == "":
        return None
    return as_datetime(value)


def _change_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _values_differ(old_value: Any, new_value: Any) -> bool:
    if isinstance(old_value, Decimal) or isinstance(new_value, Decimal):
        return as_decimal(old_value) != as_decimal(new_value)
    return _change_text(old_value) != _change_text(new_value)


def _set_order_field(
    db: Session,
    order: OpenCartOrder,
    field_name: str,
    new_value: Any,
    source_modified_at: datetime | None,
    raw: dict[str, Any],
    *,
    record_change: bool = True,
) -> None:
    old_value = getattr(order, field_name)
    if _values_differ(old_value, new_value):
        if record_change:
            db.add(
                OpenCartOrderChange(
                    order_pk=order.id,
                    order_id=order.order_id,
                    field_name=field_name,
                    old_value=_change_text(old_value),
                    new_value=_change_text(new_value),
                    source_modified_at=source_modified_at,
                    raw=raw,
                )
            )
        setattr(order, field_name, new_value)


def _order_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date_added": as_datetime(row.get("date_added")),
        "date_modified": _datetime_or_none(row.get("date_modified")),
        "order_status_id": _text_or_none(row.get("order_status_id")),
        "order_status": _text_or_none(row.get("order_status") or row.get("status")),
        "store_id": _text_or_none(row.get("store_id")),
        "store_name": _text_or_none(row.get("store_name")),
        "customer_id": _text_or_none(row.get("customer_id")),
        "customer_group_id": _text_or_none(row.get("customer_group_id")),
        "customer_group": _text_or_none(row.get("customer_group")),
        "sub_total": as_decimal(row.get("sub_total_value") or row.get("sub_total")),
        "tax": as_decimal(row.get("tax_value") or row.get("tax")),
        "total": as_decimal(row.get("total") or row.get("total_value") or row.get("total_in_order_currency")),
        "shipping": as_decimal(row.get("shipping") or row.get("shipping_value")),
        "payment_method": _text_or_none(row.get("payment_method")),
        "payment_code": _text_or_none(row.get("payment_code")),
        "shipping_title": _text_or_none(row.get("shipping_title")),
        "shipping_method": _text_or_none(row.get("shipping_method")),
        "shipping_code": _text_or_none(row.get("shipping_code")),
        "tracking_carrier": _text_or_none(row.get("tracking_carrier")),
        "payment_country": _text_or_none(row.get("payment_country")),
        "payment_zone": _text_or_none(row.get("payment_zone")),
        "payment_city": _text_or_none(row.get("payment_city")),
        "payment_postcode": _text_or_none(row.get("payment_postcode")),
        "shipping_country": _text_or_none(row.get("shipping_country")),
        "shipping_zone": _text_or_none(row.get("shipping_zone")),
        "shipping_city": _text_or_none(row.get("shipping_city")),
        "shipping_postcode": _text_or_none(row.get("shipping_postcode")),
        "currency_code": _text_or_none(row.get("currency_code")),
    }


def import_product_catalog(db: Session, rows: list[dict[str, Any]]) -> int:
    rows_by_sku = {str(row.get("sku") or "").strip(): row for row in rows if str(row.get("sku") or "").strip()}
    if not rows_by_sku:
        return 0

    existing = {
        product.sku: product
        for product in db.scalars(select(ProductCatalog).where(ProductCatalog.sku.in_(list(rows_by_sku.keys())))).all()
    }
    now = datetime.now(timezone.utc)
    for sku, row in rows_by_sku.items():
        product = existing.get(sku)
        if not product:
            product = ProductCatalog(sku=sku, name=str(row.get("name") or sku), raw=row)
            db.add(product)
            existing[sku] = product
        product.model = row.get("model")
        product.product_id = row.get("product_id")
        product.name = str(row.get("name") or product.name or sku)
        product.brand = row.get("brand") or row.get("manufacturer")
        product.manufacturer = row.get("manufacturer") or row.get("brand")
        product.category = row.get("category")
        product.category_path = row.get("category_path")
        product.status = row.get("status")
        product.quantity = as_int(row.get("quantity"))
        product.price = as_decimal(row.get("price"))
        product.link = row.get("link")
        product.image_url = row.get("image_url")
        product.raw = row
        product.last_seen_at = now
    db.flush()
    return len(rows_by_sku)


def _product_lookup(db: Session) -> dict[str, ProductCatalog]:
    lookup: dict[str, ProductCatalog] = {}
    for product in db.scalars(select(ProductCatalog)).all():
        for value in (
            product.sku,
            product.model,
            product.product_id,
            (product.raw or {}).get("isbn"),
            (product.raw or {}).get("upc"),
            (product.raw or {}).get("ean"),
            (product.raw or {}).get("jan"),
        ):
            key = _lookup_key(value)
            if key:
                lookup[key] = product
    return lookup


def _enrich_order_product(product: dict[str, Any], lookup: dict[str, ProductCatalog]) -> dict[str, Any]:
    catalog = None
    for value in (
        product.get("sku"),
        product.get("model"),
        product.get("product_id"),
        product.get("mpn"),
        product.get("isbn"),
        product.get("upc"),
        product.get("ean"),
        product.get("jan"),
    ):
        catalog = lookup.get(_lookup_key(value))
        if catalog:
            break
    if not catalog:
        return product

    enriched = {**product}
    enriched["sku"] = enriched.get("sku") or catalog.sku
    enriched["model"] = enriched.get("model") or catalog.model
    enriched["product_id"] = enriched.get("product_id") or catalog.product_id
    enriched["name"] = enriched.get("name") or catalog.name
    enriched["manufacturer"] = enriched.get("manufacturer") or catalog.manufacturer or catalog.brand
    enriched["brand"] = enriched.get("brand") or catalog.brand or catalog.manufacturer
    enriched["category"] = enriched.get("category") or catalog.category
    enriched["catalog"] = {
        "sku": catalog.sku,
        "status": catalog.status,
        "quantity": catalog.quantity,
        "price": str(catalog.price),
        "link": catalog.link,
        "image_url": catalog.image_url,
    }
    return enriched


def import_opencart_orders(db: Session, rows: list[dict[str, Any]]) -> int:
    normalized_rows = _normalize_opencart_rows(rows)
    catalog_lookup = _product_lookup(db)
    order_ids = [str(row.get("order_id") or row.get("id") or "") for row in normalized_rows]
    order_ids = [order_id for order_id in order_ids if order_id]
    existing_orders = {
        order.order_id: order
        for order in db.scalars(select(OpenCartOrder).where(OpenCartOrder.order_id.in_(order_ids))).all()
    }
    for row in normalized_rows:
        order_id = str(row.get("order_id") or row.get("id") or "")
        if not order_id:
            continue
        order_values = _order_values(row)
        source_modified_at = order_values["date_modified"]
        order = existing_orders.get(order_id)
        is_new = False
        if not order:
            order = OpenCartOrder(order_id=order_id, date_added=order_values["date_added"], raw=row)
            db.add(order)
            db.flush()
            existing_orders[order_id] = order
            is_new = True
        for field_name, new_value in order_values.items():
            _set_order_field(db, order, field_name, new_value, source_modified_at, row, record_change=not is_new)
        order.raw = row
        order.products.clear()
        for product in row.get("products", []) or []:
            product = _enrich_order_product(product, catalog_lookup)
            order.products.append(
                OpenCartOrderProduct(
                    product_id=str(product.get("product_id") or "") or None,
                    model=product.get("model"),
                    sku=product.get("sku"),
                    name=product.get("name") or "Unknown product",
                    manufacturer=product.get("manufacturer") or product.get("brand"),
                    brand=product.get("brand") or product.get("manufacturer"),
                    category=product.get("category"),
                    quantity=as_int(product.get("quantity")),
                    price=as_decimal(product.get("price")),
                    raw=product,
                )
            )
    db.commit()
    return len(normalized_rows)


def import_shoply_sales(db: Session, rows: list[dict[str, Any]]) -> int:
    for row in rows:
        db.add(
            ShoplySale(
                external_order_id=str(row.get("order_id") or row.get("id") or "") or None,
                sale_date=as_datetime(row.get("date") or row.get("date_added") or row.get("created_at")),
                status=row.get("status") or row.get("order_status"),
                total=as_decimal(row.get("total")),
                raw=row,
            )
        )
    db.commit()
    return len(rows)
