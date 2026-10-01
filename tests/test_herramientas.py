"""Tests de las herramientas que consultan la base de la farmacia."""

import pytest

from herramientas import (
    buscar_alternativas,
    buscar_producto,
    consultar_cobertura,
    formatear_pesos,
    listar_obras_sociales,
    normalizar,
)


def nombres(resultados: list[dict]) -> list[str]:
    """Devuelve solo los nombres de los productos, para comparar más fácil."""
    return [r.get("nombre") or r.get("producto") for r in resultados]


# ---------------------------------------------------------------- utilidades

@pytest.mark.parametrize("texto, esperado", [
    ("Losartán 50 mg", "losartan50mg"),
    ("  IBUPROFENO  ", "ibuprofeno"),
    ("Pañales", "panales"),
    (None, ""),
])
def test_normalizar(texto, esperado):
    assert normalizar(texto) == esperado


@pytest.mark.parametrize("valor, esperado", [
    (4100, "$ 4.100"),
    (1234.5, "$ 1.234,50"),
    (29500, "$ 29.500"),
    (0, "$ 0"),
])
def test_formatear_pesos(valor, esperado):
    assert formatear_pesos(valor) == esperado


# ---------------------------------------------------------------- buscar_producto

def test_busca_sin_tildes():
    assert nombres(buscar_producto("losartan")) == ["Losartán 50 mg x 30 comprimidos"]


@pytest.mark.parametrize("texto", ["ibuprofeno 600", "ibuprofeno600", "Ibuprofeno 600 mg"])
def test_busca_con_distintas_escrituras(texto):
    assert nombres(buscar_producto(texto)) == ["Ibuprofeno 600 mg x 20 comprimidos"]


def test_busca_palabras_en_cualquier_orden():
    resultados = buscar_producto("dermaglos protector")
    assert len(resultados) == 2
    assert all(r["marca"] == "Dermaglós" for r in resultados)


def test_corrige_errores_de_tipeo_y_lo_indica():
    resultados = buscar_producto("amoxicilna")
    assert resultados, "debería encontrar Amoxicilina"
    assert all("Amoxicilina" in r["nombre"] for r in resultados)
    assert all(r["coincidencia_aproximada"] for r in resultados)


def test_no_encuentra_palabras_dentro_de_otras():
    # 'tos' no debe coincidir con 'medicamen-tos': solo aparecen productos para la tos
    resultados = buscar_producto("algo para la tos")
    assert resultados[0]["nombre"] == "Jarabe para la tos seca x 120 ml"
    assert all(r["categoria"] == "Tos, gripe y respiratorio" for r in resultados)


def test_busca_por_categoria():
    resultados = buscar_producto("pañales")
    assert len(resultados) == 5
    assert all(r["categoria"] == "Pañales" for r in resultados)


def test_ordena_primero_la_mejor_coincidencia():
    assert buscar_producto("vitamina c")[0]["nombre"].startswith("Vitamina C")


@pytest.mark.parametrize("texto", ["xyz", "", "   ", "para la"])
def test_texto_sin_resultados_devuelve_lista_vacia(texto):
    assert buscar_producto(texto) == []


def test_nunca_informa_cantidad_de_stock():
    for producto in buscar_producto("ibuprofeno"):
        assert "stock" not in producto
        assert isinstance(producto["hay_stock"], bool)


def test_indica_si_no_hay_stock():
    actron = buscar_producto("actron")[0]
    assert actron["hay_stock"] is False


def test_informa_condicion_de_venta():
    assert buscar_producto("tafirol")[0]["condicion_venta"] == "Venta libre"
    assert buscar_producto("amoxidal")[0]["condicion_venta"] == "Bajo receta"
    assert buscar_producto("clonazepam")[0]["condicion_venta"] == "Bajo receta archivada"


# ---------------------------------------------------------------- coberturas

def test_cobertura_con_plan():
    resultados = consultar_cobertura("amoxicilina 500", "OSDE", "210")
    assert len(resultados) == 1
    cobertura = resultados[0]
    assert cobertura["porcentaje"] == 40
    assert cobertura["precio"] == "$ 6.800"
    assert cobertura["precio_final"] == "$ 4.080"


def test_cobertura_sin_plan_devuelve_todos_los_planes():
    planes = [r["plan"] for r in consultar_cobertura("enalapril", "OSDE")]
    assert planes == ["210", "310", "410", "450", "510"]


