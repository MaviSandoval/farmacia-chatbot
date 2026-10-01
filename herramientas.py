"""Herramientas que el agente puede usar para consultar la base de la farmacia.
Cada función devuelve datos simples (listas o diccionarios) para que el modelo
pueda leerlos y armar la respuesta. Solo se devuelven datos que se pueden mostrar
al cliente: por ejemplo, se informa si hay stock, pero no la cantidad.

Las búsquedas toleran mayúsculas, tildes, espacios, palabras sueltas en cualquier
orden y errores de tipeo."""

import difflib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUTA_BD = Path(__file__).parent / "farmacia_demo.db"

MAX_RESULTADOS = 20

# Palabras que no aportan a la búsqueda ("algo para la tos" -> "tos")
PALABRAS_IGNORADAS = {
    "de", "del", "la", "el", "los", "las", "para", "con", "sin", "y", "o", "en", "un", "una",
    "unos", "unas", "algo", "que", "tienen", "tenes", "hay", "x", "por", "al",
    "remedio", "remedios", "necesito", "busco", "quiero", "venden",
}

DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
ZONA_ARGENTINA = timezone(timedelta(hours=-3))  # Argentina no usa horario de verano

MOTIVO_SIN_COBERTURA = ("Es de venta libre o no es un medicamento: las obras sociales "
                        "solo cubren medicamentos bajo receta.")


# ---------------------------------------------------------------- utilidades

def normalizar(texto: str | None) -> str:
    """Deja el texto en minúsculas, sin tildes y solo con letras y números.
    Ej: 'Losartán 50 mg' -> 'losartan50mg'. Sirve para comparar sin importar cómo se escribió."""
    if texto is None:
        return ""
    descompuesto = unicodedata.normalize("NFD", texto)  # separa 'á' en 'a' + tilde
    sin_tildes = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return "".join(c for c in sin_tildes.lower() if c.isalnum())


def _palabras(texto: str | None) -> list[str]:
    """Separa un texto en palabras normalizadas, sin las palabras que no aportan."""
    palabras = (normalizar(p) for p in re.split(r"[\s/,+\-]+", texto or ""))
    return [p for p in palabras if p and p not in PALABRAS_IGNORADAS]


def _consultar(sql: str, parametros: list | tuple = ()) -> list[dict]:
    """Ejecuta una consulta SELECT y devuelve cada fila como diccionario."""
    with closing(sqlite3.connect(RUTA_BD)) as con:
        con.row_factory = sqlite3.Row
        filas = con.execute(sql, parametros).fetchall()
    return [dict(fila) for fila in filas]


def formatear_pesos(valor: float) -> str:
    """Formatea un número como precio en pesos argentinos: 4100 -> '$ 4.100', 1234.5 -> '$ 1.234,50'."""
    texto = f"{valor:,.2f}"  # formato inglés: 4,100.00
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")  # formato argentino: 4.100,00
    if texto.endswith(",00"):
        texto = texto[:-3]
    return f"$ {texto}"


# ---------------------------------------------------------------- búsqueda de productos

def _fragmentos(palabras: list[str]) -> set[str]:
    """Devuelve el texto que arranca en cada palabra: ['ibuprofeno', '600', 'mg'] ->
    {'ibuprofeno600mg', '600mg', 'mg'}. Permite encontrar 'ibuprofeno600' o '600mg'
    escritos todo junto, sin encontrar 'tos' adentro de 'medicamentos'."""
    return {"".join(palabras[i:]) for i in range(len(palabras))}


def _catalogo() -> list[dict]:
    """Devuelve cada producto preparado para buscar: sus palabras y fragmentos normalizados.
    Los campos principales (nombre, marca, principio activo) pesan más que la categoría y el rubro."""
    filas = _consultar(
        """
        SELECT p.id, p.nombre, p.marca, p.principio_activo, c.nombre AS categoria, r.nombre AS rubro
        FROM productos p
        JOIN categorias c ON c.id = p.categoria_id
        JOIN rubros r     ON r.id = c.rubro_id
        """
    )
    catalogo = []
    for fila in filas:
        principales = [_palabras(fila[campo]) for campo in ("nombre", "marca", "principio_activo")]
        secundarios = [_palabras(fila[campo]) for campo in ("categoria", "rubro")]
        catalogo.append({
            "id": fila["id"],
            "palabras_principales": {p for campo in principales for p in campo},
            "fragmentos_principales": set().union(*(_fragmentos(campo) for campo in principales)),
            "fragmentos": set().union(*(_fragmentos(campo) for campo in principales + secundarios)),
            "palabras": {p for campo in principales + secundarios for p in campo},
        })
    return catalogo


