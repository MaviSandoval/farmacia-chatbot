"""Interfaz web del asistente de farmacia con Streamlit."""

import streamlit as st

from agente import PROMPT_SISTEMA, SALUDO, responder
from herramientas import info_farmacia, listar_obras_sociales

SUGERENCIAS = [
    "¿Tienen ibuprofeno 600?",
    "¿OSDE 210 cubre el losartán?",
    "¿Hasta qué hora abren hoy?",
    "Busco protector solar para niños",
    "Necesito diclofenac 75",
    "¿Qué medios de pago aceptan?",
]

st.set_page_config(page_title="Asistente de Farmacia", page_icon="💊")


def mostrar(texto: str) -> None:
    """Muestra texto en formato Markdown. Escapa el $ para que Streamlit no lo tome como fórmula matemática."""
    st.markdown(texto.replace("$", "\\$"))


def nueva_conversacion() -> None:
    """Reinicia el historial dejando solo el prompt de sistema."""
    st.session_state.mensajes = [{"role": "system", "content": PROMPT_SISTEMA}]


# ---------------------------------------------------------------- barra lateral

with st.sidebar:
    st.header("💊 Farmacia")

    for sucursal in info_farmacia()["sucursales"]:
        estado = "🟢 Abierta ahora" if sucursal["abierta_ahora"] else "🔴 Cerrada ahora"
        st.markdown(
            f"**{sucursal['nombre']}**  \n"
            f"📍 {sucursal['direccion']}  \n"
            f"📞 {sucursal['telefono']}  \n"
            f"🕒 Hoy: {sucursal['horario_de_hoy']} · {estado}"
        )

    st.subheader("Obras sociales")
    for obra in listar_obras_sociales():
        st.markdown(f"- **{obra['obra_social']}**: {', '.join(obra['planes'])}")

    st.button("🗑️ Nueva conversación", on_click=nueva_conversacion, width="stretch")
    st.caption("Demo con datos ficticios. No reemplaza la consulta con tu médico o farmacéutico.")


# ---------------------------------------------------------------- conversación

st.title("💊 Asistente de Farmacia")

# El historial vive en session_state para no perderse entre interacciones
if "mensajes" not in st.session_state:
    nueva_conversacion()

with st.chat_message("assistant", avatar="💊"):
    st.markdown(SALUDO)

# Solo se muestran las preguntas del cliente y las respuestas finales del asistente;
# los pasos internos (llamadas a herramientas y sus resultados) quedan ocultos
for mensaje in st.session_state.mensajes:
    if mensaje["role"] == "user":
        with st.chat_message("user"):
            mostrar(mensaje["content"])
    elif mensaje["role"] == "assistant" and mensaje.get("content") and not mensaje.get("tool_calls"):
        with st.chat_message("assistant", avatar="💊"):
            mostrar(mensaje["content"])

# Preguntas sugeridas: solo al empezar, cuando todavía no hay mensajes
pregunta_sugerida = None
if len(st.session_state.mensajes) == 1:
    columnas = st.columns(2)
    for indice, sugerencia in enumerate(SUGERENCIAS):
        if columnas[indice % 2].button(sugerencia, width="stretch"):
            pregunta_sugerida = sugerencia

pregunta = st.chat_input("Escribí tu consulta...") or pregunta_sugerida
if pregunta:
    st.session_state.mensajes.append({"role": "user", "content": pregunta})
    with st.spinner("Consultando..."):
        try:
            responder(st.session_state.mensajes)
        except Exception:
            st.session_state.mensajes.append({
                "role": "assistant",
                "content": "Hubo un problema con el servicio. Probá de nuevo en un momento.",
            })
    st.rerun()  # vuelve a dibujar la página con la conversación actualizada
