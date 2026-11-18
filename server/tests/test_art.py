import time

import numpy as np
import pytest

from kindaframe import art
from kindaframe.art.base import art_area, coverage
from kindaframe.imaging import grey16

from .conftest import H, W

AW, AH = art_area(W, H)


@pytest.mark.parametrize("name", sorted(art.GENERATORS))
@pytest.mark.parametrize("seed", [1, 7, 42])
def test_generator_fills_area_with_some_but_not_too_much_ink(name, seed):
    piece = art.GENERATORS[name](np.random.default_rng(seed), AW, AH)
    assert piece.paper.shape == (AH, AW)
    assert 0.0 <= piece.paper.min() and piece.paper.max() <= 1.0
    c = coverage(piece.paper)
    assert 0.01 < c < 0.9, f"{name} seed {seed}: coverage {c:.3f}"
    assert piece.title and piece.params


@pytest.mark.parametrize("name", sorted(art.GENERATORS))
def test_generator_is_deterministic_per_seed(name):
    a = art.GENERATORS[name](np.random.default_rng(123), AW, AH).paper
    b = art.GENERATORS[name](np.random.default_rng(123), AW, AH).paper
    c = art.GENERATORS[name](np.random.default_rng(124), AW, AH).paper
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


@pytest.mark.parametrize("name", sorted(art.GENERATORS))
def test_compose_gives_exact_screen_on_palette(name):
    piece = art.GENERATORS[name](np.random.default_rng(5), AW, AH)
    img = art.compose(piece, W, H, 5, name)
    assert img.size == (W, H) and img.mode == "L"
    assert grey16.levels_used(img) <= set(grey16.LEVELS)
    assert img.getpixel((0, 0)) == 255 and img.getpixel((W - 1, H - 1)) == 255  # white margins


@pytest.mark.parametrize("name", sorted(art.GENERATORS))
def test_render_is_fast_enough(name):
    # SC-008 budget is < 5 s cold; the dev laptop should be far below. The i3 server is ~2x slower.
    t = time.perf_counter()
    piece = art.GENERATORS[name](np.random.default_rng(9), AW, AH)
    art.compose(piece, W, H, 9, name)
    assert time.perf_counter() - t < 2.5
