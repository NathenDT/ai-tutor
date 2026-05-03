import json
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..auth import (
    AUTH_COOKIE_NAME,
    AUTH_SESSION_MAX_AGE_SECONDS,
    authenticated_request,
    create_session_token,
    create_user,
    get_authenticated_request_user,
    get_request_username,
    get_user,
    validate_new_user,
    verify_password,
)
from ..database import coin_service, get_db_connection, initialize_auth_database, streak_service

router = APIRouter()


@router.get("/api/auth/me")
@router.get("/auth/me")
async def auth_me(request: Request):
    return {"authenticated": authenticated_request(request)}


@router.get("/api/streak")
async def get_current_streak(request: Request):
    username = get_request_username(request)
    if not username:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)
    return streak_service.get_streak(username)


@router.get("/api/coins")
async def get_current_coins(request: Request):
    username = get_request_username(request)
    if not username:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    coins = coin_service.get_balance(username)
    streak = streak_service.get_streak(username)
    coins["multiplier"] = max(1, int(streak["current_streak"] or 0))
    return coins


@router.get("/api/store")
async def get_store_items(request: Request):
    username = get_request_username(request)
    if not username:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    return coin_service.get_store(username)


@router.post("/api/store/purchase")
async def purchase_store_item(request: Request):
    username = get_request_username(request)
    if not username:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid purchase request."}, status_code=400)

    item_id = str(payload.get("item_id") or "").strip()
    result = coin_service.purchase_store_item(username, item_id)
    if not result.get("ok"):
        return JSONResponse(
            {"error": result.get("error", "Could not purchase item."), **result},
            status_code=int(result.get("status_code") or 400),
        )

    return result


@router.post("/api/auth/login")
@router.post("/auth/login")
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


@router.post("/api/auth/register")
@router.post("/auth/register")
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


@router.post("/api/auth/logout")
@router.post("/auth/logout")
async def auth_logout():
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")
    return response
