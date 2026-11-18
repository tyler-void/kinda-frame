"""Dashboard board registry (FR-017): adding a board = a new folder here + one line below."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .base import BoardContext, Section, SourceCache
from .daily import board as daily

BOARDS = {daily.NAME: daily}

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent)),
    autoescape=select_autoescape(["html"]),  # calendar/RSS text is untrusted
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_html(name: str, settings: dict, ctx: BoardContext) -> str:
    board = BOARDS[name]
    data = board.build(settings, ctx)
    landscape = ctx.w > ctx.h
    return _ENV.get_template(f"{name}/{board.TEMPLATE}").render(
        **data,
        board=name,
        battery=ctx.battery,
        rendered=ctx.now.strftime("%a %H:%M"),
        landscape=landscape,
        max_events=6 if landscape else 8,
    )


__all__ = ["BOARDS", "BoardContext", "Section", "SourceCache", "render_html"]
