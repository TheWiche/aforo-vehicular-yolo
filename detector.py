"""
detector.py
===========
Capa de DETECCION: envuelve el modelo YOLOv8 de Ultralytics y entrega, para
cada frame, unicamente los vehiculos de interes (auto, moto, bus, camion).

Por que YOLOv8
--------------
YOLO ("You Only Look Once") es un detector de una sola etapa: la red recibe la
imagen completa y predice en UNA pasada las cajas delimitadoras (bounding boxes),
la clase y la confianza de cada objeto. Esto lo hace lo bastante rapido para
procesar video casi en tiempo real. Usamos pesos pre-entrenados en COCO
(80 clases), por lo que NO hace falta entrenar nada: solo filtramos las clases
que nos interesan.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

import numpy as np
import supervision as sv
from ultralytics import YOLO

from config import DetectorConfig

logger = logging.getLogger(__name__)


class ModeloError(RuntimeError):
    """Se lanza si el modelo YOLO no se puede cargar o ejecutar."""


@contextmanager
def _directorio_de_trabajo(destino: Path) -> Iterator[None]:
    """Cambia temporalmente el directorio de trabajo y SIEMPRE lo restaura."""
    anterior = Path.cwd()
    os.chdir(destino)
    try:
        yield
    finally:
        os.chdir(anterior)


class VehicleDetector:
    """
    Detector de vehiculos basado en YOLOv8.

    Se implementa como clase (POO) para cargar los pesos UNA sola vez en el
    constructor; cargar el modelo en cada frame seria extremadamente lento.
    """

    def __init__(self, config: DetectorConfig) -> None:
        self._config = config
        # IDs COCO que queremos conservar: car=2, motorcycle=3, bus=5, truck=7.
        self._class_ids: List[int] = sorted(config.clases.keys())
        self._model = self._cargar_modelo(config.modelo)

    @staticmethod
    def _cargar_modelo(ruta: Path) -> YOLO:
        """
        Carga los pesos. Si `ruta` no existe y es un modelo oficial (p. ej.
        'yolov8s.pt'), Ultralytics lo descarga automaticamente en esa ubicacion.

        Detalle tecnico: Ultralytics elimina internamente los apostrofes de las
        rutas (`str(ruta).replace("'", "")`). Si alguna carpeta del proyecto
        contiene uno (p. ej. "Yolo'Aforo"), el modelo se descargaria/buscaria en
        OTRA carpeta. Para evitarlo se entra a la carpeta de los pesos y se
        carga por NOMBRE de archivo (que no contiene apostrofes).
        """
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Cargando modelo YOLO: %s", ruta)
            with _directorio_de_trabajo(ruta.parent):
                return YOLO(ruta.name)
        except Exception as exc:  # Ultralytics lanza varios tipos de error segun el caso
            raise ModeloError(f"No se pudo cargar el modelo '{ruta}': {exc}") from exc

    @property
    def class_names(self) -> dict[int, str]:
        """Mapa id_clase -> nombre en espanol, tal como lo define config.py."""
        return dict(self._config.clases)

    def detect(self, frame: np.ndarray) -> sv.Detections:
        """
        Ejecuta YOLO sobre un frame BGR y devuelve un objeto `sv.Detections`
        (cajas xyxy, confianza y class_id) ya filtrado a vehiculos.

        Parameters
        ----------
        frame : np.ndarray
            Imagen BGR (formato nativo de OpenCV) de forma (alto, ancho, 3).
        """
        try:
            resultados = self._model.predict(
                source=frame,
                conf=self._config.confianza,    # descarta detecciones poco seguras
                iou=self._config.iou_nms,       # NMS: elimina cajas duplicadas del mismo objeto
                imgsz=self._config.tamano_imagen,
                classes=self._class_ids,        # filtro de clases dentro del propio modelo
                device=self._config.dispositivo,
                verbose=False,
            )
        except Exception as exc:
            raise ModeloError(f"Fallo la inferencia de YOLO: {exc}") from exc

        detecciones = sv.Detections.from_ultralytics(resultados[0])

        # Filtro defensivo: aunque `classes=` ya filtra, nos aseguramos de que
        # jamas llegue otra clase a las etapas siguientes.
        if detecciones.class_id is not None and len(detecciones) > 0:
            detecciones = detecciones[np.isin(detecciones.class_id, self._class_ids)]
        return detecciones
