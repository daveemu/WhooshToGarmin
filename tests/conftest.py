"""Shared test fixtures.

We synthesize FIT files in-memory rather than committing real myWhoosh exports,
which contain personal data (GPS track, heart rate, etc.).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import FileType

# 2026-05-30 19:15:54 UTC, expressed in Unix milliseconds (how fit_tool stores it).
START_MS = 1780168554000
# Manufacturer 331 == "MyWhoosh Technology Services LLC" in the FIT profile.
MYWHOOSH_MANUFACTURER = 331


def _make_fit(
    path: Path,
    *,
    bad_local_timestamp: int | None,
    include_temperature: bool,
    include_session_averages: bool,
) -> Path:
    """Build a small myWhoosh-like FIT file with configurable defects."""
    file_id = FileIdMessage()
    file_id.type = FileType.ACTIVITY
    file_id.manufacturer = MYWHOOSH_MANUFACTURER
    file_id.time_created = START_MS

    records = []
    for i in range(10):
        rec = RecordMessage()
        rec.timestamp = START_MS + i * 1000
        rec.power = 100 + i
        rec.heart_rate = 120 + i
        rec.cadence = 85 + (i % 3)
        if include_temperature:
            rec.temperature = 40 + i  # bogus values myWhoosh used to emit
        records.append(rec)

    session = SessionMessage()
    session.timestamp = START_MS
    session.start_time = START_MS
    if include_session_averages:
        session.avg_power = 105
        session.avg_heart_rate = 124
        session.avg_cadence = 86

    activity = ActivityMessage()
    activity.timestamp = START_MS
    if bad_local_timestamp is not None:
        activity.local_timestamp = bad_local_timestamp

    builder = FitFileBuilder(auto_define=True)
    builder.add(file_id)
    for rec in records:
        builder.add(rec)
    builder.add(session)
    builder.add(activity)
    builder.build().to_file(str(path))
    return path


@pytest.fixture
def mywhoosh_fit(tmp_path: Path):
    """Factory for synthetic myWhoosh FIT files with configurable defects."""

    def _factory(
        *,
        bad_local_timestamp: int | None = 1780173921,  # the ~20y-off garbage value
        include_temperature: bool = False,
        include_session_averages: bool = True,
    ) -> Path:
        return _make_fit(
            tmp_path / "in.fit",
            bad_local_timestamp=bad_local_timestamp,
            include_temperature=include_temperature,
            include_session_averages=include_session_averages,
        )

    return _factory
