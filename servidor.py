"""Servidor de los canales de mensajería del asistente de farmacia: WhatsApp y Telegram.

Los dos canales usan el MISMO agente que la web (agente.responder). Solo cambia cómo
llega el mensaje y cómo se envía la respuesta:

    WhatsApp:  Meta     -> POST /whatsapp -> agente -> API de Meta     -> cliente
    WhatsApp:  Twilio   -> POST /twilio   -> agente -> respuesta TwiML -> cliente  (alternativa a Meta)
    Telegram:  Telegram -> POST /telegram -> agente -> API de Telegram -> cliente

Ejecutar localmente:  uvicorn servidor:app --reload
Variables de entorno (en .env o en el hosting); cada canal se activa si están sus variables:
    GROQ_API_KEY              clave de Groq
    WHATSAPP_TOKEN            token de acceso de la app de Meta
    WHATSAPP_PHONE_NUMBER_ID  id del número de WhatsApp (no es el número de teléfono)
    WHATSAPP_VERIFY_TOKEN     texto que inventás vos, para que Meta verifique el webhook
    WHATSAPP_APP_SECRET       (opcional) clave secreta de la app de Meta, para validar los avisos
    TWILIO_AUTH_TOKEN         clave de la cuenta de Twilio, para validar que los avisos vienen de Twilio
    TELEGRAM_TOKEN            token del bot que da @BotFather
    TELEGRAM_SECRET           (opcional) texto que inventás vos, para validar los avisos de Telegram
    URL_PUBLICA               (opcional) URL del servidor; en Render se usa RENDER_EXTERNAL_URL solo
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import threading
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response

from agente import PROMPT_SISTEMA, SALUDO, responder

load_dotenv()

VERSION_API_META = os.environ.get("WHATSAPP_API_VERSION", "v25.0")
MAX_LARGO_MENSAJE = 4096       # límite de caracteres por mensaje (igual en WhatsApp y Telegram)
MAX_MENSAJES_HISTORIAL = 30    # para no mandarle al modelo conversaciones infinitas
PALABRAS_REINICIO = {"reiniciar", "reset", "nueva conversacion", "nueva conversación", "/start"}
MENSAJE_REINICIO = "Listo, empezamos de nuevo. ¿En qué te puedo ayudar?"
MENSAJE_ERROR = "Hubo un problema con el servicio. Probá de nuevo en un momento."
MENSAJE_SOLO_TEXTO = "Por ahora solo puedo leer mensajes de texto. ¿Me escribís tu consulta?"


# ================================================================ conversaciones (comunes a todos los canales)

# Historial de cada cliente. La clave incluye el canal: 'whatsapp:549...' o 'telegram:12345'.
# Vive en memoria: si el servidor se reinicia, las conversaciones empiezan de cero.
conversaciones: dict[str, list[dict]] = {}

# Las plataformas pueden reenviar el mismo aviso: se recuerdan los últimos ids para ignorar repetidos
ids_procesados: deque[str] = deque(maxlen=2000)
candado_ids = threading.Lock()

# Un candado por cliente: sus mensajes se responden en orden, sin frenar a los demás
candados: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


def es_repetido(id_aviso: str) -> bool:
    """Devuelve True si el aviso ya se procesó; si no, lo registra."""
    with candado_ids:
        if id_aviso in ids_procesados:
            return True
        ids_procesados.append(id_aviso)
        return False


def recortar_historial(mensajes: list[dict]) -> list[dict]:
    """Deja el prompt de sistema y los últimos mensajes. Corta siempre antes de una pregunta
    del cliente, para no separar un pedido de herramienta de su resultado."""
    sistema, resto = mensajes[0], mensajes[1:]
    if len(resto) <= MAX_MENSAJES_HISTORIAL:
        return mensajes
    resto = resto[-MAX_MENSAJES_HISTORIAL:]
    while resto and resto[0]["role"] != "user":
        resto = resto[1:]
    return [sistema] + resto


def responder_cliente(clave: str, texto: str) -> str:
    """Responde el mensaje de un cliente usando su historial. Sirve para cualquier canal."""
    texto = texto.strip()
    with candados[clave]:
        reinicio = texto.lower() in PALABRAS_REINICIO
        if reinicio or clave not in conversaciones:
            conversaciones[clave] = [{"role": "system", "content": PROMPT_SISTEMA}]
        if reinicio:
            return SALUDO if texto.lower() == "/start" else MENSAJE_REINICIO

        historial = conversaciones[clave]
        historial.append({"role": "user", "content": texto})
        try:
            respuesta = responder(historial)
        except Exception as error:
            print(f"  [{clave}] error del agente: {error}")
            historial.pop()  # se descarta la pregunta que no se pudo responder
            respuesta = MENSAJE_ERROR
        conversaciones[clave] = recortar_historial(historial)
        return respuesta


def partir_mensaje(texto: str, largo: int = MAX_LARGO_MENSAJE) -> list[str]:
    """Divide un texto largo en partes que entren en un mensaje, cortando en saltos de línea."""
    partes = []
    while len(texto) > largo:
        corte = texto.rfind("\n", 0, largo)
        if corte <= 0:
            corte = largo
        partes.append(texto[:corte].strip())
        texto = texto[corte:].strip()
    if texto:
        partes.append(texto)
    return partes


# ================================================================ WhatsApp

def numero_para_responder(numero: str) -> str:
    """Corrige el número de celulares de Argentina.
    WhatsApp avisa los mensajes desde '549' + número, pero para responder la API espera
    '54' + número (sin el 9). Sin esta corrección, Meta rechaza el envío."""
    if numero.startswith("549") and len(numero) == 13:
        return "54" + numero[3:]
    return numero


def a_formato_whatsapp(texto: str) -> str:
    """Adapta el Markdown del modelo a WhatsApp, que usa *negrita* (un asterisco) y no tiene títulos."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto)
    texto = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", texto, flags=re.MULTILINE)
    return texto.strip()


