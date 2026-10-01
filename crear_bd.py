"""Crea la base de datos de demo farmacia_demo.db con el catálogo completo de una farmacia.

Los precios, el stock y los datos de las sucursales son ficticios.
Las coberturas siguen el esquema general de Argentina (simplificado para la demo):
- Los productos de venta libre, perfumería, higiene, etc. NO tienen cobertura.
- Los medicamentos bajo receta se cubren según su tipo de tratamiento:
    ambulatorio (uso eventual) ~40 %, crónico ~60-70 %, especial 100 %
    (diabetes y anticonceptivos, según el Programa Médico Obligatorio).
En la realidad cada obra social tiene su propio vademécum: estos valores son orientativos.

La condición de venta (venta libre, bajo receta o bajo receta archivada) se verificó con
el listado de venta libre de ANMAT, prospectos de los laboratorios y alfabeta.net (sep. 2026).
Depende de la dosis y del tamaño del envase: por ejemplo, el omeprazol 20 mg x 14 es de venta
libre, pero el envase x 28 es bajo receta."""

import sqlite3
from pathlib import Path

RUTA_BD = Path(__file__).parent / "farmacia_demo.db"

ESQUEMA = """
CREATE TABLE rubros (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE categorias (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    rubro_id  INTEGER NOT NULL REFERENCES rubros(id),
    nombre    TEXT NOT NULL UNIQUE
);

CREATE TABLE tipos_cobertura (
    codigo       TEXT PRIMARY KEY,
    descripcion  TEXT NOT NULL
);

CREATE TABLE productos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre            TEXT NOT NULL,
    marca             TEXT NOT NULL,
    principio_activo  TEXT,                 -- NULL si no es un medicamento
    categoria_id      INTEGER NOT NULL REFERENCES categorias(id),
    precio            REAL NOT NULL CHECK (precio > 0),
    stock             INTEGER NOT NULL CHECK (stock >= 0),
    condicion_venta   TEXT NOT NULL CHECK (condicion_venta IN
                          ('Venta libre', 'Bajo receta', 'Bajo receta archivada')),
    tipo_cobertura    TEXT REFERENCES tipos_cobertura(codigo),
    UNIQUE (nombre, marca),
    -- Solo los productos bajo receta pueden tener cobertura
    CHECK (condicion_venta <> 'Venta libre' OR tipo_cobertura IS NULL)
);

CREATE TABLE obras_sociales (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE,
    tipo    TEXT NOT NULL
);

CREATE TABLE planes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    obra_social_id  INTEGER NOT NULL REFERENCES obras_sociales(id),
    nombre          TEXT NOT NULL,
    UNIQUE (obra_social_id, nombre)
);

CREATE TABLE coberturas (
    plan_id         INTEGER NOT NULL REFERENCES planes(id),
    tipo_cobertura  TEXT NOT NULL REFERENCES tipos_cobertura(codigo),
    porcentaje      INTEGER NOT NULL CHECK (porcentaje BETWEEN 0 AND 100),
    PRIMARY KEY (plan_id, tipo_cobertura)
);

CREATE TABLE sucursales (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL UNIQUE,
    direccion  TEXT NOT NULL,
    telefono   TEXT NOT NULL
);

CREATE TABLE horarios (
    sucursal_id  INTEGER NOT NULL REFERENCES sucursales(id),
    dia          TEXT NOT NULL,
    apertura     TEXT NOT NULL,
    cierre       TEXT NOT NULL,
    PRIMARY KEY (sucursal_id, dia)
);

CREATE TABLE medios_pago (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre   TEXT NOT NULL UNIQUE,
    detalle  TEXT
);

CREATE TABLE servicios (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre   TEXT NOT NULL UNIQUE,
    detalle  TEXT NOT NULL
);
"""

