"""Pure helpers for myWhoosh session handling and download-URL validation.

These contain no browser/network I/O so they can be unit-tested directly. The
Playwright-driven parts live in :mod:`whooshtogarmin.downloader`.
"""

from __future__ import annotations

import base64
import json
import math
import time
from urllib.parse import urlparse

# myWhoosh web app endpoints (the activities list is rendered client-side here).
MYWHOOSH_LOGIN_URL = "https://event.mywhoosh.com/auth/login"
MYWHOOSH_ACTIVITIES_URL = "https://event.mywhoosh.com/user/activities"

# Playwright route glob for the backend call that returns the presigned FIT URL.
DOWNLOAD_RESPONSE_GLOB = "**/download-activity-file**"

# The JWT lives in localStorage under this key.
JWT_LOCALSTORAGE_KEY = "webToken"

# Presigned download URLs must resolve to one of these hosts.
TRUSTED_DOWNLOAD_SUFFIXES = (".amazonaws.com", ".cloudfront.net", ".mywhoosh.com")


def _b64url_decode(segment: str) -> bytes:
    """Decode a Base64URL segment, restoring missing padding (RFC 4648 §5)."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_jwt_exp(token: str) -> float | None:
    """Return the JWT ``exp`` claim (epoch seconds), or ``None`` if unreadable."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(_b64url_decode(parts[1]))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    if not math.isfinite(exp):
        return None
    return float(exp)


def token_is_valid(token: str | None, *, leeway_seconds: int = 60, now: float | None = None) -> bool:
    """True if ``token`` has a valid ``exp`` more than ``leeway_seconds`` away."""
    if not token:
        return False
    exp = decode_jwt_exp(token)
    if exp is None:
        return False
    current = time.time() if now is None else now
    return exp - current > leeway_seconds


def extract_token(storage_state: dict) -> str | None:
    """Pull the ``webToken`` JWT out of a Playwright ``storage_state`` dict."""
    for origin in storage_state.get("origins", []):
        for item in origin.get("localStorage", []):
            if item.get("name") == JWT_LOCALSTORAGE_KEY:
                return item.get("value")
    return None


def session_is_valid(storage_state: dict, *, now: float | None = None) -> bool:
    """True if the stored session carries a still-valid myWhoosh token."""
    return token_is_valid(extract_token(storage_state), now=now)


def is_trusted_download_url(url: str | None) -> bool:
    """Validate a presigned download URL: HTTPS + a trusted host suffix."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(
        host == suffix.lstrip(".") or host.endswith(suffix)
        for suffix in TRUSTED_DOWNLOAD_SUFFIXES
    )
