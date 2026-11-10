"""
Pruebas del calculo de metricas (evaluar.py) con casos construidos a mano, donde la
respuesta correcta se puede verificar con lapiz y papel.

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import CrucesDB  # noqa: E402
from evaluar import (  # noqa: E402
    Evento,
    calcular_metricas,
    cargar_eventos_sistema,
    cargar_verdad_terreno,
    emparejar,
    escribir_informe,
    guardar_metricas,
)

E = Evento


class EmparejamientoTest(unittest.TestCase):
    def test_pareja_dentro_de_la_ventana(self) -> None:
        self.assertEqual(emparejar([E(5.0, "Auto")], [E(5.6, "Auto")], 1.0), [(0, 0)])

    def test_fuera_de_la_ventana_no_hay_pareja(self) -> None:
        self.assertEqual(emparejar([E(5.0, "Auto")], [E(6.5, "Auto")], 1.0), [])

    def test_cada_evento_se_usa_una_sola_vez(self) -> None:
        # Un evento GT con dos candidatos del sistema: solo el mas cercano es pareja.
        pares = emparejar([E(5.0, "Auto")], [E(5.8, "Auto"), E(5.1, "Auto")], 1.0)
        self.assertEqual(pares, [(0, 1)])

    def test_asignacion_global_por_cercania(self) -> None:
        gt = [E(5.0, "Auto"), E(5.9, "Auto")]
        sis = [E(5.5, "Auto"), E(6.0, "Auto")]
        # 5.9<->6.0 (0.1) se asigna primero; luego 5.0<->5.5 (0.5).
        self.assertEqual(sorted(emparejar(gt, sis, 1.0)), [(0, 0), (1, 1)])


class MetricasTest(unittest.TestCase):
    def test_sistema_perfecto(self) -> None:
        gt = [E(1, "Auto"), E(5, "Bus"), E(9, "Moto")]
        sis = [E(1.2, "Auto"), E(4.8, "Bus"), E(9.3, "Moto")]
        r = calcular_metricas(gt, sis)
        self.assertEqual((r.tp, r.fp, r.fn), (3, 0, 0))
        self.assertEqual((r.precision, r.recall, r.f1), (1.0, 1.0, 1.0))
        self.assertEqual(r.clasificacion_acierto, 1.0)
        self.assertEqual(r.aforo_error_pct, 0.0)

    def test_precision_recall_f1_con_errores(self) -> None:
        # GT: 4 vehiculos. Sistema: acierta 3, cuenta 1 de mas (FP) y se pierde 1 (FN).
        gt = [E(1, "Auto"), E(5, "Auto"), E(9, "Auto"), E(14, "Auto")]
        sis = [E(1.1, "Auto"), E(5.2, "Auto"), E(9.1, "Auto"), E(20, "Auto")]
        r = calcular_metricas(gt, sis)
        self.assertEqual((r.tp, r.fp, r.fn), (3, 1, 1))
        self.assertAlmostEqual(r.precision, 0.75)           # 3 / (3 + 1)
        self.assertAlmostEqual(r.recall, 0.75)              # 3 / (3 + 1)
        self.assertAlmostEqual(r.f1, 0.75)                  # 2*.75*.75 / 1.5
        self.assertAlmostEqual(r.aforo_error_pct, 0.0)      # contó 4 y eran 4: el total coincide por casualidad

    def test_error_de_aforo_por_tipo_y_total(self) -> None:
        gt = [E(1, "Auto"), E(5, "Auto"), E(9, "Camion")]
        sis = [E(1, "Auto"), E(5, "Auto"), E(9, "Auto"), E(13, "Auto")]
        r = calcular_metricas(gt, sis)
        self.assertAlmostEqual(r.aforo_error_pct, 100 * 1 / 3)       # 4 contados vs 3 reales
        self.assertEqual(r.aforo_por_tipo, {"Auto": (2, 4), "Camion": (1, 0)})

    def test_clasificacion_y_matriz_de_confusion(self) -> None:
        gt = [E(1, "Auto"), E(5, "Camion")]
        sis = [E(1, "Auto"), E(5, "Bus")]
        r = calcular_metricas(gt, sis)
        self.assertAlmostEqual(r.clasificacion_acierto, 0.5)
        self.assertEqual(r.confusion, {("Auto", "Auto"): 1, ("Camion", "Bus"): 1})

    def test_error_de_velocidad_mae_rmse(self) -> None:
        gt = [E(1, "Auto", 50.0), E(5, "Auto", 60.0), E(9, "Auto", None)]
        sis = [E(1, "Auto", 54.0), E(5, "Auto", 57.0), E(9, "Auto", 80.0)]
        r = calcular_metricas(gt, sis)
        # Errores: +4 y -3 (el tercero no tiene velocidad real y se ignora).
        self.assertEqual(r.velocidad_n, 2)
        self.assertAlmostEqual(r.velocidad_mae, 3.5)
        self.assertAlmostEqual(r.velocidad_rmse, ((16 + 9) / 2) ** 0.5)
        self.assertEqual(r.velocidad_dentro_tolerancia_pct, 100.0)

    def test_alerta_de_exceso_de_velocidad(self) -> None:
        # Limite 60. Reales sobre el limite: 70 y 65. El sistema alerta 63 (acierto), 58 (se le escapa)
        # y 62 sobre un vehiculo real de 55 (falsa alarma).
        gt = [E(1, "Auto", 70.0), E(5, "Auto", 65.0), E(9, "Auto", 55.0), E(13, "Auto", 40.0)]
        sis = [E(1, "Auto", 63.0), E(5, "Auto", 58.0), E(9, "Auto", 62.0), E(13, "Auto", 41.0)]
        r = calcular_metricas(gt, sis, limite_kmh=60.0)
        self.assertEqual(r.exceso_n_real, 2)
        self.assertAlmostEqual(r.exceso_recall, 0.5)         # detecto 1 de 2 excesos reales
        self.assertAlmostEqual(r.exceso_precision, 0.5)      # de 2 alertas, 1 era real

    def test_sin_limite_no_se_calcula_la_alerta(self) -> None:
        r = calcular_metricas([E(1, "Auto", 70.0)], [E(1, "Auto", 70.0)])
        self.assertIsNone(r.exceso_recall)

    def test_sin_eventos_no_divide_entre_cero(self) -> None:
        r = calcular_metricas([], [])
        self.assertEqual((r.precision, r.recall, r.f1), (0.0, 0.0, 0.0))
        self.assertIsNone(r.aforo_error_pct)
        self.assertIsNone(r.velocidad_mae)


class EntradaSalidaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db = self.dir / "database.db"

    def test_cargar_verdad_de_terreno(self) -> None:
        ruta = self.dir / "gt.json"
        ruta.write_text(json.dumps({"cruces": [
            {"segundo": 9.0, "tipo": "Bus", "velocidad_kmh": 41.5},
            {"segundo": 2.0, "tipo": "Auto", "velocidad_kmh": None}]}), encoding="utf-8")
        eventos = cargar_verdad_terreno(ruta)
        self.assertEqual(eventos, [E(2.0, "Auto", None), E(9.0, "Bus", 41.5)])      # ordenados por tiempo

    def test_verdad_de_terreno_inexistente_da_mensaje_claro(self) -> None:
        with self.assertRaises(FileNotFoundError):
            cargar_verdad_terreno(self.dir / "no_existe.json")

    def test_eventos_del_sistema_se_leen_con_select_y_en_segundos_desde_el_inicio(self) -> None:
        inicio = datetime(2026, 11, 9, 8, 0, 0)
        with CrucesDB(self.db) as db:
            db.registrar_ejecucion("cam", "v.mp4", inicio, 25.0, 250)         # 10 s de video
            db.insertar_cruce(1, "Auto", inicio + timedelta(seconds=2.5), 50.0, "cam")
            db.insertar_cruce(2, "Bus", inicio + timedelta(seconds=8.0), None, "cam")
            db.insertar_cruce(3, "Auto", inicio + timedelta(hours=5), None, "cam")     # de otra corrida: se ignora
            db.insertar_cruce(4, "Auto", inicio + timedelta(seconds=3), None, "otra")  # otra camara: se ignora
        eventos, t0 = cargar_eventos_sistema(self.db, "cam")
        self.assertEqual(t0, inicio)
        self.assertEqual(eventos, [E(2.5, "Auto", 50.0), E(8.0, "Bus", None)])

    def test_camara_sin_ejecucion_da_error_claro(self) -> None:
        with CrucesDB(self.db):
            pass
        with self.assertRaises(ValueError):
            cargar_eventos_sistema(self.db, "nadie")

    def test_guardar_metricas_y_regenerar_informe(self) -> None:
        r = calcular_metricas([E(1, "Auto", 50.0)], [E(1, "Auto", 53.0)])
        guardar_metricas(self.db, "cam", r, 1.0)
        con = sqlite3.connect(self.db)
        nombres = {f[0] for f in con.execute("SELECT metrica FROM metricas")}
        con.close()
        self.assertTrue({"eventos_precision", "eventos_recall", "eventos_f1", "velocidad_mae_kmh"} <= nombres)
        informe = self.dir / "informe.md"
        escribir_informe(self.db, informe)
        texto = informe.read_text(encoding="utf-8")
        self.assertIn("Camara `cam`", texto)
        self.assertIn("velocidad_mae_kmh", texto)


if __name__ == "__main__":
    unittest.main()
