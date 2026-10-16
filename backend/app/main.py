from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.demo import router as demo_router
from app.api.errors import install_error_handlers
from app.api.health import router as health_router
from app.api.plans import router as plans_router
from app.api.parse import router as parse_router
from app.api.upcoming import router as upcoming_router
from app.config import get_settings


def setup_cors(app: FastAPI, allowed_origins: list[str]) -> None:
    if not allowed_origins:
        return
    is_wildcard = "*" in allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=not is_wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )


settings = get_settings()

app = FastAPI(
    title="GAP-AI API",
    version="0.1.0",
)
install_error_handlers(app)
setup_cors(app, settings.allowed_origins)

app.include_router(health_router)
app.include_router(demo_router)
app.include_router(plans_router)
app.include_router(parse_router)
app.include_router(upcoming_router)
