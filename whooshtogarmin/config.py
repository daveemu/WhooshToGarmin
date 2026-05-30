"""Runtime configuration, populated from environment variables.

All settings carry sensible defaults for a containerised deployment that mounts
a persistent ``/data`` volume. Override any of them via ``WHOOSH2GARMIN_*`` env
vars (e.g. ``WHOOSH2GARMIN_POLL_INTERVAL_SECONDS=600``).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WHOOSH2GARMIN_", env_file=".env", extra="ignore"
    )

    # Persistent state / secrets live under this directory (mount as a volume).
    data_dir: Path = Path("/data")

    # Timezone used to normalise the activity's local timestamp.
    tz_name: str = "Europe/Vienna"

    # Polling: how often to check myWhoosh for new activities, plus jitter so we
    # never hit the API on an exact schedule.
    poll_interval_seconds: int = 900
    jitter_fraction: float = Field(default=0.1, ge=0.0, le=0.5)

    # Optional quiet window (local hours) where polling slows down. When
    # start == end the feature is disabled.
    quiet_hours_start: int = Field(default=2, ge=0, le=23)
    quiet_hours_end: int = Field(default=6, ge=0, le=23)
    quiet_interval_multiplier: float = Field(default=4.0, ge=1.0)

    # Error backoff bounds (seconds).
    backoff_initial_seconds: int = 30
    backoff_max_seconds: int = 1800

    # Garmin / browser options.
    garmin_is_cn: bool = False
    headless: bool = True

    log_level: str = "INFO"

    @property
    def storage_state_path(self) -> Path:
        return self.data_dir / "session.json"

    @property
    def garmin_tokenstore(self) -> Path:
        return self.data_dir / "garmin_tokens"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def download_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def quiet_hours_enabled(self) -> bool:
        return self.quiet_hours_start != self.quiet_hours_end

    def is_quiet_hour(self, hour: int) -> bool:
        """True if ``hour`` (0-23, local) falls in the quiet window."""
        if not self.quiet_hours_enabled:
            return False
        start, end = self.quiet_hours_start, self.quiet_hours_end
        if start < end:
            return start <= hour < end
        # Window wraps past midnight (e.g. 22 -> 5).
        return hour >= start or hour < end
