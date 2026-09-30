"""Interfaz web del asistente de farmacia con Streamlit."""

import streamlit as st

from agente import PROMPT_SISTEMA, responder

st.set_page_config(page_title="Asistente de Farmacia", page_icon="💊")
st.title("💊 Asistente de Farmacia")
st.caption("Demo: consultá stock, precios, coberturas de obras sociales y alternativas. Datos ficticios.")


def mostrar(texto: str) -> None:
    """Muestra texto en formato Markdown. Escapa el $ para que Streamlit no lo tome como fórmula matemática."""
    st.markdown(texto.replace("$", "\\$"))


# El historial vive en session_state para no perderse entre interacciones
if "mensajes" not in st.session_state:
    st.session_state.mensajes = [{"role": "system", "content": PROMPT_SISTEMA}]

# Mostrar la conversación previa (sin el prompt de sistema ni los pasos internos de herramientas)
for mensaje in st.session_state.mensajes:
    if mensaje["role"] in ("user", "assistant") and mensaje.get("content"):
        with st.chat_message(mensaje["role"]):
            mostrar(mensaje["content"])

if pregunta := st.chat_input("Escribí tu consulta..."):
    with st.chat_message("user"):
        mostrar(pregunta)
    st.session_state.mensajes.append({"role": "user", "content": pregunta})

    with st.chat_message("assistant"):
        with st.spinner("Consultando..."):
            try:
                texto = responder(st.session_state.mensajes)
            except Exception:
                texto = "Hubo un problema con el servicio. Probá de nuevo en un momento."
        mostrar(texto)