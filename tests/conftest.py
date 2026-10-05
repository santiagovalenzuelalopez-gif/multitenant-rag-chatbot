import os
from pathlib import Path

import pytest

# Backends de demo: sin red ni credenciales. Debe fijarse ANTES de importar la app.
os.environ["TENANT_BACKEND"] = "filesystem"
os.environ["LLM_BACKEND"] = "mock"
os.environ["TENANTS_DIR"] = str(Path(__file__).resolve().parent.parent / "data" / "tenants")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.tenants import invalidate_tenant_cache  # noqa: E402


@pytest.fixture
def client():
    invalidate_tenant_cache()
    return TestClient(app)


def chat(client, tenant_id, question, history=""):
    return client.post(
        "/api/v1/chat",
        json={"tenant_id": tenant_id, "question": question, "conversation_history": history},
    )
