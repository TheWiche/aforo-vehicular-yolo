/* Encabezado con el hallazgo y las dos franjas de KPI (cada una es UN contenedor con celdas
   separadas por lineas finas). La cifra del total es la mayor: responde la pregunta de la pantalla. */

import { esc, numero, plural, sinMilis } from "../util/formato.js";

function celda({ etiqueta, valor, detalle, punto = "", unidad = "", guia = false }) {
  const marca = punto ? `<span class="punto" style="background:${esc(punto)}"></span>` : "";
  const sufijo = unidad ? `<small>${esc(unidad)}</small>` : "";
  return `<div class="celda${guia ? " guia" : ""}">
    <div class="celda-etiqueta">${marca}${esc(etiqueta)}</div>
    <div class="celda-valor">${esc(valor)}${sufijo}</div>
    <div class="celda-detalle">${esc(detalle)}</div></div>`;
}

/** La linea bajo el titulo: el hallazgo del dia, con las cifras en tinta clara. */
export function hallazgo(d) {
  const { velocidad: v } = d;
  return `<b>${plural(d.total, "vehículo contado", "vehículos contados")}</b> · ` +
    `<b>${plural(v.excesos, "exceso", "excesos")}</b> de velocidad sobre ${d.limite_kmh} km/h · ` +
    `<b>${plural(d.detenidos, "episodio", "episodios")}</b> de tráfico detenido · ` +
    `último cruce ${esc(sinMilis(d.ultimo_cruce))} · ${esc(d.seleccion.join(", "))}`;
}

export function franjas(d) {
  const primera = [
    celda({ etiqueta: "Total", valor: d.total, detalle: "vehículos que cruzaron la línea", guia: true }),
    ...d.tipos.map((t) => celda({ etiqueta: t.nombre, valor: t.total, detalle: `${t.pct} % del total`, punto: t.color })),
  ];
  const v = d.velocidad;
  const segunda = [
    celda({ etiqueta: "Velocidad promedio", valor: v.promedio === null ? "-" : numero(v.promedio), unidad: "km/h", detalle: `${v.mediciones} mediciones` }),
    celda({ etiqueta: `Excesos sobre ${d.limite_kmh} km/h`, valor: v.excesos, detalle: v.pct_excesos === null ? "sin mediciones" : `${v.pct_excesos} % de las mediciones` }),
    celda({ etiqueta: "Tráfico detenido", valor: d.detenidos, detalle: "episodios con alerta" }),
    celda({ etiqueta: "Estado de la vía", valor: d.estado_via ? d.estado_via[0] + d.estado_via.slice(1).toLowerCase() : "-", detalle: "última lectura del análisis de movimiento" }),
  ];
  return `<div class="franja c5">${primera.join("")}</div><div class="franja c4">${segunda.join("")}</div>`;
}
