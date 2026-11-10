/* Tablas: reglas y alineacion, sin cebra ni bandas. Las cifras van a la derecha en digitos
   tabulares; un valor ausente es un guion gris, nunca un cero inventado. */

import { esc, hora, numero, sinMilis } from "../util/formato.js";

const tipoCelda = (tipo, color) =>
  `<span class="tipo"><span class="punto" style="background:${esc(color ?? "var(--tinta-suave)")}"></span>${esc(tipo)}</span>`;

const velocidad = (v) => (v === null || v === undefined ? '<span class="suave">-</span>' : `${numero(v)} km/h`);

export function tablaAlertas(alertas) {
  const filas = alertas.map((a) => {
    const exceso = a.tipo === "EXCESO_VELOCIDAD";
    return `<tr><td>${hora(a.t)}</td>
      <td><span class="pildora ${exceso ? "exceso" : "detenido"}">${exceso ? "Exceso de velocidad" : "Tráfico detenido"}</span></td>
      <td class="largo">${esc(a.detalle)}</td></tr>`;
  }).join("");
  return `<div class="tabla-marco tabla-alertas"><table class="tabla">
    <thead><tr><th>Hora</th><th>Tipo</th><th>Detalle</th></tr></thead><tbody>${filas}</tbody></table></div>`;
}

export function tablaRapidos(filas) {
  const cuerpo = filas.map((f) => `<tr><td>${hora(f.t)}</td><td class="num">${esc(f.id)}</td>
    <td>${tipoCelda(f.tipo, f.color)}</td><td class="num">${velocidad(f.v)}</td><td class="suave">${esc(f.camara)}</td></tr>`).join("");
  return `<div class="tabla-marco"><table class="tabla">
    <thead><tr><th>Hora</th><th class="num">ID de seguimiento</th><th>Tipo</th><th class="num">Velocidad</th><th>Cámara</th></tr></thead>
    <tbody>${cuerpo}</tbody></table></div>`;
}

export function tablaCruces(filas) {
  const cuerpo = filas.map((f) => `<tr><td class="num suave">${esc(f.id)}</td><td class="num">${esc(f.track)}</td>
    <td>${tipoCelda(f.tipo, f.color)}</td><td>${esc(sinMilis(f.t))}</td><td class="num">${velocidad(f.v)}</td>
    <td class="suave">${esc(f.camara)}</td></tr>`).join("");
  return `<div class="tabla-marco tabla-alertas"><table class="tabla">
    <thead><tr><th class="num">id</th><th class="num">track_id</th><th>tipo</th><th>momento</th><th class="num">velocidad</th><th>camara</th></tr></thead>
    <tbody>${cuerpo}</tbody></table></div>`;
}
