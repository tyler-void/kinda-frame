"""Daily board: sources, failure isolation, escaping, and a real Chromium render (skipped if unavailable)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from kindaframe import boards, config
from kindaframe.boards.base import BoardContext, SourceCache
from kindaframe.boards.daily import board as daily
from kindaframe.imaging import grey16

from .conftest import H, W

TZ = ZoneInfo("Asia/Tokyo")  # any non-UTC zone: catches naive/aware datetime mistakes
NOW = datetime(2026, 11, 18, 21, 14, tzinfo=TZ)


def weather_json(now: datetime = NOW) -> dict:
    day0 = now.date()
    hours = [datetime.combine(day0, datetime.min.time()) + timedelta(hours=i) for i in range(48)]
    return {
        "current": {"temperature_2m": 24.6, "apparent_temperature": 26.1, "weather_code": 61},
        "hourly": {
            "time": [t.strftime("%Y-%m-%dT%H:%M") for t in hours],
            "temperature_2m": [20 + (i % 10) for i in range(48)],
            "precipitation_probability": [i % 100 for i in range(48)],
            "weather_code": [3] * 48,
        },
        "daily": {
            "time": [str(day0), str(day0 + timedelta(days=1))],
            "weather_code": [61, 2], "temperature_2m_max": [29.4, 31.0], "temperature_2m_min": [22.2, 23.0],
            "precipitation_probability_max": [80, 20],
            "sunrise": [f"{day0}T06:01", f"{day0 + timedelta(days=1)}T06:02"],
            "sunset": [f"{day0}T17:15", f"{day0 + timedelta(days=1)}T17:15"],
        },
    }


ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:standup
DTSTART;TZID=Asia/Tokyo:20261102T093000
DTEND;TZID=Asia/Tokyo:20261102T094500
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
SUMMARY:Standup
END:VEVENT
BEGIN:VEVENT
UID:birthday
DTSTART;VALUE=DATE:20261118
DTEND;VALUE=DATE:20261119
SUMMARY:Lan's birthday
END:VEVENT
BEGIN:VEVENT
UID:utc-call
DTSTART:20261118T050000Z
DTEND:20261118T060000Z
SUMMARY:<script>alert(1)</script> Call
LOCATION:Room 3
END:VEVENT
BEGIN:VEVENT
UID:tomorrow
DTSTART;TZID=Asia/Tokyo:20261119T190000
DTEND;TZID=Asia/Tokyo:20261119T210000
SUMMARY:Dinner
END:VEVENT
END:VCALENDAR
"""

SETTINGS = {"latitude": 52.52, "longitude": 13.4, "location_label": "Home", "calendars": ["http://cal/a.ics"]}


def ctx(http=None, w=W, h=H, now=NOW, battery=79, cache=None) -> BoardContext:
    return BoardContext(now=now, tz=TZ, cache=cache or SourceCache(), battery=battery, w=w, h=h,
                        orient="portrait" if w < h else "left", http=http)


def fake_http(url: str) -> bytes:
    if url.startswith(daily.OPEN_METEO):
        return json.dumps(weather_json()).encode()
    if url.endswith(".ics"):
        return ICS
    raise AssertionError(url)


def test_weather_url_has_what_parse_needs():
    u = daily.weather_url(52.52, 13.4, "Asia/Tokyo", "metric")
    for part in ("latitude=52.5200", "longitude=13.4000", "timezone=Asia/Tokyo", "forecast_days=2",
                 "current=", "hourly=", "daily="):
        assert part in u
    assert "fahrenheit" in daily.weather_url(52.52, 13.4, "UTC", "imperial")


def test_build_happy_path():
    d = daily.build(SETTINGS, ctx(fake_http))
    assert d["date"]["weekday"] == "Wednesday" and d["date"]["tomorrow"] == "Thursday"
    w = d["weather"].data
    assert w["now"] == {"temp": 25, "feels": 26, "label": "Light rain", "icon": "rain"}
    assert w["today"]["hi"] == 29 and w["today"]["sunrise"] == "06:01"
    assert [h["time"] for h in w["hours"]] == ["21:00", "00:00", "03:00", "06:00", "09:00", "12:00"]
    cal = d["calendar"].data
    titles = [e["title"] for e in cal["today"]]
    assert titles[0] == "Lan's birthday" and cal["today"][0]["when"] == "all day"  # all-day first
    assert "Standup" in titles  # recurring event expanded
    call = next(e for e in cal["today"] if "Call" in e["title"])
    assert call["when"] == "14:00–15:00"  # 05:00Z shown in local time
    assert [e["title"] for e in cal["tomorrow"]] == ["Standup", "Dinner"]


