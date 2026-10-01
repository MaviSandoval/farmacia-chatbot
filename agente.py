"""Agente de atención al cliente de la farmacia.
El modelo decide qué herramienta usar; el código la ejecuta y le devuelve el resultado."""

import json
import os

from dotenv import load_dotenv
from groq import Groq

from herramientas import (
    buscar_alternativas,
    buscar_producto,
    consultar_cobertura,
    info_farmacia,
    listar_obras_sociales,
)

load_dotenv()

def _obtener_clave() -> str:
    """Busca la clave en el .env (local) o en los Secrets de Streamlit Cloud."""
    clave = os.environ.get("GROQ_API_KEY")
    if not clave:
        try:
            import streamlit as st
            clave = st.secrets["GROQ_API_KEY"]
        except Exception:
            pass
    if not clave:
        raise RuntimeError("Falta GROQ_API_KEY: configurala en el archivo .env o en los Secrets de Streamlit.")
    return clave


cliente = Groq(api_key=_obtener_clave())

MODELO = "openai/gpt-oss-120b"
MAX_PASOS = 5  # tope de idas y vueltas con herramientas, para evitar loops infinitos

PROMPT_SISTEMA = """Sos el asistente virtual de atención al cliente de una farmacia.
Respondé en español rioplatense, de forma breve y amable. Usá siempre "vos", nunca "tú" ni
"usted": querés, podés, necesitás, tenés, acercate, consultá.
La farmacia vende medicamentos, perfumería, higiene, dermocosmética, productos para bebés y más.

Reglas:
- Para productos, stock, precios, coberturas, obras sociales o alternativas, usá SIEMPRE las
  herramientas. Nunca inventes datos.
- Solo informás: no ofrezcas reservas, compras, envíos ni ninguna acción que no puedas hacer.
  Si el cliente quiere comprar, indicale que se acerque a la farmacia.
- Mostrá los precios tal como vienen de las herramientas (pesos argentinos, ej: $ 4.100).
- Sobre el stock, decí solo si hay o no hay; nunca informes cantidades.
- Si un resultado tiene coincidencia_aproximada en true, aclaralo: por ejemplo,
  "No encontré 'amoxicilna', pero tengo Amoxicilina 500 mg".
- Condición de venta: si es "Bajo receta", avisá que necesita receta; si es "Bajo receta
  archivada", aclará que la farmacia se queda con la receta original.
- Coberturas: solo se cubren medicamentos bajo receta. Los productos de venta libre,
  perfumería, higiene, etc. no tienen cobertura. Aclará que el descuento es orientativo y
  que la farmacia lo confirma al validar la receta y la credencial.
- Si preguntan por cobertura y no dicen la obra social, preguntala. Si la obra social tiene
  varios planes y no dicen cuál, mostrá los planes o preguntá el plan.
- Si un producto no tiene stock, ofrecé alternativas con buscar_alternativas, pero aclará que
  cambiar de medicamento (sobre todo si es otro principio activo) debe consultarse con el
  farmacéutico o el médico.
- No des diagnósticos, no recomiendes medicamentos para síntomas ni indiques dosis: derivá al
  farmacéutico o al médico. Podés informar qué productos hay de una categoría si te lo piden.
- Para direcciones, teléfonos, horarios, medios de pago o servicios usá info_farmacia.
  Si preguntan si está abierto, respondé según abierta_ahora y horario_de_hoy de cada sucursal.
- Recordá lo que el cliente ya dijo en la conversación (por ejemplo, su obra social y plan) y
  usalo sin volver a preguntar.
- Si la consulta no tiene que ver con la farmacia, decilo amablemente."""


# Primer mensaje que ve el cliente (lo usan la web y los bots de mensajería)
SALUDO = (
    "¡Hola! 👋 Soy el asistente virtual de la farmacia. Puedo ayudarte con precios y stock de "
    "productos, coberturas de obras sociales, alternativas, horarios y medios de pago. "
    "¿Qué necesitás?"
)

