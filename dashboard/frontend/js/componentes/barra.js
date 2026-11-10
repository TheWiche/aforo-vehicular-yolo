/* Barra superior: selector de camaras (la seleccion es una linea de 1 px bajo la etiqueta),
   interruptor de auto-actualizacion y la hora de la ultima consulta. */

import { esc } from "../util/formato.js";

export function barraCamaras(contenedor, camaras, seleccion, alAlternar) {
  contenedor.innerHTML = camaras.map((c) => {
    const activa = seleccion === null || seleccion.includes(c);
    return `<button type="button" class="camara" aria-pressed="${activa}" data-c="${esc(c)}">${esc(c)}</button>`;
  }).join("");
  contenedor.querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => alAlternar(b.dataset.c)));
}

export function marcarActualizado(texto) {
  document.getElementById("actualizado").textContent = texto;
}
