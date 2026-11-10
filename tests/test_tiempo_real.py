"""
Pruebas del lector de cuadros del modo tiempo real (AforoPipeline._cuadros).

Usan un video sintetico minusculo escrito con OpenCV: el cuadro N tiene brillo proporcional a N,
asi se comprueba que el indice entregado corresponde al cuadro real del video.

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

import _setup  # noqa: F401  (agrega src/ y la raiz al sys.path)
from aforo.pipeline import AforoPipeline, VideoError  # noqa: E402

FPS = 30.0
CUADROS = 60


def _crear_video(ruta: Path) -> None:
    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (64, 48))
    for i in range(CUADROS):
        escritor.write(np.full((48, 64, 3), i * 4, dtype=np.uint8))
    escritor.release()


def _numero_de_cuadro(frame: np.ndarray) -> int:
    return round(float(frame.mean()) / 4)


class CuadrosTiempoRealTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.video = Path(self._tmp.name) / "v.avi"
        _crear_video(self.video)

    def test_modo_normal_entrega_todos_los_cuadros_en_orden(self) -> None:
        indices = [i for i, _ in AforoPipeline._cuadros(self.video, FPS, False)]
        self.assertEqual(indices, list(range(CUADROS)))

    def test_tiempo_real_con_consumidor_lento_salta_cuadros_pero_conserva_el_indice_real(self) -> None:
        entregados = []
        for idx, frame in AforoPipeline._cuadros(self.video, FPS, True):
            entregados.append(idx)
            self.assertAlmostEqual(_numero_de_cuadro(frame), idx, delta=1)    # el indice es el del video
            time.sleep(0.25)                                                   # analizar tarda 7 cuadros
            if len(entregados) == 4:
                break
        self.assertEqual(entregados, sorted(set(entregados)))                 # estrictamente creciente
        self.assertGreater(entregados[-1] - entregados[0], len(entregados))  # hubo saltos
        self.assertLess(entregados[-1], CUADROS)

    def test_tiempo_real_con_consumidor_rapido_no_salta_y_respeta_el_reloj(self) -> None:
        t0 = time.perf_counter()
        indices = [i for i, _ in AforoPipeline._cuadros(self.video, FPS, True)]
        duracion = time.perf_counter() - t0
        self.assertGreaterEqual(len(indices), CUADROS - 3)                    # casi ninguno saltado
        self.assertGreater(duracion, 0.8 * CUADROS / FPS)                    # dura lo que dura el video

    def test_video_inexistente_en_tiempo_real_da_error_claro(self) -> None:
        with self.assertRaises(VideoError):
            next(AforoPipeline._cuadros(Path(self._tmp.name) / "no.avi", FPS, True))


if __name__ == "__main__":
    unittest.main()
