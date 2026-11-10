// Control segmentado con pastilla deslizante (transitions.dev, receta 16).
// JS mide la pestana activa y escribe su posicion y ancho en la pastilla; CSS hace el recorrido.

import { esc } from "../formato.js";

/**
 * @param {HTMLElement} raiz   contenedor donde se dibuja
 * @param {{valor: string, texto: string, cuenta?: string}[]} opciones
 * @param {string} valor       opcion seleccionada
 * @param {(valor: string) => void} alCambiar
 * @param {string} etiqueta    nombre accesible del grupo
 */
export function segmentos(raiz, opciones, valor, alCambiar, etiqueta) {
  const firma = JSON.stringify(opciones);
  if (raiz.dataset.firma !== firma) {
    raiz.dataset.firma = firma;
    raiz.innerHTML = `<div class="t-tabs" role="tablist" aria-label="${esc(etiqueta)}">
      <span class="t-tabs-pill" aria-hidden="true"></span>
      ${opciones.map((o) => `<button class="t-tab" type="button" role="tab" data-valor="${esc(o.valor)}" aria-selected="false">${esc(o.texto)}${
        o.cuenta !== undefined ? `<span class="cuenta">${esc(o.cuenta)}</span>` : ""}</button>`).join("")}
    </div>`;
    raiz._animar = false;
    const barra = raiz.firstElementChild;
    barra.addEventListener("click", (evento) => {
      const tab = evento.target.closest(".t-tab");
      if (tab && tab.getAttribute("aria-selected") !== "true") raiz._alCambiar(tab.dataset.valor);
    });
    barra.addEventListener("keydown", (evento) => {
      if (evento.key !== "ArrowRight" && evento.key !== "ArrowLeft") return;
      const tabs = [...barra.querySelectorAll(".t-tab")];
      const i = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
      const destino = tabs[(i + (evento.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
      destino.focus();
      raiz._alCambiar(destino.dataset.valor);
    });
    new ResizeObserver(() => mover(raiz, false)).observe(barra);
  }
  raiz._alCambiar = alCambiar;
  const tabs = [...raiz.querySelectorAll(".t-tab")];
  const activa = tabs.find((t) => t.dataset.valor === valor) || tabs[0];
  tabs.forEach((t) => {
    t.setAttribute("aria-selected", t === activa ? "true" : "false");
    t.tabIndex = t === activa ? 0 : -1;
  });
  mover(raiz, raiz._animar);
  raiz._animar = true;
}

function mover(raiz, animar) {
  const pill = raiz.querySelector(".t-tabs-pill");
  const tab = raiz.querySelector('.t-tab[aria-selected="true"]');
  if (!pill || !tab || !tab.offsetWidth) return;
  if (!animar) {
    // Primera pintura y cambios de tamano: sin transicion, para que la pastilla no "llegue" desde 0.
    const prev = pill.style.transition;
    pill.style.transition = "none";
    pill.style.transform = `translateX(${tab.offsetLeft}px)`;
    pill.style.width = `${tab.offsetWidth}px`;
    void pill.offsetWidth;
    pill.style.transition = prev;
  } else {
    pill.style.transform = `translateX(${tab.offsetLeft}px)`;
    pill.style.width = `${tab.offsetWidth}px`;
  }
}
