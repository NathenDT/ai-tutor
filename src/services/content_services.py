import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .pdf_services import normalize_extracted_text
from ..config import (
    CONTENT_METADATA_SUFFIX,
    CONTENT_UPLOAD_DIR,
    PINECONE_INDEX_NAME,
)


def save_uploaded_pdf(document_id, filename, content):
    CONTENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_filename = sanitize_filename(filename)
    saved_path = CONTENT_UPLOAD_DIR / f"{document_id}-{safe_filename}"
    saved_path.write_bytes(content)
    return saved_path


def valid_document_id(document_id):
    return bool(re.fullmatch(r"[a-f0-9]{32}", document_id or ""))


def get_content_metadata_path(saved_path):
    return saved_path.with_name(f"{saved_path.name}{CONTENT_METADATA_SUFFIX}")


def write_content_metadata(document_id, filename, username, saved_path, chunk_count, status):
    metadata = {
        "documentId": document_id,
        "filename": filename,
        "namespace": username,
        "savedPath": str(saved_path),
        "chunkCount": chunk_count,
        "indexName": PINECONE_INDEX_NAME,
        "status": status,
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
        "sizeBytes": saved_path.stat().st_size if saved_path.exists() else 0,
    }
    get_content_metadata_path(saved_path).write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )


def list_content_items(username):
    CONTENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    uploaded_pdfs = sorted(
        CONTENT_UPLOAD_DIR.glob("*.pdf"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for saved_path in uploaded_pdfs:
        item = build_content_item(saved_path)
        if not item:
            continue
        namespace = item.get("namespace")
        if namespace and namespace != username:
            continue
        items.append(item)
    return items


def find_content_item(document_id):
    CONTENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for saved_path in CONTENT_UPLOAD_DIR.glob(f"{document_id}-*.pdf"):
        return build_content_item(saved_path)
    return None


def build_content_item(saved_path):
    document_id = saved_path.name.split("-", 1)[0]
    if not valid_document_id(document_id):
        return None

    metadata = read_content_metadata(saved_path)
    stat = saved_path.stat()
    filename = metadata.get("filename") or saved_path.name.split("-", 1)[1]
    uploaded_at = metadata.get("uploadedAt") or datetime.fromtimestamp(
        stat.st_mtime,
        timezone.utc,
    ).isoformat()

    return {
        "documentId": document_id,
        "filename": filename,
        "savedPath": str(saved_path),
        "chunkCount": metadata.get("chunkCount"),
        "namespace": metadata.get("namespace"),
        "indexName": metadata.get("indexName") or PINECONE_INDEX_NAME,
        "status": metadata.get("status") or "local",
        "uploadedAt": uploaded_at,
        "sizeBytes": metadata.get("sizeBytes") or stat.st_size,
    }


def read_content_metadata(saved_path):
    metadata_path = get_content_metadata_path(saved_path)
    if not metadata_path.exists():
        return {}

    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read content metadata from %s", metadata_path)
        return {}


def delete_local_content_files(content_item):
    saved_path = Path(content_item["savedPath"])
    metadata_path = get_content_metadata_path(saved_path)
    for path in (saved_path, metadata_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete local content file %s", path)


def sanitize_filename(filename):
    stem = Path(filename).stem[:80] or "document"
    suffix = Path(filename).suffix.lower() or ".pdf"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")
    return f"{safe_stem or 'document'}{suffix}"
