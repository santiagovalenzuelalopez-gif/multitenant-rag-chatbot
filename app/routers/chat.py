import asyncio
import logging

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.models.schemas import ChatRequest, ChatResponse
from app.services.fast_path import find_predetermined_answer
from app.services.llm import get_llm
from app.services.tenants import TenantNotFoundError, get_tenant
from app.services.tools import enabled_tools, intent_matches

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_TOOL_TIMEOUT_MSG = "Estoy tardando más de lo normal en consultar tu caso. Por favor intenta de nuevo en un momento."


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    """
    Orden de resolución (de más barato/determinista a más caro):

    1. Herramienta (function calling) si el tenant la habilita y el mensaje trae la forma de sus datos.
    2. Intención de usar una herramienta sin datos todavía -> respuesta que los pide.
    3. Fast path: respuesta predeterminada por palabra clave (sin LLM).
    4. RAG: el LLM responde con la base de conocimiento del tenant.
    """
    settings = get_settings()
    llm = get_llm()

    # Un tenant inexistente o inactivo corta aquí: nunca se cae a otro contexto.
    try:
        tenant = await get_tenant(payload.tenant_id)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tenant '{payload.tenant_id}' no encontrado o inactivo.") from None

    history = payload.conversation_history
    try:
        tools = enabled_tools(tenant)
        matched = {n: t for n, t in tools.items() if t.matches(payload.question, history)}

        if matched:
            answer = await _run_tool_path(llm, tenant, payload, matched, settings.tool_loop_budget_seconds)
            if answer is not None:
                return answer
            # El modelo no pidió la herramienta (faltan datos): se sigue al paso 2.

        for tool in tools.values():
            if tool.intent_answer_key and intent_matches(payload.question):
                prompt_answer = tenant.predetermined_answers.get("answers", {}).get(tool.intent_answer_key)
                if prompt_answer:
                    return ChatResponse(answer=prompt_answer, source=f"{tool.name}_intent")

        if not matched:
            predetermined = find_predetermined_answer(tenant, payload.question)
            if predetermined:
                return ChatResponse(answer=predetermined, source="predetermined")

        answer_text = await llm.answer(payload.question, tenant, history)
        return ChatResponse(answer=answer_text, source="knowledge_base")

    except HTTPException:
        raise
    except Exception:
        logger.error("chat_endpoint_error", exc_info=True, extra={"tenant_id": payload.tenant_id})
        raise HTTPException(status_code=500, detail="Error interno procesando la solicitud.") from None


async def _run_tool_path(llm, tenant, payload: ChatRequest, matched, budget: float):
    """Turno 0 (clasificación) + una sola herramienta de la allow-list + turno final. None = sin herramienta."""

    async def _flow():
        call = await llm.select_tool(payload.question, tenant, payload.conversation_history, matched)
        if call is None:
            return None
        spec = matched.get(call.name)
        if spec is None:
            # Nunca se despacha por nombre fuera de la allow-list.
            logger.warning("tool_not_allowed", extra={"tool": call.name, "tenant_id": tenant.tenant_id})
            return None
        result = await spec.handler(**call.args)
        text = await llm.answer_with_result(payload.question, tenant, payload.conversation_history, result)
        return ChatResponse(answer=text, source=f"tool:{spec.name}")

    try:
        return await asyncio.wait_for(_flow(), timeout=budget)
    except TimeoutError:
        logger.warning("tool_path_timeout", extra={"tenant_id": tenant.tenant_id})
        return ChatResponse(answer=_TOOL_TIMEOUT_MSG, source="tool_timeout")
    except TypeError:
        # Argumentos inesperados del modelo para el handler: se degrada al flujo normal.
        logger.warning("tool_bad_arguments", exc_info=True, extra={"tenant_id": tenant.tenant_id})
        return None
