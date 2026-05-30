# WhooshToGarmin

Automatically sync your [myWhoosh](https://www.mywhoosh.com/) rides to
[Garmin Connect](https://connect.garmin.com/). myWhoosh offers a Strava
integration but none for Garmin — this fills the gap with a small headless
service you run yourself (Podman / Quadlet on a Linux server).

## How it works

Every poll cycle the service does the cheap thing first and the expensive thing
only when needed:

```
loop (every ~15 min, jittered, slower during quiet hours):
  └─ check myWhoosh for activities (headless browser, reuses saved session)
       ├─ nothing new?  → sleep
       └─ new activity:
            ├─ download the .fit (intercept the presigned S3 URL)
            ├─ convert it (fix local timestamp, etc.)
            ├─ upload to Garmin Connect (token-based, no password at runtime)
            └─ record it in state.json (so it's never re-processed)
```

- **Download** — `whooshtogarmin/downloader.py` drives headless Chromium with a
  saved `storage_state` (the `webToken` JWT), reads the activities table, and
  intercepts the `download-activity-file` presigned URL. Token expiry is checked
  locally first, so an expired session fails fast without a network call.
- **Convert** — `whooshtogarmin/converter.py` (see below).
- **Upload** — `whooshtogarmin/uploader.py` uses
  [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) with a
  saved OAuth token store. Duplicate activities (Garmin 409 / message code 202)
  are treated as success.
- **State** — `whooshtogarmin/state.py`, an atomic JSON store keyed by activity
  identity. Garmin's own duplicate detection is the backstop.

> **garth note:** Garmin broke garth's mobile SSO in March 2026, so this project
> uses the maintained `garminconnect` (native `curl_cffi` auth) instead.

## What the converter fixes

Verified against a current, real myWhoosh export. Modern myWhoosh files are
already clean — they identify honestly as FIT manufacturer `331`
("MyWhoosh Technology Services LLC"), already contain average power / HR /
cadence, and carry no bogus temperature field. We **do not** spoof the device
as a Garmin unit.

| Fix | When it triggers |
| --- | --- |
| Normalise `activity.local_timestamp` to local wall-clock time | Always — current files ship a garbage value (~20 years off) that misplaces the activity's local time in Garmin |
| Backfill missing avg power / HR / cadence (session + laps) | Defensive — only if absent (older file formats) |
| Strip the temperature field | Defensive — only if present (older file formats) |

> Because myWhoosh is not a Garmin-"certified" source, activities import fully
> and correctly but do **not** feed VO₂max / FTP estimate / Training Status.
> This is the intended, honest trade-off (no device spoofing).

Convert a single file manually:

```bash
pip install -e .
python -m whooshtogarmin.converter my_activity.fit -o cleaned.fit --tz Europe/Vienna
```

## Deploy (Podman + Quadlet, rootless)

```bash
# 1. Build the image
podman build -t whooshtogarmin:latest .

# 2. Create data + config dirs
mkdir -p ~/.local/share/whooshtogarmin ~/.config/whooshtogarmin

# 3. One-time logins (run on a machine with a browser; copy results into the data dir)
python scripts/bootstrap_mywhoosh.py --out ~/.local/share/whooshtogarmin/session.json
python scripts/bootstrap_login.py    --tokenstore ~/.local/share/whooshtogarmin/garmin_tokens

# 4. Configure + install the Quadlet unit
cp deploy/whooshtogarmin.env.example ~/.config/whooshtogarmin/whooshtogarmin.env  # edit it
cp deploy/whooshtogarmin.container   ~/.config/containers/systemd/

# 5. Start (and keep running after logout)
systemctl --user daemon-reload
systemctl --user start whooshtogarmin
loginctl enable-linger "$USER"

# Logs
journalctl --user -u whooshtogarmin -f
```

Re-run `bootstrap_mywhoosh.py` whenever the myWhoosh token expires; the Garmin
token store is long-lived and auto-refreshed.

## Configuration

All settings are `WHOOSH2GARMIN_*` environment variables — see
[`deploy/whooshtogarmin.env.example`](deploy/whooshtogarmin.env.example).
Key ones: `POLL_INTERVAL_SECONDS`, `JITTER_FRACTION`, `QUIET_HOURS_*`,
`TZ_NAME`, `GARMIN_IS_CN`, `LOG_LEVEL`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests synthesize FIT files in-memory — no personal activity data is committed.
The Playwright/DOM layer (`downloader.py`) is validated against a live myWhoosh
account; its pure logic (JWT expiry, URL validation, dedup identity) is
unit-tested.

## Status

- **M1 — FIT converter** ✅
- **M2 — Garmin uploader** ✅
- **M3 — myWhoosh downloader** ✅ (browser layer needs live-account verification)
- **M4 — orchestration, state, polling loop** ✅
- **M5 — Containerfile + Quadlet + bootstrap** ✅
