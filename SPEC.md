# SPEC: kinda-frame

> Turn a jailbroken Kindle Paperwhite 4 into a picture frame / fun e-ink display for when it isn't being read.
> Owner: Tyler. Implementation: Claude Code CLI. Draft: 2026-11-18, rev. 6 (KOReader sleep-screen approach; photo-first + boards; upright mount).
> Confidence tags: **VERIFIED** (checked or stated by Tyler), **INFERRED** (derived, needs confirming), **GUESS** (must be probed).

---

## 1. Goals

- **Primary:** when Tyler puts the Kindle to sleep from KOReader, the sleep screen shows **the latest server-rendered frame**: a photo (frame mode) or a dashboard (date, weather, calendar, …).
- The Kindle stays a reader. Reading in KOReader is untouched; the frame only appears while the device sleeps.
- The Kindle is a **thin client**: all layout and rendering happen on the server; the device only fetches and shows a PNG.
- Sleep feels instant, and battery life stays close to normal KOReader use.
- **Refresh model (decided by Tyler):** a fresh image **every time the device goes to sleep** is enough. No refreshing while asleep.

## 2. Non-goals (for now)

- Using the Kindle as a real monitor (VNC, screen streaming).
- Colour, video, animation.
- Access from outside the home network (the Kindle only needs the LAN).
- Refreshing while asleep (RTC wake-ups) and an always-on dashboard mode. Revisit only if Tyler asks.

## 3. Device & environment

### Known

