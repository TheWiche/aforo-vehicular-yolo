// Arranque de la interfaz: rutas, camara activa, carga de datos y actualizacion automatica.
//
// Hay dos tipos de vistas:
//   * de DATOS (resumen, vehiculos): necesitan que la base tenga cruces de la camara elegida;
//   * de TRABAJO (videos, calibrar, procesar, sistema): funcionan siempre, tambien con la base vacia.

import { pedirPanel } from "./api.js";
import { poner } from "./componentes/texto.js";
import { duracion, entero, esc, hora } from "./formato.js";
import { guardado } from "./estado.js";
import { crearCalibrar } from "./vistas/calibrar.js";
import { crearProcesar } from "./vistas/procesar.js";
import { crearResumen } from "./vistas/resumen.js";
import { crearSistema } from "./vistas/sistema.js";
import { crearVehiculos } from "./vistas/vehiculos.js";
import { crearVideos } from "./vistas/videos.js";

const $ = (id) => document.getElementById(id);
const INTERVALO_MS = 5000;
const VISTAS = ["videos", "calibrar", "procesar", "resumen", "vehiculos", "sistema"];     // orden = direccion del deslizamiento
const VISTAS_DE_DATOS = ["resumen", "vehiculos"];
const TITULOS = { resumen: "Resumen", vehiculos: "Vehículos", videos: "Videos", calibrar: "Calibrar", procesar: "Procesar", sistema: "Sistema" };

let panel = null;
let camara = guardado.leer("aforo.camara");
let firmaDatos = "";
let temporizador = 0;
let vistaActual = "";

