// Arranque de la interfaz: rutas (#/resumen, #/vehiculos), camara activa, carga de datos y
// actualizacion automatica. Cada vista vive en su modulo y solo recibe el panel ya cargado.

import { pedirPanel } from "./api.js";
import { duracion, entero, esc, fecha, hora } from "./formato.js";
import { crearResumen } from "./vistas/resumen.js";
import { crearVehiculos } from "./vistas/vehiculos.js";

const $ = (id) => document.getElementById(id);
const INTERVALO_MS = 5000;
const VISTAS = ["resumen", "vehiculos"];

// ----------------------------- Preferencias guardadas -----------------------------
const guardado = {
  leer(clave) { try { return localStorage.getItem(clave); } catch { return null; } },
  escribir(clave, valor) { try { localStorage.setItem(clave, valor); } catch { /* modo privado */ } },
};

let panel = null;
let camara = guardado.leer("aforo.camara");
let firmaDatos = "";
let temporizador = 0;
let vistaActual = "";

// ------------------------------------- Rutas -------------------------------------
function ruta() {
  const [camino, consulta = ""] = location.hash.replace(/^#\/?/, "").split("?");
  return { vista: VISTAS.includes(camino) ? camino : "resumen", parametros: Object.fromEntries(new URLSearchParams(consulta)) };
}
function irA(vista, parametros = {}) {
  const limpio = Object.entries(parametros).filter(([clave, valor]) =>
    valor !== "" && valor !== null && valor !== undefined && !(clave === "filtro" && valor === "todos") && !(clave === "orden" && valor === "hora"));
  const consulta = new URLSearchParams(limpio).toString();
  location.hash = `#/${vista}${consulta ? "?" + consulta : ""}`;
}

const resumen = crearResumen();
const vehiculos = crearVehiculos((parametros) => irA("vehiculos", parametros));

function mostrarVista(nombre) {
  const anterior = vistaActual;
  vistaActual = nombre;
  for (const id of ["resumen", "vehiculos", "estado"]) {
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
  document.body.classList.remove("menu-abierto", "detalle-abierto");
}

function aplicarRuta(forzar = false) {
  if (!panel || panel.estado !== "ok") return;
  const { vista, parametros } = ruta();
  mostrarVista(vista);
  if (vista === "vehiculos") {
    vehiculos.mostrar(panel, parametros, forzar);
    $("buscar").value = parametros.id || "";
  } else {
    resumen.redibujar();
  }
  document.title = `${vista === "vehiculos" ? "Vehículos" : "Resumen"} · ${panel.seleccion[0]} · Aforo vial`;
}

// --------------------------------- Marco: camaras ---------------------------------
function pintarMarco() {
  const info = panel.camaras_info || [];
  $("camaras").innerHTML = info.map((c) => {
    return `<button class="camara" type="button" role="radio" aria-checked="${c.camara === camara}" data-camara="${esc(c.camara)}">
      <span><span class="camara-nombre">${esc(c.camara)}</span>
      <span class="camara-nota">${entero(c.cruces)} ${c.cruces === 1 ? "cruce" : "cruces"}</span></span>
    </button>`;
  }).join("");
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
function estadoSinDatos(titulo, mensaje) {
  $("h-estado").textContent = titulo;
  $("estado-mensaje").textContent = mensaje;
  mostrarVista("estado");
  $("camaras").innerHTML = "";
  $("ambito").textContent = "";
  document.title = "Aforo vial";
}

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
    if (panel && panel.estado === "ok") {
      aviso(`No se pudo actualizar (${error.message}). Se muestran los datos de las ${hora(panel.generado)}.`);
    } else {
      estadoSinDatos("Sin conexión con el panel", "No se pudo hablar con el servidor. Comprueba que `python -m aforo dashboard` sigue abierto.");
    }
    return;
  }
  aviso(null);
  if (nuevo.estado !== "ok") {
    panel = nuevo;
    estadoSinDatos("Aún no hay datos", nuevo.mensaje);
    return;
  }
  const cambioDeCamara = !panel || panel.estado !== "ok" || panel.seleccion[0] !== nuevo.seleccion[0];
  const firma = JSON.stringify([nuevo.seleccion, nuevo.total, nuevo.ultimo_cruce, nuevo.alertas.length, nuevo.lecturas.length, nuevo.limite_kmh, nuevo.camaras_info]);
  panel = nuevo;
  $("actualizado").textContent = `Actualizado ${hora(panel.generado)}`;
  if (silencioso && firma === firmaDatos) return;         // nada nuevo: solo cambia el sello de hora
  firmaDatos = firma;
  pintarMarco();
  if (vistaActual === "estado" || !vistaActual) mostrarVista(ruta().vista);
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

// ------------------------------------- Inicio -------------------------------------
fijarAuto(guardado.leer("aforo.auto") === "1", true);
// Las etiquetas de los graficos se miden con la fuente ya cargada.
(document.fonts ? document.fonts.ready : Promise.resolve()).then(() => cargar());
