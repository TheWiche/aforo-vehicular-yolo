/* Cada funcion llena un panel de la pantalla con su encabezado (titulo + una frase que dice como
   leerlo), su grafico o tabla, y su estado vacio propio cuando no hay datos. */

import { graficoBarras } from "../graficos/barras.js";
import { graficoDispersion } from "../graficos/dispersion.js";
import { graficoLinea } from "../graficos/lineas.js";
import { esc, hora, numero } from "../util/formato.js";
import { tablaAlertas, tablaCruces, tablaRapidos } from "./tablas.js";

const PERCENTILES = [75, 90, 95];

const cabecera = (id, titulo, texto, extra = "") =>
  `<div class="panel-cabecera"><div><h2 id="${id}">${esc(titulo)}</h2><p class="panel-texto">${texto}</p></div>${extra}</div>`;

const vacio = (mensaje) => `<div class="estado">${esc(mensaje)}</div>`;

export function panelBarras(el, d) {
  if (!d.por_tipo.length) {
    el.innerHTML = cabecera("t-barras", "Velocidad promedio por tipo", "Promedio de las mediciones de cada tipo de vehículo.") +
      vacio("Ningún cruce tiene velocidad medida. Revisa que la línea de conteo quede dentro del tramo A–B.");
    return;
  }
  const sinDatos = d.clases.map((c) => c.nombre).filter((n) => !d.por_tipo.some((t) => t.tipo === n));
  el.innerHTML = cabecera("t-barras", "Velocidad promedio por tipo",
    `${d.velocidad.mediciones} mediciones. La línea punteada es el promedio general: ${numero(d.velocidad.promedio)} km/h.`) +
    `<div data-grafico></div>` +
    (sinDatos.length ? `<p class="panel-texto" style="margin-top:8px">Sin mediciones: ${esc(sinDatos.join(", "))}</p>` : "");
  graficoBarras(el.querySelector("[data-grafico]"), d.por_tipo, d.velocidad.promedio);
}

export function panelPicos(el, d, alCambiarPercentil) {
  const opciones = `<div class="opciones" role="group" aria-label="Percentil del umbral de pico">${
    PERCENTILES.map((p) => `<button type="button" class="opcion" data-p="${p}" aria-pressed="${p === d.percentil}">P${p}</button>`).join("")}</div>`;
  if (!d.puntos.length) {
    el.innerHTML = cabecera("t-picos", "Picos de velocidad en el tiempo", "Cada punto es un vehículo medido.") +
      vacio("Todavía no hay mediciones de velocidad.");
    return;
  }
  el.innerHTML = cabecera("t-picos", "Picos de velocidad en el tiempo",
    "Cada punto es un vehículo medido. Los amarillos superan el umbral de pico.", opciones) + `<div data-grafico></div>`;
  graficoDispersion(el.querySelector("[data-grafico]"), d.puntos, d.umbral_pico, d.percentil);
  el.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => alCambiarPercentil(Number(b.dataset.p))));
}

export function panelVia(el, d) {
  const titulo = "Estado de la vía en el tiempo";
  const texto = "Lecturas del análisis de movimiento (resta de fondo, umbral y morfología) combinado con YOLO. Cada celda es una lectura.";
  if (!d.lecturas.length) {
    el.innerHTML = cabecera("t-via", titulo, texto) + vacio("Aún no hay lecturas: se guardan cada pocos segundos de video.");
    return;
  }
  const tira = d.lecturas.map((l) =>
    `<span class="${l.estado.toLowerCase()}" data-tip="${esc(`${hora(l.t)} · ${l.estado[0] + l.estado.slice(1).toLowerCase()}<br>${numero(l.vehiculos)} vehículos en la ROI`)}"></span>`).join("");
  el.innerHTML = cabecera("t-via", titulo, texto) +
    `<div class="tira">${tira}</div>
     <div class="leyenda"><span><i style="background:var(--elevado)"></i>Libre</span><span><i style="background:var(--fluido)"></i>Fluido</span><span><i style="background:var(--alerta)"></i>Detenido</span></div>
     <div data-g1></div><div data-g2 style="margin-top:6px"></div>`;
  const serie = (clave) => d.lecturas.map((l) => ({ t: l.t, v: clave === "pct" ? l.movimiento * 100 : l.vehiculos, estado: l.estado }));
  graficoLinea(el.querySelector("[data-g1]"), { titulo: "Vehículos en la ROI (promedio)", serie: serie("veh"), unidad: "vehículos", alto: 215 });
  graficoLinea(el.querySelector("[data-g2]"), { titulo: "Movimiento en la ROI (% de píxeles)", serie: serie("pct"), unidad: "%", alto: 215 });
}

export function panelAlertas(el, d) {
  const texto = "Exceso de velocidad y tráfico detenido, de la más reciente a la más antigua.";
  el.innerHTML = cabecera("t-alertas", "Alertas recientes", texto) +
    (d.alertas.length ? tablaAlertas(d.alertas) : vacio("No se han registrado alertas con los umbrales actuales."));
}

export function panelRapidos(el, d) {
  el.innerHTML = cabecera("t-rapidos", "Mayores velocidades registradas", "Los vehículos más rápidos y la hora en que cruzaron.") +
    (d.mas_rapidos.length ? tablaRapidos(d.mas_rapidos.slice(0, 5)) : vacio("Todavía no hay mediciones de velocidad."));
}

export function panelCruces(el, d) {
  el.innerHTML = `<details><summary id="t-cruces">Ver la tabla <code>cruces</code> (últimos ${d.cruces.length})</summary>${tablaCruces(d.cruces)}</details>`;
}
