"""
Pruebas de la capa de base de datos (db.py). Usan una base SQLite temporal, no
tocan datos/db/database.db.

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import _setup  # noqa: F401  (agrega src/ y la raiz al sys.path)

from aforo.persistencia.db import CrucesDB, RegistradorCruces  # noqa: E402

T0 = datetime(2026, 11, 9, 8, 0, 0)


class BaseDatosTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Carpeta que aun no existe: db.py debe crearla.
        self.ruta = Path(self._tmp.name) / "db" / "database.db"

    def _leer(self, sql: str, params: tuple = ()) -> list:
        con = sqlite3.connect(self.ruta)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    def test_crea_archivo_carpeta_y_tabla_con_campos_exactos(self) -> None:
        with CrucesDB(self.ruta):
            pass
        self.assertTrue(self.ruta.is_file())
        columnas = self._leer("PRAGMA table_info(cruces)")        # (cid, nombre, tipo, notnull, default, pk)
        self.assertEqual(
            [(c[1], c[2], c[5]) for c in columnas],
            [("id", "INTEGER", 1), ("track_id", "INTEGER", 0), ("tipo", "TEXT", 0),
             ("momento", "TIMESTAMP", 0), ("velocidad_kmh", "REAL", 0), ("camara", "TEXT", 0)],
        )

    def test_crea_las_demas_tablas_y_la_vista(self) -> None:
        with CrucesDB(self.ruta):
            pass
        objetos = dict(self._leer("SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('table','view')"))
        self.assertEqual(objetos, {"cruces": "table", "alertas": "table", "lecturas_trafico": "table",
                                   "ejecuciones": "table", "metricas": "table", "v_aforo_por_minuto": "view"})
        cols_alertas = [c[1] for c in self._leer("PRAGMA table_info(alertas)")]
        self.assertEqual(cols_alertas, ["id", "camara", "momento", "tipo", "track_id", "valor", "umbral", "descripcion"])

    def test_alertas_lecturas_y_metricas_se_insertan(self) -> None:
        with CrucesDB(self.ruta) as db:
            db.insertar_alerta("cam", T0, "EXCESO_VELOCIDAD", 7, 82.4, 60.0, "Auto a 82.4 km/h")
            db.insertar_alerta("cam", T0, "TRAFICO_DETENIDO", None, 5.0, 3.0, "5 vehiculos")
            db.insertar_lectura("cam", T0, 3.456, 0.12345, "FLUIDO")
            db.insertar_metrica("cam", T0, "precision", 0.91, "TP=10 FP=1")
        self.assertEqual(self._leer("SELECT tipo, track_id, valor, umbral FROM alertas ORDER BY id"),
                         [("EXCESO_VELOCIDAD", 7, 82.4, 60.0), ("TRAFICO_DETENIDO", None, 5.0, 3.0)])
        self.assertEqual(self._leer("SELECT vehiculos_roi, ratio_movimiento, estado FROM lecturas_trafico"),
                         [(3.46, 0.1235, "FLUIDO")])
        self.assertEqual(self._leer("SELECT metrica, valor FROM metricas"), [("precision", 0.91)])

    def test_vista_de_aforo_por_minuto_agrupa_los_cruces(self) -> None:
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(1, "Auto", datetime(2026, 11, 9, 8, 0, 10), 50.0, "cam")
            db.insertar_cruce(2, "Auto", datetime(2026, 11, 9, 8, 0, 40), 70.0, "cam")
            db.insertar_cruce(3, "Bus", datetime(2026, 11, 9, 8, 1, 5), None, "cam")
        filas = self._leer("SELECT minuto, tipo, vehiculos, velocidad_promedio_kmh FROM v_aforo_por_minuto ORDER BY minuto, tipo")
        self.assertEqual(filas, [("2026-11-09 08:00", "Auto", 2, 60.0), ("2026-11-09 08:01", "Bus", 1, None)])

    def test_eliminar_camara_borra_alertas_y_lecturas_pero_conserva_metricas(self) -> None:
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(1, "Auto", T0, None, "a")
            db.insertar_alerta("a", T0, "EXCESO_VELOCIDAD", 1, 90.0, 60.0, "x")
            db.insertar_lectura("a", T0, 1.0, 0.5, "FLUIDO")
            db.insertar_metrica("a", T0, "f1", 0.8)
            db.eliminar_camara("a")
        self.assertEqual(self._leer("SELECT COUNT(*) FROM cruces"), [(0,)])
        self.assertEqual(self._leer("SELECT COUNT(*) FROM alertas"), [(0,)])
        self.assertEqual(self._leer("SELECT COUNT(*) FROM lecturas_trafico"), [(0,)])
        self.assertEqual(self._leer("SELECT COUNT(*) FROM metricas"), [(1,)])

    def test_abrir_dos_veces_conserva_los_datos(self) -> None:
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(7, "Auto", T0, 55.5, "cam")
        with CrucesDB(self.ruta) as db:          # "CREATE TABLE IF NOT EXISTS" no borra nada
            self.assertEqual(db.contar(), 1)

    def test_insertar_guarda_los_valores(self) -> None:
        with CrucesDB(self.ruta) as db:
            fila_id = db.insertar_cruce(12, "Camion", T0, 61.25, "norte")
        filas = self._leer("SELECT id, track_id, tipo, momento, velocidad_kmh, camara FROM cruces")
        self.assertEqual(filas, [(fila_id, 12, "Camion", "2026-11-09 08:00:00.000", 61.25, "norte")])

    def test_velocidad_nula_es_null(self) -> None:
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(1, "Auto", T0, None, "cam")
        self.assertEqual(self._leer("SELECT velocidad_kmh FROM cruces"), [(None,)])

    def test_los_valores_viajan_como_parametros_no_como_sql(self) -> None:
        raro = "Auto'); DROP TABLE cruces;--"
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(1, raro, T0, 10.0, "cam")
            self.assertEqual(db.contar(), 1)        # la tabla sigue existiendo
        self.assertEqual(self._leer("SELECT tipo FROM cruces"), [(raro,)])

    def test_eliminar_camara_solo_borra_esa_camara(self) -> None:
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(1, "Auto", T0, None, "a")
            db.insertar_cruce(2, "Auto", T0, None, "a")
            db.insertar_cruce(1, "Bus", T0, None, "b")
            self.assertEqual(db.eliminar_camara("a"), 2)
            self.assertEqual(db.contar(), 1)
            self.assertEqual(db.contar("b"), 1)

    def test_un_lector_ve_los_datos_mientras_el_escritor_sigue_abierto(self) -> None:
        # Es lo que hace el dashboard mientras aforo procesar procesa un video (modo WAL).
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(1, "Auto", T0, 40.0, "cam")
            self.assertEqual(self._leer("SELECT COUNT(*) FROM cruces"), [(1,)])
            db.insertar_cruce(2, "Moto", T0, 70.0, "cam")
            self.assertEqual(self._leer("SELECT COUNT(*) FROM cruces"), [(2,)])


class RegistradorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = CrucesDB(Path(self._tmp.name) / "database.db")
        self.addCleanup(self.db.cerrar)
        self.reg = RegistradorCruces(self.db, "cam")

    def _filas(self) -> list:
        return self.db._con.execute(
            "SELECT track_id, tipo, velocidad_kmh, camara FROM cruces ORDER BY id"
        ).fetchall()

    def test_cruce_y_luego_velocidad_actualiza_la_fila(self) -> None:
        self.reg.registrar_cruce(5, "Auto", T0)
        self.assertEqual(self._filas(), [(5, "Auto", None, "cam")])      # INSERT inmediato
        self.reg.registrar_velocidad(5, 48.0)
        self.assertEqual(self._filas(), [(5, "Auto", 48.0, "cam")])      # UPDATE posterior

    def test_velocidad_antes_del_cruce_se_incluye_en_el_insert(self) -> None:
        self.reg.registrar_velocidad(9, 72.5)
        self.assertEqual(self._filas(), [])                              # aun no cruzo: no hay fila
        self.reg.registrar_cruce(9, "Bus", T0)
        self.assertEqual(self._filas(), [(9, "Bus", 72.5, "cam")])

    def test_un_track_se_registra_una_sola_vez(self) -> None:
        self.assertIsNotNone(self.reg.registrar_cruce(3, "Auto", T0))
        self.assertIsNone(self.reg.registrar_cruce(3, "Auto", T0))
        self.assertEqual(len(self._filas()), 1)
        self.assertEqual(self.reg.insertados, 1)

    def test_velocidad_de_vehiculo_que_nunca_cruza_no_crea_fila(self) -> None:
        self.reg.registrar_velocidad(4, 30.0)
        self.assertEqual(self._filas(), [])


if __name__ == "__main__":
    unittest.main()
