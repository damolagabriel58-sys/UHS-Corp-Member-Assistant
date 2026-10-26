"""Send a Director-approved signed PDF via the already authorized Gmail API."""
import base64
import re
from email.message import EmailMessage
from pathlib import Path
from gmail_service import get_gmail_service

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")


def send_signed_pdf(*, recipient: str, pdf_path: Path, filename: str, document_type: str, month: str):
    if not EMAIL_RE.fullmatch(recipient or "") or "\n" in recipient or "\r" in recipient:
        raise ValueError("Invalid recipient email address")
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise FileNotFoundError("Signed PDF not found")

    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = "UHS — Your signed document"
    message.set_content(
        "Dear Corps Member,\n\n"
        "Please find attached your signed document, reviewed and approved "
        "by the UHS Director.\n\n"
        "Kind regards,\nUHS Director's Office\n"
    )
    message.add_attachment(
        pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=filename
    )
    service = get_gmail_service(interactive=False)
    # The Gmail OAuth token MUST have the gmail.send scope. The login OAuth
    # token (openid/email/profile) is separate and cannot send mail.
    return service.users().messages().send(
        userId="me",
        body={"raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")},
    ).execute()
