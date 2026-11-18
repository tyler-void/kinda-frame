"""Photo mode (FR-016): one image from a folder, fitted, toned and dithered for the device."""

from __future__ import annotations

import io
import json
import random
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

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


MAX_UPLOAD = 30 * 1024 * 1024


def uploads_dir(state_dir: Path) -> Path:
    """Photos uploaded from the settings page (the host photo folder is mounted read-only)."""
    return state_dir / "uploads"


def all_photos(cfg: PhotoConfig, state_dir: Path) -> list[Path]:
    return list_photos(cfg.dir) + list_photos(uploads_dir(state_dir))


def safe_name(name: str) -> str:
    stem = Path(name).stem
    clean = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem).strip("._")[:60] or "photo"
    return clean


def save_upload(state_dir: Path, filename: str, data: bytes) -> Path:
    """Validate an uploaded image and store it as JPEG/PNG in the uploads folder. Raises ValueError."""
    if not data:
        raise ValueError("empty file")
    if len(data) > MAX_UPLOAD:
        raise ValueError("file larger than 30 MB")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # structural check without decoding everything
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001 - any decoder error means "not an image we can use"
        raise ValueError("not an image Pillow can read (HEIC: export as JPEG first)") from e
    folder = uploads_dir(state_dir)
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".png" if (img.format or "").upper() == "PNG" else ".jpg"  # read before exif_transpose drops it
    img = ImageOps.exif_transpose(img)  # bake the orientation in; re-saving drops metadata (GPS, camera)
    out = folder / f"{datetime.now():%Y%m%d-%H%M%S}-{safe_name(filename)}{ext}"
    tmp = out.with_suffix(out.suffix + ".tmp")
    if ext == ".jpg":
        img.convert("RGB").save(tmp, format="JPEG", quality=92)
    else:
        img.save(tmp, format="PNG")
    tmp.replace(out)
    return out


def delete_upload(state_dir: Path, name: str) -> bool:
    folder = uploads_dir(state_dir).resolve()
    target = (folder / name).resolve()
    if target.parent != folder or not target.is_file():
        return False  # only plain files directly in the uploads folder
    target.unlink()
    return True


def pick(cfg: PhotoConfig, state_dir: Path, rng: random.Random) -> tuple[Path, int, int]:
    """Return (path, index, total). Sequential order remembers its place in state_dir."""
    photos = all_photos(cfg, state_dir)
    if not photos:
        raise NoPhotos(f"no images in {cfg.dir} or uploaded")
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
