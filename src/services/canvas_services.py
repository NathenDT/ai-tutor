import asyncio
import html
import json
import logging
import re
from datetime import datetime, timezone

import httpx
from fastapi.responses import JSONResponse

from .. import config
from ..database import get_saved_user_settings
from .content_services import sanitize_filename
from .pdf_services import extract_pdf_pages, normalize_extracted_text
from .pinecone_services import (
    chunk_text,
    ensure_pinecone_index,
    pinecone_namespace_has_records,
    upsert_records_to_pinecone,
)

logger = logging.getLogger(__name__)


async def load_canvas_course_context(username, course_id):
    settings = get_saved_user_settings(username)
    if settings is None:
        return JSONResponse({"error": "User not found."}, status_code=404)

    canvas_url = str(settings.get("canvas_url") or "").strip()
    canvas_token = str(settings.get("canvas_token") or "").strip()
    if not canvas_url or not canvas_token:
        return JSONResponse(
            {"error": "Canvas settings are missing."},
            status_code=400,
        )

    courses = await fetch_canvas_courses(canvas_url, canvas_token)
    if courses is None:
        return JSONResponse(
            {"error": "Could not load Canvas courses."},
            status_code=502,
        )

    course = find_canvas_course(courses, course_id)
    if not course:
        return JSONResponse(
            {"error": "Canvas course was not found for this user."},
            status_code=404,
        )

    return canvas_url, canvas_token, course


def find_canvas_course(courses, course_id):
    normalized_course_id = str(course_id)
    for course in courses:
        if str(course.get("id")) == normalized_course_id:
            return course
    return None


