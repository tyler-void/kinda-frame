"""Frame orientation: how the Kindle is standing (plugin setting, sent as `orient=`).

The screen buffer is always portrait (w x h as KOReader reports it, e.g. 1072 x 1448). For a
landscape frame we lay the content out on an h x w canvas and turn it into the buffer:

  portrait   upright, as read                         no rotation
  left       resting on its LEFT edge (power button    landscape canvas turned 90° clockwise
             and USB end up on the right)
  right      resting on its RIGHT edge                 landscape canvas turned 90° counter-clockwise

Why clockwise for "left": standing the device on its left edge turns it 90° counter-clockwise,
so the buffer's right column becomes the viewer's top row; the canvas must turn the other way.
"""

from __future__ import annotations

from PIL import Image

ORIENTS = ("portrait", "left", "right")

_TRANSPOSE = {
    "left": Image.Transpose.ROTATE_270,   # PIL angles are counter-clockwise: 270 ccw = 90 cw
    "right": Image.Transpose.ROTATE_90,
}


def canvas_size(w: int, h: int, orient: str) -> tuple[int, int]:
    """Size to lay the frame out at, as the viewer sees it."""
    return (w, h) if orient == "portrait" else (h, w)


def to_buffer(img: Image.Image, orient: str) -> Image.Image:
    """Turn a viewer-oriented canvas into the device's portrait buffer."""
    t = _TRANSPOSE.get(orient)
    return img if t is None else img.transpose(t)
