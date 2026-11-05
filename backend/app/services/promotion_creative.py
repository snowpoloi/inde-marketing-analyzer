"""INDE motion graphics and cut timing for the local MP4 renderer."""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from app.services.promotion_service import FORMATS, font

FPS = 30
STAMP_LAND = 7 / FPS
OPENING_FRAMES = 45
ACTION_FRAMES = 45
ENDING_FRAMES = 90
MIN_PHOTO_FRAMES = 12
PLUM = "#4a2d57"
WHITE = "#ffffff"


@dataclass(frozen=True)
class Beat:
    kind: str
    frames: int
    product: int = 0
    photo: int = 0


def photo_capacity(duration):
    return (duration * FPS - OPENING_FRAMES - ACTION_FRAMES - ENDING_FRAMES) // MIN_PHOTO_FRAMES


def timeline(duration, count, style, photo_counts=None):
    photo_counts = photo_counts or [1] * count
    if sum(photo_counts) > photo_capacity(duration):
        raise ValueError("Too many photos for the selected video duration.")
    passes = min(3, 6 // count)
    if style == "editorial" and duration == 15:
        passes -= 1
    while sum(max(photos, passes) for photos in photo_counts) > photo_capacity(duration):
        passes -= 1
    shots = [(product, shot) for product, photos in enumerate(photo_counts)
             for shot in range(max(photos, passes))]
    frames, remainder = divmod(duration * FPS - OPENING_FRAMES - ACTION_FRAMES - ENDING_FRAMES, len(shots))
    beats = [Beat("hook", OPENING_FRAMES)]
    for i, (product, shot) in enumerate(shots):
        kind = "product" if shot == 0 else "detail" if shot % 2 else "offer"
        beats.append(Beat(kind, frames + int(i < remainder), product, shot % photo_counts[product]))
    return [*beats, Beat("cta", ACTION_FRAMES), Beat("end", ENDING_FRAMES)]


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


def has_white_background(photo):
    # Sample every edge so a bright wall alone does not trigger studio framing.
    red, green, blue = photo.resize((48, 48), Image.Resampling.BOX).convert("RGB").split()
    minimum_channel = ImageChops.darker(ImageChops.darker(red, green), blue)
    edges = ((0, 0, 48, 2), (0, 46, 48, 48), (0, 0, 2, 48), (46, 0, 48, 48))
    return all(sum(minimum_channel.crop(edge).histogram()[245:]) >= 87 for edge in edges)


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


def price_stamp(value, *, wide=False):
    amount = price_text(value)
    width, height = (410, 124) if wide else (336, 114)
    stamp = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(stamp)
    face = display_font(90 if wide else 78)
    while draw.textlength(amount, font=face) > width - 44:
        face = display_font(face.size - 2)
    draw.rounded_rectangle((2, 2, width - 3, height - 3), radius=10, fill=PLUM, outline=WHITE, width=4)
    draw.rounded_rectangle((10, 10, width - 11, height - 11), radius=5, outline=WHITE, width=1)
    draw.text((width / 2, height / 2), amount, font=face, fill=WHITE, anchor="mm")
    return stamp.rotate(4, resample=Image.Resampling.BICUBIC, expand=True)


def creative_frame(beat, photo, products, parameters, ratio):
    """Compose a shot and its separately animated photo and price stamp."""
    w, h = (FORMATS[ratio][key] for key in ("width", "height"))
    vertical, wide = ratio == "9:16", ratio == "16:9"
    margin = 96 if vertical else 80
    canvas = Image.new("RGB", (w, h), PLUM)
    draw = ImageDraw.Draw(canvas)
    top = 253 if vertical else 122
    draw.text((margin, top), "INDE.GR", font=display_font(27), fill=WHITE, anchor="lt")
    draw.line((margin, top + 48, w - margin, top + 48), fill=WHITE, width=2)

    if beat.kind in {"hook", "cta"}:
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
        return canvas, (photo_plate(photo, size, aperture=True), *xy), None

    product = products[beat.product]
    studio = has_white_background(photo)
    draw.text((w - margin - (40 if vertical else 0), top), f"{beat.product + 1:02d} / {len(products):02d}",
              font=display_font(25), fill=WHITE, anchor="rt")
    if wide:
        xy, size = (976, 217), (864, 712)
        title_y, title_width, price_y, price_x = 340, 800, 683, 835
        rail_y = 649
    elif vertical:
        height = 790 if studio else min(1040, max(790, round(w * photo.height / photo.width)))
        extra = height - 790
        xy, size = (0, 347), (w, height)
        title_y, title_width, price_y, price_x = 1212 + extra, 450, 1206 + extra, 930
        rail_y = 1174 + extra
    else:
        xy, size = (0, 204), (w, 532)
        title_y, title_width, price_y, price_x = 799, 540, 793, 1000
        rail_y = 765
    draw.line((margin, rail_y, price_x, rail_y), fill=WHITE, width=2)
    headline(draw, product["name"], margin, title_y, title_width, 44 if not wide else 68, WHITE, 2, serif=True)
    stamp = price_stamp(product["price_gross"], wide=wide)
    return canvas, (photo_plate(photo, size, full=studio), *xy), (stamp, price_x - stamp.width, price_y)


def soundtrack(beats):
    """An original 120 BPM groove with accents on the price stamp."""
    quarter, eighth = "mod(t,0.5)", "mod(t,0.25)"
    chord = "mod(floor(t/2),4)"
    root = f"if(eq({chord},0),110,if(eq({chord},1),87.31,if(eq({chord},2),130.81,98)))"
    step = "mod(floor(t*4),4)"
    interval = f"if(eq({step},0),2,if(eq({step},1),if(eq({chord},0),2.3784,2.5198),if(eq({step},2),3,4)))"
    lead_phase = f"2*PI*{root}*{interval}*{eighth}"
    kick = f"0.19*sin(2*PI*(52*{quarter}+1.6*(1-exp(-40*{quarter}))))*exp(-13*{quarter})"
    bass = f"0.10*sin(2*PI*{root}*{quarter})*exp(-7*{quarter})"
    pluck = f"0.074*(sin({lead_phase})+0.28*sin(2*{lead_phase}))*exp(-12*{eighth})"
    hat = f"0.037*(2*random(0)-1)*exp(-52*{eighth})"
    clap = "0.055*(2*random(1)-1)*exp(-21*mod(t+0.5,1))"
    elapsed, hits = 0, []
    for beat in beats:
        if beat.kind in {"product", "detail", "offer"}:
            tail = f"max(t-{elapsed / FPS + STAMP_LAND:.6f},0)"
            hits.append(f"0.085*(sin(2*PI*137*{tail})+0.35*sin(2*PI*415*{tail}))*exp(-25*{tail})")
        elapsed += beat.frames
    duration = elapsed / FPS
    sound = "+".join([kick, bass, pluck, hat, clap, *hits])
    return f"aevalsrc=exprs='1.6*({sound})*min((({duration}-t)/0.7),1)':s=48000:d={duration}"
