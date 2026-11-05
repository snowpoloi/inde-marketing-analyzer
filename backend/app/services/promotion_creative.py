"""INDE motion graphics and cut timing for the local MP4 renderer."""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.promotion_service import FORMATS, font

FPS = 30
PLUM = "#4a2d57"
WHITE = "#ffffff"


@dataclass(frozen=True)
class Beat:
    kind: str
    frames: int
    product: int = 0
    photo: int = 0


def timeline(duration, count, style, photo_counts=None):
    opening, action, ending = 45, 45, 90
    photo_counts = photo_counts or [1] * count
    passes = min(3, 6 // count)
    if style == "editorial" and duration == 15:
        passes -= 1
    shots = [(product, shot) for product, photos in enumerate(photo_counts)
             for shot in range(max(photos, passes))]
    frames, remainder = divmod(duration * FPS - opening - action - ending, len(shots))
    beats = [Beat("hook", opening)]
    for i, (product, shot) in enumerate(shots):
        kind = ("product", "detail", "offer")[shot]
        beats.append(Beat(kind, frames + int(i < remainder), product, shot % photo_counts[product]))
    return [*beats, Beat("cta", action), Beat("end", ending)]


def price_text(value):
    return f"{Decimal(value):,.2f}".translate(str.maketrans(",.", ".,")) + " \u20ac"


def display_font(size, *, serif=False):
    paths = ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "C:/Windows/Fonts/georgia.ttf") if serif else (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/segoeuib.ttf")
    for path in paths:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return font(size)


def headline(draw, text, x, y, width, size, fill, maximum=2, *, serif=False):
    for point in range(size, 23, -2):
        face = display_font(point, serif=serif)
        lines = []
        for word in text.split():
            combined = f"{lines[-1]} {word}" if lines else word
            if lines and draw.textlength(combined, font=face) <= width:
                lines[-1] = combined
            else:
                lines.append(word)
        if len(lines) <= maximum and all(draw.textlength(line, font=face) <= width for line in lines):
            break
    else:
        truncated = len(lines) > maximum
        lines = lines[:maximum]
        for i, line in enumerate(lines):
            if draw.textlength(line, font=face) > width or (truncated and i == maximum - 1):
                while line and draw.textlength(line + "\u2026", font=face) > width:
                    line = line[:-1]
                lines[i] = line.rstrip() + "\u2026"
    for line in lines:
        draw.text((x, y), line, font=face, fill=fill, anchor="lt")
        y += round(face.size * 1.13)


def photo_plate(photo, size, *, aperture=False, full=False):
    if full:
        w, h = size
        scale = min(w / photo.width, h / photo.height)
        fitted = photo.resize((max(1, round(photo.width * scale)), max(1, round(photo.height * scale))),
                              Image.Resampling.LANCZOS)
        result = Image.new("RGB", size, WHITE)
        result.paste(fitted, ((w - fitted.width) // 2, (h - fitted.height) // 2))
    else:
        result = ImageOps.fit(photo, size, Image.Resampling.LANCZOS)
    if aperture:
        w, h = size
        mask = Image.new("L", size)
        painter = ImageDraw.Draw(mask)
        painter.rounded_rectangle((0, 0, w - 1, h - 1), radius=w // 2, fill=255)
        frame = Image.new("RGB", size, PLUM)
        frame.paste(result, (0, 0), mask)
        return frame
    return result


def creative_frame(beat, photos, products, parameters, ratio):
    """Compose the text and the independently revealed photo for a shot."""
    w, h = (FORMATS[ratio][key] for key in ("width", "height"))
    vertical, wide = ratio == "9:16", ratio == "16:9"
    margin = 96 if vertical else 80
    canvas = Image.new("RGB", (w, h), PLUM)
    draw = ImageDraw.Draw(canvas)
    top = 253 if vertical else 122
    draw.text((margin, top), "INDE.GR", font=display_font(27), fill=WHITE, anchor="lt")
    draw.line((margin, top + 48, w - margin, top + 48), fill=WHITE, width=2)

    if beat.kind in {"hook", "cta"}:
        lead = photos[0][0]
        line = parameters["hook"] if beat.kind == "hook" else parameters["cta"]
        if beat.kind == "hook" and line == "Ο χώρος σου, αλλιώς.":
            line = "Μια κίνηση αλλάζει τον χώρο."
        if beat.kind == "cta" and len(products) > 1 and line == "Ανακάλυψέ το στο inde.gr":
            line = "Δες τα στο inde.gr"
        if wide:
            headline(draw, line, margin, 365, 880, 124, WHITE, 3, serif=True)
            xy, size = (1140, 188), (600, 748)
        elif vertical:
            headline(draw, line, margin, 343, w - 2 * margin - 64, 108, WHITE, 3, serif=True)
            xy, size = (206, 742), (668, 782)
        else:
            headline(draw, line, margin, 207, w - 2 * margin, 85, WHITE, 2, serif=True)
            xy, size = (295, 425), (490, 568)
        return canvas, (photo_plate(lead, size, aperture=True), *xy)

    product = products[beat.product]
    draw.text((w - margin - (40 if vertical else 0), top), f"{beat.product + 1:02d} / {len(products):02d}",
              font=display_font(25), fill=WHITE, anchor="rt")
    if wide:
        xy, size = (976, 217), (864, 712)
        title_y, title_width, price_y, price_x = 340, 800, 688, 835
        rail_y = 649
    elif vertical:
        xy, size = (0, 347), (w, 790)
        title_y, title_width, price_y, price_x = 1212, 525, 1206, 930
        rail_y = 1174
    else:
        xy, size = (0, 204), (w, 532)
        title_y, title_width, price_y, price_x = 799, 550, 793, 1000
        rail_y = 765
    draw.line((margin, rail_y, price_x, rail_y), fill=WHITE, width=2)
    headline(draw, product["name"], margin, title_y, title_width, 44 if not wide else 68, WHITE, 2, serif=True)
    amount = price_text(product["price_gross"])
    point = 77 if wide else 66
    while draw.textlength(amount, font=display_font(point)) > (630 if wide else 295):
        point -= 2
    draw.text((price_x, price_y), amount, font=display_font(point), fill=WHITE, anchor="rt")
    draw.text((price_x, price_y + point + 8), "με ΦΠΑ", font=display_font(24), fill=WHITE, anchor="rt")
    photo = photos[beat.product][beat.photo]
    # A second selected photo is shown as a new shot, not a crop of the first.
    full = beat.kind != "detail" or len(photos[beat.product]) > 1
    return canvas, (photo_plate(photo, size, full=full), *xy)


def soundtrack(beats):
    """An original, restrained low pulse with soft edit accents."""
    pulse = "0.11*sin(2*PI*58*t)*exp(-14*mod(t,0.5))"
    phase = "mod(t,1)"
    tone = f"0.018*(sin(2*PI*146.83*t)+sin(2*PI*220*t))*sin(PI*{phase})^2"
    elapsed, hits = 0, []
    for beat in beats:
        if elapsed:
            tail = f"max(t-{elapsed / FPS:.6f},0)"
            hits.append(f"0.055*(sin(2*PI*181*{tail})+sin(2*PI*361*{tail}))*exp(-14*{tail})")
        elapsed += beat.frames
    duration = elapsed / FPS
    sound = "+".join([pulse, tone, *hits])
    return f"aevalsrc=exprs='1.8*({sound})*min((({duration}-t)/0.7),1)':s=48000:d={duration}"
