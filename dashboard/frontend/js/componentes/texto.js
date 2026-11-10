// Cambio suave de texto (transitions.dev, receta 34): la cifra vieja se desenfoca mientras la
// nueva aparece en el mismo sitio, y el ancho se ajusta para que lo de al lado no salte.

const ms = (nombre) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(nombre)) || 0;
const sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)");

function softSwap(el, next) {
  const prev = el.dataset.text ?? el.textContent;
  if (prev === next) return;
  el.dataset.text = next;
  clearTimeout(el._softTimer);

  const out = document.createElement("span");
  out.className = "t-text-soft-old";
  out.setAttribute("aria-hidden", "true");
  out.textContent = prev;

  const inn = document.createElement("span");
  inn.className = "t-text-soft-new";
  inn.textContent = next;

  const w0 = el.getBoundingClientRect().width;
  el.classList.remove("is-swapping");
  el.replaceChildren(out, inn);
  const w1 = inn.getBoundingClientRect().width;

  el.style.width = w0 + "px";
  void el.offsetWidth; // fuerza el reflujo para que corran todas las transiciones
  el.classList.add("is-swapping");
  el.style.width = w1 + "px";

  el._softTimer = setTimeout(() => {
    el.classList.remove("is-swapping");
    el.style.removeProperty("width");
    el.textContent = next;
  }, Math.max(ms("--text-soft-dur"), ms("--text-soft-resize-dur")) + 40);
}

/**
 * Escribe `texto` en `el`. La primera vez (o si la vista esta oculta) lo pone directo;
 * despues, solo lo que cambia hace el cruce suave.
 */
export function poner(el, texto) {
  if (!el) return;
  const siguiente = String(texto);
  const primeraVez = el.dataset.text === undefined;
  if (primeraVez || sinMovimiento.matches || el.offsetParent === null) {
    clearTimeout(el._softTimer);
    el.classList.remove("is-swapping");
    el.style.removeProperty("width");
    el.classList.add("t-text-soft");
    el.dataset.text = siguiente;
    el.textContent = siguiente;
    return;
  }
  softSwap(el, siguiente);
}
