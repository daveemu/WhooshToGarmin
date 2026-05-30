# WhooshToGarmin

Sync [myWhoosh](https://www.mywhoosh.com/) activities to
[Garmin Connect](https://connect.garmin.com/), running as a small headless
service (Podman / Quadlet on a Linux server).

myWhoosh offers a Strava integration but none for Garmin Connect. This project
fills that gap: it downloads new activity `.fit` files from your myWhoosh
account, cleans them up so Garmin accepts them, and uploads them — automatically.

## Status

Under active development. Implemented so far:

- **M1 — FIT converter** ✅ (`whooshtogarmin/converter.py`)
- M2 — Garmin uploader (garth)
- M3 — myWhoosh downloader (lightweight poll + Playwright)
- M4 — orchestration, state/dedup, polling loop
- M5 — Containerfile + Quadlet unit + bootstrap

## What the converter fixes

Verified against a current, real myWhoosh export. Modern myWhoosh files are
already fairly clean — they identify honestly as FIT manufacturer `331`
("MyWhoosh Technology Services LLC"), already contain average power / heart
rate / cadence, and carry no bogus temperature field. We **do not** spoof the
device as a Garmin unit.

| Fix | When it triggers |
| --- | --- |
| Normalise `activity.local_timestamp` to local wall-clock time | Always — current files ship a garbage value (~20 years off) that misplaces the activity's local time in Garmin |
| Backfill missing avg power / HR / cadence (session + laps) | Defensive — only if absent (older file formats) |
| Strip the temperature field | Defensive — only if present (older file formats) |

> Because myWhoosh is not a Garmin-"certified" source, activities import fully
> and correctly but do **not** feed VO₂max / FTP estimate / Training Status.
> This is the intended, honest trade-off (no device spoofing).

## Usage

```bash
pip install -e .
python -m whooshtogarmin.converter my_activity.fit -o cleaned.fit --tz Europe/Vienna
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests synthesize FIT files in-memory — no personal activity data is committed.
