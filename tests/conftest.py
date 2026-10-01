"""Configuración compartida de los tests.

Cada test usa una base de datos NUEVA creada en una carpeta temporal, así los tests
no dependen de farmacia_demo.db ni la modifican."""

import pytest

import crear_bd
import herramientas


@pytest.fixture(autouse=True)
def base_de_prueba(tmp_path, monkeypatch):
    """Crea una base de datos temporal y hace que las herramientas la usen."""
    ruta = tmp_path / "farmacia_test.db"
    monkeypatch.setattr(crear_bd, "RUTA_BD", ruta)
    monkeypatch.setattr(herramientas, "RUTA_BD", ruta)
    crear_bd.crear_bd()
    return ruta


@pytest.fixture
def servidor(monkeypatch):
    """Prepara el servidor de mensajería con un agente falso y envíos falsos.
    Devuelve (módulo, cliente_http, enviados), donde enviados guarda (canal, destino, texto)."""
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "token-secreto")
    for variable in ("WHATSAPP_APP_SECRET", "TELEGRAM_TOKEN", "TELEGRAM_SECRET", "URL_PUBLICA", "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(variable, raising=False)

    from fastapi.testclient import TestClient

    import servidor as modulo

    modulo.conversaciones.clear()
    modulo.ids_procesados.clear()

    enviados = []
    monkeypatch.setattr(modulo, "enviar_whatsapp", lambda numero, texto: enviados.append(("whatsapp", numero, texto)))
    monkeypatch.setattr(modulo, "enviar_telegram", lambda chat, texto: enviados.append(("telegram", chat, texto)))
    monkeypatch.setattr(modulo, "mostrar_escribiendo", lambda chat: None)

    def responder_falso(mensajes):
        respuesta = f"Respuesta a: {mensajes[-1]['content']}"
        mensajes.append({"role": "assistant", "content": respuesta})
        return respuesta

    monkeypatch.setattr(modulo, "responder", responder_falso)
    return modulo, TestClient(modulo.app), enviados
