from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    question: str = Field(..., min_length=1, max_length=2000)
    # Historial en texto plano (más reciente al final). Es solo contexto, nunca instrucciones.
    conversation_history: str = Field(default="", max_length=20000)


class ChatResponse(BaseModel):
    answer: str
    # Quién resolvió la consulta: "predetermined" | "tool" | "knowledge_base" | ...
    source: str
