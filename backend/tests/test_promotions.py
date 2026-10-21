import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import inspect, select

from app.api.deps import get_current_user
from app.api.routes import promotions
from app.db.session import get_db
from app.models import Base, ProductCatalog, PromotionAsset, PromotionCampaign, User
from app.schemas.promotions import PromotionInput
from app.services import promotion_service


def product(db, sku="SKU-1", **options):
    p = ProductCatalog(sku=sku, name=f"Πολυθρόνα {sku}", quantity=10, price=Decimal("124"),
        image_url="https://www.inde.gr/image/catalog/chair.jpg",
        link="https://inde.gr/index.php?route=product/product&product_id=123", **options)
    db.add(p)
    db.flush()
    return p


def parameters(*ids, **options):
    return PromotionInput(title="INDE collection", product_ids=list(ids), date_from=date(2026, 10, 1),
                          date_to=date(2026, 10, 20), **options)


def user(db):
    row = User(email=f"{uuid4()}@example.test", hashed_password="test-only", is_admin=True)
    db.add(row)
    db.flush()
    return row


def client(db, person):
    app = FastAPI()
    app.include_router(promotions.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    if person is not None:
        app.dependency_overrides[get_current_user] = lambda: person
    return TestClient(app)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://inde.gr/p", "https://inde.gr.evil.test/p",
    "https://user:password@inde.gr/p", "https://inde.gr/p?access_token=secret", "https://[broken"])
def test_destination_links_are_restricted_to_public_inde_pages(url):
    assert promotion_service.store_link(url) is None


def test_tracking_links_preserve_product_identity_and_replace_tracking():
    url = "https://inde.gr/index.php?route=product/product&product_id=123&utm_source=old"
    result = promotion_service.tracking_url(url, "tiktok", "inde-test")
    assert "product_id=123" in result and "utm_source=tiktok" in result and "old" not in result


@pytest.mark.parametrize("override", [{"product_ids": []}, {"product_ids": [uuid4()] * 2},
    {"formats": []}, {"formats": ["9:16", "9:16"]}, {"style": "invented"},
    {"date_from": "2026-10-21"}, {"title": " "}])
def test_invalid_campaign_parameters_are_rejected(override):
    body = parameters(uuid4()).model_dump(mode="json")
    body.update(override)
    with pytest.raises(ValidationError):
        PromotionInput.model_validate(body)


@pytest.mark.parametrize("count,duration", [(1, 15), (2, 15), (3, 15), (2, 30), (3, 30)])
def test_storyboard_duration_and_product_fidelity(db, count, duration):
    products = [product(db, f"SKU-{n}") for n in range(count)]
    brief = promotion_service.make_brief(db, parameters(*(p.id for p in products), duration=duration))
    assert brief["provider_mode"] == "higgsfield_subscription"
    for variant in brief["variants"]:
        assert sum(shot["seconds"] for shot in variant["shots"]) + variant["end_card_seconds"] == duration
        assert all("Preserve the exact product" in shot["prompt"] for shot in variant["shots"])
    assert "purchase_cost" not in json.dumps(brief)
    assert "access_token" not in json.dumps(brief)


def test_brief_rechecks_live_stock_before_save(db):
    p = product(db)
    p.quantity = 0
    db.flush()
    with pytest.raises(ValueError, match="διαθέσιμα"):
        promotion_service.make_brief(db, parameters(p.id))


def test_package_contains_exact_size_end_cards_and_no_generated_video(db):
    p = product(db)
    brief = promotion_service.make_brief(db, parameters(p.id))
    with zipfile.ZipFile(io.BytesIO(promotion_service.export_package(brief))) as archive:
        assert "brief.json" in archive.namelist() and "ad-links.txt" in archive.namelist()
        assert not any(name.endswith(".mp4") for name in archive.namelist())
        for ratio, dims in promotion_service.FORMATS.items():
            image = Image.open(io.BytesIO(archive.read(f"{ratio.replace(':','x')}/end-card.png")))
            assert image.size == (dims["width"], dims["height"])
        assert "does not publish" in archive.read("READ-ME.txt").decode()


