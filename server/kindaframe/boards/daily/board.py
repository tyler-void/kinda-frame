"""The daily board: date, today's weather, today's (and tomorrow's) calendar, battery.

Content is chosen to stay valid for hours on a sleeping Kindle (spec FR-017a): the day, the
day's forecast and the day's agenda, plus the time the frame was rendered. No live clock.

Sources:
  weather   Open-Meteo forecast API (free, no key). Needs latitude/longitude (private config).
  calendar  Any number of ICS URLs (e.g. Google Calendar "secret address in iCal format").
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from typing import Any

from ..base import BoardContext, Section

NAME = "daily"
TEMPLATE = "template.html"

WEATHER_TTL = 30 * 60
CALENDAR_TTL = 15 * 60
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes (Open-Meteo docs) -> (label, icon)
WMO: dict[int, tuple[str, str]] = {
    0: ("Clear", "clear"), 1: ("Mainly clear", "clear"), 2: ("Partly cloudy", "partly"), 3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"), 48: ("Rime fog", "fog"),
    51: ("Light drizzle", "drizzle"), 53: ("Drizzle", "drizzle"), 55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"), 57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"), 81: ("Rain showers", "rain"), 82: ("Violent showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm, hail", "storm"), 99: ("Thunderstorm, hail", "storm"),
}


def wmo(code: Any) -> tuple[str, str]:
    try:
        return WMO.get(int(code), ("Unknown", "cloudy"))
    except (TypeError, ValueError):
        return ("Unknown", "cloudy")


# ----------------------------------------------------------------------------- weather
def weather_url(lat: float, lon: float, tz: str, units: str) -> str:
    q = (f"latitude={lat:.4f}&longitude={lon:.4f}&timezone={tz}&forecast_days=2"
         "&current=temperature_2m,apparent_temperature,weather_code,is_day"
         "&hourly=temperature_2m,precipitation_probability,weather_code,is_day"
         "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset")
    if units == "imperial":
        q += "&temperature_unit=fahrenheit"
    return f"{OPEN_METEO}?{q}"


NIGHT = {"clear": "clear_night", "partly": "partly_night"}


def night(icon: str, is_day) -> str:
    """Moon instead of sun after dark (Open-Meteo is_day = 0). Other conditions look the same at night."""
    return NIGHT.get(icon, icon) if is_day == 0 else icon


def parse_weather(raw: dict, now: datetime) -> dict:
    cur, daily, hourly = raw["current"], raw["daily"], raw["hourly"]

    def day(i: int) -> dict:
        label, icon = wmo(daily["weather_code"][i])
        return {
            "label": label, "icon": icon,
            "hi": round(daily["temperature_2m_max"][i]), "lo": round(daily["temperature_2m_min"][i]),
            "rain": daily["precipitation_probability_max"][i],
            "sunrise": daily["sunrise"][i][-5:], "sunset": daily["sunset"][i][-5:],
        }

    label, icon = wmo(cur["weather_code"])
    icon = night(icon, cur.get("is_day"))
    hourly_day = hourly.get("is_day") or [1] * len(hourly["time"])
    # Next ~15 h at 3-hour steps, starting from the current hour.
    start = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    times = [datetime.fromisoformat(t) for t in hourly["time"]]
    steps = []
    for i, t in enumerate(times):
        if t >= start and (t - start).total_seconds() % (3 * 3600) == 0 and len(steps) < 6:
            steps.append({
                "time": t.strftime("%H:%M"),
                "temp": round(hourly["temperature_2m"][i]),
                "rain": hourly["precipitation_probability"][i],
                "icon": night(wmo(hourly["weather_code"][i])[1], hourly_day[i]),
            })
    return {
        "now": {"temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
                "label": label, "icon": icon},
        "today": day(0), "tomorrow": day(1), "hours": steps,
    }


# ----------------------------------------------------------------------------- calendar
def _as_local(v: date | datetime, tz) -> tuple[datetime, bool]:
    """Return (local datetime, all_day)."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=tz)
        return v.astimezone(tz), False
    return datetime.combine(v, time.min, tz), True


