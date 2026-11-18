# Feature Specification: Sleep-Screen Frame

**Feature Branch**: `001-sleep-screen-frame`
**Created**: 2026-11-18
**Status**: Draft
**Input**: User description: "kinda-frame: turn a jailbroken Kindle Paperwhite 4 into a picture frame / e-ink display via a KOReader plugin that fetches a fresh server-rendered PNG every time the device goes to sleep. Use SPEC.md in the repo root (rev. 5) as the authoritative source for requirements, decisions, safety rules, phases and acceptance criteria."

> **Source of truth:** `SPEC.md` (rev. 5) in the repo root holds the device facts, design decisions (D1–D8), safety rules and phase plan. This document restates the *what* and *why* as testable requirements; where they differ, raise it rather than silently picking one.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sleep screen shows a full-screen frame image (Priority: P1)

The owner reads on the Kindle as usual. When they put it to sleep, the sleep screen shows a single chosen image (a photo or a test card) filling the whole screen, with no ad, no "sleeping" message and no other overlay on top.

**Why this priority**: This is the picture frame itself, and it works with no network or server at all. Everything else only makes the image fresher.

**Independent Test**: Place one image on the device, point the sleep screen at it, press the power button. The frame is visible and correct without any other part of this feature existing.

**Acceptance Scenarios**:

1. **Given** a frame image at the device's exact screen size is in place, **When** the owner puts the device to sleep, **Then** the image fills the screen edge to edge with no scaling, offset or cropping.
2. **Given** a test image with 16 grey steps, **When** it is shown on the sleep screen, **Then** all 16 steps are distinguishable by eye.
3. **Given** the device is put to sleep from the reading app, **When** the sleep screen is drawn, **Then** no ad, "sleeping" message, clock or status icon is drawn over the image.

---

### User Story 2 - A fresh image every time the device goes to sleep (Priority: P2)

