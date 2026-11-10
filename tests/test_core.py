"""
Pruebas unitarias de la logica NO dependiente de modelos: geometria, conteo y
velocidad. No necesitan GPU, video ni descargar pesos de YOLO.

Ejecutar desde la carpeta del proyecto:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List

# Permite importar los modulos de la raiz del proyecto desde /tests.
import _setup  # noqa: F401  (agrega src/ y la raiz al sys.path)

from aforo.config import ConfigError, CounterConfig, SpeedConfig, cargar_configuracion  # noqa: E402
from aforo.analitica.geometry import segment_intersection  # noqa: E402
from aforo.analitica.line_counter import LineCounter  # noqa: E402
from aforo.analitica.speed_estimator import SpeedEstimator  # noqa: E402
from aforo.vision.tracker import Movement  # noqa: E402

FPS = 25.0


def _mov(tid: int, p0, p1, f0: int, f1: int, cid: int = 2) -> Movement:
    return Movement(tid, cid, p0, p1, f0, f1)


def _trayectoria_vertical(tid: int, y_ini: float, y_fin: float, px_por_frame: float,
                          x: float = 600.0, frame_ini: int = 0) -> List[Movement]:
    """Genera un vehiculo que se mueve en linea recta vertical, un Movement por frame."""
    movs: List[Movement] = []
    paso = px_por_frame if y_fin > y_ini else -px_por_frame
    y, f = y_ini, frame_ini
    while (paso > 0 and y < y_fin) or (paso < 0 and y > y_fin):
        movs.append(_mov(tid, (x, y), (x, y + paso), f, f + 1))
        y += paso
        f += 1
    return movs


class GeometriaTest(unittest.TestCase):
    def test_cruce_simple(self) -> None:
        res = segment_intersection((5, -5), (5, 5), (0, 0), (10, 0))
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res[0], 0.5)   # el cruce ocurre a la mitad del trayecto

    def test_sin_cruce(self) -> None:
        self.assertIsNone(segment_intersection((5, 1), (5, 5), (0, 0), (10, 0)))

    def test_paralelos(self) -> None:
        self.assertIsNone(segment_intersection((0, 1), (10, 1), (0, 0), (10, 0)))

    def test_fuera_del_segmento_de_la_linea(self) -> None:
        # La recta infinita se cruzaria, pero el segmento finito de la linea no llega.
        self.assertIsNone(segment_intersection((20, -5), (20, 5), (0, 0), (10, 0)))

    def test_sentidos_opuestos_tienen_signo_opuesto(self) -> None:
        arriba = segment_intersection((5, 5), (5, -5), (0, 0), (10, 0))
        abajo = segment_intersection((5, -5), (5, 5), (0, 0), (10, 0))
        self.assertEqual(arriba[1], -abajo[1])


class ConteoTest(unittest.TestCase):
    def setUp(self) -> None:
        cfg = CounterConfig(linea=((0, 400), (1280, 400)), etiqueta_a="Sube", etiqueta_b="Baja")
        self.contador = LineCounter(cfg, {2: "Auto", 3: "Moto", 5: "Bus", 7: "Camion"})

    def test_cuenta_por_clase_y_sentido(self) -> None:
        self.contador.update([_mov(1, (100, 450), (100, 350), 0, 1, cid=2)])   # sube
        self.contador.update([_mov(2, (200, 350), (200, 450), 0, 1, cid=7)])   # baja
        self.assertEqual(self.contador.counts_by_class[2], 1)
        self.assertEqual(self.contador.counts_by_class[7], 1)
        self.assertEqual(self.contador.total, 2)
        self.assertEqual(self.contador.counts_by_direction, {"A": 1, "B": 1})

    def test_no_cuenta_dos_veces_el_mismo_id(self) -> None:
        self.contador.update([_mov(1, (100, 450), (100, 350), 0, 1)])
        self.contador.update([_mov(1, (100, 350), (100, 450), 1, 2)])   # rebota sobre la linea
        self.assertEqual(self.contador.total, 1)

    def test_vehiculo_que_no_cruza_no_cuenta(self) -> None:
        self.contador.update([_mov(1, (100, 500), (100, 450), 0, 1)])
        self.assertEqual(self.contador.total, 0)


class VelocidadTest(unittest.TestCase):
    def setUp(self) -> None:
        # ROI: lineas en y=300 y y=500; 20 m reales entre ellas.
        self.cfg = SpeedConfig(
            linea_a=((0, 300), (1280, 300)),
            linea_b=((0, 500), (1280, 500)),
            distancia_metros=20.0,
            velocidad_min_kmh=2.0,
            velocidad_max_kmh=200.0,
        )

    def _medir(self, movs: List[Movement]):
        est = SpeedEstimator(self.cfg, fps=FPS)
        res = []
        for m in movs:
            res.extend(est.update([m]))
        return est, res

    def test_velocidad_72_kmh(self) -> None:
        # 8 px/frame * 25 FPS = 200 px/s; la ROI mide 200 px => 1 s => 20 m/s = 72 km/h.
        _, res = self._medir(_trayectoria_vertical(1, 250, 550, 8))
        self.assertEqual(len(res), 1)
        self.assertAlmostEqual(res[0].speed_kmh, 72.0, delta=0.5)

    def test_funciona_en_sentido_contrario(self) -> None:
        _, res = self._medir(_trayectoria_vertical(1, 550, 250, 8))
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].entry_line, "B")
        self.assertAlmostEqual(res[0].speed_kmh, 72.0, delta=0.5)

    def test_interpolacion_subframe(self) -> None:
        # 7.3 px/frame no coincide con las lineas: sin interpolar el error seria grande.
        _, res = self._medir(_trayectoria_vertical(1, 251.3, 560, 7.3))
        esperada = 7.3 * FPS / 200.0 * 20.0 * 3.6      # px/s -> m/s -> km/h
        self.assertAlmostEqual(res[0].speed_kmh, esperada, delta=0.2)

    def test_velocidad_inverosimil_se_descarta(self) -> None:
        # 100 px/frame * 25 FPS = 2500 px/s; la ROI mide 200 px => 0.08 s => 250 m/s
        # = 900 km/h: supera VELOCIDAD_MAX_KMH (200) y debe descartarse.
        est, res = self._medir(_trayectoria_vertical(1, 250, 560, 100))
        self.assertEqual(res, [])
        self.assertIsNone(est.speed_of(1))

    def test_estado_midiendo(self) -> None:
        est = SpeedEstimator(self.cfg, fps=FPS)
        movs = _trayectoria_vertical(1, 250, 400, 8)    # entra a la ROI y no sale
        for m in movs:
            est.update([m])
        self.assertTrue(est.is_measuring(1))
        self.assertIsNone(est.speed_of(1))

    def test_fps_invalido(self) -> None:
        with self.assertRaises(ValueError):
            SpeedEstimator(self.cfg, fps=0)


class ConfigTest(unittest.TestCase):
    def test_configuracion_por_defecto_es_valida(self) -> None:
        cargar_configuracion()

    def test_fecha_inicio_valida_e_invalida(self) -> None:
        from datetime import datetime
        from aforo.config import _parsear_fecha
        self.assertEqual(_parsear_fecha("2026-11-09 08:30:00"), datetime(2026, 11, 9, 8, 30))
        self.assertIsNone(_parsear_fecha(None))
        with self.assertRaises(ConfigError):
            _parsear_fecha("ayer por la tarde")

    def test_camara_vacia_es_invalida(self) -> None:
        import dataclasses
        cfg = cargar_configuracion()
        mala = dataclasses.replace(cfg, io=dataclasses.replace(cfg.io, camara="  "))
        with self.assertRaises(ConfigError):
            mala.validate()

    def test_distancia_cero_es_invalida(self) -> None:
        import dataclasses
        cfg = cargar_configuracion()
        mala = dataclasses.replace(cfg, speed=dataclasses.replace(cfg.speed, distancia_metros=0))
        with self.assertRaises(ConfigError):
            mala.validate()


if __name__ == "__main__":
    unittest.main()