# rubro -> categorías
RUBROS = {
    "Medicamentos": [
        "Analgésicos y antiinflamatorios", "Antibióticos", "Presión arterial y corazón", "Colesterol",
        "Diabetes", "Tiroides", "Tos, gripe y respiratorio", "Antialérgicos", "Acidez y digestivo",
        "Salud mental", "Anticonceptivos", "Dermatológicos",
    ],
    "Cuidado de la salud": [
        "Vitaminas y suplementos", "Primeros auxilios", "Aparatos de medición",
        "Salud sexual", "Ortopedia",
    ],
    "Higiene personal": [
        "Higiene bucal", "Higiene corporal", "Cuidado del cabello", "Higiene femenina",
    ],
    "Dermocosmética": [
        "Protección solar y repelentes", "Cuidado facial", "Cuidado corporal",
    ],
    "Bebés y maternidad": [
        "Pañales", "Cuidado del bebé", "Alimentación infantil",
    ],
    "Perfumería": [
        "Fragancias", "Maquillaje",
    ],
}

TIPOS_COBERTURA = {
    "ambulatorio": "Medicamentos de uso agudo o eventual",
    "cronico": "Tratamientos prolongados (presión, colesterol, tiroides, asma, salud mental)",
    "especial": "Cobertura del 100 % por el PMO (diabetes, anticonceptivos)",
}

VL, BR, BRA = "Venta libre", "Bajo receta", "Bajo receta archivada"
AMB, CRO, ESP = "ambulatorio", "cronico", "especial"

