"""Chladni figures: where sand gathers on a vibrating plate.

For a plate vibrating in a superposition of modes, sand collects on the nodal lines where the
displacement is zero. For a free square plate a classic approximation is

    z(x, y) = a·cos(nπx)·cos(mπy) + b·cos(mπx)·cos(nπy),   x, y ∈ [0, 1]

with b = -a giving the familiar symmetric figures. We stretch the domain to the portrait canvas,
draw "sand" as exp(-(z/ε)²) so lines are thin where the plate moves fast and broaden near
saddle points, then add a little grain so it reads as sand rather than ink.
"""

from __future__ import annotations

import numpy as np

from .base import Piece


def render(rng: np.random.Generator, w: int, h: int) -> Piece:
    n = int(rng.integers(1, 10))
    m = int(rng.integers(n + 1, n + 8))
    a = 1.0
    b = float(rng.choice([-1.0, -1.0, -0.8, 1.0]))  # mostly the classic antisymmetric case
    y, x = np.mgrid[0:1:complex(0, h), 0:1:complex(0, w)]
    z = a * np.cos(n * np.pi * x) * np.cos(m * np.pi * y) + b * np.cos(m * np.pi * x) * np.cos(n * np.pi * y)
    eps = 0.06
    sand = np.exp(-(z / eps) ** 2)
    grain = rng.random((h, w))
    sand = np.where(grain < 0.85, sand, sand * 0.4)  # granular texture
    paper = 1.0 - 0.95 * sand
    # thin plate outline
    paper[:2, :] = paper[-2:, :] = 0.15
    paper[:, :2] = paper[:, -2:] = 0.15
    return Piece(paper, "Chladni figure", f"n = {n}, m = {m}, b/a = {b:+.1f}")
