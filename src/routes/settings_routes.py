import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..auth import get_authenticated_request_user
from ..database import get_db_connection, initialize_auth_database

router = APIRouter()


@router.get("/api/settings")
async def get_user_settings(request: Request):
    initialize_auth_database()
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    with get_db_connection() as connection:
        user_id = connection.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not user_id:
            return JSONResponse({"error": "User not found."}, status_code=404)

        settings = {}
        rows = connection.execute(
            "SELECT key, value FROM user_settings WHERE user_id = ?", (user_id[0],)
        ).fetchall()
        for row in rows:
            settings[row["key"]] = row["value"]

        return {"settings": settings}


@router.post("/api/settings")
async def save_user_settings(request: Request):
    initialize_auth_database()
    username = get_authenticated_request_user(request)
    if not username:
        return JSONResponse({"error": "Authentication required."}, status_code=401)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON payload."}, status_code=400)

    with get_db_connection() as connection:
        user_id = connection.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not user_id:
            return JSONResponse({"error": "User not found."}, status_code=404)

        for key, value in payload.items():
            if value is not None:
                connection.execute(
                    "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
                    (user_id[0], key, value),
                )
            else:
                connection.execute(
                    "DELETE FROM user_settings WHERE user_id = ? AND key = ?",
                    (user_id[0], key),
                )
        connection.commit()

    return {"message": "Settings saved successfully."}
