# Data Model: Sleep-Screen Frame

There is no database. Everything is small files on the Kindle or the server, plus in-memory state in the plugin. Entities come from the spec's Key Entities.

## Device side (Kindle, `/mnt/us/`)

### Frame (on the wire and on disk)

| Field | Type | Rule |
|---|---|---|
| width, height | int | Equal to the KOReader-reported screen size |
| pixels | 8-bit grey | Only the 16 levels `0, 17, …, 255` (FR-003) |
| encoding | PNG | Verified by signature + IHDR (contracts/frame-api.md) |

### Saved frame

- Path: `/mnt/us/kinda-frame/current.png`. This is the path KOReader's sleep screen is pointed at.
- Write rule (FR-010): download to `current.png.part` in the same directory, validate, then `os.rename()` over `current.png`. Never written in place. A leftover `.part` file is deleted at plugin start.
- First run: if `current.png` doesn't exist yet, the plugin never touches the sleep-screen settings, so the previous behaviour stays (edge case "first run").

### Device settings (KOReader plugin settings, via `G_reader_settings`, key prefix `kindaframe_`)

| Key | Type | Default | Rule |
|---|---|---|---|
| `kindaframe_enabled` | bool | `false` | Refresh-on-sleep on/off (FR-020). Off by default until tested. |
| `kindaframe_server_url` | string | `""` | Must start with `http://`. Empty means "fetch disabled". |
| `kindaframe_orient` | string | `portrait` | `portrait` \| `left` \| `right` (FR-019); sent as `orient=` |
| `kindaframe_budget_s` | number | `25` | Clamped to 3–60 s (FR-007). Raised from 15 s: a cold Wi-Fi reconnect took ~13 s (device-probe). |
| `kindaframe_margin_s` | number | `5` | Safety margin subtracted from the measured window. |
| `kindaframe_window_s` | number | `60` (measured SCREEN SAVER dwell) | Measured time between sleep screen drawn and suspend. `nil` means "unknown": fetch disabled, show the saved frame only. |

Effective budget = `min(budget_s, window_s - margin_s)`. If that's ≤ 2 s, don't fetch at all.

### Sleep-screen settings backup

- Before the first change, copy `/mnt/us/koreader/settings.reader.lua` to `/mnt/us/kinda-frame/backup/settings.reader.lua.<YYYYmmdd-HHMMSS>` (only while KOReader is closed; SPEC.md §5 rule 3).
- `restore.md` documents the one-step restore (FR-021, SC-007).

### Fetch attempt (log record)

One line per sleep in `/mnt/us/kinda-frame/kindaframe.log`, rotated at 64 KiB to `kindaframe.log.1` (one generation kept) (FR-013).

| Field | Example |
|---|---|
| `ts` | `2026-11-20T21:14:03` (device local time) |
| `outcome` | one of `new_frame`, `unchanged` (same bytes, redraw skipped), `timeout`, `unreachable`, `http_<code>`, `invalid`, `cancelled_wake`, `skipped_no_window`, `skipped_disabled` |
| `ms` | total duration |
| `wifi_before` / `wifi_after` | `on` / `off`; must be equal (FR-012) |
| `bytes` | size received |

### Fetch state machine (per sleep, in plugin memory)

```
IDLE ──suspend event──▶ SHOWING_SAVED ──(enabled & window ok)──▶ WIFI_UP ──connected──▶ FETCHING
                              │                                     │                     │
                              └──(disabled/no window)──▶ DONE        │ timeout             ├─valid──▶ SAVING ──▶ REDRAW ──▶ RESTORE_WIFI ──▶ DONE
                                                                    ▼                     ├─invalid/error──▶ RESTORE_WIFI ──▶ DONE
                                                               RESTORE_WIFI ──▶ DONE      └─budget exceeded──▶ RESTORE_WIFI ──▶ DONE

any state ──resume event──▶ CANCELLED: abort the request, delete .part, skip REDRAW, RESTORE_WIFI ──▶ IDLE
```

Invariants:
- `WakeupFromSuspend` (powerd's own RTC self-wake, about every 12 h) is **ignored**: no fetch, no `gen` bump. Only `onSuspend` / `onResume` drive the machine.
- REDRAW only happens if the state is still "asleep" at the moment of drawing. A generation counter that is bumped on every suspend and resume is checked right before the redraw (FR-011).
- RESTORE_WIFI always runs exactly once per attempt, including on error paths (FR-012).
- The download runs in a child process (`ffiutil.runInSubProcess`), and the parent only polls with `UIManager:scheduleIn`. Cancel = `terminateSubProcess` + delete `.part` (research R4).
- REDRAW is skipped when the new bytes equal the saved frame (outcome `unchanged`), so there is no needless second flash (research R5).
- Nothing in this machine may block the suspend path. If a step can't run asynchronously, it's skipped (FR-009).

## Server side (`home-server`)

### Server configuration (`server/config.toml`, uncommitted; `config.example.toml` committed)

| Key | Type | Example | Rule |
|---|---|---|---|
| `mode` | enum | `art` | `art` \| `photo` (\| `dashboard`, M3b) |
| `art.generators` | list | all four | Non-empty subset of `chladni`, `flowfield`, `attractor`, `orbits` |
| `art.order` | enum | `random` | `random` (never the same twice in a row) \| `cycle` |
| `photo.dir` | path | `/photos` (container mount) | Must exist and be readable |
| `photo.order` | enum | `random` | `random` \| `sequential` |
| `photo.fit` | enum | `crop` | `crop` (fill, centre-crop) \| `pad` (letterbox, white) |
| `dashboard.board` | string | `daily` | Must name a registered board |
| `boards.daily.location` | `{lat, lon, label}` | — | Private: only in the uncommitted file |
| `boards.daily.calendar_ics` | list of URLs | — | Private |
| `boards.<name>.*` | board-specific | — | Validated by the board itself |
| `timezone` | IANA name | `Etc/UTC` (set the real zone locally) | Used for "rendered at", date and agenda; validated at start |
| `dashboard.board` | string | `daily` | Must name a registered board |
| `boards.daily.latitude` / `longitude` | float | — | Private. Weather is "unavailable" until set |
| `boards.daily.location_label` | string | `Home` | Shown under the date |
| `boards.daily.units` | enum | `metric` | `metric` \| `imperial` |
| `boards.daily.calendars` | list of URLs | `[]` | Private (secret ICS URLs). Hashed for cache keys, never rendered or logged |

### Board

| Field | Meaning |
|---|---|
| `name` | Registry key (`daily`, later `rss`, `trends`, …) |
| `fetch(config) -> data` | Gathers data from its sources. Each source has its own timeout; failures become `{"unavailable": true}` for that section (FR-017a). |
| `ttl` | How long fetched data stays fresh (e.g. weather 30 min, calendar 15 min) |
| `template` | `server/kindaframe/boards/<name>/template.html` (Jinja2), rendered at the requested size |

Adding a board = adding one folder with `board.py` and `template.html`. Nothing else changes (FR-017).

### Photo selection state

`/state/photo_cursor.json` (`{"last": "<relative path>", "index": n}`) on a named volume. It's only used for `sequential` order.
