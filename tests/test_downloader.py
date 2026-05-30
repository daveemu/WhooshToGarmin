"""Tests for the pure download de-duplication logic.

The Playwright/browser interaction is validated against a live account, not here.
"""

from __future__ import annotations

from whooshtogarmin.downloader import activity_identity


def test_identity_ignores_download_column_and_is_order_independent():
    row_a = {"DATE": "2026-05-30", "TITLE": "dn", "DISTANCE": "27.4 km", "DOWNLOAD": "x"}
    row_b = {"DISTANCE": "27.4 km", "TITLE": "dn", "DATE": "2026-05-30", "DOWNLOAD": "y"}
    assert activity_identity(row_a) == activity_identity(row_b)


def test_identity_differs_for_different_activities():
    a = activity_identity({"DATE": "2026-05-30", "TITLE": "morning"})
    b = activity_identity({"DATE": "2026-05-31", "TITLE": "morning"})
    assert a != b


def test_identity_skips_empty_cells():
    identity = activity_identity({"DATE": "2026-05-30", "NOTE": "", "TITLE": "dn"})
    assert "NOTE" not in identity
    assert "DATE=2026-05-30" in identity
