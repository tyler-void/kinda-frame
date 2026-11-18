# Research: Sleep-Screen Frame

Sources: **installed KOReader is v2026.07.2** (updated 2026-11-18). Every API below was re-checked in the installed source (`docs/device-probe.md`). Originally read from KOReader master @ `2f48e2e` (2026-11-17) and koreader-base master @ `94550aa`, read on GitHub. The latest release is v2026.07.1, so the installed version must be checked in Phase 0. Also read: prior-art repos (trmnl-koreader, ktrm, kindle-dash, ReKindle, re-kindle). Line numbers below refer to master and will drift. **CONFIRMED** = seen in source; **UNCERTAIN** = must be proven on the device in Phase 0.

## R0. Show-stopper risk: KOReader may refuse to draw its sleep screen on Special Offers Kindles

- **Finding (CONFIRMED in source):** `Kindle:supportsScreensaver()` returns false when the device has Special Offers (`frontend/device/kindle/device.lua` ~L529). KOReader then leaves the sleep screen to the stock framework, which would show ads.
- **Counter-evidence (VERIFIED by Tyler):** sleeping from KOReader on this device shows KOReader's sleep screen with no ad. So on this device the Special Offers check must currently come out "no Special Offers" (perhaps because of the AdBreak jailbreak state), or what Tyler sees is drawn some other way.
- **Resolved (probe 2026-11-18):** on FW 5.x KOReader's `isSpecialOffers()` looks for `ad_screensaver` in `lipc-get-prop com.lab126.blanket load`. This device returns `screensaver langpicker blankwindow usb`, so KOReader draws its own sleep screen. **Ongoing check:** if that property ever lists `ad_screensaver` (after a reboot or update), the frame stops working. The quickstart's post-reboot check covers it. See `docs/device-probe.md`.
- *(Original decision)* Phase 0 records *why* it works today: how KOReader detects Special Offers, and what that check returns on this device. If it could flip (e.g. after a reboot, a firmware state change or a KOReader update), that becomes a documented risk with a check in the quickstart. **No plugin work starts until this is understood.**
- **Alternatives:** if KOReader's sleep screen turns out not to be reliable on this device, stop and ask Tyler (SPEC.md D5). Options would be the parked KUAL loop, or KindleForge's ad toggle.

## R1. Which settings point the sleep screen at our file

- **Decision:** `screensaver_type = "document_cover"` + `screensaver_document_cover = "/mnt/us/kinda-frame/current.png"`. That is KOReader's "image file" mode (`frontend/ui/screensaver.lua` `setup()` ~L381–406). Also: `screensaver_show_message = false`, `screensaver_img_background = "white"`, `screensaver_stretch_images = false`, `screensaver_rotate_auto_for_best_fit = false`.
- **Rationale:** the frame is already at the exact screen size, so stretching and rotation must stay off to get a pixel-exact result. A missing file falls back to random image and then to `resources/koreader.png`, which covers the "first run" edge case.
- **Alternative rejected:** `random_image` with a one-file folder. It works, but the "image file" mode says exactly what we mean.
- **Caching (CONFIRMED):** `show()` creates the ImageWidget with `file_do_cache=false`, so the file is decoded fresh on every sleep. No cache-busting is needed.
- **How it's set:** Tyler sets it in KOReader's menu, or the file is edited while KOReader is closed (SPEC.md rule 3). Settings are backed up first.

## R2. When the plugin runs during sleep, and how long it has

- **Flow on Kindle (CONFIRMED):** the power button makes powerd emit `goingToScreenSaver`. KOReader calls `Screensaver:setup()` + `show()` (this only *queues* the repaint), then broadcasts **`onSuspend`** to plugins (`Device:_beforeSuspend`). Later powerd emits `readyToSuspend`, and then the *framework* suspends the device. On wake, `outOfScreenSaver` → `Screensaver:close()` → **`onResume`**.
- **Who suspends:** the Kindle framework (powerd), not KOReader. KOReader's own suspend timers don't apply on Kindle.
- **Window length (UNCERTAIN):** a KOReader comment says the device "stays in Ready to suspend for 10 seconds" (`kindle/powerd.lua` ~L290). kindle-dash reports roughly 10–15 s. Phase 0 **measures** it from log timestamps of `onSuspend` and the last log line before suspend, over 10 sleeps.
- **Extending it (UNCERTAIN, not planned):** powerd `deferSuspend` is undocumented and unverified. `preventScreenSaver` blocks the screensaver *trigger*, not the suspend that follows. **Decision:** don't try to extend the window in v1. Fit inside it (FR-007).
- **Timers keep running (CONFIRMED):** `UIManager:scheduleIn` / `unschedule` keep working in the screensaver state until the kernel suspends. That's what lets the plugin poll.

