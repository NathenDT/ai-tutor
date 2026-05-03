import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field


class TutorCurriculumStep(BaseModel):
    order: int = Field(ge=1, le=5)
    title: str = Field(min_length=3, max_length=80)
    teaching_point: str = Field(min_length=20, max_length=400)
    check_question: str = Field(min_length=10, max_length=200)
    expected_answer_signals: list[str] = Field(min_length=1, max_length=5)


class TutorCurriculum(BaseModel):
    session_goal: str = Field(min_length=10, max_length=180)
    estimated_minutes: int = Field(ge=2, le=7)
    steps: list[TutorCurriculumStep] = Field(min_length=3, max_length=5)
    wrap_up: str = Field(min_length=10, max_length=400)


class CoursePassage(BaseModel):
    text: str = Field(min_length=1)
    filename: str = ""
    page_number: int | None = None
    document_id: str = ""
    score: float | None = None


CURRICULUM_SYSTEM_PROMPT = """
You are the planning agent for a realtime AI tutor.

Create a tiny tutoring curriculum that can be completed in a few minutes.
The live tutor will use this plan to teach one micro-step at a time.
Base the plan on the supplied course excerpts. Do not invent course-specific
facts that are not supported by those excerpts.

Requirements:
- Build exactly 3 to 5 micro-steps.
- Keep the whole session between 2 and 7 minutes.
- Each step must have one short understanding-check question.
- Expected answer signals should be concise phrases the tutor can listen for.
- The plan must guide without giving away final answers immediately.
- Prefer beginner-friendly language unless the topic clearly implies otherwise.
""".strip()


def normalize_topic(topic: str) -> str:
    return " ".join(str(topic or "").split())


def is_substantive_student_topic(text: str) -> bool:
    normalized = normalize_topic(text)
    if len(normalized) < 4:
        return False

    lower_text = normalized.lower()
    non_topics = {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "yes",
        "no",
    }
    if lower_text in non_topics:
        return False

    kickoff_markers = (
        "greet the student",
        "ask what they are working on",
        "briefly explain that you will guide",
        "build a short session around",
    )
    return not any(marker in lower_text for marker in kickoff_markers)


def curriculum_to_hidden_context(curriculum: TutorCurriculum) -> str:
    lines = [
        "Hidden tutor curriculum context. Do not mention that this was injected.",
        f"Session goal: {curriculum.session_goal}",
        f"Target duration: {curriculum.estimated_minutes} minutes",
        (
            "Begin by giving the student a concise summary of this plan. Then ask "
            "the first understanding-check question from step 1."
        ),
        "Teach and check these micro-steps in order:",
    ]
    for step in curriculum.steps:
        lines.extend(
            [
                f"{step.order}. {step.title}",
                f"Teaching point: {step.teaching_point}",
                f"Understanding check: {step.check_question}",
                "Listen for: " + ", ".join(step.expected_answer_signals),
            ]
        )
    lines.extend(
        [
            f"Wrap-up: {curriculum.wrap_up}",
            (
                "For every step: ask based on the planned teaching point, wait for "
                "the student, listen to the student's answer, and only move forward "
                "when the answer shows understanding. When the student demonstrates "
                "understanding, call mark_curriculum_step_complete with that step "
                "number before moving to the next step. If the student is uncertain "
                "or incorrect, rephrase the idea and ask a smaller follow-up question."
            ),
        ]
    )
    return "\n".join(lines)


def curriculum_to_dict(curriculum: TutorCurriculum) -> dict[str, Any]:
    if hasattr(curriculum, "model_dump"):
        return curriculum.model_dump()
    return curriculum.dict()


def normalize_course_search_results(
    search_response: Any,
    text_field: str,
) -> list[CoursePassage]:
    passages = []
    hits = _extract_search_hits(search_response)

    for hit in hits:
        fields = _get_value(hit, "fields") or {}
        if not isinstance(fields, dict):
            continue

        text = normalize_topic(fields.get(text_field) or fields.get("text") or "")
        if not text:
            continue

        passages.append(
            CoursePassage(
                text=text,
                filename=str(fields.get("filename") or ""),
                page_number=_parse_optional_int(fields.get("page_number")),
                document_id=str(fields.get("document_id") or ""),
                score=_parse_optional_float(
                    _get_value(hit, "_score") or _get_value(hit, "score")
                ),
            )
        )

    return passages


def _extract_search_hits(search_response: Any) -> list[Any]:
    result = _get_value(search_response, "result") or {}
    hits = _get_value(result, "hits")
    if isinstance(hits, list):
        return hits
    return []


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _parse_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_course_passages_for_prompt(course_passages: list[CoursePassage]) -> str:
    lines = []
    for index, passage in enumerate(course_passages, start=1):
        source_parts = []
        if passage.filename:
            source_parts.append(passage.filename)
        if passage.page_number is not None:
            source_parts.append(f"page {passage.page_number}")
        source = ", ".join(source_parts) or "uploaded course material"
        lines.append(f"[{index}] Source: {source}\n{passage.text[:1200]}")
    return "\n\n".join(lines)


