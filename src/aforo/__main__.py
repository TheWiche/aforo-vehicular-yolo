"""
Punto de entrada unico del proyecto:  python -m aforo [comando] [opciones]

Sin comando abre el menu interactivo. Cada comando delega en el modulo que lo
implementa (las importaciones son perezosas: `python -m aforo --help` responde al
instante y el menu funciona aunque falten las dependencias pesadas).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# comando -> (modulo, descripcion)
COMANDOS: Dict[str, Tuple[str, str]] = {
    "menu": ("aforo.menu", "Menu interactivo: diagnostico, configuracion, videos, procesar... (por defecto)"),
    "procesar": ("aforo.cli", "Procesa un video: deteccion, conteo, velocidad, alertas -> base de datos"),
    "dashboard": ("dashboard.__main__", "Abre el dashboard web (API FastAPI + interfaz propia)"),
    "descargar": ("aforo.herramientas.descargar_videos", "Descarga videos de trafico de prueba a datos/videos/"),
    "calibrar": ("aforo.herramientas.seleccionar_puntos", "Obtiene coordenadas de las lineas haciendo clic en un frame"),
    "anotar": ("aforo.evaluacion.anotar_verdad_terreno", "Marca a mano los cruces de un video (verdad de terreno)"),
    "evaluar": ("aforo.evaluacion.evaluar", "Calcula precision, recall, F1 y error de velocidad"),
    "auditar": ("aforo.evaluacion.verificar_tracking", "Audita la unicidad y estabilidad de los IDs del tracker"),
    "fallas": ("aforo.herramientas.capturar_fallas", "Extrae frames de un video para documentar casos de falla"),
    "evidencia": ("aforo.herramientas.generar_evidencia_fallas", "Regenera las imagenes de los casos de falla 3 y 4"),
}


def _ayuda() -> str:
    filas = "\n".join(f"  {nombre:<10} {desc}" for nombre, (_, desc) in COMANDOS.items())
    return (
        "Uso: python -m aforo [comando] [opciones]\n\n"
        f"Comandos:\n{filas}\n\n"
        "Cada comando acepta --help. Ejemplo: python -m aforo procesar --help"
    )


def _cargar(comando: str) -> Callable[[Optional[List[str]]], int]:
    modulo = COMANDOS[comando][0]
    if modulo.startswith("dashboard"):
        # El dashboard vive en la carpeta `dashboard/` de la raiz, fuera del paquete `aforo`.
        raiz = str(Path(__file__).resolve().parents[2])
        if raiz not in sys.path:
            sys.path.insert(0, raiz)
    return importlib.import_module(modulo).main  # type: ignore[attr-defined, no-any-return]


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _cargar("menu")(None) or 0
    comando, resto = argv[0], argv[1:]
    if comando in ("-h", "--help", "help"):
        print(_ayuda())
        return 0
    if comando not in COMANDOS:
        print(f"Comando desconocido: '{comando}'\n\n{_ayuda()}", file=sys.stderr)
        return 2
    return int(_cargar(comando)(resto) or 0)


if __name__ == "__main__":
    sys.exit(main())
