import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Request, WebSocket

from . import config
from .config import (
    AUTH_COOKIE_NAME,
    AUTH_SESSION_MAX_AGE_SECONDS,
    PASSWORD_HASH_ITERATIONS,
)
from .database import get_db_connection, initialize_auth_database


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
    if config.AUTH_SESSION_SECRET:
        return config.AUTH_SESSION_SECRET

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
