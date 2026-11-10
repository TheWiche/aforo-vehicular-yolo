"""
Pruebas del tracking: IDs unicos y estables, y que el ID del tracker es el que
termina guardado en la base de datos. Usan detecciones sinteticas (sin YOLO).

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import numpy as np
import supervision as sv

import _setup  # noqa: F401  (agrega src/ y la raiz al sys.path)

from aforo.config import CounterConfig, cargar_configuracion  # noqa: E402
from aforo.persistencia.db import CrucesDB, RegistradorCruces  # noqa: E402
from aforo.analitica.line_counter import LineCounter  # noqa: E402
from aforo.vision.tracker import VehicleTracker  # noqa: E402
from aforo.evaluacion.verificar_tracking import AuditorTracking  # noqa: E402

FPS = 25.0
NOMBRES = {2: "Auto", 3: "Moto", 5: "Bus", 7: "Camion"}


def _detecciones(cajas: List[Tuple[float, float, float, float]], clases: List[int]) -> sv.Detections:
    return sv.Detections(
        xyxy=np.array(cajas, dtype=float).reshape(-1, 4),
        confidence=np.full(len(cajas), 0.9),
        class_id=np.array(clases, dtype=int),
    )


def _con_ids(cajas, ids, clases=None) -> sv.Detections:
    det = _detecciones(cajas, clases or [2] * len(cajas))
    det.tracker_id = np.array(ids, dtype=int)
    return det


class TrackerIdsTest(unittest.TestCase):
    """Dos vehiculos que se cruzan en carriles distintos: ID unico, estable y distinto entre si."""

    def setUp(self) -> None:
        self.tracker = VehicleTracker(cargar_configuracion().tracker, fps=FPS)

    def _escenario(self, frames: int = 70):
        """Auto A baja por x=100 (y1 = 200 + 6f); camion B sube por x=400 (y1 = 700 - 6f)."""
        for f in range(frames):
            ya = 200 + 6 * f
            yb = 700 - 6 * f
            cajas = [(100, ya, 160, ya + 40), (400, yb, 480, yb + 60)]
            yield f, _detecciones(cajas, [2, 7])

    def test_cada_vehiculo_conserva_un_unico_id(self) -> None:
        ids_a, ids_b = set(), set()
        for f, det in self._escenario():
            seguidos, _ = self.tracker.update(det, frame_idx=f)
            for caja, tid in zip(seguidos.xyxy, seguidos.tracker_id):
                (ids_a if caja[0] < 250 else ids_b).add(int(tid))
        self.assertEqual(len(ids_a), 1, f"el auto A cambio de ID: {ids_a}")
        self.assertEqual(len(ids_b), 1, f"el camion B cambio de ID: {ids_b}")
        self.assertTrue(ids_a.isdisjoint(ids_b), "dos vehiculos distintos comparten ID")

    def test_el_id_del_tracker_es_el_que_se_guarda_en_la_bd(self) -> None:
        contador = LineCounter(CounterConfig(((0, 400), (1280, 400)), "A", "B"), NOMBRES)
        ids_vistos = {}
        with tempfile.TemporaryDirectory() as tmp:
            with CrucesDB(Path(tmp) / "database.db") as db:
                reg = RegistradorCruces(db, "cam")
                for f, det in self._escenario():
                    seguidos, movimientos = self.tracker.update(det, frame_idx=f)
                    for caja, tid, cid in zip(seguidos.xyxy, seguidos.tracker_id, seguidos.class_id):
                        ids_vistos[int(cid)] = int(tid)
                    for cruce in contador.update(movimientos):
                        reg.registrar_cruce(cruce.track_id, NOMBRES[cruce.class_id],
                                            datetime(2026, 1, 1))
                filas = db._con.execute("SELECT track_id, tipo FROM cruces ORDER BY tipo").fetchall()
        # Una fila por vehiculo, con exactamente el ID que asigno el tracker.
        self.assertEqual(sorted(filas), sorted([(ids_vistos[2], "Auto"), (ids_vistos[7], "Camion")]))

    def test_las_detecciones_no_confirmadas_no_reciben_id(self) -> None:
        # En el primer frame ByteTrack aun no confirma el track: no debe salir ningun ID.
        seguidos, movimientos = self.tracker.update(_detecciones([(100, 100, 160, 140)], [2]), frame_idx=0)
        self.assertEqual(len(seguidos), 0)
        self.assertEqual(movimientos, [])


class AuditorTest(unittest.TestCase):
    def test_trayectoria_limpia_pasa_las_pruebas(self) -> None:
        aud = AuditorTracking(max_frames_sin_ver=20)
        for f in range(30):
            aud.observar(f, _con_ids([(100 + 5 * f, 100, 160 + 5 * f, 140)], [0]))
        inf = aud.informe()
        self.assertTrue(inf.invariantes_ok)
        self.assertEqual((inf.ids_totales, inf.saltos_sospechosos, inf.ids_efimeros), (1, 0, 0))

    def test_detecta_id_repetido_en_un_frame(self) -> None:
        aud = AuditorTracking(max_frames_sin_ver=20)
        aud.observar(0, _con_ids([(0, 0, 50, 50), (300, 0, 350, 50)], [1, 1]))
        self.assertEqual(aud.informe().duplicados_en_frame, 1)
        self.assertFalse(aud.informe().invariantes_ok)

    def test_detecta_id_reutilizado_tras_caducar(self) -> None:
        aud = AuditorTracking(max_frames_sin_ver=10)
        aud.observar(0, _con_ids([(0, 0, 50, 50)], [4]))
        aud.observar(40, _con_ids([(0, 0, 50, 50)], [4]))      # reaparece tras 40 frames
        self.assertEqual(aud.informe().reapariciones_tardias, 1)

    def test_detecta_salto_sospechoso_de_un_id(self) -> None:
        aud = AuditorTracking(max_frames_sin_ver=20)
        aud.observar(0, _con_ids([(0, 0, 50, 50)], [2]))
        aud.observar(1, _con_ids([(600, 0, 650, 50)], [2]))    # "teletransporte" de 600 px
        self.assertEqual(aud.informe().saltos_sospechosos, 1)

    def test_recuperar_un_id_tras_una_oclusion_corta_es_valido(self) -> None:
        aud = AuditorTracking(max_frames_sin_ver=20)
        aud.observar(0, _con_ids([(0, 0, 50, 50)], [3]))
        aud.observar(8, _con_ids([(40, 0, 90, 50)], [3]))      # oculto 7 frames y vuelve cerca
        inf = aud.informe()
        self.assertTrue(inf.invariantes_ok)
        self.assertEqual(inf.saltos_sospechosos, 0)


if __name__ == "__main__":
    unittest.main()