def test_cobertura_acepta_la_palabra_plan():
    assert [r["plan"] for r in consultar_cobertura("enalapril", "OSDE", "Plan 310")] == ["310"]


def test_venta_libre_no_tiene_cobertura():
    cobertura = consultar_cobertura("tafirol", "OSDE", "210")[0]
    assert cobertura["cubierto"] is False
    assert cobertura["precio_final"] == cobertura["precio"]
    assert "venta libre" in cobertura["motivo"]


def test_diabetes_tiene_cobertura_total():
    for cobertura in consultar_cobertura("metformina 850", "Swiss Medical"):
        assert cobertura["porcentaje"] == 100
        assert cobertura["precio_final"] == "$ 0"


def test_cronicos_segun_plan():
    porcentajes = {r["plan"]: r["porcentaje"] for r in consultar_cobertura("losartan", "swiss medical")}
    assert porcentajes == {"SMG10": 60, "SMG20": 70, "SMG30": 70, "SMG40": 70}


def test_ioscor_distingue_activo_y_jubilado():
    porcentajes = {r["plan"]: r["porcentaje"] for r in consultar_cobertura("enalapril", "IOSCOR")}
    assert porcentajes == {"Activo": 50, "Jubilado": 60}


def test_tolera_tildes_y_errores_en_la_obra_social():
    assert consultar_cobertura("enalapril", "Swiss Médical", "SMG20")[0]["porcentaje"] == 70
    assert consultar_cobertura("enalapril", "ioscor", "jubilada")[0]["plan"] == "Jubilado"


def test_obra_social_desconocida_devuelve_las_disponibles():
    # 'OSPE' es otra obra social: no se debe confundir con OSDE
    respuesta = consultar_cobertura("enalapril", "OSPE")
    assert "error" in respuesta
    disponibles = [o["obra_social"] for o in respuesta["obras_sociales_disponibles"]]
    assert "OSDE" in disponibles


def test_plan_inexistente_no_se_confunde_con_uno_parecido():
    respuesta = consultar_cobertura("enalapril", "Swiss Medical", "SMG25")
    assert "error" in respuesta
    assert respuesta["planes_disponibles"] == ["SMG10", "SMG20", "SMG30", "SMG40"]


def test_listar_obras_sociales():
    obras = {o["obra_social"]: o["planes"] for o in listar_obras_sociales()}
    assert set(obras) == {"OSDE", "Swiss Medical", "IOSCOR", "PAMI"}
    assert obras["IOSCOR"] == ["Activo", "Jubilado"]


# ---------------------------------------------------------------- alternativas

def test_alternativas_tienen_stock_y_son_de_la_misma_categoria():
    alternativas = buscar_alternativas("cetirizina")
    assert alternativas
    assert all(a["categoria"] == "Antialérgicos" for a in alternativas)
    assert "Cetirizina 10 mg x 10 comprimidos" not in nombres(alternativas)
    # Solo se ofrecen productos disponibles: los sin stock no deben aparecer
    assert "Levotiroxina 100 mcg x 50 comprimidos" not in nombres(alternativas)


def test_alternativas_priorizan_mismo_principio_activo():
    primera = buscar_alternativas("diclofenac 75")[0]
    assert primera["mismo_principio_activo"] is True
    assert primera["principio_activo"] == "Diclofenac"


def test_alternativas_de_producto_inexistente():
    assert buscar_alternativas("xyz") == []


# ---------------------------------------------------------------- integridad de los datos

def test_ningun_producto_de_venta_libre_tiene_cobertura(base_de_prueba):
    import sqlite3
    with sqlite3.connect(base_de_prueba) as con:
        cantidad = con.execute(
            "SELECT COUNT(*) FROM productos WHERE condicion_venta = 'Venta libre' "
            "AND tipo_cobertura IS NOT NULL"
        ).fetchone()[0]
    assert cantidad == 0


def test_todos_los_planes_definen_los_tres_tipos_de_cobertura(base_de_prueba):
    import sqlite3
    with sqlite3.connect(base_de_prueba) as con:
        incompletos = con.execute(
            "SELECT plan_id FROM coberturas GROUP BY plan_id HAVING COUNT(*) <> 3"
        ).fetchall()
    assert incompletos == []
