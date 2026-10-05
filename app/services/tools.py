"""Herramientas que el chatbot puede invocar (function calling) con allow-list estricta.

Principios:
- Nunca se despacha por nombre fuera de ``REGISTRY``.
- Una herramienta solo se ofrece si el tenant la habilita en ``capabilities.tools`` (fail-closed).
- Los argumentos los valida el handler, no el modelo.
- Se detecta por FORMA del mensaje (p. ej. un ticket ``TCK-123456``) y no por palabra clave,
  para saltarse el fast path cuando el usuario ya trae los datos.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.tenants import TenantContext

logger = logging.getLogger(__name__)

_TICKET_RE = re.compile(r"\bTCK-\d{6}\b")
# Un token alfanumérico de 6 caracteres tiene forma de código de verificación.
_CODE_SHAPED_RE = re.compile(r"\b[A-Z0-9]{6}\b")
_INTENT_RE = re.compile(r"\b(consultar|consulta|saber|ver|revisar|seguimiento|estado)\b.*\b(ticket|solicitud|caso)\b")

# Datos sintéticos para el modo demo (sin sistema externo).
_DEMO_TICKETS: dict[str, dict[str, Any]] = {
    "TCK-100001": {"code": "A1B2C3", "estado": "En revisión", "area": "Soporte técnico", "radicado": "2026-03-02"},
    "TCK-100002": {"code": "Z9Y8X7", "estado": "Resuelto", "area": "Facturación", "radicado": "2026-02-11"},
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    # nombre del parámetro -> descripción (todos string y obligatorios)
    params: dict[str, str]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    # ¿el mensaje (o el historial) trae la forma de datos de esta herramienta?
    matches: Callable[[str, str], bool]
    # Intención sin datos todavía -> clave de respuesta predeterminada que pide los datos.
    intent_answer_key: str | None = None


async def consultar_ticket(ticket_id: str = "", verification_code: str = "") -> dict[str, Any]:
    """Consulta el estado de un ticket. Valida los argumentos aquí, no confía en el modelo."""
    ticket_id = (ticket_id or "").strip().upper()
    verification_code = (verification_code or "").strip().upper()
    if not _TICKET_RE.fullmatch(ticket_id) or not verification_code:
        return {"status": "invalid_input", "message": "Falta el número de ticket o el código de verificación."}

    settings = get_settings()
    if settings.tickets_api_url:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                resp = await client.get(
                    f"{settings.tickets_api_url.rstrip('/')}/tickets/{ticket_id}",
                    params={"code": verification_code},
                )
            if resp.status_code == 404:
                return {"status": "not_found"}
            resp.raise_for_status()
            return {"status": "ok", **resp.json()}
        except httpx.HTTPError as exc:
            logger.warning("tickets_api_error", extra={"error": str(exc)})
            return {"status": "unavailable"}

    ticket = _DEMO_TICKETS.get(ticket_id)
    if not ticket or ticket["code"] != verification_code:
        # Misma respuesta para "no existe" y "código incorrecto": no filtra qué tickets existen.
        return {"status": "not_found"}
    return {"status": "ok", **{k: v for k, v in ticket.items() if k != "code"}}


def _ticket_matches(question: str, history: str) -> bool:
    if _TICKET_RE.search(question or ""):
        return True
    # Caso multi-turno: ticket en un mensaje anterior, código en el actual.
    return bool(history and _TICKET_RE.search(history) and _CODE_SHAPED_RE.search(question or ""))


REGISTRY: dict[str, ToolSpec] = {
    "consultar_ticket": ToolSpec(
        name="consultar_ticket",
        description=(
            "Consulta el estado de un ticket de soporte ya radicado. Úsala SOLO cuando el usuario "
            "quiera saber en qué va su caso y tengas los DOS datos: número de ticket y código de "
            "verificación. Si falta alguno, NO la llames: pídeselo al usuario."
        ),
        params={
            "ticket_id": "Número de ticket, p. ej. TCK-100001",
            "verification_code": "Código de verificación entregado al crear el ticket, p. ej. A1B2C3",
        },
        handler=consultar_ticket,
        matches=_ticket_matches,
        intent_answer_key="consultar_ticket_datos",
    ),
}

TOOL_RULES = (
    "REGLAS PARA RESPONDER CON EL RESULTADO DE LA CONSULTA:\n"
    "- Si el resultado es 'not_found': no afirmes que el ticket no existe; di que con esos datos no "
    "se encontró un registro y pide verificar número y código.\n"
    "- Si es 'unavailable' o 'invalid_input': discúlpate, indica que es un problema temporal o qué "
    "dato falta, y sugiere reintentar.\n"
    "- Si hay datos: resume estado, fecha de radicación y área, en lenguaje claro."
)


def intent_matches(question: str) -> bool:
    return bool(_INTENT_RE.search((question or "").lower()))


def enabled_tools(tenant: TenantContext) -> dict[str, ToolSpec]:
    """Allow-list efectiva para este tenant."""
    return {name: spec for name, spec in REGISTRY.items() if tenant.tool_enabled(name)}