| Item | Value | Confidence |
|---|---|---|
| Device | Kindle Paperwhite 10th gen (PW4, codename moonshine) | VERIFIED |
| Jailbreak | Jailbroken, KOReader installed | VERIFIED |
| Launchers / stores | **KUAL** and **KindleForge** (app store for jailbroken Kindles) already installed | VERIFIED |
| Sleep screen | Tyler regularly uses **KOReader's own screensaver / sleep screen** | VERIFIED |
| Firmware / ABI | **5.18.1**, jailbroken with **AdBreak** → **hard-float (armhf)** (`/lib/ld-linux-armhf.so.3`). Any soft-float binary (e.g. re-kindle's `fbink`) will not run; KOReader's bundled `fbink` does. | VERIFIED (probe 2026-11-18) |
| Ads | Ad-supported ("special offers") Kindle (AdBreak needs one). **Sleeping from KOReader shows KOReader's sleep screen with no ad.** Ads appear only after the battery runs flat and the device reboots into the stock UI. | VERIFIED (Tyler) |
| SSH | KOReader's Dropbear, port 2222, user `root`, password changed from the default. Password login from Tyler's machine already works with a stock OpenSSH client, so host-key negotiation is fine: **no `HostKeyAlgorithms` override needed.** | VERIFIED |
| Dropbear | Old build (v2018.76 per MobileRead) → use an **RSA key**; the client needs `PubkeyAcceptedAlgorithms +ssh-rsa` for **user** authentication. No `scp`: use `sftp` or `cat file \| ssh kindle 'cat > path'` | INFERRED |
| Kindle IP | `192.168.1.70` (DHCP; set a reservation on the router) | VERIFIED |
| Server | `home-server`, same LAN `192.168.1.0/24`, runs Docker/Portainer 24/7 | VERIFIED |
| rootfs | Observed mounted **rw** (ext3) at probe time. Rule 2 applies regardless: no writes outside `/mnt/us/` | VERIFIED (probe) |
| Resolution | **1072×1448**, 300 ppi, 16 grey levels. Framebuffer is padded (virtual 1088 wide, stride 1088); **use the size KOReader reports**, not `fb0/virtual_size`. | VERIFIED (probe) |
| KOReader | **v2026.07.2** (updated 2026-11-18); sleep screen already in "image file" mode (`document_cover`), message off, stretch off. KOReader draws its own sleep screen because `com.lab126.blanket load` has no `ad_screensaver` | VERIFIED (probe) |
| User storage | `/mnt/us` is `fuse.fsp` (not vfat) | VERIFIED (probe) |
| Orientation | **Upright** on a stand with a cutout / corner pads keeping the power button clear. Frames are never rotated. | VERIFIED (Tyler, §11 Q2) |

### Unknown; Phase 0 must answer

- Confirm firmware 5.18.1 and the hard-float loader (`/lib/ld-linux-armhf.so.3`).
- KOReader version, and its sleep-screen options: type (single image file vs random image from folder), stretch/fit, "sleeping" message, rotation handling, background fill.
- **The sleep timing window (most important).** On Kindle, the stock powerd starts the sleep: how long between KOReader drawing the sleep screen and the device actually suspending? Can a plugin keep Wi-Fi up and redraw within that window, or delay suspend safely? Answer from KOReader's source (Kindle device / powerd event handling) and from a measurement on the device.
- How long Wi-Fi takes to come up and fetch a PNG on this device (measure with the radio off at the start).
- Which extensions are already in `/mnt/us/extensions/`, and whether KindleForge offers anything reusable.

## 4. Architecture & decisions

```
[home-server: renderer container] --HTTP (LAN)--> [Kindle: KOReader plugin]
   photos / HTML templates                         on sleep: show cached image at once → Wi-Fi → GET PNG → save → redraw sleep screen → suspend
   → grayscale + 16-level dither
```

- **D1: Render on the server, display on the Kindle.** Logic and design live in Python/HTML on the server; changing the look never touches the device.
- **D2: Reuse what already runs on the device.** KOReader is already the right ABI build and already owns the sleep screen, so the client lives inside KOReader. External binaries only if Phase 0 confirms an ABI-matching build.
- **D3: Protocol.** `GET /frame.png?batt=<pct>&w=<width>&h=<height>` returns a PNG at the requested size, grayscale and dithered. No caching tricks: KOReader redraws the sleep screen every time anyway, and dashboards carry a "rendered at" stamp, so byte-identical output and hash-skipping would save almost nothing.
- **D4: Renderer.** HTML/CSS → headless Chromium (Playwright) screenshot → Pillow: grayscale, Floyd–Steinberg dither to 16 levels. Photo mode uses Pillow directly (crop/fit + dither). No rotation (upright mount, §11 Q2).
- **D5: How the client runs.**
  - (c) **KOReader plugin + KOReader's sleep screen. Default.** Fits "it stays a reader"; no stock-framework fights, no ad overlay (VERIFIED by Tyler's daily use), normal sleep battery.
  - (b) KOReader plugin with auto-refresh while awake (`usetrmnl/trmnl-koreader` style): rejected. It prevents sleep, and one user reports poor battery.
  - (a) KUAL extension + shell loop (re-kindle / ktrm style): **parked**. It only makes sense for an always-on dashboard, which is now a non-goal.
- **D6: Sleep flow (draw first, then refresh).**
  1. On sleep, KOReader shows the **cached** image immediately (the one fetched last time), so pressing power feels instant.
  2. In the background: bring Wi-Fi up, fetch, validate, save atomically to the cached path (temp file + rename).
  3. If a new image arrives inside the time window Phase 0 measured, redraw the sleep screen with it. Then restore the Wi-Fi state and let the device suspend.
  4. If the fetch misses the window or fails: keep the cached image, restore Wi-Fi, suspend normally.
  5. **If the device wakes mid-fetch** (Tyler presses power again): cancel the fetch, skip the redraw (never paint the sleep screen over the reading view), and restore Wi-Fi.
  - When a new image arrives, each sleep shows two full e-ink refreshes (cached image, then the new one). Accepted as the price of instant sleep.
  - **If Phase 0 shows there is no usable window** (e.g. powerd suspends right after the sleep screen), stop and ask Tyler. The choice is his: accept an image that is one sleep cycle stale (prefetch while awake or on resume), or accept a slower sleep (fetch before drawing).
