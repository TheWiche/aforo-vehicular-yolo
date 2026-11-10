/* Serie en el tiempo con segmentos rectos (una curva suavizada inventaria valores entre
   lecturas). Una sola serie por grafico; las lecturas con trafico detenido llevan un punto ambar. */

import { esc, fecha, hora, numero } from "../util/formato.js";
import { montar, rejillaY } from "./base.js";
import { etiquetaTiempo, lineal, ticksNumericos, ticksTiempo } from "./escalas.js";

const M = { izq: 40, der: 14, arr: 22, abj: 28 };

/**
 * @param {object} op  { titulo, alto, serie:[{t, v, estado}], unidad, decimales }
 */
export function graficoLinea(contenedor, op) {
  const tiempos = op.serie.map((p) => fecha(p.t).getTime());
  montar(contenedor, (ancho) => {
    const alto = op.alto ?? 170;
    const t0 = Math.min(...tiempos), t1 = Math.max(...tiempos);
    const marcasY = ticksNumericos(0, Math.max(...op.serie.map((p) => p.v), 1) * 1.1, 4);
    const y = lineal(marcasY[0], marcasY.at(-1), alto - M.abj, M.arr);
    const x = lineal(t0, t1 === t0 ? t0 + 1 : t1, M.izq + 4, ancho - M.der);
    const { marcas, paso } = ticksTiempo(t0, t1 === t0 ? t0 + 1000 : t1, ancho < 520 ? 4 : 6);

    const camino = op.serie.map((p, i) => `${i ? "L" : "M"}${x(tiempos[i]).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
    const puntos = op.serie.map((p, i) => {
      const detenido = p.estado === "DETENIDO";
      const tip = `${numero(p.v, op.decimales ?? 1)} ${esc(op.unidad)}<br><span class="suave">${hora(p.t)} · ${esc(p.estado)}</span>`;
      return `<circle class="${detenido ? "g-pico" : ""}" ${detenido ? "" : 'fill="transparent"'} cx="${x(tiempos[i]).toFixed(1)}" cy="${y(p.v).toFixed(1)}"
        r="${detenido ? 5 : 8}" data-tip="${esc(tip)}"/>`;
    }).join("");
    const ejeX = marcas.map((t) =>
      `<text x="${x(t).toFixed(1)}" y="${alto - 8}" text-anchor="middle">${etiquetaTiempo(t, paso)}</text>`).join("");

    return `<svg viewBox="0 0 ${ancho} ${alto}" role="img" aria-label="${esc(op.titulo)}">
      <text x="${M.izq}" y="12">${esc(op.titulo)}</text>
      ${rejillaY(marcasY, y, M.izq, ancho - M.der)}
      <line class="g-base" x1="${M.izq}" x2="${ancho - M.der}" y1="${alto - M.abj}" y2="${alto - M.abj}"/>
      <path class="g-linea" d="${camino}"/>${puntos}${ejeX}
    </svg>`;
  });
}