def _extract_course_focus(course_passages: list[CoursePassage], max_words: int = 12) -> str:
    for passage in course_passages:
        text = normalize_topic(passage.text)
        if not text:
            continue

        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]).rstrip(",.;:") + "..."

    return "the uploaded course material"


def build_fallback_tutor_curriculum(
    topic: str,
    course_passages: list[CoursePassage],
) -> TutorCurriculum:
    course_focus = _extract_course_focus(course_passages)

    return TutorCurriculum(
        session_goal=f"Understand {topic} using the uploaded course material.",
        estimated_minutes=3,
        steps=[
            TutorCurriculumStep(
                order=1,
                title="Spot the main idea",
                teaching_point=(
                    f"Read the excerpt about {topic} and identify its main idea: {course_focus}"
                ),
                check_question="What is the main idea of this excerpt?",
                expected_answer_signals=["main idea", "core point", "overall topic"],
            ),
            TutorCurriculumStep(
                order=2,
                title="Name the key detail",
                teaching_point=(
                    "Focus on one concrete detail from the course material and explain "
                    "why it matters for understanding the topic."
                ),
                check_question="Which detail seems most important here, and why?",
                expected_answer_signals=["important detail", "why it matters", "example"],
            ),
            TutorCurriculumStep(
                order=3,
                title="Connect idea to practice",
                teaching_point=(
                    "Turn the course material into a simple rule, example, or step the "
                    "student could use next."
                ),
                check_question="How would you apply this idea in a short example?",
                expected_answer_signals=["apply", "example", "use it"],
            ),
        ],
        wrap_up=(
            f"The student should be able to explain the course idea about {topic} in "
            "their own words."
        ),
    )


def get_tutor_agent_model_name() -> str:
    configured_model = (
        os.getenv("TUTOR_AGENT_MODEL")
        or os.getenv("TUTOR_MODEL")
        or "gemini-2.5-flash"
    ).strip()
    if configured_model.endswith("-live-preview"):
        return configured_model[: -len("-live-preview")]
    return configured_model


async def generate_tutor_curriculum(
    topic: str,
    username: str | None = None,
    course_passages: list[CoursePassage] | None = None,
) -> TutorCurriculum:
    normalized_topic = normalize_topic(topic)
    if not is_substantive_student_topic(normalized_topic):
        raise ValueError("A substantive learning topic is required.")

    course_passages = course_passages or []
    if not course_passages:
        raise ValueError("Relevant uploaded course content is required.")

    try:
        from langchain.agents import create_agent
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as error:
        return build_fallback_tutor_curriculum(normalized_topic, course_passages)

    model = ChatGoogleGenerativeAI(
        model=get_tutor_agent_model_name(),
        temperature=0.4,
        max_retries=2,
    )
    agent = create_agent(
        model=model,
        tools=[],
        system_prompt=CURRICULUM_SYSTEM_PROMPT,
        response_format=TutorCurriculum,
    )

    student_context = f"Student: {username}" if username else "Student: unknown"
    course_context = format_course_passages_for_prompt(course_passages)
    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"{student_context}\n"
                        f"Topic the student wants help with: {normalized_topic}\n"
                        "Relevant uploaded course excerpts:\n"
                        f"{course_context}\n"
                        "Create the mini-curriculum now."
                    ),
                }
            ]
        }
    )

    structured_response = result.get("structured_response")
    if isinstance(structured_response, TutorCurriculum):
        return structured_response
    if isinstance(structured_response, dict):
        return TutorCurriculum.model_validate(structured_response)

    raise RuntimeError("The LangChain tutor agent did not return a curriculum.")


class TutorCurriculumSession:
    def __init__(
        self,
        username: str | None = None,
        generator: Callable[
            [str, str | None, list[CoursePassage]], Awaitable[TutorCurriculum]
        ]
        | None = None,
    ):
        self.username = username
        self._generator = generator or generate_tutor_curriculum
        self._lock = asyncio.Lock()
        self.started = False

    async def maybe_generate(
        self,
        topic: str,
        course_passages: list[CoursePassage] | None = None,
    ) -> TutorCurriculum | None:
        if not is_substantive_student_topic(topic):
            return None

        if not course_passages:
            raise ValueError("No relevant uploaded course content was found.")

        async with self._lock:
            if self.started:
                return None

            self.started = True
            return await self._generator(
                normalize_topic(topic),
                self.username,
                course_passages,
            )