def test_each_source_fails_on_its_own():
    def weather_down(url):
        if url.startswith(daily.OPEN_METEO):
            raise TimeoutError("timed out")
        return ICS
    d = daily.build(SETTINGS, ctx(weather_down))
    assert not d["weather"].ok and "timed out" in d["weather"].error
    assert d["calendar"].ok

    def cal_down(url):
        if url.endswith(".ics"):
            raise ConnectionError("refused")
        return json.dumps(weather_json()).encode()
    d = daily.build(SETTINGS, ctx(cal_down))
    assert d["weather"].ok and not d["calendar"].ok


def test_partial_calendar_failure_is_reported_not_fatal():
    s = {**SETTINGS, "calendars": ["http://cal/a.ics", "http://cal/broken.ics"]}
    http = lambda u: (b"not ical" if "broken" in u else fake_http(u))  # noqa: E731
    d = daily.build(s, ctx(http))
    assert d["calendar"].ok and d["calendar"].data["failed"] == 1


def test_missing_location_and_calendars_explain_themselves():
    d = daily.build({}, ctx(fake_http))
    assert not d["weather"].ok and "latitude" in d["weather"].error
    assert not d["calendar"].ok and "no calendars" in d["calendar"].error


def test_cache_serves_stale_data_when_a_refresh_fails():
    t = [0.0]
    cache = SourceCache(clock=lambda: t[0])
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) > 2:
            raise TimeoutError("down")
        return fake_http(url)
    daily.build(SETTINGS, ctx(flaky, cache=cache))
    t[0] = 10 * 3600  # long after both TTLs
    d = daily.build(SETTINGS, ctx(flaky, cache=cache))
    assert d["weather"].ok and d["weather"].stale


def test_secret_calendar_url_never_reaches_the_page():
    s = {**SETTINGS, "calendars": ["http://cal/private-token-abc123.ics"]}
    html = boards.render_html("daily", s, ctx(lambda u: ICS if u.endswith(".ics") else fake_http(u)))
    assert "private-token-abc123" not in html


def test_untrusted_text_is_escaped():
    html = boards.render_html("daily", SETTINGS, ctx(fake_http))
    assert "<script>" not in html and "&lt;script&gt;" in html


@pytest.mark.parametrize("w,h", [(W, H), (H, W)])
def test_template_renders_every_state(w, h):
    for http in (fake_http, lambda u: (_ for _ in ()).throw(OSError("offline"))):
        html = boards.render_html("daily", SETTINGS, ctx(http, w=w, h=h))
        assert "Wednesday" in html and ("landscape" if w > h else "portrait") in html


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:  # noqa: BLE001
        return False


needs_chromium = pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not installed")


@needs_chromium
@pytest.mark.parametrize("orient", ["portrait", "left"])
def test_real_render_both_orientations(tmp_path, orient, monkeypatch):
    from kindaframe.render import Renderer

    cfg = config.parse({"mode": "dashboard", "timezone": "Asia/Tokyo", "boards": {"daily": SETTINGS}},
                       state_dir=tmp_path)
    r = Renderer(cfg)
    monkeypatch.setattr(BoardContext, "get", lambda self, url: fake_http(url))
    r.battery = 79
    f = r.render(W, H, orient=orient)
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(f.png))
    assert img.size == (W, H) and f.mode == "dashboard" and f.source == "daily"
    assert grey16.levels_used(img) <= set(grey16.LEVELS)
    ink = sum(n for v, n in enumerate(img.histogram()) if v < 128) / (W * H)
    assert 0.01 < ink < 0.35, ink  # text and lines, mostly paper
    out = Path(__file__).parent.parent / ".pytest_cache" / f"daily-{orient}.png"
    out.parent.mkdir(exist_ok=True)
    img.save(out)  # for eyeballing during development