# (nombre, marca, principio activo, categoría, precio, stock, condición de venta, tipo de cobertura)
PRODUCTOS = [
    # --- Analgésicos y antiinflamatorios ---
    ("Ibuprofeno 400 mg x 20 comprimidos", "Ibupirac", "Ibuprofeno", "Analgésicos y antiinflamatorios", 3200, 45, VL, None),
    ("Ibuprofeno 600 mg x 20 comprimidos", "Ibupirac", "Ibuprofeno", "Analgésicos y antiinflamatorios", 4100, 30, BR, AMB),
    ("Ibuprofeno 400 mg x 10 cápsulas blandas", "Actron", "Ibuprofeno", "Analgésicos y antiinflamatorios", 3900, 0, VL, None),
    ("Paracetamol 500 mg x 20 comprimidos", "Tafirol", "Paracetamol", "Analgésicos y antiinflamatorios", 2500, 60, VL, None),
    ("Paracetamol 500 mg x 10 comprimidos", "Genérico", "Paracetamol", "Analgésicos y antiinflamatorios", 1500, 40, VL, None),
    ("Diclofenac 75 mg x 15 comprimidos", "Genérico", "Diclofenac", "Analgésicos y antiinflamatorios", 3900, 0, BR, AMB),
    ("Diclofenac gel 1 % x 60 g", "Voltaren Emulgel", "Diclofenac", "Analgésicos y antiinflamatorios", 6200, 15, VL, None),
    ("Aspirina 500 mg x 10 comprimidos", "Bayer", "Ácido acetilsalicílico", "Analgésicos y antiinflamatorios", 2300, 50, VL, None),
    ("Ketorolac 10 mg x 10 comprimidos", "Dolten", "Ketorolac", "Analgésicos y antiinflamatorios", 3600, 20, BR, AMB),
    ("Naproxeno 550 mg x 10 comprimidos", "Genérico", "Naproxeno", "Analgésicos y antiinflamatorios", 3400, 18, BR, AMB),
    ("Hioscina 10 mg x 20 grageas", "Buscapina", "Hioscina", "Analgésicos y antiinflamatorios", 4300, 25, VL, None),

    # --- Antibióticos ---
    ("Amoxicilina 500 mg x 16 comprimidos", "Amoxidal", "Amoxicilina", "Antibióticos", 6800, 20, BR, AMB),
    ("Amoxicilina 875 mg + ácido clavulánico 125 mg x 14 comprimidos", "Optamox Duo", "Amoxicilina / Ácido clavulánico", "Antibióticos", 12500, 10, BR, AMB),
    ("Azitromicina 500 mg x 3 comprimidos", "Genérico", "Azitromicina", "Antibióticos", 7500, 12, BR, AMB),
    ("Cefalexina 500 mg x 16 cápsulas", "Genérico", "Cefalexina", "Antibióticos", 8200, 0, BR, AMB),
    ("Ciprofloxacina 500 mg x 10 comprimidos", "Genérico", "Ciprofloxacina", "Antibióticos", 6900, 8, BR, AMB),

    # --- Cardiología ---
    ("Enalapril 10 mg x 30 comprimidos", "Genérico", "Enalapril", "Presión arterial y corazón", 4300, 25, BR, CRO),
    ("Losartán 50 mg x 30 comprimidos", "Losacor", "Losartán", "Presión arterial y corazón", 5600, 18, BR, CRO),
    ("Amlodipina 5 mg x 30 comprimidos", "Genérico", "Amlodipina", "Presión arterial y corazón", 4800, 22, BR, CRO),
    ("Atenolol 50 mg x 30 comprimidos", "Genérico", "Atenolol", "Presión arterial y corazón", 3900, 0, BR, CRO),
    ("Hidroclorotiazida 25 mg x 30 comprimidos", "Genérico", "Hidroclorotiazida", "Presión arterial y corazón", 3200, 15, BR, CRO),

    # --- Colesterol ---
    ("Atorvastatina 20 mg x 30 comprimidos", "Genérico", "Atorvastatina", "Colesterol", 7200, 20, BR, CRO),
    ("Rosuvastatina 10 mg x 30 comprimidos", "Genérico", "Rosuvastatina", "Colesterol", 8900, 10, BR, CRO),

    # --- Diabetes ---
    ("Metformina 850 mg x 60 comprimidos", "Genérico", "Metformina", "Diabetes", 5400, 30, BR, ESP),
    ("Metformina 500 mg x 30 comprimidos", "Genérico", "Metformina", "Diabetes", 3900, 0, BR, ESP),
    ("Glibenclamida 5 mg x 50 comprimidos", "Genérico", "Glibenclamida", "Diabetes", 3100, 12, BR, ESP),
    ("Insulina humana NPH 100 UI/ml frasco 10 ml", "Genérico", "Insulina NPH", "Diabetes", 22000, 6, BR, ESP),

    # --- Tiroides ---
    ("Levotiroxina 50 mcg x 50 comprimidos", "T4 Montpellier", "Levotiroxina", "Tiroides", 5200, 25, BR, CRO),
    ("Levotiroxina 100 mcg x 50 comprimidos", "T4 Montpellier", "Levotiroxina", "Tiroides", 5900, 0, BR, CRO),

    # --- Respiratorio ---
    ("Salbutamol aerosol 100 mcg x 250 dosis", "Salbutral", "Salbutamol", "Tos, gripe y respiratorio", 8700, 10, BR, CRO),
    ("Fluticasona spray nasal 50 mcg", "Alernix Cort", "Fluticasona", "Tos, gripe y respiratorio", 9800, 7, VL, None),
    ("Jarabe para la tos seca x 150 ml", "Genérico", "Dextrometorfano", "Tos, gripe y respiratorio", 5600, 20, BRA, AMB),
    ("Bromhexina jarabe x 120 ml", "Bisolvon", "Bromhexina", "Tos, gripe y respiratorio", 5100, 15, VL, None),
    ("Antigripal x 10 comprimidos", "Next", "Paracetamol / Fenilefrina / Clorfeniramina", "Tos, gripe y respiratorio", 4400, 35, VL, None),

    # --- Antialérgicos ---
    ("Loratadina 10 mg x 10 comprimidos", "Genérico", "Loratadina", "Antialérgicos", 2900, 35, VL, None),
    ("Cetirizina 10 mg x 10 cápsulas blandas", "Alernix", "Cetirizina", "Antialérgicos", 3100, 0, VL, None),
    ("Desloratadina 5 mg x 10 comprimidos", "Genérico", "Desloratadina", "Antialérgicos", 4600, 20, BR, AMB),
    # Fexofenadina: 60 y 120 mg son de venta libre desde la Disposición ANMAT 4714/2026; 180 mg sigue bajo receta
    ("Fexofenadina 120 mg x 10 comprimidos", "Allegra", "Fexofenadina", "Antialérgicos", 6900, 15, VL, None),
    ("Fexofenadina 180 mg x 10 comprimidos", "Allegra", "Fexofenadina", "Antialérgicos", 7900, 12, BR, AMB),

    # --- Aparato digestivo ---
    ("Omeprazol 20 mg x 14 cápsulas", "Genérico", "Omeprazol", "Acidez y digestivo", 3600, 40, VL, None),
    ("Omeprazol 20 mg x 28 cápsulas", "Ulcozol", "Omeprazol", "Acidez y digestivo", 6100, 10, BR, AMB),
    ("Famotidina 20 mg x 20 comprimidos", "Genérico", "Famotidina", "Acidez y digestivo", 3300, 15, BR, AMB),
    ("Trimebutina 200 mg x 30 comprimidos", "Genérico", "Trimebutina", "Acidez y digestivo", 7400, 0, BR, AMB),
    ("Antiácido masticable x 24 comprimidos", "Mylanta", "Carbonato de calcio y asociados", "Acidez y digestivo", 6800, 30, VL, None),
    ("Loperamida 2 mg x 10 comprimidos", "Loperapid", "Loperamida", "Acidez y digestivo", 3100, 25, VL, None),
    ("Sales de rehidratación oral x 10 sobres", "Genérico", "Sales de rehidratación oral", "Acidez y digestivo", 2800, 20, VL, None),

    # --- Salud mental ---
    ("Clonazepam 0,5 mg x 30 comprimidos", "Rivotril", "Clonazepam", "Salud mental", 5800, 20, BRA, CRO),
    ("Alprazolam 0,5 mg x 30 comprimidos", "Alplax", "Alprazolam", "Salud mental", 5500, 15, BRA, CRO),
    ("Sertralina 50 mg x 30 comprimidos", "Genérico", "Sertralina", "Salud mental", 9200, 12, BRA, CRO),
    ("Escitalopram 10 mg x 30 comprimidos", "Genérico", "Escitalopram", "Salud mental", 10400, 0, BRA, CRO),

    # --- Anticonceptivos ---
    ("Levonorgestrel + etinilestradiol x 28 comprimidos", "Genérico", "Levonorgestrel / Etinilestradiol", "Anticonceptivos", 6300, 18, BR, ESP),
    ("Drospirenona + etinilestradiol x 28 comprimidos", "Genérico", "Drospirenona / Etinilestradiol", "Anticonceptivos", 11800, 9, BR, ESP),

    # --- Dermatológicos ---
    ("Clotrimazol crema 1 % x 20 g", "Empecid", "Clotrimazol", "Dermatológicos", 3700, 14, VL, None),
    ("Aciclovir crema 5 % x 10 g", "Genérico", "Aciclovir", "Dermatológicos", 3900, 9, VL, None),
    ("Betametasona crema 0,05 % x 15 g", "Genérico", "Betametasona", "Dermatológicos", 4200, 10, BR, AMB),
    ("Mupirocina ungüento 2 % x 15 g", "Genérico", "Mupirocina", "Dermatológicos", 6800, 0, BR, AMB),

    # --- Vitaminas y suplementos ---
    ("Vitamina C 1 g x 10 comprimidos efervescentes", "Redoxon", "Ácido ascórbico", "Vitaminas y suplementos", 4500, 22, VL, None),
    ("Multivitamínico x 30 comprimidos", "Supradyn", "Multivitamínico", "Vitaminas y suplementos", 12800, 15, VL, None),
    ("Vitamina D3 1000 UI x 60 cápsulas", "Genérico", "Colecalciferol", "Vitaminas y suplementos", 8900, 10, VL, None),
    ("Magnesio x 30 comprimidos", "Genérico", "Magnesio", "Vitaminas y suplementos", 7600, 0, VL, None),
    ("Hierro + ácido fólico x 30 comprimidos", "Genérico", "Sulfato ferroso / Ácido fólico", "Vitaminas y suplementos", 6200, 12, VL, None),
    ("Colágeno hidrolizado en polvo x 250 g", "Genérico", "Colágeno hidrolizado", "Vitaminas y suplementos", 15600, 8, VL, None),

    # --- Primeros auxilios ---
    ("Alcohol etílico 70 % x 250 ml", "Porta", None, "Primeros auxilios", 2100, 50, VL, None),
    ("Alcohol en gel x 250 ml", "Genérico", None, "Primeros auxilios", 2600, 35, VL, None),
    ("Agua oxigenada 10 vol x 250 ml", "Genérico", None, "Primeros auxilios", 1600, 30, VL, None),
    ("Iodopovidona solución x 60 ml", "Pervinox", "Iodopovidona", "Primeros auxilios", 3500, 0, VL, None),
    ("Gasas estériles 10 x 10 cm x 10 unidades", "Genérico", None, "Primeros auxilios", 1900, 40, VL, None),
    ("Apósitos adhesivos x 20 unidades", "Curitas", None, "Primeros auxilios", 1800, 60, VL, None),
    ("Venda elástica 10 cm", "Genérico", None, "Primeros auxilios", 2400, 20, VL, None),

    # --- Aparatos de medición ---
    ("Termómetro digital flexible", "Omron", None, "Aparatos de medición", 7900, 12, VL, None),
    ("Tensiómetro digital de brazo", "Omron", None, "Aparatos de medición", 68000, 4, VL, None),
    ("Glucómetro con 10 tiras", "Accu-Chek", None, "Aparatos de medición", 32000, 0, VL, None),
    ("Oxímetro de pulso", "Genérico", None, "Aparatos de medición", 18500, 6, VL, None),
    ("Nebulizador a pistón", "Silfab", None, "Aparatos de medición", 58000, 3, VL, None),

    # --- Salud sexual ---
    ("Preservativos x 3 unidades", "Prime", None, "Salud sexual", 2900, 50, VL, None),
    ("Gel íntimo lubricante x 50 g", "Prime", None, "Salud sexual", 4200, 15, VL, None),
    ("Test de embarazo", "Evatest", None, "Salud sexual", 3800, 25, VL, None),

    # --- Ortopedia ---
    ("Tobillera elástica", "Genérico", None, "Ortopedia", 6500, 8, VL, None),
    ("Rodillera elástica", "Genérico", None, "Ortopedia", 7800, 0, VL, None),
    ("Faja lumbar", "Genérico", None, "Ortopedia", 21000, 4, VL, None),

    # --- Higiene bucal ---
    ("Pasta dental x 90 g", "Colgate Total 12", None, "Higiene bucal", 3200, 50, VL, None),
    ("Pasta dental blanqueadora x 70 g", "Colgate Luminous White", None, "Higiene bucal", 4800, 20, VL, None),
    ("Pasta dental para dientes sensibles x 90 g", "Sensodyne", None, "Higiene bucal", 5900, 18, VL, None),
    ("Cepillo dental suave", "Oral-B", None, "Higiene bucal", 2700, 40, VL, None),
    ("Enjuague bucal x 500 ml", "Listerine", None, "Higiene bucal", 6400, 15, VL, None),
    ("Hilo dental x 50 m", "Oral-B", None, "Higiene bucal", 3300, 0, VL, None),

    # --- Higiene corporal ---
    ("Jabón en barra x 3 unidades", "Dove", None, "Higiene corporal", 4200, 30, VL, None),
    ("Desodorante antitranspirante aerosol x 150 ml", "Rexona", None, "Higiene corporal", 3900, 40, VL, None),
    ("Desodorante roll-on x 50 ml", "Dove", None, "Higiene corporal", 3600, 0, VL, None),
    ("Gel de ducha x 250 ml", "Nivea", None, "Higiene corporal", 4700, 20, VL, None),

    # --- Cuidado del cabello ---
    ("Shampoo x 400 ml", "Pantene", None, "Cuidado del cabello", 5800, 25, VL, None),
    ("Acondicionador x 400 ml", "Pantene", None, "Cuidado del cabello", 5800, 20, VL, None),
    ("Shampoo anticaspa x 375 ml", "Head & Shoulders", None, "Cuidado del cabello", 6900, 15, VL, None),
    ("Loción antipiojos x 120 ml", "Nopucid", "Permetrina", "Cuidado del cabello", 5600, 12, VL, None),

    # --- Higiene femenina ---
    ("Toallitas femeninas x 16 unidades", "Always", None, "Higiene femenina", 3100, 30, VL, None),
    ("Tampones medianos x 16 unidades", "O.B.", None, "Higiene femenina", 4300, 0, VL, None),
    ("Protectores diarios x 40 unidades", "Carefree", None, "Higiene femenina", 3500, 20, VL, None),

    # --- Protección solar y repelentes ---
    ("Protector solar FPS 50 loción x 200 ml", "Dermaglós", None, "Protección solar y repelentes", 16900, 12, VL, None),
    ("Protector solar facial FPS 50 x 50 ml", "La Roche-Posay Anthelios", None, "Protección solar y repelentes", 29500, 6, VL, None),
    ("Protector solar FPS 30 spray x 200 ml", "Rayito de Sol", None, "Protección solar y repelentes", 12800, 0, VL, None),
    ("Protector solar para niños FPS 50 x 125 ml", "Dermaglós", None, "Protección solar y repelentes", 14200, 8, VL, None),
    ("Repelente de insectos aerosol x 165 ml", "OFF!", None, "Protección solar y repelentes", 5400, 25, VL, None),

    # --- Cuidado facial ---
    ("Gel limpiador facial x 200 ml", "CeraVe", None, "Cuidado facial", 18900, 7, VL, None),
    ("Crema hidratante facial x 50 g", "Nivea", None, "Cuidado facial", 7800, 15, VL, None),
    ("Agua micelar x 400 ml", "Garnier", None, "Cuidado facial", 8600, 10, VL, None),
    ("Sérum de ácido hialurónico x 30 ml", "Vichy Minéral 89", None, "Cuidado facial", 36500, 3, VL, None),

    # --- Cuidado corporal ---
    ("Crema corporal hidratante x 400 ml", "Nivea", None, "Cuidado corporal", 8900, 18, VL, None),
    ("Crema para manos x 50 ml", "Neutrogena", None, "Cuidado corporal", 5200, 0, VL, None),
    ("Protector labial", "Labello", None, "Cuidado corporal", 3200, 30, VL, None),

    # --- Pañales ---
    ("Pañales recién nacido x 34 unidades", "Pampers", None, "Pañales", 18500, 10, VL, None),
    ("Pañales talle M x 50 unidades", "Pampers", None, "Pañales", 28900, 8, VL, None),
    ("Pañales talle G x 44 unidades", "Huggies", None, "Pañales", 29500, 0, VL, None),
    ("Pañales talle XG x 40 unidades", "Huggies", None, "Pañales", 30800, 6, VL, None),
    ("Pañales para adultos talle M x 8 unidades", "Plenitud", None, "Pañales", 12500, 10, VL, None),

    # --- Cuidado del bebé ---
    ("Toallitas húmedas x 50 unidades", "Huggies", None, "Cuidado del bebé", 3400, 30, VL, None),
    ("Crema para paspaduras x 90 g", "Hipoglós", None, "Cuidado del bebé", 7400, 20, VL, None),
    ("Óleo calcáreo x 400 ml", "Genérico", None, "Cuidado del bebé", 3900, 12, VL, None),
    ("Shampoo para bebé x 200 ml", "Johnson's Baby", None, "Cuidado del bebé", 4500, 15, VL, None),
    ("Mamadera x 250 ml", "Avent", None, "Cuidado del bebé", 12900, 5, VL, None),
    ("Chupete de silicona 6 a 18 meses", "Avent", None, "Cuidado del bebé", 7800, 0, VL, None),

    # --- Alimentación infantil ---
    ("Leche de fórmula etapa 1 x 800 g", "Nutrilon", None, "Alimentación infantil", 29800, 6, VL, None),
    ("Leche de fórmula etapa 2 x 800 g", "Nutrilon", None, "Alimentación infantil", 28500, 0, VL, None),
    ("Leche de fórmula etapa 3 x 800 g", "SanCor Bebé", None, "Alimentación infantil", 21500, 8, VL, None),

    # --- Fragancias ---
    ("Colonia masculina x 100 ml", "Colbert Noir", None, "Fragancias", 10500, 6, VL, None),
    ("Colonia para bebé x 250 ml", "Johnson's Baby", None, "Fragancias", 7200, 10, VL, None),

    # --- Maquillaje ---
    ("Base de maquillaje x 30 ml", "Maybelline Fit Me", None, "Maquillaje", 14500, 5, VL, None),
    ("Máscara de pestañas", "Maybelline Colossal", None, "Maquillaje", 11200, 0, VL, None),
    ("Quitaesmalte x 60 ml", "Genérico", None, "Maquillaje", 1900, 15, VL, None),
]

