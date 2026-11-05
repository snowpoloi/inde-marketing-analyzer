"""Read public INDE offers and compose MP4s using local FFmpeg."""
import io
import json
import subprocess
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.services.promotion_creative import FPS, PLUM, STAMP_LAND, creative_frame, photo_capacity, price_text, soundtrack, timeline
from app.services.promotion_music import TRACKS, sync_cuts, track_path
from app.services.promotion_service import end_card

CENT = Decimal("0.01")
MAX_VIDEO_BYTES = 64 * 1024 * 1024
SCENES_PER_BATCH = 8


class RenderError(ValueError):
    pass


def inde_url(value, *, image=False):
    try:
        parts = urlsplit(value or "")
        path = unquote(parts.path)
        if (parts.scheme != "https" or parts.hostname not in {"inde.gr", "www.inde.gr"}
                or parts.port not in {None, 443} or parts.username is not None or parts.password is not None
                or "\\" in path or ".." in path.split("/")
                or any(ord(c) < 32 for c in value)):
            return None
        if image:
            return value if path.startswith("/image/") and not parts.query else None
        if path == "/index.php":
            query = parse_qs(parts.query)
            return value if (set(query) == {"route", "product_id"} and query["route"] == ["product/product"]
                             and len(query["product_id"]) == 1 and query["product_id"][0].isdigit()) else None
        if path.strip("/") and not path.startswith(("/admin", "/api/", "/image/")) and not parts.query:
            return value
    except (ValueError, TypeError):
        pass
    return None


def read_inde(client, url, *, image=False):
    limit = (8 if image else 4) * 1024 * 1024
    deadline = monotonic() + 12
    try:
        for _ in range(3):
            if not inde_url(url, image=image):
                break
            with client.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect and response.headers.get("location"):
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if monotonic() > deadline or len(body) + len(chunk) > limit:
                        raise RenderError("Η απάντηση της INDE ήταν πολύ μεγάλη ή άργησε.")
                    body.extend(chunk)
                return bytes(body)
    except httpx.HTTPError:
        raise RenderError("Η INDE δεν απάντησε. Δοκίμασε ξανά.") from None
    raise RenderError("Ο σύνδεσμος του προϊόντος ή της φωτογραφίας δεν είναι δημόσιος σύνδεσμος INDE.")


