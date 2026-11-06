"""Proposals: ADVESTIQ publishes the content with its key, only the owner sets the status. Made-up data only."""
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_current_user
from app.api.routes import advestiq
from app.db.session import get_db
from app.models import User

KEY = "test-proposals-key-789"
CODES = {"P-901", "P-911", "P-912", "D-91"}


def proposal(**overrides):
    return {"title": "Μείωση προϋπολογισμού δοκιμαστικής καμπάνιας", "platform": "google_ads", "executor": "agency",
            "what": "Από 40 € σε 32 € την ημέρα.", "why": "Παράδειγμα για τα τεστ.", "expected": "Λιγότερα έξοδα.",
            "rollback": "Επαναφορά στα 40 €.", "check_7_on": "2026-11-13", "check_14_on": "2026-11-20",
            "message_subject": "Αλλαγή προϋπολογισμού", "message_body": "Καλησπέρα,\nθα ήθελα μια αλλαγή.\n",
            "created_on": "2026-11-06", "advestiq_status": "για συζήτηση", **overrides}


def client(db, user=None):
    application = FastAPI()
    application.include_router(advestiq.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    if user is not None:
        application.dependency_overrides[get_current_user] = lambda: user
    return TestClient(application)


def owner_client(db):
    return client(db, SimpleNamespace(id=uuid4(), is_admin=True, email="owner@example.com"))


def key_client(db, monkeypatch):
    monkeypatch.setattr(deps.settings, "advestiq_api_key_sha256", hashlib.sha256(KEY.encode()).hexdigest())
    http = client(db)  # the real get_current_user: the key header becomes the transient ADVESTIQ principal
    http.headers[deps.ADVESTIQ_KEY_HEADER] = KEY
    return http


def test_key_publishes_proposals_and_never_changes_the_owner_decision(db, monkeypatch):
    key, owner = key_client(db, monkeypatch), owner_client(db)
    created = key.put("/api/advestiq/proposals/P-901", json=proposal()).json()["data"]
    assert created["created"] and created["changed"] and created["status"] == "discussion"
    assert created["notes"] == [] and created["message_body"].startswith("Καλησπέρα")
    again = key.put("/api/advestiq/proposals/P-901", json=proposal()).json()["data"]
    assert again["created"] is False and again["changed"] is False

    decided = owner.patch("/api/advestiq/proposals/P-901/status",
                          json={"status": "approved", "note": "Εντάξει, να σταλεί."}).json()["data"]
    assert decided["status"] == "approved" and decided["status_changed_at"]
    assert [(n["author"], n["status"], n["text"]) for n in decided["notes"]] == [("owner", "approved", "Εντάξει, να σταλεί.")]

    note = key.post("/api/advestiq/proposals/P-901/notes", json={"text": "Έλεγχος 7 ημερών: εντός στόχου."})
    assert note.status_code == 200 and note.json()["data"]["author"] == "advestiq"
    updated = key.put("/api/advestiq/proposals/p-901", json=proposal(advestiq_status="ελέγχθηκε: εντός στόχου")).json()["data"]
    assert updated["code"] == "P-901" and updated["created"] is False and updated["changed"] is True
    assert updated["status"] == "approved" and updated["advestiq_status"] == "ελέγχθηκε: εντός στόχου"
    assert [n["author"] for n in updated["notes"]] == ["owner", "advestiq"]

    # The key can never decide: no status route, no status field, no owner notes.
    assert key.patch("/api/advestiq/proposals/P-901/status", json={"status": "done"}).status_code == 403
    assert key.put("/api/advestiq/proposals/P-901", json=proposal(status="done")).status_code == 422
    assert key.post("/api/advestiq/proposals/P-901/notes", json={"text": "Έγινε", "author": "owner"}).status_code == 403
    final = key.get("/api/advestiq/proposals/P-901").json()["data"]
    assert final["status"] == "approved" and len(final["notes"]) == 2


def test_status_route_refuses_the_key_principal_even_without_the_path_rule(db):
    principal = User(email=deps.ADVESTIQ_EMAIL, hashed_password="!", is_admin=True, is_active=True)
    http = client(db, principal)
    assert http.put("/api/advestiq/proposals/P-901", json=proposal()).status_code == 200
    assert http.patch("/api/advestiq/proposals/P-901/status", json={"status": "done"}).status_code == 403
    assert http.post("/api/advestiq/proposals/P-901/notes", json={"text": "x", "author": "owner"}).status_code == 403
    assert http.post("/api/advestiq/proposals/P-901/notes", json={"text": "Σημείωση"}).json()["data"]["author"] == "advestiq"
    assert http.get("/api/advestiq/proposals/P-901").json()["data"]["status"] == "discussion"


def test_owner_notes_and_status_history_stay_in_time_order(db):
    owner = owner_client(db)
    owner.put("/api/advestiq/proposals/P-901", json=proposal())
    assert owner.post("/api/advestiq/proposals/P-901/notes", json={"text": "Θα το δω αύριο.", "author": "advestiq"}).status_code == 403
    assert owner.post("/api/advestiq/proposals/P-901/notes", json={"text": "   "}).status_code == 422
    owner.post("/api/advestiq/proposals/P-901/notes", json={"text": "Θα το δω αύριο."})
    owner.patch("/api/advestiq/proposals/P-901/status", json={"status": "sent"})
    same = owner.patch("/api/advestiq/proposals/P-901/status", json={"status": "sent"}).json()["data"]
    assert len(same["notes"]) == 2  # the same status again adds nothing
    commented = owner.patch("/api/advestiq/proposals/P-901/status", json={"status": "sent", "note": "Το έστειλα."}).json()["data"]
    done = owner.patch("/api/advestiq/proposals/P-901/status", json={"status": "done", "note": "Το έκαναν."}).json()["data"]
    assert [(n["text"], n["status"]) for n in done["notes"]] == [
        ("Θα το δω αύριο.", None), ("", "sent"), ("Το έστειλα.", None), ("Το έκαναν.", "done")]
    assert [n["author"] for n in done["notes"]] == ["owner"] * 4
    assert commented["status"] == "sent" and done["status"] == "done"
    assert done["status_changed_at"] >= commented["status_changed_at"]


def test_proposal_list_shows_open_first_and_filters(db):
    owner = owner_client(db)
    for code, created_on, platform in (("P-911", "2026-11-01", "google_ads"), ("P-912", "2026-11-03", "meta_ads"),
                                       ("D-91", "2026-11-02", "tracking")):
        assert owner.put(f"/api/advestiq/proposals/{code}",
                         json=proposal(created_on=created_on, platform=platform)).status_code == 200
    owner.patch("/api/advestiq/proposals/P-912/status", json={"status": "done"})
    owner.post("/api/advestiq/proposals/P-911/notes", json={"text": "Σχόλιο"})

    def codes(query=""):
        body = owner.get(f"/api/advestiq/proposals{query}").json()["data"]
        return [row["code"] for row in body["rows"] if row["code"] in CODES], body

    listed, body = codes()
    assert listed == ["D-91", "P-911", "P-912"]  # open ones first, newest first; done last
    row = next(r for r in body["rows"] if r["code"] == "P-911")
    assert row["notes_count"] == 1 and row["last_note_at"] and "message_body" not in row
    assert body["counts"]["done"] >= 1 and set(body["counts"]) == {"discussion", "approved", "sent", "done",
                                                                    "not_done", "rejected"}
    assert codes("?status=open")[0] == ["D-91", "P-911"]
    assert codes("?status=closed")[0] == ["P-912"]
    assert codes("?status=done")[0] == ["P-912"]
    assert codes("?platform=meta_ads")[0] == ["P-912"]
    full = owner.get("/api/advestiq/proposals?full=true").json()["data"]["rows"]
    assert all("message_body" in r and "notes" in r for r in full)
    assert next(r for r in full if r["code"] == "P-911")["notes"][0]["text"] == "Σχόλιο"
    assert owner.get("/api/advestiq/proposals?status=unknown").status_code == 422
    assert owner.get("/api/advestiq/proposals?platform=myspace").status_code == 422


def test_proposal_validation_and_missing_codes(db):
    owner = owner_client(db)
    assert owner.put("/api/advestiq/proposals/P_1", json=proposal()).status_code == 422
    assert owner.put("/api/advestiq/proposals/PROPOSAL-1", json=proposal()).status_code == 422
    assert owner.put("/api/advestiq/proposals/P-1", json=proposal(platform="myspace")).status_code == 422
    assert owner.put("/api/advestiq/proposals/P-1", json=proposal(executor="unknown")).status_code == 422
    assert owner.put("/api/advestiq/proposals/P-1", json=proposal(title="")).status_code == 422
    assert owner.put("/api/advestiq/proposals/P-1", json={"title": "Χωρίς ημερομηνία", "platform": "site",
                                                          "executor": "site"}).status_code == 422
    minimal = owner.put("/api/advestiq/proposals/P-1", json={"title": "Ελάχιστη", "platform": "other", "executor": "owner",
                                                             "created_on": "2026-11-06"}).json()["data"]
    assert minimal["what"] == "" and minimal["check_7_on"] is None and minimal["message_subject"] == ""
    assert owner.get("/api/advestiq/proposals/P-404").status_code == 404
    assert owner.post("/api/advestiq/proposals/P-404/notes", json={"text": "x"}).status_code == 404
    assert owner.patch("/api/advestiq/proposals/P-404/status", json={"status": "done"}).status_code == 404
    assert owner.patch("/api/advestiq/proposals/P-1/status", json={"status": "finished"}).status_code == 422
