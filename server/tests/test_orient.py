"""Orientation: landscape frames are laid out wide and turned into the portrait buffer the right way."""

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kindaframe import config
from kindaframe.app import create_app
from kindaframe.art.base import art_area
from kindaframe.imaging import grey16
from kindaframe.imaging.orient import canvas_size, to_buffer

from .conftest import H, W, decode


def marker_canvas():
    """Landscape canvas (as the viewer sees it) with a black dot near its TOP-LEFT corner."""
    img = Image.new("L", (H, W), 255)  # 1448 x 1072
    img.paste(0, (10, 10, 30, 30))
    return img


def test_canvas_is_wide_for_landscape():
    assert canvas_size(W, H, "portrait") == (W, H)
    assert canvas_size(W, H, "left") == (H, W)
    assert canvas_size(W, H, "right") == (H, W)


def test_left_edge_down_puts_viewer_top_left_at_buffer_top_right():
    # Standing on its LEFT edge, the buffer's top-right corner is what the viewer sees as top-left.
    buf = to_buffer(marker_canvas(), "left")
    assert buf.size == (W, H)
    assert buf.getpixel((W - 20, 20)) == 0
    assert buf.getpixel((20, 20)) == 255


def test_right_edge_down_puts_viewer_top_left_at_buffer_bottom_left():
    # Standing on its RIGHT edge, the buffer's bottom-left corner is the viewer's top-left.
    buf = to_buffer(marker_canvas(), "right")
    assert buf.size == (W, H)
    assert buf.getpixel((20, H - 20)) == 0
    assert buf.getpixel((W - 20, 20)) == 255


def test_portrait_is_untouched():
    img = Image.new("L", (W, H), 128)
    assert to_buffer(img, "portrait") is img


def test_art_area_uses_short_side_for_margins():
    pw, ph = art_area(W, H)
    lw, lh = art_area(H, W)
    assert (W - pw) == (H - lw)  # same side margins in both orientations
    assert lw > lh  # landscape art area is wide


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(config.parse({}, state_dir=tmp_path)))


@pytest.mark.parametrize("orient", ["portrait", "left", "right"])
def test_api_always_returns_the_portrait_buffer_size(client, orient):
    r = client.get("/frame.png", params={"w": W, "h": H, "orient": orient})
    assert r.status_code == 200
    assert r.headers["x-frame-orient"] == orient
    img = decode(r.content)
    assert img.size == (W, H)  # the plugin's IHDR check is unchanged
    assert grey16.levels_used(img) <= set(grey16.LEVELS)


def test_landscape_caption_lands_on_the_correct_buffer_edge(client):
    # The caption sits at the bottom of the viewer's canvas. Left edge down: viewer-bottom = buffer-left.
    r = client.get("/frame.png", params={"w": W, "h": H, "orient": "left", "art": "chladni", "seed": 3})
    img = decode(r.content)
    m = max(24, min(W, H) // 24)
    caption_strip = img.crop((m, m, m + 90, H - m))       # buffer-left band, inside the margin
    opposite = img.crop((W - m - 4, m, W - m, H - m))      # thin band at the buffer-right paper edge
    ink = lambda im: sum(n for v, n in enumerate(im.histogram()) if v < 128)
    assert ink(caption_strip) > 0
    assert ink(opposite) < ink(caption_strip)


def test_unknown_orient_is_400(client):
    assert client.get("/frame.png", params={"w": W, "h": H, "orient": "upside"}).status_code == 400


def test_prerender_cache_is_per_orientation(client):
    a = client.get("/frame.png", params={"w": W, "h": H, "orient": "left"})
    b = client.get("/frame.png", params={"w": W, "h": H, "orient": "portrait"})
    assert a.headers["x-frame-orient"] == "left" and b.headers["x-frame-orient"] == "portrait"
