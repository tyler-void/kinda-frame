"""HTTP layer: GET /frame.png and GET /healthz, per specs/001-sleep-screen-frame/contracts/frame-api.md.

Run with: uvicorn --factory kindaframe.app:create_app
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import web
from .config import Config
from .imaging.orient import ORIENTS
from .render import FrameCache, NoContent, Renderer
from .settings_store import ConfigStore

MIN_SIDE, MAX_SIDE = 100, 4000


def _int(params, key: str) -> int | None:
    raw = params.get(key)
    if raw is None or raw == "":
        return None
    return int(raw)  # ValueError -> 400 by the caller


def create_app(cfg: Config | None = None, store: ConfigStore | None = None) -> FastAPI:
    """With `cfg` only (tests): fixed config, no settings page. Otherwise config.toml + saved overrides."""
    if cfg is None:
        store = store or ConfigStore()
        cfg = store.current
    renderer = Renderer(cfg)
    cache = FrameCache(renderer)
    status: dict = {"last": None, "battery": None, "orient": None, "size": None}
    app = FastAPI(title="kinda-frame", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cache = cache
    if store is not None:
        def apply(new_cfg: Config) -> None:
            renderer.reconfigure(new_cfg)
            cache.clear()  # prepared frames were made with the old settings
        store.on_change(apply)
        web.install(app, store, renderer, status)

    @app.get("/frame.png")
    def frame(request: Request):
        q = request.query_params
        try:
            w, h = _int(q, "w"), _int(q, "h")
            seed = _int(q, "seed")  # debug override (art mode)
            batt = _int(q, "batt")  # accepted; used by dashboard boards (M3b)
        except ValueError:
            return JSONResponse({"error": "w, h, batt and seed must be integers"}, status_code=400)
        if w is None or h is None:
            return JSONResponse({"error": "w and h are required"}, status_code=400)
        if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
            return JSONResponse({"error": f"w and h must be within {MIN_SIDE}..{MAX_SIDE}"}, status_code=400)
        if batt is not None and not 0 <= batt <= 100:
            batt = None  # unknown battery value: ignore, don't fail the frame
        if batt is not None:
            renderer.battery = batt  # boards show the latest reported level
            status["battery"] = batt
        orient = q.get("orient") or "portrait"
        if orient not in ORIENTS:
            return JSONResponse({"error": f"orient must be one of {', '.join(ORIENTS)}"}, status_code=400)
        gen = q.get("art")
        try:
            if gen or seed is not None:
                f = renderer.render(w, h, generator=gen, seed=seed, orient=orient)
            else:
                f = cache.get(w, h, orient)
        except KeyError:
            return JSONResponse({"error": f"unknown art generator {gen!r}"}, status_code=400)
        except NoContent as e:
            return JSONResponse({"error": str(e)}, status_code=503, headers={"Retry-After": "300"})
        if not (gen or seed is not None):  # real device requests, not debug renders
            local = f.rendered_at.astimezone(ZoneInfo(renderer.cfg.timezone))
            status.update(orient=orient, size=(w, h), last=f"{f.source} · {local.strftime('%a %H:%M')}")
        headers = {
            "Cache-Control": "no-store",
            "X-Frame-Mode": f.mode,
            "X-Frame-Source": f.source,
            "X-Frame-Orient": f.orient,
            "X-Rendered-At": f.rendered_at.isoformat(timespec="seconds"),
        }
        if f.seed is not None:
            headers["X-Frame-Seed"] = str(f.seed)
        return Response(f.png, media_type="image/png", headers=headers)

    @app.get("/healthz")
    def healthz():
        last = cache.last
        c = renderer.cfg
        return {
            "status": "ok",
            "mode": c.mode,
            "now": renderer.planned_mode(),
            "config_error": store.base_error if store is not None else None,
            "generators": list(c.art.generators) if c.mode in ("art", "mixed") else None,
            "board": c.board if c.mode in ("dashboard", "mixed") else None,
            "last_render": last.rendered_at.isoformat(timespec="seconds") if last else None,
            "last_source": last.source if last else None,
        }

    return app
