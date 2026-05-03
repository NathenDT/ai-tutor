import asyncio
import base64
import binascii
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    File,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from google.genai import types
from gemini_live import GeminiLive
from safegaurd import SafeGaurd
from streaks import StreakService
from tutor_agent import (
    CoursePassage,
    TutorCurriculumSession,
    curriculum_to_dict,
    curriculum_to_hidden_context,
    normalize_course_search_results,
)
from twilio_handler import TwilioHandler

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Configure logging - DEBUG for our modules, INFO for everything else
logging.basicConfig(level=logging.INFO)
logging.getLogger("gemini_live").setLevel(logging.DEBUG)
logging.getLogger(__name__).setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_auth_database()
    streak_service.initialize()
    yield

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("MODEL", "gemini-3.1-flash-live-preview")
DEFAULT_PORT = 8001

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
streak_service = StreakService(AUTH_DATABASE_PATH)
safegaurd = SafeGaurd()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "").strip()
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ai-tutor-content").strip()
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws").strip()
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1").strip()
PINECONE_EMBED_MODEL = os.getenv("PINECONE_EMBED_MODEL", "llama-text-embed-v2").strip()
PINECONE_TEXT_FIELD = os.getenv("PINECONE_TEXT_FIELD", "text").strip() or "text"
COURSE_SEARCH_TOP_K = int(os.getenv("COURSE_SEARCH_TOP_K", "6"))
CONTENT_UPLOAD_DIR_VALUE = os.getenv("CONTENT_UPLOAD_DIR", "data/uploads")
CONTENT_UPLOAD_DIR = Path(CONTENT_UPLOAD_DIR_VALUE).expanduser()
if not CONTENT_UPLOAD_DIR.is_absolute():
    CONTENT_UPLOAD_DIR = BASE_DIR / CONTENT_UPLOAD_DIR
CONTENT_MAX_UPLOAD_MB = int(os.getenv("CONTENT_MAX_UPLOAD_MB", "25"))
CONTENT_MAX_UPLOAD_BYTES = CONTENT_MAX_UPLOAD_MB * 1024 * 1024
CONTENT_CHUNK_WORDS = 450
CONTENT_CHUNK_OVERLAP_WORDS = 50
PINECONE_UPSERT_BATCH_SIZE = 96
CONTENT_METADATA_SUFFIX = ".json"

CURRICULUM_PROGRESS_TOOL_NAME = "mark_curriculum_step_complete"

# Twilio config (optional — only needed for phone call integration)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_APP_HOST = os.getenv("TWILIO_APP_HOST")

# Initialize FastAPI
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")


@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "frontend" / "index.html")


