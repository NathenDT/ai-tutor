from fastapi import WebSocket
from google.genai import types

from ..config import CURRICULUM_PROGRESS_TOOL_NAME
from .canvas_services import strip_html_tags
from .pdf_services import normalize_extracted_text


def build_curriculum_progress_tools():
    return [
        types.Tool(
            functionDeclarations=[
                types.FunctionDeclaration(
                    name=CURRICULUM_PROGRESS_TOOL_NAME,
                    description=(
                        "Mark a curriculum step complete after the student has "
                        "demonstrated understanding of that exact step."
                    ),
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "step_order": types.Schema(
                                type=types.Type.INTEGER,
                                minimum=1,
                                maximum=5,
                                description="The curriculum step number to mark complete.",
                            ),
                            "evidence": types.Schema(
                                type=types.Type.STRING,
                                description=(
                                    "A short reason the student's latest answer shows "
                                    "understanding."
                                ),
                            ),
                        },
                        required=["step_order"],
                    ),
                )
            ]
        )
    ]


async def close_for_missing_gemini_key(websocket: WebSocket):
    """Tell the browser what to fix instead of crashing the ASGI connection."""
    message = (
        "GEMINI_API_KEY is not set. Add a line like "
        "GEMINI_API_KEY=your_api_key_here to gemini-live-genai-python-sdk/.env "
        "or export it before starting the server."
    )
    logger.error(message)
    await websocket.send_json({"type": "error", "error": message})
    await websocket.close(code=1008)


def normalize_selected_assignment_payload(assignment):
    if not isinstance(assignment, dict):
        return None

    assignment_id = assignment.get("id")
    name = normalize_extracted_text(str(assignment.get("name") or ""))
    description = strip_html_tags(assignment.get("description", "") or "")
    if not assignment_id and not name and not description:
        return None

    return {
        "id": assignment_id,
        "course_id": assignment.get("course_id"),
        "name": name or f"Assignment {assignment_id}",
        "description": description,
        "due_at": assignment.get("due_at"),
        "points_possible": assignment.get("points_possible"),
        "html_url": assignment.get("html_url"),
    }


def format_selected_assignment_context(assignment):
    if not assignment:
        return ""

    lines = [
        "Selected Canvas assignment:",
        f"Name: {assignment.get('name')}",
    ]
    if assignment.get("due_at"):
        lines.append(f"Due: {assignment.get('due_at')}")
    if assignment.get("points_possible") is not None:
        lines.append(f"Points: {assignment.get('points_possible')}")
    if assignment.get("description"):
        lines.append(f"Description: {assignment.get('description')}")
    if assignment.get("html_url"):
        lines.append(f"URL: {assignment.get('html_url')}")

    return "\n".join(lines)


def build_tutor_search_topic(topic, assignment):
    parts = []
    if assignment:
        parts.append(str(assignment.get("name") or ""))
        if assignment.get("description"):
            parts.append(str(assignment.get("description")))
    if topic:
        parts.append(str(topic))

    return normalize_extracted_text(" ".join(parts))
