/* Tooltip global: texto desnudo en una caja simple. Cualquier elemento con `data-tip` (HTML ya
   escapado por quien lo genera) lo muestra al pasar el puntero o al recibir foco. */

const caja = () => document.getElementById("tooltip");

function mostrar(html, x, y) {
  const t = caja();
  t.innerHTML = html;
  t.hidden = false;
  const { width, height } = t.getBoundingClientRect();
  const izquierda = Math.min(x + 14, window.innerWidth - width - 8);
  const arriba = y - height - 12 < 8 ? y + 18 : y - height - 12;          // si no cabe arriba, va debajo
  t.style.left = `${Math.max(8, izquierda)}px`;
  t.style.top = `${arriba}px`;
  requestAnimationFrame(() => t.classList.add("visible"));
}

function ocultar() {
  const t = caja();
  t.classList.remove("visible");              // al cerrar no hay transicion: desaparece al instante
}

/** Delegacion de eventos sobre un contenedor (los graficos se redibujan, el contenedor no). */
export function activarTooltips(contenedor) {
  contenedor.addEventListener("pointermove", (e) => {
    const objetivo = e.target.closest("[data-tip]");
    if (objetivo) mostrar(objetivo.dataset.tip, e.clientX, e.clientY);
    else ocultar();
  });
  contenedor.addEventListener("pointerleave", ocultar);
  window.addEventListener("scroll", ocultar, { passive: true });
}
