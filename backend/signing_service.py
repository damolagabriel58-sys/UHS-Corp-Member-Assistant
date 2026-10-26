"""UHS Director Assistant: approval-controlled PDF signature placement."""
from datetime import date
from pathlib import Path
import os
import tempfile

import fitz

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DATA_DIR = PROJECT_ROOT / "Private local data"
SIGNATURE_DIR = PRIVATE_DATA_DIR / "Signature"
SIGNED_PDF_DIR = PRIVATE_DATA_DIR / "Signed PDFs"

SIGNATURE_FILES = [
    SIGNATURE_DIR / "director_signature.png",
    SIGNATURE_DIR / "director_signature.jpg",
    SIGNATURE_DIR / "director_signature.jpeg",
]


def get_signature_path() -> Path:
    for path in SIGNATURE_FILES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Director signature image not found in "
        "'Private local data/Signature/'. Name it director_signature.png, "
        "director_signature.jpg, or director_signature.jpeg."
    )


def rectangles_overlap(first: fitz.Rect, second: fitz.Rect) -> bool:
    intersection = first & second
    return not intersection.is_empty and intersection.width > 0 and intersection.height > 0


def find_signature_area(page: fitz.Page):
    """Find a genuinely clear location on the last page, preferring bottom-left.

    Never cover existing text, drawings, or embedded images. Scanned full-page
    images cannot safely be treated as empty space.
    """
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
    # Include annotations, which are not returned by text/drawing extraction.
    for annot in page.annots() or []:
        occupied.append(fitz.Rect(annot.rect))

    # Search from bottom-left upwards. Prefer the lower third of the page,
    # but allow slightly higher placement rather than adding an empty page.
    bottom_y = rect.y1 - margin - height
    highest_y = rect.y0 + max(margin, rect.height * 0.48)
    y = bottom_y
    while y >= highest_y:
        candidate = fitz.Rect(rect.x0 + margin, y, rect.x0 + margin + width, y + height)
        # Small clearance around other PDF content.
        padded = fitz.Rect(candidate.x0 - 3, candidate.y0 - 3,
                           candidate.x1 + 3, candidate.y1 + 3)
        if not any(rectangles_overlap(padded, item) for item in occupied):
            return candidate
        y -= 8
    return None


def place_signature(
    page: fitz.Page,
    signature_path: Path,
    approval_date: date,
    signature_area: fitz.Rect,
):
    """Center the original image and its date on the same vertical axis."""
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

    # Calculate the actual drawn image bounds, rather than aligning the
    # date to the wider image box (which may contain empty margins).
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
    date_x = center_x - text_width / 2
    date_baseline = signature_area.y1 - 8

    page.insert_text(
        fitz.Point(date_x, date_baseline),
        date_text,
        fontsize=fontsize,
        fontname="helv",
        color=(0, 0, 0),
    )


def create_signature_page(
    document: fitz.Document,
    signature_path: Path,
    approval_date: date,
):
    """Fallback only: add a page when no safe space exists on the form."""
    page = document.new_page(width=595, height=842)
    signature_area = fitz.Rect(18, 842 - 18 - 78, 208, 842 - 18)
    place_signature(page, signature_path, approval_date, signature_area)


def create_signed_pdf(original_file_path: str | Path, document_id: int) -> str:
    """Create a signed copy only after explicit approval in the API."""
    original_path = Path(original_file_path).resolve()
    if not original_path.is_file():
        raise FileNotFoundError(f"Original PDF not found: {original_path}")
    if original_path.suffix.lower() != ".pdf":
        raise ValueError("The source document must be a PDF.")

    signature_path = get_signature_path()
    SIGNED_PDF_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SIGNED_PDF_DIR / f"document_{document_id}_signed.pdf"

    if output_path.exists():
        raise FileExistsError(f"A signed PDF already exists for document {document_id}.")

    temporary_path = None
    document = None
    try:
        document = fitz.open(str(original_path))
        if document.is_encrypted:
            raise ValueError("The original PDF is encrypted.")
        if document.page_count == 0:
            raise ValueError("The original PDF contains no pages.")

        final_page = document[-1]
        area = find_signature_area(final_page)
        if area is None:
            create_signature_page(document, signature_path, date.today())
        else:
            place_signature(final_page, signature_path, date.today(), area)

        # Save to a unique temporary file, then atomically create the final
        # filename without overwriting a previously signed document.
        with tempfile.NamedTemporaryFile(
            prefix=f".document_{document_id}_",
            suffix=".pdf",
            dir=SIGNED_PDF_DIR,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        document.save(str(temporary_path), garbage=4, deflate=True)
        document.close()
        document = None

        os.link(str(temporary_path), str(output_path))
        return str(output_path)

    finally:
        if document is not None:
            document.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
