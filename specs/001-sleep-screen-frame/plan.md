# Implementation Plan: Sleep-Screen Frame

**Branch**: `001-sleep-screen-frame` | **Date**: 2026-11-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-sleep-screen-frame/spec.md`. Engineering detail is in `SPEC.md` (rev. 6).

> **No `tasks.md` for this feature** (owner's decision). The milestones in §Delivery below replace the task phase. Each one has an exit gate taken from the spec's success criteria.

## Summary

A KOReader plugin (`kindaframe.koplugin`) on the Kindle and a renderer container on `home-server`.

1. KOReader's sleep screen is pointed at `/mnt/us/kinda-frame/current.png` ("image file" mode). Every sleep therefore shows the last saved frame instantly, with no code.
2. On `onSuspend`, the plugin brings Wi-Fi up without any UI, downloads a new frame in a child process within `min(budget, measured window − margin)`, validates it, renames it into place, and, if it differs, redraws the sleep screen before the framework suspends. On `onResume` it cancels and restores Wi-Fi.
3. The server (FastAPI + numpy + Pillow; Playwright joins in M3b) serves a pre-rendered, 16-grey frame at the requested size: generative art first (owner has no photos yet; `docs/art.md`), photo mode alongside, then dashboard boards (daily → RSS / trends / …).

Phase 0 (device probe) is a **hard gate**. Research R0 (KOReader skips its sleep screen on Special Offers Kindles), R2 (window length) and R5 (redraw sequence) must be confirmed on the device before plugin code is written.

## Technical Context

**Language/Version**: Lua (LuaJIT 2.1, as embedded in KOReader v2026.07.2, the tested version) for the plugin; Python 3.12 for the server
**Primary Dependencies**: Plugin: KOReader APIs only (`WidgetContainer`, `UIManager`, `NetworkMgr`, `Screensaver`, `ffi/util` subprocesses, `socket.http` + `socketutil`). Server: FastAPI, uvicorn, Pillow, Playwright (Chromium), Jinja2, httpx, icalendar + recurring-ical-events; later feedparser
**Storage**: Files only. Kindle: `/mnt/us/kinda-frame/` (frame, log, backups) plus KOReader settings keys `kindaframe_*`. Server: `config.toml` (uncommitted), photo folder (read-only mount), `/state` volume
**Testing**: dependency-free busted-style runner `luajit spec/run.lua` (pure `kf/` modules + `main.lua` scenarios against stubbed KOReader: virtual clock, fake Wi-Fi, fake child process, fake HTTP), mutation-checked; `pytest` (server); manual on-device scenarios in `quickstart.md`
**Target Platform**: Kindle Paperwhite 4, FW 5.18.1 hard-float, KOReader v2026.07.2; `home-server` Docker (linux/amd64)
**Project Type**: Device plugin + LAN web service (two deployables, one repo)
**Performance Goals**: Saved frame visible ≤ ~1 s after pressing power (SC-001); server answers `/frame.png` in < 1 s when pre-rendered, cold render < 5 s (SC-008); Wi-Fi + fetch fits the measured window (about 60 s SCREEN SAVER + about 10 s READY TO SUSPEND, measured)
**Constraints**: Never block suspend or the KOReader UI loop; no UI pop-ups during sleep; Wi-Fi state restored; ≤ 20 % extra daily battery (SC-004); LAN-only, IP-address server URL; no writes outside `/mnt/us/`; no secrets or private data in git
**Scale/Scope**: One device, one owner, one server. Plugin of about 500 lines of Lua; server of about 1.5k lines of Python plus templates

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the **unfilled template**, so there are no ratified principles to check against. Until `/speckit-constitution` is run, the binding rules are **SPEC.md §5 (Safety rules)**, which the spec carries as FR-022 to FR-025. They're checked here instead:

| Gate (SPEC.md §5) | Design status |
|---|---|
| 1. Read-only diagnostics first | ✅ Milestone M0 is read-only; every device write in later milestones has a stated precondition check |
| 2. No `mntroot rw`; writes only in `/mnt/us/` | ✅ Plugin dir + `/mnt/us/kinda-frame/` only; no upstart/autostart work in this feature |
| 3. Back up KOReader settings; edit only when KOReader is closed or via the menu | ✅ M1 backup step + `restore.md` |
| 4. Graceful failure, never block suspend | ✅ Child-process fetch, poll-only parent, generation counter, single Wi-Fi restore path (data-model state machine) |
| 5. Wi-Fi toggling only; don't touch KUAL/KindleForge/KOReader core/hotfix/firmware | ✅ Uses `restoreWifiAsync` + disable only; the plugin lives in `plugins/` and doesn't patch KOReader |
| 6. home-server: own container, don't touch others | ✅ Separate compose project `kinda-frame`; no daemon restarts; LAN-bound port |
| 7. Privacy | ✅ `config.toml`, `.env` and photos are git-ignored; examples use placeholders; LAN details stay in SPEC.md only while the repo is private |
| 8. Licensing | ✅ Ideas only from re-kindle (no licence) and ReKindle (CC BY-NC-SA); MIT code (trmnl-koreader, ktrm, kindle-dash) only with attribution |

**Result: PASS** (pre- and post-design). Recommendation: run `/speckit-constitution` to turn §5 into ratified principles, so future features are gated properly.

## Project Structure

### Documentation (this feature)

```text
specs/001-sleep-screen-frame/
├── spec.md              # Feature spec (/speckit-specify)
├── plan.md              # This file
├── research.md          # R0–R9 findings and decisions
├── data-model.md        # Entities, settings keys, fetch state machine
├── quickstart.md        # Probe, install, verify, restore
├── contracts/
│   └── frame-api.md     # GET /frame.png, /healthz
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
plugin/kindaframe.koplugin/          # deployed to /mnt/us/koreader/plugins/
├── _meta.lua                        # name, description
├── main.lua                         # KOReader glue: onSuspend/onResume, menu, Screensaver redraw
├── kf/
│   ├── session.lua                  # pure: per-sleep state machine + generation counter
│   ├── budget.lua                   # pure: effective budget maths
│   ├── pngcheck.lua                 # pure: signature + IHDR size check
│   ├── fetchlog.lua                 # pure-ish: one-line log, rotate at 64 KiB
│   ├── wifi.lua                     # NetworkMgr wrapper: snapshot, async up, poll, restore
│   └── fetcher.lua                  # runInSubProcess download → .part, poll, terminate
└── spec/                            # busted tests for kf/session, budget, pngcheck, fetchlog

