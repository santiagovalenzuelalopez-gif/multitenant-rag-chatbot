from tests.conftest import chat


def test_tool_returns_live_status(client):
    r = chat(client, "demo-soporte", "Estado de mi ticket TCK-100001 código A1B2C3")
    body = r.json()
    assert body["source"] == "tool:consultar_ticket"
    assert "En revisión" in body["answer"]


def test_wrong_code_does_not_leak_ticket_existence(client):
    wrong_code = chat(client, "demo-soporte", "ticket TCK-100001 código ZZZ999").json()["answer"]
    missing = chat(client, "demo-soporte", "ticket TCK-999999 código ZZZ999").json()["answer"]
    assert wrong_code == missing
    assert "no encontré" in wrong_code


def test_multi_turn_ticket_then_code(client):
    history = "Usuario: quiero saber de mi ticket TCK-100002\nAsistente: ¿Cuál es el código?"
    r = chat(client, "demo-soporte", "Z9Y8X7", history)
    assert r.json()["source"] == "tool:consultar_ticket"
    assert "Resuelto" in r.json()["answer"]


def test_intent_without_data_asks_for_it(client):
    r = chat(client, "demo-soporte", "Quiero consultar el estado de mi ticket")
    assert r.json()["source"] == "consultar_ticket_intent"
    assert "código de verificación" in r.json()["answer"]


def test_tool_is_fail_closed_for_tenants_without_capability(client):
    # demo-tienda no habilita herramientas: un ticket en el mensaje no dispara nada.
    r = chat(client, "demo-tienda", "Estado de mi ticket TCK-100001 código A1B2C3")
    assert not r.json()["source"].startswith("tool:")