# obra social -> (tipo, {plan: {tipo de cobertura: %}})
_PREPAGA_BASE = {AMB: 40, CRO: 70, ESP: 100}
OBRAS_SOCIALES = {
    "OSDE": ("Prepaga", {
        "210": _PREPAGA_BASE, "310": _PREPAGA_BASE, "410": _PREPAGA_BASE,
        "450": _PREPAGA_BASE, "510": _PREPAGA_BASE,
    }),
    "Swiss Medical": ("Prepaga", {
        "SMG10": {AMB: 40, CRO: 60, ESP: 100},
        "SMG20": _PREPAGA_BASE, "SMG30": _PREPAGA_BASE, "SMG40": _PREPAGA_BASE,
    }),
    "IOSCOR": ("Obra social provincial (Corrientes)", {
        "Activo": {AMB: 50, CRO: 50, ESP: 100},
        "Jubilado": {AMB: 60, CRO: 60, ESP: 100},
    }),
    "PAMI": ("Obra social nacional (jubilados y pensionados)", {
        "Afiliado": {AMB: 40, CRO: 70, ESP: 100},
    }),
}

SUCURSALES = [
    ("Sucursal Centro", "Av. Demo 1234, Corrientes", "(0379) 000-0001"),
    ("Sucursal Norte", "Calle Ejemplo 567, Corrientes", "(0379) 000-0002"),
]

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
HORARIOS = {
    "Sucursal Centro": {**{dia: ("08:00", "22:00") for dia in DIAS[:6]}, "Domingo": ("09:00", "13:00")},
    "Sucursal Norte": {**{dia: ("08:00", "20:00") for dia in DIAS[:5]}, "Sábado": ("08:30", "13:00")},
}