server/
├── pyproject.toml
├── Dockerfile                       # FROM mcr.microsoft.com/playwright/python
├── compose.yaml                     # project "kinda-frame", port bound to LAN IP
├── config.example.toml              # placeholders only; real config.toml is git-ignored
├── kindaframe/
│   ├── app.py                       # FastAPI: /frame.png, /healthz
│   ├── config.py
│   ├── render.py                    # Renderer (art / photo) + FrameCache: background pre-render per screen size
│   ├── imaging/
│   │   ├── grey16.py                # palette, quantize (dither / no-dither)
│   │   └── fit.py                   # crop / pad, EXIF orientation, autocontrast
│   ├── art/                         # generative art mode (docs/art.md)
│   │   ├── base.py                  # Piece, density (bincount), tonemap, captioned compose
│   │   ├── chladni.py · flowfield.py · attractor.py · orbits.py
│   ├── photo.py                     # folder scan, random / sequential, cursor state
│   ├── html.py                      # (M3b) Playwright page pool → screenshot at w×h
│   └── boards/
│       ├── base.py                  # Board protocol: name, ttl, fetch(), template
│       ├── registry.py              # discovers boards/<name>/
│       └── daily/
│           ├── board.py             # Open-Meteo + ICS sources, per-source timeout
│           └── template.html
└── tests/                           # pytest: grey16, fit, photo, boards fallback, API contract

tools/
├── make-test-card.py                # Phase 1 card: 16 steps, light-end detail, TOP marker, size label
└── stub/frame.png                   # Phase 2 stub (generated; git-ignored)

