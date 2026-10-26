
import re
from pathlib import Path


def classify_document(filename: str) -> dict:
    """
    Accept only these filename formats, case-insensitively:

    Clearance-Month-STATECODE.pdf
    PaymentApproval-Month-STATECODE.pdf

    Example:
    Clearance-October-OY-26B-1500.pdf
    PaymentApproval-October-OY-26B-1500.pdf
    """

    original_name = Path(filename).name

    result = {
        "recognized": False,
        "document_type": None,
        "month": None,
        "state_code": None,
        "filename": original_name,
    }

    pattern = re.compile(
        r"^(Clearance|PaymentApproval)-"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)-"
        r"([A-Z]{2})-"
        r"(\d{2}[A-Z])-"
        r"(\d{3,})\.pdf$",
        re.IGNORECASE,
    )

    match = pattern.fullmatch(original_name)

    if not match:
        return result

    document_label = match.group(1).lower()
    month = match.group(2).lower()

    state_code = (
        f"{match.group(3).upper()}/"
        f"{match.group(4).upper()}/"
        f"{match.group(5)}"
    )

    result.update({
        "recognized": True,
        "document_type": (
            "clearance"
            if document_label == "clearance"
            else "payment_approval"
        ),
        "month": month,
        "state_code": state_code,
    })

    return result


if __name__ == "__main__":
    examples = [
        "Clearance-October-OY-26B-1500.pdf",
        "clearance-october-oy-26b-1500.PDF",
        "PAYMENTAPPROVAL-OCTOBER-OY-26B-1500.PDF",
        "Payment-Approval-October-OY-26B-1500.pdf",
        "clearance_october_oy-26b-1500.pdf",
    ]

    for filename in examples:
        result = classify_document(filename)
        print(f"{filename} -> {result['recognized']}")
