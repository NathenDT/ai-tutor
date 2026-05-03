from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from ..auth import authenticated_request
from ..config import FRONTEND_DIR

router = APIRouter()


@router.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "login.html")


@router.get("/tutor")
async def tutor(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(FRONTEND_DIR / "tutor.html")


@router.get("/tutor/{course_id}")
async def tutor_course(course_id: str, request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(FRONTEND_DIR / "tutor.html")


@router.get("/home")
async def home(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(FRONTEND_DIR / "home.html")


@router.get("/settings")
async def settings_page(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(FRONTEND_DIR / "settings.html")


@router.get("/store")
async def store_page(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(FRONTEND_DIR / "store-page.html")


@router.get("/farm")
async def farm_page(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(FRONTEND_DIR / "farm.html")


@router.get("/upload-content")
async def upload_content_page(request: Request):
    if not authenticated_request(request):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(FRONTEND_DIR / "upload-content.html")


@router.get("/create-user")
async def create_user_page(request: Request):
    return FileResponse(FRONTEND_DIR / "create-user.html")
