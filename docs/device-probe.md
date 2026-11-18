# Device probe (M0)

Probed 2026-11-18 over `ssh kindle` (key auth, no password). All commands were read-only.

## Verdicts

| Item | Result | Status |
|---|---|---|
| Firmware | `Kindle 5.18.1` (`/etc/prettyversion.txt`); kernel `4.1.15-lab126`, armv7l | ✅ VERIFIED |
| ABI | `/lib/ld-linux-armhf.so.3` → **hard-float**. KOReader's bundled `/mnt/us/koreader/fbink` runs (hard-float build) | ✅ VERIFIED |
| Screen | **1072×1448**, 300 dpi, PW4 "Moonshine" (`fbink -e`: viewWidth/Height = screenWidth/Height). Framebuffer is padded: `virtual_size` 1088,6144, stride 1088, so **use KOReader's size, never `virtual_size`** | ✅ VERIFIED |
| KOReader | **v2026.07.2** (updated by Tyler on 2026-11-18 via the built-in updater; was v2025.10). Settings and sleep-screen config survived the update | ✅ VERIFIED |
| SSH security | **Fixed 2026-11-18:** Tyler turned "Login without password" off (the running dropbear has no `-n`; the settings file updates on KOReader's next flush) and turned on "Start SSH server with KOReader" (`SSH_autostart = true`) | ✅ |
| Special Offers check (research R0) | KOReader (FW 5.x path, `isSpecialOffers()`) looks for `ad_screensaver` in `lipc-get-prop com.lab126.blanket load`. On this device that returns `screensaver langpicker blankwindow usb`, with **no `ad_screensaver`**. So KOReader treats the device as not Special Offers and draws its own sleep screen. This matches Tyler's experience | ✅ R0 explained |
| Current sleep screen | `screensaver_type = "document_cover"` (image file) → `/mnt/us/koreader/wallpapers/previous-wallpaper.png`; `show_message = false`; `stretch_images = false`; `rotate_auto_for_best_fit = false`; `img_background = "black"`; `delay = "disable"` | ✅ Already "image file" mode; only the path (and maybe background) needs to change |
| Wi-Fi now | `wirelessEnable = 1`, wifid `cmState = CONNECTED` | info |
| Battery now | 89 % (`powerd battLevel`); powerd state `active` | info |
| RTC | `rtc0`, `rtc1` present (not needed: no refresh while asleep) | info |
| Tools | `curl`, `wget`, `md5sum`, `sha1sum` in `/usr/bin` | info |
| User storage | `/mnt/us` is **`fuse.fsp`** (27.3 G, 1 % used), not vfat | ⚠ rename to be tested |
| Root FS | `/dev/root` mounted **rw** (ext3) | ⚠ differs from SPEC.md |
| Extensions | `KUAL.cfg`, `MRInstaller`, `gnomegames`, `kindlefetch`, `koreader`, `kterm`, `renameotabin` | info |
| KOReader plugins | 38 stock plugins incl. `SSH`, `keepalive`, `autosuspend`, `kosync`, `newsdownloader` | info |

## KOReader API check (re-run on v2026.07.2)

| Research item | In v2025.10? |
|---|---|
| Screensaver "image file" = `document_cover`, `file_do_cache = false` (R1) | ✅ `frontend/ui/screensaver.lua` L530 |
| `Screensaver:setup/show/close_widget/close/cleanup` (R5 redraw) | ✅ L346, L450, L704, L710, L735 |
| `intoScreenSaver` → `Screensaver:setup()` + `show()` when `supportsScreensaver()` (R2) | ✅ `kindle/device.lua` L752 |
| `NetworkMgr:restoreWifiAsync()` = `kindleEnableWifi(1)` without UI (R3) | ✅ `kindle/device.lua` L453 |
| `ffiutil.runInSubProcess / isSubProcessDone / terminateSubProcess` (R4) | ✅ `ffi/util.lua` L340, L452, L466 (+ `fsyncOpenedFile` L578) |
| "Kindle stays in Ready to suspend for 10 seconds" comment (R2) | ✅ `kindle/powerd.lua` L288 |
| Special Offers check still keyed on `ad_screensaver` (R0) | ✅ `kindle/device.lua` L347; blanket load unchanged after the update |

## Sleep window (measured 2026-11-18)

Sources: KOReader debug log (`crash.log`) plus powerd lines in `/var/log/messages` (read-only).

| Time | Event |
|---|---|
| 01:50:23 | Power pressed → powerd `ACTIVE -> SCREEN SAVER`; KOReader `IntoSS`, plugins' `onSuspend`, sleep screen painted (same second) |
| 01:51:23 | powerd `SCREEN SAVER -> READY TO SUSPEND` (**60 s** after the press); KOReader gets `ReadyToSuspend` with param 10 (s until suspend), then again at 01:51:28 with param 8 |
| 01:51:32 | Woken by Tyler before actual suspend; powerd logs `Time spent in ready to suspend: 9 s` |

- **Window ≈ 60 s in SCREEN SAVER + ~10 s in READY TO SUSPEND ≈ 70 s** from pressing power to suspend. That's far more than research R2 assumed (about 10 s: that comment is about READY TO SUSPEND only).
- Three earlier short sleeps (8 s, 5 s, 3 s) never left SCREEN SAVER, which fits.
- Sleep screen paint: the `IntoSS` → `painting widget: ScreenSaver` gap is under 1 s (SC-001 timing OK; previous-wallpaper.png needs MuPDF decode + scaling, while an exact-size PNG will be faster).
- **Confirmed with more samples:** SCREEN SAVER dwell was 61 s (01:53:48 → 01:54:49) and 59 s after an RTC self-wake (14:13:49 → 14:14:48). It's a fixed ~60 s powerd timer.
- **READY TO SUSPEND is not a fixed 10 s.** Its countdown can stall and restart (10, 8, 7, *20 s gap*, 7, 6, 2, …). One run lasted **67 s** (powerd: `Time spent in ready to suspend: 67`). Using only the 60 s SCREEN SAVER phase as the window stays the conservative choice.

## Real suspend and Wi-Fi (overnight, 2026-11-18)

| Time | Event |
|---|---|
| 01:53:48 | Sleep pressed |
| ~01:55:3x | Suspended |
| 14:13:49 | **Self-wake by RTC**: powerd's own alarm (`rtcset client=phd`, ~12.4 h after suspend). KOReader receives `WakeupFromSuspend` only, **no `OutOfSS` and no `onResume`**. The device stays on the sleep screen |
| 14:15:57 | Re-suspended without user action (SCREEN SAVER 59 s + READY TO SUSPEND 67 s) |
| 20:10:19 | Woken by Tyler (`BUTTON_WAKEUP`) after 21 264 s (5.9 h) suspended |

**Wi-Fi across a real suspend:**
- The radio is **powered off during suspend** (`brcm_wlan_power: setting gpio #[47] off/on` at wake), so Tyler's "it disconnects when it sleeps" is confirmed. But `wirelessEnable` stays `1`, and wifid reconnects by itself after wake.
- **During the 60 s SCREEN SAVER phase the radio is still on.** Every short sleep woke up with Wi-Fi `CONNECTED`. So if Wi-Fi was on when Tyler pressed power, the plugin can fetch at once with no bring-up.
- **Cold reconnect time** (wake 20:10:19 → `cmd: READY -> CONNECTED` 20:10:32): **~13 s**. Scan + associate took ~1.4 s, then the first DHCP attempt failed after ~5 s (`Failed to obtain IP address`), then re-associate + DHCP succeeded. Best case is about 3–4 s; the observed worst is about 13 s. The default fetch budget goes up from 15 s to **25 s** (still inside the 55 s effective window).

**Battery data point (not the baseline):** 89 % at 01:50 → 85 % at 14:15 → 84 % at 20:10, almost all of it suspended, i.e. about 5 % over 18 h idle with Wi-Fi enabled. The real baseline still needs one normal reading day.

**Oddity, unrelated to this project:** powerd logs `DECIDE SUSPEND POLICY … Hibernate epoch time = 0, Deferral_reason=EMMC_CORRUPTED` before each suspend. It looks like powerd has hibernation turned off because of an eMMC flag. Meaning not verified; worth a look separately, but it doesn't affect the frame.
- **D6: GO, approved by Tyler 2026-11-18.** Decision input: Plan with `window_s = 60` (only the SCREEN SAVER phase, ignoring READY TO SUSPEND) and `margin_s = 5`, so the effective budget = min(25, 55) = **25 s**. The redraw itself still needs the M1b spike.

## Still open (need Tyler at the device)

1. ~~Sleep window~~ measured (see above). Turn debug logging off again when M0 is done. Then press power 10× and measure the gap to suspend.
2. ~~Wi-Fi after a real suspend~~ measured (see above).
3. **Wi-Fi up + fetch time from Wi-Fi *off*** (cold reconnect after wake is ~13 s, see above; this is the from-off case, only needed if Tyler reads with Wi-Fi off): with Wi-Fi off, time `wirelessEnable 1` until a `curl` of a LAN PNG succeeds. This toggles Wi-Fi and drops the SSH session, so it must run as a detached script that logs to `/mnt/us/kinda-frame/`.
4. **Battery baseline:** note battery % at the start and end of one normal day (start: 89 % now, if today counts).
5. **Atomic rename on `fuse.fsp`:** confirm that `mv` over an existing file in `/mnt/us/kinda-frame/` is atomic enough (write test in M1, the first write step).

## Notes

- **Root FS is rw** although SPEC.md §3 says read-only by default. Safety rule 2 still applies unchanged: no writes outside `/mnt/us/`.
- Tyler's current wallpaper `/mnt/us/koreader/wallpapers/previous-wallpaper.png` stays untouched. Restoring = setting `screensaver_document_cover` back to that path (and `img_background` back to `black`).

## M1 progress (2026-11-18)

- `/mnt/us/kinda-frame/` created. Settings backed up to `backup/settings.reader.lua.20261118-201437` (verified with `cmp`).
- **Rename-over-existing on `fuse.fsp` works** (`.part` → `mv` replaced the old file's content). Item 5 above is closed.
- Test card (`tools/make-test-card.py`, 1072×1448, all 16 levels, palette-exact) pushed as `current.png` via `.part` + `mv`; md5 matches the local file.
- Tyler pointed the sleep screen at `current.png` (Screen → Sleep screen → Wallpaper → Custom images → Choose image or document cover).
- **M1 visual checks: all pass** (Tyler, 2026-11-18): every edge and corner present, fine patterns crisp (no scaling), all 16 levels distinct, **light end 12/13/14/15 distinguishable**, no message or ad, TOP at the top. SC-005 met.
- To do: confirm in `crash.log` that ImageWidget rendered without `scale_factor` (device was suspended at check time); one-step restore test (SC-007).

## M1b redraw spike (deployed 2026-11-18)

- Code read on v2026.07.2: `ScreenSaverWidget:onCloseWidget()` does `setDirty(nil, "full")` **and** `Screensaver:cleanup()` (resets `Device.screen_saver_mode`). So research R5's `close_widget → setup → show` sequence was **rejected without testing**: it could paint the reading view mid-sleep and break the sleep-mode flag.
- The spike tests two non-closing alternatives instead: **swap** (replace the ImageWidget inside the existing ScreenSaverWidget, then `setDirty` it) and **overlay** (our own full-screen widget on top, closed in `onResume`). Both end with `forceRePaint()` + `waitForVSync()` (blocks until the EPDC finished the refresh).
- Deployed: `/mnt/us/koreader/plugins/kfspike.koplugin`, cards `spike/a.png` ("CARD A") and `spike/b.png` ("REDRAWN · CARD B"). `current.png` = card A. Log: `/mnt/us/kinda-frame/spike/spike.log`.
- Process note: during deployment a scratch file was briefly written to `/tmp/t.lua` on the device (outside `/mnt/us/`, against rule 2). It was removed straight away.

### M1b results (2026-11-18, mode = swap)

From `/mnt/us/kinda-frame/spike/spike.log`:

| Run | Result |
|---|---|
| a: sleep about 10 s, ×4 | **4/4 redrawn** (A→B, B→A, …), 3.6–4.6 s after `onSuspend` with a 2 s delay. Breakdown: copy + fsync 0.3–0.9 s, `forceRePaint` 0.58–0.91 s, `waitForVSync` 0 ms (*), scheduler slack ~0.8 s |
| b: wake within ~1–1.6 s | **2/2 skipped** (`woke up before redraw (gen 3 != 4)`). Nothing drawn over the book |
| c: delay 50 s | **Redrawn at 51.8 s** into sleep, `screen_saver_mode` still true. A redraw near the end of the 60 s phase works |
| Errors | none (`crash.log` has no kfspike errors or tracebacks) |

- On every `onResume`, `screen_saver_mode` was already false: KOReader closed its own sleep screen (with our swapped image inside) before our handler ran, as expected.
- (*) `waitForVSync` returned in 0 ms each time. Either `forceRePaint` already blocks on the full refresh, or the wait doesn't cover it. UNCERTAIN; the real plugin also holds ~1 s after the redraw (the window allows it easily).
- Only 2 of the 3 "run b" attempts appear in the log; the third was probably slower than the delay, so it counts as a normal redraw.
- **Gate: PASS.** Tyler saw the sleep screen switch cards in place ("the screen rearranges itself"), with no other issues reported. Swap mode becomes the plugin's redraw method.
- Cleanup: spike disarmed (log `armed=false` 20:34:35), then `kfspike.koplugin` and `/mnt/us/kinda-frame/spike/` deleted from the device. Leftover `kfspike_*` keys in `settings.reader.lua` are harmless. The spike source stays in the repo (`plugin/kfspike.koplugin/`) as a reference for M2 and will be removed with M2.
- Settings flush note: `kfspike_next` on disk read `"b"` while the in-memory value was `"a"`. Live proof that KOReader keeps settings in memory and flushes later (rule 3).

## M2 on-device run (2026-11-18, stub server on the dev machine)

`/mnt/us/kinda-frame/kindaframe.log`, first build:

- **Wi-Fi on (11 sleeps + 1 manual):** 5 × `new_frame` (redrawn about 1.7 s into sleep; logged `ms` includes the 1 s settle), 4 × `unchanged` (no second flash), 2 × `cancelled_wake` during settling (frame already saved + drawn). No errors. Stub fetch from the Kindle: 18 ms.
- **Bug found and fixed:** successful redraws were logged as `detail=no_redraw:_nil` (`x and nil or y` idiom). Fixed + regression test; redeployed.
- **Wi-Fi off (3 sleeps):** `timeout detail=wifi` (25 s) · `unchanged` after 12.5 s · `cancelled_wake detail=connecting`. Wi-Fi left off each time ✓.
  - wifid log for the timeout: radio on 20:50:50, every targeted scan of 2472 MHz (ch 13) returned `networks-in-range=0/2` until the budget ran out. The second attempt found the AP after 7 s and connected after about 11 s.
  - Likely factors (not proven): Wi-Fi had been switched off by hand 7 s earlier (`suspend/wakeup already in progress`); the router is on **channel 13**, while the country code is `''`/`00` right after radio power-on.
  - Take-away: keeping Wi-Fi on while reading is the fast path (~1 s, radio stays up during the 60 s SCREEN SAVER phase). With Wi-Fi off, cold reconnect takes ~11 s to >25 s. Options: budget 40 s (menu), router on channel 1–11.
- **Server down (stub stopped, Wi-Fi on, 3 sleeps):** 3 × `unreachable detail=connection_refused`, ~1.1 s each, `wifi_before=on wifi_after=on`, last good frame kept, no errors in `crash.log`. KOReader restarted 20:49:58 with the fixed build.

### M2 gate (2026-11-18)

| Criterion | Result |
|---|---|
| SC-001 sleep screen ≈ 1 s; newest frame lands when the fetch fits | ✅ saved frame drawn immediately; 5/5 new frames redrawn (Wi-Fi on) |
| SC-002 server down: sleep works, last frame kept, Wi-Fi restored | ✅ 3/3 (spec asks 20; the rest accrues during the M4 soak) |
| SC-003 wake mid-attempt never overdrawn | ✅ 3/3 (`settling` ×2, `connecting` ×1; spec asks 10) |
| `wifi_before == wifi_after` on every line | ✅ 18/18 |
| Unit + scenario tests | ✅ 46/46, mutation-checked |
| Battery vs baseline (SC-004) | ⏳ M4 |

**M2: PASS** (with reduced sample counts, to be topped up in M4). Spike plugin source removed from the repo, as planned.

## M3a on-device (2026-11-18, real server `home-server:8787`, art mode)

- Plugin URL switched to the server. Manual fetch 21:15:45 (Chladni, 138 KB), then 3 sleeps → 3 × `new_frame`, no `detail` (redraw succeeded; confirms the label fix). Server log shows the Kindle's requests with `batt=79`.
- Tyler saw each sleep open on the previous piece and switch to the new one: Chladni → flow field → harmonograph → de Jong. Expected D6 behaviour.
- Art PNGs are 140–310 KB (dithered linework compresses less than the stub cards' ~30 KB); still well inside the window: ~1.7 s from sleep to redraw, as with the stub.
- Gate counter: 3 / 20 cycles; the rest accrue with normal use.
- **Visual check on the panel: good** (Tyler, 2026-11-18). Flow-field linework, dithered shading and captions all fine at 300 ppi; no tuning needed.
