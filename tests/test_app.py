"""Tests de la interfaz de Streamlit, sin abrir el navegador ni llamar a Groq.

AppTest ejecuta app.py en memoria y permite hacer clic en botones o escribir en el chat."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from test_agente import ClienteFalso, llamada, respuesta

RUTA_APP = str(Path(__file__).parent.parent / "app.py")


@pytest.fixture
def app(monkeypatch):
    """Prepara la app con un modelo falso. Devuelve (app, cliente_falso)."""
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    import agente

    cliente = ClienteFalso([])
    monkeypatch.setattr(agente, "cliente", cliente)
    return AppTest.from_file(RUTA_APP, default_timeout=30).run(), cliente


def boton(app, texto: str):
    return next(b for b in app.button if b.label == texto)


def conversacion(pantalla) -> list[tuple[str, str]]:
    """Devuelve los mensajes del chat sin el saludo inicial, como (rol, texto)."""
    return [(m.name, m.markdown[0].value) for m in pantalla.chat_message][1:]


def test_arranca_con_saludo_sugerencias_y_sucursales(app):
    pantalla, _ = app
    assert not pantalla.exception
    assert pantalla.chat_message[0].markdown[0].value.startswith("¡Hola!")
    etiquetas = [b.label for b in pantalla.button]
    assert "¿Tienen ibuprofeno 600?" in etiquetas
    assert "🗑️ Nueva conversación" in etiquetas
    barra = " ".join(md.value for md in pantalla.sidebar.markdown)
    assert "Sucursal Centro" in barra and "OSDE" in barra


def test_sugerencia_envia_la_pregunta_y_oculta_lo_tecnico(app):
    pantalla, cliente = app
    cliente.respuestas += [
        respuesta(tool_calls=[llamada("1", "info_farmacia", {})]),
        respuesta(content="Hoy abrimos hasta las 22."),
    ]

    boton(pantalla, "¿Hasta qué hora abren hoy?").click().run()

    assert conversacion(pantalla) == [
        ("user", "¿Hasta qué hora abren hoy?"),
        ("assistant", "Hoy abrimos hasta las 22."),
    ]
    # El cliente no ve las llamadas a herramientas
    assert len(pantalla.expander) == 0
    assert len(pantalla.code) == 0
    # Las sugerencias desaparecen cuando ya empezó la conversación
    assert [b.label for b in pantalla.button] == ["🗑️ Nueva conversación"]


def test_escapa_el_signo_pesos(app):
    pantalla, cliente = app
    cliente.respuestas.append(respuesta(content="Sale $ 4.100"))

    pantalla.chat_input[0].set_value("¿Cuánto sale?").run()

    assert conversacion(pantalla)[-1] == ("assistant", "Sale \\$ 4.100")


def test_nueva_conversacion_borra_el_historial(app):
    pantalla, cliente = app
    cliente.respuestas.append(respuesta(content="Hola"))
    pantalla.chat_input[0].set_value("Hola").run()
    assert len(conversacion(pantalla)) == 2

    boton(pantalla, "🗑️ Nueva conversación").click().run()

    assert conversacion(pantalla) == []
    assert "¿Tienen ibuprofeno 600?" in [b.label for b in pantalla.button]


def test_error_del_servicio_muestra_mensaje_amable(app):
    pantalla, _ = app  # el cliente falso no tiene respuestas: va a fallar

    pantalla.chat_input[0].set_value("Hola").run()

    assert not pantalla.exception
    assert "problema con el servicio" in conversacion(pantalla)[-1][1]
