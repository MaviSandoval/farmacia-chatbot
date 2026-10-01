"""Canal de WhatsApp del asistente de farmacia (WhatsApp Cloud API de Meta).

Cómo funciona:
1. Un cliente escribe al número de WhatsApp del bot.
2. Meta le avisa a este servidor con un POST a /webhook (el "webhook").
3. El servidor le pasa el mensaje al mismo agente que usa la web (agente.responder).
4. La respuesta se envía al cliente con la API de Meta.

Ejecutar localmente:  uvicorn whatsapp_bot:app --reload
Variables de entorno necesarias (en .env o en el hosting):
    GROQ_API_KEY             clave de Groq (la misma de siempre)
    WHATSAPP_TOKEN           token de acceso de la app de Meta
    WHATSAPP_PHONE_NUMBER_ID id del número de WhatsApp (no es el número de teléfono)
    WHATSAPP_VERIFY_TOKEN    texto que inventás vos, para que Meta verifique el webhook
    WHATSAPP_APP_SECRET      (opcional) clave secreta de la app, para validar que los avisos vienen de Meta
"""

import hashlib
import hmac
import json
import os
import re
import threading
from collections import defaultdict, deque

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agente import PROMPT_SISTEMA, responder

load_dotenv()

VERSION_API = os.environ.get("WHATSAPP_API_VERSION", "v25.0")
MAX_LARGO_MENSAJE = 4096       # límite de caracteres de WhatsApp por mensaje
MAX_MENSAJES_HISTORIAL = 30    # para no mandarle al modelo conversaciones infinitas
PALABRAS_REINICIO = {"reiniciar", "reset", "/start", "nueva conversacion", "nueva conversación"}

app = FastAPI(title="Asistente de Farmacia - WhatsApp")

# Historial de cada cliente, por número de teléfono. Vive en memoria: si el servidor
# se reinicia, las conversaciones empiezan de cero (suficiente para una demo).
conversaciones: dict[str, list[dict]] = {}

# Meta puede reenviar el mismo aviso: se recuerdan los últimos ids para ignorar repetidos
ids_procesados: deque[str] = deque(maxlen=1000)
candado_ids = threading.Lock()

# Un candado por cliente: sus mensajes se responden en orden, sin frenar a los demás clientes
candados_por_numero: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


# ---------------------------------------------------------------- utilidades

def numero_para_responder(numero: str) -> str:
    """Corrige el número de celulares de Argentina.
    WhatsApp avisa los mensajes desde '549' + número, pero para responder la API espera
    '54' + número (sin el 9). Sin esta corrección, Meta rechaza el envío."""
    if numero.startswith("549") and len(numero) == 13:
        return "54" + numero[3:]
    return numero


def a_formato_whatsapp(texto: str) -> str:
    """Adapta el Markdown del modelo al formato de WhatsApp.
    WhatsApp usa *negrita* (un asterisco) y no tiene títulos."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto)                       # **negrita** -> *negrita*
    texto = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", texto, flags=re.MULTILINE)  # ## Título -> *Título*
    return texto.strip()


def partir_mensaje(texto: str, largo: int = MAX_LARGO_MENSAJE) -> list[str]:
    """Divide un texto largo en partes que entren en un mensaje de WhatsApp, cortando en saltos de línea."""
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


def firma_valida(cuerpo: bytes, firma: str | None) -> bool:
    """Verifica que el aviso viene de Meta: la firma es un HMAC-SHA256 del cuerpo con la clave de la app.
    Si no se configuró WHATSAPP_APP_SECRET, no se verifica (útil para probar)."""
    secreto = os.environ.get("WHATSAPP_APP_SECRET")
    if not secreto:
        return True
    if not firma or not firma.startswith("sha256="):
        return False
    esperada = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, firma.removeprefix("sha256="))


def extraer_mensajes(datos: dict) -> list[dict]:
    """Saca los mensajes entrantes del aviso de Meta. Ignora avisos de estado (enviado, leído, etc.)."""
    mensajes = []
    for entrada in datos.get("entry", []):
        for cambio in entrada.get("changes", []):
            for mensaje in cambio.get("value", {}).get("messages", []):
                mensajes.append(mensaje)
    return mensajes


# ---------------------------------------------------------------- envío

def enviar_whatsapp(numero: str, texto: str) -> None:
    """Envía un mensaje de texto con la API de WhatsApp de Meta."""
    url = f"https://graph.facebook.com/{VERSION_API}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
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


# ---------------------------------------------------------------- lógica del bot

def procesar_mensaje(mensaje: dict) -> None:
    """Responde un mensaje entrante. Corre en segundo plano para contestarle rápido a Meta."""
    numero = mensaje["from"]

    if mensaje.get("type") != "text":
        enviar_whatsapp(numero, "Por ahora solo puedo leer mensajes de texto. ¿Me escribís tu consulta?")
        return

    texto = mensaje["text"]["body"].strip()
    print(f"  [whatsapp] {numero}: {texto}")

    with candados_por_numero[numero]:
        if texto.lower() in PALABRAS_REINICIO or numero not in conversaciones:
            conversaciones[numero] = [{"role": "system", "content": PROMPT_SISTEMA}]
            if texto.lower() in PALABRAS_REINICIO:
                enviar_whatsapp(numero, "Listo, empezamos de nuevo. ¿En qué te puedo ayudar?")
                return

        historial = conversaciones[numero]
        historial.append({"role": "user", "content": texto})
        try:
            respuesta = responder(historial)
        except Exception as error:
            print(f"  [whatsapp] error del agente: {error}")
            historial.pop()  # se descarta la pregunta que no se pudo responder
            respuesta = "Hubo un problema con el servicio. Probá de nuevo en un momento."
        conversaciones[numero] = recortar_historial(historial)

    enviar_whatsapp(numero, respuesta)


# ---------------------------------------------------------------- endpoints

@app.get("/")
def estado() -> dict:
    """Permite comprobar que el servidor está andando (y despertarlo si el hosting lo durmió)."""
    return {"estado": "ok", "servicio": "Asistente de Farmacia - WhatsApp"}


@app.get("/webhook", response_class=PlainTextResponse)
def verificar_webhook(request: Request) -> str:
    """Meta llama a este endpoint una vez, al configurar el webhook, para confirmar que es nuestro.
    Hay que devolver hub.challenge si el verify_token coincide con el nuestro."""
    parametros = request.query_params
    if (parametros.get("hub.mode") == "subscribe"
            and parametros.get("hub.verify_token") == os.environ.get("WHATSAPP_VERIFY_TOKEN")):
        return parametros.get("hub.challenge", "")
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/webhook")
async def recibir_webhook(request: Request, tareas: BackgroundTasks) -> dict:
    """Recibe los avisos de Meta. Responde enseguida (si tarda, Meta reintenta)
    y procesa cada mensaje en segundo plano."""
    cuerpo = await request.body()
    if not firma_valida(cuerpo, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Firma inválida")

    try:
        datos = json.loads(cuerpo)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")

    for mensaje in extraer_mensajes(datos):
        with candado_ids:
            if mensaje["id"] in ids_procesados:
                continue
            ids_procesados.append(mensaje["id"])
        tareas.add_task(procesar_mensaje, mensaje)

    return {"estado": "recibido"}
