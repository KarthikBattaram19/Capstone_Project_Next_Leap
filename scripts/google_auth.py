"""One-time, on the operator's machine: prints the JSON for GOOGLE_OAUTH_CREDENTIALS."""

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
]

if __name__ == "__main__":
    client_secret_file = sys.argv[
        1
    ]  # downloaded from Google Cloud Console (OAuth client, Desktop app)
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
    creds = flow.run_local_server(port=0)
    print(
        json.dumps(
            {
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "refresh_token": creds.refresh_token,
            }
        )
    )
