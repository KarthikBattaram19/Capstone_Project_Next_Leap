"""One-time, on the operator's machine: runs Google's installed-app OAuth flow.

Default - the service token. Prints the JSON for GOOGLE_OAUTH_CREDENTIALS, with the
Calendar + Gmail-send scopes the backend runs on:

    python scripts/google_auth.py <client_secret.json>

--gmail-readonly - the reader token for Task 4.1's L8 (PDF delivery timed to inbox arrival),
passed to scripts/timed_interactions.py --gmail-reader-credentials. Sign in as the INBOX that
receives the confirmations, not necessarily the sender. It is a separate grant on purpose:
the service token stays send-only because the backend never needs to read anyone's mail.

    python scripts/google_auth.py <client_secret.json> --gmail-readonly --out data/raw/gmail_reader.json

--out writes the file itself, UTF-8 with no byte-order mark. Redirecting stdout from Windows
PowerShell (`>`) adds a BOM, and timed_interactions reads the file as plain UTF-8, so the
JSON would fail to parse mid-run. The file holds a client secret and a refresh token: keep it
under data/raw/, which is gitignored, and never commit it.
"""

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
]
READER_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

USAGE = "usage: python scripts/google_auth.py <client_secret.json> [--gmail-readonly] [--out PATH]"


def main(argv: list[str]) -> int:
    args = list(argv)
    reader = "--gmail-readonly" in args
    if reader:
        args.remove("--gmail-readonly")
    out = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print(USAGE, file=sys.stderr)
            return 2
        out = Path(args[i + 1])
        del args[i : i + 2]
    if len(args) != 1:
        print(USAGE, file=sys.stderr)
        return 2

    # Downloaded from Google Cloud Console: APIs & Services -> Credentials -> the OAuth client
    # of type "Desktop app" -> Download JSON.
    client_secret_file = args[0]
    flow = InstalledAppFlow.from_client_secrets_file(
        client_secret_file, READER_SCOPES if reader else SCOPES
    )
    creds = flow.run_local_server(port=0)
    body = json.dumps(
        {
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "refresh_token": creds.refresh_token,
        }
    )
    if out is None:
        print(body)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")  # no BOM - see the module docstring
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
