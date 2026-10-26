
"""Private Supabase Storage operations for UHS Director Assistant."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from supabase import Client, create_client

ORIGINAL_BUCKET = "original-pdfs"
SIGNED_BUCKET = "signed-pdfs"
ASSETS_BUCKET = "director-assets"

ALLOWED_BUCKETS = {
    ORIGINAL_BUCKET,
    SIGNED_BUCKET,
    ASSETS_BUCKET,
}


@lru_cache(maxsize=1)
def get_storage_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Supabase Storage credentials are missing. "
            "Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )

    return create_client(url, key)


def validate_object(bucket: str, object_path: str) -> str:
    if bucket not in ALLOWED_BUCKETS:
        raise ValueError("Unknown storage bucket.")

    if not object_path or not isinstance(object_path, str):
        raise ValueError("A storage object path is required.")

    parts = object_path.split("/")

    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Invalid storage object path.")

    if "\\" in object_path or "\x00" in object_path:
        raise ValueError("Invalid storage object path.")

    return object_path


def upload_file(
    bucket: str,
    object_path: str,
    local_path: str | Path,
    content_type: str = "application/pdf",
) -> str:
    """Upload a file without intentionally overwriting an existing object."""
    object_path = validate_object(bucket, object_path)
    local_path = Path(local_path)

    if not local_path.is_file():
        raise FileNotFoundError(f"Upload source not found: {local_path}")

    client = get_storage_client()

    with local_path.open("rb") as file:
        client.storage.from_(bucket).upload(
            path=object_path,
            file=file,
            file_options={
                "content-type": content_type,
                "upsert": "false",
            },
        )

    return object_path


def download_bytes(bucket: str, object_path: str) -> bytes:
    """Retrieve a private storage object on the backend."""
    object_path = validate_object(bucket, object_path)

    return get_storage_client().storage.from_(bucket).download(
        object_path
    )


def download_file(
    bucket: str,
    object_path: str,
    destination: str | Path,
) -> Path:
    """Download a private object to a local temporary file."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    data = download_bytes(bucket, object_path)

    destination.write_bytes(data)
    return destination


def delete_file(bucket: str, object_path: str) -> None:
    """Delete a storage object. Call only after authorization."""
    object_path = validate_object(bucket, object_path)

    get_storage_client().storage.from_(bucket).remove(
        [object_path]
    )
