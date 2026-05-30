"""Convert a myWhoosh ``.fit`` file into one that Garmin Connect accepts cleanly.

Design notes (verified against a real, current myWhoosh export):

* Current myWhoosh files already identify themselves honestly as manufacturer
  ``331`` ("MyWhoosh Technology Services LLC", a registered FIT manufacturer)
  and already include avg power / heart rate / cadence and *no* temperature
  field. So we deliberately do **not** spoof the device as Garmin.

* The one real defect in current files is ``activity.local_timestamp``: it is
  garbage (off by ~20 years and an odd offset). Garmin uses this field to place
  the activity in the athlete's local time, so we normalise it to
  ``timestamp + UTC offset`` for a configured timezone.

* The average / temperature handling below is *defensive*: it only acts when a
  value is missing or a field is present, so it also repairs older-format files
  without touching already-correct ones.

Implementation detail: ``fit_tool`` cannot inject a scalar field that was absent
from a parsed message (the field exists with size 0 and is "not growable"). To
add missing averages we therefore rebuild the affected message as a fresh
object, copying every present field and developer field across. The output is
written with ``auto_define=True`` so definition messages are regenerated to
match the (possibly modified) data messages.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fit_tool.fit_file import FitFile
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.record import DataMessage
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage

# Seconds between the Unix epoch (1970-01-01) and the FIT epoch (1989-12-31).
FIT_EPOCH_OFFSET = 631065600

# FIT field number for RecordMessage.temperature.
TEMPERATURE_FIELD_ID = 13

DEFAULT_TIMEZONE = "Europe/Vienna"

# (average field, source record field) pairs we can backfill.
_AVERAGE_SPECS = (
    ("avg_power", "power"),
    ("avg_heart_rate", "heart_rate"),
    ("avg_cadence", "cadence"),
)


@dataclass
class ConversionResult:
    """Summary of what the converter changed, for logging and tests."""

    input_path: Path
    output_path: Path
    local_timestamp_fixed: bool = False
    temperature_fields_removed: int = 0
    averages_filled: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (
            self.local_timestamp_fixed
            or self.temperature_fields_removed > 0
            or bool(self.averages_filled)
        )


def _utc_offset_seconds(unix_seconds: float, tz: ZoneInfo) -> int:
    """UTC offset (incl. DST) for ``tz`` at the given instant, in seconds."""
    offset = datetime.fromtimestamp(unix_seconds, tz).utcoffset()
    return int(offset.total_seconds()) if offset else 0


def _fix_local_timestamp(message: ActivityMessage, tz: ZoneInfo) -> bool:
    """Normalise ``local_timestamp`` to ``timestamp`` + local UTC offset.

    ``fit_tool`` exposes ``timestamp`` as Unix milliseconds but ``local_timestamp``
    as the raw FIT value (seconds since the FIT epoch). We compute the correct raw
    value so a reader interprets it as the athlete's local wall-clock time.
    """
    if message.timestamp is None:
        return False
    unix_seconds = message.timestamp // 1000
    offset = _utc_offset_seconds(unix_seconds, tz)
    desired_raw = unix_seconds + offset - FIT_EPOCH_OFFSET
    if message.local_timestamp == desired_raw:
        return False
    message.local_timestamp = desired_raw
    return True


def _strip_temperature(message: RecordMessage) -> bool:
    """Remove the (bogus) temperature field from a record if present."""
    if getattr(message, "temperature", None) is None:
        return False
    message.remove_field(TEMPERATURE_FIELD_ID)
    return True


def _missing_averages(
    message: SessionMessage | LapMessage,
    records: list[RecordMessage],
) -> dict[str, int]:
    """Compute averages for fields that are absent on ``message``."""
    computed: dict[str, int] = {}
    for avg_attr, record_attr in _AVERAGE_SPECS:
        if getattr(message, avg_attr, None) is not None:
            continue
        values = [
            v for r in records if (v := getattr(r, record_attr, None)) is not None
        ]
        if values:
            computed[avg_attr] = round(statistics.fmean(values))
    return computed


def _clone_with_averages(
    message: SessionMessage | LapMessage,
    averages: dict[str, int],
) -> SessionMessage | LapMessage:
    """Return a fresh copy of ``message`` with the given averages added.

    A fresh message instance accepts new scalar fields, unlike a parsed one.
    All present standard fields and developer fields are carried across.
    """
    clone = type(message)()
    for fit_field in message.fields:
        value = fit_field.get_value()
        if fit_field.size == 0 or value is None:
            continue
        setattr(clone, fit_field.name, value)
    for developer_field in getattr(message, "developer_fields", []):
        clone.developer_fields.append(developer_field)
    for name, value in averages.items():
        setattr(clone, name, value)
    return clone


def _records_in_lap(
    records: list[RecordMessage], lap: LapMessage
) -> list[RecordMessage]:
    """Records whose timestamp falls inside the lap's time window."""
    if lap.start_time is None or lap.timestamp is None:
        return []
    return [
        r
        for r in records
        if r.timestamp is not None and lap.start_time <= r.timestamp <= lap.timestamp
    ]


def convert_fit(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    tz_name: str = DEFAULT_TIMEZONE,
) -> ConversionResult:
    """Read a myWhoosh FIT file, apply Garmin-friendly fixes, write the result.

    Args:
        input_path: Source ``.fit`` file from myWhoosh.
        output_path: Destination. Defaults to ``<input>.garmin.fit``.
        tz_name: IANA timezone used to compute the local timestamp offset.

    Returns:
        A :class:`ConversionResult` describing the changes made.
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path.with_suffix(".garmin.fit")
    output_path = Path(output_path)
    tz = ZoneInfo(tz_name)

    fit = FitFile.from_file(str(input_path))
    result = ConversionResult(input_path=input_path, output_path=output_path)

    records = [r.message for r in fit.records if isinstance(r.message, RecordMessage)]

    builder = FitFileBuilder(auto_define=True)
    for record in fit.records:
        message = record.message
        # Definition messages are regenerated by the builder; skip the originals.
        if not isinstance(message, DataMessage):
            continue

        if isinstance(message, ActivityMessage):
            if _fix_local_timestamp(message, tz):
                result.local_timestamp_fixed = True
        elif isinstance(message, RecordMessage):
            if _strip_temperature(message):
                result.temperature_fields_removed += 1
        elif isinstance(message, SessionMessage):
            averages = _missing_averages(message, records)
            if averages:
                message = _clone_with_averages(message, averages)
                result.averages_filled += [f"session.{a}" for a in averages]
        elif isinstance(message, LapMessage):
            averages = _missing_averages(message, _records_in_lap(records, message))
            if averages:
                message = _clone_with_averages(message, averages)
                result.averages_filled += [f"lap.{a}" for a in averages]

        builder.add(message)

    builder.build().to_file(str(output_path))
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m whooshtogarmin.converter input.fit [-o out.fit]``."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean a myWhoosh FIT file for Garmin Connect upload."
    )
    parser.add_argument("input", help="myWhoosh .fit file")
    parser.add_argument("-o", "--output", help="output path (default <input>.garmin.fit)")
    parser.add_argument(
        "--tz", default=DEFAULT_TIMEZONE, help=f"timezone (default {DEFAULT_TIMEZONE})"
    )
    args = parser.parse_args(argv)

    result = convert_fit(args.input, args.output, tz_name=args.tz)
    print(f"wrote {result.output_path}")
    print(f"  local_timestamp fixed:  {result.local_timestamp_fixed}")
    print(f"  temperature removed:    {result.temperature_fields_removed}")
    print(f"  averages filled:        {result.averages_filled or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
