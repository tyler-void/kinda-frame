"""The device palette: 16 grey levels 0, 17, ..., 255 (spec FR-003, contracts/frame-api.md).

Everything the server sends goes through `quantize`, so every pixel is exactly one of LEVELS.
Dithered (Floyd–Steinberg) for photos and generative art with smooth tones; undithered for
text/UI where crisp edges matter more than smooth gradients.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

LEVELS: tuple[int, ...] = tuple(i * 17 for i in range(16))

_PALETTE_IMG: Image.Image | None = None


def _palette_image() -> Image.Image:
    global _PALETTE_IMG
    if _PALETTE_IMG is None:
        pal = Image.new("P", (1, 1))
        flat: list[int] = []
        for v in LEVELS:
            flat += [v, v, v]
        flat += [0, 0, 0] * (256 - len(LEVELS))  # unused entries
        pal.putpalette(flat)
        _PALETTE_IMG = pal
    return _PALETTE_IMG


def quantize(img: Image.Image, dither: bool = True) -> Image.Image:
    """Return an 'L' image whose pixels are all in LEVELS."""
    rgb = img.convert("RGB")
    q = rgb.quantize(
        palette=_palette_image(),
        dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE,
    )
    # Palette index i -> grey i*17 (indices beyond 15 never occur: only 16 colours are distinct,
    # but map defensively onto the nearest level).
    idx = np.asarray(q, dtype=np.uint8)
    lut = np.array([LEVELS[min(i, 15)] for i in range(256)], dtype=np.uint8)
    return Image.fromarray(lut[idx], mode="L")


def from_float(arr: np.ndarray) -> Image.Image:
    """Float array in [0, 1] (0 = black ink, 1 = white paper) -> 8-bit 'L' image (not yet quantized)."""
    a = np.clip(arr, 0.0, 1.0)
    return Image.fromarray((a * 255.0 + 0.5).astype(np.uint8), mode="L")


def levels_used(img: Image.Image) -> set[int]:
    hist = img.convert("L").histogram()
    return {v for v, n in enumerate(hist) if n}


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
