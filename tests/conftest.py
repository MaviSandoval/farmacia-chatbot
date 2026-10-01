"""Configuración compartida de los tests.

Cada test usa una base de datos NUEVA creada en una carpeta temporal, así los tests
no dependen de farmacia_demo.db ni la modifican."""

import pytest

import crear_bd
import herramientas


@pytest.fixture(autouse=True)
def base_de_prueba(tmp_path, monkeypatch):
    """Crea una base de datos temporal y hace que las herramientas la usen."""
    ruta = tmp_path / "farmacia_test.db"
    monkeypatch.setattr(crear_bd, "RUTA_BD", ruta)
    monkeypatch.setattr(herramientas, "RUTA_BD", ruta)
    crear_bd.crear_bd()
    return ruta