@app.get("/tutor")
async def tutor(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(BASE_DIR / "frontend" / "tutor.html")


@app.get("/home")
async def home(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(BASE_DIR / "frontend" / "home.html")

@app.get("/settings")
async def settings(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(BASE_DIR / "frontend" / "settings.html")


@app.get("/upload-content")
async def upload_content_page(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(BASE_DIR / "frontend" / "upload-content.html")


@app.get("/settings")
async def settings_page(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(BASE_DIR / "frontend" / "settings.html")


@app.get("/create-user")
async def create_user_page(request: Request):
    if authenticated_request(request):
        return RedirectResponse(url="/home", status_code=303)
    return FileResponse(BASE_DIR / "frontend" / "create-user.html")


@app.post("/api/content/upload-pdf")
async def upload_pdf_content(request: Request, file: UploadFile = File(...)):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    if not PINECONE_API_KEY:
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
    if len(content) > CONTENT_MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"error": f"PDF uploads are limited to {CONTENT_MAX_UPLOAD_MB} MB."},
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
        "indexName": PINECONE_INDEX_NAME,
    }


@app.get("/api/content")
async def list_uploaded_content(request: Request):
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    return {"items": list_content_items(username)}


@app.delete("/api/content/{document_id}")
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
    if PINECONE_API_KEY:
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


def pinecone_namespace_not_found(error):
    error_text = str(error).lower()
    return "namespace not found" in error_text


@app.get("/auth/me")
async def auth_me(request: Request):
    return {"authenticated": authenticated_request(request)}


@app.get("/api/streak")
async def get_current_streak(request: Request):
    username = get_request_username(request)
    if not username:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)
    return streak_service.get_streak(username)


@app.post("/auth/login")
async def auth_login(request: Request):
    initialize_auth_database()

    try:
        credentials = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid login request."}, status_code=400)

    if not isinstance(credentials, dict):
        return JSONResponse({"error": "Invalid login request."}, status_code=400)

    username = str(credentials.get("username", "")).strip()
    password = str(credentials.get("password", ""))

    user = get_user(username)
    if not user or not verify_password(password, user["password_hash"]):
        return JSONResponse({"error": "Invalid username or password."}, status_code=401)

    streak = streak_service.record_login(username)
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_session_token(username),
        httponly=True,
        max_age=AUTH_SESSION_MAX_AGE_SECONDS,
        path="/",
        samesite="lax",
    )
    response.headers["X-Current-Streak"] = str(streak["current_streak"])
    return response


@app.post("/auth/register")
async def auth_register(request: Request):
    initialize_auth_database()

    try:
        credentials = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid create user request."}, status_code=400)

    if not isinstance(credentials, dict):
        return JSONResponse({"error": "Invalid create user request."}, status_code=400)

    username = str(credentials.get("username", "")).strip()
    password = str(credentials.get("password", ""))

    validation_error = validate_new_user(username, password)
    if validation_error:
        return JSONResponse({"error": validation_error}, status_code=400)

    try:
        create_user(username, password)
    except sqlite3.IntegrityError:
        return JSONResponse({"error": "That username is already taken."}, status_code=409)

    streak = streak_service.record_login(username)
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_session_token(username),
        httponly=True,
        max_age=AUTH_SESSION_MAX_AGE_SECONDS,
        path="/",
        samesite="lax",
    )
    response.headers["X-Current-Streak"] = str(streak["current_streak"])
    return response


@app.post("/auth/logout")
async def auth_logout():
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")
    return response


def get_db_connection():
    connection = sqlite3.connect(AUTH_DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_auth_database():
    AUTH_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count == 0 and AUTH_BOOTSTRAP_USERNAME and AUTH_BOOTSTRAP_PASSWORD:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    AUTH_BOOTSTRAP_USERNAME,
                    hash_password(AUTH_BOOTSTRAP_PASSWORD),
                    int(time.time()),
                ),
            )
            logger.info(
                "Created initial local auth user '%s' in %s",
                AUTH_BOOTSTRAP_USERNAME,
                AUTH_DATABASE_PATH,
            )
        connection.commit()


def hash_password(password):
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}$"
        f"{salt.hex()}${password_hash.hex()}"
    )


def verify_password(password, password_hash):
    try:
        algorithm, iterations_text, salt_hex, hash_hex = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
    except (ValueError, binascii.Error):
        return False

    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_hash, expected_hash)


def validate_new_user(username, password):
    if len(username) < 3:
        return "Username must be at least 3 characters."
    if len(username) > 40:
        return "Username must be 40 characters or fewer."
    if not username.replace("_", "").replace("-", "").isalnum():
        return "Username can only use letters, numbers, hyphens, and underscores."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    return ""


