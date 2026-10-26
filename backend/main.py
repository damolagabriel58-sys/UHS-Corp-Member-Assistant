
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
import asyncio
import logging
from contextlib import asynccontextmanager
from tempfile import TemporaryDirectory
from urllib.parse import quote

from dotenv import load_dotenv

# Load backend/.env before importing database configuration.
BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

from gmail_sync_worker import gmail_sync_loop

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from database import Base, engine, get_db
from models import (
    AuthSession,
    CorpsMember,
    Document,
    DocumentAuditLog,
    GmailCredential,
)
from signing_service import create_signed_pdf
from gmail_send_service import send_signed_pdf
from storage_service import ORIGINAL_BUCKET, SIGNED_BUCKET, download_bytes, download_file


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

PROJECT_ROOT = BACKEND_DIR.parent

DIRECTOR_EMAIL = os.getenv("DIRECTOR_EMAIL", "").strip().lower()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://127.0.0.1:8000/auth/callback",
)

SESSION_SIGNING_KEY = os.getenv("SESSION_SIGNING_KEY", "")

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://127.0.0.1:5173",
).rstrip("/")

COOKIE_SECURE = (
    os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"
)

SESSION_COOKIE_NAME = "uhs_session"
OAUTH_STATE_COOKIE_NAME = "uhs_oauth_state"

SESSION_LIFETIME = timedelta(hours=8)

# Local development origins. Configure exact production origins
# through FRONTEND_ORIGINS when deploying.
DEFAULT_FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

configured_origins = os.getenv("FRONTEND_ORIGINS", "")

if configured_origins.strip():
    FRONTEND_ORIGINS = [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]
else:
    FRONTEND_ORIGINS = DEFAULT_FRONTEND_ORIGINS.copy()

if FRONTEND_URL not in FRONTEND_ORIGINS:
    FRONTEND_ORIGINS.append(FRONTEND_URL)

if not all(
    [
        DIRECTOR_EMAIL,
        GOOGLE_CLIENT_ID,
        GOOGLE_CLIENT_SECRET,
        SESSION_SIGNING_KEY,
    ]
):
    raise RuntimeError(
        "Google authentication is not configured. "
        "Check DIRECTOR_EMAIL, GOOGLE_CLIENT_ID, "
        "GOOGLE_CLIENT_SECRET, and SESSION_SIGNING_KEY "
        "in backend/.env."
    )

if len(SESSION_SIGNING_KEY) < 32:
    raise RuntimeError(
        "SESSION_SIGNING_KEY is too short. "
        "Generate a strong random secret."
    )

# Production must use HTTPS for both the application and its cookies.
if COOKIE_SECURE:
    if not FRONTEND_URL.startswith("https://"):
        raise RuntimeError(
            "Production FRONTEND_URL must use HTTPS."
        )

    if not GOOGLE_REDIRECT_URI.startswith("https://"):
        raise RuntimeError(
            "Production GOOGLE_REDIRECT_URI must use HTTPS."
        )


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

# Models, including AuthSession, must be imported before this call.
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# AUTOMATIC GMAIL SYNCHRONIZATION
# ---------------------------------------------------------

logger = logging.getLogger("uhs.gmail.lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Starts with the FastAPI process; never signs or sends documents.
    sync_task = asyncio.create_task(gmail_sync_loop(), name="gmail-sync")
    logger.info("Gmail synchronization task started")
    try:
        yield
    finally:
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass
        logger.info("Gmail synchronization task stopped")


# ---------------------------------------------------------
# FASTAPI APPLICATION
# ---------------------------------------------------------

app = FastAPI(
    title="UHS Director Assistant",
    description=(
        "Email-driven document review, approval, "
        "PDF signing, and return workflow."
    ),
    version="0.4.0",
    lifespan=lifespan,
)

# Authlib uses this short-lived signed session to protect OAuth state.
# The Director's actual login session is stored in PostgreSQL.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SIGNING_KEY,
    session_cookie=OAUTH_STATE_COOKIE_NAME,
    max_age=600,
    same_site="lax",
    https_only=COOKIE_SECURE,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


# ---------------------------------------------------------
# GOOGLE OAUTH
# ---------------------------------------------------------

oauth = OAuth()

oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url=(
        "https://accounts.google.com/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid email profile",
    },
)


