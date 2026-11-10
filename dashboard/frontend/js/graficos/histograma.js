// Distribucion de velocidades: histograma con clases iguales de 5 km/h. Las clases por encima del
// limite llevan el rojo de la senal; una linea marca la V85 (la velocidad que el 85 % no supera).

import { dec1, entero } from "../formato.js";
import { ejeX, ejeY, lienzo, lineal, marcas, mostrarTooltip, nodo, ocultarTooltip, vacio } from "./base.js";

const CLASE = 5;   // km/h

/**
 * @param {HTMLElement} el
 * @param {object} d
 * @param {number[]} d.velocidades
 * @param {number} d.limite
 * @param {number|null} d.v85
 */
export function histograma(el, d) {
  if (!d.velocidades.length) return vacio(el, "Sin velocidades medidas todavía.");
  const c = lienzo(el, { izq: 30, der: 4, arriba: 40, abajo: 26 },
    `Distribución de ${d.velocidades.length} velocidades en clases de ${CLASE} km/h; V85 de ${d.v85 !== null ? dec1(d.v85) : "?"} km/h`);
  if (!c) return;

  const maximo = Math.max(d.limite + CLASE, ...d.velocidades);
  const clases = Math.ceil((maximo + 0.001) / CLASE);
  const cuentas = new Array(clases).fill(0);
  for (const v of d.velocidades) cuentas[Math.min(clases - 1, Math.floor(v / CLASE))]++;

  const valoresY = marcas(Math.max(...cuentas), 3, true);
  const y = lineal(0, valoresY[valoresY.length - 1], c.y1, c.y0);
  const x = lineal(0, clases * CLASE, c.x0, c.x1);
  ejeY(c, y, valoresY, entero, "vehículos");
  const pasoX = clases * CLASE > 80 ? 20 : 10;
  const valoresX = [];
  for (let v = 0; v <= clases * CLASE; v += pasoX) valoresX.push(v);
  ejeX(c, x, valoresX, String);

  cuentas.forEach((n, i) => {
    const desde = i * CLASE, hasta = desde + CLASE;
    const izq = x(desde) + 1, ancho = Math.max(1, x(hasta) - x(desde) - 2);
    const grupo = nodo("g", { class: "g-columna" }, c.svg);
    nodo("rect", { x: izq - 1, y: c.y0, width: ancho + 2, height: c.y1 - c.y0, class: "g-toque" }, grupo);
    const arriba = y(n);
    // Una clase es "sobre el limite" si empieza en el limite o despues.
    nodo("rect", { x: izq, y: arriba, width: ancho, height: Math.max(0, c.y1 - arriba), class: `g-barra ${desde >= d.limite ? "exceso" : "normal"}` }, grupo);
    grupo.addEventListener("pointerenter", () => {
      const caja = grupo.getBoundingClientRect();
      const parte = Math.round((100 * n) / d.velocidades.length);
      mostrarTooltip(`<b>${entero(n)} ${n === 1 ? "vehículo" : "vehículos"}</b> · ${parte} %<span class="t2">de ${desde} a ${hasta} km/h</span>`,
        caja.left + caja.width / 2, caja.top + (arriba - c.y0));
    });
    grupo.addEventListener("pointerleave", ocultarTooltip);
  });

  // Referencias verticales: limite (punteada) y V85 (continua). Sus etiquetas van en la franja
  // superior, cada una hacia el lado contrario de la otra para que nunca se pisen.
  const xLimite = Math.round(x(d.limite)) + 0.5;
  nodo("line", { x1: xLimite, x2: xLimite, y1: c.y0 - 14, y2: c.y1, class: "g-ref" }, c.svg);
  const v85Derecha = d.v85 === null || d.v85 >= d.limite;
  nodo("text", { x: xLimite + (v85Derecha ? -6 : 6), y: c.y0 - 20, "text-anchor": v85Derecha ? "end" : "start", class: "g-ref-texto" }, c.svg,
    `Límite ${dec1(d.limite).replace(/,0$/, "")}`);
  if (d.v85 !== null) {
    const xV85 = Math.round(x(d.v85)) + 0.5;
    nodo("line", { x1: xV85, x2: xV85, y1: c.y0 - 14, y2: c.y1, class: "g-ref-solida" }, c.svg);
    nodo("text", { x: xV85 + (v85Derecha ? 6 : -6), y: c.y0 - 20, "text-anchor": v85Derecha ? "start" : "end", class: "g-ref-texto" }, c.svg,
      `V85 ${dec1(d.v85)}`);
  }
}
