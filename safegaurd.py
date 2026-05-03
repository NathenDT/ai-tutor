import json
import re


EDUCATION_ONLY_MESSAGE = (
    "I can only help with education-related questions. Try asking about a "
    "class topic, homework concept, study plan, exam prep, or a skill you want "
    "to learn."
)


class SafeGaurd:
    """Filters user text before it is sent to Gemini."""

    EDUCATION_KEYWORDS = {
        "academic",
        "algebra",
        "analysis",
        "anatomy",
        "answer",
        "biology",
        "calculus",
        "chemistry",
        "class",
        "college",
        "concept",
        "course",
        "curriculum",
        "definition",
        "derivative",
        "diagram",
        "education",
        "essay",
        "exam",
        "explain",
        "formula",
        "geometry",
        "grade",
        "grammar",
        "history",
        "homework",
        "integral",
        "language",
        "learn",
        "lesson",
        "literature",
        "math",
        "midterm",
        "notes",
        "physics",
        "practice",
        "problem",
        "programming",
        "project",
        "proof",
        "quiz",
        "read",
        "research",
        "review",
        "science",
        "school",
        "solve",
        "study",
        "teach",
        "test",
        "theorem",
        "topic",
        "tutor",
        "understand",
        "university",
        "writing",
    }

    NON_EDUCATION_KEYWORDS = {
        "bet",
        "boyfriend",
        "casino",
        "celebrity gossip",
        "crypto",
        "dating",
        "gambling",
        "girlfriend",
        "gossip",
        "investment tip",
        "lottery",
        "movie",
        "party",
        "political campaign",
        "recipe",
        "relationship advice",
        "shopping",
        "song",
        "sports pick",
        "stocks",
        "stock pick",
        "travel",
        "vacation itinerary",
    }

    ALLOWED_SHORT_MESSAGES = {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "yes",
        "no",
        "ok",
        "okay",
        "continue",
        "go on",
        "next",
        "more",
    }

    def extract_text(self, raw_message):
        """Return the user text from a raw WebSocket message."""
        if not raw_message:
            return ""

        try:
            payload = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            return str(raw_message).strip()

        if isinstance(payload, dict):
            return str(payload.get("text") or payload.get("message") or "").strip()

        return str(raw_message).strip()

    def is_education_related(self, text):
        """Heuristic check for whether a user prompt belongs in the tutor app."""
        normalized = self._normalize(text)
        if not normalized:
            return False

        if normalized in self.ALLOWED_SHORT_MESSAGES:
            return True

        if self._contains_any(normalized, self.NON_EDUCATION_KEYWORDS):
            return False

        if self._contains_any(normalized, self.EDUCATION_KEYWORDS):
            return True

        # Common school-style requests without explicit subject words.
        if re.search(r"\b(how|why|what|when|where)\b.+\b(work|mean|use|find|calculate)\b", normalized):
            return True

        return False

    def validate_text(self, text):
        if self.is_education_related(text):
            return {"allowed": True, "message": ""}

        return {
            "allowed": False,
            "message": EDUCATION_ONLY_MESSAGE,
        }

    def _normalize(self, text):
        return re.sub(r"\s+", " ", str(text).strip().lower())

    def _contains_any(self, text, keywords):
        return any(keyword in text for keyword in keywords)


# Backwards-compatible alias with the standard spelling.
SafeGuard = SafeGaurd
