import json

import pytest

from app.services.fast_path import find_predetermined_answer, normalize
from app.services.llm import truncate_history
from app.services.tenants import FilesystemTenantRepository, TenantContext, TenantNotFoundError


def _tenant():
    return TenantContext(
        tenant_id="t",
        predetermined_answers={
            "keywords": [
                {"keyword": "ica", "answer_key": "ica"},
                {"keyword": "pago de facturas", "answer_key": "pagos"},
                {"keyword": "pago", "answer_key": "pago_generico"},
            ],
            "answers": {"ica": "ICA", "pagos": "PAGOS", "pago_generico": "PAGO"},
        },
    )


def test_normalize_strips_accents():
    assert normalize("Atención TRÁNSITO") == "atencion transito"


def test_keyword_matches_whole_word_only():
    assert find_predetermined_answer(_tenant(), "información pública") is None


def test_longest_keyword_wins():
    assert find_predetermined_answer(_tenant(), "pago de facturas") == "PAGOS"


def test_truncate_history_keeps_the_end_on_a_line_boundary():
    history = "\n".join(f"linea {i}" for i in range(100))
    out = truncate_history(history, 50)
    assert out.endswith("linea 99")
    assert len(out) <= 50
    assert out.startswith("linea ")


@pytest.mark.asyncio
async def test_filesystem_repository_rejects_inactive_and_traversal(tmp_path):
    (tmp_path / "off").mkdir()
    (tmp_path / "off" / "tenant.json").write_text(json.dumps({"active": False}))
    repo = FilesystemTenantRepository(str(tmp_path))
    with pytest.raises(TenantNotFoundError):
        await repo.load("off")
    with pytest.raises(TenantNotFoundError):
        await repo.load("../off")