// ------------------------------------- Rutas -------------------------------------
function ruta() {
  const [camino, consulta = ""] = location.hash.replace(/^#\/?/, "").split("?");
  return {
    vista: VISTAS.includes(camino) ? camino : null,
    parametros: Object.fromEntries(new URLSearchParams(consulta)),
  };
}
function irA(vista, parametros = {}) {
  const limpio = Object.entries(parametros).filter(([clave, valor]) =>
    valor !== "" && valor !== null && valor !== undefined && !(clave === "filtro" && valor === "todos") && !(clave === "orden" && valor === "hora"));
  const consulta = new URLSearchParams(limpio).toString();
  location.hash = `#/${vista}${consulta ? "?" + consulta : ""}`;
}

// --------------------------------------- Vistas ---------------------------------------
const resumen = crearResumen();
const vehiculos = crearVehiculos((parametros) => irA("vehiculos", parametros));
const videos = crearVideos();
const calibrar = crearCalibrar({ irA });
const sistema = crearSistema();
const procesar = crearProcesar({
  alEstado: pintarIndicador,
  alTerminar: async (datos) => {
    // El analisis acaba de terminar: se recarga el panel y se deja elegida su camara.
    if (datos.camara) { camara = datos.camara; guardado.escribir("aforo.camara", camara); }
    firmaDatos = "";
    await cargar();
  },
});

/** Indicador junto a "Procesar" en el menu: el avance mientras hay un analisis en marcha. */
function pintarIndicador(datos) {
  const chip = $("nav-proceso");
  const enMarcha = datos.estado === "corriendo" || datos.estado === "iniciando";
  chip.hidden = !enMarcha;
  if (enMarcha) poner(chip, datos.estado === "iniciando" ? "…" : `${Math.round((datos.progreso || 0) * 100)} %`);
}

function mostrarVista(nombre) {
  const anterior = vistaActual;
  if (anterior && anterior !== nombre && anterior === "procesar") procesar.ocultar();
  vistaActual = nombre;
  for (const id of [...VISTAS, "estado"]) {
    const seccion = $(`vista-${id}`);
    const visible = id === nombre;
    seccion.hidden = !visible;
    seccion.classList.remove("entra", "desde-izq");
    if (visible && anterior && anterior !== nombre) {
      // Deslizamiento de pagina: la vista nueva entra desde el lado hacia el que se navega.
      if (VISTAS.indexOf(nombre) < VISTAS.indexOf(anterior)) seccion.classList.add("desde-izq");
      void seccion.offsetWidth;
      seccion.classList.add("entra");
    }
  }
  document.querySelectorAll(".nav-item").forEach((a) => {
    if (a.dataset.vista === nombre) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  // La lista de camaras solo importa al mirar resultados.
  $("grupo-camaras").hidden = !VISTAS_DE_DATOS.includes(nombre) || !panel || panel.estado !== "ok";
  $("buscador").hidden = nombre !== "vehiculos";
  document.body.classList.remove("menu-abierto", "detalle-abierto");
  window.scrollTo(0, 0);
}

function hayDatos() { return panel && panel.estado === "ok"; }

function aplicarRuta(forzar = false) {
  const { vista: pedida, parametros } = ruta();
  // Sin direccion: se abre el resumen si ya hay resultados y, si no, el primer paso del flujo.
  const vista = pedida || (hayDatos() ? "resumen" : "videos");
  if (!pedida && location.hash === "") history.replaceState(null, "", `#/${vista}`);

  if (VISTAS_DE_DATOS.includes(vista)) {
    if (!hayDatos()) {
      $("h-estado").textContent = "Aún no hay datos";
      $("estado-mensaje").textContent = panel ? panel.mensaje : "";
      mostrarVista("estado");
      document.title = "Aforo vial";
      return;
    }
    mostrarVista(vista);
    if (vista === "vehiculos") { vehiculos.mostrar(panel, parametros, forzar); $("buscar").value = parametros.id || ""; }
    else resumen.redibujar();
    document.title = `${TITULOS[vista]} · ${panel.seleccion[0]} · Aforo vial`;
    return;
  }

  const cambio = vista !== vistaActual;
  // Una recarga de datos (forzar) no debe reiniciar la vista de trabajo en la que se esta (p. ej. un analisis en curso).
  if (forzar && !cambio) return;
  mostrarVista(vista);
  document.title = `${TITULOS[vista]} · Aforo vial`;
  if (vista === "videos") videos.mostrar();
  else if (vista === "calibrar") calibrar.mostrar(parametros);
  else if (vista === "procesar") procesar.mostrar(parametros);
  else if (vista === "sistema" && (cambio || forzar)) sistema.mostrar();
}

// --------------------------------- Marco: camaras ---------------------------------
function pintarMarco() {
  if (!hayDatos()) { $("camaras").innerHTML = ""; $("ambito").textContent = ""; return; }
  const info = panel.camaras_info || [];
  $("camaras").innerHTML = info.map((c) => `<button class="camara" type="button" role="radio" aria-checked="${c.camara === camara}" data-camara="${esc(c.camara)}">
      <span><span class="camara-nombre">${esc(c.camara)}</span>
      <span class="camara-nota">${entero(c.cruces)} ${c.cruces === 1 ? "cruce" : "cruces"}</span></span>
    </button>`).join("");
  const e = panel.ejecucion;
  $("ambito").innerHTML = `<b>${esc(camara)}</b>${e ? ` · ${esc(e.video)}${e.duracion_s ? ` · ${duracion(e.duracion_s)}` : ""}` : ""}`;
}
$("camaras").addEventListener("click", (evento) => {
  const boton = evento.target.closest(".camara");
  if (!boton || boton.dataset.camara === camara) return;
  camara = boton.dataset.camara;
  guardado.escribir("aforo.camara", camara);
  if (ruta().vista === "vehiculos") irA("vehiculos");       // los filtros de otra camara no aplican
  cargar();
});

// -------------------------------- Carga de datos --------------------------------
function aviso(mensaje) {
  let caja = $("aviso");
  if (!mensaje) { caja?.remove(); return; }
  if (!caja) {
    caja = document.createElement("div");
    caja.id = "aviso";
    caja.className = "aviso";
    caja.setAttribute("role", "status");
    $("contenido").prepend(caja);
  }
  caja.innerHTML = `<span>${esc(mensaje)}</span><button class="enlace" type="button">Reintentar</button>`;
  caja.querySelector("button").addEventListener("click", () => cargar());
}

async function cargar({ silencioso = false } = {}) {
  let nuevo;
  try {
    nuevo = await pedirPanel(camara);
    // Sin camara guardada (o si ya no existe) se abre la que tiene los datos mas recientes.
    if (nuevo.estado === "ok" && (!camara || !nuevo.camaras.includes(camara) || nuevo.seleccion.length !== 1)) {
      const reciente = [...nuevo.camaras_info].sort((a, b) => (a.hasta < b.hasta ? 1 : -1))[0];
      camara = reciente.camara;
      guardado.escribir("aforo.camara", camara);
      nuevo = await pedirPanel(camara);
    }
  } catch (error) {
    if (hayDatos()) {
      aviso(`No se pudo actualizar (${error.message}). Se muestran los datos de las ${hora(panel.generado)}.`);
    } else {
      aviso(`${error.message}`);
      panel = null;
      aplicarRuta();
    }
    return;
  }
  aviso(null);
  const cambioDeCamara = !hayDatos() || nuevo.estado !== "ok" || panel.seleccion[0] !== nuevo.seleccion[0];
  const habiaDatos = hayDatos();
  panel = nuevo;
  if (nuevo.estado !== "ok") {
    pintarMarco();
    aplicarRuta();
    return;
  }
  const firma = JSON.stringify([nuevo.seleccion, nuevo.total, nuevo.ultimo_cruce, nuevo.alertas.length, nuevo.lecturas.length, nuevo.limite_kmh, nuevo.camaras_info]);
  $("actualizado").textContent = `Actualizado ${hora(panel.generado)}`;
  if (silencioso && firma === firmaDatos && habiaDatos) return;         // nada nuevo: solo cambia el sello de hora
  firmaDatos = firma;
  pintarMarco();
  resumen.pintar(panel, cambioDeCamara);
  aplicarRuta(true);
}

// ------------------------------- Controles del marco -------------------------------
const interruptor = $("auto");
function fijarAuto(activo, alIniciar = false) {
  if (!alIniciar) interruptor.classList.add("is-init");    // sin esto el rebote se reproduce al cargar
  interruptor.dataset.on = String(activo);
  interruptor.setAttribute("aria-checked", String(activo));
  guardado.escribir("aforo.auto", activo ? "1" : "0");
  clearInterval(temporizador);
  if (activo) temporizador = setInterval(() => { if (!document.hidden) cargar({ silencioso: true }); }, INTERVALO_MS);
}
interruptor.addEventListener("click", () => fijarAuto(interruptor.dataset.on !== "true"));

$("refrescar").addEventListener("click", () => {
  const boton = $("refrescar");
  boton.classList.remove("girando");
  void boton.offsetWidth;
  boton.classList.add("girando");
  cargar();
});
$("estado-reintentar").addEventListener("click", () => cargar());

$("buscador").addEventListener("submit", (evento) => {
  evento.preventDefault();
  const id = $("buscar").value.replace(/\D/g, "");
  $("buscar").value = id;
  if (id) irA("vehiculos", { id });
  else if (ruta().vista === "vehiculos") irA("vehiculos", { ...ruta().parametros, id: "" });
});
document.addEventListener("keydown", (evento) => {
  const escribiendo = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "");
  if (evento.key === "/" && !escribiendo) { evento.preventDefault(); $("buscar").focus(); }
  if (evento.key === "Escape") document.body.classList.remove("menu-abierto", "detalle-abierto");
});

$("menu-abrir").addEventListener("click", () => { document.body.classList.add("menu-abierto"); $("menu-cerrar").focus(); });
$("menu-cerrar").addEventListener("click", () => { document.body.classList.remove("menu-abierto"); $("menu-abrir").focus(); });

window.addEventListener("hashchange", () => aplicarRuta());
// Cambios sin guardar en el calibrador: el navegador avisa antes de cerrar la pestana.
window.addEventListener("beforeunload", (e) => { if (calibrar.haySinGuardar()) { e.preventDefault(); e.returnValue = ""; } });

// ------------------------------------- Inicio -------------------------------------
fijarAuto(guardado.leer("aforo.auto") === "1", true);
procesar.retomar();
// Las etiquetas de los graficos se miden con la fuente ya cargada.
(document.fonts ? document.fonts.ready : Promise.resolve()).then(() => cargar());
