"""Strange attractors: the long-run shape of a simple chaotic map.

Two classic 2-D maps:

    Clifford:  x' = sin(a·y) + c·cos(a·x)      y' = sin(b·x) + d·cos(b·y)
    de Jong:   x' = sin(a·y) − cos(b·x)        y' = sin(c·x) − cos(d·y)

Iterating either from almost any start converges onto a fractal set. We run many short
trajectories in parallel (vectorised), drop the transient, and histogram all visited points.
Parameters start from a curated list and are jittered; draws that collapse to a few points or
fill the whole frame are rejected by a coverage check.
"""

from __future__ import annotations

import numpy as np

from .base import Piece, align, aspect_bounds, coverage, density, tonemap

CLIFFORD = [(-1.4, 1.6, 1.0, 0.7), (1.7, 1.7, 0.6, 1.2), (-1.7, 1.3, -0.1, -1.2),
            (-1.7, 1.8, -1.9, -0.4), (1.5, -1.8, 1.6, 0.9), (-1.8, -2.0, -0.5, -0.9)]
DE_JONG = [(1.4, -2.3, 2.4, -2.1), (-2.7, -0.09, -0.86, -2.2), (-0.827, -1.637, 1.659, -0.943),
           (2.01, -2.53, 1.61, -0.33), (-2.24, 0.43, -0.65, -2.43)]


def _iterate(kind: str, p: tuple[float, ...], rng: np.random.Generator,
             walkers: int = 24000, steps: int = 220, skip: int = 20) -> tuple[np.ndarray, np.ndarray]:
    a, b, c, d = p
    x = rng.uniform(-1, 1, walkers)
    y = rng.uniform(-1, 1, walkers)
    xs = np.empty((steps - skip, walkers))
    ys = np.empty((steps - skip, walkers))
    for i in range(steps):
        if kind == "clifford":
            x, y = np.sin(a * y) + c * np.cos(a * x), np.sin(b * x) + d * np.cos(b * y)
        else:
            x, y = np.sin(a * y) - np.cos(b * x), np.sin(c * x) - np.cos(d * y)
        if i >= skip:
            xs[i - skip], ys[i - skip] = x, y
    return xs.ravel(), ys.ravel()


def render(rng: np.random.Generator, w: int, h: int) -> Piece:
    for _ in range(6):
        kind = str(rng.choice(["clifford", "dejong"]))
        base = CLIFFORD if kind == "clifford" else DE_JONG
        p = tuple(float(v) for v in np.array(base[int(rng.integers(len(base)))]) + rng.normal(0, 0.04, 4))
        xs, ys = _iterate(kind, p, rng)
        xs, ys = align(xs, ys, w, h)  # long axis along the frame's long side
        d = density(xs, ys, w, h, aspect_bounds(xs, ys, w, h))
        paper = tonemap(d, gamma=0.42)
        if 0.04 < coverage(paper) < 0.75:
            break
    name = "Clifford attractor" if kind == "clifford" else "de Jong attractor"
    return Piece(paper, name, "a = {:.3f}, b = {:.3f}, c = {:.3f}, d = {:.3f}".format(*p))
