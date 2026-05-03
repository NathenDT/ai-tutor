import logging
import sys
import types as module_types
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import auth as _auth
from . import config as _config
from . import database as _database
from .config import DEFAULT_PORT, FRONTEND_DIR
from .database import coin_service, initialize_auth_database, streak_service
from .routes import (
    auth_routes,
    canvas_routes,
    content_routes,
    pages,
    settings_routes,
    twilio_routes,
    websocket_routes,
)

# Re-export frequently used helpers for compatibility with older imports/tests.
from .auth import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .database import *  # noqa: F401,F403
from .services.canvas_services import *  # noqa: F401,F403
from .services.content_services import *  # noqa: F401,F403
from .services.pdf_services import *  # noqa: F401,F403
from .services.pinecone_services import *  # noqa: F401,F403
from .services.tutor_services import *  # noqa: F401,F403
from .services import canvas_services as _canvas_services
from .services import content_services as _content_services
from .services import pdf_services as _pdf_services
from .services import pinecone_services as _pinecone_services
from .services import tutor_services as _tutor_services

logging.basicConfig(level=logging.INFO)
logging.getLogger("gemini_live").setLevel(logging.DEBUG)
logging.getLogger(__name__).setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_auth_database()
    streak_service.initialize()
    coin_service.initialize()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

app.include_router(pages.router)
app.include_router(canvas_routes.router)
app.include_router(settings_routes.router)
app.include_router(content_routes.router)
app.include_router(auth_routes.router)
app.include_router(websocket_routes.router)
app.include_router(twilio_routes.router)


class _MainModule(module_types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for module in (
            _config,
            _auth,
            _database,
            _canvas_services,
            _content_services,
            _pdf_services,
            _pinecone_services,
            _tutor_services,
            canvas_routes,
            content_routes,
            settings_routes,
            auth_routes,
            websocket_routes,
            twilio_routes,
        ):
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _MainModule


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.getenv("PORT", DEFAULT_PORT))
    logger.info("Open the tutor at http://localhost:%s", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
