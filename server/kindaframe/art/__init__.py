"""Generative art mode ("art"): original, code-rendered pieces made for e-ink.

Inspired by Blackbody (alistair-roberts.co.uk/blackbody): images computed from maths and physics
rather than drawn. Blackbody targets OLED (black background, <3 % lit); e-ink is the opposite
medium, so these are dark linework on white paper. No code or images from Blackbody are used.

Each generator is a pure function `render(rng, w, h) -> Piece` and must be deterministic for a
given seed. See docs/art.md for what each one draws and the maths behind it.
"""

from __future__ import annotations

from . import attractor, chladni, flowfield, orbits
from .base import Piece, compose

GENERATORS = {
    "chladni": chladni.render,
    "flowfield": flowfield.render,
    "attractor": attractor.render,
    "orbits": orbits.render,
}

__all__ = ["GENERATORS", "Piece", "compose"]
