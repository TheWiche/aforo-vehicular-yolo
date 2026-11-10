// Aforo por minuto: una columna por minuto del video (cuantos vehiculos cruzaron la linea de conteo).
// Debajo, sobre el mismo eje de tiempo, la tira del estado de la via que produce el analisis de
// movimiento (resta de fondo + umbral + morfologia): libre, fluido o detenido.

import { entero, hora } from "../formato.js";
import { ejeX, ejeY, lienzo, lineal, marcas, marcasDeTiempo, mostrarTooltip, nodo, ocultarTooltip, vacio } from "./base.js";

const MINUTO = 60000;
const NOMBRE_ESTADO = { LIBRE: "Vía libre", FLUIDO: "Tráfico fluido", DETENIDO: "Tráfico detenido" };

/**
 * @param {HTMLElement} el
 * @param {object} d
 * @param {{t:number, n:number}[]} d.minutos     inicio de cada minuto (ms) y vehiculos contados
 * @param {{t:number, estado:string}[]} d.lecturas  estado de la via cada pocos segundos
 * @param {[number, number]} d.dominio
 */
export function columnas(el, d) {
  if (!d.minutos.length) return vacio(el, "Aún no hay cruces registrados.");
  const hayVia = d.lecturas.length > 0;
  const total = d.minutos.reduce((s, m) => s + m.n, 0);
  const c = lienzo(el, { izq: 30, der: 4, arriba: 22, abajo: hayVia ? 44 : 26 },
    `Vehículos contados en cada minuto: ${total} en ${d.minutos.length} minutos`);
  if (!c) return;

  const t0 = Math.floor(d.dominio[0] / MINUTO) * MINUTO;
  const t1 = Math.max(Math.ceil(d.dominio[1] / MINUTO) * MINUTO, t0 + MINUTO);
  const valoresY = marcas(Math.max(...d.minutos.map((m) => m.n)), 3, true);
  const y = lineal(0, valoresY[valoresY.length - 1], c.y1, c.y0);
  const x = lineal(t0, t1, c.x0, c.x1);
  ejeY(c, y, valoresY, entero, "vehículos");
  const tiempo = marcasDeTiempo(t0, t1, c.x1 - c.x0);
  ejeX(c, x, tiempo.marcas, (t) => hora(new Date(t), tiempo.paso < MINUTO));

  // Columnas: esquinas rectas sobre la linea base, 2 px de aire entre vecinas.
  for (const m of d.minutos) {
    const izq = x(m.t) + 1, ancho = Math.max(1, x(m.t + MINUTO) - x(m.t) - 2);
    const grupo = nodo("g", { class: "g-columna" }, c.svg);
    nodo("rect", { x: izq - 1, y: c.y0, width: ancho + 2, height: c.y1 - c.y0, class: "g-toque" }, grupo);
    const arriba = y(m.n);
    nodo("rect", { x: izq, y: arriba, width: ancho, height: Math.max(0, c.y1 - arriba), class: "g-barra normal" }, grupo);
    grupo.addEventListener("pointerenter", () => {
      const caja = grupo.getBoundingClientRect();
      mostrarTooltip(`<b>${entero(m.n)} ${m.n === 1 ? "vehículo" : "vehículos"}</b><span class="t2">${hora(new Date(m.t), false)} a ${hora(new Date(m.t + MINUTO), false)}</span>`,
        caja.left + caja.width / 2, caja.top + (arriba - c.y0));
    });
    grupo.addEventListener("pointerleave", ocultarTooltip);
  }

  // Tira del estado de la via: tramos consecutivos con el mismo estado se unen.
  if (hayVia) {
    const yTira = c.y1 + 30;
    let i = 0;
    while (i < d.lecturas.length) {
      let j = i;
      while (j + 1 < d.lecturas.length && d.lecturas[j + 1].estado === d.lecturas[i].estado) j++;
      const desde = Math.max(d.lecturas[i].t, t0);
      const hasta = Math.min(j + 1 < d.lecturas.length ? d.lecturas[j + 1].t : d.dominio[1], t1);
      if (hasta > desde) {
        const tramo = nodo("rect", { x: x(desde), y: yTira, width: Math.max(1, x(hasta) - x(desde)), height: 8, class: `via-${d.lecturas[i].estado}` }, c.svg);
        const estado = d.lecturas[i].estado;
        tramo.addEventListener("pointerenter", () => {
          const caja = tramo.getBoundingClientRect();
          mostrarTooltip(`<b>${NOMBRE_ESTADO[estado] || estado}</b><span class="t2">${hora(new Date(desde))} a ${hora(new Date(hasta))}</span>`, caja.left + caja.width / 2, caja.top);
        });
        tramo.addEventListener("pointerleave", ocultarTooltip);
      }
      i = j + 1;
    }
  }
}
