"""Night icons on the daily board, and photo uploads from the settings page."""

from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kindaframe import boards, photo
from kindaframe.app import create_app
from kindaframe.boards.daily import board as daily
from kindaframe.settings_store import ConfigStore

from .test_dashboard import NOW, SETTINGS, ctx, weather_json

ORIGIN = {"Origin": "http://testserver"}


# ------------------------------------------------------------------ night icons
def test_moon_after_dark_sun_by_day():
    raw = weather_json()
    raw["current"]["weather_code"] = 0
    raw["current"]["is_day"] = 0
    raw["hourly"]["weather_code"] = [0] * 48
    raw["hourly"]["is_day"] = [1 if 6 <= i % 24 < 18 else 0 for i in range(48)]
    w = daily.parse_weather(raw, NOW)  # NOW is 21:14
    assert w["now"]["icon"] == "clear_night"
    assert {h["time"]: h["icon"] for h in w["hours"]} == {
        "21:00": "clear_night", "00:00": "clear_night", "03:00": "clear_night",
        "06:00": "clear", "09:00": "clear", "12:00": "clear"}
    assert daily.night("rain", 0) == "rain" and daily.night("partly", 0) == "partly_night"


def test_missing_is_day_means_day():
    raw = weather_json()
    raw["current"]["weather_code"] = 0
    assert daily.parse_weather(raw, NOW)["now"]["icon"] == "clear"


def test_night_icons_render():
    raw = weather_json()
    raw["current"].update(weather_code=1, is_day=0)
    html = boards.render_html("daily", SETTINGS, ctx(lambda u: json.dumps(raw).encode()
                                                     if u.startswith(daily.OPEN_METEO) else b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"))
    assert "a20 20 0 1 0 12 30" in html  # the crescent path


# ------------------------------------------------------------------ uploads
def jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (400, 300), (120, 160, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 cw
    exif[0x8825] = {1: "N", 2: (10.0, 50.0, 0.0)}  # GPSInfo
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


@pytest.fixture
def setup(tmp_path):
    base = tmp_path / "config.toml"
    base.write_text(f'mode = "photo"\n[photo]\ndir = "{tmp_path / "hostphotos"}"\n')
    (tmp_path / "hostphotos").mkdir()
    Image.new("L", (300, 400), 90).save(tmp_path / "hostphotos" / "host.png")
    store = ConfigStore(base, tmp_path / "state")
    return TestClient(create_app(store=store)), store


def test_upload_strips_metadata_and_bakes_orientation(setup):
    client, store = setup
    r = client.post("/photos/upload?name=../../evil name.JPG", content=jpeg_with_gps(), headers=ORIGIN)
    assert r.status_code == 200, r.text
    name = r.json()["name"]
    assert "/" not in name and ".." not in name and name.endswith("-evil_name.jpg")
    saved = photo.uploads_dir(store.current.state_dir) / name
    with Image.open(saved) as im:
        assert im.size == (300, 400)  # EXIF orientation applied
        assert 0x8825 not in im.getexif() and 0x0112 not in im.getexif()  # no GPS, no orientation tag


def test_upload_refusals(setup):
    client, store = setup
    assert client.post("/photos/upload?name=a.jpg", content=jpeg_with_gps()).status_code == 403
    assert client.post("/photos/upload?name=a.jpg", content=b"not an image", headers=ORIGIN).status_code == 400
    assert client.post("/photos/upload?name=a.jpg", content=b"", headers=ORIGIN).status_code == 400
    big = client.post("/photos/upload?name=a.jpg", content=b"x" * 10,
                      headers={**ORIGIN, "Content-Length": str(31 * 1024 * 1024)})
    assert big.status_code in (400, 413)
    assert photo.list_photos(photo.uploads_dir(store.current.state_dir)) == []


def test_uploaded_photos_join_photo_mode_and_can_be_deleted(setup):
    client, store = setup
    name = client.post("/photos/upload?name=sky.jpg", content=jpeg_with_gps(), headers=ORIGIN).json()["name"]
    assert len(photo.all_photos(store.current.photo, store.current.state_dir)) == 2
    page = client.get("/settings").text
    assert name in page and "server folder" in page
    assert client.get("/photos/thumb", params={"src": "uploads", "name": name}).status_code == 200
    assert client.get("/photos/thumb", params={"src": "folder", "name": "host.png"}).status_code == 200
    # host-folder photos can't be deleted from the page; traversal names do nothing
    client.post("/photos/delete", data={"name": "../config.toml"}, headers=ORIGIN)
    client.post("/photos/delete", data={"name": "host.png"}, headers=ORIGIN)
    assert len(photo.all_photos(store.current.photo, store.current.state_dir)) == 2
    assert client.post("/photos/delete", data={"name": name}).status_code == 403  # cross-origin
    client.post("/photos/delete", data={"name": name}, headers=ORIGIN)
    assert len(photo.all_photos(store.current.photo, store.current.state_dir)) == 1


def test_thumb_only_serves_listed_files(setup):
    client, _ = setup
    assert client.get("/photos/thumb", params={"src": "uploads", "name": "../settings.json"}).status_code == 404
    assert client.get("/photos/thumb", params={"src": "folder", "name": "/etc/passwd"}).status_code == 404
