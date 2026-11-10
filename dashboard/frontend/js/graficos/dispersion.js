/* Dispersion: cada medicion de velocidad contra la hora del cruce. Las mediciones normales son
   grises; las que igualan o superan el umbral de pico (percentil elegido) son ambar. Hay dos
   series, asi que lleva leyenda; el punto mas rapido tiene etiqueta directa. */

import { esc, hora, numero } from "../util/formato.js";
import { montar, rejillaY } from "./base.js";
import { etiquetaTiempo, lineal, ticksNumericos, ticksTiempo } from "./escalas.js";
import { fecha } from "../util/formato.js";

const ALTO = 300;
const M = { izq: 40, der: 14, arr: 40, abj: 30 };

export function graficoDispersion(contenedor, puntos, umbral, percentil) {
  const tiempos = puntos.map((p) => fecha(p.t).getTime());
  montar(contenedor, (ancho) => {
    const t0 = Math.min(...tiempos), t1 = Math.max(...tiempos);
    const margen = Math.max((t1 - t0) * 0.04, 2000);
    const vs = puntos.map((p) => p.v);
    const marcasY = ticksNumericos(Math.max(0, Math.min(...vs, umbral ?? Infinity) - 8), Math.max(...vs) * 1.12, 5);
    const y = lineal(marcasY[0], marcasY.at(-1), ALTO - M.abj, M.arr);
    const x = lineal(t0 - margen, t1 + margen, M.izq + 6, ancho - M.der);
    const { marcas, paso } = ticksTiempo(t0 - margen, t1 + margen, ancho < 520 ? 4 : 7);

    const ejeX = marcas.map((t) =>
      `<text x="${x(t).toFixed(1)}" y="${ALTO - 8}" text-anchor="middle">${etiquetaTiempo(t, paso)}</text>`).join("");

    const dibujaPunto = (p, i) => {
      const esPico = umbral !== null && p.v >= umbral;
      const tip = `<b>${esc(p.tipo)}</b> (ID ${esc(p.id)})<br>${numero(p.v)} km/h<br><span class="suave">${hora(p.t)}</span>`;
      return `<circle class="${esPico ? "g-pico" : "g-punto"}" cx="${x(tiempos[i]).toFixed(1)}" cy="${y(p.v).toFixed(1)}"
        r="${esPico ? 6 : 4.5}" data-tip="${esc(tip)}"/>`;
    };
    const normales = puntos.map((p, i) => (umbral !== null && p.v >= umbral ? "" : dibujaPunto(p, i))).join("");
    const picos = puntos.map((p, i) => (umbral !== null && p.v >= umbral ? dibujaPunto(p, i) : "")).join("");

    const iMax = vs.indexOf(Math.max(...vs));
    const angosto = ancho < 640;     // en pantallas estrechas la leyenda se acorta para que no se pise
    const px = x(tiempos[iMax]), py = y(vs[iMax]);
    const anclaDer = px > ancho - 150;
    const anota = `<line class="g-guia" x1="${px}" x2="${px}" y1="${py - 9}" y2="${py - 22}"/>
      <text class="g-anota" x="${px}" y="${py - 28}" text-anchor="${anclaDer ? "end" : "middle"}">Máx. ${numero(vs[iMax])} km/h · ${hora(puntos[iMax].t)}</text>`;

    const yU = umbral === null ? null : y(umbral).toFixed(1);
    const ref = yU === null ? "" :
      `<line class="g-ref" x1="${M.izq}" x2="${ancho - M.der}" y1="${yU}" y2="${yU}"/>
`;

    return `<svg viewBox="0 0 ${ancho} ${ALTO}" role="img" aria-label="Velocidad de cada vehiculo medido a lo largo del tiempo">
      <circle class="g-punto" cx="${M.izq + 5}" cy="10" r="4.5"/><text x="${M.izq + 16}" y="14">Medición</text>
      <circle class="g-pico" cx="${M.izq + 92}" cy="10" r="5"/><text x="${M.izq + 104}" y="14">${angosto ? `Pico (P${percentil})` : `Pico (percentil ${percentil} o mayor)`}</text>
      ${umbral === null || angosto ? "" : `<line class="g-ref" x1="${ancho - M.der - 150}" x2="${ancho - M.der - 128}" y1="10" y2="10"/>
      <text x="${ancho - M.der}" y="14" text-anchor="end">Umbral ${numero(umbral)} km/h</text>`}
      ${rejillaY(marcasY, y, M.izq, ancho - M.der)}
      <line class="g-base" x1="${M.izq}" x2="${ancho - M.der}" y1="${ALTO - M.abj}" y2="${ALTO - M.abj}"/>
      ${ref}${ejeX}${normales}${picos}${anota}
    </svg>`;
  });
}
