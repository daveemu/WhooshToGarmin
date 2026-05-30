"""Tests for the FIT converter."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fitparse import FitFile as ParseFit

from whooshtogarmin.converter import FIT_EPOCH_OFFSET, convert_fit


def _read(path, message_name, field_name):
    msg = next(ParseFit(str(path)).get_messages(message_name))
    return msg.get_value(field_name)


def test_local_timestamp_normalised_to_local_time(mywhoosh_fit):
    src = mywhoosh_fit()
    res = convert_fit(src, tz_name="Europe/Vienna")

    assert res.local_timestamp_fixed is True

    utc = _read(res.output_path, "activity", "timestamp")
    local = _read(res.output_path, "activity", "local_timestamp")
    # Vienna is UTC+2 in summer, so local wall-clock is two hours ahead of UTC.
    assert (local - utc).total_seconds() == 2 * 3600
    assert utc == datetime(2026, 5, 30, 19, 15, 54)
    assert local == datetime(2026, 5, 30, 21, 15, 54)


def test_local_timestamp_respects_timezone(mywhoosh_fit):
    src = mywhoosh_fit()
    res = convert_fit(src, tz_name="UTC")
    utc = _read(res.output_path, "activity", "timestamp")
    local = _read(res.output_path, "activity", "local_timestamp")
    assert utc == local


def test_already_correct_local_timestamp_is_left_alone(mywhoosh_fit):
    # Pre-compute the correct raw value so the converter has nothing to do.
    tz = ZoneInfo("Europe/Vienna")
    unix_seconds = 1780168554
    offset = int(datetime.fromtimestamp(unix_seconds, tz).utcoffset().total_seconds())
    correct_raw = unix_seconds + offset - FIT_EPOCH_OFFSET

    src = mywhoosh_fit(bad_local_timestamp=correct_raw)
    res = convert_fit(src, tz_name="Europe/Vienna")
    assert res.local_timestamp_fixed is False


def test_temperature_is_stripped_when_present(mywhoosh_fit):
    src = mywhoosh_fit(include_temperature=True)
    res = convert_fit(src)
    assert res.temperature_fields_removed == 10
    assert _read(res.output_path, "record", "temperature") is None


def test_temperature_untouched_when_absent(mywhoosh_fit):
    src = mywhoosh_fit(include_temperature=False)
    res = convert_fit(src)
    assert res.temperature_fields_removed == 0


def test_missing_session_averages_are_filled(mywhoosh_fit):
    src = mywhoosh_fit(include_session_averages=False)
    res = convert_fit(src)
    assert "session.avg_power" in res.averages_filled
    assert "session.avg_heart_rate" in res.averages_filled
    # records carry power 100..109 -> mean 104.5 -> rounded 104
    assert _read(res.output_path, "session", "avg_power") == 104


def test_present_session_averages_are_preserved(mywhoosh_fit):
    src = mywhoosh_fit(include_session_averages=True)
    res = convert_fit(src)
    assert res.averages_filled == []
    assert _read(res.output_path, "session", "avg_power") == 105


def test_manufacturer_is_not_spoofed(mywhoosh_fit):
    src = mywhoosh_fit()
    res = convert_fit(src)
    # Honest cleaning: stays MyWhoosh (331), not faked as Garmin (1).
    assert _read(res.output_path, "file_id", "manufacturer") == 331


def test_default_output_path(mywhoosh_fit):
    src = mywhoosh_fit()
    res = convert_fit(src)
    assert res.output_path.name == "in.garmin.fit"
    assert res.output_path.exists()