# Descripción de las herramientas en formato JSON Schema: es lo que "lee" el modelo
HERRAMIENTAS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_producto",
            "description": (
                "Busca productos del catálogo (medicamentos, perfumería, higiene, bebés, etc.) por nombre, "
                "marca, principio activo o categoría. Tolera tildes y errores de tipeo. Devuelve precio, "
                "si hay stock y la condición de venta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {
                        "type": "string",
                        "description": "Palabras clave, ej: 'ibuprofeno 600', 'protector solar', 'pañales talle G'",
                    },
                },
                "required": ["texto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_cobertura",
            "description": (
                "Indica si una obra social cubre un producto, con el porcentaje de descuento y el precio final. "
                "Si la obra social o el plan no existen, devuelve un error con las opciones disponibles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "producto": {"type": "string", "description": "Nombre, marca o principio activo del producto"},
                    "obra_social": {"type": "string", "description": "Nombre de la obra social, ej: 'OSDE', 'PAMI'"},
                    "plan": {"type": "string", "description": "Plan de la obra social (opcional), ej: '210', 'Jubilado'"},
                },
                "required": ["producto", "obra_social"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_obras_sociales",
            "description": "Lista las obras sociales y prepagas con las que trabaja la farmacia, con sus planes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "info_farmacia",
            "description": (
                "Devuelve las sucursales (dirección, teléfono, horarios y si están abiertas ahora), "
                "los medios de pago y los servicios de la farmacia."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_alternativas",
            "description": "Busca productos con stock de la misma categoría que el producto indicado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "producto": {"type": "string", "description": "Nombre o principio activo del producto sin stock"},
                },
                "required": ["producto"],
            },
        },
    },
]

# Nombre que usa el modelo -> función real de Python
FUNCIONES = {
    "buscar_producto": buscar_producto,
    "consultar_cobertura": consultar_cobertura,
    "listar_obras_sociales": listar_obras_sociales,
    "info_farmacia": info_farmacia,
    "buscar_alternativas": buscar_alternativas,
}


def ejecutar_herramienta(nombre: str, argumentos_json: str) -> str:
    """Ejecuta la herramienta pedida por el modelo y devuelve el resultado como JSON."""
    try:
        funcion = FUNCIONES[nombre]
        argumentos = json.loads(argumentos_json or "{}")
        resultado = funcion(**argumentos)
    except Exception as error:
        # Si algo falla, se lo contamos al modelo en vez de romper el programa
        resultado = {"error": str(error)}
    return json.dumps(resultado, ensure_ascii=False)


def responder(mensajes: list[dict]) -> str:
    """Loop del agente: consulta al modelo y ejecuta herramientas hasta obtener la respuesta final."""
    for _ in range(MAX_PASOS):
        respuesta = cliente.chat.completions.create(
            model=MODELO,
            messages=mensajes,
            tools=HERRAMIENTAS,
            tool_choice="auto",
        )
        mensaje = respuesta.choices[0].message

        # Sin llamadas a herramientas = respuesta final
        if not mensaje.tool_calls:
            mensajes.append({"role": "assistant", "content": mensaje.content})
            return mensaje.content

        # Guardamos en el historial qué herramientas pidió el modelo
        mensajes.append({
            "role": "assistant",
            "content": mensaje.content or "",
            "tool_calls": [
                {
                    "id": llamada.id,
                    "type": "function",
                    "function": {"name": llamada.function.name, "arguments": llamada.function.arguments},
                }
                for llamada in mensaje.tool_calls
            ],
        })

        # Ejecutamos cada herramienta y le devolvemos el resultado
        for llamada in mensaje.tool_calls:
            print(f"  [herramienta] {llamada.function.name}({llamada.function.arguments})")
            resultado = ejecutar_herramienta(llamada.function.name, llamada.function.arguments)
            mensajes.append({"role": "tool", "tool_call_id": llamada.id, "content": resultado})

    texto = "Perdón, no pude resolver tu consulta. ¿Podés reformularla?"
    mensajes.append({"role": "assistant", "content": texto})
    return texto


def main() -> None:
    mensajes = [{"role": "system", "content": PROMPT_SISTEMA}]
    print("Asistente de Farmacia — escribí 'salir' para terminar\n")

    while True:
        pregunta = input("Vos: ").strip()
        if pregunta.lower() in ("salir", "exit"):
            break
        if not pregunta:
            continue

        mensajes.append({"role": "user", "content": pregunta})
        try:
            print(f"Bot: {responder(mensajes)}\n")
        except Exception as error:
            print(f"Bot: Hubo un problema con el servicio ({error}). Probá de nuevo.\n")


if __name__ == "__main__":
    main()