MEDIOS_PAGO = [
    ("Efectivo", None),
    ("Tarjeta de débito", None),
    ("Tarjeta de crédito", "Hasta 3 cuotas sin interés en perfumería y dermocosmética"),
    ("Mercado Pago", "Pago con QR"),
    ("Transferencia bancaria", None),
]

SERVICIOS = [
    ("Toma de presión arterial", "Sin costo, sin turno"),
    ("Aplicación de inyectables", "Con receta médica"),
    ("Vacunación antigripal", "Durante la campaña de otoño e invierno"),
    ("Control de glucemia", "Con turno previo"),
]


def crear_bd() -> None:
    """Borra la base anterior (si existe), crea las tablas y carga los datos."""
    if RUTA_BD.exists():
        RUTA_BD.unlink()

    con = sqlite3.connect(RUTA_BD)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(ESQUEMA)

        con.executemany("INSERT INTO tipos_cobertura (codigo, descripcion) VALUES (?, ?)",
                        TIPOS_COBERTURA.items())

        # Diccionarios nombre -> id, para no escribir IDs a mano
        id_categoria = {}
        for rubro, categorias in RUBROS.items():
            id_rubro = con.execute("INSERT INTO rubros (nombre) VALUES (?)", (rubro,)).lastrowid
            for categoria in categorias:
                cur = con.execute("INSERT INTO categorias (rubro_id, nombre) VALUES (?, ?)",
                                  (id_rubro, categoria))
                id_categoria[categoria] = cur.lastrowid

        for nombre, marca, principio, categoria, precio, stock, condicion, cobertura in PRODUCTOS:
            con.execute(
                """INSERT INTO productos (nombre, marca, principio_activo, categoria_id,
                                          precio, stock, condicion_venta, tipo_cobertura)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (nombre, marca, principio, id_categoria[categoria], precio, stock, condicion, cobertura),
            )

        cantidad_planes = 0
        for obra_social, (tipo, planes) in OBRAS_SOCIALES.items():
            id_os = con.execute("INSERT INTO obras_sociales (nombre, tipo) VALUES (?, ?)",
                                (obra_social, tipo)).lastrowid
            for plan, porcentajes in planes.items():
                id_plan = con.execute("INSERT INTO planes (obra_social_id, nombre) VALUES (?, ?)",
                                      (id_os, plan)).lastrowid
                cantidad_planes += 1
                for tipo_cobertura, porcentaje in porcentajes.items():
                    con.execute(
                        "INSERT INTO coberturas (plan_id, tipo_cobertura, porcentaje) VALUES (?, ?, ?)",
                        (id_plan, tipo_cobertura, porcentaje),
                    )

        for nombre, direccion, telefono in SUCURSALES:
            id_sucursal = con.execute(
                "INSERT INTO sucursales (nombre, direccion, telefono) VALUES (?, ?, ?)",
                (nombre, direccion, telefono),
            ).lastrowid
            for dia, (apertura, cierre) in HORARIOS[nombre].items():
                con.execute(
                    "INSERT INTO horarios (sucursal_id, dia, apertura, cierre) VALUES (?, ?, ?, ?)",
                    (id_sucursal, dia, apertura, cierre),
                )

        con.executemany("INSERT INTO medios_pago (nombre, detalle) VALUES (?, ?)", MEDIOS_PAGO)
        con.executemany("INSERT INTO servicios (nombre, detalle) VALUES (?, ?)", SERVICIOS)

        con.commit()
    finally:
        con.close()

    cantidad_categorias = sum(len(categorias) for categorias in RUBROS.values())
    print(f"Base creada: {RUTA_BD.name}")
    print(f"  {len(RUBROS)} rubros, {cantidad_categorias} categorías, {len(PRODUCTOS)} productos")
    print(f"  {len(OBRAS_SOCIALES)} obras sociales, {cantidad_planes} planes")
    print(f"  {len(SUCURSALES)} sucursales, {len(MEDIOS_PAGO)} medios de pago, {len(SERVICIOS)} servicios")


if __name__ == "__main__":
    crear_bd()
