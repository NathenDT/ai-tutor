from pathlib import Path
import os
from dotenv import load_dotenv

SRC_DIR = Path(__file__).resolve().parent
BASE_DIR = SRC_DIR.parent
FRONTEND_DIR = BASE_DIR / "frontend"

load_dotenv(BASE_DIR / ".env")

DEFAULT_PORT = 8001

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("MODEL", "gemini-3.1-flash-live-preview")

AUTH_SESSION_SECRET = os.getenv("AUTH_SESSION_SECRET", "").strip()
AUTH_DATABASE_PATH = Path(
    os.getenv("AUTH_DATABASE_PATH", BASE_DIR / "data" / "auth.db")
).expanduser()
AUTH_BOOTSTRAP_USERNAME = (
    os.getenv("AUTH_BOOTSTRAP_USERNAME") or os.getenv("AUTH_USERNAME") or ""
).strip()
AUTH_BOOTSTRAP_PASSWORD = os.getenv("AUTH_BOOTSTRAP_PASSWORD") or os.getenv("AUTH_PASSWORD") or ""
AUTH_COOKIE_NAME = "ai_tutor_session"
AUTH_SESSION_MAX_AGE_SECONDS = 60 * 60 * 12
PASSWORD_HASH_ITERATIONS = 210_000

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "").strip()
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ai-tutor-content").strip()
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws").strip()
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1").strip()
PINECONE_EMBED_MODEL = os.getenv("PINECONE_EMBED_MODEL", "llama-text-embed-v2").strip()
PINECONE_TEXT_FIELD = os.getenv("PINECONE_TEXT_FIELD", "text").strip() or "text"
COURSE_SEARCH_TOP_K = int(os.getenv("COURSE_SEARCH_TOP_K", "6"))
PINECONE_UPSERT_BATCH_SIZE = 96

CONTENT_UPLOAD_DIR_VALUE = os.getenv("CONTENT_UPLOAD_DIR", "data/uploads")
CONTENT_UPLOAD_DIR = Path(CONTENT_UPLOAD_DIR_VALUE).expanduser()
if not CONTENT_UPLOAD_DIR.is_absolute():
    CONTENT_UPLOAD_DIR = BASE_DIR / CONTENT_UPLOAD_DIR
CONTENT_MAX_UPLOAD_MB = int(os.getenv("CONTENT_MAX_UPLOAD_MB", "25"))
CONTENT_MAX_UPLOAD_BYTES = CONTENT_MAX_UPLOAD_MB * 1024 * 1024
CONTENT_CHUNK_WORDS = 450
CONTENT_CHUNK_OVERLAP_WORDS = 50
CONTENT_METADATA_SUFFIX = ".json"

CANVAS_COURSE_INDEX_STATUSES = {}
CANVAS_COURSE_INDEX_TASKS = {}

CURRICULUM_PROGRESS_TOOL_NAME = "mark_curriculum_step_complete"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_APP_HOST = os.getenv("TWILIO_APP_HOST")
