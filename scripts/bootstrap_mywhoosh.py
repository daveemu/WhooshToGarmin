#!/usr/bin/env python3
"""One-time interactive myWhoosh login that writes the browser session.

Opens a visible Chromium window at the myWhoosh login page. Log in by hand
(including any captcha / 2FA); once the activities page is reachable, the script
saves the storage state (cookies + the ``webToken`` JWT) to ``session.json``.
Copy that file into the service's data volume; the service then runs headlessly
until the token expires (~repeat this bootstrap when that happens).

    python scripts/bootstrap_mywhoosh.py --out ./data/session.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from whooshtogarmin.mywhoosh_auth import (
    MYWHOOSH_ACTIVITIES_URL,
    MYWHOOSH_LOGIN_URL,
    extract_token,
    token_is_valid,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="./data/session.json", help="session output path")
    parser.add_argument(
        "--timeout", type=int, default=300, help="seconds to wait for manual login"
    )
    args = parser.parse_args(argv)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(MYWHOOSH_LOGIN_URL)

        print("Log in to myWhoosh in the opened browser window...")
        try:
            # Wait until the app has navigated to an authenticated area.
            page.wait_for_url(f"{MYWHOOSH_ACTIVITIES_URL}*", timeout=args.timeout * 1000)
        except Exception:
            print(
                "Did not detect the activities page automatically; "
                "navigate to it manually, then press Enter here.",
                file=sys.stderr,
            )
            input()

        state = context.storage_state()
        if not token_is_valid(extract_token(state)):
            print("ERROR: no valid webToken captured. Are you fully logged in?", file=sys.stderr)
            browser.close()
            return 1

        out.write_text(__import__("json").dumps(state))
        out.chmod(0o600)
        browser.close()

    print(f"\n✓ Session saved to {out}")
    print("  Mount it into the container's /data volume.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