**Measured (probe 2026-11-18):** pressing power puts powerd in SCREEN SAVER for **60 s**, then READY TO SUSPEND for about 10 s, then it suspends. That's about **70 s total** (one long sample; see `docs/device-probe.md`). The "10 seconds" comment covers READY TO SUSPEND only. The window is therefore not a constraint for the 25 s budget.

**Decision:** hook `onSuspend` (the saved frame is already queued for display, which is spec FR-004 for free) and `onResume` (cancel). The effective budget is `min(budget, measured_window − margin)` with a default margin of 2 s.

## R3. Wi-Fi without UI pop-ups

- **Finding (CONFIRMED):** on Kindle, `NetworkMgr:turnOnWifi()` → `reconnectOrShowNetworkMenu` **blocks and shows "Scanning…/Connected" messages**. Those would be drawn over the sleep screen (KOSync has workarounds; issue #15974 reports the blocking). `runWhenOnline` / `goOnlineToRun` also go through it.
- **Decision:** use the UI-free path. `NetworkMgr:restoreWifiAsync()` (on Kindle this is just `kindleEnableWifi(1)`) plus our own polling of `NetworkMgr:isConnected()` with `scheduleIn(0.25, …)` until connected or out of budget. Turn Wi-Fi off with the Kindle wifid disable (as `turnOffWifi` does, without its UI). Before starting, record `NetworkMgr:isWifiOn()` and restore that state (FR-012).
- **Measured (probe):** the radio stays connected through the 60 s SCREEN SAVER phase and is powered off only at real suspend (`brcm_wlan_power gpio off`). `wirelessEnable` stays 1, and wifid reconnects after wake in ~3–13 s (one DHCP retry seen). So when Wi-Fi was on at sleep, the fetch needs no bring-up at all.
- **Finding:** KOReader does **not** turn Wi-Fi off on suspend on Kindle (`hasWifiManager` is false). Whether the framework drops it on suspend is Tyler's observation (UNCERTAIN). Phase 0 checks it. Either way the plugin restores what it found.
- **Alternatives rejected:** `NetworkMgr:turnOnWifi` / `runWhenOnline`, because of UI over the sleep screen and blocking. Calling `lipc-set-prop com.lab126.cmd wirelessEnable` directly is the fallback only if `restoreWifiAsync` turns out not to exist or to behave differently on the installed version.

## R4. Fetching without freezing KOReader

- **Finding (CONFIRMED):** `socket.http` + `socketutil:set_timeout()` blocks the UI loop, and DNS lookups aren't covered by the timeouts. `HttpAsync` still blocks its caller.
- **Decision:** run the download in a child process with `ffiutil.runInSubProcess(fn)`. The child does `socket.http` with `socketutil` timeouts and writes `current.png.part`. The parent polls `ffiutil.isSubProcessDone(pid)` with `scheduleIn`, kills it with `ffiutil.terminateSubProcess(pid)` on budget-out or resume, then validates the file and renames it atomically (`ffiutil.fsyncOpenedFile` + `os.rename`). This pattern is used by coverbrowser's `bookinfomanager.lua`.
- **Use an IP address for the server URL**, not a hostname, so there is no DNS lookup to hang on. The quickstart's config example says so.
- **Alternatives rejected:** blocking `socket.http` in the UI process (trmnl-koreader does this, but it isn't sleep-critical there). `Trapper:dismissableRunInSubprocess` needs a trap widget, i.e. UI.

## R5. Redrawing the sleep screen with the new frame

- **Finding:** there's no "refresh screensaver" API. The originally proposed `close_widget()` → `setup()` → `show()` sequence was **rejected** after reading v2026.07.2: `ScreenSaverWidget:onCloseWidget()` runs `Screensaver:cleanup()` (clears `Device.screen_saver_mode`) and marks the whole screen dirty, so it could paint the book mid-sleep.
- **Decision (M1b, tested 2026-11-18): "swap in place".** Replace the `ImageWidget` inside the existing `Screensaver.screensaver_widget` (`ssw[1][1] = ImageWidget:new{file=current.png, file_do_cache=false, width/height=screen, scale_factor=0, alpha=true}`), `old:free()`, `UIManager:setDirty(ssw, "full", frame.dimen)`, `forceRePaint()`, `waitForVSync()`. Nothing is closed, so KOReader closes its own sleep screen normally on wake. Spike results: **5/5 redraws** (incl. one at 51.8 s into sleep), **2/2 wake-before-redraw correctly skipped**, no errors; redraw cost ≈ 0.6–0.9 s repaint + 0.3–0.9 s file copy with fsync. The alternative "overlay own widget" wasn't needed and wasn't tested. Guards before the redraw (FR-011):
  1. the generation counter is unchanged since `onSuspend`;
  2. `Device.screen_saver_mode` is still true;
  3. the new file's bytes differ from the previous frame. If they're the same, skip the redraw and avoid the extra flash. (This idea comes from re-kindle.)
- **Wait for the panel:** `forceRePaint()` flushes the queued refresh. Then wait about 1 s (tunable) before declaring the attempt done, so the device never suspends mid-refresh. re-kindle found that suspending mid-update leaves a half-drawn screen.
- **Fallback if the redraw sequence is unreliable:** ask Tyler (D6). The choices are a one-sleep-stale image (fetch on resume, show next time) or a slower sleep.

## R6. Screen size

- **CONFIRMED:** `Screen:getWidth()` / `getHeight()` return the visible resolution, and framebuffer padding is hidden inside the stride. PW4 = `KindlePaperWhite4`, 300 dpi. 1072×1448 is expected but read on the device.
- **Decision:** the plugin always sends `Screen:getWidth()` / `getHeight()` as `w` / `h`. The rotation-independent form, with KOReader in portrait, is what the sleep screen uses: R1's settings force portrait on the screensaver path (`Device.orig_rotation_mode`).

## R7. Server renderer stack

- **Decision:** Python 3.12, FastAPI + uvicorn, Pillow, Playwright (Chromium) for HTML boards, Jinja2 templates. Board data: Open-Meteo for weather (no API key), ICS calendars via `icalendar` + `recurring-ical-events`, and later `feedparser` for RSS. Container based on the official Playwright Python image.
- **Dithering:** convert to `L`, apply autocontrast and a mild gamma lift, then quantize to a fixed 16-grey palette (`0, 17, …, 255`) with Pillow's Floyd–Steinberg (`Image.quantize(palette=…, dither=FLOYDSTEINBERG)`), and convert back to `L`. Dashboards: render at 1× device pixels, and use **no dithering for text/UI** (quantize without dither) so text stays crisp. Photos are dithered.
- **Light greys:** re-kindle found light greys "barely visible". The Phase 1 test card checks the light end, and board templates keep text at levels ≤ 0x44.
- **Pre-rendering:** a background job re-renders the current frame whenever board data refreshes or (in photo mode) after each serve. `/frame.png` serves the prepared frame for the requested size, so responses usually take milliseconds and well within the device's window.
- **Alternatives rejected:** rendering on the device (re-kindle's awk + FBInk approach and its pitfalls); `wkhtmltoimage` (unmaintained); Node/Puppeteer (no advantage, and Pillow is the better image tool).

## R8. Prior art and licences

| Project | What it is | Licence | Use |
|---|---|---|---|
| usetrmnl/trmnl-koreader | KOReader plugin showing a TRMNL image while awake | MIT | Reference for KOReader HTTP + image code. May reuse with attribution. |
| amarder/ktrm | Shell TRMNL client, power-button refresh | MIT | Behaviour reference |
| pascalw/kindle-dash | Shell dashboard client, suspend + RTC | MIT | Behaviour reference (parked D5-a) |
| abdenourgnx/re-kindle | KUAL shell dashboard (7th gen, soft-float `fbink`) | **none** | Ideas only (temp file + `mv`, skip unchanged redraw, wait for the refresh before suspending) |
| ReKindleOS/ReKindle | In-browser web-app suite (games, RSS, weather), KPM add-on | CC BY-NC-SA 4.0 | Ideas only. Issue #28 asks for a KOReader plugin, so nobody has built this. |

Neither ReKindle nor re-kindle changes the D5-c choice: neither hooks KOReader's sleep screen.

## R9. Testing approach

- **Plugin:** keep the logic (state machine, budget maths, PNG validation, log rotation) in pure-Lua modules with no KOReader imports, and unit-test them with `busted` on the dev machine (LuaJIT / Lua 5.1). The KOReader glue is thin and is tested on the device through the quickstart's manual scenarios. There's no emulator in the loop for v1.
- **Server:** `pytest` for dithering (palette values, exact size), photo fitting, board fallback and the HTTP contract (with `httpx`/TestClient). One end-to-end render test runs inside the container.
