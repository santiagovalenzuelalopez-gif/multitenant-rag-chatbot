from tests.conftest import chat


def test_health_and_version(client):
    assert client.get("/health").json() == {"status": "ok"}
    body = client.get("/version").json()
    assert {"service", "version", "environment"} <= body.keys()


def test_unknown_tenant_is_404(client):
    assert chat(client, "no-existe", "hola").status_code == 404


def test_invalid_tenant_id_is_rejected(client):
    # Path traversal / formato inválido: lo corta el schema, nunca llega al repositorio.
    assert chat(client, "../etc", "hola").status_code == 422


def test_fast_path_keyword(client):
    r = chat(client, "demo-soporte", "¿Cuál es el horario de atención?")
    assert r.status_code == 200
    assert r.json()["source"] == "predetermined"
    assert "8:00" in r.json()["answer"]


def test_fast_path_menu_option(client):
    r = chat(client, "demo-soporte", "2")
    assert r.json()["source"] == "predetermined"
    assert "soporte@example.com" in r.json()["answer"]


def test_long_question_skips_fast_path_and_uses_rag(client):
    q = "Tengo una duda larga y específica sobre el horario en que responden los tickets críticos hoy"
    r = chat(client, "demo-soporte", q)
    assert r.json()["source"] == "knowledge_base"


def test_rag_answers_from_tenant_knowledge(client):
    r = chat(client, "demo-soporte", "¿Cuánto tarda la primera respuesta de un ticket estándar?")
    assert r.json()["source"] == "knowledge_base"
    assert "4 horas" in r.json()["answer"]


def test_tenants_are_isolated(client):
    # El conocimiento de envíos es de otro tenant: demo-soporte no debe conocerlo.
    r = chat(client, "demo-soporte", "¿Cuántos días tardan los envíos nacionales?")
    assert "2 y 5 días" not in r.json()["answer"]
    r = chat(client, "demo-tienda", "¿Cuántos días tardan los envíos nacionales?")
    assert "2 y 5 días" in r.json()["answer"]


def test_correlation_id_is_propagated(client):
    r = client.get("/health", headers={"X-Correlation-ID": "abc-123"})
    assert r.headers["X-Correlation-ID"] == "abc-123"
    assert "X-Correlation-ID" in client.get("/health").headers
