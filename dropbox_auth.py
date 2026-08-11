#!/usr/bin/env python3
"""One-time Dropbox authorization helper.

Run this once to turn an authorization code (that Leslie gets by clicking the
consent link) into a long-lived refresh token to paste into .env.

Usage:
    1. Put DROPBOX_APP_KEY and DROPBOX_APP_SECRET in .env (from the Dropbox App Console).
    2. Get the consent link printed by this script; send it to Leslie.
    3. She approves and sends back the short code.
    4. Run:  python dropbox_auth.py <code>
    5. Paste the printed DROPBOX_REFRESH_TOKEN into .env.

Note: authorization codes expire within minutes — do the exchange promptly.
"""

from __future__ import annotations

import sys

from src.config import load_secrets
from src.dropbox_client import exchange_code_for_refresh_token


def main(argv: list[str]) -> int:
    secrets = load_secrets()
    app_key = secrets.dropbox_app_key
    app_secret = secrets.dropbox_app_secret
    if not app_key or not app_secret:
        print("Set DROPBOX_APP_KEY and DROPBOX_APP_SECRET in .env first.", file=sys.stderr)
        return 2

    if len(argv) < 2:
        url = (f"https://www.dropbox.com/oauth2/authorize?client_id={app_key}"
               f"&response_type=code&token_access_type=offline")
        print("1) Send this consent link to the account owner:\n")
        print("   " + url + "\n")
        print("2) They click Allow and copy the code Dropbox shows them.")
        print("3) Run:  python dropbox_auth.py <code>")
        return 0

    code = argv[1].strip()
    data = exchange_code_for_refresh_token(app_key, app_secret, code)
    token = data.get("refresh_token")
    if not token:
        print(f"No refresh_token in response: {data}", file=sys.stderr)
        return 1
    print("\nSuccess! Add this line to your .env:\n")
    print(f"DROPBOX_REFRESH_TOKEN={token}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
