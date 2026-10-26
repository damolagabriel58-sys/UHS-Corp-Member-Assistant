"""Background Gmail importer, started by FastAPI lifespan."""
import asyncio
import logging

from gmail_service import verify_director_gmail
from document_service import process_recent_documents

logger = logging.getLogger("uhs.gmail.worker")
SYNC_INTERVAL_SECONDS = 30
MAX_RESULTS = 100


def sync_gmail_once():
    """Verify mailbox and import valid PDF attachments. No signing/sending."""
    verify_director_gmail()
    return process_recent_documents(max_results=MAX_RESULTS)


async def gmail_sync_loop():
    logger.info("Automatic Gmail import enabled (every %s seconds)", SYNC_INTERVAL_SECONDS)
    while True:
        try:
            result = await asyncio.to_thread(sync_gmail_once)
            logger.info("Gmail import completed: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Gmail import failed; retrying on next interval")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
