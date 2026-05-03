import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..auth import get_authenticated_request_user
from .. import config
from ..database import get_saved_user_settings, initialize_auth_database
from ..services.canvas_services import (
    build_canvas_course_namespace,
    fetch_canvas_course_assignments,
    fetch_canvas_courses,
    index_canvas_course_modules_metadata,
    index_canvas_course_pdfs,
    load_canvas_course_context,
    make_canvas_index_status,
    validate_canvas_connection,
)
from ..services.pinecone_services import pinecone_namespace_has_records

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/canvas/validate")
async def validate_canvas_api(request: Request):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON payload."}, status_code=400)

    canvas_url = str(payload.get("canvas_url") or "").strip()
    canvas_token = str(payload.get("canvas_token") or "").strip()
    if not canvas_url or not canvas_token:
        return JSONResponse(
            {"connected": False, "message": "Canvas URL and API token are required."},
            status_code=200,
        )

    connected = await validate_canvas_connection(canvas_url, canvas_token)
    return {"connected": connected}


@router.get("/api/canvas/courses")
async def get_canvas_courses_api(request: Request):
    initialize_auth_database()
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    settings = get_saved_user_settings(username)
    if settings is None:
        return JSONResponse({"error": "User not found."}, status_code=404)

    canvas_url = str(settings.get("canvas_url") or "").strip()
    canvas_token = str(settings.get("canvas_token") or "").strip()
    if not canvas_url or not canvas_token:
        return {
            "connected": False,
            "courses": [],
            "message": "Canvas settings are missing.",
        }

    courses = await fetch_canvas_courses(canvas_url, canvas_token)
    if courses is None:
        return {
            "connected": False,
            "courses": [],
            "message": "Could not load Canvas courses.",
        }

    return {"connected": True, "courses": courses}


@router.post("/api/canvas/courses/{course_id}/index")
async def start_canvas_course_index_api(course_id: str, request: Request):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    course_context = await load_canvas_course_context(username, course_id)
    if isinstance(course_context, JSONResponse):
        return course_context

    canvas_url, canvas_token, course = course_context
    namespace = build_canvas_course_namespace(username, course)

    if not config.PINECONE_API_KEY:
        return JSONResponse(
            {"error": "PINECONE_API_KEY is not set. Canvas course indexing requires Pinecone."},
            status_code=503,
        )

    try:
        if await asyncio.to_thread(pinecone_namespace_has_records, namespace):
            status = make_canvas_index_status(
                "indexing",
                namespace,
                course,
                message="Indexing Canvas module details.",
            )
            config.CANVAS_COURSE_INDEX_STATUSES[namespace] = status
            config.CANVAS_COURSE_INDEX_TASKS[namespace] = asyncio.create_task(
                index_canvas_course_modules_metadata(
                    canvas_url,
                    canvas_token,
                    course,
                    namespace,
                    existing_content_ready=True,
                )
            )
            return status
    except Exception as error:
        logger.exception("Could not inspect Pinecone namespace %s", namespace)
        return JSONResponse(
            {"error": f"Could not inspect Pinecone namespace: {error}"},
            status_code=502,
        )

    existing_status = config.CANVAS_COURSE_INDEX_STATUSES.get(namespace)
    existing_task = config.CANVAS_COURSE_INDEX_TASKS.get(namespace)
    if existing_status and existing_status.get("status") == "indexing":
        if existing_task and not existing_task.done():
            return existing_status

    status = make_canvas_index_status(
        "indexing",
        namespace,
        course,
        message="Indexing Canvas course PDFs and module details.",
    )
    config.CANVAS_COURSE_INDEX_STATUSES[namespace] = status
    config.CANVAS_COURSE_INDEX_TASKS[namespace] = asyncio.create_task(
        index_canvas_course_pdfs(canvas_url, canvas_token, course, namespace)
    )
    return status


@router.get("/api/canvas/courses/{course_id}/index/status")
async def get_canvas_course_index_status_api(course_id: str, request: Request):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    course_context = await load_canvas_course_context(username, course_id)
    if isinstance(course_context, JSONResponse):
        return course_context

    _, _, course = course_context
    namespace = build_canvas_course_namespace(username, course)
    status = config.CANVAS_COURSE_INDEX_STATUSES.get(namespace)
    if status:
        return status

    if not config.PINECONE_API_KEY:
        return JSONResponse(
            {"error": "PINECONE_API_KEY is not set. Canvas course indexing requires Pinecone."},
            status_code=503,
        )

    try:
        if await asyncio.to_thread(pinecone_namespace_has_records, namespace):
            status = make_canvas_index_status(
                "ready",
                namespace,
                course,
                message="Course content is ready.",
            )
            config.CANVAS_COURSE_INDEX_STATUSES[namespace] = status
            return status
    except Exception as error:
        logger.exception("Could not inspect Pinecone namespace %s", namespace)
        return JSONResponse(
            {"error": f"Could not inspect Pinecone namespace: {error}"},
            status_code=502,
        )

    return make_canvas_index_status(
        "empty",
        namespace,
        course,
        message="Course has not been indexed yet.",
    )


@router.get("/api/canvas/courses/{course_id}/assignments")
async def get_canvas_course_assignments_api(course_id: str, request: Request):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    course_context = await load_canvas_course_context(username, course_id)
    if isinstance(course_context, JSONResponse):
        return course_context

    canvas_url, canvas_token, course = course_context

    try:
        assignments = await fetch_canvas_course_assignments(
            canvas_url,
            canvas_token,
            course.get("id"),
        )
    except Exception as error:
        logger.exception("Could not load Canvas assignments for course %s", course_id)
        return JSONResponse(
            {"error": f"Could not load Canvas assignments: {error}"},
            status_code=502,
        )

    return {"course": course, "assignments": assignments}
