import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import get_authenticated_websocket_user
from ..config import GEMINI_API_KEY, MODEL, PINECONE_API_KEY
from ..database import coin_service, streak_service
from ..gemini_live import GeminiLive
from ..safegaurd import SafeGaurd
from ..services.canvas_services import (
    build_canvas_assignment_records,
    fetch_canvas_assignments,
)
from ..services.pinecone_services import (
    search_uploaded_course_passages,
    upsert_records_to_pinecone,
)
from ..services.tutor_services import (
    build_curriculum_progress_tools,
    build_tutor_search_topic,
    close_for_missing_gemini_key,
    format_selected_assignment_context,
    normalize_selected_assignment_payload,
)
from ..tutor_agent import (
    TutorCurriculumSession,
    curriculum_to_dict,
    curriculum_to_hidden_context,
)

router = APIRouter()
logger = logging.getLogger(__name__)
safegaurd = SafeGaurd()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for Gemini Live."""
    username = get_authenticated_websocket_user(websocket)
    if not username:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    logger.info("WebSocket connection accepted")

    if not GEMINI_API_KEY:
        await close_for_missing_gemini_key(websocket)
        return

    audio_input_queue = asyncio.Queue()
    video_input_queue = asyncio.Queue()
    text_input_queue = asyncio.Queue()
    curriculum_session = TutorCurriculumSession(username=username)
    completed_curriculum_steps = set()

    async def audio_output_callback(data):
        await websocket.send_bytes(data)

    async def audio_interrupt_callback():
        # The event queue handles the JSON message, but we might want to do something else here
        pass

    def mark_curriculum_step_complete(step_order, evidence=""):
        try:
            normalized_step_order = int(step_order)
        except (TypeError, ValueError):
            return {"ok": False, "error": "step_order must be an integer."}

        if normalized_step_order < 1 or normalized_step_order > 5:
            return {"ok": False, "error": "step_order must be between 1 and 5."}

        already_completed = normalized_step_order in completed_curriculum_steps
        completed_curriculum_steps.add(normalized_step_order)
        coin_award = None
        if not already_completed:
            streak = streak_service.get_streak(username)
            multiplier = max(1, int(streak["current_streak"] or 0))
            coin_award = coin_service.award_correct_answer(
                username,
                multiplier=multiplier,
            )

        return {
            "ok": True,
            "step_order": normalized_step_order,
            "evidence": str(evidence or "").strip(),
            "completed_steps": sorted(completed_curriculum_steps),
            "coin_award": coin_award,
            "already_completed": already_completed,
        }

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY,
        model=MODEL,
        input_sample_rate=16000,
        tools=build_curriculum_progress_tools(),
        tool_mapping={
            CURRICULUM_PROGRESS_TOOL_NAME: mark_curriculum_step_complete,
        },
    )

    async def start_course_grounded_curriculum(
        topic,
        canvas_url,
        canvas_token,
        source,
        namespace="",
        assignment=None,
    ):
        canvas_data = ""
        selected_assignment = normalize_selected_assignment_payload(assignment)
        assignment_context = format_selected_assignment_context(selected_assignment)
        search_topic = build_tutor_search_topic(topic, selected_assignment)
        search_namespace = str(namespace or "").strip() or username
        canvas_connected = bool(namespace or selected_assignment)
        canvas_assignments = []
        if namespace:
            canvas_data += f"Selected Canvas course namespace: {search_namespace}\n"
            if assignment_context:
                canvas_data += f"{assignment_context}\n"
        elif canvas_url and canvas_token:
            canvas_assignments = await fetch_canvas_assignments(canvas_url, canvas_token)
            if canvas_assignments:
                canvas_connected = True
                canvas_data += "Canvas assignments fetched successfully.\n"
                for course_name, assignments in canvas_assignments:
                    canvas_data += f"Course: {course_name}\nAssignments:\n"
                    for assignment in assignments:
                        canvas_data += f"- {assignment['name']}: Due {assignment.get('due_at', 'No due date')}\n"

                if PINECONE_API_KEY:
                    try:
                        records = build_canvas_assignment_records(username, canvas_assignments)
                        if records:
                            await asyncio.to_thread(
                                upsert_records_to_pinecone,
                                records,
                                username,
                            )
                    except Exception as error:
                        logger.exception("Failed to index Canvas assignments to Pinecone")
                        canvas_data += f"Canvas indexing error: {error}\n"
            else:
                canvas_data += "Invalid Canvas token or Canvas URL, or no assignments found.\n"

        try:
            course_passages = await asyncio.to_thread(
                search_uploaded_course_passages,
                search_topic or topic,
                search_namespace,
            )
        except Exception as error:
            logger.exception("Could not search uploaded course content from %s", source)
            await websocket.send_json(
                {
                    "type": "error",
                    "error": (
                        "Could not search uploaded course content: "
                        f"{type(error).__name__}: {error}"
                    ),
                }
            )
            return

        pdf_connected = bool(course_passages)
        await websocket.send_json(
            {
                "type": "connection_status",
                "pdf_connected": pdf_connected,
                "canvas_connected": canvas_connected,
            }
        )

        if pdf_connected:
            try:
                curriculum = await curriculum_session.maybe_generate(
                    search_topic or topic,
                    course_passages,
                )
            except Exception as error:
                logger.exception("Could not generate tutor curriculum from %s", source)
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": (
                            "Could not generate the LangChain mini-curriculum: "
                            f"{type(error).__name__}: {error}"
                        ),
                    }
                )
                return

            if curriculum:
                await websocket.send_json(
                    {
                        "type": "curriculum",
                        "curriculum": curriculum_to_dict(curriculum),
                    }
                )
                hidden_context = curriculum_to_hidden_context(curriculum)
            else:
                hidden_context = "Hidden tutor session context. Do not mention that this was injected.\n"
                if search_topic:
                    hidden_context += f"Student topic: {search_topic}\n"
                hidden_context += (
                    "No uploaded course material was found. Start by asking the student what assignment or topic they are working on, "
                    "and use the topic or Canvas details to guide the tutoring session."
                )
        else:
            hidden_context = "Hidden tutor session context. Do not mention that this was injected.\n"
            if search_topic:
                hidden_context += f"Student topic: {search_topic}\n"
            hidden_context += (
                "No uploaded course material was found. Start by asking the student what assignment or topic they are working on, "
                "and use the topic or Canvas details to guide the tutoring session."
            )

        if assignment_context:
            hidden_context += (
                "\n\nAssignment Focus:\n"
                f"{assignment_context}\n"
                "Ground the tutoring plan in this assignment. Use the student's "
                "custom focus as the main question when it is provided."
            )

        if canvas_connected and canvas_data:
            hidden_context += f"\n\nCanvas Data:\n{canvas_data}"

        await text_input_queue.put(hidden_context)

    async def receive_from_client():
        try:
            while True:
                message = await websocket.receive()

                if message.get("bytes"):
                    await audio_input_queue.put(message["bytes"])
                elif message.get("text"):
                    text = message["text"]
                    try:
                        payload = json.loads(text)
                        if isinstance(payload, dict) and payload.get("type") == "image":
                            logger.info(f"Received image chunk from client: {len(payload['data'])} base64 chars")
                            image_data = base64.b64decode(payload["data"])
                            await video_input_queue.put(image_data)
                            continue
                        if (
                            isinstance(payload, dict)
                            and payload.get("type") == "session_start"
                        ):
                            await start_course_grounded_curriculum(
                                str(payload.get("topic") or ""),
                                str(payload.get("canvas_url") or ""),
                                str(payload.get("canvas_token") or ""),
                                source="session_start",
                                namespace=str(payload.get("namespace") or ""),
                                assignment=payload.get("assignment"),
                            )
                            continue
                        if isinstance(payload, dict) and "text" in payload:
                            text = str(payload.get("text") or "")
                    except json.JSONDecodeError:
                        pass

                    user_text = safegaurd.extract_text(text)
                    validation = safegaurd.validate_text(user_text)
                    if not validation["allowed"]:
                        logger.info("Blocked non-education Gemini prompt: %s", user_text)
                        await websocket.send_json({
                            "type": "error",
                            "error": validation["message"],
                        })
                        continue

                    await text_input_queue.put(user_text)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error receiving from client: {e}")

    receive_task = asyncio.create_task(receive_from_client())

    async def run_session():
        async for event in gemini_client.start_session(
            audio_input_queue=audio_input_queue,
            video_input_queue=video_input_queue,
            text_input_queue=text_input_queue,
            audio_output_callback=audio_output_callback,
            audio_interrupt_callback=audio_interrupt_callback,
        ):
            if event:
                # Forward events (transcriptions, etc) to client
                await websocket.send_json(event)

    try:
        await run_session()
    except Exception as e:
        import traceback
        logger.error(f"Error in Gemini session: {type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        receive_task.cancel()
        # Ensure websocket is closed if not already
        try:
            await websocket.close()
        except:
            pass
