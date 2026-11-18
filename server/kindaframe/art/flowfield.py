"""Flow field: particles drifting through a divergence-free (curl) velocity field.

A stream function ψ built from a few random plane waves,

    ψ(x, y) = Σ_k a_k · sin(k_k · (x, y) + φ_k)

gives the velocity v = (∂ψ/∂y, −∂ψ/∂x). It's divergence-free, so streamlines never pile up into
sinks: the picture looks like ink in water or marbled paper. Thousands of particles are advected
with a simple Euler step and their positions are accumulated into a density image.
"""

from __future__ import annotations

import numpy as np

from .base import Piece, density, tonemap


def render(rng: np.random.Generator, w: int, h: int) -> Piece:
    aspect = h / w
    k = int(rng.integers(3, 7))
    ang = rng.uniform(0, 2 * np.pi, k)
    mag = rng.uniform(1.5, 5.0, k)
    kx, ky = mag * np.cos(ang), mag * np.sin(ang)
    amp = rng.uniform(0.5, 1.0, k) / mag
    phase = rng.uniform(0, 2 * np.pi, k)

    def velocity(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        arg = np.outer(x, kx) + np.outer(y, ky) + phase  # (N, k)
        c = np.cos(arg) * amp
        return c @ ky, -(c @ kx)

    n, steps, dt = 5000, 320, 0.0045
    x = rng.uniform(0, 1, n)
    y = rng.uniform(0, aspect, n)
    xs = np.empty((steps, n))
    ys = np.empty((steps, n))
    for i in range(steps):
        vx, vy = velocity(x, y)
        speed = np.sqrt(vx * vx + vy * vy) + 1e-9
        x = x + dt * vx / speed  # unit speed: even line density regardless of local field strength
        y = y + dt * vy / speed
        xs[i], ys[i] = x, y
    d = density(xs.ravel(), ys.ravel(), w, h, (0.0, 1.0, 0.0, aspect))
    paper = tonemap(d, gamma=0.45)
    return Piece(paper, "Flow field", f"{k} waves · {n} particles × {steps} steps")
