import io
import json
import shutil
import subprocess
from html import escape

import httpx
import pytest
from PIL import Image, ImageChops, ImageStat

from app.api.routes import promotions
from app.models import PromotionAsset
from app.services import promotion_render as render
from app.services import promotion_render_jobs as jobs
from app.services.promotion_creative import FPS, timeline
from app.services.promotion_service import END_CARD, FORMATS, end_card
from test_promotions import client, parameters, product, user

PHOTO = "https://inde.gr/image/catalog/chair.jpg"
PHOTO_TWO = "https://inde.gr/image/catalog/chair-in-room.jpg"


def offer_html(price="19.50", sku="SKU-1", **overrides):
    offer = {"@type": "Offer", "price": price, "priceCurrency": "EUR",
             "availability": "https://schema.org/InStock", **overrides}
    doc = {"@graph": [{"@type": "Product", "sku": sku, "image": PHOTO, "offers": offer}]}
    return f'<script type="application/ld+json">{json.dumps(doc)}</script>'.encode()


def storefront(price="19.50"):
    return httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=offer_html(price))))


def gallery_storefront():
    urls = [PHOTO, PHOTO_TWO, PHOTO, "https://other.test/image/unknown.jpg"]
    data = escape(json.dumps([{"src": url} for url in urls]), quote=True)
    body = offer_html() + f'<div class="lightgallery lightgallery-product-images" data-images="{data}"></div>'.encode()
    return httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)))


@pytest.mark.parametrize("body", [
    offer_html(sku="wrong"),
    offer_html(price="-1"),
    offer_html(price="NaN"),
    offer_html(price="19.504"),
    offer_html(priceCurrency="USD"),
    offer_html(availability="https://schema.org/OutOfStock"),
    offer_html(priceSpecification={"valueAddedTaxIncluded": False}),
    offer_html() + offer_html("29.50"),
])
def test_unverifiable_prices_are_not_rendered(body):
    with pytest.raises(render.RenderError):
        render.product_offer(body, "SKU-1")


def test_confirmed_price_is_from_the_storefront():
    value, image = render.product_offer(offer_html(), "SKU-1")
    assert render.price_text(value) == "19,50 \u20ac"
    assert image == PHOTO


@pytest.mark.parametrize("redirect", ["http://inde.gr/product", "https://inde.gr:8443/product",
                                      "https://inde.gr.evil.test/product", "https://127.0.0.1/"])
def test_storefront_redirects_cannot_leave_public_inde(redirect):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": redirect})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(render.RenderError):
            render.read_inde(http, "https://inde.gr/product")
    assert len(requests) == 1


def make_campaign(http, p):
    return http.post("/api/promotions/campaigns", json=parameters(p.id, formats=["9:16"]).model_dump(mode="json")).json()["id"]


def test_queue_owner_and_price_changes(db, tmp_path, monkeypatch):
    person, other, p = user(db), user(db), product(db)
    monkeypatch.setattr(promotions, "inde_client", storefront)
    monkeypatch.setattr(jobs, "inde_client", lambda: storefront("21.00"))
    monkeypatch.setattr(jobs.settings, "promotion_media_dir", str(tmp_path))
    monkeypatch.setattr(jobs, "render_video", lambda *args: pytest.fail("Price changed: must not encode"))
    with client(db, person) as http:
        campaign = make_campaign(http, p)
        base = f"/api/promotions/campaigns/{campaign}"
        assert http.get("/api/promotions/end-card").content == END_CARD.read_bytes()
        quote = http.get(f"{base}/render-prices").json()
        assert quote["rows"][0]["price_gross"] == "19.50"  # The catalog fixture is 124.
        body = {"aspect_ratio": "9:16", "prices": {p.sku: "19.50"}}
        assert http.post(f"{base}/render", json={**body, "prices": {"wrong": "19.50"}}).status_code == 422
        queued = http.post(f"{base}/render", json=body)
        assert queued.status_code == 202 and queued.json()["render"]["status"] == "queued"
        assert http.post(f"{base}/render", json=body).status_code == 409
    with client(db, other) as http:
        assert http.get(f"{base}/render-prices").status_code == 404
        assert http.post(f"{base}/render", json=body).status_code == 404
    jobs._process_locked(db)
    with client(db, person) as http:
        row = http.get(base).json()
    assert row["render"]["status"] == "failed"
    assert not row["assets"] and not list(tmp_path.iterdir())


