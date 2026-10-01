"""Tests del canal de WhatsApp. Simulan los avisos que manda Meta, sin WhatsApp real,
sin internet y sin llamar a Groq (ver la fixture 'servidor' en conftest.py)."""

import hashlib
import hmac
import json

import pytest

NUMERO = "5493794000000"


def aviso_de_meta(texto: str, numero: str = NUMERO, id_: str = "wamid.1", tipo: str = "text") -> dict:
    """Arma un aviso con el mismo formato que manda Meta cuando llega un mensaje."""
    mensaje = {"from": numero, "id": id_, "timestamp": "1790800000", "type": tipo}
    if tipo == "text":
        mensaje["text"] = {"body": texto}
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "123", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550000000", "phone_number_id": "999"},
            "messages": [mensaje],
        }}]}],
    }


# ---------------------------------------------------------------- verificación del webhook

def test_verificacion_con_token_correcto_devuelve_el_challenge(servidor):
    _, cliente, _ = servidor
    respuesta = cliente.get("/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "token-secreto", "hub.challenge": "12345",
    })
    assert respuesta.status_code == 200
    assert respuesta.text == "12345"


def test_verificacion_con_token_incorrecto_se_rechaza(servidor):
    _, cliente, _ = servidor
    respuesta = cliente.get("/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "otro", "hub.challenge": "12345",
    })
    assert respuesta.status_code == 403


# ---------------------------------------------------------------- mensajes

def test_responde_un_mensaje_de_texto(servidor):
    _, cliente, enviados = servidor
    assert cliente.post("/whatsapp", json=aviso_de_meta("¿Tienen ibuprofeno?")).status_code == 200
    assert enviados == [("whatsapp", NUMERO, "Respuesta a: ¿Tienen ibuprofeno?")]


def test_guarda_el_historial_por_cliente(servidor):
    modulo, cliente, _ = servidor
    cliente.post("/whatsapp", json=aviso_de_meta("Hola", numero="5493790000001", id_="a"))
    cliente.post("/whatsapp", json=aviso_de_meta("¿Y PAMI?", numero="5493790000001", id_="b"))
    cliente.post("/whatsapp", json=aviso_de_meta("Hola", numero="5493790000002", id_="c"))

    historial = modulo.conversaciones["whatsapp:5493790000001"]
    assert [m["content"] for m in historial if m["role"] == "user"] == ["Hola", "¿Y PAMI?"]
    assert len(modulo.conversaciones) == 2


def test_ignora_avisos_repetidos(servidor):
    _, cliente, enviados = servidor
    cliente.post("/whatsapp", json=aviso_de_meta("Hola", id_="repetido"))
    cliente.post("/whatsapp", json=aviso_de_meta("Hola", id_="repetido"))
    assert len(enviados) == 1


def test_mensaje_que_no_es_texto(servidor):
    _, cliente, enviados = servidor
    cliente.post("/whatsapp", json=aviso_de_meta("", tipo="audio"))
    assert "solo puedo leer mensajes de texto" in enviados[0][2]


def test_reiniciar_borra_la_conversacion(servidor):
    modulo, cliente, enviados = servidor
    cliente.post("/whatsapp", json=aviso_de_meta("Hola", id_="1"))
    cliente.post("/whatsapp", json=aviso_de_meta("reiniciar", id_="2"))
    assert [m["role"] for m in modulo.conversaciones[f"whatsapp:{NUMERO}"]] == ["system"]
    assert "empezamos de nuevo" in enviados[-1][2]


def test_avisos_de_estado_no_generan_respuesta(servidor):
    _, cliente, enviados = servidor
    aviso = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "statuses": [{"id": "wamid.1", "status": "read"}],
    }}]}]}
    assert cliente.post("/whatsapp", json=aviso).status_code == 200
    assert enviados == []


def test_error_del_agente_responde_amable(servidor, monkeypatch):
    modulo, cliente, enviados = servidor

    def responder_roto(mensajes):
        raise RuntimeError("Groq caído")

    monkeypatch.setattr(modulo, "responder", responder_roto)
    cliente.post("/whatsapp", json=aviso_de_meta("Hola"))
    assert "problema con el servicio" in enviados[0][2]
    # La pregunta fallida no queda en el historial
    assert [m["role"] for m in modulo.conversaciones[f"whatsapp:{NUMERO}"]] == ["system"]


# ---------------------------------------------------------------- seguridad

def test_firma_de_meta(servidor, monkeypatch):
    _, cliente, enviados = servidor
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "secreto-de-la-app")
    cuerpo = json.dumps(aviso_de_meta("Hola")).encode()
    firma = hmac.new(b"secreto-de-la-app", cuerpo, hashlib.sha256).hexdigest()

    sin_firma = cliente.post("/whatsapp", content=cuerpo, headers={"Content-Type": "application/json"})
    firma_falsa = cliente.post("/whatsapp", content=cuerpo, headers={"X-Hub-Signature-256": "sha256=falsa"})
    con_firma = cliente.post("/whatsapp", content=cuerpo, headers={"X-Hub-Signature-256": f"sha256={firma}"})

    assert sin_firma.status_code == 401
    assert firma_falsa.status_code == 401
    assert con_firma.status_code == 200
    assert len(enviados) == 1


# ---------------------------------------------------------------- utilidades

@pytest.mark.parametrize("entrada, esperado", [
    ("5493794123456", "543794123456"),   # celular argentino: se saca el 9
    ("543794123456", "543794123456"),    # ya está bien
    ("15551234567", "15551234567"),      # otro país: no se toca
])
def test_numero_para_responder(servidor, entrada, esperado):
    modulo, _, _ = servidor
    assert modulo.numero_para_responder(entrada) == esperado


def test_formato_whatsapp(servidor):
    modulo, _, _ = servidor
    texto = "## Resultado\nEl **Ibuprofeno 600** sale $ 4.100"
    assert modulo.a_formato_whatsapp(texto) == "*Resultado*\nEl *Ibuprofeno 600* sale $ 4.100"


def test_partir_mensajes_largos(servidor):
    modulo, _, _ = servidor
    partes = modulo.partir_mensaje("\n".join(["linea de prueba"] * 500))  # ~8000 caracteres
    assert len(partes) == 2
    assert all(len(parte) <= modulo.MAX_LARGO_MENSAJE for parte in partes)


def test_recortar_historial_no_deja_resultados_huerfanos(servidor, monkeypatch):
    modulo, _, _ = servidor
    monkeypatch.setattr(modulo, "MAX_MENSAJES_HISTORIAL", 4)
    historial = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "content": "r"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "2"},
        {"role": "assistant", "content": "a2"},
    ]
    recortado = modulo.recortar_historial(historial)
    assert recortado[0]["role"] == "system"
    assert recortado[1]["role"] == "user"   # nunca arranca con un resultado de herramienta
    assert [m["content"] for m in recortado[1:]] == ["2", "a2"]
