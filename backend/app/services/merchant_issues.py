"""Merchant Center product approval statuses and item-level issues: the latest snapshot.

Every status sync replaces the snapshot. status_since and first_seen_at carry over from the previous snapshot
while a product's status or issue stays the same, so new problems can be told from old ones.
"""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MerchantProductIssue, MerchantProductStatus

STATUSES = ("disapproved", "partly_disapproved", "pending", "approved", "unknown")
SEVERITIES = ("DISAPPROVED", "DEMOTED", "NOT_IMPACTED")
# Issues that limit or stop delivery; NOT_IMPACTED issues are advice only.
DEFAULT_AFFECTED_SEVERITIES = ("DISAPPROVED", "DEMOTED")
NOTE = (
    "The latest Merchant Center snapshot (one products.list read per daily sync). status is per destination "
    "(reporting context): disapproved, partly_disapproved (approved in some countries only), pending, approved or "
    "unknown. is_new marks issues first seen in the latest snapshot; in the very first snapshot every issue is new."
)


def _label(value: Any, max_length: int, empty: str = "") -> str:
    text = str(value or "").strip()
    return text[:max_length] if text else empty


def _optional(value: Any, max_length: int | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_length] if max_length else text


def destination_status(destination: dict[str, Any]) -> str:
    approved = destination.get("approved_countries") or []
    if destination.get("disapproved_countries"):
        return "partly_disapproved" if approved else "disapproved"
    if approved:
        return "approved"
    if destination.get("pending_countries"):
        return "pending"
    return "unknown"


def _iso(value: datetime) -> str:
    """ISO time in the sync time zone, as in GET /api/dashboard/freshness."""
    return value.astimezone(ZoneInfo(settings.sync_timezone)).isoformat()


def _countries(value: Any) -> list[str]:
    return sorted({str(country) for country in value or [] if country})


def import_product_statuses(db: Session, products: list[dict[str, Any]], synced_at: datetime) -> dict[str, int]:
    """Replace the snapshot with `products` (rows from MerchantCenterConnector.fetch_product_statuses)."""
    previous_status = {
        (row.offer_id, row.feed_label, row.content_language, row.reporting_context): (row.status, row.status_since)
        for row in db.execute(select(
            MerchantProductStatus.offer_id, MerchantProductStatus.feed_label, MerchantProductStatus.content_language,
            MerchantProductStatus.reporting_context, MerchantProductStatus.status, MerchantProductStatus.status_since,
        )).all()
    }
    previous_issue = {
        (row.offer_id, row.feed_label, row.content_language, row.code, row.reporting_context, row.attribute):
            row.first_seen_at
        for row in db.execute(select(
            MerchantProductIssue.offer_id, MerchantProductIssue.feed_label, MerchantProductIssue.content_language,
            MerchantProductIssue.code, MerchantProductIssue.reporting_context, MerchantProductIssue.attribute,
            MerchantProductIssue.first_seen_at,
        )).all()
    }

    identities: set[tuple[str, str, str]] = set()
    statuses: dict[tuple, dict[str, Any]] = {}
    issues: dict[tuple, dict[str, Any]] = {}
    for product in products:
        identity = (_label(product.get("offer_id"), 160), _label(product.get("feed_label"), 64),
                    _label(product.get("content_language"), 16))
        if not identity[0]:
            continue
        identities.add(identity)
        base = dict(zip(("offer_id", "feed_label", "content_language"), identity),
                    title=_optional(product.get("title"), 500), synced_at=synced_at)
        for destination in product.get("destinations") or [{}]:
            key = (*identity, _label(destination.get("reporting_context"), 64))
            status = destination_status(destination)
            previous = previous_status.get(key)
            statuses[key] = {
                **base,
                "reporting_context": key[3],
                "status": status,
                "approved_countries": _countries(destination.get("approved_countries")),
                "pending_countries": _countries(destination.get("pending_countries")),
                "disapproved_countries": _countries(destination.get("disapproved_countries")),
                "status_since": previous[1] if previous and previous[0] == status else synced_at,
            }
        for issue in product.get("issues") or []:
            key = (*identity, _label(issue.get("code"), 255, "(no code)"),
                   _label(issue.get("reporting_context"), 64), _label(issue.get("attribute"), 160))
            if key in issues:
                countries = set(issues[key]["applicable_countries"]) | set(_countries(issue.get("applicable_countries")))
                issues[key]["applicable_countries"] = sorted(countries)
                continue
            issues[key] = {
                **base,
                "code": key[3],
                "reporting_context": key[4],
                "attribute": key[5],
                "severity": _label(issue.get("severity"), 32, "SEVERITY_UNSPECIFIED").upper(),
                "resolution": _optional(issue.get("resolution"), 64),
                "description": _optional(issue.get("description")),
                "detail": _optional(issue.get("detail")),
                "documentation": _optional(issue.get("documentation")),
                "applicable_countries": _countries(issue.get("applicable_countries")),
                "first_seen_at": previous_issue.get(key, synced_at),
            }

    db.execute(delete(MerchantProductIssue))
    db.execute(delete(MerchantProductStatus))
    if statuses:
        db.execute(insert(MerchantProductStatus), list(statuses.values()))
    if issues:
        db.execute(insert(MerchantProductIssue), list(issues.values()))
    db.commit()
    return {
        "merchant_status_products": len(identities),
        "merchant_status_rows": len(statuses),
        "merchant_issue_rows": len(issues),
    }


