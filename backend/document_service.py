"""Import and classify Gmail PDFs, storing originals in private Supabase Storage.

The Document.original_file_path column stores a Supabase object key, NOT a local
filesystem path. Update PDF preview/signing routes before enabling this importer.
"""

import hashlib
import logging
import uuid
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from models import CorpsMember, Document
from gmail_service import (
    list_recent_emails,
    list_pdf_attachments,
    download_pdf_attachment,
)
from document_classifier import classify_document
from storage_service import ORIGINAL_BUCKET, upload_file, delete_file

logger = logging.getLogger(__name__)


def _object_key(message_id: str, attachment_id: str) -> str:
    """Use a fresh, non-guessable key for each attempted import."""
    digest = hashlib.sha256(
        f"{message_id}:{attachment_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"gmail/{digest}/{uuid.uuid4().hex}.pdf"


def _cleanup_unreferenced_upload(object_key: str) -> None:
    """Delete only an object not referenced by any committed Document.

    If the database cannot be checked, retain the object for later cleanup
    rather than risk deleting a successfully committed document.
    """
    try:
        with SessionLocal() as check_db:
            referenced = (
                check_db.query(Document.id)
                .filter(Document.original_file_path == object_key)
                .first()
            )
        if referenced:
            logger.warning("Keeping uploaded PDF referenced by database: %s", object_key)
            return
    except Exception:
        logger.exception("Cannot verify upload references; retaining object %s", object_key)
        return

    try:
        delete_file(ORIGINAL_BUCKET, object_key)
    except Exception:
        logger.exception("Could not remove orphaned Supabase PDF %s", object_key)


def _email_year(email: dict) -> int:
    """Year is inferred from receipt date because filenames have no year.

    Prefer date from Gmail message metadata. If missing/unparseable, import year
    is used (logged); in future use Gmail internalDate for stronger provenance.
    """
    raw_date = email.get("date", "")
    if raw_date:
        try:
            return parsedate_to_datetime(raw_date).year
        except (TypeError, ValueError, OverflowError):
            logger.warning("Invalid Gmail Date header for %s: %r", email.get("id"), raw_date)
    logger.warning("No trustworthy message date for %s; using import year", email.get("id"))
    return datetime.now(timezone.utc).year


def process_recent_documents(max_results=100):
    """Import recognized Gmail PDFs into PostgreSQL and private Supabase Storage.

    This function does NOT approve, sign, or send any document.
    """
    saved_count = duplicate_count = rejected_count = failed_count = 0

    # Fetch outside the DB transaction. Each attachment gets its own session,
    # preventing one bad message from poisoning subsequent imports.
    emails = list_recent_emails(
        max_results=max_results,
        query="has:attachment filename:pdf",
    )

    for email in emails:
        message_id = email["id"]
        submission_year = _email_year(email)
        sender_email = parseaddr(email.get("sender", ""))[1].strip().lower()

        try:
            attachments = list_pdf_attachments(message_id)
        except Exception:
            failed_count += 1
            logger.exception("Unable to inspect Gmail message %s", message_id)
            continue

        for attachment in attachments:
            filename = attachment.get("filename", "")
            real_attachment_id = attachment.get("attachment_id")
            inline_data = attachment.get("inline_data")
            attachment_id = real_attachment_id

            if not attachment_id and inline_data:
                attachment_id = "inline_" + hashlib.sha256(
                    f"{message_id}:{filename}:{inline_data}".encode("utf-8")
                ).hexdigest()

            if not attachment_id:
                rejected_count += 1
                logger.warning("Attachment has no downloadable data: %s", filename)
                continue

            details = classify_document(filename)
            if not details.get("recognized"):
                rejected_count += 1
                logger.info("Invalid document filename: %s", filename)
                continue

            if not sender_email:
                rejected_count += 1
                logger.warning("Sender email unavailable: %s", filename)
                continue

            document_type = details["document_type"]
            month = details["month"]
            year = int(details.get("year") or submission_year)
            state_code = details["state_code"]
            uploaded_key = None

            with SessionLocal() as db:
                try:
                    if db.query(Document.id).filter_by(
                        gmail_message_id=message_id,
                        attachment_id=attachment_id,
                    ).first():
                        duplicate_count += 1
                        continue

                    member = db.query(CorpsMember).filter_by(
                        state_code=state_code
                    ).first()

                    if member is not None and db.query(Document.id).filter_by(
                        corps_member_id=member.id,
                        month=month,
                        year=year,
                        document_type=document_type,
                    ).first():
                        duplicate_count += 1
                        logger.info("Duplicate business document skipped: %s", filename)
                        continue

                    # Existing Gmail helper downloads to a local cache. Render's
                    # filesystem is temporary, so this file is NOT the durable copy.
                    local_path = Path(download_pdf_attachment(
                        message_id=message_id,
                        attachment_id=real_attachment_id,
                        filename=filename,
                        inline_data=inline_data,
                    ))

                    if not local_path.is_file():
                        raise FileNotFoundError(f"Downloaded PDF missing: {local_path}")

                    uploaded_key = _object_key(message_id, attachment_id)
                    upload_file(
                        bucket=ORIGINAL_BUCKET,
                        object_path=uploaded_key,
                        local_path=local_path,
                        content_type="application/pdf",
                    )

                    if member is None:
                        member = CorpsMember(state_code=state_code)
                        db.add(member)
                        db.flush()

                    db.add(Document(
                        corps_member_id=member.id,
                        document_type=document_type,
                        month=month,
                        year=year,
                        filename=filename,
                        gmail_message_id=message_id,
                        attachment_id=attachment_id,
                        sender_email=sender_email,
                        status="pending_review",
                        original_file_path=uploaded_key,
                    ))
                    db.commit()
                    uploaded_key = None  # Committed object is now owned by the document.
                    saved_count += 1
                    logger.info(
                        "SAVED: %s | %s | %s | %s | pending_review",
                        filename, document_type, state_code, year,
                    )

                except IntegrityError:
                    db.rollback()
                    duplicate_count += 1
                    logger.warning("Database uniqueness conflict: %s", filename)
                    if uploaded_key:
                        _cleanup_unreferenced_upload(uploaded_key)

                except Exception:
                    db.rollback()
                    failed_count += 1
                    logger.exception("Failed to import document: %s", filename)
                    if uploaded_key:
                        _cleanup_unreferenced_upload(uploaded_key)

    summary = {
        "saved": saved_count,
        "duplicates": duplicate_count,
        "rejected": rejected_count,
        "failed": failed_count,
    }
    logger.info("Processing summary: %s", summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(process_recent_documents(max_results=100))
