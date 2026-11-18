# Quickstart: Sleep-Screen Frame

Placeholders: `<kindle-ip>` and `<server-lan-ip>` (the real values live in SPEC.md §3 while the repo is private). Steps marked 🧑 are Tyler's.

## 0. One-time SSH setup (🧑, needs the root password)

```sh
ssh-keygen -t rsa -b 4096 -f ~/.ssh/kindle_pw4 -C kindle
cat ~/.ssh/kindle_pw4.pub | ssh -p 2222 root@<kindle-ip> \
  'mkdir -p /mnt/us/koreader/settings/SSH && cat >> /mnt/us/koreader/settings/SSH/authorized_keys'
```

`~/.ssh/config`:

```
Host kindle
    HostName <kindle-ip>
    Port 2222
    User root
    IdentityFile ~/.ssh/kindle_pw4
    PubkeyAcceptedAlgorithms +ssh-rsa
```

Check: `ssh kindle true` returns without a password prompt.

## 1. Probe (M0, read-only)

Run the command list in SPEC.md §6 and save the output to `docs/device-probe.md`. Additionally record:

- the KOReader version, and how KOReader's Special Offers check comes out on this device (research R0);
- the sleep window: enable the probe log, press power 10×, note the `onSuspend` → last-log-line gap;
- whether Wi-Fi is still up after a sleep/wake (`lipc-get-prop com.lab126.cmd wirelessEnable` before and after);
- a battery baseline: battery % at the start and end of one normal day.

## 2. Static frame (M1, no code)

```sh
python3 tools/make-test-card.py --w <W> --h <H> -o tools/stub/frame.png   # W×H = KOReader-reported size
ssh kindle 'mkdir -p /mnt/us/kinda-frame/backup'
cat tools/stub/frame.png | ssh kindle 'cat > /mnt/us/kinda-frame/current.png'
```

🧑 Set it up in KOReader's menu (*Settings → Screen → Sleep screen*):
- wallpaper: **image file** → `/mnt/us/kinda-frame/current.png`
- sleep screen message: **off**
- stretch: **off**; background: **white**

If you edit `settings.reader.lua` by hand instead, close KOReader first and back up the file to `/mnt/us/kinda-frame/backup/settings.reader.lua.<timestamp>`.

**Verify:** press power. The card fills the screen, all 16 steps are distinct (check the light end), and there's no "Sleeping" message and no ad.

## 3. Plugin against the stub (M2)

```sh
cd tools/stub && python3 -m http.server 8787 --bind <dev-ip>     # dev machine, LAN; serves tools/stub/frame.png
ssh kindle 'mkdir -p /mnt/us/koreader/plugins/kindaframe.koplugin'
tar -C plugin --exclude=spec -cf - kindaframe.koplugin | ssh kindle 'tar -C /mnt/us/koreader/plugins -xf -'
```

Restart KOReader. 🧑 *Tools → Kinda Frame*: Server URL `http://<dev-ip>:8787/frame.png` (**use an IP, not a hostname**), then turn *Refresh on sleep* on.

**Verify (spec SC-001 to SC-003):**
1. Swap `tools/stub/frame.png` for a different image, then sleep: the old image appears in about 1 s and the new one replaces it before suspend.
2. Stop the stub, then sleep 20×: every sleep works, showing the last image.
3. Sleep and wake again within 2 s, 10×: you're always back in the book and nothing draws over it later.
4. `ssh kindle 'tail /mnt/us/kinda-frame/kindaframe.log'`: `wifi_before` = `wifi_after` on every line.

## 4. Server (M3)

On `home-server`:

```sh
# from the dev machine: sync the stack (never -a or tar: keeps the logbook's permission rules)
rsync -rlt --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude config.toml --exclude .env --exclude photos server/ home-server:kinda-frame/
# on home-server, in ~/kinda-frame (first time only: config, photo folder, LAN bind)
cp config.example.toml config.toml        # mode = "art" by default; edit locally, never commit
mkdir -p photos
echo "KF_BIND=<server-lan-ip>" > .env && chmod 600 .env
docker compose -p kinda-frame up -d --build
curl -s http://<server-lan-ip>:8787/healthz
curl -s -o /tmp/f.png 'http://<server-lan-ip>:8787/frame.png?w=<W>&h=<H>' && python3 -c "from PIL import Image; i=Image.open('/tmp/f.png'); print(i.size, i.mode, sorted(set(i.getdata()))[:5])"
```

Point the plugin's Server URL at `http://<server-lan-ip>:8787/frame.png`.

Only ever run `docker compose -p kinda-frame …`. Never restart Docker and never touch other stacks.

## 5. Development checks

```sh
cd plugin/kindaframe.koplugin && luajit spec/run.lua   # dependency-free busted-style runner, 45 tests incl. stubbed-KOReader scenarios
cd server && pytest
```

## 6. Undo (FR-021)

1. *Tools → Kinda Frame → Refresh on sleep*: off. The sleep screen keeps showing the saved image.
2. Full restore: follow `docs/restore.md`. Close KOReader and copy the newest `/mnt/us/kinda-frame/backup/settings.reader.lua.*` back to `/mnt/us/koreader/settings.reader.lua`. Optionally remove `/mnt/us/koreader/plugins/kindaframe.koplugin`.

## After a flat battery

The device boots into the stock UI (with ads) until KOReader is opened. Open KOReader, then sleep once and check that the frame, not an ad, appears. Quick check over SSH:

```sh
ssh kindle 'lipc-get-prop com.lab126.blanket load'   # must NOT contain ad_screensaver
```

If it lists `ad_screensaver`, or an ad shows from inside KOReader, research R0 has changed: stop and investigate.
