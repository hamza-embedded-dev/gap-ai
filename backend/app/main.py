from fastapi import FastAPI

from app.api.errors import install_error_handlers
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="GAP-AI API",
    version="0.1.0",
)
install_error_handlers(app)
