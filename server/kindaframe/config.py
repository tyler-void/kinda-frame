"""Server configuration (data-model.md "Server configuration").

Read from the TOML file named by $KF_CONFIG (default /app/config.toml). The real file is private
and never committed; config.example.toml documents every key. A missing file means defaults
(art mode with all generators), so the container is useful out of the box.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

MODES = ("art", "photo", "dashboard", "mixed")
CONTENT_MODES = ("art", "photo", "dashboard")  # what "mixed" chooses between
ALL_GENERATORS = ("chladni", "flowfield", "attractor", "orbits")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ArtConfig:
    generators: tuple[str, ...] = ALL_GENERATORS
    order: str = "random"  # random (no immediate repeats) | cycle


@dataclass(frozen=True)
class PhotoConfig:
    dir: Path = Path("/photos")
    order: str = "random"  # random | sequential
    fit: str = "crop"  # crop | pad


@dataclass(frozen=True)
class MixedConfig:
    """mode = "mixed": switch between content modes on a daily schedule, or alternate every sleep."""

    strategy: str = "schedule"  # schedule | alternate
    modes: tuple[str, ...] = ("dashboard", "art")  # used by "alternate"
    # (minute of day, mode), sorted. Each entry applies from its time until the next one (wrapping at midnight).
    schedule: tuple[tuple[int, str], ...] = ((6 * 60, "dashboard"), (21 * 60, "art"))

    def mode_at(self, minute_of_day: int) -> str:
        current = self.schedule[-1][1]  # before the first entry: the last one is still running from yesterday
        for start, mode in self.schedule:
            if minute_of_day >= start:
                current = mode
        return current


def _minutes(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        h, m = int(h), int(m)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
        return h * 60 + m
    except ValueError:
        raise ConfigError(f"time must be HH:MM (got {hhmm!r})") from None


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Config:
    mode: str = "art"
    art: ArtConfig = field(default_factory=ArtConfig)
    photo: PhotoConfig = field(default_factory=PhotoConfig)
    state_dir: Path = Path("/state")
    timezone: str = "Etc/UTC"
    board: str = "daily"  # [dashboard].board
    boards: dict = field(default_factory=dict)  # [boards.<name>] settings, passed to the board as-is
    mixed: MixedConfig = field(default_factory=MixedConfig)


def _choice(value: str, allowed: tuple[str, ...], key: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{key} must be one of {', '.join(allowed)} (got {value!r})")
    return value


def parse(data: dict, state_dir: Path | None = None) -> Config:
    art = data.get("art", {})
    photo = data.get("photo", {})
    gens = tuple(art.get("generators", ALL_GENERATORS))
    unknown = [g for g in gens if g not in ALL_GENERATORS]
    if unknown or not gens:
        raise ConfigError(f"art.generators must be a non-empty subset of {ALL_GENERATORS} (bad: {unknown})")
    tz = data.get("timezone", "Etc/UTC")
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except Exception as e:  # noqa: BLE001
        raise ConfigError(f"timezone {tz!r} is not a valid IANA zone") from e
    from .boards import BOARDS  # local import: boards pull in jinja2/httpx

    board = data.get("dashboard", {}).get("board", "daily")
    if board not in BOARDS:
        raise ConfigError(f"dashboard.board must be one of {', '.join(BOARDS)} (got {board!r})")
    mx = data.get("mixed", {})
    strategy = _choice(mx.get("strategy", "schedule"), ("schedule", "alternate"), "mixed.strategy")
    alt = tuple(mx.get("modes", ("dashboard", "art")))
    if not alt or any(m not in CONTENT_MODES for m in alt):
        raise ConfigError(f"mixed.modes must be a non-empty list of {CONTENT_MODES}")
    sched_raw = mx.get("schedule", [{"from": "06:00", "mode": "dashboard"}, {"from": "21:00", "mode": "art"}])
    sched = []
    for entry in sched_raw:
        sched.append((_minutes(entry.get("from", "")), _choice(entry.get("mode", ""), CONTENT_MODES, "mixed.schedule.mode")))
    if not sched:
        raise ConfigError("mixed.schedule needs at least one entry")
    sched.sort()
    if len({s for s, _ in sched}) != len(sched):
        raise ConfigError("mixed.schedule has two entries at the same time")
    return Config(
        mixed=MixedConfig(strategy=strategy, modes=alt, schedule=tuple(sched)),
        timezone=tz,
        board=board,
        boards={k: dict(v) for k, v in data.get("boards", {}).items()},
        mode=_choice(data.get("mode", "art"), MODES, "mode"),
        art=ArtConfig(generators=gens, order=_choice(art.get("order", "random"), ("random", "cycle"), "art.order")),
        photo=PhotoConfig(
            dir=Path(photo.get("dir", "/photos")),
            order=_choice(photo.get("order", "random"), ("random", "sequential"), "photo.order"),
            fit=_choice(photo.get("fit", "crop"), ("crop", "pad"), "photo.fit"),
        ),
        state_dir=state_dir or Path(os.environ.get("KF_STATE", "/state")),
    )


def load(path: str | os.PathLike | None = None) -> Config:
    p = Path(path or os.environ.get("KF_CONFIG", "/app/config.toml"))
    if not p.is_file():
        return parse({})
    with p.open("rb") as f:
        return parse(tomllib.load(f))
