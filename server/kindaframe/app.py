"""HTTP layer: GET /frame.png and GET /healthz, per specs/001-sleep-screen-frame/contracts/frame-api.md.

Run with: uvicorn --factory kindaframe.app:create_app
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import config as config_mod
from .config import Config
from .render import FrameCache, NoContent, Renderer

MIN_SIDE, MAX_SIDE = 100, 4000


def _int(params, key: str) -> int | None:
    raw = params.get(key)
    if raw is None or raw == "":
        return None
    return int(raw)  # ValueError -> 400 by the caller


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or config_mod.load()
    renderer = Renderer(cfg)
    cache = FrameCache(renderer)
    app = FastAPI(title="kinda-frame", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cache = cache

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
        gen = q.get("art")
        try:
            if gen or seed is not None:
                f = renderer.render(w, h, generator=gen, seed=seed)
            else:
                f = cache.get(w, h)
        except KeyError:
            return JSONResponse({"error": f"unknown art generator {gen!r}"}, status_code=400)
        except NoContent as e:
            return JSONResponse({"error": str(e)}, status_code=503, headers={"Retry-After": "300"})
        headers = {
            "Cache-Control": "no-store",
            "X-Frame-Mode": f.mode,
            "X-Frame-Source": f.source,
            "X-Rendered-At": f.rendered_at.isoformat(timespec="seconds"),
        }
        if f.seed is not None:
            headers["X-Frame-Seed"] = str(f.seed)
        return Response(f.png, media_type="image/png", headers=headers)

    @app.get("/healthz")
    def healthz():
        last = cache.last
        return {
            "status": "ok",
            "mode": cfg.mode,
            "generators": list(cfg.art.generators) if cfg.mode == "art" else None,
            "last_render": last.rendered_at.isoformat(timespec="seconds") if last else None,
            "last_source": last.source if last else None,
        }

    return app
