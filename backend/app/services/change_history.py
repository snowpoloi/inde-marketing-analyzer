"""Change history of the ad platforms for one window, grouped in SQL.

A nightly Google Ads feed upload stores thousands of identical automated changes. They are counted per Athens day
and folded into one "bulk" group each, so the few manual changes stay visible. A 93-day window stays cheap: the
grouping and the search for individual changes read only `ix_review_events_changes`, never the wide payload rows.
Only the rows on the page (and, for a text search, the individual candidates) are read in full.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, any_, bindparam, cast, func, literal_column, not_, or_, select, text, union_all
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Session

from app.models import CampaignDailyMetric, ReviewEvent, ReviewJob

TIMEZONE_NAME = "Europe/Athens"
TIMEZONE = ZoneInfo(TIMEZONE_NAME)
BULK_MIN_SIZE = 50
MAX_DAYS = 93
MAX_BULK_GROUPS = 1000
NO_ACTOR = "__none__"  # actor filter value for changes without a recorded person
HISTORY_PROVIDERS = ("google_ads", "meta_ads")  # the providers whose APIs the history jobs read

# Literal constants: bound parameters would differ between SELECT and GROUP BY for PostgreSQL.
DAY = cast(func.timezone(literal_column(f"'{TIMEZONE_NAME}'"), ReviewEvent.occurred_at), Date)
ACTOR = func.coalesce(ReviewEvent.actor, literal_column("''"))

# Greek capitals and accents are folded the same way in SQL and in Python, so «μαρια» finds «Μαρία» whatever the
# database locale. ILIKE then ignores the case of Latin letters.
GREEK_FROM = "ΆΈΉΊΌΎΏΪΫάέήίόύώϊϋΐΰςΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
GREEK_TO = "αεηιουωιυαεηιουωιυιυσαβγδεζηθικλμνξοπρστυφχψω"
GREEK_FOLD = str.maketrans(GREEK_FROM, GREEK_TO)


def window_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    start = datetime.combine(date_from, time.min, tzinfo=TIMEZONE)
    return start, datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=TIMEZONE)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _matches(field, pattern: str):
    return func.translate(field, GREEK_FROM, GREEK_TO).ilike(pattern, escape="\\")


def _fold(value: str | None) -> str:
    return (value or "").translate(GREEK_FOLD).casefold()


def _search(db: Session, q: str):
    pattern = f"%{_escape_like(q.translate(GREEK_FOLD))}%"
    conditions = [_matches(field, pattern) for field in
                  (ReviewEvent.title, ReviewEvent.detail, ReviewEvent.actor, ReviewEvent.object_id)]
    # Google change events name the campaign only by id; match the names we know from the daily metrics.
    campaign_ids = db.scalars(select(CampaignDailyMetric.campaign_id).distinct().where(
        CampaignDailyMetric.source == "google_ads", _matches(CampaignDailyMetric.campaign_name, pattern),
        CampaignDailyMetric.campaign_id.is_not(None), CampaignDailyMetric.campaign_id != "").limit(50)).all()
    conditions += [ReviewEvent.object_id.like(f"%/campaigns/{_escape_like(cid)}", escape="\\") for cid in campaign_ids]
    return or_(*conditions)


def _campaign_names(db: Session, events: list[ReviewEvent]) -> dict[str, str]:
    ids = {(event.object_id or "").rsplit("/campaigns/", 1)[1] for event in events
           if event.source == "google_ads" and "/campaigns/" in (event.object_id or "")}
    ids = {value for value in ids if value.isdigit()}
    if not ids:
        return {}
    rows = db.execute(select(CampaignDailyMetric.campaign_id, func.max(CampaignDailyMetric.campaign_name))
                      .where(CampaignDailyMetric.source == "google_ads", CampaignDailyMetric.campaign_id.in_(ids))
                      .group_by(CampaignDailyMetric.campaign_id)).all()
    return {campaign_id: name for campaign_id, name in rows}


def _payload_text(payload, key: str) -> str | None:
    value = payload.get(key) if isinstance(payload, dict) else None
    return str(value) if value not in (None, "") else None


def serialize_change(event: ReviewEvent, campaigns: dict[str, str]) -> dict:
    object_id = event.object_id or ""
    campaign_id = object_id.rsplit("/campaigns/", 1)[1] if "/campaigns/" in object_id else None
    payload = event.payload if isinstance(event.payload, dict) else {}
    return {"id": str(event.id), "source": event.source, "occurred_at": event.occurred_at.isoformat(),
            "day": event.occurred_at.astimezone(TIMEZONE).date().isoformat(), "evidence_type": event.evidence_type,
            "actor": event.actor or None, "title": event.title, "detail": event.detail, "object_id": event.object_id,
            "reference_url": event.reference_url,
            # Google: what kind of item changed and with which tool. Meta keeps that in `title` (event type).
            "resource_type": _payload_text(payload, "change_resource_type"),
            "client_type": _payload_text(payload, "client_type"),
            "campaign": campaigns.get(campaign_id) if campaign_id else None, "payload": payload}


def _coverage(db: Session, date_from: date, date_to: date) -> list[dict]:
    """Which days the history jobs have read, per provider. Error texts stay out (they can carry account details)."""
    jobs = db.execute(select(ReviewJob.provider, ReviewJob.date_from, ReviewJob.date_to, ReviewJob.status)
                      .where(ReviewJob.kind == "changes", ReviewJob.provider.in_(HISTORY_PROVIDERS),
                             ReviewJob.date_from <= date_to, ReviewJob.date_to >= date_from)).all()
    fetched = dict(db.execute(select(ReviewJob.provider, func.max(ReviewJob.finished_at))
                              .where(ReviewJob.kind == "changes", ReviewJob.status == "success",
                                     ReviewJob.provider.in_(HISTORY_PROVIDERS))
                              .group_by(ReviewJob.provider)).all())
    requested = (date_to - date_from).days + 1
    result = []
    for provider in HISTORY_PROVIDERS:
        days: dict[str, set[date]] = {"success": set(), "unavailable": set(), "failed": set()}
        for job_provider, start, end, status in jobs:
            if job_provider != provider or status not in days:
                continue
            day = max(start, date_from)
            while day <= min(end, date_to):
                days[status].add(day)
                day += timedelta(days=1)
        result.append({"source": provider, "days_requested": requested, "days_covered": len(days["success"]),
                       "days_unavailable": len(days["unavailable"] - days["success"]),
                       "days_failed": len(days["failed"] - days["success"]),
                       "last_fetched_at": fetched[provider].isoformat() if fetched.get(provider) else None})
    return result


def _groups(db: Session, start: datetime, end: datetime) -> list[dict]:
    """Every group of the window (day, source, actor, type, title) with its size and time range."""
    key = (DAY, ReviewEvent.source, ACTOR, ReviewEvent.evidence_type, ReviewEvent.title)
    # Room to group a 93-day window in memory instead of sorting on disk; ends with the request's transaction.
    db.execute(text("SET LOCAL work_mem = '64MB'"))
    rows = db.execute(select(*key, func.count(), func.min(ReviewEvent.occurred_at), func.max(ReviewEvent.occurred_at))
                      .where(ReviewEvent.occurred_at >= start, ReviewEvent.occurred_at < end).group_by(*key))
    return [{"day": day, "source": source, "actor": actor, "evidence_type": evidence_type, "title": title,
             "count": count, "first": first, "last": last, "bulk": count >= BULK_MIN_SIZE}
            for day, source, actor, evidence_type, title, count, first, last in rows]


def _individual(start: datetime, end: datetime, bulk: list[dict], filters: list):
    """Id and time of every row outside the bulk groups, read from the index alone.

    All rows of a bulk group lie inside its time range. Between those ranges every row is individual; inside a range,
    a row is individual when its key matches none of the bulk groups of that range. So no row is compared with the
    whole list of groups.
    """
    segments: list[dict] = []
    for group in sorted(bulk, key=lambda item: item["first"]):
        if segments and group["first"] <= segments[-1]["last"]:
            segments[-1]["last"] = max(segments[-1]["last"], group["last"])
            segments[-1]["groups"].append(group)
        else:
            segments.append({"first": group["first"], "last": group["last"], "groups": [group]})
    at, columns = ReviewEvent.occurred_at, (ReviewEvent.id, ReviewEvent.occurred_at)
    parts, lower = [], at >= start
    for segment in segments:
        parts.append(select(*columns).where(lower, at < segment["first"], *filters))
        same_key = [and_(ReviewEvent.source == g["source"], ACTOR == g["actor"],
                         ReviewEvent.evidence_type == g["evidence_type"], ReviewEvent.title == g["title"])
                    for g in segment["groups"]]
        parts.append(select(*columns).where(at >= segment["first"], at <= segment["last"], not_(or_(*same_key)),
                                            *filters))
        lower = at > segment["last"]
    parts.append(select(*columns).where(lower, at < end, *filters))
    return (union_all(*parts) if len(parts) > 1 else parts[0]).subquery("individual")


def _samples(db: Session, groups: list[dict]) -> dict[tuple, ReviewEvent]:
    """One stored row per bulk group (its last one): what kind of item changed and with which tool."""
    key = (DAY, ReviewEvent.source, ACTOR, ReviewEvent.evidence_type, ReviewEvent.title)
    found: dict[tuple, object] = {}
    for row in db.execute(select(ReviewEvent.id, *key).where(
            ReviewEvent.occurred_at.in_(sorted({group["last"] for group in groups})))):
        found.setdefault(tuple(row[1:]), row[0])
    events = {event.id: event for event in db.scalars(
        select(ReviewEvent).where(ReviewEvent.id.in_(list(found.values()))))} if found else {}
    return {group_key: events[event_id] for group_key, event_id in found.items() if event_id in events}


def _group_key(group: dict) -> tuple:
    return group["day"], group["source"], group["actor"], group["evidence_type"], group["title"]


def change_history(db: Session, date_from: date, date_to: date, *, source: str | None = None,
                   actor: str | None = None, q: str | None = None, include_bulk: bool = False,
                   offset: int = 0, limit: int = 200) -> dict:
    if date_to < date_from or (date_to - date_from).days >= MAX_DAYS:
        raise ValueError(f"The window must contain between 1 and {MAX_DAYS} days.")
    start, end = window_bounds(date_from, date_to)
    wanted_actor = None if actor is None else "" if actor == NO_ACTOR else actor
    groups = _groups(db, start, end)
    bulk = [group for group in groups if group["bulk"]]

    # Totals of the whole window, before filters: they also fill the platform and person filters.
    by_source: dict[str, dict] = {}
    by_actor: dict[str, dict] = {}
    for group in groups:
        kind = "bulk" if group["bulk"] else "individual"
        for bucket, name in ((by_source, group["source"]), (by_actor, group["actor"])):
            total = bucket.setdefault(name, {"count": 0, "individual": 0, "bulk": 0, "sources": set()})
            total["count"] += group["count"]
            total[kind] += group["count"]
            total["sources"].add(group["source"])

    def ranked(bucket: dict, field: str) -> list[dict]:
        rows = [{field: name or None, "count": value["count"], "individual": value["individual"],
                 "bulk": value["bulk"], **({"sources": sorted(value["sources"])} if field == "actor" else {})}
                for name, value in bucket.items()]
        return sorted(rows, key=lambda item: (-item["count"], item[field] or ""))

    def selected(group: dict) -> bool:
        return (not source or group["source"] == source) and (wanted_actor is None or group["actor"] == wanted_actor)

    # Individual changes: newest first, paginated.
    filters = []
    if source:
        filters.append(ReviewEvent.source == source)
    if wanted_actor is not None:
        filters.append(ACTOR == wanted_actor)
    candidates = _individual(start, end, bulk, filters)
    if q:
        # Only the individual candidates are read in full for the text search, never the bulk rows.
        search = _search(db, q)
        rows = db.execute(select(candidates.c.id)).scalars().all()
        matched = []
        for index in range(0, len(rows), 5000):
            chunk = bindparam(f"ids_{index}", rows[index:index + 5000], type_=ARRAY(PG_UUID(as_uuid=True)))
            matched += db.execute(select(ReviewEvent.id, ReviewEvent.occurred_at)
                                  .where(ReviewEvent.id == any_(chunk), search)).all()
        matched.sort(key=lambda row: (row.occurred_at, row.id), reverse=True)
        individual_total, ids = len(matched), [row.id for row in matched[offset:offset + limit]]
    else:
        individual_total = sum(group["count"] for group in groups if not group["bulk"] and selected(group))
        ids = db.scalars(select(candidates.c.id).order_by(candidates.c.occurred_at.desc(), candidates.c.id.desc())
                         .offset(offset).limit(limit)).all()
    events = {event.id: event for event in db.scalars(select(ReviewEvent).where(ReviewEvent.id.in_(ids)))} if ids else {}
    page = [events[event_id] for event_id in ids]
    campaigns = _campaign_names(db, page)

    # Bulk groups: one folded line per day. A search matches their person, title and sample row.
    chosen = sorted((group for group in bulk if selected(group)), key=lambda g: (g["day"], g["last"]), reverse=True)
    samples = _samples(db, chosen[:MAX_BULK_GROUPS]) if chosen and (include_bulk or q) else {}
    if q:
        needle = _fold(q)

        def found(group: dict) -> bool:
            sample = samples.get(_group_key(group))
            payload = sample.payload if sample is not None and isinstance(sample.payload, dict) else {}
            values = [group["actor"], group["title"], _payload_text(payload, "change_resource_type")]
            if sample is not None:
                values += [sample.detail, sample.object_id]
            return any(needle in _fold(value) for value in values)

        chosen = [group for group in chosen[:MAX_BULK_GROUPS] if found(group)]
    bulk_rows = []
    for group in chosen[:MAX_BULK_GROUPS] if include_bulk else []:
        sample = samples.get(_group_key(group))
        payload = sample.payload if sample is not None and isinstance(sample.payload, dict) else {}
        bulk_rows.append({"day": group["day"].isoformat(), "source": group["source"], "actor": group["actor"] or None,
                          "evidence_type": group["evidence_type"], "title": group["title"], "count": group["count"],
                          "first": group["first"].isoformat(), "last": group["last"].isoformat(),
                          "sample": None if sample is None else {
                              "resource_type": _payload_text(payload, "change_resource_type"),
                              "client_type": _payload_text(payload, "client_type"),
                              "detail": sample.detail, "object_id": sample.object_id}})

    return {
        "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "timezone": TIMEZONE_NAME,
        "bulk_min_size": BULK_MIN_SIZE,
        "totals": {"changes": sum(g["count"] for g in groups),
                   "individual": sum(g["count"] for g in groups if not g["bulk"]),
                   "bulk": sum(g["count"] for g in bulk), "bulk_groups": len(bulk),
                   "by_source": ranked(by_source, "source"), "by_actor": ranked(by_actor, "actor")},
        "filtered": {"individual": individual_total, "bulk": sum(g["count"] for g in chosen),
                     "bulk_groups": len(chosen)},
        "bulk_groups": bulk_rows, "bulk_groups_truncated": include_bulk and len(chosen) > MAX_BULK_GROUPS,
        "changes": [serialize_change(event, campaigns) for event in page],
        "offset": offset, "limit": limit, "has_more": offset + len(page) < individual_total,
        "coverage": _coverage(db, date_from, date_to),
    }
