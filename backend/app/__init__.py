import os
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import MAX_CONTENT_LENGTH
from app.config.settings import CORS_ORIGINS, MAX_CONTENT_LENGTH


def create_app() -> FastAPI:
    app = FastAPI(title="CognifyAI API", version="1.0.0")

    app.state.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    app.state.max_content_length = MAX_CONTENT_LENGTH

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api import register_routers
    register_routers(app)

    return app
