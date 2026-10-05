"""Registro de tenants con caché TTL en memoria.

Cada tenant es una configuración aislada (identidad, protocolo de atención, respuestas
predeterminadas, capacidades y base de conocimiento). El origen es intercambiable:

- ``filesystem``: ``data/tenants/<tenant_id>/`` (modo demo y tests, sin credenciales).
- ``firestore``: colección ``tenants`` (modo productivo en GCP).
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class TenantNotFoundError(Exception):
    """El tenant no existe o está inactivo. Nunca se cae a otro tenant ni a uno genérico."""


@dataclass
class TenantContext:
    tenant_id: str
    identity: dict[str, Any] = field(default_factory=dict)
    protocol: dict[str, Any] = field(default_factory=dict)
    predetermined_answers: dict[str, Any] = field(default_factory=dict)
    # Autorización por tenant. Vacío = ninguna herramienta expuesta (fail-closed).
    #   {"tools": {"consultar_ticket": true}}
    capabilities: dict[str, Any] = field(default_factory=dict)
    # Nombre del File Search Store de Gemini (se crea en la ingesta, no en el request path).
    file_search_store_name: str | None = None
    # Texto de la base de conocimiento {ruta: contenido}; solo lo usa el LLM simulado.
    knowledge: dict[str, str] = field(default_factory=dict)

    def tool_enabled(self, tool_name: str) -> bool:
        tools = self.capabilities.get("tools", {}) if isinstance(self.capabilities, dict) else {}
        return tools.get(tool_name) is True


class TenantRepository(Protocol):
    async def load(self, tenant_id: str) -> TenantContext: ...


class FilesystemTenantRepository:
    def __init__(self, base_dir: str):
        self._base = Path(base_dir).resolve()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _load_sync(self, tenant_id: str) -> TenantContext:
        # Defensa en profundidad contra path traversal (el schema de la API ya valida el formato).
        if not _TENANT_ID_RE.match(tenant_id):
            raise TenantNotFoundError(f"Tenant '{tenant_id}' no existe.")
        root = (self._base / tenant_id).resolve()
        if self._base not in root.parents or not root.is_dir():
            raise TenantNotFoundError(f"Tenant '{tenant_id}' no existe.")

        meta = self._read_json(root / "tenant.json")
        if not meta.get("active", False):
            raise TenantNotFoundError(f"Tenant '{tenant_id}' está inactivo.")

        knowledge = {
            str(p.relative_to(root / "knowledge")): p.read_text(encoding="utf-8")
            for p in sorted((root / "knowledge").rglob("*"))
            if p.is_file() and p.suffix in {".md", ".txt"}
        }
        return TenantContext(
            tenant_id=tenant_id,
            identity=self._read_json(root / "identity.json"),
            protocol=self._read_json(root / "protocol.json"),
            predetermined_answers=self._read_json(root / "predetermined_answers.json"),
            capabilities=meta.get("capabilities", {}),
            file_search_store_name=meta.get("file_search_store_name"),
            knowledge=knowledge,
        )

    async def load(self, tenant_id: str) -> TenantContext:
        return await asyncio.to_thread(self._load_sync, tenant_id)


class FirestoreTenantRepository:
    """Documento ``tenants/{tenant_id}`` con los mismos campos que la variante filesystem."""

    def __init__(self, project: str):
        # Import perezoso: el modo demo no necesita las dependencias de GCP.
        from google.cloud import firestore

        self._db = firestore.AsyncClient(project=project or None)

    async def load(self, tenant_id: str) -> TenantContext:
        snapshot = await self._db.collection("tenants").document(tenant_id).get()
        if not snapshot.exists:
            raise TenantNotFoundError(f"Tenant '{tenant_id}' no existe.")
        data = snapshot.to_dict() or {}
        if not data.get("active", False):
            raise TenantNotFoundError(f"Tenant '{tenant_id}' está inactivo.")
        return TenantContext(
            tenant_id=tenant_id,
            identity=data.get("identity", {}),
            protocol=data.get("protocol", {}),
            predetermined_answers=data.get("predetermined_answers", {}),
            capabilities=data.get("capabilities", {}),
            file_search_store_name=data.get("file_search_store_name"),
        )


@lru_cache
def get_repository() -> TenantRepository:
    settings = get_settings()
    if settings.tenant_backend == "firestore":
        return FirestoreTenantRepository(settings.gcp_project)
    return FilesystemTenantRepository(settings.tenants_dir)


# tenant_id -> (instante de carga, contexto)
_cache: dict[str, "tuple[float, TenantContext]"] = {}


async def get_tenant(tenant_id: str) -> TenantContext:
    """Resuelve un tenant, cacheado en memoria con TTL (``tenant_cache_ttl_seconds``)."""
    ttl = get_settings().tenant_cache_ttl_seconds
    cached = _cache.get(tenant_id)
    if cached and (time.monotonic() - cached[0]) < ttl:
        return cached[1]

    tenant = await get_repository().load(tenant_id)
    _cache[tenant_id] = (time.monotonic(), tenant)
    # Log a propósito: "¿por qué no se activó la herramienta?" se responde en segundos.
    logger.info(
        "tenant_resolved",
        extra={"tenant_id": tenant_id, "capabilities_loaded": tenant.capabilities},
    )
    return tenant


def invalidate_tenant_cache(tenant_id: str | None = None) -> None:
    """Fuerza a releer el origen en la próxima resolución (un tenant, o todos)."""
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(tenant_id, None)