def create_user(username, password):
    initialize_auth_database()
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (username, password_hash, created_at)
            VALUES (?, ?, ?)
            """,
            (username, hash_password(password), int(time.time())),
        )
        connection.commit()


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


def extract_pdf_pages(content):
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "PDF extraction dependency is missing. Install requirements.txt, including pypdf."
        ) from error

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as error:
        raise RuntimeError("Could not read the uploaded PDF.") from error

    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            logger.warning("Could not extract text from PDF page %s", page_number)
            text = ""

        normalized_text = normalize_extracted_text(text)
        if normalized_text:
            pages.append({"page_number": page_number, "text": normalized_text})

    return pages


def normalize_extracted_text(text):
    return re.sub(r"\s+", " ", text).strip()


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
                    PINECONE_TEXT_FIELD: chunk_text_value,
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
        end = min(start + CONTENT_CHUNK_WORDS, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(end - CONTENT_CHUNK_OVERLAP_WORDS, start + 1)
    return chunks


def upsert_records_to_pinecone(records, namespace):
    try:
        from pinecone import Pinecone
    except ImportError as error:
        raise RuntimeError(
            "Pinecone dependency is missing. Install requirements.txt, including pinecone."
        ) from error

    pc = Pinecone(api_key=PINECONE_API_KEY)
    ensure_pinecone_index(pc)
    index = pc.Index(PINECONE_INDEX_NAME)

    for start in range(0, len(records), PINECONE_UPSERT_BATCH_SIZE):
        batch = records[start : start + PINECONE_UPSERT_BATCH_SIZE]
        index.upsert_records(namespace=namespace, records=batch)


def delete_document_from_pinecone(document_id, namespace):
    try:
        from pinecone import Pinecone
    except ImportError as error:
        raise RuntimeError(
            "Pinecone dependency is missing. Install requirements.txt, including pinecone."
        ) from error

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    index.delete(namespace=namespace, filter={"document_id": {"$eq": document_id}})


def ensure_pinecone_index(pc):
    if not pc.has_index(PINECONE_INDEX_NAME):
        pc.create_index_for_model(
            name=PINECONE_INDEX_NAME,
            cloud=PINECONE_CLOUD,
            region=PINECONE_REGION,
            embed={
                "model": PINECONE_EMBED_MODEL,
                "metric": "cosine",
                "field_map": {"text": PINECONE_TEXT_FIELD},
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
        description = pc.describe_index(PINECONE_INDEX_NAME)
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
        f"Pinecone index '{PINECONE_INDEX_NAME}' was not ready after waiting."
    )


def search_uploaded_course_passages(
    topic: str,
    namespace: str,
    top_k: int = COURSE_SEARCH_TOP_K,
) -> list[CoursePassage]:
    if not PINECONE_API_KEY:
        raise RuntimeError(
            "PINECONE_API_KEY is not set. Upload and course search require Pinecone."
        )

    normalized_topic = normalize_extracted_text(topic)
    if not normalized_topic:
        raise ValueError("A learning topic is required before connecting.")

    try:
        from pinecone import Pinecone, SearchQuery
    except ImportError as error:
        raise RuntimeError(
            "Pinecone dependency is missing. Install requirements.txt, including pinecone."
        ) from error

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    search_response = index.search_records(
        namespace=namespace,
        query=SearchQuery(inputs={"text": normalized_topic}, top_k=top_k),
        fields=[PINECONE_TEXT_FIELD, "filename", "page_number", "document_id"],
    )
    return normalize_course_search_results(search_response, PINECONE_TEXT_FIELD)


def get_user(username):
    if not username:
        return None

    initialize_auth_database()
    with get_db_connection() as connection:
        return connection.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()


def get_or_create_session_secret():
    if AUTH_SESSION_SECRET:
        return AUTH_SESSION_SECRET

    initialize_auth_database()
    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT value FROM auth_settings WHERE key = ?",
            ("session_secret",),
        ).fetchone()
        if row:
            return row["value"]

        session_secret = secrets.token_urlsafe(48)
        connection.execute(
            "INSERT INTO auth_settings (key, value) VALUES (?, ?)",
            ("session_secret", session_secret),
        )
        connection.commit()
        return session_secret


def create_session_token(username):
    expires_at = int(time.time()) + AUTH_SESSION_MAX_AGE_SECONDS
    payload = f"{username}:{expires_at}"
    encoded_payload = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")
    encoded_payload = encoded_payload.rstrip("=")
    signature = sign_session_payload(payload)
    return f"{encoded_payload}.{signature}"


def sign_session_payload(payload):
    return hmac.new(
        get_or_create_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def get_authenticated_user(token):
    initialize_auth_database()
    if not token:
        return None

    try:
        encoded_payload, signature = token.split(".", 1)
        padding = "=" * (-len(encoded_payload) % 4)
        payload = base64.urlsafe_b64decode(encoded_payload + padding).decode("utf-8")
        expected_signature = sign_session_payload(payload)
        if not hmac.compare_digest(signature, expected_signature):
            return None

        username, expires_at_text = payload.rsplit(":", 1)
        expires_at = int(expires_at_text)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None

    if expires_at < int(time.time()):
        return None
    if not get_user(username):
        return None
    return username


def authenticated_request(request: Request):
    return get_authenticated_request_user(request) is not None


def get_authenticated_request_user(request: Request):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    return get_authenticated_user(token)


def get_request_username(request: Request):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    return get_authenticated_user(token)


def authenticated_websocket(websocket: WebSocket):
    token = websocket.cookies.get(AUTH_COOKIE_NAME)
    return get_authenticated_user(token) is not None


def get_authenticated_websocket_user(websocket: WebSocket):
    token = websocket.cookies.get(AUTH_COOKIE_NAME)
    return get_authenticated_user(token)


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


@app.websocket("/ws")
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

        completed_curriculum_steps.add(normalized_step_order)
        return {
            "ok": True,
            "step_order": normalized_step_order,
            "evidence": str(evidence or "").strip(),
            "completed_steps": sorted(completed_curriculum_steps),
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

    async def start_course_grounded_curriculum(topic, source):
        try:
            course_passages = await asyncio.to_thread(
                search_uploaded_course_passages,
                topic,
                username,
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

        if not course_passages:
            await websocket.send_json(
                {
                    "type": "error",
                    "error": (
                        "No relevant uploaded course content was found for that topic. "
                        "Upload course material first or try a topic from the uploaded PDF."
                    ),
                }
            )
            return

        try:
            curriculum = await curriculum_session.maybe_generate(topic, course_passages)
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

        if not curriculum:
            return

        await websocket.send_json(
            {
                "type": "curriculum",
                "curriculum": curriculum_to_dict(curriculum),
            }
        )
        await text_input_queue.put(curriculum_to_hidden_context(curriculum))

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
                                source="session_start",
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


# ─── Twilio Endpoints ─────────────────────────────────────────────────────────

@app.post("/twilio/inbound")
async def twilio_inbound():
    """Handles inbound Twilio calls. Returns TwiML to open a media stream."""
    host = TWILIO_APP_HOST or f"localhost:{DEFAULT_PORT}"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Connecting to Gemini Live.</Say>
    <Connect>
        <Stream url="wss://{host}/twilio/stream" />
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.post("/twilio/outbound")
async def twilio_outbound(
    to_number: str = Query(..., description="Destination phone number (E.164 format)"),
    from_number: str = Query(..., description="Your Twilio phone number (E.164 format)"),
):
    """Initiates an outbound Twilio call that connects to Gemini Live."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return {"error": "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in environment"}
    if not TWILIO_APP_HOST:
        return {"error": "TWILIO_APP_HOST must be set in environment"}

    from twilio.rest import Client as TwilioClient

    client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    twiml = f"""<Response>
    <Say>Connecting to Gemini Live.</Say>
    <Connect>
        <Stream url="wss://{TWILIO_APP_HOST}/twilio/stream" />
    </Connect>
</Response>"""

    call = client.calls.create(
        to=to_number,
        from_=from_number,
        twiml=twiml,
    )
    logger.info(f"Outbound call initiated: {call.sid}")
    return {"callSid": call.sid, "status": call.status}


@app.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket):
    """WebSocket endpoint for Twilio Media Streams."""
    await websocket.accept()
    logger.info("Twilio media stream WebSocket connected")

    if not GEMINI_API_KEY:
        await close_for_missing_gemini_key(websocket)
        return

    handler = TwilioHandler(gemini_api_key=GEMINI_API_KEY, model=MODEL)
    try:
        await handler.handle_media_stream(websocket)
    except Exception as e:
        logger.error(f"Twilio stream error: {e}", exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("Twilio media stream WebSocket closed")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", DEFAULT_PORT))
    logger.info(f"Open the tutor at http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
