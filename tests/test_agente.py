"""Tests del agente sin llamar a la API de Groq.

Se reemplaza el cliente real por uno falso que devuelve respuestas guionadas.
Así se prueba el loop del agente (pedir herramienta -> ejecutarla -> responder)
sin gastar cuota, sin internet y sin clave real."""

import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def agente(monkeypatch):
    """Importa agente.py con una clave falsa (no se usa: el cliente se reemplaza en cada test)."""
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    import agente as modulo
    return modulo


def llamada(id_: str, nombre: str, argumentos: dict):
    """Arma una llamada a herramienta con la misma forma que devuelve la API."""
    return SimpleNamespace(
        id=id_,
        function=SimpleNamespace(name=nombre, arguments=json.dumps(argumentos)),
    )


def respuesta(content=None, tool_calls=None):
    """Arma una respuesta del modelo con la misma forma que devuelve la API."""
    mensaje = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)])


class ClienteFalso:
    """Imita cliente.chat.completions.create(...) devolviendo respuestas en orden."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        # Se guarda una copia de los mensajes para revisar qué se le mandó al modelo
        self.pedidos.append([dict(m) for m in kwargs["messages"]])
        return self.respuestas.pop(0)


def test_ejecutar_herramienta_devuelve_json(agente):
    resultado = json.loads(agente.ejecutar_herramienta("buscar_producto", '{"texto": "losartan"}'))
    assert resultado[0]["nombre"] == "Losartán 50 mg x 30 comprimidos"


def test_ejecutar_herramienta_sin_argumentos(agente):
    resultado = json.loads(agente.ejecutar_herramienta("listar_obras_sociales", ""))
    assert len(resultado) == 4


@pytest.mark.parametrize("nombre, argumentos", [
    ("herramienta_inexistente", "{}"),
    ("buscar_producto", "esto no es json"),
    ("buscar_producto", '{"parametro_equivocado": 1}'),
])
def test_ejecutar_herramienta_con_error_no_rompe(agente, nombre, argumentos):
    resultado = json.loads(agente.ejecutar_herramienta(nombre, argumentos))
    assert "error" in resultado


def test_todas_las_herramientas_declaradas_existen(agente):
    declaradas = {h["function"]["name"] for h in agente.HERRAMIENTAS}
    assert declaradas == set(agente.FUNCIONES)


def test_loop_ejecuta_herramienta_y_responde(agente, monkeypatch):
    cliente = ClienteFalso([
        respuesta(tool_calls=[llamada("1", "buscar_producto", {"texto": "ibuprofeno 600"})]),
        respuesta(content="Sí, hay Ibuprofeno 600 a $ 4.100."),
    ])
    monkeypatch.setattr(agente, "cliente", cliente)

    mensajes = [{"role": "system", "content": agente.PROMPT_SISTEMA},
                {"role": "user", "content": "¿Tienen ibuprofeno 600?"}]
    texto = agente.responder(mensajes)

    assert texto == "Sí, hay Ibuprofeno 600 a $ 4.100."
    # En la segunda vuelta el modelo recibió el resultado real de la herramienta
    mensaje_tool = cliente.pedidos[1][-1]
    assert mensaje_tool["role"] == "tool"
    assert mensaje_tool["tool_call_id"] == "1"
    assert "Ibuprofeno 600 mg x 20 comprimidos" in mensaje_tool["content"]
    # Y la respuesta final quedó guardada en el historial
    assert mensajes[-1] == {"role": "assistant", "content": texto}


def test_loop_encadena_varias_herramientas(agente, monkeypatch):
    cliente = ClienteFalso([
        respuesta(tool_calls=[llamada("1", "buscar_producto", {"texto": "cetirizina"})]),
        respuesta(tool_calls=[llamada("2", "buscar_alternativas", {"producto": "cetirizina"})]),
        respuesta(content="No hay cetirizina, pero hay loratadina."),
    ])
    monkeypatch.setattr(agente, "cliente", cliente)

    texto = agente.responder([{"role": "user", "content": "Necesito cetirizina"}])

    assert texto == "No hay cetirizina, pero hay loratadina."
    assert len(cliente.pedidos) == 3


def test_loop_se_corta_si_no_termina(agente, monkeypatch):
    # Un modelo que pide herramientas para siempre no debe colgar el programa
    pedidos_infinitos = [
        respuesta(tool_calls=[llamada(str(i), "listar_obras_sociales", {})])
        for i in range(agente.MAX_PASOS)
    ]
    monkeypatch.setattr(agente, "cliente", ClienteFalso(pedidos_infinitos))

    mensajes = [{"role": "user", "content": "hola"}]
    texto = agente.responder(mensajes)

    assert "no pude resolver" in texto
    # El mensaje de disculpa también queda en el historial, para que la interfaz lo muestre
    assert mensajes[-1] == {"role": "assistant", "content": texto}
