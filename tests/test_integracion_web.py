"""
Pruebas de la integracion web: perfiles de calibracion, canal de progreso (Reportero), control del
proceso, API de videos / calibracion / proceso y el lanzador `iniciar.py`.

Usan una carpeta temporal y un video sintetico minusculo: no tocan datos/ ni ejecutan YOLO.

Ejecutar:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

import _setup  # noqa: F401  (agrega src/ y la raiz al sys.path)
from fastapi.testclient import TestClient

import iniciar
from aforo import cli, perfiles
from aforo.config import ConfigError, cargar_configuracion
from aforo.reporte import Reportero
from dashboard.backend import proceso as modulo_proceso
from dashboard.backend import sistema, videos
from dashboard.backend.app import crear_app
from dashboard.backend.proceso import ErrorProceso, GestorProceso

ANCHO, ALTO, FPS, CUADROS = 160, 90, 10.0, 30


def crear_video(ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (ANCHO, ALTO))
    for i in range(CUADROS):
        escritor.write(np.full((ALTO, ANCHO, 3), i * 6, dtype=np.uint8))
    escritor.release()


PERFIL = {
    "CAMARA": "calle", "LINEA_VELOCIDAD_A": [[20, 20], [20, 70]], "LINEA_CONTEO": [[60, 20], [60, 70]],
    "LINEA_VELOCIDAD_B": [[100, 20], [100, 70]], "DISTANCIA_REAL_METROS": 8.0,
    "LIMITE_VELOCIDAD_KMH": 40.0, "VELOCIDAD_MAX_KMH": 120.0,
}


class PerfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ruta = Path(self._tmp.name) / "datos" / "calibraciones.json"

    def test_guardar_mezcla_y_conserva_otros_videos_y_claves(self) -> None:
        perfiles.guardar("a.mp4", {"CAMARA": "a", "nota": "hola"}, self.ruta)
        perfiles.guardar("b.mp4", PERFIL, self.ruta)
        perfiles.guardar("a.mp4", {"DISTANCIA_REAL_METROS": 5.0}, self.ruta)
        todos = perfiles.cargar(self.ruta)
        self.assertEqual(set(todos), {"a.mp4", "b.mp4"})
        self.assertEqual(todos["a.mp4"], {"CAMARA": "a", "nota": "hola", "DISTANCIA_REAL_METROS": 5.0})
        self.assertFalse(self.ruta.with_suffix(".json.tmp").exists())        # la escritura atomica no deja temporales

    def test_ignora_claves_desconocidas_y_archivos_danados(self) -> None:
        perfiles.guardar("a.mp4", {"CAMARA": "a", "otra_cosa": 1}, self.ruta)
        self.assertNotIn("otra_cosa", perfiles.cargar(self.ruta)["a.mp4"])
        self.ruta.write_text("{ no es json", encoding="utf-8")
        self.assertEqual(perfiles.cargar(self.ruta), {})
        self.assertEqual(perfiles.cargar(self.ruta.with_name("no_existe.json")), {})

    def test_perfil_valido_no_da_errores(self) -> None:
        errores, avisos = perfiles.validar(PERFIL, ANCHO, ALTO)
        self.assertEqual((errores, avisos), ([], []))

    def test_detecta_errores(self) -> None:
        malo = {**PERFIL, "LINEA_CONTEO": [[5, 5], [5, 6]], "DISTANCIA_REAL_METROS": 0,
                "LINEA_VELOCIDAD_B": [[100, 20], [300, 70]], "CAMARA": "con espacios"}
        texto = " ".join(perfiles.validar(malo, ANCHO, ALTO)[0])
        for esperado in ("demasiado corta", "distancia real", "sale del video", "nombre de la cámara"):
            self.assertIn(esperado, texto)
        self.assertTrue(perfiles.validar({**PERFIL, "VELOCIDAD_MAX_KMH": 30.0}, ANCHO, ALTO)[0])   # max <= limite
        self.assertTrue(perfiles.validar({k: v for k, v in PERFIL.items() if k != "LINEA_CONTEO"}, ANCHO, ALTO)[0])

    def test_avisa_si_el_conteo_queda_fuera_del_tramo(self) -> None:
        fuera = {**PERFIL, "LINEA_CONTEO": [[140, 20], [140, 70]]}
        errores, avisos = perfiles.validar(fuera, ANCHO, ALTO)
        self.assertEqual(errores, [])
        self.assertTrue(any("entre A y B" in a for a in avisos))

    def test_aplicar_a_config_solo_cambia_lo_que_define_el_perfil(self) -> None:
        base = cargar_configuracion()
        nueva = perfiles.aplicar_a_config(base, PERFIL)
        self.assertEqual(nueva.io.camara, "calle")
        self.assertEqual(nueva.counter.linea, ((60, 20), (60, 70)))
        self.assertEqual((nueva.speed.distancia_metros, nueva.alertas.limite_velocidad_kmh), (8.0, 40.0))
        self.assertEqual(nueva.detector, base.detector)                      # lo que no esta en el perfil queda igual
        parcial = perfiles.aplicar_a_config(base, {"DISTANCIA_REAL_METROS": 3.0})
        self.assertEqual((parcial.speed.distancia_metros, parcial.io.camara), (3.0, base.io.camara))
        with self.assertRaises(ConfigError):
            perfiles.aplicar_a_config(base, {"LINEA_CONTEO": "mal"})

    def test_sugerencia_es_un_perfil_valido(self) -> None:
        sugerido = perfiles.sugerir(1920, 1080)
        self.assertEqual(perfiles.validar({**sugerido, "CAMARA": "x"}, 1920, 1080), ([], []))


class ReporteroTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name)
        self.estado, self.cuadro, self.parar = d / "estado.json", d / "cuadro.jpg", d / "parar"

    def test_publica_estado_cuadro_y_atiende_la_parada(self) -> None:
        rep = Reportero(self.estado, self.cuadro, self.parar, meta={"video": "v.mp4"}, intervalo_estado_s=0, intervalo_cuadro_s=0)
        self.assertTrue(rep.cuadro_vencido() and rep.estado_vencido())
        rep.publicar_cuadro(np.zeros((1080, 1920, 3), dtype=np.uint8))
        img = cv2.imread(str(self.cuadro))
        self.assertEqual(img.shape[1], 960)                                   # se reduce para la vista previa
        rep.publicar_estado("corriendo", frame=5, total=2)
        datos = json.loads(self.estado.read_text(encoding="utf-8"))
        self.assertEqual((datos["estado"], datos["frame"], datos["video"]), ("corriendo", 5, "v.mp4"))
        self.assertFalse(rep.debe_parar())
        self.parar.write_text("parar")
        self.assertTrue(rep.debe_parar())
        rep.finalizar("detenido", total=2)
        self.assertEqual(json.loads(self.estado.read_text(encoding="utf-8"))["estado"], "detenido")

    def test_una_parada_vieja_no_afecta_a_la_corrida_nueva(self) -> None:
        self.parar.write_text("parar")
        self.assertFalse(Reportero(self.estado, None, self.parar).debe_parar())

    def test_respeta_el_intervalo_entre_cuadros(self) -> None:
        rep = Reportero(self.estado, self.cuadro, None, intervalo_cuadro_s=5.0)
        rep.publicar_cuadro(np.zeros((10, 10, 3), dtype=np.uint8))
        self.assertFalse(rep.cuadro_vencido())

    def test_sin_destinos_no_hace_nada(self) -> None:
        rep = Reportero(None)
        rep.publicar_estado("corriendo")
        rep.finalizar("terminado")
        self.assertFalse(rep.debe_parar() or rep.cuadro_vencido() or rep.estado_vencido())


class ComandoYEstadoTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        self.gestor = GestorProceso(self.raiz, self.raiz / "db.db", python="py")
        self.video = self.raiz / "v.mp4"

    def comando(self, modo: str, gpu: bool = True, reemplazar: bool = False, guardar: bool = False):
        return self.gestor.construir_comando(self.video, modo, "calle", gpu, reemplazar, guardar)

    def test_modo_vivo_usa_camara_aparte_tiempo_real_y_siempre_reemplaza(self) -> None:
        c = self.comando("vivo")
        self.assertIn("--tiempo-real", c)
        self.assertEqual(c[c.index("--camara") + 1], "calle_vivo")
        self.assertIn("--reemplazar", c)
        self.assertIn("--perfil", c)
        self.assertNotIn("--modelo", c)                                      # con GPU se usa el modelo configurado
        self.assertIn("--modelo", self.comando("vivo", gpu=False))            # sin GPU, el liviano

    def test_modo_completo_y_rapido(self) -> None:
        completo = self.comando("completo", reemplazar=True)
        self.assertIn("--cuadro-vivo", completo)
        self.assertIn("--reemplazar", completo)
        self.assertIn("--sin-video", completo)
        self.assertNotIn("--sin-video", self.comando("completo", guardar=True))
        self.assertNotIn("--camara", completo)                               # usa la camara del perfil
        rapido = self.comando("rapido")
        self.assertNotIn("--cuadro-vivo", rapido)                            # sin vista previa
        self.assertIn("--modelo", rapido)
        with self.assertRaises(ErrorProceso):
            self.comando("otro")

    def test_estado_libre_y_lectura_del_progreso(self) -> None:
        self.assertEqual(self.gestor.estado(), {"estado": "libre"})
        self.gestor.carpeta.mkdir(parents=True)
        self.gestor.ruta_estado.write_text(json.dumps(
            {"estado": "terminado", "frame": 50, "total_frames": 100, "cuadros_por_s": 10.0, "modo": "completo"}), encoding="utf-8")
        e = self.gestor.estado()
        self.assertEqual((e["estado"], e["progreso"], e["restante_s"]), ("terminado", 0.5, 5))

    def test_un_proceso_que_muere_sin_estado_final_se_reporta_como_error(self) -> None:
        self.gestor.carpeta.mkdir(parents=True)
        self.gestor.ruta_log.write_text("Traceback...\nValueError: algo fallo\n", encoding="utf-8")
        self.gestor.ruta_estado.write_text(json.dumps({"estado": "corriendo", "actualizado": time.time()}), encoding="utf-8")
        self.gestor._proceso = mock.Mock(poll=lambda: 1)                      # ya termino
        e = self.gestor.estado()
        self.assertEqual(e["estado"], "error")
        self.assertIn("algo fallo", e["mensaje"])

    def test_no_se_pueden_lanzar_dos_analisis(self) -> None:
        self.gestor._proceso = mock.Mock(poll=lambda: None)                   # sigue vivo
        with self.assertRaises(ErrorProceso):
            self.gestor.iniciar(self.video, "rapido", "calle", False, False, False)

    def test_detener_crea_el_archivo_de_parada(self) -> None:
        self.gestor._proceso = mock.Mock(poll=lambda: None, wait=lambda timeout=None: None)
        self.gestor.detener()
        self.assertTrue(self.gestor.ruta_parar.exists())


class ApiWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        crear_video(self.raiz / "datos" / "videos" / "calle.avi")
        self.gestor = mock.Mock()
        self.gestor.estado.return_value = {"estado": "libre"}
        self.cliente = TestClient(crear_app(self.raiz / "datos" / "db" / "x.db", raiz=self.raiz, gestor=self.gestor))

    def test_lista_videos_con_propiedades_y_estado(self) -> None:
        v = self.cliente.get("/api/videos").json()["videos"]
        self.assertEqual(len(v), 1)
        self.assertEqual((v[0]["nombre"], v[0]["ancho"], v[0]["alto"], v[0]["calibrado"]), ("calle.avi", ANCHO, ALTO, False))
        self.assertAlmostEqual(v[0]["duracion_s"], CUADROS / FPS, places=1)

    def test_cuadro_de_video_y_errores(self) -> None:
        r = self.cliente.get("/api/videos/cuadro", params={"video": "calle.avi", "t": 1.0, "ancho": 160})
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/jpeg"))
        self.assertEqual(self.cliente.get("/api/videos/cuadro", params={"video": "no.avi"}).status_code, 404)
        self.assertEqual(self.cliente.get("/api/videos/cuadro", params={"video": "calle.avi", "t": -1}).status_code, 422)
        # solo se usa el nombre: una ruta con carpetas no sale de datos/videos
        self.assertEqual(self.cliente.get("/api/videos/cuadro", params={"video": "../../x/calle.avi"}).status_code, 200)

    def test_calibracion_get_put_y_validacion(self) -> None:
        g = self.cliente.get("/api/calibracion", params={"video": "calle.avi"}).json()
        self.assertFalse(g["calibrado"])
        self.assertEqual((g["ancho"], g["alto"]), (ANCHO, ALTO))
        cuerpo = {"video": "calle.avi", "camara": "calle", "linea_conteo": PERFIL["LINEA_CONTEO"], "linea_a": PERFIL["LINEA_VELOCIDAD_A"],
                  "linea_b": PERFIL["LINEA_VELOCIDAD_B"], "distancia_m": 8.0, "limite_kmh": 40.0, "velocidad_max_kmh": 120.0}
        r = self.cliente.put("/api/calibracion", json=cuerpo)
        self.assertEqual((r.status_code, r.json()["ok"]), (200, True))
        guardado = json.loads((self.raiz / "datos" / "calibraciones.json").read_text(encoding="utf-8"))
        self.assertEqual(guardado["calle.avi"]["DISTANCIA_REAL_METROS"], 8.0)
        self.assertTrue(self.cliente.get("/api/calibracion", params={"video": "calle.avi"}).json()["calibrado"])
        self.assertTrue(self.cliente.get("/api/videos").json()["videos"][0]["calibrado"])
        # linea fuera del video -> 422 con la lista de errores
        malo = self.cliente.put("/api/calibracion", json={**cuerpo, "linea_conteo": [[0, 0], [999, 999]]})
        self.assertEqual(malo.status_code, 422)
        self.assertIn("sale del video", " ".join(malo.json()["detail"]["errores"]))
        self.assertEqual(self.cliente.put("/api/calibracion", json={**cuerpo, "distancia_m": "mucho"}).status_code, 422)
        self.assertEqual(self.cliente.put("/api/calibracion", json={**cuerpo, "video": "no.avi"}).status_code, 404)

    def test_agregar_video_por_ruta(self) -> None:
        with tempfile.TemporaryDirectory() as otra:
            externo = Path(otra) / "fuera.avi"
            crear_video(externo)
            self.assertEqual(self.cliente.post("/api/videos/agregar", json={"ruta": str(externo)}).json(), {"nombre": "fuera.avi"})
            lista = {v["nombre"]: v for v in self.cliente.get("/api/videos").json()["videos"]}
            self.assertTrue(lista["fuera.avi"]["externo"])
            self.assertEqual(self.cliente.get("/api/videos/cuadro", params={"video": "fuera.avi"}).status_code, 200)
        for ruta in ("relativa.avi", str(self.raiz / "no_existe.avi"), str(self.raiz / "datos" / "calibraciones.txt")):
            self.assertEqual(self.cliente.post("/api/videos/agregar", json={"ruta": ruta}).status_code, 422)

    def test_subir_video_valida_nombre_contenido_y_duplicados(self) -> None:
        crear_video(self.raiz / "origen.avi")
        datos = (self.raiz / "origen.avi").read_bytes()
        r = self.cliente.put("/api/videos/subir", params={"nombre": "nuevo.avi"}, content=datos)
        self.assertEqual((r.status_code, r.json()["bytes"]), (200, len(datos)))
        self.assertTrue((self.raiz / "datos" / "videos" / "nuevo.avi").is_file())
        self.assertEqual(self.cliente.put("/api/videos/subir", params={"nombre": "nuevo.avi"}, content=datos).status_code, 422)   # ya existe
        self.assertEqual(self.cliente.put("/api/videos/subir", params={"nombre": "doc.txt"}, content=datos).status_code, 422)     # no es video
        self.assertEqual(self.cliente.put("/api/videos/subir", params={"nombre": "roto.avi"}, content=b"no soy un video").status_code, 422)
        self.assertFalse((self.raiz / "datos" / "videos" / "roto.avi").exists())                 # no quedan restos
        self.assertFalse(list((self.raiz / "datos" / "videos").glob("*.part")))
        self.assertTrue(self.cliente.put("/api/videos/subir", params={"nombre": "../../escape.avi"}, content=datos).status_code == 200)
        self.assertFalse((self.raiz / "escape.avi").exists())                                    # el nombre se limpia: nunca sale de la carpeta

    def test_iniciar_proceso_exige_calibracion_y_modo_valido(self) -> None:
        r = self.cliente.post("/api/proceso/iniciar", json={"video": "calle.avi", "modo": "vivo"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("calibrado", r.json()["detail"])
        perfiles.guardar("calle.avi", PERFIL, self.raiz / "datos" / "calibraciones.json")
        self.assertEqual(self.cliente.post("/api/proceso/iniciar", json={"video": "calle.avi", "modo": "turbo"}).status_code, 422)
        with mock.patch.object(sistema, "estado_gpu", return_value={"modo": "gpu", "nombre": "X"}):
            ok = self.cliente.post("/api/proceso/iniciar", json={"video": "calle.avi", "modo": "vivo", "reemplazar": True})
        self.assertEqual(ok.status_code, 200)
        args = self.gestor.iniciar.call_args.args
        self.assertEqual((args[0].name, args[1], args[2], args[3]), ("calle.avi", "vivo", "calle", True))
        self.gestor.iniciar.side_effect = ErrorProceso("Ya hay un análisis en marcha.")
        with mock.patch.object(sistema, "estado_gpu", return_value={"modo": "cpu", "nombre": ""}):
            ocupado = self.cliente.post("/api/proceso/iniciar", json={"video": "calle.avi", "modo": "rapido"})
        self.assertEqual((ocupado.status_code, ocupado.json()["detail"]), (409, "Ya hay un análisis en marcha."))

    def test_calibracion_con_lineas_fuera_del_video_guardada_a_mano_no_se_procesa(self) -> None:
        perfiles.guardar("calle.avi", {**PERFIL, "LINEA_CONTEO": [[0, 0], [999, 999]]}, self.raiz / "datos" / "calibraciones.json")
        r = self.cliente.post("/api/proceso/iniciar", json={"video": "calle.avi", "modo": "rapido"})
        self.assertEqual(r.status_code, 409)

    def test_estado_proceso_y_detener(self) -> None:
        self.assertEqual(self.cliente.get("/api/proceso").json(), {"estado": "libre"})
        self.assertEqual(self.cliente.post("/api/proceso/detener").status_code, 200)
        self.gestor.detener.assert_called_once()
        self.gestor.cuadro.return_value = None
        self.assertEqual(self.cliente.get("/api/proceso/cuadro").status_code, 404)

    def test_sistema_devuelve_el_diagnostico(self) -> None:
        with mock.patch.object(sistema, "estado_gpu", return_value={"modo": "cpu", "nombre": ""}):
            d = self.cliente.get("/api/sistema").json()
        self.assertTrue(d["python_ok"])
        self.assertIn("cv2", [p["modulo"] for p in d["paquetes"]])
        self.assertEqual(d["gpu"]["modo"], "cpu")
        self.assertIn("pip install", d["gpu"]["comando"])

    def test_sirve_las_vistas_nuevas(self) -> None:
        html = self.cliente.get("/").text
        for vista in ("vista-videos", "vista-calibrar", "vista-procesar", "vista-sistema"):
            self.assertIn(vista, html)
        for js in ("js/vistas/calibrar.js", "js/vistas/procesar.js", "js/componentes/editorLineas.js", "css/herramientas.css"):
            self.assertEqual(self.cliente.get("/" + js).status_code, 200, js)


class CliPerfilTest(unittest.TestCase):
    def test_perfil_aplica_la_calibracion_del_video_y_las_opciones_la_sobrescriben(self) -> None:
        base = cargar_configuracion()
        args = cli._parsear_argumentos(["--video", "datos/videos/calle.avi", "--perfil", "--camara", "otra",
                                        "--tiempo-real", "--sin-ventana", "--db", "x.db"])
        with mock.patch.object(perfiles, "cargar", return_value={"calle.avi": PERFIL}):
            config = cli._aplicar_argumentos(base, args)
        self.assertEqual(config.counter.linea, ((60, 20), (60, 70)))
        self.assertEqual(config.alertas.limite_velocidad_kmh, 40.0)
        self.assertEqual(config.io.camara, "otra")                           # --camara gana al perfil
        self.assertEqual(config.io.db_ruta.name, "x.db")
        self.assertTrue(config.visual.tiempo_real)
        self.assertFalse(config.visual.mostrar_ventana)                      # --sin-ventana: la vista previa va a la web

    def test_perfil_de_un_video_sin_calibrar_da_un_error_claro(self) -> None:
        args = cli._parsear_argumentos(["--video", "datos/videos/nuevo.mp4", "--perfil"])
        with mock.patch.object(perfiles, "cargar", return_value={}), self.assertRaises(ConfigError) as ctx:
            cli._aplicar_argumentos(cargar_configuracion(), args)
        self.assertIn("calibración", str(ctx.exception))

    def test_tiempo_real_sin_la_opcion_abre_ventana(self) -> None:
        args = cli._parsear_argumentos(["--tiempo-real"])
        self.assertTrue(cli._aplicar_argumentos(cargar_configuracion(), args).visual.mostrar_ventana)


class LanzadorTest(unittest.TestCase):
    def test_modulos_faltantes(self) -> None:
        existe = lambda m: None if m in ("torch", "fastapi") else object()
        self.assertEqual(iniciar.modulos_faltantes({"cv2": "opencv-python", "torch": "torch", "fastapi": "fastapi"}, existe), ["torch", "fastapi"])
        self.assertEqual(iniciar.modulos_faltantes({"cv2": "x"}, lambda m: object()), [])

    def test_cuda_del_driver_e_indice_de_torch(self) -> None:
        cabecera = "| NVIDIA-SMI 616.92   Driver Version: 616.92   CUDA Version: 13.4 |"
        self.assertEqual(iniciar.version_cuda_del_driver(cabecera), (13, 4))
        self.assertIsNone(iniciar.version_cuda_del_driver("sin gpu"))
        self.assertEqual(iniciar.indice_de_torch((13, 4)), "cu130")
        self.assertEqual(iniciar.indice_de_torch((12, 8)), "cu126")
        self.assertIsNone(iniciar.indice_de_torch((12, 1)))
        self.assertIsNone(iniciar.indice_de_torch(None))

    def test_comando_de_torch_con_cuda_fija_las_mismas_versiones_que_requirements(self) -> None:
        cmd = " ".join(iniciar.comando_torch_cuda("cu130", "py"))
        requisitos = (Path(iniciar.__file__).parent / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn(f"torch=={iniciar.VERSION_TORCH}", requisitos)
        self.assertIn(f"torchvision=={iniciar.VERSION_TORCHVISION}", requisitos)
        self.assertIn(f"torch=={iniciar.VERSION_TORCH}+cu130", cmd)
        self.assertIn("whl/cu130", cmd)

    def test_puerto_libre_salta_los_ocupados(self) -> None:
        import socket
        with socket.socket() as ocupado:
            ocupado.bind(("127.0.0.1", 0))
            ocupado.listen()
            puerto = ocupado.getsockname()[1]
            libre = iniciar.puerto_libre(puerto)
            self.assertIsNotNone(libre)
            self.assertNotEqual(libre, puerto)

    def test_revisa_el_entorno_sin_abrir_el_panel(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(iniciar, "revisar_python", return_value=True), \
                mock.patch.object(iniciar, "revisar_dependencias", return_value=False):
            self.assertEqual(iniciar.main(["--solo-revisar"]), 1)             # dependencias sin resolver: no continua
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(iniciar, "revisar_python", return_value=True), \
                mock.patch.object(iniciar, "revisar_dependencias", return_value=True), \
                mock.patch.object(iniciar, "revisar_gpu"), mock.patch.object(iniciar, "revisar_pesos"), \
                mock.patch.object(iniciar, "revisar_configuracion", return_value=True):
            self.assertEqual(iniciar.main(["--solo-revisar"]), 0)


if __name__ == "__main__":
    unittest.main()
