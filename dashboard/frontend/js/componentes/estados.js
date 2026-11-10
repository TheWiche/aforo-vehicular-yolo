/* Estados honestos: carga (el layout final con barras planas del tamano real), pantalla vacia
   y error dentro del propio bloque que fallo. */

import { esc } from "../util/formato.js";

export function esqueleto() {
  const celdas = (n) => Array.from({ length: n }, () => '<span class="esq esq-cel"></span>').join("");
  return `<div class="franja c5">${celdas(5)}</div><div class="franja c4">${celdas(4)}</div>
    <div class="fila f-4-8"><span class="esq esq-grafico"></span><span class="esq esq-grafico"></span></div>`;
}

const TITULOS = {
  sin_bd: "Todavía no hay base de datos",
  sin_tablas: "La base de datos no tiene la tabla de cruces",
  vacia: "Aún no hay cruces registrados",
};

/** Pantalla completa cuando no hay nada que mostrar: dice por que y que hacer. */
export function pantallaVacia(d) {
  return `<section class="pantalla-vacia"><h2>${esc(TITULOS[d.estado] ?? "Sin datos")}</h2>
    <p>${esc(d.mensaje)}</p>
    <p style="margin-top:10px">Ejecuta <code>python -m aforo procesar</code> sobre un video y esta pantalla se llenará sola.</p></section>`;
}

/** Error dentro de un bloque: que fallo y un boton para reintentar. */
export function errorBloque(mensaje) {
  return `<div class="estado" role="alert">${esc(mensaje)}<button type="button" data-reintentar>Reintentar</button></div>`;
}
