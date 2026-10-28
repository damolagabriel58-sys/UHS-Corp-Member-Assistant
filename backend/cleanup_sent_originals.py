"""Optional maintenance: remove old originals for ALREADY SENT documents.

Never run without a backup. By default, print what would happen.
Run from backend/ AFTER applying the SQL migration:
  python cleanup_sent_originals.py
  python cleanup_sent_originals.py --execute

Only originals of SENT documents with valid signed PDFs are removed.
Never deletes buckets, signature assets, or the signed PDF itself.
"""
import argparse
import logging

from database import SessionLocal
from models import Document, DocumentAuditLog
from storage_service import ORIGINAL_BUCKET, SIGNED_BUCKET, download_bytes, delete_file

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Really delete eligible originals")
    args = parser.parse_args()
    eligible = removed = skipped = 0

    with SessionLocal() as db:
        docs = db.query(Document).filter(Document.status == "sent", Document.original_file_path.isnot(None)).all()
        for doc in docs:
            if not doc.signed_file_path:
                log.warning("Skip %s (no stored signed PDF)", doc.id)
                skipped += 1
                continue
            try:
                data = download_bytes(SIGNED_BUCKET, doc.signed_file_path)
                if not data.startswith(b"%PDF-"):
                    raise ValueError("Not a valid PDF")
                eligible += 1
                if not args.execute:
                    log.info("DRY RUN doc=%s original=%s", doc.id, doc.original_file_path)
                    continue
                delete_file(ORIGINAL_BUCKET, doc.original_file_path)
                doc.original_file_path = None
                db.add(DocumentAuditLog(
                    document_id=doc.id,
                    action="original_pdf_discarded",
                    actor="system",
                    details="Historical cleanup: sent PDF verified; signed archive retained.",
                ))
                db.commit()
                removed += 1
                log.info("Original discarded for sent doc=%s", doc.id)
            except Exception:
                db.rollback()
                skipped += 1
                log.exception("Skipped original for doc=%s", doc.id)

    log.info("Eligible=%s; originals removed=%s; skipped=%s; mode=%s",
             eligible, removed, skipped, "EXECUTE" if args.execute else "DRY RUN")


if __name__ == "__main__":
    main()
