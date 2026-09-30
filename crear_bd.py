"""Crea la base de datos de demo farmacia_demo.db con datos de ejemplo.
Precios, stock y porcentajes de cobertura son ficticios."""

import sqlite3
from pathlib import Path

RUTA_BD = Path(__file__).parent / "farmacia_demo.db"

ESQUEMA = """
CREATE TABLE categorias (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE productos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre           TEXT NOT NULL UNIQUE,
    principio_activo TEXT NOT NULL,
    categoria_id     INTEGER NOT NULL REFERENCES categorias(id),
    precio           REAL NOT NULL CHECK (precio > 0),
    stock            INTEGER NOT NULL CHECK (stock >= 0),
    requiere_receta  INTEGER NOT NULL CHECK (requiere_receta IN (0, 1))
);

CREATE TABLE obras_sociales (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE planes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    obra_social_id  INTEGER NOT NULL REFERENCES obras_sociales(id),
    nombre          TEXT NOT NULL,
    UNIQUE (obra_social_id, nombre)
);

CREATE TABLE coberturas (
    plan_id       INTEGER NOT NULL REFERENCES planes(id),
    categoria_id  INTEGER NOT NULL REFERENCES categorias(id),
    porcentaje    INTEGER NOT NULL CHECK (porcentaje BETWEEN 0 AND 100),
    PRIMARY KEY (plan_id, categoria_id)
);
"""

CATEGORIAS = [
    "Analgésicos", "Antibióticos", "Antihipertensivos",
    "Antialérgicos", "Protectores gástricos", "Vitaminas",
]

# (nombre, principio activo, categoría, precio, stock, requiere receta)
PRODUCTOS = [
    ("Ibuprofeno 400 mg x 20", "Ibuprofeno", "Analgésicos", 3200, 45, False),
    ("Ibuprofeno 600 mg x 20", "Ibuprofeno", "Analgésicos", 4100, 30, False),
    ("Paracetamol 500 mg x 20", "Paracetamol", "Analgésicos", 2500, 60, False),
    ("Diclofenac 75 mg x 15", "Diclofenac", "Analgésicos", 3900, 0, False),
    ("Amoxicilina 500 mg x 16", "Amoxicilina", "Antibióticos", 6800, 20, True),
    ("Azitromicina 500 mg x 3", "Azitromicina", "Antibióticos", 7500, 12, True),
    ("Cefalexina 500 mg x 16", "Cefalexina", "Antibióticos", 8200, 0, True),
    ("Enalapril 10 mg x 30", "Enalapril", "Antihipertensivos", 4300, 25, True),
    ("Losartán 50 mg x 30", "Losartán", "Antihipertensivos", 5600, 18, True),
    ("Loratadina 10 mg x 10", "Loratadina", "Antialérgicos", 2900, 35, False),
    ("Cetirizina 10 mg x 10", "Cetirizina", "Antialérgicos", 3100, 0, False),
    ("Omeprazol 20 mg x 14", "Omeprazol", "Protectores gástricos", 3600, 40, False),
    ("Famotidina 20 mg x 20", "Famotidina", "Protectores gástricos", 3300, 15, False),
    ("Vitamina C 1 g x 10 efervescente", "Ácido ascórbico", "Vitaminas", 4500, 22, False),
]

# obra social -> lista de planes
PLANES = {
    "OSDE": ["210", "310"],
    "Swiss Medical": ["SMG20", "SMG30"],
    "IOSCOR": ["General"],
    "PAMI": ["Único"],
}

# (obra social, plan) -> {categoría: % de descuento}
# Si una categoría no figura, ese plan no la cubre.
COBERTURAS = {
    ("OSDE", "210"): {"Analgésicos": 40, "Antibióticos": 50, "Antihipertensivos": 60,
                      "Antialérgicos": 40, "Protectores gástricos": 40},
    ("OSDE", "310"): {"Analgésicos": 50, "Antibióticos": 60, "Antihipertensivos": 70,
                      "Antialérgicos": 50, "Protectores gástricos": 50},
    ("Swiss Medical", "SMG20"): {"Analgésicos": 40, "Antibióticos": 40, "Antihipertensivos": 50,
                                "Antialérgicos": 30, "Protectores gástricos": 40},
    ("Swiss Medical", "SMG30"): {"Analgésicos": 50, "Antibióticos": 60, "Antihipertensivos": 70,
                                "Antialérgicos": 40, "Protectores gástricos": 50},
    ("IOSCOR", "General"): {"Analgésicos": 40, "Antibióticos": 50, "Antihipertensivos": 70,
                            "Protectores gástricos": 40},
    ("PAMI", "Único"): {"Analgésicos": 50, "Antibióticos": 80, "Antihipertensivos": 100,
                        "Antialérgicos": 50, "Protectores gástricos": 60},
}


def crear_bd() -> None:
    """Borra la base anterior (si existe), crea las tablas y carga los datos."""
    if RUTA_BD.exists():
        RUTA_BD.unlink()

    con = sqlite3.connect(RUTA_BD)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(ESQUEMA)

        # Diccionarios nombre -> id, para no escribir IDs a mano
        id_categoria = {}
        for nombre in CATEGORIAS:
            cur = con.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,))
            id_categoria[nombre] = cur.lastrowid

        for nombre, principio, categoria, precio, stock, receta in PRODUCTOS:
            con.execute(
                """INSERT INTO productos
                   (nombre, principio_activo, categoria_id, precio, stock, requiere_receta)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (nombre, principio, id_categoria[categoria], precio, stock, int(receta)),
            )

        id_plan = {}
        for obra_social, planes in PLANES.items():
            cur = con.execute("INSERT INTO obras_sociales (nombre) VALUES (?)", (obra_social,))
            id_os = cur.lastrowid
            for plan in planes:
                cur = con.execute(
                    "INSERT INTO planes (obra_social_id, nombre) VALUES (?, ?)", (id_os, plan)
                )
                id_plan[(obra_social, plan)] = cur.lastrowid

        for clave_plan, porcentajes in COBERTURAS.items():
            for categoria, porcentaje in porcentajes.items():
                con.execute(
                    "INSERT INTO coberturas (plan_id, categoria_id, porcentaje) VALUES (?, ?, ?)",
                    (id_plan[clave_plan], id_categoria[categoria], porcentaje),
                )

        con.commit()
    finally:
        con.close()

    print(f"Base creada: {RUTA_BD.name}")
    print(f"  {len(CATEGORIAS)} categorías, {len(PRODUCTOS)} productos, "
          f"{len(PLANES)} obras sociales, {len(id_plan)} planes")


if __name__ == "__main__":
    crear_bd()