def _coincide(palabra: str, fragmentos: set[str]) -> bool:
    """True si algún fragmento del producto empieza con la palabra buscada."""
    return any(fragmento.startswith(palabra) for fragmento in fragmentos)


def _buscar_ids(texto: str) -> tuple[dict[int, int], bool]:
    """Busca productos que contengan TODAS las palabras del texto, en cualquier orden.
    Si una palabra no aparece en el catálogo, la reemplaza por la más parecida (errores
    de tipeo) o la descarta. Devuelve {id: puntaje} y si la coincidencia es aproximada.
    El puntaje sirve para ordenar: pesa más coincidir en el nombre que en la categoría."""
    palabras = _palabras(texto)
    if not palabras:
        return {}, False

    catalogo = _catalogo()
    vocabulario = set().union(*(producto["palabras"] for producto in catalogo))
    aproximada = False
    buscadas = []

    for palabra in palabras:
        if any(_coincide(palabra, producto["fragmentos"]) for producto in catalogo):
            buscadas.append(palabra)
            continue
        parecidas = difflib.get_close_matches(palabra, vocabulario, n=1, cutoff=0.75)
        if parecidas:
            buscadas.append(parecidas[0])
        aproximada = True  # se corrigió o se descartó una palabra

    if not buscadas:
        return {}, False

    puntajes = {}
    for producto in catalogo:
        if all(_coincide(b, producto["fragmentos"]) for b in buscadas):
            puntajes[producto["id"]] = sum(
                2 * (b in producto["palabras_principales"]) + _coincide(b, producto["fragmentos_principales"])
                for b in buscadas
            )
    return puntajes, aproximada


def _marcadores(cantidad: int) -> str:
    """Devuelve '?, ?, ?' para usar en un IN (...) con parámetros."""
    return ", ".join("?" * cantidad)


def buscar_producto(texto: str) -> list[dict]:
    """Busca productos por nombre, marca, principio activo o categoría.
    Devuelve precio, si hay stock y la condición de venta (venta libre o bajo receta)."""
    puntajes, aproximada = _buscar_ids(texto)
    if not puntajes:
        return []

    filas = _consultar(
        f"""
        SELECT p.id, p.nombre, p.marca, p.principio_activo, c.nombre AS categoria, r.nombre AS rubro,
               p.precio, p.stock, p.condicion_venta
        FROM productos p
        JOIN categorias c ON c.id = p.categoria_id
        JOIN rubros r     ON r.id = c.rubro_id
        WHERE p.id IN ({_marcadores(len(puntajes))})
        """,
        list(puntajes),
    )
    # Primero los que mejor coinciden; a igual puntaje, los que tienen stock
    filas.sort(key=lambda fila: (-puntajes[fila["id"]], fila["stock"] == 0, fila["nombre"]))

    resultado = []
    for fila in filas[:MAX_RESULTADOS]:
        del fila["id"]
        if fila["principio_activo"] is None:
            del fila["principio_activo"]
        fila["precio"] = formatear_pesos(fila["precio"])
        fila["hay_stock"] = fila.pop("stock") > 0  # se saca la cantidad y queda solo sí/no
        fila["coincidencia_aproximada"] = aproximada
        resultado.append(fila)
    return resultado


# ---------------------------------------------------------------- obras sociales y coberturas

def listar_obras_sociales() -> list[dict]:
    """Devuelve las obras sociales con las que trabaja la farmacia y sus planes."""
    filas = _consultar(
        """
        SELECT os.nombre AS obra_social, os.tipo, pl.nombre AS plan
        FROM obras_sociales os
        JOIN planes pl ON pl.obra_social_id = os.id
        ORDER BY os.nombre, pl.id
        """
    )
    resultado: dict[str, dict] = {}
    for fila in filas:
        obra = resultado.setdefault(fila["obra_social"], {
            "obra_social": fila["obra_social"], "tipo": fila["tipo"], "planes": [],
        })
        obra["planes"].append(fila["plan"])
    return list(resultado.values())


