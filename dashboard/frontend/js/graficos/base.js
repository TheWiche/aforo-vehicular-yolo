// Base comun de los graficos SVG: lienzo con margenes, escalas, marcas redondas y tooltip.
// Reglas de la casa: 3-5 lineas de guia horizontales, sin linea de eje vertical, la marca superior
// siempre por encima del maximo, etiquetas del eje X planas y con un mismo paso.

const NS = "http://www.w3.org/2000/svg";

export function nodo(etiqueta, atributos = {}, padre = null, texto = null) {
  const n = document.createElementNS(NS, etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) if (valor !== null && valor !== undefined) n.setAttribute(clave, valor);
  if (texto !== null) n.textContent = texto;
  if (padre) padre.appendChild(n);
  return n;
}

/** Escala lineal: dominio [d0, d1] -> rango [r0, r1]. */
export const lineal = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

/** Marcas redondas (pasos de 1, 2, 2.5 o 5 x 10^n) cuya ultima marca queda por encima del maximo. */
export function marcas(maximo, cuantas = 4, soloEnteros = false) {
  const tope = Math.max(maximo, soloEnteros ? cuantas : 1e-9);
  const bruto = tope / cuantas;
  const magnitud = 10 ** Math.floor(Math.log10(bruto));
  let paso = [1, 2, 2.5, 5, 10].map((m) => m * magnitud).find((p) => p >= bruto) || 10 * magnitud;
  if (soloEnteros) paso = Math.max(1, Math.ceil(paso));
  let ultima = Math.ceil(tope / paso) * paso;
  if (ultima <= maximo) ultima += paso;
  const salida = [];
  for (let v = 0; v <= ultima + paso / 2; v += paso) salida.push(+v.toFixed(6));
  return salida;
}

/** Marcas de tiempo en instantes redondos, con un paso que deja entre 3 y 7 etiquetas segun el ancho. */
export function marcasDeTiempo(t0, t1, anchoPx) {
  const pasos = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400].map((s) => s * 1000);
  const maximas = Math.max(2, Math.min(7, Math.floor(anchoPx / 84)));
  const paso = pasos.find((p) => (t1 - t0) / p <= maximas) || pasos[pasos.length - 1];
  const salida = [];
  // Se alinea a la hora local (los pasos de minutos caen en :00, :05, ...).
  const desfase = new Date(t0).getTimezoneOffset() * 60000;
  for (let t = Math.ceil((t0 - desfase) / paso) * paso + desfase; t <= t1; t += paso) salida.push(t);
  return { paso, marcas: salida };
}

/**
 * Prepara el lienzo: limpia el contenedor y crea el <svg> a su tamano real.
 * Devuelve null si el contenedor aun no tiene tamano (vista oculta).
 */
export function lienzo(el, margen, descripcion) {
  const ancho = el.clientWidth, alto = el.clientHeight;
  if (ancho < 40 || alto < 40) return null;
  el.replaceChildren();
  const svg = nodo("svg", { width: ancho, height: alto, viewBox: `0 0 ${ancho} ${alto}`, role: "img", "aria-label": descripcion }, el);
  return { svg, ancho, alto, x0: margen.izq, x1: ancho - margen.der, y0: margen.arriba, y1: alto - margen.abajo };
}

/** Lineas de guia horizontales con su etiqueta en un carril propio a la izquierda. */
export function ejeY(c, escala, valores, formato, unidad = "") {
  valores.forEach((v, i) => {
    const y = Math.round(escala(v)) + 0.5;
    nodo("line", { x1: c.x0, x2: c.x1, y1: y, y2: y, class: i === 0 ? "g-base" : "g-guia" }, c.svg);
    const ultimo = i === valores.length - 1;
    nodo("text", { x: c.x0 - 8, y: y + 4, "text-anchor": "end" }, c.svg, formato(v));
    if (ultimo && unidad) nodo("text", { x: c.x0, y: y - 8, "text-anchor": "start" }, c.svg, unidad);
  });
}

/** Etiquetas del eje X (planas, bajo la linea base). */
export function ejeX(c, escala, valores, formato) {
  valores.forEach((v) => {
    const x = escala(v);
    const ancla = x < c.x0 + 18 ? "start" : x > c.x1 - 18 ? "end" : "middle";
    nodo("text", { x, y: c.y1 + 18, "text-anchor": ancla }, c.svg, formato(v));
  });
}

/** Mensaje cuando no hay nada que dibujar: el marco se conserva, con una frase. */
export function vacio(el, mensaje) {
  el.replaceChildren();
  const p = document.createElement("p");
  p.className = "grafico-vacio";
  p.textContent = mensaje;
  el.appendChild(p);
}

/** Vuelve a dibujar cuando cambia el tamano del contenedor (y la primera vez que se hace visible). */
export function alRedimensionar(el, dibujar) {
  let cuadro = 0, previo = "";
  new ResizeObserver(() => {
    const firma = `${el.clientWidth}x${el.clientHeight}`;
    if (firma === previo) return;
    previo = firma;
    cancelAnimationFrame(cuadro);
    cuadro = requestAnimationFrame(dibujar);
  }).observe(el);
}

// ---------------------------------------------------------------------------------------------
// Tooltip compartido: una sola caja para todos los graficos, pegada al puntero.
// ---------------------------------------------------------------------------------------------
const caja = () => document.getElementById("tooltip");

export function mostrarTooltip(html, clienteX, clienteY) {
  const t = caja();
  t.innerHTML = html;
  const { width, height } = t.getBoundingClientRect();
  const ancho = t.offsetWidth || width, alto = t.offsetHeight || height;
  let x = clienteX - ancho / 2;
  let y = clienteY - alto - 14;
  x = Math.max(8, Math.min(x, window.innerWidth - ancho - 8));
  if (y < 8) y = clienteY + 18;
  t.style.translate = `${Math.round(x)}px ${Math.round(y)}px`;
  t.dataset.show = "true";
}

export function ocultarTooltip() {
  caja().dataset.show = "false";
}
