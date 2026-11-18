"""LAN settings page: GET/POST /settings, POST /settings/reset, GET /preview.png.

No login (LAN-only service, like the frame endpoint), but:
  * state-changing requests must come from this page (Origin/Referer host == Host), so a web page
    you visit elsewhere can't silently change the frame (CSRF);
  * calendar URLs are secrets: shown masked, never echoed back in full; they can only be removed
    or added;
  * every save is validated (ConfigStore.save) before anything is written.
"""

from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config as config_mod
from .config import ALL_GENERATORS, CONTENT_MODES, Config, hhmm
from . import photo as photo_mod
from .imaging import grey16
from .imaging.orient import ORIENTS
from .render import NoContent, Renderer
from .settings_store import ConfigStore

_ENV = Environment(loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
                   autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)

MODE_LABELS = {
    "art": "Generative art",
    "photo": "Photos",
    "dashboard": "Daily dashboard",
    "mixed": "Mixed (schedule or alternate)",
}
GEN_LABELS = {"chladni": "Chladni figures", "flowfield": "Flow fields",
              "attractor": "Strange attractors", "orbits": "Orbits (harmonograph / epicycles)"}


def mask(url: str) -> str:
    p = urlparse(url)
    tail = url[-6:] if len(url) > 12 else ""
    return f"{p.scheme}://{p.netloc}/…{tail}"


def same_origin(request: Request) -> bool:
    host = request.headers.get("host", "")
    src = request.headers.get("origin") or request.headers.get("referer") or ""
    return bool(host) and urlparse(src).netloc == host


def _one(form: dict, key: str, default: str = "") -> str:
    return (form.get(key) or [default])[0].strip()


def form_to_overrides(form: dict, cfg: Config) -> dict:
    """Turn the posted form into a complete override set for the keys this page manages."""
    daily = cfg.boards.get("daily", {})
    # Calendars: keep current ones unless ticked for removal, add the new one.
    cals = [u for i, u in enumerate(daily.get("calendars", [])) if f"cal_remove_{i}" not in form]
    new = _one(form, "cal_add")
    if new:
        if new.startswith("webcal://"):
            new = "https://" + new[len("webcal://"):]
        if not new.startswith(("http://", "https://")):
            raise config_mod.ConfigError("calendar URL must start with https:// (or webcal://)")
        cals.append(new)

    def coord(key: str, lo: float, hi: float):
        raw = _one(form, key)
        if not raw:
            return None
        try:
            v = float(raw.replace(",", "."))
        except ValueError:
            raise config_mod.ConfigError(f"{key} must be a number") from None
        if not lo <= v <= hi:
            raise config_mod.ConfigError(f"{key} must be between {lo} and {hi}")
        return round(v, 4)

    schedule = []
    i = 0
    while f"sched_from_{i}" in form:
        start = _one(form, f"sched_from_{i}")
        if start:
            schedule.append({"from": start, "mode": _one(form, f"sched_mode_{i}", "art")})
        i += 1

    return {
        "mode": _one(form, "mode", cfg.mode),
        "timezone": _one(form, "timezone", cfg.timezone) or "Etc/UTC",
        "mixed": {
            "strategy": _one(form, "mixed_strategy", cfg.mixed.strategy),
            "modes": form.get("alt_modes", []),
            "schedule": schedule,
        },
        "art": {"generators": form.get("art_gen", []), "order": _one(form, "art_order", cfg.art.order)},
        "photo": {"order": _one(form, "photo_order", cfg.photo.order), "fit": _one(form, "photo_fit", cfg.photo.fit)},
        "dashboard": {"board": "daily"},
        "boards": {"daily": {
            "location_label": _one(form, "location_label"),
            "latitude": coord("latitude", -90, 90),
            "longitude": coord("longitude", -180, 180),
            "units": _one(form, "units", "metric"),
            "calendars": cals,
        }},
    }


