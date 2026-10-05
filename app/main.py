from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.middleware import CorrelationMiddleware
from app.routers import chat, health

settings = get_settings()
setup_logging(settings.log_level)

app = FastAPI(
    title="Multitenant RAG Chatbot",
    description="Chatbot multitenant con RAG, fast path de respuestas predeterminadas y herramientas.",
    version=settings.service_version,
)

app.add_middleware(CorrelationMiddleware)

app.include_router(health.router)
app.include_router(chat.router, prefix="/api/v1")
