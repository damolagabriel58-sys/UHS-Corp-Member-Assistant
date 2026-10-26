
import base64
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(BASE_DIR / ".env")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

ORIGINAL_PDF_DIR = (
    PROJECT_ROOT / "Private local data" / "Original PDFs"
)

DIRECTOR_EMAIL = os.getenv(
    "DIRECTOR_EMAIL", ""
).strip().lower()

MAX_PDF_SIZE = 15 * 1024 * 1024  # 15 MB

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# TOKEN MANAGEMENT
# ---------------------------------------------------------

def save_token(creds):
    """Save Gmail OAuth credentials safely."""

    TOKEN_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # Avoid writing partially updated credentials.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=TOKEN_FILE.parent,
        prefix=".gmail_token_",
        suffix=".tmp",
        delete=False,
    ) as temp_file:
        temp_file.write(creds.to_json())
        temporary_path = Path(temp_file.name)

    try:
        os.replace(temporary_path, TOKEN_FILE)
    finally:
        temporary_path.unlink(missing_ok=True)


def get_gmail_service(interactive=False):
    """
    Create an authenticated Gmail API client.

    interactive=False:
        Used by background workers.
        Never launches a browser.

    interactive=True:
        Used only for initial authorization.
    """

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Gmail credentials not found: {CREDENTIALS_FILE}"
        )

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(TOKEN_FILE),
            SCOPES
        )

    # A previously saved read-only token cannot be upgraded just by changing
    # SCOPES. Require a fresh interactive consent grant before sending.
    if creds and not creds.has_scopes(SCOPES):
        if not interactive:
            raise RuntimeError(
                "Gmail token lacks the required send permission. "
                "Back up backend/token.json, remove the active token.json, "
                "and run get_gmail_service(interactive=True) to reauthorize."
            )
        creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(creds)

            logger.info(
                "Gmail access token refreshed successfully."
            )

        except Exception:
            logger.exception(
                "Unable to refresh Gmail access token."
            )

            if not interactive:
                raise RuntimeError(
                    "Gmail authorization requires attention. "
                    "Background synchronization cannot continue."
                )

            creds = None

    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError(
                "Gmail authorization is missing or invalid. "
                "Run initial interactive authorization."
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            SCOPES
        )

        creds = flow.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
        )

        save_token(creds)

        logger.info(
            "Initial Gmail authorization completed."
        )

    return build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )


# ---------------------------------------------------------
# ACCOUNT VERIFICATION
# ---------------------------------------------------------

def get_connected_gmail_address(service=None):
    """Return the Gmail address associated with the OAuth token."""

    if service is None:
        service = get_gmail_service()

    profile = (
        service.users()
        .getProfile(userId="me")
        .execute()
    )

    return profile["emailAddress"].strip().lower()


def verify_director_gmail(service=None):
    """
    Ensure Gmail synchronization uses the authorized
    Director's mailbox.
    """

    if not DIRECTOR_EMAIL:
        raise RuntimeError(
            "DIRECTOR_EMAIL is missing from backend/.env."
        )

    if service is None:
        service = get_gmail_service()

    connected_email = get_connected_gmail_address(service)

    if connected_email != DIRECTOR_EMAIL:
        raise PermissionError(
            "Connected Gmail account does not match "
            "the authorized Director's email. "
            "Synchronization has been blocked."
        )

    return service


# ---------------------------------------------------------
# LIST RECENT EMAILS
# ---------------------------------------------------------

def list_recent_emails(max_results=10, query=None):
    """
    Retrieve recent Gmail message metadata.

    query:
        Optional Gmail search query, for example:
        has:attachment filename:pdf
    """

    service = verify_director_gmail()

    request_args = {
        "userId": "me",
        "maxResults": max_results,
    }

    if query:
        request_args["q"] = query

    response = (
        service.users()
        .messages()
        .list(**request_args)
        .execute()
    )

    messages = response.get("messages", [])
    results = []

    for message in messages:
        details = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=[
                    "From",
                    "Subject",
                    "Date",
                ],
            )
            .execute()
        )

        headers = {
            header["name"].lower(): header["value"]
            for header in details.get(
                "payload", {}
            ).get("headers", [])
        }

        results.append({
            "id": message["id"],
            "thread_id": details.get("threadId"),
            "sender": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": details.get("snippet", ""),
        })

    return results


# ---------------------------------------------------------
# FIND PDF ATTACHMENTS
# ---------------------------------------------------------

def list_pdf_attachments(message_id):
    """
    Find PDF attachments, including nested MIME parts
    and attachments in the root payload.
    """

    service = verify_director_gmail()

    message = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="full",
        )
        .execute()
    )

    pdfs = []

    def inspect_parts(parts):
        for part in parts:
            filename = part.get("filename", "")
            mime_type = part.get(
                "mimeType", ""
            ).lower()

            body = part.get("body", {})

            if filename and (
                filename.lower().endswith(".pdf")
                or mime_type == "application/pdf"
            ):
                pdfs.append({
                    "filename": filename,
                    "attachment_id": body.get(
                        "attachmentId"
                    ),
                    "message_id": message_id,
                    "size": body.get("size", 0),
                    "inline_data": body.get("data"),
                })

            inspect_parts(
                part.get("parts", [])
            )

    inspect_parts([
        message.get("payload", {})
    ])

    return pdfs


# ---------------------------------------------------------
# DOWNLOAD PDF ATTACHMENTS
# ---------------------------------------------------------

def download_pdf_attachment(
    message_id,
    attachment_id,
    filename,
    inline_data=None,
):
    """
    Download a Gmail PDF attachment.

    Supports:
    - Standard Gmail attachment IDs
    - Inline base64 attachment data
    - PDF signature validation
    - File size limits
    - Collision-resistant filenames
    """

    service = verify_director_gmail()

    if attachment_id:
        response = (
            service.users()
            .messages()
            .attachments()
            .get(
                userId="me",
                messageId=message_id,
                id=attachment_id,
            )
            .execute()
        )

        encoded_data = response.get(
            "data", ""
        )

    elif inline_data:
        encoded_data = inline_data

    else:
        raise ValueError(
            "No attachment ID or inline PDF data "
            "was provided."
        )

    pdf_data = base64.urlsafe_b64decode(
        encoded_data + "=" * (-len(encoded_data) % 4)
    )

    if len(pdf_data) > MAX_PDF_SIZE:
        raise ValueError(
            "PDF attachment exceeds the 15 MB limit."
        )

    if not pdf_data.startswith(b"%PDF-"):
        raise ValueError(
            "The attachment does not contain "
            "a valid PDF header."
        )

    ORIGINAL_PDF_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    safe_name = Path(
        filename.replace("\\", "/")
    ).name

    if not safe_name.lower().endswith(".pdf"):
        raise ValueError(
            "Attachment filename must end with .pdf."
        )

    if not safe_name or safe_name in (".", ".."):
        raise ValueError(
            "Invalid attachment filename."
        )

    # Preserve the original attachment name while
    # preventing accidental overwrites.
    output_path = (
        ORIGINAL_PDF_DIR /
        f"{message_id}_{safe_name}"
    )

    if output_path.exists():
        logger.info(
            "PDF already downloaded: %s",
            output_path.name
        )

        return str(output_path)

    # Exclusive creation prevents overwriting
    # an existing document.
    with output_path.open("xb") as file:
        file.write(pdf_data)

    logger.info(
        "PDF downloaded successfully: %s",
        output_path.name
    )

    return str(output_path)
