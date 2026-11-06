"""GET /api/business-review/changes: bulk groups per Athens day, individual changes, totals. Made-up data only."""
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_current_user
from app.api.routes import business_review
from app.db.session import get_db
from app.models import CampaignDailyMetric, ReviewEvent, ReviewJob
from app.services.business_review_jobs import clip_bytes

ATHENS = ZoneInfo("Europe/Athens")
BOT = "feed-bot@example.com"
MANAGER = "manager@example.com"


def at(day, hour, minute, second=0):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=ATHENS)


def event(db, occurred_at, *, source="google_ads", actor=MANAGER, title="UPDATE", detail="", object_id=None,
          payload=None, evidence_type="api"):
    db.add(ReviewEvent(source_key=uuid4().hex, source=source, occurred_at=occurred_at, evidence_type=evidence_type,
                       actor=actor, title=title, detail=detail, object_id=object_id, payload=payload or {}))


def seed(db):
    # Nightly feed uploads: 60 asset creations on 4/11 and 55 on 5/11, between 04:39 and 04:53 Athens time.
    for day, count in ((4, 60), (5, 55)):
        for index in range(count):
            event(db, at(day, 4, 39 + index * 14 // count, index % 60), actor=BOT, title="CREATE", detail="asset",
                  object_id=f"customers/1/assets/{day}{index}",
                  payload={"change_resource_type": "ASSET", "client_type": "GOOGLE_ADS_API"})
    # 49 identical rows stay individual: below the 50-row bulk size.
    for index in range(49):
        event(db, at(3, 10, index), actor="editor@example.com", title="UPDATE", detail="keyword")
    event(db, at(5, 11, 15), title="UPDATE", detail="amount_micros", object_id="customers/1/campaigns/111",
          payload={"change_resource_type": "CAMPAIGN_BUDGET", "client_type": "GOOGLE_ADS_WEB_CLIENT",
                   "old_resource": {"campaign_budget": {"amount_micros": "40000000"}},
                   "new_resource": {"campaign_budget": {"amount_micros": "32000000"}}})
    event(db, at(5, 12, 0), source="meta_ads", actor="Μαρία Π.", title="update_ad_set_budget", detail="Δοκιμαστικό σύνολο")
    event(db, at(5, 13, 0), actor=None, title="UPDATE", detail="status")
    # Athens midnight, not UTC: 23:30 on 5/11 and 00:10 on 6/11 belong to different days.
    event(db, at(5, 23, 30), title="UPDATE", detail="late change")
    event(db, at(6, 0, 10), title="UPDATE", detail="early change")
    db.add(CampaignDailyMetric(source="google_ads", metric_date=date(2026, 11, 5), campaign_id="111",
                               campaign_name="Δοκιμαστική καμπάνια επίπλων"))
    db.add(ReviewJob(provider="google_ads", kind="changes", date_from=date(2026, 11, 2), date_to=date(2026, 11, 5),
                     status="success", records=0, attempts=1, meta={}, finished_at=at(5, 14, 0)))
    db.add(ReviewJob(provider="meta_ads", kind="changes", date_from=date(2026, 11, 6), date_to=date(2026, 11, 6),
                     status="failed", records=0, attempts=1, meta={}, error="secret details stay hidden"))
    db.flush()


def http_client(db):
    application = FastAPI()
    application.include_router(business_review.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4(), is_admin=True)
    return TestClient(application)


def changes(http, date_from="2026-11-03", date_to="2026-11-06", **params):
    response = http.get("/api/business-review/changes", params={"date_from": date_from, "date_to": date_to, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_bulk_changes_fold_per_day_and_individual_changes_stay_listed(db):
    seed(db)
    with http_client(db) as http:
        body = changes(http)
        totals = body["totals"]
        assert totals["changes"] == 60 + 55 + 49 + 5 and totals["bulk"] == 115 and totals["bulk_groups"] == 2
        assert totals["individual"] == 54
        google = next(row for row in totals["by_source"] if row["source"] == "google_ads")
        assert google == {"source": "google_ads", "count": 168, "individual": 53, "bulk": 115}
        bot = next(row for row in totals["by_actor"] if row["actor"] == BOT)
        assert bot["bulk"] == 115 and bot["individual"] == 0 and bot["sources"] == ["google_ads"]
        assert any(row["actor"] is None for row in totals["by_actor"])

        # Bulk rows are hidden by default, the others are listed newest first.
        assert body["bulk_groups"] == [] and body["filtered"] == {"individual": 54, "bulk": 115, "bulk_groups": 2}
        listed = body["changes"]
        assert len(listed) == 54 and all(row["actor"] != BOT for row in listed)
        assert [row["occurred_at"] for row in listed] == sorted((row["occurred_at"] for row in listed), reverse=True)
        assert (listed[0]["detail"], listed[0]["day"]) == ("early change", "2026-11-06")
        assert (listed[1]["detail"], listed[1]["day"]) == ("late change", "2026-11-05")
        budget = next(row for row in listed if row["detail"] == "amount_micros")
        assert budget["campaign"] == "Δοκιμαστική καμπάνια επίπλων" and budget["resource_type"] == "CAMPAIGN_BUDGET"
        assert budget["client_type"] == "GOOGLE_ADS_WEB_CLIENT" and budget["payload"]["new_resource"]
        assert body["has_more"] is False and body["timezone"] == "Europe/Athens"

        shown = changes(http, include_bulk="true")["bulk_groups"]
        assert [(g["day"], g["count"]) for g in shown] == [("2026-11-05", 55), ("2026-11-04", 60)]
        assert shown[0]["actor"] == BOT and shown[0]["title"] == "CREATE" and shown[0]["evidence_type"] == "api"
        first, last = (datetime.fromisoformat(shown[0][key]).astimezone(ATHENS) for key in ("first", "last"))
        assert (first.hour, first.minute) == (4, 39) and (last.hour, last.minute) == (4, 52)
        assert shown[0]["sample"]["resource_type"] == "ASSET" and shown[0]["sample"]["client_type"] == "GOOGLE_ADS_API"


def test_filters_search_and_pagination(db):
    seed(db)
    with http_client(db) as http:
        meta = changes(http, source="meta_ads")
        assert [row["source"] for row in meta["changes"]] == ["meta_ads"]
        assert meta["totals"]["changes"] == 169  # totals cover the window before filters
        assert meta["filtered"] == {"individual": 1, "bulk": 0, "bulk_groups": 0}
        assert {row["detail"] for row in changes(http, actor=MANAGER)["changes"]} == {
            "amount_micros", "late change", "early change"}
        assert [row["detail"] for row in changes(http, actor="__none__")["changes"]] == ["status"]
        bot = changes(http, actor=BOT, include_bulk="true")
        assert bot["changes"] == [] and len(bot["bulk_groups"]) == 2

        # Search covers title, detail, actor and the Google campaign names known from the daily metrics,
        # without Greek accents or capitals.
        assert [row["detail"] for row in changes(http, q="AMOUNT_micros")["changes"]] == ["amount_micros"]
        assert [row["detail"] for row in changes(http, q="ΚΑΜΠΑΝΙΑ επιπλων")["changes"]] == ["amount_micros"]
        assert [row["actor"] for row in changes(http, q="μαρια")["changes"]] == ["Μαρία Π."]
        assert changes(http, q="100%")["changes"] == []  # LIKE wildcards are literal
        # A search matches bulk groups on their person, title and sample row, never on all their rows.
        assets = changes(http, q="asset", include_bulk="true")
        assert assets["changes"] == [] and [g["count"] for g in assets["bulk_groups"]] == [55, 60]
        assert assets["filtered"] == {"individual": 0, "bulk": 115, "bulk_groups": 2}
        assert changes(http, q="feed-bot")["filtered"]["bulk_groups"] == 2
        assert changes(http, q="keyword")["filtered"] == {"individual": 49, "bulk": 0, "bulk_groups": 0}
        searched = changes(http, q="keyword", limit=20, offset=40)
        assert len(searched["changes"]) == 9 and searched["has_more"] is False

        page = changes(http, limit=20, offset=0)
        rest = changes(http, limit=20, offset=40)
        assert len(page["changes"]) == 20 and page["has_more"] is True
        assert len(rest["changes"]) == 14 and rest["has_more"] is False
        ids = {row["id"] for row in page["changes"]} | {row["id"] for row in changes(http, limit=20, offset=20)["changes"]}
        assert len(ids | {row["id"] for row in rest["changes"]}) == 54


def test_changes_made_during_a_bulk_upload_stay_listed(db):
    # Two bulk groups overlap in time (creations and removals by the same robot), with manual changes between them.
    for index in range(50):
        event(db, at(10, 4, 0, index), actor=BOT, title="CREATE", detail="asset")
        event(db, at(10, 4, 0, 30 + index % 30), actor=BOT, title="REMOVE", detail="asset")
    event(db, at(10, 4, 0, 20), actor=MANAGER, title="CREATE", detail="manual inside")  # same time, other person
    event(db, at(10, 4, 0, 40), actor=BOT, title="UPDATE", detail="robot update")  # same person, other title
    event(db, at(10, 4, 0, 0), source="meta_ads", actor=BOT, title="CREATE", detail="other platform")  # first second
    event(db, at(10, 4, 0, 59), actor=BOT, title="CREATE", evidence_type="manual", detail="other type")  # last second
    event(db, at(11, 4, 0, 10), actor=BOT, title="CREATE", detail="next day, below 50")
    event(db, at(10, 0, 0, 0), title="UPDATE", detail="midnight")  # exactly at the window start
    db.flush()
    with http_client(db) as http:
        body = changes(http, date_from="2026-11-10", date_to="2026-11-11", include_bulk="true")
        assert {row["detail"] for row in body["changes"]} == {
            "manual inside", "robot update", "other platform", "other type", "next day, below 50", "midnight"}
        assert body["filtered"] == {"individual": 6, "bulk": 100, "bulk_groups": 2}
        assert sorted(g["title"] for g in body["bulk_groups"]) == ["CREATE", "REMOVE"]
        only_bot = changes(http, date_from="2026-11-10", date_to="2026-11-11", actor=BOT)
        assert {row["detail"] for row in only_bot["changes"]} == {"robot update", "other platform", "other type",
                                                                   "next day, below 50"}


def test_window_validation_and_coverage(db):
    seed(db)
    with http_client(db) as http:
        bad = http.get("/api/business-review/changes?date_from=2026-11-06&date_to=2026-11-05")
        assert bad.status_code == 400
        assert http.get("/api/business-review/changes?date_from=2026-08-04&date_to=2026-11-05").status_code == 400
        assert http.get("/api/business-review/changes?date_from=2026-08-05&date_to=2026-11-05").status_code == 200
        assert http.get("/api/business-review/changes?date_from=2026-11-01&date_to=2026-11-06&limit=0").status_code == 422
        coverage = {row["source"]: row for row in changes(http)["coverage"]}
        assert coverage["google_ads"]["days_requested"] == 4 and coverage["google_ads"]["days_covered"] == 3
        assert coverage["google_ads"]["last_fetched_at"].startswith("2026-11-05")
        assert coverage["meta_ads"]["days_covered"] == 0 and coverage["meta_ads"]["days_failed"] == 1
        assert "secret" not in str(coverage)
        empty = changes(http, date_from="2026-10-01", date_to="2026-10-02")
        assert empty["totals"]["changes"] == 0 and empty["changes"] == [] and empty["has_more"] is False


def test_change_index_covers_the_grouping_columns(db):
    definition = db.scalar(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_review_events_changes'"))
    assert "(occurred_at, id) INCLUDE (source, actor, evidence_type, title)" in definition


def test_long_titles_and_actors_are_clipped_to_fit_the_index():
    assert clip_bytes("UPDATE", 1000) == "UPDATE" and clip_bytes(None, 500) is None
    clipped = clip_bytes("😀" * 400, 1000)
    assert len(clipped.encode("utf-8")) <= 1000 and clipped == "😀" * 250
    assert clip_bytes("α" * 300, 500) == "α" * 250
