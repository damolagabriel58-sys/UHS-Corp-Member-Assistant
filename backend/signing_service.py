"""UHS Director Assistant: approval-controlled PDF signing.

Sign ONLY recognized University Health Service Director fields on the supplied
Clearance and Payment Advice form layouts. This module does not authorize
signing, approve documents, or send email. The FastAPI approval endpoint must
verify the Director and an explicit approval before calling create_signed_pdf.

Original and signed PDFs, and the genuine Director signature image, remain in
private Supabase Storage. This module never changes the stored original.
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import fitz

from storage_service import (
    ORIGINAL_BUCKET,
    SIGNED_BUCKET,
    ASSETS_BUCKET,
    download_file,
    upload_file,
)

logger = logging.getLogger(__name__)

SIGNATURE_OBJECT_KEYS = (
    "director_signature.png",
    "director_signature.jpg",
    "director_signature.jpeg",
)


class SignatureFieldNotFound(ValueError):
    """A recognized, safe Director signature field could not be identified."""


def _normalize_document_type(document_type: str | None) -> str | None:
    if document_type is None:
        return None
    normalized = document_type.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in ("clearance", "monthly_clearance"):
        return "clearance"
    if normalized in ("payment_approval", "paymentapproval", "payment_advice"):
        return "payment_approval"
    raise SignatureFieldNotFound(f"Unsupported document type: {document_type}")


def _rectangles_overlap(first: fitz.Rect, second: fitz.Rect) -> bool:
    overlap = first & second
    return not overlap.is_empty and overlap.width > 0.5 and overlap.height > 0.5


def _ensure_area_is_blank(page: fitz.Page, image_rect: fitz.Rect) -> None:
    """Refuse to cover text, images, or annotations already in the target."""
    if not page.rect.contains(image_rect) or image_rect.width < 50 or image_rect.height < 15:
        raise SignatureFieldNotFound("Director signature space is outside the page or too small")

    for word in page.get_text("words"):
        if _rectangles_overlap(image_rect, fitz.Rect(word[:4])):
            raise SignatureFieldNotFound("Director signature space contains existing text")

    for image in page.get_images(full=True):
        for placed_rect in page.get_image_rects(image[0]):
            if _rectangles_overlap(image_rect, placed_rect):
                raise SignatureFieldNotFound("Director signature space already contains an image")

    # Guard against an already drawn (vector-ink) signature. Thin printed
    # underlines do not occupy the image rectangle on these form layouts.
    for drawing in page.get_drawings():
        ink_rect = fitz.Rect(drawing["rect"])
        if ink_rect.height > 2 and _rectangles_overlap(image_rect, ink_rect):
            raise SignatureFieldNotFound("Director signature space contains existing drawing")

    for annotation in page.annots() or []:
        if _rectangles_overlap(image_rect, annotation.rect):
            raise SignatureFieldNotFound("Director signature space contains an annotation")


# Small date beside the signature, not beneath it.
APPROVAL_DATE_FONT_SIZE = 6.5


def _ensure_date_is_blank(
    page: fitz.Page, date_position: fitz.Point, image_rect: fitz.Rect
) -> None:
    """Keep the date inside a blank, separate area beside the signature."""
    # A representative full-length date defines the maximum reserved width.
    sample_date = "28 September 2026"
    width = fitz.get_text_length(
        sample_date, fontname="helv", fontsize=APPROVAL_DATE_FONT_SIZE
    )
    date_rect = fitz.Rect(
        date_position.x - 1,
        date_position.y - 10,
        date_position.x + width + 2,
        date_position.y + 5,
    )
    if _rectangles_overlap(date_rect, image_rect):
        raise SignatureFieldNotFound("Date would overlap the Director's signature")
    _ensure_area_is_blank(page, date_rect)


def _find_clearance_field(page: fitz.Page) -> tuple[fitz.Rect, fitz.Point]:
    """Between 'Yours faithfully' and the printed Director name."""
    if not page.search_for("CLEARANCE FOR THE MONTH OF"):
        raise SignatureFieldNotFound("Not a recognized UHS clearance form")

    closings = page.search_for("Yours faithfully")
    names = page.search_for("Dr Aderonke B. Ajav")
    if not closings or not names:
        raise SignatureFieldNotFound("Clearance closing or printed Director name missing")

    closing = max(closings, key=lambda rect: rect.y0)
    names_below = [rect for rect in names if rect.y0 > closing.y1]
    if not names_below:
        raise SignatureFieldNotFound("Director name not found below clearance closing")
    name = min(names_below, key=lambda rect: rect.y0)

    gap = name.y0 - closing.y1
    if not 32 <= gap <= 85:
        raise SignatureFieldNotFound("Unexpected clearance signature area dimensions")

    # Anchor the visible signature ink immediately beneath 'Yours faithfully'.
    # The supplied signature image has padding around the handwritten ink, so
    # its image rectangle starts slightly left of the text; this keeps the ink
    # below the salutation rather than over on the right-hand side of the page.
    # Reserve a separate horizontal area for a small date to its RIGHT.
    image_rect = fitz.Rect(
        max(page.rect.x0 + 5, closing.x0 - 33),
        closing.y1 + 3,
        closing.x0 + 77,
        name.y0 - 12,
    )
    date_position = fitz.Point(closing.x0 + 91, closing.y1 + 25)
    _ensure_area_is_blank(page, image_rect)
    _ensure_date_is_blank(page, date_position, image_rect)
    return image_rect, date_position


def _find_payment_field(page: fitz.Page) -> tuple[fitz.Rect, fitz.Point]:
    """Above the underline marked 'Signature of Director', never the employee line."""
    if not page.search_for("PAYMENT ADVICE FOR INTERNS"):
        raise SignatureFieldNotFound("Not a recognized UHS payment advice form")

    labels = page.search_for("Signature of Director:")
    if not labels:
        raise SignatureFieldNotFound("Director signature label missing")
    label = max(labels, key=lambda rect: rect.y0)

    # Find the actual horizontal underline to the right of this precise label.
    candidate_lines = []
    for drawing in page.get_drawings():
        line = fitz.Rect(drawing["rect"])
        if (line.width >= 125 and line.height < 1.5
                and line.x0 >= label.x1 + 25
                and abs(line.y0 - label.y1) < 8):
            candidate_lines.append(line)
    if not candidate_lines:
        raise SignatureFieldNotFound("Director signature underline not found")
    line = min(candidate_lines, key=lambda rect: abs(rect.y0 - label.y1))

    # Both the signature and date sit BETWEEN the employee underline and the
    # Director underline. The compact image box leaves clear space on its right
    # for a small date, ABOVE (not below) the Director's signing line.
    image_rect = fitz.Rect(
        line.x0 + 5,
        line.y0 - 27,
        line.x0 + 120,
        line.y0 - 3,
    )
    date_position = fitz.Point(line.x0 + 130, line.y0 - 8)
    _ensure_area_is_blank(page, image_rect)
    _ensure_date_is_blank(page, date_position, image_rect)
    return image_rect, date_position


def find_director_signature_field(
    page: fitz.Page,
    document_type: str | None = None,
) -> tuple[fitz.Rect, fitz.Point]:
    """Find genuine Director field by textual anchors and drawn underline."""
    normalized = _normalize_document_type(document_type)
    attempts = (normalized,) if normalized else ("clearance", "payment_approval")
    for doc_type in attempts:
        try:
            if doc_type == "clearance":
                return _find_clearance_field(page)
            if doc_type == "payment_approval":
                return _find_payment_field(page)
        except SignatureFieldNotFound:
            continue
    raise SignatureFieldNotFound(
        "No safe, recognizable Director signature field was found. "
        "Document was not signed; manual review is required."
    )


def place_signature(
    page: fitz.Page,
    signature_path: Path,
    approval_date,
    image_rect: fitz.Rect,
    date_position: fitz.Point,
) -> None:
    """Embed the existing signature image unchanged; add the approval date."""
    # PyMuPDF embeds the original image; keep_proportion prevents stretching.
    page.insert_image(
        image_rect,
        filename=str(signature_path),
        keep_proportion=True,
        overlay=True,
    )
    page.insert_text(
        date_position,
        approval_date.strftime("%d %B %Y"),
        fontsize=APPROVAL_DATE_FONT_SIZE,
        fontname="helv",
        color=(0, 0, 0),
        overlay=True,
    )


def _download_signature(destination_dir: Path) -> Path:
    """Read genuine signature only from the private director-assets bucket."""
    last_error = None
    for key in SIGNATURE_OBJECT_KEYS:
        destination = destination_dir / key
        try:
            download_file(ASSETS_BUCKET, key, destination)
            if not destination.is_file() or destination.stat().st_size == 0:
                raise ValueError("Signature asset is empty")
            # Verify that the stored file is a valid image before stamping it.
            pixmap = fitz.Pixmap(str(destination))
            if pixmap.width < 5 or pixmap.height < 5:
                raise ValueError("Signature image dimensions are invalid")
            return destination
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status is None:
                status = getattr(exc, "status", None)
            message = str(exc).lower()
            missing = status in (400, 404, "400", "404") and (
                "not found" in message or "not_found" in message or "no such" in message
            )
            if not missing:
                raise RuntimeError("Could not retrieve the Director's signature asset") from exc
            last_error = exc
    raise FileNotFoundError(
        "Upload director_signature.png, .jpg, or .jpeg to the private "
        "director-assets bucket (bucket root)."
    ) from last_error


def create_signed_pdf(
    original_file_path: str | Path,
    document_id: int,
    document_type: str | None = None,
) -> str:
    """Sign only a designated Director field and upload to private signed-pdfs.

    Call ONLY after explicit Director approval, from the protected FastAPI route.
    The document_type argument is optional for compatibility with the existing
    main.py, which currently supplies only the stored object key and document id.
    If omitted, the function identifies the recognized form from PDF anchors.
    Unknown / incompatible layouts fail closed: no fallback to bottom-left and
    no new signature page is created.
    """
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
        raise ValueError("document_id must be a positive integer")

    original_key = str(original_file_path)
    if not original_key or not original_key.lower().endswith(".pdf"):
        raise ValueError("The source document must be a stored PDF object key")

    # Validate any explicit document type before downloading signature material.
    _normalize_document_type(document_type)
    signed_key = f"document_{document_id}_signed.pdf"
    approval_date = datetime.now(ZoneInfo("Africa/Lagos")).date()

    with TemporaryDirectory(prefix="uhs_signing_") as tmp:
        workdir = Path(tmp)
        original_path = workdir / "original.pdf"
        output_path = workdir / "signed.pdf"

        download_file(ORIGINAL_BUCKET, original_key, original_path)
        if not original_path.read_bytes().startswith(b"%PDF-"):
            raise ValueError("Original storage object is not a PDF")
        signature_path = _download_signature(workdir)

        document = fitz.open(str(original_path))
        try:
            if document.is_encrypted:
                raise ValueError("The original PDF is encrypted")
            if document.page_count == 0:
                raise ValueError("The original PDF contains no pages")

            # Page may vary, but the approved field must be positively recognized.
            target = None
            for page_index in range(document.page_count - 1, -1, -1):
                try:
                    image_rect, date_position = find_director_signature_field(
                        document[page_index], document_type
                    )
                    target = (page_index, image_rect, date_position)
                    break
                except SignatureFieldNotFound:
                    continue

            if target is None:
                raise SignatureFieldNotFound(
                    "This PDF has no recognized Director signature field. "
                    "Nothing was signed. Review the form template before retrying."
                )

            page_index, image_rect, date_position = target
            place_signature(
                document[page_index], signature_path, approval_date,
                image_rect, date_position,
            )
            document.save(str(output_path), garbage=4, deflate=True)
        finally:
            document.close()

        # Existing storage_service.upload_file uses upsert=False. Never replace
        # an earlier signed PDF, even after an accidental approval retry.
        upload_file(SIGNED_BUCKET, signed_key, output_path, content_type="application/pdf")
        logger.info("Signed PDF uploaded for document %s", document_id)
        return signed_key
