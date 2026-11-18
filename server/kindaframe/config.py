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

MODES = ("art", "photo")  # "dashboard" arrives with M3b
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
class Config:
    mode: str = "art"
    art: ArtConfig = field(default_factory=ArtConfig)
    photo: PhotoConfig = field(default_factory=PhotoConfig)
    state_dir: Path = Path("/state")


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
    return Config(
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
