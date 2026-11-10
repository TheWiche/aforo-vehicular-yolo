"""
Pruebas del menu interactivo (menu.py): edicion segura de config.py, validacion de
valores y comprobaciones del diagnostico. No abren ventanas ni ejecutan YOLO.

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import menu  # noqa: E402

TEXTO = '''"""Doc con acentos: línea."""
RAIZ = Path("x")
NOMBRE: str = "videos/a.mp4"      # comentario con ñ y acentos
DISTANCIA: float = 20.0   # metros
LINEA: Tuple[Point, Point] = ((0, 400), (1280, 400))
CLASES: Dict[int, str] = {
    2: "Auto",
}
OPCIONAL: Optional[str] = None
'''


class EdicionDeConfigTest(unittest.TestCase):
    def test_lee_solo_constantes_literales_de_una_linea(self) -> None:
        c = menu.leer_constantes(TEXTO)
        self.assertEqual(set(c), {"NOMBRE", "DISTANCIA", "LINEA", "OPCIONAL"})   # sin RAIZ (Path) ni CLASES (multilinea)
        self.assertEqual(c["LINEA"].valor, ((0, 400), (1280, 400)))
        self.assertIsNone(c["OPCIONAL"].valor)

    def test_reemplaza_solo_el_valor_y_conserva_comentarios(self) -> None:
        nuevo = menu.reemplazar_constante(TEXTO, "DISTANCIA", 35.5)
        self.assertIn("DISTANCIA: float = 35.5   # metros", nuevo)
        self.assertEqual(nuevo.replace("35.5", "20.0"), TEXTO)           # nada mas cambio

    def test_funciona_con_acentos_antes_en_el_archivo_y_cadenas(self) -> None:
        nuevo = menu.reemplazar_constante(TEXTO, "NOMBRE", "videos/ñandú.mp4")
        self.assertIn('NOMBRE: str = "videos/ñandú.mp4"      # comentario con ñ y acentos', nuevo)

    def test_reemplaza_lineas_y_none(self) -> None:
        nuevo = menu.reemplazar_constante(TEXTO, "LINEA", ((10, 20), (30, 40)))
        self.assertIn("= ((10, 20), (30, 40))", nuevo)
        nuevo = menu.reemplazar_constante(nuevo, "OPCIONAL", "2026-01-01 08:00:00")
        self.assertEqual(menu.leer_constantes(nuevo)["OPCIONAL"].valor, "2026-01-01 08:00:00")

    def test_respeta_finales_de_linea_crlf(self) -> None:
        crlf = TEXTO.replace("\n", "\r\n")
        nuevo = menu.reemplazar_constante(crlf, "DISTANCIA", 5.0)
        self.assertEqual(nuevo.count("\r\n"), crlf.count("\r\n"))
        self.assertEqual(menu.leer_constantes(nuevo)["DISTANCIA"].valor, 5.0)

    def test_constante_inexistente_o_no_editable(self) -> None:
        with self.assertRaises(KeyError):
            menu.reemplazar_constante(TEXTO, "CLASES", {})

    def test_la_config_real_tiene_todos_los_parametros_del_catalogo(self) -> None:
        reales = menu.valores_actuales()
        faltan = [p.nombre for g in menu.GRUPOS.values() for p in g if p.nombre not in reales]
        self.assertEqual(faltan, [])

    def test_un_cambio_invalido_se_revierte(self) -> None:
        original = menu.CONFIG_PY.read_text(encoding="utf-8")
        try:
            error = menu.aplicar_cambios({"DISTANCIA_REAL_METROS": -5.0})    # config.validate() lo rechaza
            self.assertIsNotNone(error)
            self.assertEqual(menu.CONFIG_PY.read_text(encoding="utf-8"), original)
        finally:
            menu.CONFIG_PY.write_text(original, encoding="utf-8", newline="")

    def test_un_cambio_valido_se_guarda(self) -> None:
        original = menu.CONFIG_PY.read_text(encoding="utf-8")
        try:
            self.assertIsNone(menu.aplicar_cambios({"LIMITE_VELOCIDAD_KMH": 77.0}))
            self.assertEqual(menu.valores_actuales()["LIMITE_VELOCIDAD_KMH"], 77.0)
        finally:
            menu.CONFIG_PY.write_text(original, encoding="utf-8", newline="")
        self.assertEqual(menu.CONFIG_PY.read_text(encoding="utf-8"), original)


class ParseoDeValoresTest(unittest.TestCase):
    def _p(self, nombre: str) -> menu.Parametro:
        return menu._buscar_parametro(nombre)

    def test_numeros_con_coma_y_rangos(self) -> None:
        self.assertEqual(menu.parsear_valor(self._p("DISTANCIA_REAL_METROS"), "12,5"), 12.5)
        with self.assertRaises(ValueError):
            menu.parsear_valor(self._p("DISTANCIA_REAL_METROS"), "0")
        with self.assertRaises(ValueError):
            menu.parsear_valor(self._p("CONFIANZA_MINIMA"), "1.5")
        with self.assertRaises(ValueError):
            menu.parsear_valor(self._p("TAMANO_IMAGEN"), "abc")

    def test_lineas_aceptan_varios_separadores(self) -> None:
        esperado = ((10, 20), (30, 40))
        for texto in ("10,20,30,40", "10 20 30 40", "(10, 20), (30, 40)", "10;20;30;40"):
            self.assertEqual(menu.parsear_valor(self._p("LINEA_CONTEO"), texto), esperado)
        with self.assertRaises(ValueError):
            menu.parsear_valor(self._p("LINEA_CONTEO"), "10,20,30")

    def test_booleanos_fecha_dispositivo_ancla_y_ruta(self) -> None:
        self.assertTrue(menu.parsear_valor(self._p("MOSTRAR_VENTANA"), "s"))
        self.assertFalse(menu.parsear_valor(self._p("MOSTRAR_VENTANA"), "no"))
        self.assertIsNone(menu.parsear_valor(self._p("FECHA_INICIO_VIDEO"), "none"))
        self.assertEqual(menu.parsear_valor(self._p("FECHA_INICIO_VIDEO"), "2026-11-09 08:00:00"), "2026-11-09 08:00:00")
        with self.assertRaises(ValueError):
            menu.parsear_valor(self._p("FECHA_INICIO_VIDEO"), "ayer")
        self.assertIsNone(menu.parsear_valor(self._p("DISPOSITIVO"), "auto"))
        self.assertEqual(menu.parsear_valor(self._p("DISPOSITIVO"), "cpu"), "cpu")
        self.assertEqual(menu.parsear_valor(self._p("ANCLA_VEHICULO"), "center"), "CENTER")
        with self.assertRaises(ValueError):
            menu.parsear_valor(self._p("ANCLA_VEHICULO"), "medio")
        self.assertEqual(menu.parsear_valor(self._p("VIDEO_ENTRADA"), "videos\\mi video.mp4"), "videos/mi video.mp4")

    def test_salida_de_seleccionar_puntos(self) -> None:
        salida = ("Resolucion...\n\nPega esto en config.py:\n\n"
                  "LINEA_CONTEO = ((1, 2), (3, 4))\nLINEA_VELOCIDAD_A = ((5, 6), (7, 8))\n")
        self.assertEqual(menu.parsear_salida_seleccionar(salida),
                         {"LINEA_CONTEO": ((1, 2), (3, 4)), "LINEA_VELOCIDAD_A": ((5, 6), (7, 8))})
        self.assertEqual(menu.parsear_salida_seleccionar("nada"), {})


class DiagnosticoTest(unittest.TestCase):
    def test_lineas_fuera_de_cuadro(self) -> None:
        vals = {"LINEA_CONTEO": ((0, 100), (500, 100)), "LINEA_VELOCIDAD_A": ((0, 0), (900, 0)),
                "LINEA_VELOCIDAD_B": ((0, 50), (100, 700))}
        self.assertEqual(menu.lineas_fuera_de_cuadro(vals, 640, 480), ["LINEA_VELOCIDAD_A", "LINEA_VELOCIDAD_B"])
        self.assertEqual(menu.lineas_fuera_de_cuadro(vals, 1000, 800), [])

    def test_deteccion_de_calibracion_de_ejemplo(self) -> None:
        self.assertTrue(menu.es_calibracion_de_ejemplo(dict(menu.VALORES_EJEMPLO)))
        otra = dict(menu.VALORES_EJEMPLO, DISTANCIA_REAL_METROS=33.0)
        self.assertFalse(menu.es_calibracion_de_ejemplo(otra))

    def test_los_presets_son_validos(self) -> None:
        for nombre, preset in menu.PRESETS.items():
            self.assertEqual(set(preset), set(menu.VALORES_EJEMPLO), nombre)

    def test_dependencias_faltantes_devuelve_nombres_pip(self) -> None:
        for pip in menu.dependencias_faltantes(True):
            self.assertIn(pip, [v[0] for v in {**menu.DEPENDENCIAS_NUCLEO, **menu.DEPENDENCIAS_DASHBOARD}.values()])

    def test_resumen_de_bd_inexistente_es_none(self) -> None:
        self.assertIsNone(menu.resumen_bd(Path("no_existe.db")))


if __name__ == "__main__":
    unittest.main()