class ProductData(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.script = None
        self.documents = []
        self.gallery = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.script = []
        if tag == "div" and "lightgallery-product-images" in (attrs.get("class") or "").split():
            try:
                images = json.loads(attrs.get("data-images") or "[]")
            except (ValueError, RecursionError):
                return
            if isinstance(images, list):
                self.gallery.extend(item.get("src") for item in images if isinstance(item, dict))

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            try:
                self.documents.append(json.loads("".join(self.script), parse_float=Decimal))
            except (ValueError, RecursionError):
                pass
            self.script = None


def product_nodes(document):
    if isinstance(document, list):
        for child in document:
            yield from product_nodes(child)
    elif isinstance(document, dict):
        kind = document.get("@type")
        if kind == "Product" or isinstance(kind, list) and "Product" in kind:
            yield document
        if isinstance(document.get("@graph"), list):
            yield from product_nodes(document["@graph"])


def product_offer(body, sku):
    parser = ProductData()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parsed_offer(parser, sku)


def parsed_offer(parser, sku):
    offers = []
    for doc in parser.documents:
        for node in product_nodes(doc):
            if str(node.get("sku", "")).strip() != sku:
                continue
            rows = node.get("offers")
            for row in rows if isinstance(rows, list) else [rows]:
                if not isinstance(row, dict) or row.get("@type") != "Offer":
                    continue
                spec = row.get("priceSpecification")
                specs = spec if isinstance(spec, list) else [spec]
                tax_excluded = row.get("valueAddedTaxIncluded") is False or any(
                    isinstance(s, dict) and s.get("valueAddedTaxIncluded") is False for s in specs)
                try:
                    price = Decimal(str(row.get("price")))
                    if (row.get("priceCurrency") != "EUR" or tax_excluded
                            or str(row.get("availability", "")).rsplit("/", 1)[-1] != "InStock"
                            or not price.is_finite() or not 0 < price <= Decimal("99999999.99")
                            or price != price.quantize(CENT)):
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    raise RenderError(f"Δεν επιβεβαιώθηκε διαθέσιμη τιμή με ΦΠΑ για {sku}.") from None
                photos = node.get("image")
                photos = photos if isinstance(photos, list) else [photos]
                photo = next((u for u in photos if isinstance(u, str) and inde_url(u, image=True)), None)
                offers.append((price.quantize(CENT), photo))
    if not offers or len({p for p, _ in offers}) != 1:
        raise RenderError(f"Δεν βρέθηκε μοναδική τρέχουσα τιμή στην INDE για {sku}.")
    return offers[0][0], next((img for _, img in offers if img), None)


def live_products(client, brief):
    products = []
    for product in brief["products"]:
        parser = ProductData()
        parser.feed(read_inde(client, product["link"]).decode("utf-8", errors="replace"))
        price, photo = parsed_offer(parser, product["sku"])
        photo = photo or inde_url(product["image_url"], image=True)
        gallery = list(dict.fromkeys(
            url for url in parser.gallery if isinstance(url, str) and len(url) <= 2048 and inde_url(url, image=True)
        ))
        if not gallery and photo:
            gallery = [photo]
        if not gallery:
            raise RenderError(f"Δεν βρέθηκε δημόσια φωτογραφία INDE για {product['sku']}.")
        products.append({**product, "price_gross": str(price), "image_url": gallery[0], "gallery": gallery})
    return products


def inde_client():
    return httpx.Client(timeout=httpx.Timeout(5, connect=4), headers={
        "User-Agent": "IndeMarketingAnalyzer/1.0", "Cache-Control": "no-cache",
    })


def product_photo(client, url):
    data = read_inde(client, url, image=True)
    try:
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as photo:
            if photo.width * photo.height > 16_000_000:
                raise RenderError("Η φωτογραφία ξεπερνά το όριο ανάλυσης.")
            image = ImageOps.exif_transpose(photo)
            image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            return image.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise RenderError("Η φωτογραφία προϊόντος δεν μπόρεσε να διαβαστεί.") from None


def scene_graph(beats, frame_for, folder):
    inputs, filters = [], []

    def still(frame, label, frames):
        source = len(inputs) // 4
        path = folder / f"{label}.png"
        frame.save(path)
        inputs.extend(["-framerate", str(FPS), "-i", str(path)])
        pixel_format = "yuva420p" if frame.mode == "RGBA" else "yuv420p"
        filters.append(f"[{source}:v]loop={frames-1}:1:0,setpts=N/({FPS}*TB),"
                       f"setsar=1,format={pixel_format}[{label}]")

    for i, beat in enumerate(beats):
        frame, layer, stamp = frame_for(beat)
        if stamp and beat.frames < 24:
            # Short photo cuts show the whole image and price from the first frame.
            photo, x, y = layer
            frame.paste(photo, (x, y))
            art, x, y = stamp
            frame.paste(art, (x, y), art)
            layer = stamp = None
        still(frame, f"base{i}" if layer else f"v{i}", beat.frames)
        if layer:
            photo, x, y = layer
            still(photo, f"photo{i}", beat.frames)
            still(Image.new("RGB", photo.size, PLUM), f"stage{i}", beat.frames)
            length = 0.46 if beat.kind in {"hook", "cta"} else 0.28
            axis = "y" if beat.kind in {"hook", "cta", "offer"} else "x"
            dimension = "h" if axis == "y" else "w"
            direction = "-" if beat.kind != "detail" else ""
            start = 0.16 if beat.kind == "hook" else 0.0
            displacement = f"{direction}{dimension}*pow(max(0,1-(t+{start})/{length}),3)"
            output = f"shot{i}" if stamp else f"v{i}"
            filters.extend([
                f"[stage{i}][photo{i}]overlay={axis}='{displacement}':shortest=1[window{i}]",
                f"[base{i}][window{i}]overlay={x}:{y}:shortest=1[{output}]",
            ])
        if stamp:
            art, x, y = stamp
            still(art, f"stamp{i}", beat.frames)
            # Drop, overshoot for one frame, then settle on the beat.
            fall = f"38*max(0,1-pow(max(0,t-0.06)/{STAMP_LAND - 0.06:.6f},2))"
            rebound = f"8*max(0,1-abs(t-{STAMP_LAND + 1 / FPS:.6f})*{FPS})"
            filters.append(f"[shot{i}][stamp{i}]overlay={x}:y='{y}-{fall}+{rebound}':"
                           f"enable='gte(t,0.06)':shortest=1[v{i}]")
    filters.append("".join(f"[v{i}]" for i in range(len(beats)))
                   + f"concat=n={len(beats)}:v=1:a=0,settb=1/{FPS},setpts=N[video]")
    return inputs, ["-filter_complex", ";".join(filters), "-map", "[video]"]


def render_video(client, brief, products, ratio, folder: Path, *, soundtrack_id=None):
    parameters = brief["parameters"]
    duration = parameters["duration"]
    music = track_path(soundtrack_id)
    if soundtrack_id is not None and music is None:
        raise RenderError("Το επιλεγμένο κομμάτι δεν είναι διαθέσιμο.")
    urls = [product.get("selected_images", [product["image_url"]]) for product in products]
    photo_counts = [len(group) for group in urls]
    if sum(photo_counts) > photo_capacity(duration):
        raise RenderError("Οι φωτογραφίες δεν χωρούν στη διάρκεια του βίντεο.")
    beats = timeline(duration, len(products), parameters["style"], photo_counts)
    if music:
        beats = sync_cuts(beats, TRACKS[soundtrack_id]["accent_frames"])

    deadline = monotonic() + 240
    load_photo = lru_cache(maxsize=4)(lambda url: product_photo(client, url))

    def frame_for(beat):
        if monotonic() >= deadline:
            raise RenderError("Η δημιουργία βίντεο άργησε. Δοκίμασε λιγότερες φωτογραφίες.")
        if beat.kind == "end":
            return end_card(ratio), None, None
        return creative_frame(beat, load_photo(urls[beat.product][beat.photo]), products, parameters, ratio)

    def run(*args):
        subprocess.run([settings.promotion_ffmpeg_path, "-nostdin", "-v", "error", "-filter_complex_threads", "1",
                        *args], check=True, capture_output=True, timeout=max(0.1, deadline - monotonic()))

    audio_input = ["-i", str(music)] if music else ["-f", "lavfi", "-i", soundtrack(beats)]
    audio_filters = ["-af", f"afade=t=out:st={duration - 0.7}:d=0.7"] if music else []
    audio_encode = [*audio_filters, "-c:a", "aac", "-ac", "2", "-b:a", "128k", "-t", str(duration),
                    "-movflags", "+faststart"]
    video_encode = ["-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-r", str(FPS)]
    target = folder / "render.mp4"
    try:
        if len(beats) <= SCENES_PER_BATCH:
            inputs, graph = scene_graph(beats, frame_for, folder)
            run(*inputs, *audio_input, *graph, "-map", f"{len(inputs) // 4}:a",
                *video_encode, *audio_encode, str(target))
        else:
            # Bound decoder memory and input count independently of the number of photos.
            segments = []
            for index in range(0, len(beats), SCENES_PER_BATCH):
                batch = beats[index:index + SCENES_PER_BATCH]
                segment = folder / f"segment-{index}.mp4"
                with TemporaryDirectory(dir=folder) as stills:
                    inputs, graph = scene_graph(batch, frame_for, Path(stills))
                    run(*inputs, *graph, *video_encode, "-an", str(segment))
                segments.extend([f"file {segment.name}", f"duration {sum(beat.frames for beat in batch) / FPS:.6f}"])
            playlist = folder / "segments.ffconcat"
            playlist.write_text("ffconcat version 1.0\n" + "\n".join(segments) + "\n", encoding="ascii")
            run("-f", "concat", "-safe", "1", "-i", str(playlist), *audio_input, "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", *audio_encode, str(target))
    except (OSError, subprocess.SubprocessError):
        raise RenderError("Η εξαγωγή MP4 απέτυχε. Δοκίμασε ξανά.") from None
    if not target.is_file() or not 0 < target.stat().st_size <= MAX_VIDEO_BYTES:
        raise RenderError("Το MP4 είναι κενό ή ξεπερνά τα 64 MB.")
    return target
