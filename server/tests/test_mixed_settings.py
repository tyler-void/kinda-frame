"""Mixed mode (schedule / alternate) and the LAN settings page."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from kindaframe import config
from kindaframe.app import create_app
from kindaframe.render import FrameCache, Renderer
from kindaframe.settings_store import ConfigStore, deep_merge

from .conftest import H, W

ORIGIN = {"Origin": "http://testserver"}
SECRET = "https://calendar.example.com/calendar/ical/me/private-SECRETTOKEN123/basic.ics"


# ------------------------------------------------------------------ mixed mode
def test_schedule_wraps_past_midnight():
    m = config.parse({"mode": "mixed", "mixed": {"schedule": [
        {"from": "21:00", "mode": "art"}, {"from": "06:30", "mode": "dashboard"}]}}).mixed
    assert m.schedule == ((390, "dashboard"), (1260, "art"))
    assert [m.mode_at(t) for t in (0, 389, 390, 1259, 1260)] == ["art", "art", "dashboard", "dashboard", "art"]


@pytest.mark.parametrize("bad", [
    {"strategy": "random"}, {"modes": []}, {"modes": ["mixed"]},
    {"schedule": []}, {"schedule": [{"from": "25:00", "mode": "art"}]},
    {"schedule": [{"from": "06:00", "mode": "art"}, {"from": "06:00", "mode": "photo"}]},
])
def test_bad_mixed_config_rejected(bad):
    with pytest.raises(config.ConfigError):
        config.parse({"mode": "mixed", "mixed": bad})


def test_alternate_cycles_modes(tmp_path, photo_dir):
    cfg = config.parse({"mode": "mixed", "mixed": {"strategy": "alternate", "modes": ["art", "photo"]},
                        "photo": {"dir": str(photo_dir)}}, state_dir=tmp_path)
    r = Renderer(cfg)
    assert r.planned_mode() is None
    assert [r.render(300, 400).mode for _ in range(4)] == ["art", "photo", "art", "photo"]


def test_schedule_picks_mode_by_local_time(tmp_path, photo_dir, monkeypatch):
    cfg = config.parse({"mode": "mixed", "photo": {"dir": str(photo_dir)},
                        "mixed": {"schedule": [{"from": "08:00", "mode": "photo"}, {"from": "20:00", "mode": "art"}]}},
                       state_dir=tmp_path)
    r = Renderer(cfg)
    monkeypatch.setattr(r, "_local_now", lambda: datetime(2026, 11, 18, 9, 0))
    assert r.planned_mode() == "photo" and r.render(300, 400).mode == "photo"
    monkeypatch.setattr(r, "_local_now", lambda: datetime(2026, 11, 18, 22, 0))
    assert r.render(300, 400).mode == "art"


def test_prerendered_frame_is_replaced_when_the_schedule_moved_on(tmp_path, photo_dir, monkeypatch):
    cfg = config.parse({"mode": "mixed", "photo": {"dir": str(photo_dir)},
                        "mixed": {"schedule": [{"from": "08:00", "mode": "photo"}, {"from": "20:00", "mode": "art"}]}},
                       state_dir=tmp_path)
    r = Renderer(cfg)
    cache = FrameCache(r)
    monkeypatch.setattr(r, "_local_now", lambda: datetime(2026, 11, 18, 19, 59))
    assert cache.get(300, 400).mode == "photo"  # also pre-renders the next one (photo)
    cache._ready[(300, 400, "portrait")].result()
    monkeypatch.setattr(r, "_local_now", lambda: datetime(2026, 11, 18, 20, 1))
    assert cache.get(300, 400).mode == "art"  # the prepared photo is stale: 20:00 switched to art


def test_stale_dashboard_frame_is_rerendered(tmp_path):
    from kindaframe.render import Frame
    r = Renderer(config.parse({"mode": "art"}, state_dir=tmp_path))
    cache = FrameCache(r)
    old = Frame(b"x", "dashboard", "daily", None, datetime.now(timezone.utc) - timedelta(minutes=10), 300, 400)
    rendered = []
    monkey = r.render
    r.render = lambda *a, **k: rendered.append(k.get("mode")) or monkey(300, 400, mode="art")  # type: ignore[method-assign]
    from concurrent.futures import Future
    fut: Future = Future(); fut.set_result(old)
    cache._ready[(300, 400, "portrait")] = fut
    r.planned_mode = lambda: None  # type: ignore[method-assign] # alternate: no fixed plan
    cache.get(300, 400)
    assert rendered[0] == "dashboard"


# ------------------------------------------------------------------ settings store
def test_deep_merge_tables_merge_lists_replace():
    assert deep_merge({"a": {"x": 1, "y": [1]}, "b": 1}, {"a": {"y": [2]}}) == {"a": {"x": 1, "y": [2]}, "b": 1}


def test_broken_overrides_fall_back_to_base(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"mode": "nonsense"}))
    store = ConfigStore(tmp_path / "missing.toml", tmp_path)
    assert store.current.mode == "art"


def test_unreadable_or_broken_config_never_crashes(tmp_path):
    base = tmp_path / "config.toml"
    base.write_text('mode = "art"\n')
    base.chmod(0o000)
    try:
        store = ConfigStore(base, tmp_path / "s")
        if store.base_error:  # (root can read anything; skip the assertion there)
            assert "PermissionError" in store.base_error and store.current.mode == "art"
    finally:
        base.chmod(0o644)
    base.write_text("mode = [broken")
    store = ConfigStore(base, tmp_path / "s")
    assert "TOMLDecodeError" in store.base_error and store.current.mode == "art"
    base.write_text('mode = "billboard"\n')
    store = ConfigStore(base, tmp_path / "s")
    assert "ignored" in store.base_error and store.current.mode == "art"
    c = TestClient(create_app(store=store))
    assert c.get("/healthz").json()["config_error"]
    assert "Server config problem" in c.get("/settings").text


# ------------------------------------------------------------------ settings page
@pytest.fixture
def store(tmp_path):
    base = tmp_path / "config.toml"
    base.write_text('mode = "art"\ntimezone = "Europe/Berlin"\n')
    return ConfigStore(base, tmp_path / "state")


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store))


def form(**over):
    data = {"mode": "mixed", "mixed_strategy": "schedule", "sched_from_0": "06:00", "sched_mode_0": "dashboard",
            "sched_from_1": "21:00", "sched_mode_1": "art", "sched_from_2": "", "sched_mode_2": "art",
            "alt_modes": ["dashboard", "art"], "art_gen": ["chladni", "orbits"], "art_order": "random",
            "photo_order": "random", "photo_fit": "crop", "timezone": "Europe/Berlin",
            "location_label": "Home", "latitude": "52.52", "longitude": "13.40", "units": "metric", "cal_add": ""}
    data.update(over)
    return data


def test_page_renders(client):
    r = client.get("/settings")
    assert r.status_code == 200 and "kinda-frame" in r.text and 'name="mode"' in r.text
    assert client.get("/", follow_redirects=False).status_code == 303


def test_post_without_same_origin_is_refused(client, store):
    assert client.post("/settings", data=form()).status_code == 403
    assert client.post("/settings", data=form(), headers={"Origin": "http://evil.example"}).status_code == 403
    assert store.overrides() == {}


def test_save_applies_live_and_persists(client, store):
    r = client.post("/settings", data=form(), headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings?saved=1"
    cfg = store.current
    assert cfg.mode == "mixed" and cfg.mixed.schedule == ((360, "dashboard"), (1260, "art"))
    assert cfg.art.generators == ("chladni", "orbits")
    assert cfg.boards["daily"]["latitude"] == 52.52
    assert store.overrides_path.is_file() and (store.overrides_path.stat().st_mode & 0o777) == 0o600
    assert client.get("/healthz").json()["mode"] == "mixed"  # renderer reconfigured without a restart


def test_invalid_input_saves_nothing(client, store):
    r = client.post("/settings", data=form(latitude="200"), headers=ORIGIN)
    assert r.status_code == 400 and "Not saved" in r.text
    assert store.overrides() == {}
    r = client.post("/settings", data=form(art_gen=[]), headers=ORIGIN)
    assert r.status_code == 400 and store.overrides() == {}


def test_calendar_secret_is_masked_and_removable(client, store):
    client.post("/settings", data=form(cal_add=SECRET.replace("https://", "webcal://")), headers=ORIGIN)
    assert store.current.boards["daily"]["calendars"] == [SECRET]  # webcal:// normalised to https://
    page = client.get("/settings").text
    assert "SECRETTOKEN" not in page and "calendar.example.com" in page
    client.post("/settings", data=form(cal_remove_0="on"), headers=ORIGIN)
    assert store.current.boards["daily"]["calendars"] == []


def test_reset_drops_overrides(client, store):
    client.post("/settings", data=form(), headers=ORIGIN)
    assert client.post("/settings/reset", headers=ORIGIN, follow_redirects=False).status_code == 303
    assert store.current.mode == "art" and store.overrides() == {}


def test_preview_is_a_png_and_does_not_touch_the_device_cache(client):
    r = client.get("/preview.png", params={"mode": "art", "orient": "left"})
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get("/preview.png", params={"mode": "nope"}).status_code == 400
    assert client.get("/healthz").json()["last_render"] is None


def test_device_request_updates_status_shown_on_page(client):
    client.get("/frame.png", params={"w": W, "h": H, "batt": 66, "orient": "left"})
    page = client.get("/settings").text
    assert "battery 66%" in page and "landscape, left edge down" in page
