"""Photo mode (FR-016): one image from a folder, fitted, toned and dithered for the device."""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image

from .config import PhotoConfig
from .imaging import fit as fitting
from .imaging import grey16

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


class NoPhotos(RuntimeError):
    pass


def list_photos(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS
                  and not p.name.startswith("."))


def pick(cfg: PhotoConfig, state_dir: Path, rng: random.Random) -> tuple[Path, int, int]:
    """Return (path, index, total). Sequential order remembers its place in state_dir."""
    photos = list_photos(cfg.dir)
    if not photos:
        raise NoPhotos(f"no images in {cfg.dir}")
    if cfg.order == "random":
        i = rng.randrange(len(photos))
    else:
        cursor = state_dir / "photo_cursor.json"
        last = -1
        try:
            last = int(json.loads(cursor.read_text())["index"])
        except (OSError, ValueError, KeyError):
            pass
        i = (last + 1) % len(photos)
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            tmp = cursor.with_suffix(".tmp")
            tmp.write_text(json.dumps({"index": i}))
            tmp.replace(cursor)
        except OSError:
            pass  # read-only state: still serve, just restart the sequence next time
    return photos[i], i, len(photos)


def render(path: Path, w: int, h: int, mode: str) -> Image.Image:
    with Image.open(path) as img:
        fitted = fitting.fit(img, w, h, mode)
    return grey16.quantize(fitting.tone(fitted), dither=True)
