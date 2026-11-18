"""Effective configuration = the hand-written config.toml (base) + overrides saved from the web page.

Overrides live in the state volume (/state/settings.json, JSON because the stdlib can't write TOML)
and win over the base. Lists are replaced, tables are merged. Every save is validated by parsing
the merged result first, then written atomically (temp file + rename).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import tomllib
from pathlib import Path

from . import config as config_mod
from .config import Config

log = logging.getLogger(__name__)


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class ConfigStore:
    def __init__(self, base_path: str | os.PathLike | None = None, state_dir: str | os.PathLike | None = None):
        self.base_path = Path(base_path or os.environ.get("KF_CONFIG", "/app/config.toml"))
        self.state_dir = Path(state_dir or os.environ.get("KF_STATE", "/state"))
        self.overrides_path = self.state_dir / "settings.json"
        self._lock = threading.Lock()
        self._listeners = []
        self.base_error: str | None = None  # shown on the settings page and in /healthz
        self._current = self._build()

    # -- reading
    def base(self) -> dict:
        """The hand-written config. Unreadable or invalid TOML never crashes the server: defaults instead."""
        if not self.base_path.is_file():
            self.base_error = None
            return {}
        try:
            with self.base_path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            self.base_error = f"config.toml ignored: {type(e).__name__}: {e}"[:200]
            log.error(self.base_error)
            return {}
        self.base_error = None
        return data

    def overrides(self) -> dict:
        try:
            return json.loads(self.overrides_path.read_text())
        except (OSError, ValueError):
            return {}

    def merged(self) -> dict:
        return deep_merge(self.base(), self.overrides())

    def _build(self) -> Config:
        try:
            return config_mod.parse(self.merged(), state_dir=self.state_dir)
        except config_mod.ConfigError as e:
            # A bad override must never take the frame down: fall back to the base file alone,
            # and if the base itself is invalid, to the built-in defaults.
            log.error("settings ignored: %s", e)
            try:
                return config_mod.parse(self.base(), state_dir=self.state_dir)
            except config_mod.ConfigError as e2:
                self.base_error = f"config.toml ignored: {e2}"
                log.error(self.base_error)
                return config_mod.parse({}, state_dir=self.state_dir)

    @property
    def current(self) -> Config:
        return self._current

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    # -- writing
    def save(self, overrides: dict) -> Config:
        """Validate base + overrides, then persist. Raises ConfigError (nothing written) if invalid."""
        with self._lock:
            cfg = config_mod.parse(deep_merge(self.base(), overrides), state_dir=self.state_dir)
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.overrides_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(overrides, indent=2, sort_keys=True))
            os.chmod(tmp, 0o600)  # may hold secret calendar URLs
            tmp.replace(self.overrides_path)
            self._current = cfg
        for fn in self._listeners:
            fn(cfg)
        return cfg

    def reset(self) -> Config:
        with self._lock:
            try:
                self.overrides_path.unlink()
            except FileNotFoundError:
                pass
            self._current = config_mod.parse(self.base(), state_dir=self.state_dir)
        for fn in self._listeners:
            fn(self._current)
        return self._current