def firma_meta_valida(cuerpo: bytes, firma: str | None) -> bool:
    """Verifica que el aviso viene de Meta: la firma es un HMAC-SHA256 del cuerpo con la clave de la app.
    Si no se configuró WHATSAPP_APP_SECRET, no se verifica (útil para probar)."""
    secreto = os.environ.get("WHATSAPP_APP_SECRET")
    if not secreto:
        return True
    if not firma or not firma.startswith("sha256="):
        return False
    esperada = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma.removeprefix("sha256="))


def extraer_mensajes_whatsapp(datos: dict) -> list[dict]:
    """Saca los mensajes entrantes del aviso de Meta. Ignora avisos de estado (enviado, leído, etc.)."""
    return [
        mensaje
        for entrada in datos.get("entry", [])
        for cambio in entrada.get("changes", [])
        for mensaje in cambio.get("value", {}).get("messages", [])
    ]


def enviar_whatsapp(numero: str, texto: str) -> None:
    """Envía un mensaje de texto con la API de WhatsApp de Meta."""
    url = f"https://graph.facebook.com/{VERSION_API_META}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    encabezados = {"Authorization": f"Bearer {os.environ['WHATSAPP_TOKEN']}"}
    for parte in partir_mensaje(a_formato_whatsapp(texto)):
        respuesta = httpx.post(url, headers=encabezados, timeout=20, json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": numero_para_responder(numero),
            "type": "text",
            "text": {"preview_url": False, "body": parte},
        })
        if respuesta.status_code >= 400:
            print(f"  [whatsapp] error al enviar a {numero}: {respuesta.status_code} {respuesta.text}")


def procesar_whatsapp(mensaje: dict) -> None:
    """Responde un mensaje de WhatsApp. Corre en segundo plano para contestarle rápido a Meta."""
    numero = mensaje["from"]
    if mensaje.get("type") != "text":
        enviar_whatsapp(numero, MENSAJE_SOLO_TEXTO)
        return
    texto = mensaje["text"]["body"]
    print(f"  [whatsapp:{numero}] {texto}")
    enviar_whatsapp(numero, responder_cliente(f"whatsapp:{numero}", texto))


# ================================================================ WhatsApp por Twilio (alternativa a Meta)

# La respuesta va dentro de la misma respuesta HTTP del webhook (TwiML), no por la API:
# la cuenta de prueba de Twilio solo deja enviar mensajes libres de esa forma (por la API
# exige plantillas aprobadas, error 21654). Twilio espera como máximo 15 segundos.
MAX_LARGO_TWILIO = 1600         # Twilio corta los mensajes de WhatsApp en 1600 caracteres
ESPERA_MAXIMA_TWILIO = 13       # segundos; un poco menos que el límite de Twilio
MENSAJE_DEMORA = ("Estoy tardando más de lo normal en responder 😅 "
                  "Probá escribirme de nuevo en un momento.")


