"""UHS Director Assistant: approval-controlled signing using private Supabase Storage.

This module does not authorize signing. The FastAPI approval endpoint MUST verify
an authenticated Director, explicit approval, and document status before calling it.
"""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import logging

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


def rectangles_overlap(first: fitz.Rect, second: fitz.Rect) -> bool:
    intersection = first & second
    return not intersection.is_empty and intersection.width > 0 and intersection.height > 0


def find_signature_area(page: fitz.Page):
    """Find unoccupied space on the last page, preferring bottom-left."""
    rect = page.rect
    margin = 18
    width = min(190, rect.width * 0.36)
    height = 78
    if rect.width < width + 2 * margin or rect.height < height + 2 * margin:
        return None

    occupied = []
    for block in page.get_text("blocks"):
        if len(block) >= 5 and str(block[4]).strip():
            occupied.append(fitz.Rect(*block[:4]))
    for drawing in page.get_drawings():
        drawing_rect = drawing.get("rect")
        if drawing_rect is not None:
            occupied.append(fitz.Rect(drawing_rect))
    for image in page.get_images(full=True):
        for image_rect in page.get_image_rects(image[0]):
            occupied.append(fitz.Rect(image_rect))
    for annot in page.annots() or []:
        occupied.append(fitz.Rect(annot.rect))

    bottom_y = rect.y1 - margin - height
    highest_y = rect.y0 + max(margin, rect.height * 0.48)
    y = bottom_y
    while y >= highest_y:
        candidate = fitz.Rect(rect.x0 + margin, y, rect.x0 + margin + width, y + height)
        padded = fitz.Rect(candidate.x0 - 3, candidate.y0 - 3,
                           candidate.x1 + 3, candidate.y1 + 3)
        if not any(rectangles_overlap(padded, item) for item in occupied):
            return candidate
        y -= 8
    return None


def place_signature(page: fitz.Page, signature_path: Path, approval_date, signature_area: fitz.Rect):
    """Insert the original signature image without altering its pixels or colors."""
    padding = 5
    image_box = fitz.Rect(
        signature_area.x0 + padding,
        signature_area.y0 + 3,
        signature_area.x1 - padding,
        signature_area.y0 + signature_area.height - 23,
    )
    pix = fitz.Pixmap(str(signature_path))
    try:
        aspect = pix.width / pix.height
    finally:
        pix = None

    image_width = min(image_box.width, image_box.height * aspect)
    image_height = image_width / aspect
    center_x = (image_box.x0 + image_box.x1) / 2
    center_y = (image_box.y0 + image_box.y1) / 2
    actual_image_rect = fitz.Rect(
        center_x - image_width / 2,
        center_y - image_height / 2,
        center_x + image_width / 2,
        center_y + image_height / 2,
    )
    page.insert_image(
        actual_image_rect,
        filename=str(signature_path),
        keep_proportion=True,
        overlay=True,
    )

    date_text = approval_date.strftime("%d %B %Y")
    fontsize = 9
    text_width = fitz.get_text_length(date_text, fontname="helv", fontsize=fontsize)
    page.insert_text(
        fitz.Point(center_x - text_width / 2, signature_area.y1 - 8),
        date_text,
        fontsize=fontsize,
        fontname="helv",
        color=(0, 0, 0),
    )


def create_signature_page(document: fitz.Document, signature_path: Path, approval_date):
    """Add a signature page only if the form has no safe blank area."""
    page = document.new_page(width=595, height=842)
    area = fitz.Rect(18, 842 - 18 - 78, 208, 842 - 18)
    place_signature(page, signature_path, approval_date, area)


def _download_signature(destination_dir: Path) -> Path:
    """Read a signature only from the private director-assets bucket."""
    last_error = None
    for key in SIGNATURE_OBJECT_KEYS:
        destination = destination_dir / key
        try:
            download_file(ASSETS_BUCKET, key, destination)
            if not destination.is_file() or destination.stat().st_size == 0:
                raise ValueError("Signature asset is empty")
            return destination
        except Exception as exc:
            # Missing-object errors are expected when the uploaded image has
            # a different extension. Other failures must not be concealed.
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


def create_signed_pdf(original_file_path: str | Path, document_id: int) -> str:
    """Sign a stored original and return the signed PDF's Supabase object key.

    `original_file_path` is now an object key in `original-pdfs`, NOT a local path.
    The API must call this function only after explicit Director approval.
    The signed PDF is uploaded to `signed-pdfs` without overwriting an existing copy.
    """
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
        raise ValueError("document_id must be a positive integer")

    original_key = str(original_file_path)
    if not original_key or not original_key.lower().endswith(".pdf"):
        raise ValueError("The source document must be a stored PDF object key")

    signed_key = f"document_{document_id}_signed.pdf"
    approval_date = datetime.now(ZoneInfo("Africa/Lagos")).date()

    with TemporaryDirectory(prefix="uhs_signing_") as tmp:
        workdir = Path(tmp)
        original_path = workdir / "original.pdf"
        output_path = workdir / "signed.pdf"
        download_file(ORIGINAL_BUCKET, original_key, original_path)
        signature_path = _download_signature(workdir)

        if not original_path.read_bytes().startswith(b"%PDF-"):
            raise ValueError("Original storage object is not a PDF")

        document = fitz.open(str(original_path))
        try:
            if document.is_encrypted:
                raise ValueError("The original PDF is encrypted")
            if document.page_count == 0:
                raise ValueError("The original PDF contains no pages")
            final_page = document[-1]
            area = find_signature_area(final_page)
            if area is None:
                create_signature_page(document, signature_path, approval_date)
            else:
                place_signature(final_page, signature_path, approval_date, area)
            document.save(str(output_path), garbage=4, deflate=True)
        finally:
            document.close()

        # storage_service.upload_file uses upsert=false; do not replace an
        # already signed document, even if the approval endpoint is retried.
        upload_file(SIGNED_BUCKET, signed_key, output_path, content_type="application/pdf")
        logger.info("Signed PDF uploaded for document %s", document_id)
        return signed_key