docs/
├── device-probe.md                  # Phase 0 output
└── restore.md                       # one-step sleep-screen restore (FR-021)
```

**Structure Decision**: one repo with two top-level deployables, `plugin/` and `server/`, plus `tools/` and `docs/`. The plugin folder is the exact folder copied to the device. Pure-Lua logic sits in `kf/` so it can be unit-tested without KOReader. The server's boards are self-contained folders, so a new board (RSS, trends) is a new directory and nothing else (FR-017).

## Design Notes (how the requirements are met)

### Sleep path (FR-004 to FR-012), see data-model state machine

1. **`onSuspend`**: KOReader has already queued the saved frame (R2), so FR-004 needs no work. Bump `gen`. If disabled, no URL, or no measured window, log `skipped_*` and stop.
2. Snapshot `wifi_before = NetworkMgr:isWifiOn()`. If it's off, `NetworkMgr:restoreWifiAsync()` (no UI, R3). Poll `isConnected()` every 0.25 s against the deadline.
3. Once connected: `fetcher.start(url?w&h&batt)` in a child process writing `current.png.part`. Poll `isSubProcessDone` every 0.25 s. If the deadline passes, `terminateSubProcess`.
4. Validate (`pngcheck`: HTTP status passed from the child via an exit code, signature, IHDR = w×h). If the bytes are identical to the current file, outcome `unchanged`. Otherwise fsync and rename.
5. Redraw only if `gen` is unchanged **and** `Device.screen_saver_mode`: swap the `ImageWidget` inside `Screensaver.screensaver_widget` (never close it) → `setDirty` → `UIManager:forceRePaint()` → `waitForVSync()`. Then hold about 1 s for the panel (R5, proven in M1b).
6. **Always** restore Wi-Fi to `wifi_before` and write one log line.
7. **`onResume`**: bump `gen`, terminate the child if it's running, delete `.part`, restore Wi-Fi, log `cancelled_wake`.

The device suspends on the framework's own schedule. The plugin never asks for more time (R2). Its only promise is that nothing is in flight once the effective budget has passed.

### Menu (FR-020)

Tools → Kinda Frame: *Refresh on sleep* (toggle) · *Server URL* · *Fetch budget* · *Fetch now* (awake: same fetcher, with an InfoMessage allowed) · *Last fetch status* (tail of the log) · *Measured window / margin* (shows Phase 0 values; editable).

### Server (FR-015 to FR-019)

- `GET /frame.png?w&h&batt` per `contracts/frame-api.md`. A prepared frame is cached per (mode, board, w, h). On a miss, render synchronously (cold < 5 s).
- Photo mode: pick (random or cursor), EXIF-transpose, fit (crop/pad), autocontrast and gamma, then `grey16.quantize(dither=True)`. After each serve, pre-render the next photo.
- Dashboard: `board.fetch()` on its TTL in the background. Each source has a 5 s timeout and turns into `unavailable` on failure. Jinja2 renders to HTML, a warm Playwright page screenshots it at w×h with DPR 1, then `grey16.quantize(dither=False)`. Every board shows "rendered at" and can show `batt`.
- No rotation (FR-019). Upright mount.

## Delivery (replaces tasks.md)

Each milestone must pass its gate before the next starts. Owner approval is needed where marked 🧑.

| # | Milestone | Covers | Exit gate |
|---|---|---|---|
| **M0** | Device probe (read-only): SSH key (🧑 Tyler installs), SPEC.md §6 commands, KOReader version, **R0** Special Offers check, window measurement ×10, Wi-Fi drop on suspend, Wi-Fi up + fetch time, battery baseline day | Research R0, R2, R3, R6 | `docs/device-probe.md` complete; R0 explained; window measured; **🧑 go/no-go for D6** |
| **M1** | Static frame: test card at KOReader's size; back up settings; point the sleep screen at `current.png` (R1 settings) | Story 1, FR-001 to FR-003, FR-021 | SC-005 passes; no message or overlay; `docs/restore.md` restore tested once (SC-007) |
| **M1b** | Redraw spike: debug-only menu entry that, 2 s into sleep, swaps `current.png` and runs the R5 redraw sequence | Research R5 | Redraw works ≥ 9/10 sleeps with no late redraw after wake, or **🧑 choose the D6 fallback** |
| **M2** | Plugin against the stub server (`python -m http.server` on the dev machine) | Stories 2, 3, 5; FR-004 to FR-014, FR-020 | SC-001, SC-002, SC-003 on the stub; Wi-Fi before = after in every log line; busted suite green |
| **M3a** | Server, **art mode** (4 generators) + photo mode, deployed on home-server | Story 4 (art, photo), FR-015, FR-016, FR-018, FR-019, FR-024 | pytest green (57); `/frame.png` correct size and palette; SC-008 (cold 1.2 s, pre-rendered ~30 ms); plugin pointed at the server passes 20 cycles |
| **M3b** | Server, daily board (date, Open-Meteo weather, ICS calendar, battery, rendered-at) | Story 4 (dashboard), FR-017, FR-017a | Board renders with each source killed in turn; SC-006 for a template edit |
| **M4** | Soak and battery: one day of normal use with the plugin on | SC-004 | ≤ 20 % over the M0 baseline; log shows no stuck Wi-Fi |
| later | More boards (RSS, trend tracker, …) as separate features | FR-017 | each one: new `boards/<name>/` only |

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| R0: KOReader decides the device has Special Offers and stops drawing its sleep screen (e.g. after a reboot or update) | Ads instead of the frame | Understand the check in M0; quickstart check after reboots; fallback options go to Tyler |
| The window is shorter than Wi-Fi up + fetch (**largely retired**: measured about 70 s) | Fresh frame rarely lands | Pre-rendered server frames (fast response); IP URL; the measured budget decides; D6 fallback 🧑 |
| The redraw sequence ghosts or flashes badly (cf. issue #15702) | Ugly double refresh | Skip unchanged frames; tune the flash; M1b gate |
| Child-process fetch is killed by suspend mid-write | Corrupt `.part` | `.part` + validate + rename; `.part` cleaned at start |
| A KOReader update changes Screensaver/NetworkMgr internals | Plugin breaks | Pin the tested version in `docs/device-probe.md`; a glue-only `main.lua` keeps the blast radius small; every call guarded by `pcall` |

## Complexity Tracking

No constitution violations to justify (see Constitution Check). Two deployables is the minimum for "render on the server, display on the device" (SPEC.md D1).
