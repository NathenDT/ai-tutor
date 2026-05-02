import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from gemini_live import GeminiLive
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


@app.get("/create-user")
async def create_user_page(request: Request):
    if authenticated_request(request):
        return RedirectResponse(url="/tutor", status_code=303)
    return FileResponse(BASE_DIR / "frontend" / "create-user.html")


@app.get("/auth/me")
async def auth_me(request: Request):
    return {"authenticated": authenticated_request(request)}


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

    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_session_token(username),
        httponly=True,
        max_age=AUTH_SESSION_MAX_AGE_SECONDS,
        path="/",
        samesite="lax",
    )
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

    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        create_session_token(username),
        httponly=True,
        max_age=AUTH_SESSION_MAX_AGE_SECONDS,
        path="/",
        samesite="lax",
    )
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
    token = request.cookies.get(AUTH_COOKIE_NAME)
    return get_authenticated_user(token) is not None


def authenticated_websocket(websocket: WebSocket):
    token = websocket.cookies.get(AUTH_COOKIE_NAME)
    return get_authenticated_user(token) is not None


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
    if not authenticated_websocket(websocket):
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

    async def audio_output_callback(data):
        await websocket.send_bytes(data)

    async def audio_interrupt_callback():
        # The event queue handles the JSON message, but we might want to do something else here
        pass

    gemini_client = GeminiLive(
        api_key=GEMINI_API_KEY, model=MODEL, input_sample_rate=16000
    )

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
                    except json.JSONDecodeError:
                        pass

                    await text_input_queue.put(text)
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
