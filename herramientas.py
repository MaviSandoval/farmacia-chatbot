"""Herramientas que el agente puede usar para consultar la base de la farmacia.
Cada función devuelve datos simples (listas de diccionarios) para que el modelo
pueda leerlos y armar la respuesta."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

RUTA_BD = Path(__file__).parent / "farmacia_demo.db"


def _consultar(sql: str, parametros: list) -> list[dict]:
    """Ejecuta una consulta SELECT y devuelve cada fila como diccionario."""
    with closing(sqlite3.connect(RUTA_BD)) as con:
        con.row_factory = sqlite3.Row
        filas = con.execute(sql, parametros).fetchall()
    return [dict(fila) for fila in filas]


def buscar_producto(texto: str) -> list[dict]:
    """Busca productos por nombre o principio activo.
    Devuelve nombre, categoría, precio, stock y si requiere receta."""
    filas = _consultar(
        """
        SELECT p.nombre, p.principio_activo, c.nombre AS categoria,
               p.precio, p.stock, p.requiere_receta
        FROM productos p
        JOIN categorias c ON c.id = p.categoria_id
        WHERE p.nombre LIKE ? OR p.principio_activo LIKE ?
        ORDER BY p.nombre
        """,
        [f"%{texto}%", f"%{texto}%"],
    )
    for fila in filas:
        fila["requiere_receta"] = bool(fila["requiere_receta"])
        fila["disponible"] = fila["stock"] > 0
    return filas


def consultar_cobertura(producto: str, obra_social: str, plan: str | None = None) -> list[dict]:
    """Indica si una obra social (y opcionalmente un plan) cubre un producto,
    con el porcentaje de descuento y el precio final. Si no se indica el plan,
    devuelve todos los planes de esa obra social."""
    sql = """
        SELECT p.nombre AS producto, c.nombre AS categoria,
               os.nombre AS obra_social, pl.nombre AS plan,
               p.precio, COALESCE(co.porcentaje, 0) AS porcentaje
        FROM productos p
        JOIN categorias c       ON c.id = p.categoria_id
        CROSS JOIN planes pl
        JOIN obras_sociales os  ON os.id = pl.obra_social_id
        LEFT JOIN coberturas co ON co.plan_id = pl.id AND co.categoria_id = p.categoria_id
        WHERE (p.nombre LIKE ? OR p.principio_activo LIKE ?)
          AND os.nombre LIKE ?
    """
    parametros = [f"%{producto}%", f"%{producto}%", f"%{obra_social}%"]

    if plan:
        sql += " AND pl.nombre LIKE ?"
        parametros.append(f"%{plan}%")

    sql += " ORDER BY p.nombre, pl.nombre"

    filas = _consultar(sql, parametros)
    for fila in filas:
        fila["cubierto"] = fila["porcentaje"] > 0
        fila["precio_final"] = round(fila["precio"] * (1 - fila["porcentaje"] / 100), 2)
    return filas


def buscar_alternativas(producto: str) -> list[dict]:
    """Busca productos con stock de la misma categoría que el producto indicado.
    Primero aparecen los que tienen el mismo principio activo, después el resto
    ordenado por precio."""
    filas = _consultar(
        """
        SELECT alt.nombre, alt.principio_activo, c.nombre AS categoria,
               alt.precio, alt.stock, alt.requiere_receta,
               MAX(alt.principio_activo = orig.principio_activo) AS mismo_principio_activo
        FROM productos orig
        JOIN productos alt ON alt.categoria_id = orig.categoria_id AND alt.id <> orig.id
        JOIN categorias c  ON c.id = alt.categoria_id
        WHERE (orig.nombre LIKE ? OR orig.principio_activo LIKE ?)
          AND alt.stock > 0
        GROUP BY alt.id
        ORDER BY mismo_principio_activo DESC, alt.precio
        """,
        [f"%{producto}%", f"%{producto}%"],
    )
    for fila in filas:
        fila["requiere_receta"] = bool(fila["requiere_receta"])
        fila["mismo_principio_activo"] = bool(fila["mismo_principio_activo"])
    return filas


if __name__ == "__main__":
    def mostrar(titulo: str, datos: list[dict]) -> None:
        print(f"\n=== {titulo} ===")
        print(json.dumps(datos, indent=2, ensure_ascii=False))

    mostrar("buscar_producto('ibuprofeno')", buscar_producto("ibuprofeno"))
    mostrar("consultar_cobertura('amoxicilina', 'osde')", consultar_cobertura("amoxicilina", "osde"))
    mostrar("consultar_cobertura('loratadina', 'ioscor')", consultar_cobertura("loratadina", "ioscor"))
    mostrar("buscar_alternativas('diclofenac')", buscar_alternativas("diclofenac"))