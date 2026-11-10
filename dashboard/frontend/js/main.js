/* Arranque y ciclo de vida de la pantalla: carga -> render -> (opcional) actualizacion automatica.
   Los datos viven en el servidor; aqui solo se guardan los filtros elegidos. */

import { obtenerPanel } from "./api.js";
import { barraCamaras, marcarActualizado } from "./componentes/barra.js";
import { errorBloque, esqueleto, pantallaVacia } from "./componentes/estados.js";
import { franjas, hallazgo } from "./componentes/franjas.js";
import { panelAlertas, panelBarras, panelCruces, panelPicos, panelRapidos, panelVia } from "./componentes/paneles.js";
import { alternarCamara, cargarEstado, guardarEstado } from "./estado.js";
import { activarTooltips } from "./graficos/tooltip.js";

const INTERVALO_MS = 5000;
const $ = (id) => document.getElementById(id);

const estado = cargarEstado();
let ultimoJson = "";
let temporizador = null;
let primeraCarga = true;

const BLOQUES = ["panel-barras", "panel-picos", "panel-via", "panel-alertas", "panel-rapidos", "panel-cruces"];
const mostrarBloques = (visible) => BLOQUES.forEach((id) => ($(id).hidden = !visible));

function pintar(d) {
  $("hallazgo").innerHTML = hallazgo(d);
  $("franjas").innerHTML = franjas(d);
  panelBarras($("panel-barras"), d);
  panelPicos($("panel-picos"), d, cambiarPercentil);
  panelVia($("panel-via"), d);
  panelAlertas($("panel-alertas"), d);
  panelRapidos($("panel-rapidos"), d);
  panelCruces($("panel-cruces"), d);
  barraCamaras($("camaras"), d.camaras, estado.camaras, (c) => {
    estado.camaras = alternarCamara(estado.camaras, c, d.camaras);
    guardarEstado(estado);
    cargar();
  });
}

async function cargar({ silencioso = false } = {}) {
  if (!silencioso && primeraCarga) {
    $("franjas").innerHTML = esqueleto();
  }
  try {
    const d = await obtenerPanel({ camaras: estado.camaras, percentil: estado.percentil });
    const ahora = new Date().toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    marcarActualizado(`Actualizado ${ahora}`);
    if (d.estado !== "ok") {
      mostrarBloques(false);
      $("hallazgo").textContent = "";
      $("franjas").hidden = false;
      $("franjas").innerHTML = pantallaVacia(d);
      barraCamaras($("camaras"), d.camaras, null, () => {});
      ultimoJson = "";
      return;
    }
    // Si nada cambio desde la ultima consulta no se redibuja (evita parpadeos al auto-actualizar).
    const firma = JSON.stringify({ ...d, generado: 0 });
    if (firma === ultimoJson) return;
    ultimoJson = firma;
    mostrarBloques(true);
    pintar(d);
    if (primeraCarga) $("franjas").classList.add("revela");
    primeraCarga = false;
  } catch (error) {
    $("franjas").hidden = false;
    $("franjas").innerHTML = errorBloque(error.message);
    $("franjas").querySelector("[data-reintentar]")?.addEventListener("click", () => cargar());
    mostrarBloques(false);
    $("franjas").hidden = false;
  }
}

function cambiarPercentil(p) {
  estado.percentil = p;
  guardarEstado(estado);
  cargar();
}

function programarActualizacion() {
  clearInterval(temporizador);
  if (estado.auto) temporizador = setInterval(() => cargar({ silencioso: true }), INTERVALO_MS);
}

const interruptor = $("auto");
interruptor.checked = estado.auto;
interruptor.addEventListener("change", () => {
  estado.auto = interruptor.checked;
  guardarEstado(estado);
  programarActualizacion();
});

activarTooltips(document.querySelector(".lienzo"));
programarActualizacion();
cargar();