def parse_calendar(ics: bytes, day_start: datetime, days: int, tz) -> list[dict]:
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(ics)
    end = day_start + timedelta(days=days)
    events = []
    for ev in recurring_ical_events.of(cal).between(day_start, end):
        start, all_day = _as_local(ev.get("DTSTART").dt, tz)
        dtend = ev.get("DTEND")
        stop = _as_local(dtend.dt, tz)[0] if dtend else start
        events.append({
            "title": str(ev.get("SUMMARY", "(no title)")).strip() or "(no title)",
            "location": str(ev.get("LOCATION", "")).strip(),
            "start": start, "end": stop, "all_day": all_day,
        })
    return events


def agenda(events: list[dict], day: date, tz) -> list[dict]:
    """Events overlapping `day`, all-day first, then by start time, with display strings."""
    lo = datetime.combine(day, time.min, tz)
    hi = lo + timedelta(days=1)
    out = []
    for e in events:
        if e["start"] < hi and (e["end"] > lo or (e["end"] == e["start"] and e["start"] >= lo)):
            when = "all day" if e["all_day"] else (
                e["start"].strftime("%H:%M") + ("–" + e["end"].strftime("%H:%M") if e["end"] > e["start"] else ""))
            out.append({**e, "when": when})
    out.sort(key=lambda e: (not e["all_day"], e["start"], e["title"]))
    return out


# ----------------------------------------------------------------------------- board
def build(settings: dict, ctx: BoardContext) -> dict:
    now = ctx.now
    today = now.date()
    tz_name = str(ctx.tz.key)

    # Weather
    lat, lon = settings.get("latitude"), settings.get("longitude")
    if lat is None or lon is None:
        weather = Section(False, error="set latitude/longitude in config.toml")
    else:
        units = settings.get("units", "metric")
        url = weather_url(float(lat), float(lon), tz_name, units)
        weather = ctx.source(f"weather:{lat},{lon},{units}", WEATHER_TTL, lambda: json.loads(ctx.get(url)))
        if weather.ok:
            try:
                weather = Section(True, parse_weather(weather.data, now), weather.error, weather.stale)
            except (KeyError, IndexError, TypeError, ValueError) as e:
                weather = Section(False, error=f"unexpected weather data ({type(e).__name__})")

    # Calendars (each URL is its own cached source; partial failures are reported, not fatal)
    urls = list(settings.get("calendars", []))
    day_start = datetime.combine(today, time.min, ctx.tz)
    events: list[dict] = []
    failed = 0
    for url in urls:
        key = "ics:" + hashlib.sha256(url.encode()).hexdigest()[:16]  # never log/show the secret URL
        sec = ctx.source(key, CALENDAR_TTL, lambda u=url: ctx.get(u))
        if not sec.ok:
            failed += 1
            continue
        try:
            events += parse_calendar(sec.data, day_start, 2, ctx.tz)
        except Exception:  # noqa: BLE001 - a malformed feed is one failed calendar
            failed += 1
    if not urls:
        calendar = Section(False, error="no calendars configured")
    elif failed == len(urls):
        calendar = Section(False, error="calendar unavailable")
    else:
        calendar = Section(True, {
            "today": agenda(events, today, ctx.tz),
            "tomorrow": agenda(events, today + timedelta(days=1), ctx.tz)[:4],
            "failed": failed,
        })

    return {
        "date": {
            "weekday": now.strftime("%A"), "day": now.day, "month": now.strftime("%B"),
            "year": now.year, "week": now.isocalendar().week,
            "tomorrow": (now + timedelta(days=1)).strftime("%A"),
        },
        "location": settings.get("location_label", ""),
        "units": "°F" if settings.get("units") == "imperial" else "°C",
        "weather": weather,
        "calendar": calendar,
    }
