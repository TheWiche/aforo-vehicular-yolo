// Dispersion: cada vehiculo medido es un punto (hora del cruce, velocidad). La linea punteada es
// el limite de la via; lo que queda por encima se pinta con el rojo de la senal.
// Al pasar el puntero se resalta el vehiculo mas cercano; un clic lo selecciona y muestra su cuadro.

import { dec1, esc, hora, nombreTipo } from "../formato.js";
import { ejeX, ejeY, lienzo, lineal, marcas, marcasDeTiempo, mostrarTooltip, nodo, ocultarTooltip, vacio } from "./base.js";

const RADIO = 4;
const ALCANCE = 22;      // el blanco del puntero es mayor que el punto

/**
 * @param {HTMLElement} el
 * @param {object} d
 * @param {{t:number, v:number, tipo:string, id:number, momento:string}[]} d.puntos
 * @param {number} d.limite
 * @param {[number, number]} d.dominio      inicio y fin del video (ms)
 * @param {string} d.tipo                   'todos' o el tipo que se resalta
 * @param {number|null} d.seleccion         track seleccionado
 * @param {(punto) => void} d.alElegir
 */
export function dispersion(el, d) {
  if (!d.puntos.length) return vacio(el, "Ningún vehículo completó el tramo de medición A–B, así que no hay velocidades que mostrar.");
  const c = lienzo(el, { izq: 40, der: 8, arriba: 22, abajo: 26 },
    `Velocidad de ${d.puntos.length} vehículos a lo largo del video; ${d.puntos.filter((p) => p.v > d.limite).length} superan el límite de ${d.limite} km/h`);
  if (!c) return;

  const valoresY = marcas(Math.max(d.limite, ...d.puntos.map((p) => p.v)), 5);
  const y = lineal(0, valoresY[valoresY.length - 1], c.y1, c.y0);
  const x = lineal(d.dominio[0], d.dominio[1], c.x0 + 6, c.x1 - 6);
  ejeY(c, y, valoresY, (v) => dec1(v).replace(/,0$/, ""), "km/h");
  const tiempo = marcasDeTiempo(d.dominio[0], d.dominio[1], c.x1 - c.x0);
  ejeX(c, x, tiempo.marcas, (t) => hora(new Date(t), tiempo.paso < 60000));

  // Linea de referencia: el limite (su nombre va en la leyenda, donde ningun punto lo tapa).
  const yLimite = Math.round(y(d.limite)) + 0.5;
  nodo("line", { x1: c.x0, x2: c.x1, y1: yLimite, y2: yLimite, class: "g-ref" }, c.svg);

  // Los apagados (otro tipo) primero; despues los normales y encima los excesos.
  const filtrando = d.tipo !== "todos";
  const orden = [...d.puntos].sort((a, b) => peso(a) - peso(b));
  function peso(p) { return (filtrando && p.tipo !== d.tipo ? 0 : p.v > d.limite ? 2 : 1); }
  const marcasPunto = new Map();
  for (const p of orden) {
    const apagado = filtrando && p.tipo !== d.tipo;
    const circulo = nodo("circle", {
      cx: x(p.t).toFixed(1), cy: y(p.v).toFixed(1), r: RADIO,
      class: `g-punto ${apagado ? "apagado" : p.v > d.limite ? "exceso" : "normal"}`,
    }, c.svg);
    marcasPunto.set(p, circulo);
  }

  // Aro del vehiculo seleccionado.
  const elegido = d.puntos.find((p) => p.id === d.seleccion && !(filtrando && p.tipo !== d.tipo));
  if (elegido) nodo("circle", { cx: x(elegido.t).toFixed(1), cy: y(elegido.v).toFixed(1), r: RADIO + 4, class: "g-aro" }, c.svg);

  // Zona de puntero: busca el punto visible mas cercano.
  const zona = nodo("rect", { x: c.x0, y: c.y0 - 10, width: c.x1 - c.x0, height: c.y1 - c.y0 + 10, class: "g-zona" }, c.svg);
  const candidatos = d.puntos.filter((p) => !(filtrando && p.tipo !== d.tipo));
  let activo = null;
  function cercano(evento) {
    const caja = c.svg.getBoundingClientRect();
    const px = evento.clientX - caja.left, py = evento.clientY - caja.top;
    let mejor = null, distancia = ALCANCE * ALCANCE;
    for (const p of candidatos) {
      const dx = x(p.t) - px, dy = y(p.v) - py, dd = dx * dx + dy * dy;
      if (dd < distancia) { distancia = dd; mejor = p; }
    }
    return mejor;
  }
  function resaltar(p, evento) {
    if (activo && activo !== p) marcasPunto.get(activo).setAttribute("r", RADIO);
    activo = p;
    zona.classList.toggle("sobre-punto", Boolean(p));
    if (!p) return ocultarTooltip();
    const circulo = marcasPunto.get(p);
    circulo.setAttribute("r", RADIO + 2);
    const caja = circulo.getBoundingClientRect();
    mostrarTooltip(
      `<b>${dec1(p.v)} km/h</b> · ${esc(nombreTipo(p.tipo))} #${esc(p.id)}<span class="t2">${hora(p.momento)} · clic para ver el cuadro</span>`,
      caja.left + caja.width / 2, caja.top);
  }
  zona.addEventListener("pointermove", (e) => resaltar(cercano(e), e));
  zona.addEventListener("pointerleave", () => resaltar(null));
  zona.addEventListener("click", (e) => { const p = cercano(e); if (p) d.alElegir(p); });
}