def test_completed_render_becomes_private_reviewable_asset(db, tmp_path, monkeypatch):
    person, p = user(db), product(db)
    monkeypatch.setattr(jobs.settings, "promotion_media_dir", str(tmp_path))
    monkeypatch.setattr(jobs, "inde_client", gallery_storefront)
    monkeypatch.setattr(promotions, "inde_client", gallery_storefront)

    def encode(_, brief, products, ratio, folder):
        assert products[0]["price_gross"] == "19.50"
        assert products[0]["selected_images"] == [PHOTO_TWO, PHOTO]
        target = folder / "render.mp4"
        target.write_bytes(b"\x00\x00\x00\x20ftypisom")
        return target

    monkeypatch.setattr(jobs, "render_video", encode)
    with client(db, person) as http:
        base = f"/api/promotions/campaigns/{make_campaign(http, p)}"
        quote = http.get(f"{base}/render-prices").json()
        assert quote["rows"][0]["gallery"] == [PHOTO, PHOTO_TWO]
        body = {"aspect_ratio": "9:16", "prices": {p.sku: "19.50"}}
        for photos in ([PHOTO, PHOTO], ["https://external.test/image/chair.jpg"]):
            assert http.post(f"{base}/render", json={**body, "photo_selections": {p.sku: photos}}).status_code == 422
        unknown = "https://inde.gr/image/catalog/different-product.jpg"
        assert http.post(f"{base}/render", json={**body, "photo_selections": {p.sku: [unknown]}}).status_code == 202
        jobs._process_locked(db)
        assert http.get(base).json()["render"]["status"] == "failed"
        queued = http.post(f"{base}/render", json={**body, "photo_selections": {p.sku: [PHOTO_TWO, PHOTO]}}).json()
        jobs._process_locked(db)
        row = http.get(base).json()
        assert row["render"]["status"] == "success"
        assert row["status"] == "needs_review"
        asset_id = queued["render"]["id"]
        assert row["assets"][0]["id"] == asset_id
        assert http.get(f"/api/promotions/assets/{asset_id}/content").content.endswith(b"ftypisom")
        assert db.query(PromotionAsset).count() == 1


@pytest.mark.parametrize("duration", [15, 30])
@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("style", ["cinematic", "editorial", "detail"])
def test_creative_timeline_preserves_each_product_and_end_card(duration, count, style):
    beats = timeline(duration, count, style)
    assert sum(beat.frames for beat in beats) == duration * FPS
    assert beats[0].kind == "hook" and beats[0].frames == 45
    assert beats[-2].kind == "cta"
    assert beats[-1].kind == "end" and beats[-1].frames == 3 * FPS
    assert list(dict.fromkeys(beat.product for beat in beats if beat.kind == "product")) == list(range(count))
    assert all(beat.frames >= FPS for beat in beats)


def test_two_selected_photos_fit_even_the_short_editorial_cut():
    beats = timeline(15, 3, "editorial", [2, 2, 1])
    for product in (0, 1):
        assert [beat.photo for beat in beats if beat.kind in {"product", "detail"} and beat.product == product] == [0, 1]


@pytest.mark.parametrize("ratio,duration,count", [("9:16", 15, 3), ("1:1", 15, 2), ("16:9", 30, 1)])
def test_ffmpeg_renders_full_product_video_and_final_card(ratio, duration, count, tmp_path, monkeypatch):
    ffmpeg = shutil.which(render.settings.promotion_ffmpeg_path)
    if not ffmpeg:
        pytest.skip("Install FFmpeg or set PROMOTION_FFMPEG_PATH.")
    monkeypatch.setattr(render, "product_photo", lambda *_: Image.new("RGB", (240, 450), "#c09060"))
    products = [{"name": "INDE floor lamp", "price_gross": "19.50", "image_url": PHOTO}] * count
    brief = {"parameters": {"duration": duration, "cta": "inde.gr", "hook": "INDE", "style": "cinematic"}}
    path = render.render_video(None, brief, products, ratio, tmp_path)
    subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-t", "0.5", "-f", "null", "-"],
                   check=True, capture_output=True)
    stats = subprocess.check_output([ffmpeg, "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(path),
                                     "-map", "0:v:0", "-f", "null", "-"], text=True)
    assert f"frame={duration * FPS}\n" in stats
    expected = end_card(ratio)
    for time in (duration - 3, duration - 0.04):
        frame = subprocess.check_output([ffmpeg, "-v", "error", "-ss", str(time), "-i", str(path),
                                         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"])
        with Image.open(io.BytesIO(frame)) as decoded:
            assert decoded.size == (FORMATS[ratio]["width"], FORMATS[ratio]["height"])
            assert max(ImageStat.Stat(ImageChops.difference(expected, decoded.convert("RGB"))).mean) < 4