- **D7: Wi-Fi.** The plugin restores whatever Wi-Fi state it found. If Wi-Fi was off before sleep, it turns it on only for the fetch and off again afterwards. It never edits saved networks. *(Measured: the radio stays up during the 60 s SCREEN SAVER phase, is powered off during real suspend, and wifid reconnects by itself after wake in ~3–13 s.)* Fetch budget: configurable, default 25 s total (Wi-Fi up + request). **Effective budget = min(configured budget, measured sleep window − safety margin)**, so the device never suspends with a fetch still in flight.
- **D8: Why no refresh while asleep.** The Kindle drops Wi-Fi when it suspends (Tyler's observation, INFERRED; confirm in Phase 0). Any refresh while asleep therefore means waking the CPU, reconnecting Wi-Fi from scratch and suspending again, every cycle. Staying awake to keep Wi-Fi up (trmnl-koreader's auto-refresh) is worse still. Fetching once per sleep, inside the window before suspend, is the cheapest option and matches §1.

## 5. Safety rules (Claude Code must follow)

1. **Read-only diagnostics first, changes second.** Every write on the Kindle is preceded by a check that confirms its precondition.
2. **No `mntroot rw`**, and no writes outside `/mnt/us/` without asking Tyler. Project files live in `/mnt/us/koreader/plugins/kindaframe.koplugin/` and `/mnt/us/kinda-frame/` (images, logs).
3. **KOReader settings:** change sleep-screen settings **through the KOReader menu** (Tyler does it), or edit `settings.reader.lua` **only while KOReader is closed**, because KOReader keeps settings in memory and writes them back, overwriting hand edits (INFERRED). Always back the file up first (timestamped copy). Tyler's current sleep-screen setup must be restorable in one step.
4. **Graceful failure:** a failed or slow fetch must never block suspend, crash KOReader, or leave Wi-Fi in a different state than the plugin found it.
5. Wi-Fi toggling by the plugin is allowed (D7). Editing saved networks, firmware/OTA updates, the jailbreak hotfix, and modifying or uninstalling KUAL, KindleForge or KOReader itself are not.
6. `home-server`: deploy as its own container. **Don't restart the Docker daemon and don't touch other services/containers** (the box also hosts other people's things).
7. **Privacy:** no real name in the repo or commits (author `Tyler` / `@tyler-void`, alias email). Coordinates, API keys and personal photo paths go in an **uncommitted** config/`.env` (`.gitignore` it). The repo is private on Forgejo by default. If it ever goes public, move the LAN IP, hostnames and infra details out of this spec into an untracked local note.
8. **Licensing:** `abdenourgnx/re-kindle` has **no LICENSE**: read it for ideas only, **don't copy code**. Reuse code from other repos (trmnl-koreader, ktrm, kindle-dash) only after checking their licence.

## 6. Phase 0: Device probe (read-only)

**Precondition (Tyler's step, needs the root password):** install an RSA key so `ssh kindle` works without a password prompt.

```sh
ssh-keygen -t rsa -b 4096 -f ~/.ssh/kindle_pw4 -C kindle
cat ~/.ssh/kindle_pw4.pub | ssh -p 2222 root@192.168.1.70 'mkdir -p /mnt/us/koreader/settings/SSH && cat >> /mnt/us/koreader/settings/SSH/authorized_keys'
```

`~/.ssh/config`:

```
Host kindle
    HostName 192.168.1.70
    Port 2222
    User root
    IdentityFile ~/.ssh/kindle_pw4
    PubkeyAcceptedAlgorithms +ssh-rsa
```

Then run these and write all output to `docs/device-probe.md` (all read-only; if a command doesn't exist, record "missing"):

```sh
cat /etc/prettyversion.txt                      # firmware
uname -a
ls -l /lib/ld-linux*.so.3                       # soft-float vs hard-float loader
cat /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/bits_per_pixel
ls /mnt/us/koreader /mnt/us/koreader/plugins    # KOReader layout, installed plugins
cat /mnt/us/koreader/git-rev 2>/dev/null        # KOReader version, if present
grep -n -i 'screensaver' /mnt/us/koreader/settings.reader.lua   # current sleep-screen settings
ls /mnt/us/extensions
lipc-get-prop com.lab126.powerd battLevel
lipc-get-prop com.lab126.cmd wirelessEnable
df -h /mnt/us
```

Also, from KOReader's source for the installed version: the screensaver module, the Kindle suspend/resume event flow, the network manager's Wi-Fi on/off API, and what screen size KOReader reports. D6 depends on two things to confirm there: **the sleep screen re-reads the image file each time it is shown** (no in-memory cache), and **a plugin can trigger a second sleep-screen draw** while still in the sleep state.

Then **measure on the device** (Tyler presses the power button; Claude Code watches KOReader's `crash.log` / a debug log): the time from the sleep screen being drawn to actual suspend, the time for Wi-Fi up + one HTTP fetch, and whether Wi-Fi is dropped on suspend.

**Battery baseline:** before installing the plugin, record battery % at the start and end of one day of Tyler's normal use (light level and reading time roughly noted). Phase 2 compares against this.

**Done when** `docs/device-probe.md` records: firmware + ABI verdict, the KOReader-reported screen size, KOReader version, current sleep-screen settings and options, the suspend hooks a plugin can use (with source references), the measured sleep window and Wi-Fi/fetch time, whether Wi-Fi drops on suspend, the battery baseline, and a go/no-go for D6.

## 7. Phase 1: Hello PNG via KOReader sleep screen (no code, no server)

- Generate a test image on the dev machine at the KOReader-reported size: 16 grey steps, large text, a "TOP" arrow pointing at the power-button edge.
- Push it to `/mnt/us/kinda-frame/current.png` (sftp or `cat | ssh`).
- Tyler points KOReader's sleep screen at that file through the menu (or, if KOReader only supports "random image from folder", at `/mnt/us/kinda-frame/` containing only that file), with stretch/fit and the sleeping message set as Phase 0 recommends. Then he presses the power button.

**Done when** the sleep screen shows the image filling the screen with no scaling or offset, all 16 grey steps distinguishable, **no KOReader "sleeping" message or other overlay on top**, and no ad. Record the result.

> At this point the picture frame already works with zero code: put photos in a folder and point KOReader's sleep screen at a random image from it. Everything after this is about **fresh, server-rendered** content.

## 8. Phase 2: KOReader plugin `kindaframe.koplugin` (against a stub server)

- Test server for this phase: a static stub on the dev machine or home-server (e.g. `python -m http.server` serving a few test PNGs, swapped by hand) so Phase 2 doesn't depend on Phase 3.
- Menu under Tools: Fetch now, Enable/disable refresh-on-sleep, Server URL, Fetch budget, Show last fetch status.
- Implements D6 (draw first, then refresh) and D7 (restore Wi-Fi state, budget).
- Validate before saving: HTTP 200, size > 0, PNG magic bytes, expected dimensions.
- Config lives in KOReader's plugin settings (server URL and budget only, nothing sensitive).
- Small rotating log file in `/mnt/us/kinda-frame/`.

**Done when:**
- the sleep screen appears within about a second of pressing power (cached image);
- over 20 sleep/wake cycles, the newest stub image replaces the cached one whenever the fetch fits the window;
- with the stub server down, sleep still works, shows the last good image, and Wi-Fi ends in its original state;
- waking the device mid-fetch returns cleanly to the reading view, with no late sleep-screen redraw and Wi-Fi restored;
- reading in KOReader is unaffected; battery drain over a day of normal use is comparable to the Phase 0 baseline.

## 9. Phase 3: Renderer on home-server

- Its own container (Python + Playwright + Pillow), port exposed on the LAN only.
- Endpoints `GET /frame.png` (+ `GET /healthz`). Configured by `config.toml` (`mode = art|photo|dashboard`, `[art]`, `[photo]`, later `[dashboard]`); LAN bind from `.env`. Size comes from the request (`w`, `h`).
- **Build order (Tyler, updated 2026-11-18):** no photos yet → **generative art mode first** (4 generators: Chladni figures, flow fields, strange attractors, harmonograph/epicycle orbits; inspired by Blackbody, original code; see `docs/art.md`). Photo mode built alongside for later. Then the dashboard.
- `photo`: pick an image (random or sequential), crop/fit, boost contrast, dither to 16 levels.
- `dashboard`: HTML/CSS template → screenshot → grayscale/dither. Built from interchangeable **boards**, one selected at a time. First board: **daily** (date, the day's weather, today's calendar). Later boards, added without touching the device or other boards: RSS/news headlines, a trend tracker, or anything else fun. Board data (feeds, weather, calendar, trends) is fetched by the server, never the Kindle; if one source fails, that section shows "unavailable" and the frame still renders. The frame can sit on screen for hours, so show *when* it was rendered and prefer content that stays valid (date, the day's weather, today's calendar) over anything time-of-day.

**Done when** images come out at the requested size, render in a few seconds, and the Kindle shows them on sleep via the Phase 2 plugin.

## 10. Phase 4: Optional

- **After a flat battery:** the device reboots into the stock UI (ads on its lock screen) until KOReader is opened again. Investigate whether KOReader can be started automatically after boot (KUAL/KindleForge options); report findings, don't enable without asking Tyler.
- Special images for occasions (birthday, Tết, …).
- Package the plugin for KindleForge (only if the repo goes public).

## 11. Open questions for Tyler

Only Q6 is still open.

1. ~~Which first, and what should the dashboard show?~~ Photo mode first, then a dashboard of swappable boards: daily (date, weather, calendar) first, later RSS board, trend tracker, or something cool (VERIFIED).
2. ~~**Orientation.**~~ **Decided: (a) upright** (VERIFIED). Original options kept for the record: The PW4 can't tell how it is being held (no accelerometer, INFERRED), so a frame pre-rotated 180° for an upside-down mount shows upside down whenever you put it to sleep while holding it. Options:
   - (a) **Mount it upright** on a stand with a cutout (or rest it on two corner pads so the power button is clear). No rotation, no conflict. *Recommended for dual use.*
   - (b) Mount it at 180° and accept an upside-down frame until it's docked.
   - (c) Mount it at 180° and add a plugin toggle ("docked: rotate 180°") that is sent with the request.
3. ~~Will the Kindle still be used for reading?~~ Yes: it stays a reader (VERIFIED), hence D5-c.
4. ~~Refresh while asleep?~~ No: a fresh image on every sleep is enough (VERIFIED).
5. ~~Ads over the KOReader sleep screen?~~ Only after a flat battery + reboot into the stock UI (VERIFIED).
6. Repo: private on Forgejo or public on GitHub?

## 12. References

- KOReader: sleep screen (screensaver) settings, Kindle suspend handling, network manager, plugin system. Read the source for the installed version (`frontend/ui/screensaver.lua`, the Kindle device code, `plugins/*.koplugin` for examples).
- `usetrmnl/trmnl-koreader`: TRMNL display plugin for KOReader. Useful reference for fetch + display inside KOReader. Its auto-refresh mode **prevents sleep**; one user found it reliable but poor on battery.
- `amarder/ktrm`: minimal Kindle TRMNL client: power button → wake, fetch, full refresh, sleep. Notes that the Kindle OS occasionally draws a status icon over the image.
- `abdenourgnx/re-kindle`: weather dashboard for a Kindle 7th gen. Background reading only (D5-a is parked). **No LICENSE: read only.**
- `pascalw/kindle-dash`, `mbirth/trmnl-kindle`: shell-loop clients; background reading only. The latter targets FW 5.15.1.1 (soft-float), so don't reuse its binaries.
- Stock screensaver hack: kindlemodding's FAQ says no screensaver-changing extension exists for hard-float firmware. Irrelevant here because KOReader draws its own sleep screen.
- KindleForge (app store for jailbroken Kindles, KindleTweaks org): check its catalogue before building any helper binary yourself.
- KOReader wiki, SSH: <https://github.com/koreader/koreader/wiki/SSH>
- kindlemodding.org, Jailbreak FAQ (soft-float vs hard-float): <https://kindlemodding.org/jailbreaking/Legacy/jailbreak-faq.html>
