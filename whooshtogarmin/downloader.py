"""Download new activity FIT files from myWhoosh via a headless browser.

myWhoosh has no documented JSON API for listing activities or downloading FIT
files; the activities table is rendered client-side and the download button
triggers a backend call (``download-activity-file``) that returns a short-lived
S3 presigned URL. We therefore drive a headless Chromium (Playwright) using a
saved ``storage_state`` (cookies + the ``webToken`` JWT) and intercept that
presigned URL, mirroring the approach proven by ``technic0/mywhoosh_downloader``.

The session is created once interactively (see ``scripts/bootstrap_login.py``
counterpart for myWhoosh) and reused headlessly thereafter. Token expiry is
checked locally before launching a browser, so an expired session fails fast
without a network round-trip.

NOTE: The DOM selectors and the precise download-response shape can only be
validated against a live myWhoosh account. They are kept defensive (multiple
fallbacks) and centralised here so they are easy to adjust.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from whooshtogarmin.mywhoosh_auth import (
    DOWNLOAD_RESPONSE_GLOB,
    MYWHOOSH_ACTIVITIES_URL,
    extract_token,
    is_trusted_download_url,
    token_is_valid,
)

logger = logging.getLogger(__name__)

# JS run in the page to read the activities table as a list of column->text dicts.
# Download-button cells are stripped so the identity is stable across polls.
_JS_LIST_ACTIVITIES = """
() => {
  const tables = Array.from(document.querySelectorAll('table'));
  const table = tables.find(t => {
    const h = t.textContent.toUpperCase();
    return h.includes('DATE') && h.includes('DOWNLOAD');
  });
  if (!table) return { headers: [], activities: [] };
  const headers = Array.from(table.querySelectorAll('thead th, thead td'))
    .map(c => c.textContent.trim());
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const activities = rows.map(tr => {
    const cells = Array.from(tr.children).map(td => {
      const clone = td.cloneNode(true);
      clone.querySelectorAll('button, svg, img, a').forEach(e => e.remove());
      return clone.textContent.trim();
    });
    const row = {};
    cells.forEach((v, i) => { row[headers[i] || ('col' + i)] = v; });
    return row;
  });
  return { headers, activities };
}
"""


@dataclass
class MyWhooshActivity:
    """A row from the myWhoosh activities table."""

    identity: str
    fields: dict[str, str] = field(default_factory=dict)
    row_index: int = 0


def activity_identity(row: dict[str, str]) -> str:
    """Build a stable identity from a table row, ignoring the download column.

    myWhoosh exposes no activity id in the DOM, so we hash the visible
    descriptive cells (date, title, distance, ...). This is only a *download*
    de-duplication hint; Garmin's own 409 duplicate detection is the backstop
    against ever creating a duplicate activity.
    """
    parts = [
        f"{key}={value}"
        for key, value in sorted(row.items())
        if value and "download" not in key.lower()
    ]
    return "|".join(parts)


class MyWhooshDownloader:
    """Headless myWhoosh activity downloader."""

    def __init__(
        self,
        storage_state_path: str | Path,
        download_dir: str | Path,
        *,
        headless: bool = True,
        page_timeout_ms: int = 30000,
    ) -> None:
        self.storage_state_path = Path(storage_state_path)
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.page_timeout_ms = page_timeout_ms

    # -- session -----------------------------------------------------------

    def _load_storage_state(self) -> dict:
        return json.loads(self.storage_state_path.read_text())

    def session_valid(self) -> bool:
        """Local-only check: do we hold a still-valid myWhoosh token?"""
        if not self.storage_state_path.exists():
            return False
        try:
            token = extract_token(self._load_storage_state())
        except (ValueError, json.JSONDecodeError):
            return False
        return token_is_valid(token)

    # -- browser-driven steps ---------------------------------------------

    def list_activities(self, page) -> list[MyWhooshActivity]:
        """Navigate to the activities page and read the rendered table."""
        page.goto(MYWHOOSH_ACTIVITIES_URL, wait_until="networkidle")
        data = page.evaluate(_JS_LIST_ACTIVITIES)
        activities = []
        for index, row in enumerate(data.get("activities", [])):
            activities.append(
                MyWhooshActivity(
                    identity=activity_identity(row), fields=row, row_index=index
                )
            )
        logger.info("myWhoosh lists %d activities", len(activities))
        return activities

    def _resolve_download_url(self, page, activity: MyWhooshActivity) -> str:
        """Click the row's download control and capture the presigned URL."""
        rows = page.locator("table tbody tr")
        row = rows.nth(activity.row_index)
        download_control = row.locator(
            '[aria-label*="download" i], [title*="download" i], button'
        ).first
        with page.expect_response(DOWNLOAD_RESPONSE_GLOB, timeout=self.page_timeout_ms) as info:
            download_control.click()
        payload = info.value.json()
        url = payload.get("data") if isinstance(payload, dict) else None
        if not is_trusted_download_url(url):
            raise ValueError(f"Refusing untrusted download URL: {url!r}")
        return url

    def _download_file(self, url: str, activity: MyWhooshActivity) -> Path:
        safe = "".join(c if c.isalnum() else "_" for c in activity.identity)[:80]
        dest = self.download_dir / f"{int(time.time())}_{safe or 'activity'}.fit"
        with httpx.stream("GET", url, timeout=self.page_timeout_ms / 1000) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        logger.info("Downloaded %s -> %s", activity.identity, dest)
        return dest

    # -- orchestration -----------------------------------------------------

    def fetch_new(self, known_identities: set[str]) -> list[tuple[MyWhooshActivity, Path]]:
        """Return ``(activity, fit_path)`` for activities not seen before.

        Raises ``RuntimeError`` if the session is expired (re-run the myWhoosh
        login bootstrap).
        """
        if not self.session_valid():
            raise RuntimeError(
                "myWhoosh session missing or expired; re-run the login bootstrap."
            )

        # Imported lazily so the pure helpers/tests don't require Playwright.
        from playwright.sync_api import sync_playwright

        downloaded: list[tuple[MyWhooshActivity, Path]] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless, args=["--no-sandbox"]
            )
            context = browser.new_context(storage_state=str(self.storage_state_path))
            page = context.new_page()
            page.set_default_timeout(self.page_timeout_ms)
            try:
                for activity in self.list_activities(page):
                    if activity.identity in known_identities:
                        continue
                    url = self._resolve_download_url(page, activity)
                    path = self._download_file(url, activity)
                    downloaded.append((activity, path))
            finally:
                context.close()
                browser.close()
        return downloaded