def merchant_issue_report(
    db: Session,
    severity: str | None = None,
    reporting_context: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Counts by status and by issue, and the affected products of the latest snapshot."""
    status_query = select(MerchantProductStatus.offer_id, MerchantProductStatus.feed_label,
                          MerchantProductStatus.content_language, MerchantProductStatus.title,
                          MerchantProductStatus.reporting_context, MerchantProductStatus.status,
                          MerchantProductStatus.status_since)
    issue_query = select(MerchantProductIssue)
    if reporting_context:
        status_query = status_query.where(MerchantProductStatus.reporting_context == reporting_context)
        issue_query = issue_query.where(MerchantProductIssue.reporting_context == reporting_context)
    synced_at = db.scalar(select(func.max(MerchantProductStatus.synced_at)))

    products: set[tuple[str, str, str]] = set()
    titles: dict[tuple[str, str, str], str | None] = {}
    status_counts: dict[str, dict[str, int]] = {}
    disapproved: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in db.execute(status_query).all():
        identity = (row.offer_id, row.feed_label, row.content_language)
        products.add(identity)
        titles[identity] = row.title
        counts = status_counts.setdefault(row.reporting_context, dict.fromkeys(STATUSES, 0))
        counts[row.status] = counts.get(row.status, 0) + 1
        if row.status in ("disapproved", "partly_disapproved"):
            disapproved.setdefault(identity, []).append({
                "reporting_context": row.reporting_context or None, "status": row.status,
                "status_since": _iso(row.status_since)})

    severities = (severity,) if severity else DEFAULT_AFFECTED_SEVERITIES
    by_issue: dict[tuple[str, str, str], dict[str, Any]] = {}
    severity_products: dict[str, set] = {name: set() for name in SEVERITIES}
    affected: dict[tuple[str, str, str], dict[str, Any]] = {}
    new_issue_rows = 0
    for issue in db.scalars(issue_query.order_by(MerchantProductIssue.offer_id, MerchantProductIssue.code)).all():
        identity = (issue.offer_id, issue.feed_label, issue.content_language)
        is_new = synced_at is not None and issue.first_seen_at == synced_at
        new_issue_rows += is_new
        severity_products.setdefault(issue.severity, set()).add(identity)
        summary = by_issue.setdefault((issue.code, issue.severity, issue.attribute), {
            "code": issue.code, "severity": issue.severity, "attribute": issue.attribute or None,
            "description": issue.description, "reporting_contexts": set(), "products": set(), "new_products": set()})
        summary["reporting_contexts"].add(issue.reporting_context)
        summary["products"].add(identity)
        if is_new:
            summary["new_products"].add(identity)
        if issue.severity not in severities:
            continue
        product = affected.setdefault(identity, {
            "offer_id": issue.offer_id, "feed_label": issue.feed_label or None,
            "content_language": issue.content_language or None, "title": issue.title,
            "disapproved_destinations": disapproved.get(identity, []), "issues": []})
        product["issues"].append({
            "code": issue.code, "severity": issue.severity, "attribute": issue.attribute or None,
            "reporting_context": issue.reporting_context or None, "description": issue.description,
            "detail": issue.detail, "documentation": issue.documentation, "resolution": issue.resolution,
            "applicable_countries": issue.applicable_countries, "first_seen_at": _iso(issue.first_seen_at),
            "is_new": is_new,
        })

    if "DISAPPROVED" in severities:
        # Disapproved for a destination without an item-level issue (e.g. an account-level problem).
        for identity, destinations in disapproved.items():
            affected.setdefault(identity, {
                "offer_id": identity[0], "feed_label": identity[1] or None, "content_language": identity[2] or None,
                "title": titles.get(identity), "disapproved_destinations": destinations, "issues": []})

    def severity_rank(name: str) -> int:
        return SEVERITIES.index(name) if name in SEVERITIES else len(SEVERITIES)

    def product_rank(product: dict[str, Any]) -> tuple:
        worst = min((severity_rank(issue["severity"]) for issue in product["issues"]),
                    default=0 if product["disapproved_destinations"] else len(SEVERITIES))
        return (worst, not product["disapproved_destinations"], -len(product["issues"]), product["offer_id"])

    ranked = sorted(affected.values(), key=product_rank)
    return {
        "synced_at": _iso(synced_at) if synced_at else None,
        "severity": severity,
        "reporting_context": reporting_context,
        "products": len(products),
        "status_counts": [
            {"reporting_context": context or None, **counts, "total": sum(counts.values())}
            for context, counts in sorted(status_counts.items())
        ],
        "severity_counts": {name: len(identities) for name, identities in severity_products.items()},
        "issue_counts": [
            {**{key: value for key, value in summary.items() if key not in {"products", "new_products",
                                                                          "reporting_contexts"}},
             "reporting_contexts": sorted(context for context in summary["reporting_contexts"] if context),
             "products": len(summary["products"]), "new_products": len(summary["new_products"])}
            for summary in sorted(by_issue.values(), key=lambda item: (
                severity_rank(item["severity"]), -len(item["products"]), item["code"], item["attribute"] or ""))
        ],
        "new_issue_rows": new_issue_rows,
        "affected_severities": list(severities),
        "affected_product_count": len(ranked),
        "affected_products": ranked[:limit],
        "note": NOTE,
    }
