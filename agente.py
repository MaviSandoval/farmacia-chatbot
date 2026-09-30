"""Agente de atención al cliente de la farmacia.
El modelo decide qué herramienta usar; el código la ejecuta y le devuelve el resultado."""

import json
import os

from dotenv import load_dotenv
from groq import Groq

from herramientas import buscar_alternativas, buscar_producto, consultar_cobertura

load_dotenv()
cliente = Groq(api_key=os.environ["GROQ_API_KEY"])

MODELO = "openai/gpt-oss-120b"
MAX_PASOS = 5  # tope de idas y vueltas con herramientas, para evitar loops infinitos

PROMPT_SISTEMA = """Sos el asistente virtual de atención al cliente de una farmacia.
Respondé en español rioplatense, de forma breve y amable.

Reglas:
- Para stock, precios, coberturas o alternativas, usá SIEMPRE las herramientas. Nunca inventes datos.
- Solo informás: no ofrezcas reservas, compras, envíos ni ninguna acción que no puedas hacer.
  Si el cliente quiere comprar, indicale que se acerque a la farmacia.
- Mostrá los precios tal como vienen de las herramientas (pesos argentinos, ej: $ 4.100).
- Sobre el stock, decí solo si hay o no hay; nunca informes cantidades.
- Si un producto requiere receta, avisalo.
- Si preguntan por cobertura y no dicen la obra social, preguntala.
- Si un producto no tiene stock, ofrecé alternativas con buscar_alternativas, pero aclará que
  cambiar de medicamento (sobre todo si es otro principio activo) debe consultarse con el
  farmacéutico o el médico.
- No des diagnósticos ni indiques dosis: derivá al farmacéutico o al médico.
- Si la consulta no tiene que ver con la farmacia, decilo amablemente."""


# Descripción de las herramientas en formato JSON Schema: es lo que "lee" el modelo
HERRAMIENTAS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_producto",
            "description": "Busca productos por nombre o principio activo. Devuelve precio, stock y si requiere receta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Nombre o principio activo, ej: 'ibuprofeno 600'"},
                },
                "required": ["texto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_cobertura",
            "description": "Indica si una obra social cubre un producto, con el porcentaje de descuento y el precio final.",
            "parameters": {
                "type": "object",
                "properties": {
                    "producto": {"type": "string", "description": "Nombre o principio activo del producto"},
                    "obra_social": {"type": "string", "description": "Nombre de la obra social, ej: 'OSDE'"},
                    "plan": {"type": "string", "description": "Plan de la obra social (opcional), ej: '210'"},
                },
                "required": ["producto", "obra_social"],
            },
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

    return "Perdón, no pude resolver tu consulta. ¿Podés reformularla?"


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