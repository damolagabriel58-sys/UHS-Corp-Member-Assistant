
"""One-time migration of Gmail credentials into encrypted PostgreSQL storage."""

import json

from google.oauth2.credentials import Credentials

from gmail_service import (
    TOKEN_FILE,
    SCOPES,
    DIRECTOR_EMAIL,
    get_connected_gmail_address,
)
from gmail_token_store import save_gmail_token, load_gmail_token
from googleapiclient.discovery import build


def main():
    if not DIRECTOR_EMAIL:
        raise RuntimeError("DIRECTOR_EMAIL is not configured.")

    if not TOKEN_FILE.is_file():
        raise FileNotFoundError(
            "backend/token.json was not found."
        )

    # Read the existing local authorization.
    token_json = TOKEN_FILE.read_text(encoding="utf-8")

    credentials = Credentials.from_authorized_user_info(
        json.loads(token_json),
        SCOPES,
    )

    if not credentials.has_scopes(SCOPES):
        raise RuntimeError(
            "The Gmail token is missing required permissions."
        )

    # Verify the account independently using the local token.
    service = build(
        "gmail",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )

    connected_email = get_connected_gmail_address(service)

    if connected_email != DIRECTOR_EMAIL:
        raise PermissionError(
            "The Gmail token belongs to a different account."
        )

    # Save the token encrypted in the current PostgreSQL database.
    save_gmail_token(
        email=DIRECTOR_EMAIL,
        token_json=credentials.to_json(),
    )

    # Verify that the stored credentials can be decrypted.
    restored = load_gmail_token(DIRECTOR_EMAIL)

    if restored is None:
        raise RuntimeError(
            "Gmail credentials could not be retrieved."
        )

    print("Gmail authorization migrated successfully.")


if __name__ == "__main__":
    main()
