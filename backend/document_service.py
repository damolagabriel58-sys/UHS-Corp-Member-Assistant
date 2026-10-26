
import hashlib
import logging
from email.utils import parseaddr
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

logger = logging.getLogger(__name__)


def process_recent_documents(max_results=100):
    """Import valid Gmail PDFs into PostgreSQL without duplicates."""

    db = SessionLocal()

    saved_count = 0
    duplicate_count = 0
    rejected_count = 0
    failed_count = 0

    try:
        emails = list_recent_emails(
            max_results=max_results,
            query="has:attachment filename:pdf",
        )

        for email in emails:
            message_id = email["id"]
            sender_email = parseaddr(
                email.get("sender", "")
            )[1].strip().lower()

            try:
                attachments = list_pdf_attachments(message_id)
            except Exception:
                failed_count += 1
                logger.exception(
                    "Unable to inspect Gmail message %s",
                    message_id,
                )
                continue

            for attachment in attachments:
                filename = attachment["filename"]
                attachment_id = attachment.get("attachment_id")
                inline_data = attachment.get("inline_data")

                # Use a stable synthetic identifier for inline PDFs.
                # The database must accept a string attachment ID.
                if not attachment_id and inline_data:
                    attachment_id = (
                        "inline_"
                        + hashlib.sha256(
                            (
                                message_id
                                + ":"
                                + filename
                                + ":"
                                + inline_data
                            ).encode("utf-8")
                        ).hexdigest()
                    )

                if not attachment_id:
                    rejected_count += 1
                    logger.warning(
                        "Attachment has no downloadable data: %s",
                        filename,
                    )
                    continue

                # Check for previously imported Gmail attachments.
                existing_attachment = (
                    db.query(Document)
                    .filter_by(
                        gmail_message_id=message_id,
                        attachment_id=attachment_id,
                    )
                    .first()
                )

                if existing_attachment:
                    duplicate_count += 1
                    continue

                details = classify_document(filename)

                if not details["recognized"]:
                    rejected_count += 1
                    logger.info(
                        "Invalid document filename: %s",
                        filename,
                    )
                    continue

                document_type = details["document_type"]
                month = details["month"]
                state_code = details["state_code"]

                if not sender_email:
                    rejected_count += 1
                    logger.warning(
                        "Sender email unavailable: %s",
                        filename,
                    )
                    continue

                member = (
                    db.query(CorpsMember)
                    .filter_by(state_code=state_code)
                    .first()
                )

                # Prevent repeated submissions for the same
                # member, month, and document type.
                if member is not None:
                    existing_document = (
                        db.query(Document)
                        .filter_by(
                            corps_member_id=member.id,
                            month=month,
                            document_type=document_type,
                        )
                        .first()
                    )

                    if existing_document:
                        duplicate_count += 1
                        logger.info(
                            "Duplicate business document skipped: %s",
                            filename,
                        )
                        continue

                original_path = None

                try:
                    # The updated Gmail service supports inline_data.
                    original_path = download_pdf_attachment(
                        message_id=message_id,
                        attachment_id=(
                            attachment.get("attachment_id")
                        ),
                        filename=filename,
                        inline_data=inline_data,
                    )

                    if member is None:
                        member = CorpsMember(
                            state_code=state_code
                        )
                        db.add(member)
                        db.flush()

                    document = Document(
                        corps_member_id=member.id,
                        document_type=document_type,
                        month=month,
                        filename=filename,
                        gmail_message_id=message_id,
                        attachment_id=attachment_id,
                        sender_email=sender_email,
                        status="pending_review",
                        original_file_path=original_path,
                    )

                    db.add(document)
                    db.commit()

                    saved_count += 1

                    logger.info(
                        "SAVED: %s | %s | %s | pending_review",
                        filename,
                        document_type,
                        state_code,
                    )

                except IntegrityError:
                    db.rollback()
                    duplicate_count += 1
                    logger.warning(
                        "Database uniqueness conflict: %s",
                        filename,
                    )

                except Exception:
                    db.rollback()
                    failed_count += 1
                    logger.exception(
                        "Failed to import document: %s",
                        filename,
                    )

        summary = {
            "saved": saved_count,
            "duplicates": duplicate_count,
            "rejected": rejected_count,
            "failed": failed_count,
        }

        logger.info("Processing summary: %s", summary)

        return summary

    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print(
        process_recent_documents(max_results=100)
    )