# ---------------------------------------------------------
# SECURITY HELPERS
# ---------------------------------------------------------

def hash_session_token(token: str) -> str:
    """Hash a session token before storing or querying it."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_allowed_origin(request: Request) -> None:
    """
    Protect state-changing browser requests against cross-site requests.

    The browser must send an Origin matching the configured frontend.
    Requests without a matching Origin are rejected.
    """

    origin = request.headers.get("origin", "").rstrip("/")

    if not origin or origin not in FRONTEND_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Request origin is not authorized.",
        )


def require_director(
    request: Request,
    db: Session = Depends(get_db),
) -> str:
    """Authenticate the Director using a PostgreSQL-backed session."""

    session_token = request.cookies.get(SESSION_COOKIE_NAME)

    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Please sign in with the authorized Google account.",
        )

    session_hash = hash_session_token(session_token)

    auth_session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == session_hash)
        .first()
    )

    now = datetime.now(timezone.utc)

    if auth_session is None:
        raise HTTPException(
            status_code=401,
            detail="Session is invalid. Please sign in again.",
        )

    if auth_session.revoked_at is not None:
        raise HTTPException(
            status_code=401,
            detail="Session has been revoked. Please sign in again.",
        )

    # PostgreSQL normally returns timezone-aware timestamps for TIMESTAMPTZ.
    # Handle a naive value defensively if the database/model configuration
    # returns one.
    expires_at = auth_session.expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at <= now:
        raise HTTPException(
            status_code=401,
            detail="Session has expired. Please sign in again.",
        )

    if auth_session.email.strip().lower() != DIRECTOR_EMAIL:
        raise HTTPException(
            status_code=403,
            detail="This account is not authorized.",
        )

    return auth_session.email


def get_document_or_404(
    document_id: int,
    db: Session,
) -> Document:
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    return document


def require_pdf_key(value: str | None, label: str) -> str:
    """Validate a private Supabase object key; never interpret it as a local path."""
    if not value or not isinstance(value, str):
        raise HTTPException(status_code=404, detail=f"{label} is unavailable.")
    key = value.strip()
    parts = key.split("/")
    if (key.startswith("/") or "\\" in key or ":" in key
            or any(part in ("", ".", "..") for part in parts)
            or not key.lower().endswith(".pdf")):
        raise HTTPException(status_code=400, detail=f"Invalid {label} storage key.")
    return key


def private_pdf_response(bucket: str, key: str, filename: str) -> Response:
    """Stream bytes only to an authenticated Director; never issue public URLs."""
    try:
        content = download_bytes(bucket, key)
    except Exception:
        logger.exception("Private PDF download failed")
        raise HTTPException(status_code=502, detail="Private PDF could not be retrieved.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=502, detail="Stored document is not a valid PDF.")
    safe_filename = Path(filename.replace("\\", "/")).name
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename*=UTF-8''" + quote(safe_filename),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# ---------------------------------------------------------
# PUBLIC ROUTES
# ---------------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "UHS Director Assistant backend is running",
        "status": "success",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "UHS Director Assistant",
    }


# ---------------------------------------------------------
# AUTHENTICATION ROUTES
# ---------------------------------------------------------

@app.get("/auth/login")
async def google_login(request: Request):
    """Redirect the user to Google's sign-in page."""

    return await oauth.google.authorize_redirect(
        request,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )


