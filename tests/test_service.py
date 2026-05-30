"""Tests for state persistence and the polling-interval logic."""

from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from whooshtogarmin.config import Settings
from whooshtogarmin.main import base_interval, jittered, next_sleep_seconds
from whooshtogarmin.state import StateStore


# -- state -----------------------------------------------------------------


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    assert store.known_identities() == set()

    store.record("act-1", garmin_activity_id=42)
    store.record("act-2", duplicate=True)

    reloaded = StateStore(path)
    assert reloaded.known_identities() == {"act-1", "act-2"}
    assert reloaded.is_known("act-1")
    assert not reloaded.is_known("act-3")


def test_state_handles_corrupt_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not valid json")
    store = StateStore(path)  # should not raise
    assert store.known_identities() == set()


# -- polling interval ------------------------------------------------------


def _settings(**kw) -> Settings:
    base = dict(
        poll_interval_seconds=900,
        quiet_hours_start=2,
        quiet_hours_end=6,
        quiet_interval_multiplier=4.0,
        jitter_fraction=0.1,
    )
    base.update(kw)
    return Settings(**base)


def test_base_interval_normal_hours():
    assert base_interval(_settings(), hour=14) == 900


def test_base_interval_quiet_hours_widened():
    assert base_interval(_settings(), hour=3) == 3600  # 900 * 4


def test_quiet_hours_disabled_when_equal():
    s = _settings(quiet_hours_start=0, quiet_hours_end=0)
    assert s.quiet_hours_enabled is False
    assert base_interval(s, hour=3) == 900


def test_quiet_hours_wrap_past_midnight():
    s = _settings(quiet_hours_start=22, quiet_hours_end=5)
    assert s.is_quiet_hour(23) is True
    assert s.is_quiet_hour(3) is True
    assert s.is_quiet_hour(12) is False


def test_jitter_stays_within_bounds():
    rng = random.Random(0)
    for _ in range(100):
        value = jittered(900, 0.1, rng)
        assert 810 <= value <= 990


def test_next_sleep_uses_quiet_window():
    rng = random.Random(0)
    now = datetime(2026, 5, 30, 3, 0, tzinfo=ZoneInfo("Europe/Vienna"))
    sleep = next_sleep_seconds(_settings(), now=now, rng=rng)
    # base 3600 +/- 10%
    assert 3240 <= sleep <= 3960
