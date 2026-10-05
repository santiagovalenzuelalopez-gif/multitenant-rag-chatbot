"""Fast path: respuestas predeterminadas por palabra clave, sin llamar al LLM (costo cero).

Formato de ``predetermined_answers.json``::

    {
      "keywords": [{"keyword": "horario", "answer_key": "horarios"}],
      "menu_options": {"1": "horarios"},
      "answers": {"horarios": "Atendemos de lunes a viernes de 8:00 a 17:00."}
    }
"""

import re
import unicodedata

from app.services.tenants import TenantContext

# Si el mensaje trae más palabras que la keyword + este margen, se considera una pregunta
# elaborada (no una navegación tipo menú) y se deja pasar al RAG: sin este límite, una
# pregunta larga que solo menciona de pasada "horario" quedaba interceptada por el menú.
MAX_EXTRA_WORDS = 5

# Un mensaje que es ÚNICAMENTE un número (1-2 dígitos) se interpreta como opción de menú.
_MENU_OPTION_RE = re.compile(r"^\d{1,2}$")


def normalize(text: str) -> str:
    """Minúsculas y sin diacríticos: 'Atención' y 'atencion' deben matchear igual."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def find_predetermined_answer(tenant: TenantContext, question: str) -> str | None:
    keywords = tenant.predetermined_answers.get("keywords", [])
    answers = tenant.predetermined_answers.get("answers", {})
    if not keywords or not answers:
        return None

    stripped = question.strip()
    menu_options = tenant.predetermined_answers.get("menu_options", {})
    if menu_options and _MENU_OPTION_RE.match(stripped):
        answer = answers.get(menu_options.get(stripped, ""))
        if answer:
            return answer

    normalized = normalize(question)
    total_words = _word_count(normalized)

    # Keywords más largas primero: "horario de atención" gana sobre "horario".
    for entry in sorted(keywords, key=lambda e: len(e.get("keyword", "")), reverse=True):
        keyword = normalize(entry.get("keyword", ""))
        if not keyword:
            continue
        # \b: una keyword corta no debe matchear dentro de otra palabra ("ica" en "pública").
        if not re.search(rf"\b{re.escape(keyword)}\b", normalized):
            continue
        if total_words - _word_count(keyword) > MAX_EXTRA_WORDS:
            continue
        answer = answers.get(entry.get("answer_key"))
        if answer:
            return answer

    return None
