# Restore the original sleep screen (FR-021)

Tyler's setup before kinda-frame: **custom image** `/mnt/us/koreader/wallpapers/<previous wallpaper>` (real file name in `.local/infra.md`, not in this public repo), message off, stretch off, black background.
That file is never touched by this project.

## One step (on the Kindle, recommended)

File browser → top menu → **Screen** tab → **Sleep screen** → **Wallpaper** → **Custom images** → **Choose image or document cover** → pick your previous wallpaper in `/mnt/us/koreader/wallpapers/`.

The other sleep-screen settings were not changed, so this is the whole restore.

## Full settings rollback (only if more than the image path changed)

Backups are in `/mnt/us/kinda-frame/backup/settings.reader.lua.<YYYYmmdd-HHMMSS>` (the first one: `…20261118-201437`, taken before any change).

KOReader rewrites its settings file from memory, so the copy has to happen **while KOReader is not running**. KOReader's SSH server stops with it, so this can't be done over KOReader's SSH:

1. Exit KOReader (back to the stock UI).
2. Connect the Kindle by USB, or use KUAL → kterm.
3. Copy the backup over `koreader/settings.reader.lua`.
4. Start KOReader again from KUAL.

## Remove the plugin (after M2)

Delete `/mnt/us/koreader/plugins/kindaframe.koplugin` and restart KOReader. `/mnt/us/kinda-frame/` can be deleted too (frames, logs, backups).
