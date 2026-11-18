#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Generate the M1 sleep-screen test card (spec Story 1, SC-005).

The card checks, at a glance on the Kindle:
  * exact size / no offset   -> 1 px black border on every edge + corner marks
  * no scaling               -> 1 px checkerboard and line patches stay crisp (scaling = grey mush/moiré)
  * 16 grey levels           -> 16 labelled swatches, values 0, 17, ..., 255
  * light end is visible     -> big side-by-side bars for levels 12-15 (re-kindle found light greys faint)
  * orientation              -> TOP marker

Every pixel is snapped to the 16-level palette, so the PNG is exactly what the
server will send later (8-bit greyscale, values k*17).

Usage:  uv run tools/make-test-card.py --w 1072 --h 1448 -o tools/stub/frame.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LEVELS = [i * 17 for i in range(16)]  # 0x00, 0x11, ..., 0xFF

FONT_CANDIDATES = [
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
]


def load_font(size: int, path: str | None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ([path] if path else []) + FONT_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def snap(value: int) -> int:
    """Nearest of the 16 levels."""
    return min(LEVELS, key=lambda lv: abs(lv - value))


def text_fill(bg: int) -> int:
    return 255 if bg < 136 else 0


def build(w: int, h: int, font_path: str | None, banner: str | None = None) -> Image.Image:
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    big = load_font(max(24, w // 18), font_path)
    mid = load_font(max(16, w // 30), font_path)
    small = load_font(max(12, w // 48), font_path)
    m = max(24, w // 40)  # outer margin

    # Exact-edge border (1 px) + corner marks: any crop or offset shows as a missing edge.
    d.rectangle([0, 0, w - 1, h - 1], outline=0, width=1)
    ck = m
    for x0, y0, sx, sy in [(0, 0, 1, 1), (w - 1, 0, -1, 1), (0, h - 1, 1, -1), (w - 1, h - 1, -1, -1)]:
        d.line([(x0, y0), (x0 + sx * ck, y0)], fill=0, width=5)
        d.line([(x0, y0), (x0, y0 + sy * ck)], fill=0, width=5)

    # TOP marker.
    y = m // 2
    tri = [(w // 2, y), (w // 2 - m, y + m), (w // 2 + m, y + m)]
    d.polygon(tri, fill=0)
    d.text((w // 2, y + m + 6), "TOP", font=mid, fill=0, anchor="mt")

    # Title block.
    y = y + m + 6 + mid.size + m // 2
    d.text((w // 2, y), "kinda-frame · M1 test card", font=big, fill=0, anchor="mt")
    y += big.size + 10
    d.text((w // 2, y), f"{w} × {h} px · 16 grey levels", font=mid, fill=0, anchor="mt")
    y += mid.size + m

    # 16 swatches, 4 x 4 grid.
    cols, rows = 4, 4
    gw = w - 2 * m
    sw = gw // cols
    sh = int(h * 0.36) // rows
    for i, lv in enumerate(LEVELS):
        cx, cy = i % cols, i // cols
        x0, y0 = m + cx * sw, y + cy * sh
        d.rectangle([x0, y0, x0 + sw - 1, y0 + sh - 1], fill=lv)
        d.text((x0 + sw // 2, y0 + sh // 2), f"{i}\n0x{lv:02X}", font=mid, fill=text_fill(lv),
               anchor="mm", align="center")
    d.rectangle([m - 1, y - 1, m + cols * sw, y + rows * sh], outline=0, width=1)
    y += rows * sh + m

    # Light end, large bars side by side: levels 12..15 must all be distinguishable.
    d.text((m, y), "Light end: 12 · 13 · 14 · 15 (white) must all differ", font=small, fill=0)
    y += small.size + 8
    bar_h = int(h * 0.08)
    light = LEVELS[12:]
    bw = gw // len(light)
    for j, lv in enumerate(light):
        x0 = m + j * bw
        d.rectangle([x0, y, x0 + bw - 1, y + bar_h - 1], fill=lv)
        d.text((x0 + bw // 2, y + bar_h // 2), str(12 + j), font=mid, fill=0, anchor="mm")
    d.rectangle([m - 1, y - 1, m + len(light) * bw, y + bar_h], outline=0, width=1)
    y += bar_h + m

    # Scaling detectors: 1 px checkerboard, 1 px vertical lines, 1 px horizontal lines.
    d.text((m, y), "Fine patterns: crisp texture = 1:1 · grey mush or moiré = scaled", font=small, fill=0)
    y += small.size + 8
    patch = min(int(h * 0.12), (gw - 2 * m) // 3)
    for k in range(3):
        x0 = m + k * (patch + m)
        for py in range(patch):
            for px in range(patch):
                if k == 0:
                    on = (px + py) % 2 == 0
                elif k == 1:
                    on = px % 2 == 0
                else:
                    on = py % 2 == 0
                if on:
                    img.putpixel((x0 + px, y + py), 0)
        d.rectangle([x0 - 1, y - 1, x0 + patch, y + patch], outline=0, width=1)
    y += patch + m

    # Optional banner in the free space below the patterns (used for redraw tests: "REDRAWN B").
    if banner:
        bottom = h - m - small.size - m // 2
        if bottom - y > big.size * 2:
            d.rectangle([m, y, w - m - 1, bottom], fill=0)
            d.text((w // 2, (y + bottom) // 2), banner, font=big, fill=255, anchor="mm")

    # Bottom note.
    d.text((w // 2, h - m), "bottom edge · power button", font=small, fill=0, anchor="mb")

    # Snap every pixel (anti-aliased text included) to the 16-level palette.
    lut = [snap(v) for v in range(256)]
    return img.point(lut)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--w", type=int, required=True, help="screen width as KOReader reports it")
    ap.add_argument("--h", type=int, required=True, help="screen height as KOReader reports it")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--font", help="TTF to use instead of the built-in candidates")
    ap.add_argument("--banner", help="large white-on-black label in the free area (e.g. 'REDRAWN B')")
    a = ap.parse_args()

    img = build(a.w, a.h, a.font, a.banner)
    used = {v for v, n in enumerate(img.histogram()) if n}
    assert img.size == (a.w, a.h) and img.mode == "L"
    assert used <= set(LEVELS), "pixel outside the 16-level palette"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(a.out, optimize=True)
    print(f"wrote {a.out} ({a.w}x{a.h}, levels used: {len(used)}/16)")


if __name__ == "__main__":
    main()
