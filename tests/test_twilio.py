"""Tests del canal de WhatsApp por Twilio. Simulan los avisos que manda Twilio (formulario
firmado), sin cuenta real, sin internet y sin llamar a Groq (ver la fixture 'servidor').
La respuesta del bot va dentro del XML (TwiML) que devuelve el webhook."""

import base64
import hashlib
import hmac
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import pytest

TOKEN = "token-de-prueba"
URL = "https://farmacia-bots.onrender.com/twilio"
DESTINO = "whatsapp:+5493794000000"


@pytest.fixture
def twilio(servidor, monkeypatch):
    """Servidor con Twilio configurado y con la URL pública que usa Twilio para firmar."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://farmacia-bots.onrender.com")
    return servidor


def firmar(parametros: dict, token: str = TOKEN, url: str = URL) -> str:
    """Calcula la firma igual que Twilio: HMAC-SHA1 de la URL más los parámetros ordenados."""
    datos = url + "".join(clave + parametros[clave] for clave in sorted(parametros))
    return base64.b64encode(hmac.new(token.encode(), datos.encode(), hashlib.sha1).digest()).decode()


def aviso_de_twilio(texto: str, sid: str = "SM1", desde: str = DESTINO, medios: int = 0) -> dict:
    """Arma los campos que manda Twilio cuando llega un mensaje de WhatsApp."""
    return {
        "MessageSid": sid, "From": desde, "To": "whatsapp:+17372508034",
        "Body": texto, "NumMedia": str(medios), "ProfileName": "Ana",
    }


def enviar(cliente, parametros: dict, firma: str | None = "calcular"):
    encabezados = {"Content-Type": "application/x-www-form-urlencoded"}
    if firma == "calcular":
        firma = firmar(parametros)
    if firma:
        encabezados["X-Twilio-Signature"] = firma
    return cliente.post("/twilio", content=urlencode(parametros), headers=encabezados)


def mensajes_de(respuesta) -> list[str]:
    """Lee los <Message> del TwiML devuelto."""
    raiz = ET.fromstring(respuesta.content)
    assert raiz.tag == "Response"
    return [mensaje.text for mensaje in raiz.findall("Message")]


def test_responde_dentro_del_twiml(twilio):
    _, cliente, _ = twilio
    respuesta = enviar(cliente, aviso_de_twilio("¿Tienen ibuprofeno 600?"))
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/xml")
    assert mensajes_de(respuesta) == ["Respuesta a: ¿Tienen ibuprofeno 600?"]


def test_escapa_caracteres_especiales_del_xml(twilio, monkeypatch):
    modulo, cliente, _ = twilio
    monkeypatch.setattr(modulo, "responder_cliente", lambda clave, texto: "Precio < $ 5.000 & con **receta**")
    respuesta = enviar(cliente, aviso_de_twilio("Hola"))
    assert mensajes_de(respuesta) == ["Precio < $ 5.000 & con *receta*"]  # además, negrita de WhatsApp


def test_firma_con_tildes_y_simbolos(twilio):
    _, cliente, _ = twilio
    respuesta = enviar(cliente, aviso_de_twilio("¿Cubren el losartán? 50% & más"))
    assert respuesta.status_code == 200
    assert mensajes_de(respuesta) == ["Respuesta a: ¿Cubren el losartán? 50% & más"]


@pytest.mark.parametrize("firma", [None, "firma-falsa", firmar(aviso_de_twilio("Hola"), token="otro-token")])
def test_rechaza_firmas_invalidas(twilio, firma):
    modulo, cliente, _ = twilio
    assert enviar(cliente, aviso_de_twilio("Hola"), firma=firma).status_code == 401
    assert modulo.conversaciones == {}


def test_sin_twilio_configurado_se_rechaza(servidor):
    _, cliente, _ = servidor  # sin TWILIO_AUTH_TOKEN
    assert enviar(cliente, aviso_de_twilio("Hola")).status_code == 401


def test_ignora_avisos_repetidos(twilio):
    _, cliente, _ = twilio
    primera = enviar(cliente, aviso_de_twilio("Hola", sid="SMrepetido"))
    segunda = enviar(cliente, aviso_de_twilio("Hola", sid="SMrepetido"))
    assert len(mensajes_de(primera)) == 1
    assert mensajes_de(segunda) == []


def test_mensaje_sin_texto(twilio):
    _, cliente, _ = twilio
    respuesta = enviar(cliente, aviso_de_twilio("", medios=1))  # por ejemplo, una foto
    assert "solo puedo leer mensajes de texto" in mensajes_de(respuesta)[0]


def test_historial_propio_del_canal(twilio):
    modulo, cliente, _ = twilio
    enviar(cliente, aviso_de_twilio("Hola", sid="SM1"))
    enviar(cliente, aviso_de_twilio("¿Y OSDE?", sid="SM2"))
    historial = modulo.conversaciones[f"twilio:{DESTINO}"]
    assert [m["content"] for m in historial if m["role"] == "user"] == ["Hola", "¿Y OSDE?"]


def test_respuestas_largas_en_varios_mensajes(twilio, monkeypatch):
    modulo, cliente, _ = twilio
    largo = "\n".join(["linea de prueba"] * 200)  # ~3200 caracteres
    monkeypatch.setattr(modulo, "responder_cliente", lambda clave, texto: largo)
    mensajes = mensajes_de(enviar(cliente, aviso_de_twilio("Hola")))
    assert len(mensajes) == 2
    assert all(len(mensaje) <= 1600 for mensaje in mensajes)
    assert "\n".join(mensajes).count("linea de prueba") == 200  # no se pierde texto


def test_si_el_agente_tarda_avisa_en_vez_de_quedar_en_silencio(twilio, monkeypatch):
    modulo, cliente, _ = twilio
    monkeypatch.setattr(modulo, "ESPERA_MAXIMA_TWILIO", 0.1)

    def agente_lento(clave, texto):
        time.sleep(0.5)
        return "tarde"

    monkeypatch.setattr(modulo, "responder_cliente", agente_lento)
    mensajes = mensajes_de(enviar(cliente, aviso_de_twilio("Hola")))
    assert mensajes == [modulo.MENSAJE_DEMORA]
