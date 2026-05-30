#!/usr/bin/env python3
"""One-time interactive login that writes the Garmin OAuth token store.

Run this once on a machine where you can type your password and MFA code. It
authenticates against Garmin Connect and saves refreshable OAuth tokens to the
token store directory. Copy that directory into the service's data volume; the
service then runs fully headless and never needs your password again.

    python scripts/bootstrap_login.py --tokenstore ./data/garmin_tokens

Tokens are valid ~1 year and are auto-refreshed by the service.
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from garminconnect import Garmin


def prompt_mfa() -> str:
    return input("Garmin MFA / 2FA code: ").strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tokenstore",
        default="./data/garmin_tokens",
        help="directory to write the Garmin OAuth token store",
    )
    parser.add_argument("--is-cn", action="store_true", help="use the Garmin China domain")
    args = parser.parse_args(argv)

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    tokenstore = str(Path(args.tokenstore).expanduser())
    client = Garmin(email=email, password=password, is_cn=args.is_cn, prompt_mfa=prompt_mfa)
    client.login(tokenstore=tokenstore)

    print(f"\n✓ Logged in as {client.display_name or email}")
    print(f"✓ Tokens written to {tokenstore}")
    print("  Mount this directory into the container as the token store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