def test_suggestions_use_sale_pack_cost_not_single_piece_cost(db, monkeypatch):
    p = product(db)
    monkeypatch.setattr(promotion_service, "product_performance", lambda *a: [{"sku": p.sku, "orders": 3, "quantity": 4}])
    monkeypatch.setattr(promotion_service, "latest_aade_costs", lambda *a: {("pak", p.id): (SimpleNamespace(
        net_unit_cost=Decimal("20"), purchase_date=date(2026, 10, 1)), "MARK")})
    monkeypatch.setattr(promotion_service, "catalog_sale_quantities", lambda *a: {("pak", p.id): Decimal(4)})
    monkeypatch.setattr(promotion_service, "pricing_settings", lambda *a: {"sale_vat_rate": 24})
    result = promotion_service.candidates(db, date(2026, 10, 1), date(2026, 10, 20))
    assert result["rows"][0]["margin_percent"] == 20
    assert result["rows"][0]["orders"] == 3
    assert promotion_service.candidates(db, date(2026, 10, 1), date(2026, 10, 20), minimum_margin=21)["rows"] == []
    monkeypatch.setattr(promotion_service, "catalog_sale_quantities", lambda *a: {})
    assert promotion_service.candidates(db, date(2026, 10, 1), date(2026, 10, 20))["rows"] == []


def test_campaign_creation_owner_auth_upload_and_review(db, tmp_path, monkeypatch):
    person, other, p = user(db), user(db), product(db)
    monkeypatch.setattr(promotions.settings, "promotion_media_dir", str(tmp_path))
    with client(db, None) as http:
        assert http.get("/api/promotions/campaigns").status_code == 401
    with client(db, SimpleNamespace(id=person.id, is_admin=False)) as http:
        assert http.get("/api/promotions/campaigns").status_code == 403
    with client(db, person) as http:
        response = http.post("/api/promotions/campaigns", json=parameters(p.id, formats=["9:16"]).model_dump(mode="json"))
        assert response.status_code == 201
        campaign_id = response.json()["id"]
        assert http.get(f"/api/promotions/campaigns/{campaign_id}/package").status_code == 200
        assert http.post(f"/api/promotions/campaigns/{campaign_id}/assets", data={"aspect_ratio": "9:16"},
            files={"file": ("evil.mp4", b"<html>not an mp4", "video/mp4")}).status_code == 422
        assert not list(tmp_path.iterdir())
        # Container signature only; content remains subject to explicit playback/identity review.
        video = b"\x00\x00\x00\x20ftypisom" + b"0" * 100
        response = http.post(f"/api/promotions/campaigns/{campaign_id}/assets", data={"aspect_ratio": "9:16"},
            files={"file": ("video.mp4", video, "video/mp4")})
        assert response.status_code == 201
        asset_id = response.json()["assets"][0]["id"]
        assert response.json()["status"] == "needs_review"
        assert http.get(f"/api/promotions/assets/{asset_id}/content").content == video
        assert http.post(f"/api/promotions/assets/{asset_id}/approve", json={"product_identity": True}).status_code == 422
        review = {"product_identity": True, "cta_and_text": True, "image_and_audio_rights": True, "platform_format": True}
        assert http.post(f"/api/promotions/assets/{asset_id}/approve", json=review).json()["status"] == "approved"
        again = http.post(f"/api/promotions/campaigns/{campaign_id}/assets", data={"aspect_ratio": "9:16"},
            files={"file": ("renamed.mp4", video, "video/mp4")})
        assert len(again.json()["assets"]) == 1
    with client(db, other) as http:
        assert http.get(f"/api/promotions/campaigns/{campaign_id}").status_code == 404
        assert http.get(f"/api/promotions/assets/{asset_id}/content").status_code == 404
        assert http.get(f"/api/promotions/campaigns/{campaign_id}/package").status_code == 404
        assert http.post(f"/api/promotions/assets/{asset_id}/approve", json=review).status_code == 404
        assert http.get("/api/promotions/campaigns").json()["rows"] == []


def test_promotion_migration_matches_models(db):
    inspector = inspect(db.get_bind())
    for name in ("promotion_campaigns", "promotion_assets"):
        table = Base.metadata.tables[name]
        columns = {c["name"]: c for c in inspector.get_columns(name)}
        assert set(columns) == set(table.columns.keys())
        assert all(columns[c.name]["nullable"] == c.nullable for c in table.columns)
