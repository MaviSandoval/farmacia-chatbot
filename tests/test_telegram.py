"""Tests del canal de Telegram. Simulan los avisos que manda Telegram, sin bot real,
sin internet y sin llamar a Groq (ver la fixture 'servidor' en conftest.py)."""

CHAT = 123456789


def aviso_de_telegram(texto: str | None, chat_id: int = CHAT, update_id: int = 1) -> dict:
    """Arma un aviso con el mismo formato que manda Telegram cuando llega un mensaje."""
    mensaje = {
        "message_id": update_id,
        "from": {"id": chat_id, "is_bot": False, "first_name": "Ana"},
        "chat": {"id": chat_id, "type": "private"},
        "date": 1790800000,
    }
    if texto is not None:
        mensaje["text"] = texto
    return {"update_id": update_id, "message": mensaje}


def test_start_saluda(servidor):
    _, cliente, enviados = servidor
    assert cliente.post("/telegram", json=aviso_de_telegram("/start")).status_code == 200
    assert enviados[0][0] == "telegram"
    assert enviados[0][2].startswith("¡Hola!")


def test_responde_un_mensaje(servidor):
    _, cliente, enviados = servidor
    cliente.post("/telegram", json=aviso_de_telegram("¿Tienen pañales?"))
    assert enviados == [("telegram", CHAT, "Respuesta a: ¿Tienen pañales?")]


def test_historial_separado_de_whatsapp(servidor):
    modulo, cliente, _ = servidor
    cliente.post("/telegram", json=aviso_de_telegram("Hola", update_id=1))
    cliente.post("/telegram", json=aviso_de_telegram("¿Y OSDE?", update_id=2))
    historial = modulo.conversaciones[f"telegram:{CHAT}"]
    assert [m["content"] for m in historial if m["role"] == "user"] == ["Hola", "¿Y OSDE?"]


def test_ignora_avisos_repetidos(servidor):
    _, cliente, enviados = servidor
    cliente.post("/telegram", json=aviso_de_telegram("Hola", update_id=7))
    cliente.post("/telegram", json=aviso_de_telegram("Hola", update_id=7))
    assert len(enviados) == 1


def test_mensaje_sin_texto(servidor):
    _, cliente, enviados = servidor
    cliente.post("/telegram", json=aviso_de_telegram(None))  # por ejemplo, una foto
    assert "solo puedo leer mensajes de texto" in enviados[0][2]


def test_avisos_sin_mensaje_se_ignoran(servidor):
    _, cliente, enviados = servidor
    assert cliente.post("/telegram", json={"update_id": 9, "edited_message": {}}).status_code == 200
    assert enviados == []


def test_secreto_de_telegram(servidor, monkeypatch):
    _, cliente, enviados = servidor
    monkeypatch.setenv("TELEGRAM_SECRET", "secreto")
    sin_secreto = cliente.post("/telegram", json=aviso_de_telegram("Hola", update_id=1))
    secreto_falso = cliente.post("/telegram", json=aviso_de_telegram("Hola", update_id=2),
                                 headers={"X-Telegram-Bot-Api-Secret-Token": "otro"})
    con_secreto = cliente.post("/telegram", json=aviso_de_telegram("Hola", update_id=3),
                               headers={"X-Telegram-Bot-Api-Secret-Token": "secreto"})
    assert sin_secreto.status_code == 401
    assert secreto_falso.status_code == 401
    assert con_secreto.status_code == 200
    assert len(enviados) == 1


def test_texto_sin_markdown(servidor):
    modulo, _, _ = servidor
    assert modulo.a_texto_telegram("## Precio\nEl **Losartán** sale $ 5.600") == "Precio\nEl Losartán sale $ 5.600"


def test_registra_el_webhook_al_arrancar(servidor, monkeypatch):
    modulo, _, _ = servidor
    llamadas = []
    monkeypatch.setattr(modulo, "llamar_telegram", lambda metodo, datos: llamadas.append((metodo, datos)))
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_SECRET", "secreto")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://farmacia.onrender.com/")

    modulo.registrar_webhook_telegram()

    assert llamadas == [("setWebhook", {
        "url": "https://farmacia.onrender.com/telegram",
        "allowed_updates": ["message"],
        "secret_token": "secreto",
    })]


def test_sin_token_no_registra_webhook(servidor, monkeypatch):
    modulo, _, _ = servidor
    llamadas = []
    monkeypatch.setattr(modulo, "llamar_telegram", lambda metodo, datos: llamadas.append(metodo))
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://farmacia.onrender.com")
    modulo.registrar_webhook_telegram()
    assert llamadas == []
