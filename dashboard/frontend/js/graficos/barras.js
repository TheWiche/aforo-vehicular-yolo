/* Barras: velocidad promedio por tipo de vehiculo. Una sola serie => sin leyenda; el nombre del
   tipo va en el eje y cada barra lleva su valor encima. La linea punteada es el promedio general. */

import { esc, numero } from "../util/formato.js";
import { montar, rejillaY } from "./base.js";
import { lineal, ticksNumericos } from "./escalas.js";

const ALTO = 300;
const M = { izq: 40, der: 8, arr: 26, abj: 30 };

export function graficoBarras(contenedor, datos, promedioGeneral) {
  montar(contenedor, (ancho) => {
    const maxV = Math.max(...datos.map((d) => d.promedio), promedioGeneral);
    const marcas = ticksNumericos(0, maxV * 1.1, 5);
    const y = lineal(marcas[0], marcas.at(-1), ALTO - M.abj, M.arr);
    const paso = (ancho - M.izq - M.der) / datos.length;
    const bw = Math.min(56, paso * 0.5);

    const barras = datos.map((d, i) => {
      const cx = M.izq + paso * (i + 0.5);
      const top = y(d.promedio);
      const tip = `<b>${esc(d.tipo)}</b><br>Promedio ${numero(d.promedio)} km/h<br>` +
        `<span class="suave">${d.n} mediciones · ${numero(d.minimo)} a ${numero(d.maximo)} km/h</span>`;
      return `<g data-tip="${esc(tip)}">
        <path class="g-barra" fill="${esc(d.color)}" d="M${cx - bw / 2},${ALTO - M.abj} V${top + 2} q0,-2 2,-2 h${bw - 4} q2,0 2,2 V${ALTO - M.abj} Z"/>
        <text class="g-valor" x="${cx}" y="${top - 8}" text-anchor="middle">${numero(d.promedio)}</text>
        <text x="${cx}" y="${ALTO - 8}" text-anchor="middle">${esc(d.tipo)}</text>
      </g>`;
    }).join("");

    const yMedia = y(promedioGeneral).toFixed(1);
    return `<svg viewBox="0 0 ${ancho} ${ALTO}" role="img" aria-label="Velocidad promedio por tipo de vehiculo">
      ${rejillaY(marcas, y, M.izq, ancho - M.der)}
      <line class="g-base" x1="${M.izq}" x2="${ancho - M.der}" y1="${ALTO - M.abj}" y2="${ALTO - M.abj}"/>
      ${barras}
      <line class="g-ref" x1="${M.izq}" x2="${ancho - M.der}" y1="${yMedia}" y2="${yMedia}"/>
    </svg>`;
  });
}