def strip_html_tags(text):
    if not isinstance(text, str):
        return ""
    text = re.sub(r"<(br|/p|/div|/li|/h[1-6])\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return normalize_extracted_text(html.unescape(text))


def build_canvas_assignment_records(username, canvas_assignments):
    uploaded_at = datetime.now(timezone.utc).isoformat()
    records = []

    for course_name, assignments in canvas_assignments:
        for assignment in assignments:
            assignment_id = assignment.get("id")
            if assignment_id is None:
                continue

            text = "\n".join(
                filter(
                    None,
                    [
                        f"Course: {course_name}",
                        f"Assignment: {assignment.get('name', 'Unnamed assignment')}",
                        f"Due: {assignment.get('due_at', 'No due date')}",
                        f"Points: {assignment.get('points_possible', 'Unknown')}",
                        strip_html_tags(assignment.get('description', '') or ""),
                        f"URL: {assignment.get('html_url', '')}",
                    ],
                )
            )

            records.append(
                {
                    "_id": (
                        f"canvas-{assignment.get('course_id')}-{assignment_id}"
                    ),
                    config.PINECONE_TEXT_FIELD: text,
                    "document_id": f"canvas-{assignment.get('course_id')}",
                    "username": username,
                    "filename": course_name,
                    "course_id": assignment.get('course_id'),
                    "assignment_id": assignment_id,
                    "uploaded_at": uploaded_at,
                    "source": "canvas",
                }
            )

    return records


def normalize_canvas_assignment(course_id, assignment):
    description = strip_html_tags(assignment.get("description", "") or "")
    assignment_id = assignment.get("id")
    return {
        "id": assignment_id,
        "course_id": assignment.get("course_id") or course_id,
        "name": assignment.get("name") or f"Assignment {assignment_id}",
        "description": description,
        "due_at": assignment.get("due_at"),
        "points_possible": assignment.get("points_possible"),
        "html_url": assignment.get("html_url") or assignment.get("url"),
        "published": assignment.get("published"),
        "locked_for_user": assignment.get("locked_for_user"),
        "lock_at": assignment.get("lock_at"),
        "unlock_at": assignment.get("unlock_at"),
    }


def extract_canvas_detail_text(payload):
    if not isinstance(payload, dict):
        return ""

    for key in ("description", "body", "message"):
        value = strip_html_tags(payload.get(key, "") or "")
        if value:
            return value

    return ""


def build_canvas_module_item_records(course, modules):
    uploaded_at = datetime.now(timezone.utc).isoformat()
    course_id = course.get("id")
    records = []

    for module in modules:
        module_id = module.get("id")
        module_name = module.get("name") or f"Module {module_id}"
        for item in module.get("items") or []:
            item_id = item.get("id") or item.get("content_id") or item.get("position")
            if item_id is None:
                continue

            item_title = item.get("title") or f"Module item {item_id}"
            item_type = item.get("type") or "ModuleItem"
            description = extract_canvas_detail_text(item.get("details") or {})
            if not description:
                description = strip_html_tags(item.get("description", "") or "")

            text = "\n".join(
                filter(
                    None,
                    [
                        f"Course: {course.get('name') or f'Course {course_id}'}",
                        f"Module: {module_name}",
                        f"Item: {item_title}",
                        f"Type: {item_type}",
                        f"Description: {description}" if description else "",
                        f"URL: {item.get('html_url') or item.get('url') or ''}",
                    ],
                )
            )
            text = normalize_extracted_text(text)
            if not text:
                continue

            records.append(
                {
                    "_id": f"canvas-{course_id}-module-{module_id}-item-{item_id}",
                    config.PINECONE_TEXT_FIELD: text,
                    "document_id": f"canvas-{course_id}-module-{module_id}",
                    "source": "canvas",
                    "canvas_record_type": "module_item",
                    "course_id": course_id,
                    "course_name": course.get("name") or f"Course {course_id}",
                    "course_code": course.get("course_code"),
                    "module_id": module_id,
                    "module_name": module_name,
                    "module_position": module.get("position"),
                    "module_published": module.get("published"),
                    "module_item_id": item_id,
                    "module_item_title": item_title,
                    "module_item_type": item_type,
                    "module_item_position": item.get("position"),
                    "module_item_content_id": item.get("content_id"),
                    "module_item_published": item.get("published"),
                    "module_item_locked_for_user": item.get("locked_for_user"),
                    "module_item_url": item.get("url"),
                    "module_item_html_url": item.get("html_url"),
                    "uploaded_at": uploaded_at,
                }
            )

    return records


def slugify_canvas_namespace_part(value):
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "course"


def build_canvas_course_namespace(username, course):
    course_id = str(course.get("id") or "").strip()
    username_slug = slugify_canvas_namespace_part(username)
    course_id_slug = slugify_canvas_namespace_part(course_id)
    return f"{username_slug}-{course_id_slug}"


def make_canvas_index_status(
    status,
    namespace,
    course,
    indexed_file_count=0,
    chunk_count=0,
    module_item_count=0,
    message="",
):
    return {
        "status": status,
        "namespace": namespace,
        "course": course,
        "indexedFileCount": indexed_file_count,
        "chunkCount": chunk_count,
        "moduleItemCount": module_item_count,
        "message": message,
    }


def is_canvas_pdf_file(file_item):
    content_type = (
        file_item.get("content-type")
        or file_item.get("content_type")
        or ""
    ).lower()
    filename = (
        file_item.get("display_name")
        or file_item.get("filename")
        or ""
    ).lower()
    return content_type == "application/pdf" or filename.endswith(".pdf")


def build_canvas_course_pdf_records(course, file_item, pages):
    uploaded_at = datetime.now(timezone.utc).isoformat()
    course_id = course.get("id")
    file_id = file_item.get("id")
    filename = file_item.get("display_name") or file_item.get("filename") or f"file-{file_id}.pdf"
    document_id = f"canvas-{course_id}-{file_id}"
    records = []

    for page in pages:
        chunks = chunk_text(page["text"])
        for chunk_index, chunk_text_value in enumerate(chunks):
            records.append(
                {
                    "_id": (
                        f"canvas-{course_id}-{file_id}"
                        f"-p{page['page_number']}-c{chunk_index}"
                    ),
                    config.PINECONE_TEXT_FIELD: chunk_text_value,
                    "document_id": document_id,
                    "source": "canvas",
                    "course_id": course_id,
                    "course_name": course.get("name") or f"Course {course_id}",
                    "course_code": course.get("course_code"),
                    "canvas_file_id": file_id,
                    "filename": filename,
                    "page_number": page["page_number"],
                    "chunk_index": chunk_index,
                    "uploaded_at": uploaded_at,
                }
            )

    return records


async def fetch_canvas_assignments(canvas_url, canvas_token):
    if not canvas_url or not canvas_token:
        return []

    try:
        async def get_json(client, url, params=None):
            response = await client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                return None
            return response.json()

        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {"Authorization": f"Bearer {canvas_token}"}
            user_response = await client.get(f"{canvas_url}/api/v1/users/self", headers=headers)
            if user_response.status_code != 200:
                return []

            courses = await get_json(
                client,
                f"{canvas_url}/api/v1/courses",
                params={"enrollment_state": "active", "per_page": 50},
            )
            if not courses:
                return []

            canvas_data = []
            for course in courses:
                course_id = course.get("id")
                course_name = course.get("name") or f"Course {course_id}"
                assignments = await get_json(
                    client,
                    f"{canvas_url}/api/v1/courses/{course_id}/assignments",
                    params={"per_page": 100},
                )
                if assignments:
                    for assignment in assignments:
                        assignment["course_id"] = course_id
                    canvas_data.append((course_name, assignments))

            return canvas_data
    except Exception:
        logger.exception("Error fetching Canvas assignments")
        return []


def normalize_canvas_course(course):
    course_id = course.get("id")
    return {
        "id": course_id,
        "name": course.get("name") or f"Course {course_id}",
        "course_code": course.get("course_code"),
        "workflow_state": course.get("workflow_state"),
        "start_at": course.get("start_at"),
        "end_at": course.get("end_at"),
    }


async def fetch_canvas_courses(canvas_url, canvas_token):
    if not canvas_url or not canvas_token:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {"Authorization": f"Bearer {canvas_token}"}
            next_url = f"{canvas_url.rstrip('/')}/api/v1/courses"
            params = {"enrollment_state": "active", "per_page": 100}
            courses = []

            while next_url:
                response = await client.get(next_url, headers=headers, params=params)
                if response.status_code != 200:
                    return None

                page = response.json()
                if not isinstance(page, list):
                    return None

                courses.extend(normalize_canvas_course(course) for course in page)
                next_url = response.links.get("next", {}).get("url")
                params = None

            return courses
    except Exception:
        logger.exception("Error fetching Canvas courses")
        return None


async def fetch_canvas_course_pdf_files(canvas_url, canvas_token, course_id):
    if not canvas_url or not canvas_token:
        return []

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {canvas_token}"}
        next_url = f"{canvas_url.rstrip('/')}/api/v1/courses/{course_id}/files"
        params = {
            "content_types[]": "application/pdf",
            "per_page": 100,
        }
        files = []

        while next_url:
            response = await client.get(next_url, headers=headers, params=params)
            if response.status_code != 200:
                raise RuntimeError("Could not load Canvas course files.")

            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError("Canvas returned an invalid course files response.")

            files.extend(file_item for file_item in page if is_canvas_pdf_file(file_item))
            next_url = response.links.get("next", {}).get("url")
            params = None

        return files


async def fetch_canvas_module_item_details(client, headers, canvas_url, course_id, item):
    item_type = str(item.get("type") or "").lower()
    content_id = item.get("content_id")
    detail_url = item.get("url")

    if not detail_url and item_type == "assignment" and content_id:
        detail_url = (
            f"{canvas_url.rstrip('/')}/api/v1/courses/{course_id}"
            f"/assignments/{content_id}"
        )

    if not detail_url:
        return {}

    response = await client.get(detail_url, headers=headers)
    if response.status_code != 200:
        return {}

    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def fetch_canvas_course_modules(canvas_url, canvas_token, course_id):
    if not canvas_url or not canvas_token:
        return []

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {canvas_token}"}
        next_url = f"{canvas_url.rstrip('/')}/api/v1/courses/{course_id}/modules"
        params = {
            "include[]": "items",
            "per_page": 100,
        }
        modules = []

        while next_url:
            response = await client.get(next_url, headers=headers, params=params)
            if response.status_code != 200:
                raise RuntimeError("Could not load Canvas course modules.")

            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError("Canvas returned an invalid course modules response.")

            modules.extend(page)
            next_url = response.links.get("next", {}).get("url")
            params = None

        for module in modules:
            enriched_items = []
            for item in module.get("items") or []:
                enriched_item = dict(item)
                try:
                    details = await fetch_canvas_module_item_details(
                        client,
                        headers,
                        canvas_url,
                        course_id,
                        enriched_item,
                    )
                except Exception:
                    logger.warning(
                        "Could not load Canvas module item details for item %s",
                        item.get("id"),
                    )
                    details = {}
                if details:
                    enriched_item["details"] = details
                    enriched_item.setdefault("html_url", details.get("html_url"))
                    enriched_item.setdefault("published", details.get("published"))
                    enriched_item.setdefault(
                        "locked_for_user",
                        details.get("locked_for_user"),
                    )
                enriched_items.append(enriched_item)
            module["items"] = enriched_items

        return modules


async def fetch_canvas_course_assignments(canvas_url, canvas_token, course_id):
    if not canvas_url or not canvas_token:
        return []

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {canvas_token}"}
        next_url = f"{canvas_url.rstrip('/')}/api/v1/courses/{course_id}/assignments"
        params = {"per_page": 100}
        assignments = []

        while next_url:
            response = await client.get(next_url, headers=headers, params=params)
            if response.status_code != 200:
                raise RuntimeError("Could not load Canvas course assignments.")

            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError(
                    "Canvas returned an invalid course assignments response."
                )

            assignments.extend(
                normalize_canvas_assignment(course_id, assignment)
                for assignment in page
            )
            next_url = response.links.get("next", {}).get("url")
            params = None

        return assignments


async def download_canvas_pdf(canvas_url, canvas_token, course_id, file_item):
    file_id = file_item.get("id")
    download_url = file_item.get("url")
    if not download_url:
        download_url = f"{canvas_url.rstrip('/')}/courses/{course_id}/files/{file_id}/download"

    headers = {"Authorization": f"Bearer {canvas_token}"}
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(download_url, headers=headers)
        if response.status_code != 200:
            filename = file_item.get("display_name") or file_item.get("filename") or file_id
            raise RuntimeError(f"Could not download Canvas PDF {filename}.")
        if not response.content:
            filename = file_item.get("display_name") or file_item.get("filename") or file_id
            raise RuntimeError(f"Canvas PDF {filename} was empty.")
        return response.content


async def index_canvas_course_modules_metadata(
    canvas_url,
    canvas_token,
    course,
    namespace,
    existing_content_ready=False,
):
    module_item_count = 0

    try:
        modules = await fetch_canvas_course_modules(
            canvas_url,
            canvas_token,
            course.get("id"),
        )
        module_records = build_canvas_module_item_records(course, modules)
        if module_records:
            await asyncio.to_thread(upsert_records_to_pinecone, module_records, namespace)
            module_item_count = len(module_records)

        final_status = "ready" if existing_content_ready or module_item_count else "empty"
        final_message = (
            "Course content is ready."
            if final_status == "ready"
            else "No Canvas module details were found for this course."
        )
        config.CANVAS_COURSE_INDEX_STATUSES[namespace] = make_canvas_index_status(
            final_status,
            namespace,
            course,
            module_item_count=module_item_count,
            message=final_message,
        )
    except Exception as error:
        logger.exception("Canvas module metadata indexing failed for namespace %s", namespace)
        if existing_content_ready:
            config.CANVAS_COURSE_INDEX_STATUSES[namespace] = make_canvas_index_status(
                "ready",
                namespace,
                course,
                message=(
                    "Course content is ready, but Canvas module details could not "
                    f"be indexed: {error}"
                ),
            )
            return

        config.CANVAS_COURSE_INDEX_STATUSES[namespace] = make_canvas_index_status(
            "failed",
            namespace,
            course,
            message=f"Canvas module indexing failed: {error}",
        )


async def index_canvas_course_pdfs(canvas_url, canvas_token, course, namespace):
    indexed_file_count = 0
    chunk_count = 0
    module_item_count = 0

    try:
        pdf_files = await fetch_canvas_course_pdf_files(
            canvas_url,
            canvas_token,
            course.get("id"),
        )
        for file_item in pdf_files:
            content = await download_canvas_pdf(
                canvas_url,
                canvas_token,
                course.get("id"),
                file_item,
            )
            pages = extract_pdf_pages(content)
            records = build_canvas_course_pdf_records(course, file_item, pages)
            if not records:
                continue

            await asyncio.to_thread(upsert_records_to_pinecone, records, namespace)
            indexed_file_count += 1
            chunk_count += len(records)

            config.CANVAS_COURSE_INDEX_STATUSES[namespace] = make_canvas_index_status(
                "indexing",
                namespace,
                course,
                indexed_file_count=indexed_file_count,
                chunk_count=chunk_count,
                module_item_count=module_item_count,
                message="Indexing Canvas course PDFs and module details.",
            )

        modules = await fetch_canvas_course_modules(
            canvas_url,
            canvas_token,
            course.get("id"),
        )
        module_records = build_canvas_module_item_records(course, modules)
        if module_records:
            await asyncio.to_thread(upsert_records_to_pinecone, module_records, namespace)
            module_item_count = len(module_records)

            config.CANVAS_COURSE_INDEX_STATUSES[namespace] = make_canvas_index_status(
                "indexing",
                namespace,
                course,
                indexed_file_count=indexed_file_count,
                chunk_count=chunk_count,
                module_item_count=module_item_count,
                message="Indexing Canvas course PDFs and module details.",
            )

        final_status = "ready" if chunk_count or module_item_count else "empty"
        final_message = (
            "Course content is ready."
            if chunk_count or module_item_count
            else "No extractable text or Canvas module details were found for this course."
        )
        config.CANVAS_COURSE_INDEX_STATUSES[namespace] = make_canvas_index_status(
            final_status,
            namespace,
            course,
            indexed_file_count=indexed_file_count,
            chunk_count=chunk_count,
            module_item_count=module_item_count,
            message=final_message,
        )
    except Exception as error:
        logger.exception("Canvas course indexing failed for namespace %s", namespace)
        config.CANVAS_COURSE_INDEX_STATUSES[namespace] = make_canvas_index_status(
            "failed",
            namespace,
            course,
            indexed_file_count=indexed_file_count,
            chunk_count=chunk_count,
            module_item_count=module_item_count,
            message=f"Canvas course indexing failed: {error}",
        )


async def validate_canvas_connection(canvas_url, canvas_token):
    if not canvas_url or not canvas_token:
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {"Authorization": f"Bearer {canvas_token}"}
            response = await client.get(f"{canvas_url}/api/v1/users/self", headers=headers)
            return response.status_code == 200
    except Exception:
        logger.exception("Error validating Canvas connection")
        return False
