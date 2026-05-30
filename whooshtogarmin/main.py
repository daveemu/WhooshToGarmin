"""Service entry point: poll myWhoosh, convert, upload to Garmin, repeat."""

from __future__ import annotations

import argparse
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from whooshtogarmin.config import Settings
from whooshtogarmin.converter import convert_fit
from whooshtogarmin.downloader import MyWhooshDownloader
from whooshtogarmin.state import StateStore
from whooshtogarmin.uploader import GarminUploader

logger = logging.getLogger("whooshtogarmin")


def base_interval(settings: Settings, hour: int) -> int:
    """Poll interval (seconds) before jitter, widened during quiet hours."""
    if settings.is_quiet_hour(hour):
        return int(settings.poll_interval_seconds * settings.quiet_interval_multiplier)
    return settings.poll_interval_seconds


def jittered(interval: int, fraction: float, rng: random.Random) -> float:
    """Apply +/- ``fraction`` jitter so polls don't align to an exact schedule."""
    return interval * (1 + rng.uniform(-fraction, fraction))


def next_sleep_seconds(
    settings: Settings, *, now: datetime, rng: random.Random
) -> float:
    return jittered(
        base_interval(settings, now.hour), settings.jitter_fraction, rng
    )


class SyncService:
    """Wires the downloader, converter, uploader and state together."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tz = ZoneInfo(settings.tz_name)
        self.state = StateStore(settings.state_path)
        self.downloader = MyWhooshDownloader(
            settings.storage_state_path,
            settings.download_dir,
            headless=settings.headless,
        )
        self.uploader = GarminUploader(
            settings.garmin_tokenstore, is_cn=settings.garmin_is_cn
        )

    def run_once(self) -> int:
        """One sync cycle. Returns the number of activities newly uploaded."""
        new_activities = self.downloader.fetch_new(self.state.known_identities())
        if not new_activities:
            logger.debug("No new myWhoosh activities")
            return 0

        synced = 0
        for activity, fit_path in new_activities:
            try:
                cleaned = Path(fit_path).with_suffix(".garmin.fit")
                convert_fit(fit_path, cleaned, tz_name=self.settings.tz_name)
                result = self.uploader.upload(cleaned)
            except Exception:
                logger.exception("Failed to process activity %s", activity.identity)
                continue

            self.state.record(
                activity.identity,
                garmin_activity_id=result.activity_id,
                duplicate=result.duplicate,
            )
            if result.duplicate:
                logger.info("Activity %s already on Garmin", activity.identity)
            else:
                logger.info(
                    "Uploaded %s -> Garmin activity %s",
                    activity.identity,
                    result.activity_id,
                )
                synced += 1
        return synced

    def run_forever(self) -> None:
        rng = random.Random()
        backoff = self.settings.backoff_initial_seconds
        logger.info(
            "Starting sync loop (interval %ss, tz %s)",
            self.settings.poll_interval_seconds,
            self.settings.tz_name,
        )
        while True:
            try:
                self.run_once()
                backoff = self.settings.backoff_initial_seconds  # reset on success
                sleep_for = next_sleep_seconds(
                    self.settings, now=datetime.now(self.tz), rng=rng
                )
            except Exception:
                logger.exception("Sync cycle failed; backing off %ss", backoff)
                sleep_for = backoff
                backoff = min(backoff * 2, self.settings.backoff_max_seconds)
            logger.debug("Sleeping %.0fs", sleep_for)
            time.sleep(sleep_for)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="myWhoosh -> Garmin Connect sync")
    parser.add_argument(
        "--once", action="store_true", help="run a single sync cycle and exit"
    )
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)
    service = SyncService(settings)

    if args.once:
        synced = service.run_once()
        logger.info("Synced %d new activities", synced)
        return 0
    service.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
