from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Observabilidad
    service_name: str = "multitenant-rag-chatbot"
    service_version: str = "1.0.0"
    environment: str = "dev"
    log_level: str = "INFO"

    # Backends intercambiables. "demo" no requiere credenciales ni red:
    # tenants desde el sistema de archivos + LLM simulado.
    tenant_backend: Literal["filesystem", "firestore"] = "filesystem"
    llm_backend: Literal["mock", "gemini"] = "mock"

    # Registro de tenants
    tenants_dir: str = "data/tenants"
    gcp_project: str = ""
    tenant_cache_ttl_seconds: int = 90

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Historial: se conserva el final (lo más reciente) de la conversación.
    max_history_chars: int = 4000

    # Presupuesto duro del camino con herramienta (clasificación + consulta + respuesta).
    tool_loop_budget_seconds: float = 20.0

    # API externa de tickets. Vacía = la herramienta usa datos sintéticos de demo.
    tickets_api_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
