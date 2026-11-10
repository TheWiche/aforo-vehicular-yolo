"""
Pruebas del backend del dashboard: consultas SQL, armado del panel y rutas de la API.
Usan una base SQLite temporal (no tocan datos/db/database.db).

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import _setup  # noqa: F401  (agrega src/ y la raiz al sys.path)
from fastapi.testclient import TestClient

from aforo.persistencia.db import CrucesDB
from dashboard.backend import consultas
from dashboard.backend.app import crear_app
from dashboard.backend.panel import construir_panel, percentil

T0 = datetime(2026, 11, 9, 8, 0, 0)
CLASES = [{"nombre": "Auto", "color": "#3987e5"}, {"nombre": "Camion", "color": "#9085e9"}]


class PercentilTest(unittest.TestCase):
    def test_coincide_con_la_interpolacion_lineal_clasica(self) -> None:
        self.assertAlmostEqual(percentil([10, 20, 30, 40, 50], 50), 30.0)
        self.assertAlmostEqual(percentil([10, 20, 30, 40, 50], 90), 46.0)    # 40 + 0.6 * 10
        self.assertAlmostEqual(percentil([7], 90), 7.0)
        self.assertIsNone(percentil([], 90))


class ConBaseDeDatosTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ruta = Path(self._tmp.name) / "database.db"
        with CrucesDB(self.ruta) as db:
            db.insertar_cruce(1, "Auto", T0 + timedelta(seconds=5), 50.0, "norte")
            db.insertar_cruce(2, "Auto", T0 + timedelta(seconds=9), 70.0, "norte")
            db.insertar_cruce(3, "Camion", T0 + timedelta(seconds=15), 40.0, "norte")
            db.insertar_cruce(4, "Auto", T0 + timedelta(seconds=20), None, "sur")
            db.insertar_alerta("norte", T0 + timedelta(seconds=9), "EXCESO_VELOCIDAD", 2, 70.0, 60.0, "Auto a 70 km/h")
            db.insertar_alerta("norte", T0 + timedelta(seconds=30), "TRAFICO_DETENIDO", None, 5.0, 3.0, "5 vehiculos")
            db.insertar_lectura("norte", T0 + timedelta(seconds=5), 2.5, 0.4, "FLUIDO")
            db.insertar_lectura("norte", T0 + timedelta(seconds=10), 5.0, 0.01, "DETENIDO")

    def _con(self) -> sqlite3.Connection:
        return sqlite3.connect(self.ruta)

    def test_consultas_agregan_con_sql(self) -> None:
        con = self._con()
        self.assertEqual({f["tipo"]: f["total"] for f in consultas.total_por_tipo(con, ["norte"])},
                         {"Auto": 2, "Camion": 1})
        por_tipo = {f["tipo"]: f for f in consultas.velocidad_por_tipo(con, ["norte"])}
        self.assertEqual(por_tipo["Auto"]["promedio"], 60.0)
        self.assertEqual((por_tipo["Auto"]["minimo"], por_tipo["Auto"]["maximo"], por_tipo["Auto"]["n"]), (50.0, 70.0, 2))
        self.assertEqual(consultas.excesos(con, ["norte"], 60.0), {"medidos": 3, "excesos": 1})
        self.assertEqual([f["velocidad_kmh"] for f in consultas.mas_rapidos(con, ["norte"], 2)], [70.0, 50.0])
        con.close()

    def test_el_filtro_de_camaras_se_respeta(self) -> None:
        con = self._con()
        self.assertEqual(sum(f["total"] for f in consultas.total_por_tipo(con, ["sur"])), 1)
        self.assertEqual(sum(f["total"] for f in consultas.total_por_tipo(con, ["norte", "sur"])), 4)
        con.close()

    def test_un_nombre_de_camara_malicioso_no_inyecta_sql(self) -> None:
        con = self._con()
        self.assertEqual(consultas.total_por_tipo(con, ["x') OR 1=1 --"]), [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM cruces").fetchone()[0], 4)     # la tabla sigue intacta
        con.close()

    def test_panel_completo(self) -> None:
        p = construir_panel(self.ruta, ["norte"], 90, CLASES, 60.0)
        self.assertEqual(p["estado"], "ok")
        self.assertEqual((p["total"], p["detenidos"], p["estado_via"]), (3, 1, "DETENIDO"))
        self.assertEqual(p["velocidad"], {"promedio": 53.3, "mediciones": 3, "excesos": 1, "pct_excesos": 33})
        self.assertEqual([t["total"] for t in p["tipos"]], [2, 1])
        self.assertEqual([t["pct"] for t in p["tipos"]], [67, 33])
        self.assertAlmostEqual(p["umbral_pico"], 66.0)           # p90 de [40, 50, 70]
        self.assertEqual(len(p["puntos"]), 3)
        self.assertEqual(p["cruces"][0]["tipo"], "Camion")        # el mas reciente primero
        self.assertEqual(p["camaras"], ["norte", "sur"])

    def test_panel_sin_seleccion_usa_todas_las_camaras(self) -> None:
        self.assertEqual(construir_panel(self.ruta, None, 90, CLASES, 60.0)["total"], 4)
        self.assertEqual(construir_panel(self.ruta, ["no_existe"], 90, CLASES, 60.0)["total"], 4)

    def test_el_panel_no_puede_modificar_la_base(self) -> None:
        from dashboard.backend.panel import abrir_solo_lectura
        con = abrir_solo_lectura(self.ruta)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("DELETE FROM cruces")
        con.close()

    def test_base_antigua_sin_tablas_nuevas_no_rompe(self) -> None:
        antigua = Path(self._tmp.name) / "antigua.db"
        con = sqlite3.connect(antigua)
        con.execute("CREATE TABLE cruces (id INTEGER PRIMARY KEY, track_id INTEGER, tipo TEXT, momento TIMESTAMP, "
                    "velocidad_kmh REAL, camara TEXT)")
        con.execute("INSERT INTO cruces (track_id, tipo, momento, velocidad_kmh, camara) VALUES (1, 'Auto', '2026-11-09 08:00:01.000', 55.0, 'v')")
        con.commit(); con.close()
        p = construir_panel(antigua, None, 90, CLASES, 60.0)
        self.assertEqual((p["estado"], p["total"], p["alertas"], p["lecturas"]), ("ok", 1, [], []))


class EstadosVaciosTest(unittest.TestCase):
    def test_estados(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(construir_panel(Path(tmp) / "no.db", None, 90, CLASES, 60.0)["estado"], "sin_bd")
            vacia = Path(tmp) / "vacia.db"
            with CrucesDB(vacia):
                pass
            self.assertEqual(construir_panel(vacia, None, 90, CLASES, 60.0)["estado"], "vacia")
            otra = Path(tmp) / "otra.db"
            c = sqlite3.connect(otra); c.execute("CREATE TABLE x (a)"); c.commit(); c.close()
            self.assertEqual(construir_panel(otra, None, 90, CLASES, 60.0)["estado"], "sin_tablas")


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        ruta = Path(self._tmp.name) / "database.db"
        with CrucesDB(ruta) as db:
            db.insertar_cruce(1, "Auto", T0, 55.0, "cam")
        self.cliente = TestClient(crear_app(ruta, limite_kmh=50.0))

    def test_panel_devuelve_json_con_el_limite_configurado(self) -> None:
        r = self.cliente.get("/api/panel")
        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertEqual((cuerpo["estado"], cuerpo["total"], cuerpo["limite_kmh"]), ("ok", 1, 50.0))
        self.assertEqual(cuerpo["velocidad"]["excesos"], 1)           # 55 > 50

    def test_parametros_validados(self) -> None:
        self.assertEqual(self.cliente.get("/api/panel?percentil=10").status_code, 422)
        self.assertEqual(self.cliente.get("/api/panel?camaras=cam&percentil=95").status_code, 200)

    def test_sirve_la_interfaz(self) -> None:
        r = self.cliente.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<h1", r.text)
        self.assertEqual(self.cliente.get("/js/main.js").status_code, 200)
        self.assertEqual(self.cliente.get("/css/tokens.css").status_code, 200)


if __name__ == "__main__":
    unittest.main()