@app.get("/auth/callback")
async def google_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    """Validate Google's OpenID Connect identity and create a session."""

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        # Do not expose OAuth codes, tokens, or provider error details.
        raise HTTPException(
            status_code=401,
            detail=(
                "Google sign-in could not be completed. "
                "Please try signing in again."
            ),
        )

    # With OpenID Connect configured, Authlib validates the ID token
    # and normally exposes the verified claims as token["userinfo"].
    user_info = token.get("userinfo")

    if not user_info:
        raise HTTPException(
            status_code=401,
            detail="Google did not return a validated identity.",
        )

    email = str(user_info.get("email", "")).strip().lower()
    email_verified = user_info.get("email_verified") is True
    google_subject = user_info.get("sub")

    if not google_subject or not email or not email_verified:
        raise HTTPException(
            status_code=403,
            detail="Google account identity could not be verified.",
        )

    # Only the Director's configured Google account may enter.
    if email != DIRECTOR_EMAIL:
        raise HTTPException(
            status_code=403,
            detail=(
                "This Google account is not authorized "
                "to use UHS Director Assistant."
            ),
        )

    now = datetime.now(timezone.utc)
    raw_session_token = secrets.token_urlsafe(32)

    auth_session = AuthSession(
        token_hash=hash_session_token(raw_session_token),
        email=email,
        created_at=now,
        expires_at=now + SESSION_LIFETIME,
        last_seen_at=now,
    )

    try:
        db.add(auth_session)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="A secure application session could not be created.",
        )

    # Redirect only to the configured frontend URL, never a URL supplied
    # by the request. The session cookie is not accessible to JavaScript.
    response = RedirectResponse(
        url=f"{FRONTEND_URL}/",
        status_code=303,
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_session_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )

    # Remove temporary OAuth state after successful authentication.
    request.session.clear()

    return response


@app.get("/auth/me")
def get_current_director(
    director: str = Depends(require_director),
):
    """Return the currently authenticated Director."""

    return {
        "authenticated": True,
        "email": director,
    }


