import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse

from ..auth import get_authenticated_request_user
from .. import config
from ..services.content_services import (
    delete_local_content_files,
    find_content_item,
    list_content_items,
    save_uploaded_pdf,
    valid_document_id,
    write_content_metadata,
)
from ..services.pdf_services import extract_pdf_pages
from ..services.pinecone_services import (
    build_pinecone_records,
    delete_document_from_pinecone,
    pinecone_namespace_not_found,
    upsert_records_to_pinecone,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/content/upload-pdf")
async def upload_pdf_content(request: Request, file: UploadFile = File(...)):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    if not config.PINECONE_API_KEY:
        return JSONResponse(
            {
                "error": (
                    "PINECONE_API_KEY is not set. Add it to .env before uploading "
                    "content to Pinecone."
                )
            },
            status_code=503,
        )

    original_filename = Path(file.filename or "").name
    if not original_filename or Path(original_filename).suffix.lower() != ".pdf":
        return JSONResponse({"error": "Upload a PDF file."}, status_code=400)

    content = await file.read()
    if not content:
        return JSONResponse({"error": "The uploaded PDF is empty."}, status_code=400)
    if len(content) > config.CONTENT_MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"error": f"PDF uploads are limited to {config.CONTENT_MAX_UPLOAD_MB} MB."},
            status_code=413,
        )

    document_id = uuid4().hex
    saved_path = save_uploaded_pdf(document_id, original_filename, content)

    try:
        pages = extract_pdf_pages(content)
    except RuntimeError as error:
        return JSONResponse(
            {
                "error": str(error),
                "documentId": document_id,
                "savedPath": str(saved_path),
            },
            status_code=400,
        )

    records = build_pinecone_records(
        document_id=document_id,
        filename=original_filename,
        username=username,
        saved_path=saved_path,
        pages=pages,
    )
    if not records:
        return JSONResponse(
            {
                "error": "No extractable text was found in the PDF.",
                "documentId": document_id,
                "savedPath": str(saved_path),
            },
            status_code=400,
        )

    write_content_metadata(
        document_id=document_id,
        filename=original_filename,
        username=username,
        saved_path=saved_path,
        chunk_count=len(records),
        status="saved",
    )

    try:
        await asyncio.to_thread(upsert_records_to_pinecone, records, username)
    except Exception as error:
        logger.exception("Pinecone upload failed for %s", saved_path)
        return JSONResponse(
            {
                "error": f"Saved PDF locally, but Pinecone upload failed: {error}",
                "documentId": document_id,
                "savedPath": str(saved_path),
                "chunkCount": len(records),
            },
            status_code=502,
        )

    write_content_metadata(
        document_id=document_id,
        filename=original_filename,
        username=username,
        saved_path=saved_path,
        chunk_count=len(records),
        status="indexed",
    )

    return {
        "filename": original_filename,
        "documentId": document_id,
        "savedPath": str(saved_path),
        "chunkCount": len(records),
        "namespace": username,
        "indexName": config.PINECONE_INDEX_NAME,
    }


@router.get("/api/content")
async def list_uploaded_content(request: Request):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    return {"items": list_content_items(username)}


@router.delete("/api/content/{document_id}")
async def delete_uploaded_content(document_id: str, request: Request):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    if not valid_document_id(document_id):
        return JSONResponse({"error": "Invalid document id."}, status_code=400)

    content_item = find_content_item(document_id)
    if not content_item:
        return JSONResponse({"error": "Content was not found."}, status_code=404)

    item_namespace = content_item.get("namespace")
    if item_namespace and item_namespace != username:
        return JSONResponse(
            {"error": "You can only delete your own content."},
            status_code=403,
        )

    pinecone_warning = ""
    if config.PINECONE_API_KEY:
        try:
            await asyncio.to_thread(
                delete_document_from_pinecone,
                document_id,
                item_namespace or username,
            )
        except Exception as error:
            if pinecone_namespace_not_found(error):
                pinecone_warning = (
                    "Pinecone namespace was not found, so only the local PDF was deleted."
                )
            else:
                logger.exception("Pinecone delete failed for document %s", document_id)
                return JSONResponse(
                    {"error": f"Could not delete content from Pinecone: {error}"},
                    status_code=502,
                )
    else:
        pinecone_warning = "PINECONE_API_KEY is not set, so only the local PDF was deleted."

    delete_local_content_files(content_item)
    response = {
        "deleted": True,
        "documentId": document_id,
    }
    if pinecone_warning:
        response["warning"] = pinecone_warning
    return response