def _resolver_planes(obra_social: str, plan: str | None) -> tuple[list[int], dict | None]:
    """Encuentra los ids de los planes pedidos, tolerando tildes y errores de tipeo.
    Si no los encuentra, devuelve un diccionario de error con las opciones disponibles."""
    planes = _consultar(
        """
        SELECT pl.id, pl.nombre AS plan, os.nombre AS obra_social
        FROM planes pl
        JOIN obras_sociales os ON os.id = pl.obra_social_id
        """
    )

    buscada = normalizar(obra_social)
    candidatos = [p for p in planes if buscada and buscada in normalizar(p["obra_social"])]
    if not candidatos:
        nombres = {normalizar(p["obra_social"]): p["obra_social"] for p in planes}
        # Umbral alto: 'OSPE' no debe confundirse con 'OSDE', son obras sociales distintas
        parecida = difflib.get_close_matches(buscada, nombres, n=1, cutoff=0.85)
        candidatos = [p for p in planes if parecida and normalizar(p["obra_social"]) == parecida[0]]
    if not candidatos:
        return [], {
            "error": f"La farmacia no trabaja con la obra social '{obra_social}'.",
            "obras_sociales_disponibles": listar_obras_sociales(),
        }

    plan_buscado = normalizar(plan).removeprefix("plan")  # 'Plan 210' -> '210'
    if plan_buscado:
        con_plan = [p for p in candidatos if plan_buscado in normalizar(p["plan"])]
        # Solo se corrigen planes con nombre (ej. 'jubilada'); un número distinto
        # ('SMG25') es otro plan y no se debe confundir con uno parecido ('SMG20')
        if not con_plan and not any(c.isdigit() for c in plan_buscado):
            nombres = {normalizar(p["plan"]) for p in candidatos}
            parecido = difflib.get_close_matches(plan_buscado, nombres, n=1, cutoff=0.75)
            con_plan = [p for p in candidatos if parecido and normalizar(p["plan"]) == parecido[0]]
        if not con_plan:
            return [], {
                "error": f"No existe el plan '{plan}' en {candidatos[0]['obra_social']}.",
                "planes_disponibles": [p["plan"] for p in candidatos],
            }
        candidatos = con_plan

    return [p["id"] for p in candidatos], None


def consultar_cobertura(producto: str, obra_social: str, plan: str | None = None) -> list[dict] | dict:
    """Indica si una obra social (y opcionalmente un plan) cubre un producto,
    con el porcentaje de descuento y el precio final. Si no se indica el plan,
    devuelve todos los planes de esa obra social."""
    ids_planes, error = _resolver_planes(obra_social, plan)
    if error:
        return error

    puntajes, aproximada = _buscar_ids(producto)
    if not puntajes:
        return []
    ids_productos = list(puntajes)

    filas = _consultar(
        f"""
        SELECT p.nombre AS producto, p.marca, p.condicion_venta,
               os.nombre AS obra_social, pl.nombre AS plan,
               p.precio, tc.descripcion AS tipo_de_tratamiento,
               COALESCE(co.porcentaje, 0) AS porcentaje
        FROM productos p
        CROSS JOIN planes pl
        JOIN obras_sociales os        ON os.id = pl.obra_social_id
        LEFT JOIN tipos_cobertura tc  ON tc.codigo = p.tipo_cobertura
        LEFT JOIN coberturas co       ON co.plan_id = pl.id AND co.tipo_cobertura = p.tipo_cobertura
        WHERE p.id IN ({_marcadores(len(ids_productos))})
          AND pl.id IN ({_marcadores(len(ids_planes))})
        ORDER BY p.nombre, pl.id
        LIMIT {MAX_RESULTADOS}
        """,
        ids_productos + ids_planes,
    )
    for fila in filas:
        precio_final = fila["precio"] * (1 - fila["porcentaje"] / 100)
        fila["cubierto"] = fila["porcentaje"] > 0
        fila["precio"] = formatear_pesos(fila["precio"])
        fila["precio_final"] = formatear_pesos(precio_final)
        if not fila["cubierto"]:
            fila["motivo"] = MOTIVO_SIN_COBERTURA
            del fila["tipo_de_tratamiento"]
        fila["coincidencia_aproximada"] = aproximada
    return filas


# ---------------------------------------------------------------- alternativas

def buscar_alternativas(producto: str) -> list[dict]:
    """Busca productos con stock de la misma categoría que el producto indicado.
    Primero aparecen los que tienen el mismo principio activo, después el resto
    ordenado por precio."""
    puntajes, _ = _buscar_ids(producto)
    if not puntajes:
        return []
    ids = list(puntajes)

    filas = _consultar(
        f"""
        SELECT alt.nombre, alt.marca, alt.principio_activo, c.nombre AS categoria,
               alt.precio, alt.condicion_venta,
               COALESCE(MAX(alt.principio_activo = orig.principio_activo), 0) AS mismo_principio_activo
        FROM productos orig
        JOIN productos alt ON alt.categoria_id = orig.categoria_id AND alt.id <> orig.id
        JOIN categorias c  ON c.id = alt.categoria_id
        WHERE orig.id IN ({_marcadores(len(ids))})
          AND alt.stock > 0
        GROUP BY alt.id
        ORDER BY mismo_principio_activo DESC, alt.precio
        LIMIT 10
        """,
        ids,
    )
    for fila in filas:
        if fila["principio_activo"] is None:
            del fila["principio_activo"]
        fila["precio"] = formatear_pesos(fila["precio"])
        fila["mismo_principio_activo"] = bool(fila["mismo_principio_activo"])
    return filas


