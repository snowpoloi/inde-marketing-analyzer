"""Bundled music and its precomputed rhythmic accents at the renderer's 30 fps."""
import json
from dataclasses import replace
from itertools import accumulate
from pathlib import Path

MUSIC_DIR = Path(__file__).resolve().parents[1] / "assets" / "promotion-soundtracks"
TRACKS = {row["id"]: row for row in json.loads((MUSIC_DIR / "catalog.json").read_text(encoding="utf-8"))}


def music_catalog():
    return [{key: row[key] for key in ("id", "title", "artist", "genre", "license")} for row in TRACKS.values()]


def track_path(track_id):
    if track_id in TRACKS:
        path = MUSIC_DIR / f"{track_id}.mp3"
        if path.is_file():
            return path
    return None


def sync_cuts(beats, accents):
    boundaries = [0, *accumulate(beat.frames for beat in beats)]
    total = boundaries[-1]
    for i in range(1, len(beats)):
        original = boundaries[i]
        left = boundaries[i - 1] + min(12, beats[i - 1].frames)
        right = boundaries[i + 1] - min(12, beats[i].frames)
        eligible = (frame for frame in accents if abs(frame - original) <= 9
                    and left <= frame <= right
                    and (beats[i].kind != "end" or frame <= total - beats[i].frames))
        boundaries[i] = min(eligible, key=lambda frame: abs(frame - original), default=original)
    return [replace(beat, frames=end - start) for beat, start, end in zip(beats, boundaries, boundaries[1:])]
