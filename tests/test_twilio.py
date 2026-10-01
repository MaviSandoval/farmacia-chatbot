"""Tests del canal de WhatsApp por Twilio. Simulan los avisos que manda Twilio (formulario
firmado), sin cuenta real, sin internet y sin llamar a Groq (ver la fixture 'servidor')."""

import base64
import hashlib
import hmac
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
        "MessageSid": sid, "From": desde, "To": "whatsapp:+14155238886",
        "Body": texto, "NumMedia": str(medios), "ProfileName": "Ana",
    }


def enviar(cliente, parametros: dict, firma: str | None = "calcular"):
    encabezados = {"Content-Type": "application/x-www-form-urlencoded"}
    if firma == "calcular":
        firma = firmar(parametros)
    if firma:
        encabezados["X-Twilio-Signature"] = firma
    return cliente.post("/twilio", content=urlencode(parametros), headers=encabezados)


def test_responde_un_mensaje(twilio):
    _, cliente, enviados = twilio
    respuesta = enviar(cliente, aviso_de_twilio("¿Tienen ibuprofeno 600?"))
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/xml")
    assert respuesta.text == "<Response></Response>"
    assert enviados == [("twilio", DESTINO, "Respuesta a: ¿Tienen ibuprofeno 600?")]


def test_firma_con_tildes_y_simbolos(twilio):
    _, cliente, enviados = twilio
    assert enviar(cliente, aviso_de_twilio("¿Cubren el losartán? 50% & más")).status_code == 200
    assert len(enviados) == 1


@pytest.mark.parametrize("firma", [None, "firma-falsa", firmar(aviso_de_twilio("Hola"), token="otro-token")])
def test_rechaza_firmas_invalidas(twilio, firma):
    _, cliente, enviados = twilio
    assert enviar(cliente, aviso_de_twilio("Hola"), firma=firma).status_code == 401
    assert enviados == []


def test_sin_twilio_configurado_se_rechaza(servidor):
    _, cliente, enviados = servidor  # sin TWILIO_AUTH_TOKEN
    assert enviar(cliente, aviso_de_twilio("Hola")).status_code == 401
    assert enviados == []


def test_ignora_avisos_repetidos(twilio):
    _, cliente, enviados = twilio
    enviar(cliente, aviso_de_twilio("Hola", sid="SMrepetido"))
    enviar(cliente, aviso_de_twilio("Hola", sid="SMrepetido"))
    assert len(enviados) == 1


def test_mensaje_sin_texto(twilio):
    _, cliente, enviados = twilio
    enviar(cliente, aviso_de_twilio("", medios=1))  # por ejemplo, una foto
    assert "solo puedo leer mensajes de texto" in enviados[0][2]


def test_historial_propio_del_canal(twilio):
    modulo, cliente, _ = twilio
    enviar(cliente, aviso_de_twilio("Hola", sid="SM1"))
    enviar(cliente, aviso_de_twilio("¿Y OSDE?", sid="SM2"))
    historial = modulo.conversaciones[f"twilio:{DESTINO}"]
    assert [m["content"] for m in historial if m["role"] == "user"] == ["Hola", "¿Y OSDE?"]


def test_enviar_parte_mensajes_largos(monkeypatch):
    """enviar_twilio real (sin la fixture 'servidor', que lo reemplaza), con la API de Twilio
    sustituida por una función que guarda los pedidos."""
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    import servidor as modulo

    monkeypatch.delenv("TWILIO_WHATSAPP_FROM", raising=False)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(modulo, "ESPERA_ENTRE_MENSAJES", 0)
    pedidos = []

    class RespuestaFalsa:
        status_code = 201
        text = ""

    def post_falso(url, **datos):
        pedidos.append((url, datos))
        return RespuestaFalsa()

    monkeypatch.setattr(modulo.httpx, "post", post_falso)

    texto = "**Precio:** $ 4.100\n" + "\n".join(["linea de prueba"] * 200)  # ~3200 caracteres
    modulo.enviar_twilio(DESTINO, texto)

    assert len(pedidos) == 3
    url, datos = pedidos[0]
    assert url == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    assert datos["auth"] == ("AC123", TOKEN)
    assert datos["data"]["From"] == "whatsapp:+14155238886"
    assert datos["data"]["To"] == DESTINO
    assert datos["data"]["Body"].startswith("*Precio:* $ 4.100")
    assert all(len(d["data"]["Body"]) <= 1600 for _, d in pedidos)