# ---------------------------------------------------------------- información de la farmacia

def _horarios_de(sucursal_id: int) -> dict[str, dict]:
    """Devuelve {día: {'apertura', 'cierre'}} de una sucursal. Los días que no figuran, cierra."""
    filas = _consultar("SELECT dia, apertura, cierre FROM horarios WHERE sucursal_id = ?", [sucursal_id])
    return {fila["dia"]: fila for fila in filas}


def _info_farmacia(ahora: datetime) -> dict:
    """Arma la información de la farmacia para un momento dado (separado para poder testearlo)."""
    hoy = DIAS_SEMANA[ahora.weekday()]  # weekday(): 0 = lunes
    hora = ahora.strftime("%H:%M")

    sucursales = []
    for sucursal in _consultar("SELECT id, nombre, direccion, telefono FROM sucursales ORDER BY id"):
        horarios = _horarios_de(sucursal["id"])
        de_hoy = horarios.get(hoy)
        sucursales.append({
            "nombre": sucursal["nombre"],
            "direccion": sucursal["direccion"],
            "telefono": sucursal["telefono"],
            "horario_de_hoy": f"{de_hoy['apertura']} a {de_hoy['cierre']}" if de_hoy else "Cerrado",
            # Las horas 'HH:MM' se pueden comparar como texto: '08:00' < '21:30'
            "abierta_ahora": bool(de_hoy and de_hoy["apertura"] <= hora < de_hoy["cierre"]),
            "horarios": [
                f"{dia}: {horarios[dia]['apertura']} a {horarios[dia]['cierre']}" if dia in horarios
                else f"{dia}: cerrado"
                for dia in DIAS_SEMANA
            ],
        })

    medios_pago = [
        f"{fila['nombre']} ({fila['detalle']})" if fila["detalle"] else fila["nombre"]
        for fila in _consultar("SELECT nombre, detalle FROM medios_pago ORDER BY id")
    ]
    servicios = [
        f"{fila['nombre']}: {fila['detalle']}"
        for fila in _consultar("SELECT nombre, detalle FROM servicios ORDER BY id")
    ]

    return {
        "dia_y_hora_actual": f"{hoy} {hora}",
        "sucursales": sucursales,
        "medios_de_pago": medios_pago,
        "servicios": servicios,
        "aclaracion": "Los horarios pueden cambiar en feriados.",
    }


def info_farmacia() -> dict:
    """Devuelve sucursales (dirección, teléfono, horarios y si están abiertas ahora),
    medios de pago y servicios de la farmacia."""
    return _info_farmacia(datetime.now(ZONA_ARGENTINA))


if __name__ == "__main__":
    def mostrar(titulo: str, datos: list | dict) -> None:
        print(f"\n=== {titulo} ===")
        print(json.dumps(datos, indent=2, ensure_ascii=False))

    mostrar("sin tilde: 'losartan'", buscar_producto("losartan"))
    mostrar("marca + categoría en cualquier orden: 'dermaglos protector'", buscar_producto("dermaglos protector"))
    mostrar("error de tipeo: 'amoxicilna'", buscar_producto("amoxicilna"))
    mostrar("por categoría: 'pañales'", buscar_producto("pañales"))
    mostrar("cobertura con tilde: 'metformina', 'Swiss Médical'", consultar_cobertura("metformina 850", "Swiss Médical"))
    mostrar("venta libre no se cubre: 'paracetamol', 'OSDE 210'", consultar_cobertura("tafirol", "OSDE", "210"))
    mostrar("IOSCOR jubilado", consultar_cobertura("enalapril", "ioscor", "jubilado"))
    mostrar("obra social inexistente", consultar_cobertura("enalapril", "OSPE"))
    mostrar("alternativas: 'diclofenac 75'", buscar_alternativas("diclofenac 75"))
    mostrar("inexistente: 'xyz'", buscar_producto("xyz"))
    mostrar("información de la farmacia", info_farmacia())
