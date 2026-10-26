
import base64
import json
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from gmail_token_store import load_gmail_token, save_gmail_token


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
    """Persist encrypted credentials to PostgreSQL, and locally for development."""
    if not DIRECTOR_EMAIL:
        raise RuntimeError("DIRECTOR_EMAIL is not configured.")

    token_json = creds.to_json()
    save_gmail_token(DIRECTOR_EMAIL, token_json)

    # Render's filesystem is ephemeral; never write token.json there.
    if os.getenv("RENDER"):
        return

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=TOKEN_FILE.parent,
            prefix=".gmail_token_",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(token_json)
            temporary_path = Path(temp_file.name)
        os.replace(temporary_path, TOKEN_FILE)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _load_authorized_credentials():
    """Prefer encrypted DB credentials; allow local token only during migration."""
    stored_token = load_gmail_token(DIRECTOR_EMAIL)
    if stored_token:
        info = json.loads(stored_token)
        granted = set(info.get("scopes") or [])
        if not set(SCOPES).issubset(granted):
            raise RuntimeError(
                "Stored Gmail token does not record the required Gmail scopes. "
                "Reauthorize locally with both permissions."
            )
        return Credentials.from_authorized_user_info(info, scopes=SCOPES)

    if not os.getenv("RENDER") and TOKEN_FILE.exists():
        info = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        granted = set(info.get("scopes") or [])
        if not set(SCOPES).issubset(granted):
            raise RuntimeError(
                "Local Gmail token does not record the required Gmail scopes. "
                "Reauthorize locally with both permissions."
            )
        return Credentials.from_authorized_user_info(info, scopes=SCOPES)

    return None


def get_gmail_service(interactive=False):
    """Build Gmail client without browser interaction in background workers."""
    if not DIRECTOR_EMAIL:
        raise RuntimeError("DIRECTOR_EMAIL is not configured.")

    creds = _load_authorized_credentials()

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(creds)
            logger.info("Gmail access token refreshed and persisted.")
        except Exception as exc:
            logger.exception("Unable to refresh and persist Gmail credentials.")
            if not interactive:
                raise RuntimeError(
                    "Gmail authorization requires attention; synchronization stopped."
                ) from exc
            creds = None

    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError(
                "Gmail authorization missing or invalid. "
                "Authorize locally and migrate the token to PostgreSQL."
            )
        if os.getenv("RENDER"):
            raise RuntimeError("Interactive Gmail authorization is disabled on Render.")
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"Gmail OAuth client configuration not found: {CREDENTIALS_FILE}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE), SCOPES
        )
        creds = flow.run_local_server(
            host="localhost", port=0, open_browser=True
        )

        # Verify the actual mailbox BEFORE persisting a new authorization.
        provisional_service = build(
            "gmail", "v1", credentials=creds, cache_discovery=False
        )
        connected = get_connected_gmail_address(provisional_service)
        if connected != DIRECTOR_EMAIL:
            raise PermissionError(
                "New Gmail authorization belongs to a different account. "
                "Credentials were not saved."
            )
        save_token(creds)
        logger.info("Initial Gmail authorization completed and persisted.")

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


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
