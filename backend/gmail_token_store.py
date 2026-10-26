
"""Encrypted Gmail OAuth credential storage."""

import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from sqlalchemy import select

from database import SessionLocal
from models import GmailCredential

load_dotenv(Path(__file__).resolve().parent / ".env")


def get_cipher():
    key = os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY")

    if not key:
        raise RuntimeError(
            "GMAIL_TOKEN_ENCRYPTION_KEY is missing."
        )

    return Fernet(key.encode("utf-8"))


def save_gmail_token(email: str, token_json: str):
    """Encrypt and save Gmail credentials in PostgreSQL."""

    email = email.strip().lower()

    if not email or not token_json:
        raise ValueError("Email and token are required.")

    encrypted = get_cipher().encrypt(
        token_json.encode("utf-8")
    ).decode("utf-8")

    with SessionLocal() as db:
        record = db.execute(
            select(GmailCredential)
            .where(GmailCredential.email == email)
            .with_for_update()
        ).scalar_one_or_none()

        if record is None:
            record = GmailCredential(
                email=email,
                encrypted_token=encrypted,
            )
            db.add(record)
        else:
            record.encrypted_token = encrypted
            record.updated_at = datetime.now(timezone.utc)

        db.commit()


def load_gmail_token(email: str) -> str | None:
    """Decrypt Gmail credentials for the configured account."""

    email = email.strip().lower()

    with SessionLocal() as db:
        record = db.execute(
            select(GmailCredential).where(
                GmailCredential.email == email
            )
        ).scalar_one_or_none()

        if record is None:
            return None

        return get_cipher().decrypt(
            record.encrypted_token.encode("utf-8")
        ).decode("utf-8")
