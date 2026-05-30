"""Upload cleaned FIT files to Garmin Connect.

Uses ``garminconnect`` (the maintained successor to the now-deprecated ``garth``;
Garmin changed their SSO flow in March 2026 and ``garth``'s mobile auth no longer
works for fresh logins).

Authentication is token-based: a one-time interactive bootstrap (see
``scripts/bootstrap_login.py``) logs in with credentials + MFA and writes an
OAuth token store. The service then runs fully headless, loading and
auto-refreshing those tokens — no password is needed at runtime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

logger = logging.getLogger(__name__)

# Garmin's upload endpoint returns 409 when the activity already exists, and
# embeds messageCode 202 ("Duplicate Activity") in the import result failures.
# The native client surfaces 409 as a GarminConnectConnectionError whose message
# starts with "API Error 409", so we match on the status code in the text.
HTTP_CONFLICT = "409"
DUPLICATE_MESSAGE_CODE = 202


@dataclass
class UploadResult:
    """Outcome of a single upload attempt."""

    uploaded: bool
    duplicate: bool
    activity_id: int | None = None
    detail: str = ""


def parse_upload_response(response: Any) -> UploadResult:
    """Interpret Garmin's upload response payload.

    Garmin replies with a ``detailedImportResult`` containing ``successes`` and
    ``failures``. A new activity yields a success with an ``internalId``; a
    re-upload of an existing activity yields a failure carrying message code 202.
    """
    result = response.get("detailedImportResult", {}) if isinstance(response, dict) else {}
    successes = result.get("successes") or []
    failures = result.get("failures") or []

    if successes:
        activity_id = successes[0].get("internalId")
        return UploadResult(
            uploaded=True, duplicate=False, activity_id=activity_id, detail="uploaded"
        )

    for failure in failures:
        for message in failure.get("messages", []):
            if message.get("code") == DUPLICATE_MESSAGE_CODE:
                return UploadResult(
                    uploaded=False,
                    duplicate=True,
                    activity_id=failure.get("internalId"),
                    detail="duplicate activity",
                )

    return UploadResult(uploaded=False, duplicate=False, detail=str(response))


class GarminUploader:
    """Lazily-authenticated Garmin Connect upload client."""

    def __init__(self, tokenstore: str | Path, *, is_cn: bool = False) -> None:
        self._tokenstore = str(tokenstore)
        self._is_cn = is_cn
        self._client: Garmin | None = None

    def _client_or_login(self) -> Garmin:
        if self._client is not None:
            return self._client
        client = Garmin(is_cn=self._is_cn)
        try:
            # Token-only login: loads the stored OAuth tokens and refreshes them
            # if needed. Raises if no valid tokens exist (re-run the bootstrap).
            client.login(tokenstore=self._tokenstore)
        except (GarminConnectAuthenticationError, FileNotFoundError) as exc:
            raise GarminConnectAuthenticationError(
                f"No valid Garmin tokens in {self._tokenstore!r}. "
                "Run scripts/bootstrap_login.py once to authenticate."
            ) from exc
        self._client = client
        return client

    def upload(self, fit_path: str | Path) -> UploadResult:
        """Upload a FIT file, treating an existing activity as success."""
        client = self._client_or_login()
        try:
            response = client.upload_activity(str(fit_path))
        except GarminConnectConnectionError as exc:
            if f"API Error {HTTP_CONFLICT}" in str(exc):
                logger.info("Garmin reports %s as a duplicate (409)", fit_path)
                return UploadResult(
                    uploaded=False, duplicate=True, detail="duplicate (409)"
                )
            raise
        return parse_upload_response(response)