def url_publica(ruta: str, request: Request) -> str:
    """URL pública con la que la plataforma llamó al servidor. Detrás del proxy de Render,
    request.url puede figurar como http://, por eso se prefiere la URL pública configurada."""
    base = os.environ.get("URL_PUBLICA") or os.environ.get("RENDER_EXTERNAL_URL")
    return f"{base.rstrip('/')}{ruta}" if base else str(request.url)


def firma_twilio_valida(url: str, parametros: dict[str, str], firma: str | None) -> bool:
    """Verifica que el aviso viene de Twilio. La firma es un HMAC-SHA1, en base64, de la URL
    seguida de cada parámetro (ordenados por nombre) pegado a su valor, con el Auth Token como clave."""
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not token or not firma:
        return False
    datos = url + "".join(clave + parametros[clave] for clave in sorted(parametros))
    esperada = base64.b64encode(hmac.new(token.encode(), datos.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(esperada, firma)


def twiml(mensajes: list[str]) -> str:
    """Arma la respuesta en TwiML (el XML de Twilio) con uno o más mensajes de WhatsApp."""
    cuerpo = "".join(f"<Message>{escape(mensaje)}</Message>" for mensaje in mensajes)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{cuerpo}</Response>'


def respuesta_twilio(parametros: dict[str, str]) -> list[str]:
    """Arma los mensajes de respuesta para un aviso de Twilio. Corre en un hilo aparte."""
    destino = parametros["From"]
    texto = parametros.get("Body", "").strip()
    if not texto:  # foto, audio, ubicación, etc.
        return [MENSAJE_SOLO_TEXTO]
    print(f"  [{destino}] {texto}")
    respuesta = responder_cliente(f"twilio:{destino}", texto)
    return partir_mensaje(a_formato_whatsapp(respuesta), MAX_LARGO_TWILIO)


# ================================================================ Telegram

def a_texto_telegram(texto: str) -> str:
    """Telegram muestra el texto tal cual: se sacan los asteriscos y numerales del Markdown."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    texto = re.sub(r"^#{1,6}\s*", "", texto, flags=re.MULTILINE)
    return texto.strip()


def llamar_telegram(metodo: str, datos: dict) -> httpx.Response:
    """Llama a un método de la API de bots de Telegram."""
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/{metodo}"
    respuesta = httpx.post(url, json=datos, timeout=20)
    if respuesta.status_code >= 400:
        print(f"  [telegram] error en {metodo}: {respuesta.status_code} {respuesta.text}")
    return respuesta


def enviar_telegram(chat_id: int, texto: str) -> None:
    """Envía un mensaje de texto a un chat de Telegram."""
    for parte in partir_mensaje(a_texto_telegram(texto)):
        llamar_telegram("sendMessage", {"chat_id": chat_id, "text": parte})


def mostrar_escribiendo(chat_id: int) -> None:
    """Muestra 'escribiendo...' en Telegram mientras el agente arma la respuesta."""
    llamar_telegram("sendChatAction", {"chat_id": chat_id, "action": "typing"})


def procesar_telegram(mensaje: dict) -> None:
    """Responde un mensaje de Telegram. Corre en segundo plano para contestarle rápido a Telegram."""
    chat_id = mensaje["chat"]["id"]
    texto = mensaje.get("text")
    if not texto:
        enviar_telegram(chat_id, MENSAJE_SOLO_TEXTO)
        return
    print(f"  [telegram:{chat_id}] {texto}")
    mostrar_escribiendo(chat_id)
    enviar_telegram(chat_id, responder_cliente(f"telegram:{chat_id}", texto))


def registrar_webhook_telegram() -> None:
    """Le avisa a Telegram a qué URL mandar los mensajes. Se hace solo al arrancar el servidor."""
    url_publica = os.environ.get("URL_PUBLICA") or os.environ.get("RENDER_EXTERNAL_URL")
    if not os.environ.get("TELEGRAM_TOKEN") or not url_publica:
        return
    datos = {"url": f"{url_publica.rstrip('/')}/telegram", "allowed_updates": ["message"]}
    if os.environ.get("TELEGRAM_SECRET"):
        datos["secret_token"] = os.environ["TELEGRAM_SECRET"]
    try:
        llamar_telegram("setWebhook", datos)
        print(f"  [telegram] webhook registrado en {datos['url']}")
    except httpx.HTTPError as error:
        print(f"  [telegram] no se pudo registrar el webhook: {error}")


# ================================================================ aplicación y endpoints

@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Código que corre al arrancar el servidor."""
    registrar_webhook_telegram()
    yield


app = FastAPI(title="Asistente de Farmacia - Mensajería", lifespan=ciclo_de_vida)


@app.get("/")
def estado() -> dict:
    """Permite comprobar que el servidor está andando (y despertarlo si el hosting lo durmió)."""
    return {"estado": "ok", "servicio": "Asistente de Farmacia - WhatsApp y Telegram"}


@app.get("/whatsapp", response_class=PlainTextResponse)
def verificar_webhook_whatsapp(request: Request) -> str:
    """Meta llama a este endpoint una vez, al configurar el webhook, para confirmar que es nuestro.
    Hay que devolver hub.challenge si el verify_token coincide con el nuestro."""
    parametros = request.query_params
    token_esperado = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    if (token_esperado  # si WhatsApp no está configurado, se rechaza siempre
            and parametros.get("hub.mode") == "subscribe"
            and parametros.get("hub.verify_token") == token_esperado):
        return parametros.get("hub.challenge", "")
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/whatsapp")
async def recibir_whatsapp(request: Request, tareas: BackgroundTasks) -> dict:
    """Recibe los avisos de Meta. Responde enseguida (si tarda, Meta reintenta)
    y procesa cada mensaje en segundo plano."""
    cuerpo = await request.body()
    if not firma_meta_valida(cuerpo, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Firma inválida")
    try:
        datos = json.loads(cuerpo)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")

    for mensaje in extraer_mensajes_whatsapp(datos):
        if not es_repetido(f"whatsapp:{mensaje['id']}"):
            tareas.add_task(procesar_whatsapp, mensaje)
    return {"estado": "recibido"}


@app.post("/twilio")
async def recibir_twilio(request: Request) -> Response:
    """Recibe los avisos de Twilio (formulario, no JSON) y responde con TwiML (XML) que
    contiene el mensaje del agente. Twilio lo entrega por WhatsApp al cliente."""
    cuerpo = (await request.body()).decode()
    parametros = dict(parse_qsl(cuerpo, keep_blank_values=True))
    firma = request.headers.get("X-Twilio-Signature")
    url = url_publica("/twilio", request)
    if not firma_twilio_valida(url, parametros, firma):
        # Diagnóstico sin mostrar secretos: qué URL se usó y si hay token configurado
        print(f"  [twilio] firma inválida (url usada: {url}, token configurado: "
              f"{bool(os.environ.get('TWILIO_AUTH_TOKEN'))}, firma recibida: {bool(firma)})")
        raise HTTPException(status_code=401, detail="Firma inválida")

    if "From" not in parametros or es_repetido(f"twilio:{parametros.get('MessageSid')}"):
        return Response(content=twiml([]), media_type="text/xml")

    try:
        # El agente es código sincrónico: se corre en otro hilo para no bloquear el servidor
        mensajes = await asyncio.wait_for(run_in_threadpool(respuesta_twilio, parametros),
                                          timeout=ESPERA_MAXIMA_TWILIO)
    except TimeoutError:
        print(f"  [twilio] el agente tardó más de {ESPERA_MAXIMA_TWILIO} s")
        mensajes = [MENSAJE_DEMORA]
    return Response(content=twiml(mensajes), media_type="text/xml")


@app.post("/telegram")
async def recibir_telegram(request: Request, tareas: BackgroundTasks) -> dict:
    """Recibe los avisos de Telegram y procesa el mensaje en segundo plano."""
    secreto = os.environ.get("TELEGRAM_SECRET")
    if secreto and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secreto:
        raise HTTPException(status_code=401, detail="Secreto inválido")
    try:
        datos = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")

    mensaje = datos.get("message")
    if mensaje and not es_repetido(f"telegram:{datos.get('update_id')}"):
        tareas.add_task(procesar_telegram, mensaje)
    return {"estado": "recibido"}