def install(app: FastAPI, store: ConfigStore, renderer: Renderer, status: dict) -> None:
    def photo_list() -> list[dict]:
        cfg = store.current
        out = [{"name": p.name, "src": "folder"} for p in photo_mod.list_photos(cfg.photo.dir)]
        out += [{"name": p.name, "src": "uploads"} for p in photo_mod.list_photos(photo_mod.uploads_dir(cfg.state_dir))]
        return out

    def photo_path(src: str, name: str):
        cfg = store.current
        folder = cfg.photo.dir if src == "folder" else photo_mod.uploads_dir(cfg.state_dir)
        for p in photo_mod.list_photos(folder):  # only files that are actually listed: no path tricks
            if p.name == name:
                return p
        return None

    def page(request: Request, error: str | None = None, code: int = 200) -> HTMLResponse:
        cfg = store.current
        daily = cfg.boards.get("daily", {})
        if cfg.mode == "mixed":
            previews = list(dict.fromkeys(m for _, m in cfg.mixed.schedule)) if cfg.mixed.strategy == "schedule" \
                else list(cfg.mixed.modes)
        else:
            previews = [cfg.mode]
        html = _ENV.get_template("settings.html").render(
            cfg=cfg, daily=daily, error=error, saved="saved" in request.query_params,
            modes=MODE_LABELS, content_modes=CONTENT_MODES, generators=ALL_GENERATORS, gen_labels=GEN_LABELS,
            schedule=[(hhmm(s), m) for s, m in cfg.mixed.schedule] + [("", "art")],
            calendars=[mask(u) for u in daily.get("calendars", [])],
            planned=renderer.planned_mode(), previews=previews, status=status,
            has_overrides=bool(store.overrides()),
            photos=photo_list(),
            max_upload_mb=photo_mod.MAX_UPLOAD // (1024 * 1024),
            base_error=store.base_error,
        )
        return HTMLResponse(html, status_code=code, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def root():
        return RedirectResponse("/settings", status_code=303)

    @app.get("/settings")
    def get_settings(request: Request):
        return page(request)

    @app.post("/settings")
    async def post_settings(request: Request):
        if not same_origin(request):
            return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
        form = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
        try:
            store.save(form_to_overrides(form, store.current))
        except config_mod.ConfigError as e:
            return page(request, error=str(e), code=400)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.post("/settings/reset")
    def reset(request: Request):
        if not same_origin(request):
            return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
        store.reset()
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.post("/photos/upload")
    async def upload(request: Request):
        if not same_origin(request):
            return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
        if int(request.headers.get("content-length") or 0) > photo_mod.MAX_UPLOAD:
            return JSONResponse({"error": "file larger than 30 MB"}, status_code=413)
        data = await request.body()
        try:
            saved = photo_mod.save_upload(store.current.state_dir, request.query_params.get("name", "photo"), data)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"ok": True, "name": saved.name}

    @app.post("/photos/delete")
    async def delete_photo(request: Request):
        if not same_origin(request):
            return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        photo_mod.delete_upload(store.current.state_dir, _one(form, "name"))
        return RedirectResponse("/settings?saved=1#photos", status_code=303)

    @app.get("/photos/thumb")
    def thumb(src: str = "uploads", name: str = ""):
        p = photo_path(src, name)
        if p is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        from PIL import Image, ImageOps

        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((240, 240))
            buf = io.BytesIO()
            im.convert("L").save(buf, format="JPEG", quality=80)  # greyscale: roughly what the Kindle will show
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/preview.png")
    def preview(request: Request):
        q = request.query_params
        mode = q.get("mode") or renderer.planned_mode() or "art"
        orient = q.get("orient") or status.get("orient") or "portrait"
        if mode not in CONTENT_MODES or orient not in ORIENTS:
            return JSONResponse({"error": "bad mode/orient"}, status_code=400)
        w, h = status.get("size") or (1072, 1448)
        try:
            f = renderer.render(w, h, orient=orient, mode=mode)  # bypasses the cache: the Kindle's next frame is untouched
        except NoContent as e:
            return JSONResponse({"error": str(e)}, status_code=503)
        # Show it the way the viewer sees it (undo the buffer rotation) at half size for the page.
        from PIL import Image

        img = Image.open(io.BytesIO(f.png))
        inverse = {"left": Image.Transpose.ROTATE_90, "right": Image.Transpose.ROTATE_270}.get(orient)
        if inverse is not None:
            img = img.transpose(inverse)
        img = img.resize((img.width // 2, img.height // 2), Image.Resampling.LANCZOS)
        return Response(grey16.to_png(img), media_type="image/png", headers={"Cache-Control": "no-store"})
