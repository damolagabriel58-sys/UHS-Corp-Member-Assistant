
from gmail_service import (
    list_recent_emails,
    list_pdf_attachments,
)
from document_classifier import classify_document


def scan_incoming_documents(max_results=10):
    """Find PDF attachments and classify them by filename."""

    emails = list_recent_emails(max_results=max_results)
    documents = []

    for email in emails:
        attachments = list_pdf_attachments(email["id"])

        for attachment in attachments:
            filename = attachment["filename"]
            classification = classify_document(filename)

            document = {
                "email_id": email["id"],
                "sender": email["sender"],
                "subject": email["subject"],
                "filename": filename,
                "attachment_id": attachment["attachment_id"],
                **classification,
            }

            documents.append(document)

            if classification["recognized"]:
                print(
                    f"[RECOGNIZED] {filename}\n"
                    f"  Type: {classification['document_type']}\n"
                    f"  Month: {classification['month']}\n"
                    f"  State code: {classification['state_code']}"
                )
            else:
                print(
                    f"[MANUAL REVIEW] {filename}\n"
                    "  Reason: Filename does not match a supported type."
                )

    return documents


if __name__ == "__main__":
    results = scan_incoming_documents(max_results=10)
    print(f"\nTotal PDF attachments found: {len(results)}")
