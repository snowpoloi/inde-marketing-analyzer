"""Read public INDE offers and compose MP4s using local FFmpeg."""
import io
import json
import subprocess
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.services.promotion_service import FORMATS, end_card, font

CENT = Decimal("0.01")
MAX_VIDEO_BYTES = 64 * 1024 * 1024
PLUM = "#452d4f"
FPS = 30


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

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.script = []

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
        price, photo = product_offer(read_inde(client, product["link"]), product["sku"])
        photo = photo or inde_url(product["image_url"], image=True)
        if not photo:
            raise RenderError(f"Δεν βρέθηκε δημόσια φωτογραφία INDE για {product['sku']}.")
        products.append({**product, "price_gross": str(price), "image_url": photo})
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
            return ImageOps.exif_transpose(photo).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise RenderError("Η φωτογραφία προϊόντος δεν μπόρεσε να διαβαστεί.") from None


def price_text(value):
    return f"{Decimal(value):,.2f}".translate(str.maketrans(",.", ".,")) + " \u20ac"


def fit_lines(draw, text, face, width, maximum):
    words = " ".join(text.split()).split()
    lines = [""]
    for word in words:
        candidate = f"{lines[-1]} {word}".strip()
        if draw.textlength(candidate, font=face) <= width:
            lines[-1] = candidate
        elif len(lines) < maximum and lines[-1]:
            lines.append(word)
        else:
            lines[-1] = candidate
            break
    for i, line in enumerate(lines):
        if draw.textlength(line, font=face) > width:
            while line and draw.textlength(line.rstrip() + "\u2026", font=face) > width:
                line = line[:-1]
            lines[i] = line.rstrip() + "\u2026"
    return lines


def product_frame(photo, product, parameters, ratio):
    w, h = (FORMATS[ratio][key] for key in ("width", "height"))
    portrait = ratio == "9:16"
    canvas = Image.new("RGB", (w, h), "#faf8f7")
    draw = ImageDraw.Draw(canvas)
    if portrait:
        box = (84, 98, w - 84, 1140)
        x, y, width = 95, 1200, w - 190
    else:
        box = (w // 2, 84, w - 74, h - 84)
        x, y, width = 74, 174, w // 2 - 118
    hook_font = font(30)
    hook = fit_lines(draw, parameters["hook"], hook_font, w - 180, 1)[0]
    draw.text((x, 42), hook, font=hook_font, fill=PLUM, anchor="lt")
    draw.rectangle(box, fill="white")
    contained = ImageOps.contain(photo, (box[2] - box[0] - 32, box[3] - box[1] - 32),
                                 Image.Resampling.LANCZOS)
    canvas.paste(contained, ((box[0] + box[2] - contained.width) // 2,
                            (box[1] + box[3] - contained.height) // 2))
    draw.rectangle((x, y, x + 50, y + 4), fill=PLUM)
    draw.text((x, y + 22), "INDE", font=font(27), fill=PLUM, anchor="lt")
    y += 72
    title_font = font(42 if w == h else 55)
    for line in fit_lines(draw, product["name"], title_font, width, 3):
        draw.text((x, y), line, font=title_font, fill="#251f27", anchor="lt")
        y += title_font.size + 12
    y += 22
    amount = price_text(product["price_gross"])
    size = 81 if w != h else 67
    while draw.textlength(amount, font=font(size)) > width:
        size -= 2
    draw.text((x, y), amount, font=font(size), fill=PLUM, anchor="lt")
    y += size + 14
    draw.text((x, y), "\u03bc\u03b5 \u03a6\u03a0\u0391", font=font(27), fill=PLUM, anchor="lt")
    y += 54
    for line in fit_lines(draw, parameters["cta"], font(28), width, 2):
        draw.text((x, y), line, font=font(28), fill="#534759", anchor="lt")
        y += 35
    return canvas


def render_video(client, brief, products, ratio, folder: Path):
    parameters = brief["parameters"]
    seconds, remainder = divmod(parameters["duration"] - 3, len(products))
    inputs, filters = [], []
    motion = {"cinematic": 0.028, "editorial": 0.012, "detail": 0.04}[parameters["style"]]
    w, h = (FORMATS[ratio][key] for key in ("width", "height"))
    for i, product in enumerate(products):
        path = folder / f"scene-{i}.png"
        product_frame(product_photo(client, product["image_url"]), product, parameters, ratio).save(path)
        inputs += ["-i", str(path)]
        frames = (seconds + int(i < remainder)) * FPS
        # Keep the entire product in frame with a shallow push-in.
        filters.append(f"[{i}:v]scale=iw*2:ih*2,zoompan=z='1+{motion}*on/{frames-1}':"
                       f"x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s={w}x{h}:fps={FPS},"
                       f"setsar=1,format=yuv420p[v{i}]")
    card = folder / "end-card.png"
    end_card(ratio).save(card)
    i = len(products)
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(card)]
    filters.append(f"[{i}:v]trim=duration=3,setpts=PTS-STARTPTS,setsar=1,format=yuv420p[v{i}]")
    filters.append("".join(f"[v{k}]" for k in range(i + 1)) + f"concat=n={i+1}:v=1:a=0[video]")
    target = folder / "render.mp4"
    try:
        subprocess.run([settings.promotion_ffmpeg_path, "-nostdin", "-v", "error", "-filter_complex_threads", "1",
                        *inputs, "-filter_complex", ";".join(filters), "-map", "[video]", "-an", "-c:v", "libx264",
                        "-threads", "2", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-frames:v", str(parameters["duration"] * FPS), "-movflags", "+faststart", str(target)],
                       check=True, capture_output=True, timeout=150)
    except (OSError, subprocess.SubprocessError):
        raise RenderError("Η εξαγωγή MP4 απέτυχε. Δοκίμασε ξανά.") from None
    if not target.is_file() or not 0 < target.stat().st_size <= MAX_VIDEO_BYTES:
        raise RenderError("Το MP4 είναι κενό ή ξεπερνά τα 64 MB.")
    return target
