"""Shared helpers for the art generators: density accumulation, tone mapping, captioned layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..imaging import grey16

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian (container: fonts-dejavu-core)
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
)


@dataclass(frozen=True)
class Piece:
    paper: np.ndarray  # float (h, w) in [0, 1]: 1 = white paper, 0 = full ink
    title: str  # e.g. "Chladni figure"
    params: str  # e.g. "n = 3, m = 7"


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def aspect_bounds(xs: np.ndarray, ys: np.ndarray, w: int, h: int, pad: float = 0.04,
                  lo: float = 0.2, hi: float = 99.8) -> tuple[float, float, float, float]:
    """Robust data bounds (percentiles), padded and widened to the canvas aspect ratio."""
    x0, x1 = np.percentile(xs, [lo, hi])
    y0, y1 = np.percentile(ys, [lo, hi])
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    sx, sy = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    sx, sy = sx * (1 + 2 * pad), sy * (1 + 2 * pad)
    target = w / h
    if sx / sy < target:
        sx = sy * target
    else:
        sy = sx / target
    return cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2


def align(xs: np.ndarray, ys: np.ndarray, w: int, h: int,
          lo: float = 1.0, hi: float = 99.0) -> tuple[np.ndarray, np.ndarray]:
    """Turn a point cloud a quarter turn if its long axis disagrees with the canvas's long axis,
    so it fills the frame in portrait and in landscape."""
    wx = np.subtract(*np.percentile(xs, [hi, lo]))
    wy = np.subtract(*np.percentile(ys, [hi, lo]))
    if (wx > wy) != (w > h):
        return ys, -xs
    return xs, ys


def density(xs: np.ndarray, ys: np.ndarray, w: int, h: int,
            bounds: tuple[float, float, float, float]) -> np.ndarray:
    """Count points per pixel (y axis pointing up). np.bincount is ~10x faster than np.add.at."""
    x0, x1, y0, y1 = bounds
    ix = ((xs - x0) / (x1 - x0) * (w - 1)).astype(np.int64)
    iy = ((y1 - ys) / (y1 - y0) * (h - 1)).astype(np.int64)
    ok = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    flat = iy[ok] * w + ix[ok]
    return np.bincount(flat, minlength=w * h).reshape(h, w).astype(np.float64)


def tonemap(d: np.ndarray, gamma: float = 0.5, ink: float = 0.97) -> np.ndarray:
    """Log density -> paper value. Empty pixels stay pure white (no ink anywhere unneeded)."""
    if d.max() <= 0:
        return np.ones_like(d)
    v = np.log1p(d)
    v /= v.max()
    return 1.0 - ink * v ** gamma


def coverage(paper: np.ndarray, threshold: float = 0.92) -> float:
    """Fraction of the canvas carrying visible ink (used to reject degenerate parameter draws)."""
    return float((paper < threshold).mean())


def compose(piece: Piece, w: int, h: int, seed: int, name: str) -> Image.Image:
    """Lay the piece out on the full screen with a small caption, quantized to the 16 levels.

    The art is dithered (smooth tones); the caption is drawn afterwards and snapped without
    dithering so the text stays crisp.
    """
    aw, ah = art_area(w, h)
    s = min(w, h)  # scale type and margins by the short side: same look in portrait and landscape
    margin = max(24, s // 24)
    cap_size = max(14, s // 48)

    art = piece.paper
    if art.shape != (ah, aw):
        art = np.asarray(grey16.from_float(art).resize((aw, ah), Image.Resampling.LANCZOS),
                         dtype=np.float64) / 255.0

    canvas = np.ones((h, w), dtype=np.float64)
    canvas[margin:margin + ah, margin:margin + aw] = art
    img = grey16.quantize(grey16.from_float(canvas), dither=True)

    d = ImageDraw.Draw(img)
    y = margin + ah + cap_size // 2
    d.line([(margin, y), (margin + aw // 6, y)], fill=0, width=2)
    d.text((margin, y + cap_size // 2), piece.title, font=font(int(cap_size * 1.15)), fill=0)
    small = font(cap_size)
    d.text((margin, y + int(cap_size * 1.9)), piece.params, font=small, fill=68)
    tag = f"{name} · seed {seed}"
    d.text((margin + aw, y + int(cap_size * 1.9)), tag, font=small, fill=68, anchor="ra")
    return grey16.quantize(img, dither=False)


def art_area(w: int, h: int) -> tuple[int, int]:
    """The (width, height) generators should render at for a w x h screen (matches compose)."""
    s = min(w, h)
    margin = max(24, s // 24)
    cap_h = int(max(14, s // 48) * 3.2)
    return w - 2 * margin, h - 2 * margin - cap_h
