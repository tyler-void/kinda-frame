# Contract: Frame HTTP API (renderer ↔ Kindle plugin)

**Version**: 1 · **Transport**: plain HTTP on the LAN only (no TLS, no auth; see Security) · **Producer**: `server/` renderer · **Consumer**: `plugin/kindaframe.koplugin`

The contract is deliberately tiny so the device side stays dumb (SPEC.md D1/D3). Anything about *what* a frame shows is server configuration, never a request parameter.

## `GET /frame.png`

### Query parameters

| Name | Required | Type | Rule | Meaning |
|---|---|---|---|---|
| `w` | yes | int | 100 ≤ w ≤ 4000 | Screen width in pixels, as KOReader reports it |
| `h` | yes | int | 100 ≤ h ≤ 4000 | Screen height in pixels |
| `batt` | no | int | 0 ≤ batt ≤ 100 | Battery %, so boards can show it |
| `orient` | no | enum | `portrait` (default) \| `left` \| `right` | How the device stands. `left`/`right` = landscape resting on that edge: the server lays out at `h`×`w` and turns it into the `w`×`h` buffer (90° clockwise for `left`, counter-clockwise for `right`). The response size is always `w`×`h`. |

Unknown parameters are ignored, so older plugins keep working with newer servers. An out-of-range `batt` is ignored rather than rejected.

**Debug overrides (not sent by the plugin):** `art=<generator>` and/or `seed=<int>` render that exact piece (bypassing the pre-render cache), e.g. to re-render one seen on the device from its caption.

### Responses

| Status | When | Body | Headers |
|---|---|---|---|
| `200` | Frame rendered | PNG, exactly `w`×`h`, 8-bit greyscale (mode `L`), values limited to the 16 levels `0, 17, 34, …, 255` | `Content-Type: image/png`, `Content-Length`, `Cache-Control: no-store`, `X-Frame-Mode: art\|photo\|dashboard`, `X-Frame-Source: <generator \| "photo i/n" \| board>` (never a file name), `X-Frame-Seed: <int>` (art only), `X-Frame-Orient: portrait\|left\|right`, `X-Rendered-At: <ISO-8601 UTC>` |
| `400` | `w`/`h` missing, not integers or out of range; unknown `art` generator; unknown `orient` | JSON `{"error": "<reason>"}` | — |
| `503` | Nothing to render (e.g. empty photo folder) or the renderer is broken | JSON `{"error": "<reason>"}` | `Retry-After: 300` |

A board whose data source fails still returns `200` with that section marked "unavailable" (spec FR-017a). `503` is reserved for "no frame can be made at all".

### Client obligations (plugin)

- Accept the frame only if **all** hold (spec FR-010): status `200`; body > 0 bytes; body starts with the PNG signature `89 50 4E 47 0D 0A 1A 0A`; the IHDR width/height (bytes 16–23, big-endian) equal the `w`/`h` sent.
- Anything else, including redirects, is a failed attempt: keep the saved frame.
- Request timeout = the remaining effective budget (spec FR-007). Never retry within the same sleep.
- No cookies, no auth headers, no other endpoints.

### Server obligations

- Render time target < 5 s for a cold dashboard and < 1 s for a photo (spec SC-008). The server should pre-render the current frame in the background so a request usually just serves the latest one.
- Never block on an external data source longer than its own short timeout. Board data is cached and refreshed in the background.
- Never include private data in headers or logs beyond what the board itself displays.

## `GET /healthz`

`200` `{"status": "ok", "mode": "<mode>", "board": "<name or null>", "last_render": "<ISO-8601 or null>"}`. Used for container health checks and by the quickstart. It is not called by the plugin.

## Security

- The port is published only on the LAN interface of `home-server` (compose `ports: "<lan-ip>:8787:8787"`), never on `0.0.0.0` behind a router port-forward.
- No authentication, because the only data exposed is the frame itself, which is already visible on the device. If the repo goes public, this stays a documented LAN-only assumption.

## Stub server for Phase 2 (same contract, subset)

For plugin development, `python -m http.server` serving a directory that contains `frame.png` satisfies this contract well enough: it ignores the query string and returns a fixed PNG. Swap the file by hand to simulate a new frame. It doesn't check `w`/`h`, so the stub PNG must already be the device size.
