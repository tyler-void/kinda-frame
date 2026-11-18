"""Orbits: harmonograph and epicycle traces.

Harmonograph: a pen moved by damped pendulums, one pair per axis,

    x(t) = Σ A_i · sin(f_i·t + p_i) · e^(−d_i·t)        (same form for y)

With frequencies near small whole-number ratios (2:3, 3:4, …) and a slight detune, the slowly
decaying figure spirals inward into the classic woven rosette.

Epicycles: a point carried by circles riding on circles (Ptolemy's deferent and epicycles),

    z(t) = Σ r_k · e^(i·(ω_k·t + φ_k)),   ω_k integers

which closes into a symmetric rosette whose symmetry is set by the frequency differences.
The curve is sampled very densely and accumulated as a density image, so overlapping passes
darken naturally like real ink.
"""

from __future__ import annotations

import numpy as np

from .base import Piece, aspect_bounds, density, portrait, tonemap

RATIOS = [(2, 3), (3, 4), (1, 2), (3, 5), (2, 5), (4, 5), (1, 3)]


def _harmonograph(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, str]:
    p, q = RATIOS[int(rng.integers(len(RATIOS)))]
    base = rng.uniform(1.8, 2.6)
    f = np.array([p, q, q, p], dtype=float) * base + rng.normal(0, 0.012, 4)
    ph = rng.uniform(0, 2 * np.pi, 4)
    damp = rng.uniform(0.0012, 0.004, 4)
    amp = np.array([1.0, rng.uniform(0.3, 0.9), 1.0, rng.uniform(0.3, 0.9)])
    t = np.linspace(0, 900, 2_400_000)
    e = np.exp(-np.outer(damp, t))
    x = amp[0] * np.sin(f[0] * t + ph[0]) * e[0] + amp[1] * np.sin(f[1] * t + ph[1]) * e[1]
    y = amp[2] * np.sin(f[2] * t + ph[2]) * e[2] + amp[3] * np.sin(f[3] * t + ph[3]) * e[3]
    return x, y, f"harmonograph {p}:{q} · detune {abs(f[0] - p * base):.3f}"


def _epicycles(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, str]:
    sym = int(rng.integers(3, 10))  # rotational symmetry
    k = int(rng.integers(2, 4))
    omegas = [1] + [1 + sym * int(rng.integers(1, 4)) * int(rng.choice([-1, 1])) for _ in range(k)]
    radii = [1.0] + list(rng.uniform(0.15, 0.6, k))
    phases = rng.uniform(0, 2 * np.pi, k + 1)
    t = np.linspace(0, 2 * np.pi, 1_600_000)
    z = sum(r * np.exp(1j * (om * t + ph)) for r, om, ph in zip(radii, omegas, phases))
    # Draw several slightly scaled copies: a pen line with some weight and texture.
    scales = np.linspace(0.995, 1.005, 3)
    x = np.concatenate([z.real * s for s in scales])
    y = np.concatenate([z.imag * s for s in scales])
    return x, y, f"epicycles ω = {omegas} · {sym}-fold"


def render(rng: np.random.Generator, w: int, h: int) -> Piece:
    if rng.random() < 0.5:
        x, y, params = _harmonograph(rng)
        title = "Harmonograph"
    else:
        x, y, params = _epicycles(rng)
        title = "Epicycles"
    x, y = portrait(x, y)
    d = density(x, y, w, h, aspect_bounds(x, y, w, h, lo=0.0, hi=100.0))
    return Piece(tonemap(d, gamma=0.5), title, params)
