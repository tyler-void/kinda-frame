"""The HTTP contract (specs/001-sleep-screen-frame/contracts/frame-api.md), as the plugin sees it."""

import time

import pytest
from fastapi.testclient import TestClient

from kindaframe import config
from kindaframe.app import create_app
from kindaframe.imaging import grey16

from .conftest import H, W, decode

PNG_SIG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(config.parse({}, state_dir=tmp_path)))


def test_frame_matches_plugin_obligations(client):
    r = client.get("/frame.png", params={"w": W, "h": H, "batt": 84})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-mode"] == "art"
    assert r.headers["x-frame-source"] in ("chladni", "flowfield", "attractor", "orbits")
    assert int(r.headers["x-frame-seed"]) >= 0
    assert r.content[:8] == PNG_SIG
    # What the plugin's pngcheck reads: IHDR width/height at bytes 16..23
    assert int.from_bytes(r.content[16:20], "big") == W and int.from_bytes(r.content[20:24], "big") == H
    img = decode(r.content)
    assert img.mode == "L" and grey16.levels_used(img) <= set(grey16.LEVELS)


@pytest.mark.parametrize("params", [{}, {"w": W}, {"h": H}, {"w": "x", "h": H}, {"w": 50, "h": H}, {"w": W, "h": 5000}])
def test_bad_size_is_400(client, params):
    r = client.get("/frame.png", params=params)
    assert r.status_code == 400 and "error" in r.json()


def test_unknown_params_ignored_and_bad_battery_tolerated(client):
    r = client.get("/frame.png", params={"w": W, "h": H, "batt": 140, "future": "x"})
    assert r.status_code == 200


def test_debug_override_is_reproducible(client):
    a = client.get("/frame.png", params={"w": W, "h": H, "art": "chladni", "seed": 7})
    b = client.get("/frame.png", params={"w": W, "h": H, "art": "chladni", "seed": 7})
    assert a.status_code == 200 and a.content == b.content
    assert a.headers["x-frame-source"] == "chladni" and a.headers["x-frame-seed"] == "7"


def test_unknown_generator_is_400(client):
    assert client.get("/frame.png", params={"w": W, "h": H, "art": "nope"}).status_code == 400


def test_second_request_is_prerendered_and_fast(client):
    client.get("/frame.png", params={"w": W, "h": H})  # cold; schedules the next one
    time.sleep(3)  # let the background render finish
    t = time.perf_counter()
    r = client.get("/frame.png", params={"w": W, "h": H})
    assert r.status_code == 200
    assert time.perf_counter() - t < 0.3


def test_consecutive_frames_differ(client):
    a = client.get("/frame.png", params={"w": W, "h": H}).content
    b = client.get("/frame.png", params={"w": W, "h": H}).content
    assert a != b  # a fresh piece on every sleep


def test_random_order_never_repeats_back_to_back(tmp_path):
    from kindaframe.render import Renderer
    r = Renderer(config.parse({}, state_dir=tmp_path))
    picks = [r._next_generator() for _ in range(200)]
    assert all(a != b for a, b in zip(picks, picks[1:]))
    assert set(picks) == set(config.ALL_GENERATORS)


def test_cycle_order_rotates_generators(tmp_path):
    c = TestClient(create_app(config.parse({"art": {"order": "cycle", "generators": ["chladni", "orbits"]}},
                                           state_dir=tmp_path)))
    srcs = [c.get("/frame.png", params={"w": 300, "h": 400}).headers["x-frame-source"] for _ in range(4)]
    assert srcs == ["chladni", "orbits", "chladni", "orbits"]


def test_photo_mode_and_empty_folder(tmp_path, photo_dir):
    ok = TestClient(create_app(config.parse({"mode": "photo", "photo": {"dir": str(photo_dir)}}, state_dir=tmp_path)))
    r = ok.get("/frame.png", params={"w": W, "h": H})
    assert r.status_code == 200 and r.headers["x-frame-mode"] == "photo"
    assert r.headers["x-frame-source"].startswith("photo ") and "x-frame-seed" not in r.headers
    assert decode(r.content).size == (W, H)

    empty = TestClient(create_app(config.parse({"mode": "photo", "photo": {"dir": str(tmp_path / "none")}},
                                              state_dir=tmp_path)))
    r = empty.get("/frame.png", params={"w": W, "h": H})
    assert r.status_code == 503 and r.headers["retry-after"] == "300"


def test_healthz(client):
    client.get("/frame.png", params={"w": W, "h": H})
    j = client.get("/healthz").json()
    assert j["status"] == "ok" and j["mode"] == "art" and j["last_render"] and j["last_source"]
