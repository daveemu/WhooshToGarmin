"""Persistent sync state: which myWhoosh activities we've already handled.

A tiny JSON document on the data volume. Keyed by the myWhoosh activity
identity (see :func:`whooshtogarmin.downloader.activity_identity`); each entry
records the upload outcome so a restart never re-processes the same ride.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SyncRecord:
    identity: str
    garmin_activity_id: int | None = None
    duplicate: bool = False
    uploaded_at: float = field(default_factory=time.time)


class StateStore:
    """JSON-backed store of processed activities."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records: dict[str, SyncRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (ValueError, json.JSONDecodeError):
            return
        for identity, data in raw.get("records", {}).items():
            self._records[identity] = SyncRecord(**data)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"records": {k: asdict(v) for k, v in self._records.items()}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.path)

    def known_identities(self) -> set[str]:
        return set(self._records)

    def is_known(self, identity: str) -> bool:
        return identity in self._records

    def record(
        self,
        identity: str,
        *,
        garmin_activity_id: int | None = None,
        duplicate: bool = False,
    ) -> None:
        self._records[identity] = SyncRecord(
            identity=identity,
            garmin_activity_id=garmin_activity_id,
            duplicate=duplicate,
        )
        self._save()
