import json
import time
from datetime import datetime, timezone

from .. import config
from .pdf_services import normalize_extracted_text
from ..tutor_agent import CoursePassage, normalize_course_search_results


def pinecone_namespace_not_found(error):
    error_text = str(error).lower()
    return "namespace not found" in error_text


def build_pinecone_records(document_id, filename, username, saved_path, pages):
    uploaded_at = datetime.now(timezone.utc).isoformat()
    records = []

    for page in pages:
        chunks = chunk_text(page["text"])
        for chunk_index, chunk_text_value in enumerate(chunks):
            records.append(
                {
                    "_id": (
                        f"{document_id}-p{page['page_number']}"
                        f"-c{chunk_index}"
                    ),
                    config.PINECONE_TEXT_FIELD: chunk_text_value,
                    "document_id": document_id,
                    "username": username,
                    "filename": filename,
                    "page_number": page["page_number"],
                    "chunk_index": chunk_index,
                    "uploaded_at": uploaded_at,
                    "local_path": str(saved_path),
                }
            )

    return records


def chunk_text(text):
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + config.CONTENT_CHUNK_WORDS, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(end - config.CONTENT_CHUNK_OVERLAP_WORDS, start + 1)
    return chunks


def sanitize_pinecone_record(record):
    sanitized = {}
    for key, value in record.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
            continue
        if isinstance(value, list):
            list_value = [str(item) for item in value if item is not None]
            if list_value:
                sanitized[key] = list_value
            continue

        sanitized[key] = json.dumps(value, sort_keys=True)

    return sanitized


def upsert_records_to_pinecone(records, namespace):
    try:
        from pinecone import Pinecone
    except ImportError as error:
        raise RuntimeError(
            "Pinecone dependency is missing. Install requirements.txt, including pinecone."
        ) from error

    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    ensure_pinecone_index(pc)
    index = pc.Index(config.PINECONE_INDEX_NAME)

    for start in range(0, len(records), config.PINECONE_UPSERT_BATCH_SIZE):
        batch = [
            sanitize_pinecone_record(record)
            for record in records[start : start + config.PINECONE_UPSERT_BATCH_SIZE]
        ]
        index.upsert_records(namespace=namespace, records=batch)


def delete_document_from_pinecone(document_id, namespace):
    try:
        from pinecone import Pinecone
    except ImportError as error:
        raise RuntimeError(
            "Pinecone dependency is missing. Install requirements.txt, including pinecone."
        ) from error

    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    index = pc.Index(config.PINECONE_INDEX_NAME)
    index.delete(namespace=namespace, filter={"document_id": {"$eq": document_id}})


def pinecone_namespace_has_records(namespace):
    try:
        from pinecone import Pinecone
    except ImportError as error:
        raise RuntimeError(
            "Pinecone dependency is missing. Install requirements.txt, including pinecone."
        ) from error

    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    ensure_pinecone_index(pc)
    index = pc.Index(config.PINECONE_INDEX_NAME)
    stats = index.describe_index_stats()
    namespaces = get_pinecone_stats_namespaces(stats)
    namespace_stats = namespaces.get(namespace)
    if not namespace_stats:
        return False

    vector_count = get_pinecone_namespace_vector_count(namespace_stats)
    return vector_count > 0


def get_pinecone_stats_namespaces(stats):
    if isinstance(stats, dict):
        return stats.get("namespaces") or {}
    return getattr(stats, "namespaces", {}) or {}


def get_pinecone_namespace_vector_count(namespace_stats):
    if isinstance(namespace_stats, dict):
        return int(
            namespace_stats.get("vector_count")
            or namespace_stats.get("vectorCount")
            or 0
        )
    return int(
        getattr(namespace_stats, "vector_count", None)
        or getattr(namespace_stats, "vectorCount", None)
        or 0
    )


def ensure_pinecone_index(pc):
    if not pc.has_index(config.PINECONE_INDEX_NAME):
        pc.create_index_for_model(
            name=config.PINECONE_INDEX_NAME,
            cloud=config.PINECONE_CLOUD,
            region=config.PINECONE_REGION,
            embed={
                "model": config.PINECONE_EMBED_MODEL,
                "metric": "cosine",
                "field_map": {"text": config.PINECONE_TEXT_FIELD},
                "write_parameters": {
                    "input_type": "passage",
                    "truncate": "END",
                },
                "read_parameters": {
                    "input_type": "query",
                    "truncate": "END",
                },
            },
        )

    wait_for_pinecone_index(pc)


def wait_for_pinecone_index(pc):
    for _ in range(30):
        description = pc.describe_index(config.PINECONE_INDEX_NAME)
        status = getattr(description, "status", {}) or {}
        ready = (
            status.get("ready")
            if isinstance(status, dict)
            else getattr(status, "ready", False)
        )
        if ready:
            return
        time.sleep(2)

    raise RuntimeError(
        f"Pinecone index '{config.PINECONE_INDEX_NAME}' was not ready after waiting."
    )


def search_uploaded_course_passages(
    topic: str,
    namespace: str,
    top_k: int = config.COURSE_SEARCH_TOP_K,
) -> list[CoursePassage]:
    if not config.PINECONE_API_KEY:
        raise RuntimeError(
            "PINECONE_API_KEY is not set. Upload and course search require Pinecone."
        )

    normalized_topic = normalize_extracted_text(topic)
    if not normalized_topic:
        normalized_topic = "assignment"

    try:
        from pinecone import Pinecone, SearchQuery
    except ImportError as error:
        raise RuntimeError(
            "Pinecone dependency is missing. Install requirements.txt, including pinecone."
        ) from error

    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    index = pc.Index(config.PINECONE_INDEX_NAME)
    search_response = index.search_records(
        namespace=namespace,
        query=SearchQuery(inputs={"text": normalized_topic}, top_k=top_k),
        fields=[config.PINECONE_TEXT_FIELD, "filename", "page_number", "document_id"],
    )
    return normalize_course_search_results(search_response, config.PINECONE_TEXT_FIELD)
