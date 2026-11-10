"""
Pruebas del analisis de movimiento (movimiento.py) y de las reglas de alerta
(alertas.py). Usan imagenes sinteticas: no necesitan videos ni YOLO.

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

import numpy as np

import _setup  # noqa: F401  (agrega src/ y la raiz al sys.path)

from aforo.analitica.alertas import EstadoTrafico, MonitorTrafico, supera_limite  # noqa: E402
from aforo.config import AlertasConfig, MovimientoConfig, cargar_configuracion  # noqa: E402
from aforo.vision.movimiento import DetectorMovimiento  # noqa: E402

ROI = np.array([[0, 0], [199, 0], [199, 199], [0, 199]], dtype=np.int32)
CFG = MovimientoConfig(escala=1.0, alfa_fondo=0.1, umbral_diferencia=25, kernel_apertura=3, kernel_cierre=7)


def _frame_gris(valor: int = 100) -> np.ndarray:
    return np.full((200, 200, 3), valor, dtype=np.uint8)


def _con_bloque(x: int, y: int, lado: int = 40, valor: int = 220) -> np.ndarray:
    f = _frame_gris()
    f[y:y + lado, x:x + lado] = valor
    return f


class MovimientoTest(unittest.TestCase):
    def _detector(self, cfg: MovimientoConfig = CFG) -> DetectorMovimiento:
        return DetectorMovimiento(cfg, ROI, (200, 200))

    def test_escena_estatica_no_tiene_movimiento(self) -> None:
        det = self._detector()
        for _ in range(10):
            res = det.actualizar(_frame_gris())
        self.assertEqual(res.ratio_roi, 0.0)

    def test_un_objeto_que_se_mueve_genera_movimiento(self) -> None:
        det = self._detector()
        for _ in range(5):
            det.actualizar(_frame_gris())
        res = det.actualizar(_con_bloque(60, 60))
        # El bloque cubre 40x40 de una ROI de 200x200 (4 %); la mascara lo detecta casi completo.
        self.assertGreater(res.ratio_roi, 0.03)

    def test_la_apertura_morfologica_elimina_el_ruido_puntual(self) -> None:
        ruidoso = _frame_gris()
        ruidoso[100, 100] = 255                 # un solo pixel "caliente" (ruido del sensor)
        con_apertura, sin_apertura = self._detector(), self._detector(dataclasses.replace(CFG, kernel_apertura=1, kernel_cierre=1))
        for d in (con_apertura, sin_apertura):
            for _ in range(5):
                d.actualizar(_frame_gris())
        # Con apertura 3x3 el pixel aislado desaparece; sin apertura la umbralizacion lo deja pasar.
        self.assertEqual(con_apertura.actualizar(ruidoso).ratio_roi, 0.0)
        self.assertGreater(sin_apertura.actualizar(ruidoso).ratio_roi, 0.0)

    def test_el_cierre_morfologico_rellena_huecos_dentro_del_objeto(self) -> None:
        bloque = _con_bloque(60, 60)
        bloque[75:79, 75:79] = 100              # "hueco" del color del fondo dentro del vehiculo
        con_cierre = self._detector()
        sin_cierre = self._detector(dataclasses.replace(CFG, kernel_cierre=1))
        for d in (con_cierre, sin_cierre):
            for _ in range(5):
                d.actualizar(_frame_gris())
        r_con = con_cierre.actualizar(bloque).ratio_roi
        r_sin = sin_cierre.actualizar(bloque).ratio_roi
        self.assertGreater(r_con, r_sin)

    def test_un_vehiculo_detenido_se_absorbe_en_el_fondo(self) -> None:
        det = self._detector()
        for _ in range(5):
            det.actualizar(_frame_gris())
        caja = np.array([[60, 60, 100, 100]], dtype=float)
        al_llegar = det.actualizar(_con_bloque(60, 60), caja).ratio_en_vehiculos
        for _ in range(40):
            det.actualizar(_con_bloque(60, 60), caja)
        despues = det.actualizar(_con_bloque(60, 60), caja).ratio_en_vehiculos
        self.assertGreater(al_llegar, 0.8)      # cuando llega, casi toda la caja "cambio"
        self.assertLess(despues, 0.1)           # estatico: el promedio movil ya lo aprendio

    def test_sin_cajas_no_hay_ratio_en_vehiculos(self) -> None:
        det = self._detector()
        self.assertIsNone(det.actualizar(_frame_gris()).ratio_en_vehiculos)

    def test_contar_vehiculos_en_roi(self) -> None:
        det = DetectorMovimiento(CFG, np.array([[50, 50], [150, 50], [150, 150], [50, 150]]), (200, 200))
        puntos = np.array([[100, 100], [10, 10], [149, 149], [180, 100]], dtype=float)
        self.assertEqual(det.contar_vehiculos_en_roi(puntos), 2)

    def test_configuracion_por_defecto_incluye_movimiento_y_alertas_validos(self) -> None:
        cfg = cargar_configuracion()
        self.assertGreater(cfg.alertas.limite_velocidad_kmh, 0)
        self.assertEqual(cfg.movimiento.kernel_apertura % 2, 1)


class AlertasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = AlertasConfig(
            limite_velocidad_kmh=60.0, detenido_min_vehiculos=3, detenido_ratio_max=0.12,
            detenido_segundos=4.0, salida_segundos=2.0, calentamiento_s=3.0, intervalo_lectura_s=5.0,
        )
        self.monitor = MonitorTrafico(self.cfg)

    def _simular(self, desde: float, hasta: float, vehiculos: int, ratio: float, paso: float = 0.5):
        alertas, t = [], desde
        while t < hasta:
            act = self.monitor.actualizar(t, vehiculos, ratio)
            if act.alerta_nueva:
                alertas.append(t)
            t += paso
        return alertas

    def test_limite_de_velocidad(self) -> None:
        self.assertTrue(supera_limite(60.1, 60.0))
        self.assertFalse(supera_limite(60.0, 60.0))
        self.assertFalse(supera_limite(45.0, 60.0))

    def test_sin_vehiculos_el_estado_es_libre(self) -> None:
        self.assertEqual(self.monitor.actualizar(10.0, 0, None).estado, EstadoTrafico.LIBRE)

    def test_vehiculos_en_movimiento_es_fluido_sin_alerta(self) -> None:
        self.assertEqual(self._simular(0, 30, vehiculos=5, ratio=0.6), [])
        self.assertEqual(self.monitor.estado, EstadoTrafico.FLUIDO)

    def test_trafico_detenido_sostenido_genera_una_sola_alerta(self) -> None:
        alertas = self._simular(5, 40, vehiculos=6, ratio=0.02)
        self.assertEqual(len(alertas), 1)                       # una por episodio, no una por frame
        self.assertAlmostEqual(alertas[0], 9.0, delta=0.6)      # tras 4 s de condicion sostenida
        self.assertEqual(self.monitor.estado, EstadoTrafico.DETENIDO)

    def test_un_parpadeo_corto_no_genera_alerta(self) -> None:
        self._simular(5, 10, vehiculos=6, ratio=0.5)
        self.assertEqual(self._simular(10, 12, vehiculos=6, ratio=0.02), [])    # solo 2 s detenido
        self.assertEqual(self.monitor.estado, EstadoTrafico.FLUIDO)

    def test_durante_el_calentamiento_no_se_alerta(self) -> None:
        self.assertEqual(self._simular(0, 3, vehiculos=6, ratio=0.0), [])

    def test_el_episodio_termina_y_uno_nuevo_vuelve_a_alertar(self) -> None:
        primera = self._simular(5, 15, vehiculos=6, ratio=0.02)
        self._simular(15, 20, vehiculos=6, ratio=0.7)           # vuelve a fluir (> 2 s)
        self.assertEqual(self.monitor.estado, EstadoTrafico.FLUIDO)
        segunda = self._simular(20, 35, vehiculos=6, ratio=0.02)
        self.assertEqual((len(primera), len(segunda)), (1, 1))

    def test_pocos_vehiculos_quietos_no_es_congestion(self) -> None:
        # 2 vehiculos parados (< minimo de 3): puede ser un par de autos estacionados.
        self.assertEqual(self._simular(5, 40, vehiculos=2, ratio=0.0), [])


if __name__ == "__main__":
    unittest.main()
