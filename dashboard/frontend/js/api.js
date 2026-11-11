// Acceso a la API del backend. Todo error se convierte en un ErrorApi con un mensaje legible.

export class ErrorApi extends Error {
  constructor(mensaje, estado = 0, detalles = []) {
    super(mensaje);
    this.estado = estado;
    this.detalles = detalles;          // lista de problemas (p. ej. los errores de validacion de la calibracion)
  }
}

/** Convierte la respuesta de error de FastAPI ({"detail": ...}) en un mensaje para la persona. */
async function leerError(respuesta) {
  let detalle = null;
  try { detalle = (await respuesta.json()).detail; } catch { /* sin cuerpo JSON */ }
  if (typeof detalle === "string") return new ErrorApi(detalle, respuesta.status);
  if (detalle && Array.isArray(detalle.errores)) return new ErrorApi(detalle.errores[0], respuesta.status, detalle.errores);
  if (Array.isArray(detalle) && detalle.length) {
    const lista = detalle.map((d) => `${(d.loc || []).slice(1).join(".") || "valor"}: ${d.msg}`);
    return new ErrorApi(`Datos no válidos (${lista[0]}).`, respuesta.status, lista);
  }
  return new ErrorApi(`El servidor respondió ${respuesta.status}.`, respuesta.status);
}

async function pedir(ruta, parametros = {}, opciones = {}) {
  const consulta = new URLSearchParams();
  for (const [clave, valor] of Object.entries(parametros)) {
    if (valor !== null && valor !== undefined && valor !== "") consulta.set(clave, valor);
  }
  const texto = consulta.toString();
  let respuesta;
  try {
    respuesta = await fetch(texto ? `${ruta}?${texto}` : ruta, { headers: { Accept: "application/json" }, ...opciones });
  } catch {
    throw new ErrorApi("No se pudo conectar con el servidor. ¿Sigue abierto iniciar.py?");
  }
  if (!respuesta.ok) throw await leerError(respuesta);
  return respuesta.json();
}

const enviarJson = (metodo, cuerpo) => ({
  method: metodo, headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(cuerpo),
});

// ---- Resultados -------------------------------------------------------------------------
/** Resumen de una camara (o de todas si no se indica). El percentil 85 es la V85 de transito. */
export const pedirPanel = (camara) => pedir("/api/panel", { camaras: camara, percentil: 85 });
export const pedirCruces = (parametros) => pedir("/api/cruces", parametros);
export const urlFotograma = (camara, momento) =>
  `/api/fotograma?${new URLSearchParams({ camara, ...(momento ? { t: momento } : {}) })}`;

// ---- Videos y calibracion ---------------------------------------------------------------
export const pedirVideos = () => pedir("/api/videos");
export const urlCuadroVideo = (video, segundo, ancho = 1280) =>
  `/api/videos/cuadro?${new URLSearchParams({ video, t: String(Math.max(0, segundo)), ancho: String(ancho) })}`;
export const pedirCalibracion = (video) => pedir("/api/calibracion", { video });
export const guardarCalibracion = (perfil) => pedir("/api/calibracion", {}, enviarJson("PUT", perfil));
export const agregarVideoRuta = (ruta) => pedir("/api/videos/agregar", {}, enviarJson("POST", { ruta }));

/** Sube un video con progreso (fetch no informa del avance de subida; XMLHttpRequest si). */
export function subirVideo(archivo, alProgreso) {
  return new Promise((resolver, rechazar) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/videos/subir?${new URLSearchParams({ nombre: archivo.name })}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) alProgreso(e.loaded / e.total); };
    xhr.onerror = () => rechazar(new ErrorApi("Se interrumpió la subida."));
    xhr.onload = () => {
      let cuerpo = {};
      try { cuerpo = JSON.parse(xhr.responseText); } catch { /* sin JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolver(cuerpo);
      rechazar(new ErrorApi(typeof cuerpo.detail === "string" ? cuerpo.detail : `El servidor respondió ${xhr.status}.`, xhr.status));
    };
    xhr.send(archivo);
  });
}

// ---- Procesamiento y sistema --------------------------------------------------------------
export const pedirProceso = () => pedir("/api/proceso");
export const iniciarProceso = (cuerpo) => pedir("/api/proceso/iniciar", {}, enviarJson("POST", cuerpo));
export const detenerProceso = () => pedir("/api/proceso/detener", {}, { method: "POST" });
export const urlVistaEnVivo = () => `/api/proceso/video?ts=${Date.now()}`;
export const urlUltimoCuadro = () => `/api/proceso/cuadro?ts=${Date.now()}`;
export const pedirSistema = () => pedir("/api/sistema");
