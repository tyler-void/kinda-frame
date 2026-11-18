"""Fitting arbitrary images onto the device screen (photo mode, FR-016)."""

from __future__ import annotations

from PIL import Image, ImageOps


def fit(img: Image.Image, w: int, h: int, mode: str = "crop") -> Image.Image:
    """EXIF-orient, then either fill-and-centre-crop ('crop') or letterbox on white ('pad')."""
    img = ImageOps.exif_transpose(img).convert("L")
    if mode == "pad":
        return ImageOps.pad(img, (w, h), method=Image.Resampling.LANCZOS, color=255)
    return ImageOps.fit(img, (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def tone(img: Image.Image, gamma: float = 0.9, cutoff: float = 0.5) -> Image.Image:
    """Autocontrast + a mild gamma lift: e-ink renders mid-tones darker than an LCD."""
    img = ImageOps.autocontrast(img, cutoff=cutoff)
    lut = [round(255 * ((v / 255) ** gamma)) for v in range(256)]
    return img.point(lut)