Each time the owner puts the Kindle to sleep, it shows the latest image from the home server (a new photo, or today's dashboard). Sleep still feels instant: the previous image appears straight away, and is replaced by the new one a few seconds later if it arrives in time.

**Why this priority**: This turns a static frame into a living one. It depends on Story 1's display working.

**Independent Test**: Serve a set of test images from any simple home-network source, change which one is served, put the device to sleep, and check that the newest one ends up on screen.

**Acceptance Scenarios**:

1. **Given** the server offers a new image, **When** the owner presses power, **Then** the previously saved image appears within about one second, and the new image replaces it before the device fully suspends.
2. **Given** Wi-Fi was off before sleep, **When** the device fetches the new image, **Then** Wi-Fi is turned on only for the fetch and is off again afterwards.
3. **Given** Wi-Fi was on before sleep, **When** the fetch ends, **Then** Wi-Fi is left in the state it was found in (the device's own suspend may still drop it).
4. **Given** the new image arrives, **When** it is saved, **Then** it becomes the image shown first on the next sleep.

---

### User Story 3 - Never gets in the way of reading or sleeping (Priority: P2)

Whatever happens with the network or server, the Kindle behaves like a normal reader: it always goes to sleep, always wakes back to the book, and the battery lasts about as long as before.

**Why this priority**: The device stays a reader (decided by the owner). A frame that blocks sleep, crashes the reading app or drains the battery is worse than no frame. It ships together with Story 2.

**Independent Test**: With the server switched off, and separately with Wi-Fi unavailable, put the device to sleep and wake it repeatedly; wake it mid-fetch; compare a day's battery use against a baseline taken before the feature was installed.

**Acceptance Scenarios**:

1. **Given** the server is unreachable or slow, **When** the owner puts the device to sleep, **Then** it sleeps normally showing the last good image, and Wi-Fi ends in its original state.
2. **Given** a fetch is still running, **When** the owner presses power again to wake the device, **Then** the device returns to the reading view, no sleep-screen image is drawn over it later, and Wi-Fi is restored.
3. **Given** the server returns something that is not a valid image of the expected size, **When** the device receives it, **Then** it is discarded and the last good image is kept.
4. **Given** a feature error of any kind, **When** the device goes to sleep, **Then** sleep still completes and the reading app keeps running.

---

### User Story 4 - The server decides what the frame shows (Priority: P3)

The owner changes what the frame looks like (generative art, photo mode or a dashboard "board") entirely on the home server, without touching the Kindle. **Generative art comes first** (owner's decision, 2026-11-18: no photos yet). Four generators, all original code inspired by Blackbody: Chladni figures, flow fields, strange attractors, harmonograph/epicycle orbits (see `docs/art.md`). Photo mode is built alongside for when photos exist; the dashboard follows, starting with a daily board (date, the day's weather, today's calendar), and is built so that other boards can be added later, e.g. an RSS/news board or a trend tracker.

**Why this priority**: It's needed for real content, but Stories 1–3 can be built and proven against hand-made test images first.

**Independent Test**: Request a frame from the server in each mode and check size, greyscale and content, with no Kindle involved; then confirm the Kindle shows it via Story 2.

**Acceptance Scenarios**:

1. **Given** art mode, **When** a frame is requested, **Then** the server returns a new piece from one of the configured generators (never the same generator twice in a row in random order), laid out on white paper with a caption showing title, parameters and seed, at the requested size and on the 16-grey palette; the same generator + seed reproduces the same image.
1b. **Given** photo mode and a folder of photos, **When** a frame is requested, **Then** the server returns one photo cropped/fitted to the requested screen size and converted for a 16-grey e-ink screen.
2. **Given** dashboard mode with the daily board selected, **When** a frame is requested, **Then** the server returns an image showing the date, the day's weather and today's calendar, plus when it was rendered, and no live clock.
4. **Given** a new board type (e.g. an RSS headline board or a trend tracker) is added on the server, **When** the owner selects it in the server configuration, **Then** the Kindle shows it on the next sleep with no change on the device.
3. **Given** the device reports its battery level with the request, **When** the dashboard is rendered, **Then** it can show the battery level.

---

### User Story 5 - Easy to undo (Priority: P3)

The owner can turn the refresh off, or go back to their previous sleep-screen setup in one step.

**Why this priority**: It's a safety net rather than a feature, but it's required before the feature is left running day to day.

**Independent Test**: Enable the feature, then disable it and restore the previous setup; the sleep screen behaves exactly as before installation.

**Acceptance Scenarios**:

1. **Given** the feature is enabled, **When** the owner disables refresh-on-sleep from the reading app's menu, **Then** the device stops fetching and simply shows the saved image.
2. **Given** the original sleep-screen settings were backed up before any change, **When** the owner restores them, **Then** the sleep screen is exactly as it was before the project.

---

### Edge Cases

- **Device wakes mid-fetch:** the fetch is cancelled and no late redraw happens (Story 3, scenario 2).
- **No usable time window before suspend:** if the device suspends almost immediately after drawing the sleep screen, the "draw, then refresh" flow is impossible. Work stops and the owner chooses between a one-sleep-stale image and a slower sleep (SPEC.md D6).
- **Partial download / power loss while saving:** the saved image is replaced atomically, so the next sleep never shows a corrupt or half-written image.
- **First run with no saved image yet:** the sleep screen falls back to the owner's previous sleep-screen behaviour until the first successful fetch.
- **Battery runs flat:** the device reboots into the stock interface and shows its ads until the reading app is opened again. Out of scope for this feature (SPEC.md Phase 4).
- **Device held instead of mounted:** with a landscape orientation selected, a frame shown while the device is held upright appears sideways (the PW4 has no orientation sensor). Portrait has no such conflict.
- **A board's data source is down** (e.g. weather service, an RSS feed): the server still returns a frame, marking that section as unavailable instead of failing the whole image.
- **Server returns the same image as last time:** shown as normal; no special handling.

## Requirements *(mandatory)*

### Functional Requirements

**Display (Story 1)**

- **FR-001**: The sleep screen MUST show the saved frame image at the device's native screen size, with no scaling, offset or cropping.
- **FR-002**: The sleep screen MUST show no overlay (ad, "sleeping" message, clock, status icons) on top of the frame when the device is put to sleep from the reading app.
- **FR-003**: Frame images MUST be greyscale and prepared for a 16-grey-level display.

**Refresh on sleep (Story 2)**

- **FR-004**: On every sleep, the device MUST first show the most recently saved frame immediately (target: within about one second of pressing power).
- **FR-005**: After showing the saved frame, the device MUST try to fetch a new frame from the home server, sending its screen size and battery level.
- **FR-006**: If a valid new frame arrives within the available time before suspend, the device MUST redraw the sleep screen with it and save it as the new saved frame.
- **FR-007**: The time spent fetching MUST NOT exceed the smaller of a configurable budget (default 25 s) and the measured time available before suspend, minus a safety margin.
- **FR-008**: The device MUST NOT refresh the frame while asleep (no periodic wake-ups), and MUST NOT keep itself awake to refresh.

**Reliability and safety (Story 3)**

- **FR-009**: A failed, slow or invalid fetch MUST NOT delay or block suspend, crash the reading app, or change which image is saved.
- **FR-010**: A received image MUST be validated (successful response, non-empty, a real image, expected dimensions) before it replaces the saved frame. The replacement MUST be atomic.
- **FR-011**: If the device is woken while a fetch is in progress, the fetch MUST be cancelled and no sleep-screen redraw may happen afterwards.
- **FR-012**: The feature MUST leave Wi-Fi in the state it found it (on → on, off → off) and MUST NOT change saved Wi-Fi networks.
- **FR-013**: The feature MUST keep a small, size-limited log of fetch attempts and outcomes on the device.
- **FR-014**: The device MUST only talk to the home server on the local network. No internet service is contacted from the device.

**Server-side content (Story 4)**

- **FR-015**: The server MUST return a frame at the screen size the device requests.
- **FR-016**: The server MUST support an **art mode** (generative pieces from configurable generators `chladni`, `flowfield`, `attractor`, `orbits`; random or cycling order; deterministic per seed; delivered first) and a **photo mode** (one image from a configured folder, random or sequential, fitted and contrast-adjusted for e-ink).
- **FR-017**: The server MUST support a dashboard mode made of interchangeable boards, selected in server configuration. The first board is the daily board (date, the day's weather, today's calendar). Adding a board (e.g. RSS headlines, trend tracker) MUST NOT require changes to the device or to existing boards.
- **FR-017a**: Every dashboard frame MUST show when it was rendered, MUST favour content that stays valid for hours over time-of-day content, and MUST still render if one of its data sources is unavailable.
- **FR-018**: All look-and-feel changes MUST be possible on the server alone, without changing anything on the device.
- **FR-019**: The owner MUST be able to choose the frame orientation on the device (plugin menu): **portrait**, **landscape resting on the left edge**, or **landscape resting on the right edge**. The server lays the frame out for that orientation and returns it in the device's fixed portrait buffer size. Changing the setting fetches a new frame immediately. *(Revised 2026-11-18; was "always upright".)*

**Control and undo (Story 5)**

- **FR-020**: The owner MUST be able, from the reading app's menu, to: fetch now, enable/disable refresh-on-sleep, set the server address, set the fetch budget, and see the last fetch status.
- **FR-021**: The owner's existing sleep-screen settings MUST be backed up before any change and be restorable in one step.

**Project constraints (from SPEC.md §5, binding on implementation)**

- **FR-022**: Nothing outside the device's user storage area may be written, and the device's system partition MUST NOT be made writable, without the owner's explicit approval.
- **FR-023**: Existing tools on the device (the reading app itself, the app launcher, the jailbreak app store, the jailbreak hotfix) MUST NOT be modified or removed. No firmware updates.
- **FR-024**: The server component MUST run isolated from the other services on the shared home server and MUST NOT disrupt them.
- **FR-025**: No real name, location coordinates, API keys or personal photo paths may be committed to the repository.

### Key Entities

- **Frame**: one greyscale image sized for the device screen. Attributes: size, mode it came from (photo/dashboard), time rendered.
- **Saved frame**: the last valid frame stored on the device; it is what the sleep screen shows first.
- **Fetch attempt**: one try to get a new frame during a sleep. Attributes: start time, duration, outcome (new frame / no change needed / timed out / server unreachable / invalid / cancelled by wake), Wi-Fi state before and after.
- **Device settings**: server address, fetch budget, refresh-on-sleep on/off, plus the backed-up original sleep-screen settings.
- **Board**: one dashboard layout with its own data sources (daily board first; RSS board, trend tracker, … later). Attributes: name, data sources, how often its data goes stale.
- **Server configuration**: mode, photo folder, selected board, board data sources. Kept out of the repository where it contains private data.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 20 consecutive sleep/wake cycles with the server available, a sleep screen appears within about 1 second of pressing power every time, and the newest server image is on screen at suspend in every cycle where the fetch fits the time window.
- **SC-002**: With the server switched off, 20 out of 20 sleeps complete normally, each showing the last good image, with Wi-Fi back in its original state.
- **SC-003**: In 10 attempts at waking the device mid-fetch, the reading view is never overdrawn by a sleep-screen image.
- **SC-004**: Battery use over a day of normal reading is no more than 20% higher than the baseline day recorded before the feature was installed.
- **SC-005**: The frame fills the screen with no visible offset or scaling, and all 16 grey steps of the test image are distinguishable.
- **SC-006**: A change to the frame's look (switching mode, editing the dashboard, adding photos) reaches the device on the next sleep with no change on the device.
- **SC-007**: Restoring the original sleep-screen setup takes one step and returns behaviour exactly to how it was before installation.
- **SC-008**: The server produces a frame in a few seconds (target: under 5 s), so it is ready well inside the device's fetch window.

## Assumptions

- **Single owner, single device.** One Kindle Paperwhite 4, used by one person, on one home network. No accounts or multi-user concerns.
- **The device stays a reader.** The frame only appears while asleep. An always-on dashboard and refresh-while-asleep are out of scope (owner's decision, SPEC.md §1–2).
- **The reading app owns the sleep screen.** Sleeping from it already shows its own sleep screen with no ad (verified by the owner). Ads only appear after a flat-battery reboot into the stock interface, which is out of scope.
- **The device drops Wi-Fi on suspend** (owner's observation, to be confirmed). That is why the fetch must finish in the short window between drawing the sleep screen and suspending.
- **Feasibility gate.** The "show saved image, then refresh" flow depends on a usable time window before suspend and on the sleep screen being redrawable. A read-only device probe (SPEC.md Phase 0) confirms both before any plugin work. If either fails, the owner decides the fallback.
- **Battery target.** "Comparable to before" is read as at most 20% more daily drain than the measured baseline.
- **Orientation (owner's decision, revised 2026-11-18).** Selectable per device: portrait, or landscape resting on the left edge (the owner's preferred stand position: power button and USB on the right) or on the right edge.
- **Board data comes from the server side.** RSS feeds, weather, calendars and trend data are fetched by the home server, which may use the internet; the Kindle itself still only talks to the home server (FR-014). Credentials and feed lists live in uncommitted server config.
- **Double refresh accepted.** When a new image arrives, the screen refreshes twice during sleep (saved image, then new one). This is the price of instant sleep.
- **Outside the home network** is out of scope for this feature: the Kindle keeps its last frame away from home. Chosen direction for a later feature: Cloudflare tunnel + secret token, LAN first (SPEC.md §2).
- **Testing order.** Stories 2–3 are proven against a simple stand-in image source before the real server (Story 4) exists.
- **Dependencies:** the existing jailbreak, the reading app and its remote-login access, and an always-on home server on the same network.