@app.post("/auth/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """Revoke the current session and clear the browser cookie."""

    require_allowed_origin(request)

    session_token = request.cookies.get(SESSION_COOKIE_NAME)

    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="No active session was found.",
        )

    auth_session = (
        db.query(AuthSession)
        .filter(
            AuthSession.token_hash == hash_session_token(session_token),
            AuthSession.email == director,
        )
        .first()
    )

    if auth_session is not None and auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(timezone.utc)
        db.commit()

    response = RedirectResponse(
        url=f"{FRONTEND_URL}/",
        status_code=303,
    )

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )

    return response


# ---------------------------------------------------------
# DOCUMENT ROUTES
# ---------------------------------------------------------

@app.get("/documents/pending")
def get_pending_documents(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """Return documents waiting for the Director's approval."""

    documents = (
        db.query(Document)
        .filter(Document.status == "pending_review")
        .order_by(Document.created_at.desc())
        .limit(limit)
        .all()
    )

    results = []

    for document in documents:
        member = (
            db.query(CorpsMember)
            .filter(CorpsMember.id == document.corps_member_id)
            .first()
        )

        results.append(
            {
                "id": document.id,
                "filename": document.filename,
                "document_type": document.document_type,
                "month": document.month,
                "state_code": member.state_code if member else None,
                "sender_email": document.sender_email,
                "status": document.status,
                "created_at": (
                    document.created_at.isoformat()
                    if document.created_at
                    else None
                ),
            }
        )

    return {
        "count": len(results),
        "documents": results,
    }


@app.get("/documents/signed")
def get_signed_documents(
    month: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """Read-only signed archive, including documents later marked as sent."""
    query = db.query(Document).filter(Document.status.in_(["signed", "sent", "sending", "send_unknown"]))
    if month:
        query = query.filter(Document.month == month)
    documents = query.order_by(Document.approved_at.desc(), Document.id.desc()).limit(limit).all()
    member_ids = {doc.corps_member_id for doc in documents}
    members = (
        {member.id: member for member in db.query(CorpsMember).filter(CorpsMember.id.in_(member_ids)).all()}
        if member_ids else {}
    )
    return {
        "count": len(documents),
        "documents": [
            {
                "id": doc.id,
                "filename": doc.filename,
                "document_type": doc.document_type,
                "month": doc.month,
                "state_code": members[doc.corps_member_id].state_code if doc.corps_member_id in members else None,
                "sender_email": doc.sender_email,
                "status": doc.status,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "approved_at": doc.approved_at.isoformat() if doc.approved_at else None,
            }
            for doc in documents
        ],
    }


@app.get("/documents/{document_id}")
def get_document_details(
    document_id: int,
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """Return metadata for one document."""

    document = get_document_or_404(document_id, db)

    member = (
        db.query(CorpsMember)
        .filter(CorpsMember.id == document.corps_member_id)
        .first()
    )

    return {
        "id": document.id,
        "filename": document.filename,
        "document_type": document.document_type,
        "month": document.month,
        "state_code": member.state_code if member else None,
        "sender_email": document.sender_email,
        "status": document.status,
        "approved_at": (
            document.approved_at.isoformat()
            if document.approved_at
            else None
        ),
        "approved_by": document.approved_by,
        "created_at": (
            document.created_at.isoformat()
            if document.created_at
            else None
        ),
    }


@app.get("/documents/{document_id}/pdf")
def preview_document_pdf(
    document_id: int,
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """Display the original PDF to the authenticated Director."""

    document = get_document_or_404(document_id, db)
    key = require_pdf_key(document.original_file_path, "Original PDF")
    return private_pdf_response(ORIGINAL_BUCKET, key, document.filename)



@app.get("/documents/{document_id}/signed-pdf")
def preview_signed_document(
    document_id: int,
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """Allow the authenticated Director to review a signed copy."""
    document = get_document_or_404(document_id, db)
    if document.status not in {"signed", "sending", "send_unknown", "sent"} or not document.signed_file_path:
        raise HTTPException(status_code=404, detail="Signed PDF is not available.")

    key = require_pdf_key(document.signed_file_path, "Signed PDF")
    return private_pdf_response(SIGNED_BUCKET, key, f"document_{document.id}_signed.pdf")



@app.post("/documents/{document_id}/send")
def send_approved_document(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """Explicit Director-only send; never invoked by Gmail sync or signing."""
    require_allowed_origin(request)
    try:
        doc = db.query(Document).filter(Document.id == document_id).with_for_update().first()
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if doc.status != "signed":
            raise HTTPException(status_code=409, detail=f"Cannot send a document with status {doc.status}")
        if not doc.sender_email:
            raise HTTPException(status_code=400, detail="Original sender email is missing")
        if not doc.signed_file_path:
            raise HTTPException(status_code=400, detail="Signed PDF is missing")
        signed_key = require_pdf_key(doc.signed_file_path, "Signed PDF")
        # Check storage before reserving the send. No Gmail call yet.
        try:
            signed_content = download_bytes(SIGNED_BUCKET, signed_key)
        except Exception:
            logger.exception("Signed PDF retrieval failed before send reservation")
            raise HTTPException(status_code=502, detail="Signed PDF could not be retrieved")
        if not signed_content.startswith(b"%PDF-"):
            raise HTTPException(status_code=502, detail="Signed PDF is invalid")

        recipient = doc.sender_email.strip()
        # Reserve the send BEFORE calling Gmail. An ambiguous network failure
        # must not cause automatic retries and accidental duplicate emails.
        doc.status = "sending"
        db.add(DocumentAuditLog(document_id=doc.id, action="send_requested", actor=director,
            details=f"Recipient: {recipient}; PDF: {signed_key}"))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    try:
        with TemporaryDirectory(prefix="uhs_send_") as temp_dir:
            pdf = Path(temp_dir) / f"document_{document_id}_signed.pdf"
            pdf.write_bytes(signed_content)
            result = send_signed_pdf(
                recipient=recipient,
                pdf_path=pdf,
                filename=pdf.name,
                document_type=doc.document_type,
                month=doc.month,
            )
    except Exception as exc:
        # Gmail may have accepted the message before a connection timed out.
        # Preserve the unknown state for manual reconciliation, never retry blindly.
        db.rollback()
        doc = db.query(Document).filter(Document.id == document_id).first()
        doc.status = "send_unknown"
        db.add(DocumentAuditLog(document_id=document_id, action="send_outcome_unknown",
            actor=director, details=f"Recipient: {recipient}; Error type: {type(exc).__name__}"))
        db.commit()
        logger.exception("Gmail delivery outcome unknown for document %s", document_id)
        raise HTTPException(status_code=502, detail=(
            "Gmail delivery could not be confirmed. Do not retry until the "
            "Director checks Gmail Sent Mail and the audit record."
        ))

    gmail_id = result.get("id")
    if not gmail_id:
        doc = db.query(Document).filter(Document.id == document_id).first()
        doc.status = "send_unknown"
        db.add(DocumentAuditLog(document_id=document_id, action="send_outcome_unknown",
            actor=director, details=f"Gmail response had no message ID; recipient: {recipient}"))
        db.commit()
        raise HTTPException(status_code=502, detail="Gmail did not confirm a message ID; check Sent Mail")

    doc = db.query(Document).filter(Document.id == document_id).first()
    doc.status = "sent"
    sent_at = datetime.now(timezone.utc)
    db.add(DocumentAuditLog(document_id=document_id, action="email_sent",
        actor=director, details=f"Recipient: {recipient}; Gmail ID: {gmail_id}; Sent at: {sent_at.isoformat()}"))
    db.commit()
    return {"status": "sent", "recipient": recipient, "sent_at": sent_at.isoformat(), "gmail_message_id": gmail_id}


@app.post("/documents/{document_id}/approve")
def approve_and_sign_document(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
    director: str = Depends(require_director),
):
    """
    Explicitly approve and sign one pending document.

    This endpoint does not send email. The Director's browser must
    make an intentional POST request from the authorized frontend.
    """

    # Reject cross-origin approval attempts.
    require_allowed_origin(request)

    try:
        # Lock the row to prevent concurrent approvals.
        document = (
            db.query(Document)
            .filter(Document.id == document_id)
            .with_for_update()
            .first()
        )

        if document is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        if document.status != "pending_review":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This document is not awaiting review. "
                    f"Current status: {document.status}."
                ),
            )

        original_key = require_pdf_key(document.original_file_path, "Original PDF")
        signed_key = create_signed_pdf(
            original_file_path=original_key,
            document_id=document.id,
        )
        document.signed_file_path = signed_key
        document.approved_at = datetime.now(timezone.utc)
        document.approved_by = director
        document.status = "signed"

        audit_entry = DocumentAuditLog(
            document_id=document.id,
            action="approved_and_signed",
            actor=director,
            details=(
                f"Original: {original_key}; "
                f"Signed copy: {signed_key}"
            ),
        )

        db.add(audit_entry)
        db.commit()

        return {
            "message": (
                "Document approved and signed. "
                "Email delivery has not been performed."
            ),
            "document_id": document.id,
            "status": document.status,
            "approved_at": document.approved_at.isoformat(),
            "approved_by": director,
            "signed_file": signed_key,
            "email_sent": False,
        }

    except HTTPException:
        db.rollback()
        raise

    except FileExistsError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "A signed PDF already exists. Check the existing "
                "file and audit records before retrying."
            ),
        )

    except (FileNotFoundError, ValueError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        db.rollback()
        # Do not blindly delete the signed file. A database commit
        # might have succeeded before an error was reported.
        raise HTTPException(
            status_code=500,
            detail=(
                "Approval could not be completed. Check backend "
                "logs and database records before retrying."
            ),
        )
