// Editor de lineas sobre un cuadro de video. Cada linea tiene dos extremos que se arrastran; tambien
// se puede arrastrar la linea entera, moverla con las flechas del teclado o dibujarla de nuevo con
// dos clics. Las coordenadas son SIEMPRE pixeles del video original (no de la pantalla): el SVG usa
// como viewBox el tamano real del video, asi lo que se guarda es lo que el analisis usa.

import { nodo } from "../graficos/base.js";

const LINEAS = {
  conteo: { nombre: "Conteo", clase: "conteo" },
  a: { nombre: "A", clase: "punteada" },
  b: { nombre: "B", clase: "punteada" },
  regla: { nombre: "Referencia", clase: "regla" },
};
const RADIO_ASA_PX = 8;          // radio de los extremos en pixeles de pantalla
const PASO_TECLA = 1, PASO_TECLA_GRANDE = 10;

/**
 * @param {HTMLElement} contenedor  el .lienzo
 * @param {{alCambiar?: (id: string) => void, alElegir?: (id: string) => void}} eventos
 */
export function crearEditor(contenedor, eventos = {}) {
  let ancho = 1920, alto = 1080;
  let lineas = { conteo: null, a: null, b: null, regla: null };
  let elegida = "conteo";
  let dibujo = null;                 // { id, paso } mientras se dibuja una linea con dos clics
  let arrastre = null;
  let textoCota = "";

  contenedor.innerHTML = "";
  contenedor.style.aspectRatio = `${ancho} / ${alto}`;
  const img = document.createElement("img");
  img.alt = "Cuadro del video para colocar las líneas";
  const svg = nodo("svg", { viewBox: `0 0 ${ancho} ${alto}`, preserveAspectRatio: "none", "aria-hidden": "true" });
  const fondo = nodo("rect", { class: "ed-fondo", x: 0, y: 0, width: ancho, height: alto, fill: "transparent" }, svg);
  const cota = nodo("path", { class: "ed-linea punteada cota", style: "stroke-width:1.5;opacity:.85" }, svg);
  const grupos = {};
  for (const id of Object.keys(LINEAS)) {
    const g = nodo("g", { class: "ed-grupo", "data-linea": id }, svg);
    grupos[id] = {
      g,
      casing: nodo("path", { class: `ed-casing ${LINEAS[id].clase}` }, g),
      trazo: nodo("path", { class: `ed-linea ${LINEAS[id].clase}` }, g),
      golpe: nodo("path", { class: "ed-golpe", "data-linea": id, "data-punto": "todo" }, g),
      asas: [0, 1].map((i) => nodo("circle", { class: "ed-asa", "data-linea": id, "data-punto": String(i), r: 10 }, g)),
    };
  }
  const rotulos = {};
  for (const id of Object.keys(LINEAS)) {
    const r = document.createElement("span");
    r.className = `ed-rotulo ${id === "regla" ? "regla" : ""}`;
    r.textContent = LINEAS[id].nombre;
    rotulos[id] = r;
  }
  const rotuloCota = document.createElement("span");
  rotuloCota.className = "ed-rotulo cota";
  contenedor.append(img, svg, ...Object.values(rotulos), rotuloCota);

  // ------------------------------------------------------------------ conversion y limites
  const escala = () => ancho / (svg.getBoundingClientRect().width || ancho);        // unidades de video por px de pantalla
  function aVideo(evento) {
    const r = svg.getBoundingClientRect();
    return [((evento.clientX - r.left) / r.width) * ancho, ((evento.clientY - r.top) / r.height) * alto];
  }
  const acotar = ([x, y]) => [Math.round(Math.min(ancho, Math.max(0, x))), Math.round(Math.min(alto, Math.max(0, y)))];

  // ------------------------------------------------------------------ pintado
  function pintar() {
    const k = escala();
    for (const [id, partes] of Object.entries(grupos)) {
      const l = lineas[id];
      partes.g.style.display = l ? "" : "none";
      rotulos[id].style.display = l ? "" : "none";
      if (!l) continue;
      const d = `M${l[0][0]} ${l[0][1]}L${l[1][0]} ${l[1][1]}`;
      partes.casing.setAttribute("d", d);
      partes.trazo.setAttribute("d", d);
      partes.golpe.setAttribute("d", d);
      partes.asas.forEach((asa, i) => {
        asa.setAttribute("cx", l[i][0]);
        asa.setAttribute("cy", l[i][1]);
        asa.setAttribute("r", (RADIO_ASA_PX * k).toFixed(1));
      });
      partes.g.classList.toggle("elegida", id === elegida);
      // El rotulo va sobre el extremo mas alto de la linea.
      const arriba = l[0][1] <= l[1][1] ? l[0] : l[1];
      rotulos[id].style.left = `${(100 * arriba[0]) / ancho}%`;
      rotulos[id].style.top = `${(100 * arriba[1]) / alto}%`;
    }
    // Cota entre A y B: une los puntos medios y muestra la distancia real.
    const { a, b } = lineas;
    if (a && b && textoCota) {
      const ma = [(a[0][0] + a[1][0]) / 2, (a[0][1] + a[1][1]) / 2];
      const mb = [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2];
      cota.setAttribute("d", `M${ma[0]} ${ma[1]}L${mb[0]} ${mb[1]}`);
      cota.style.display = "";
      rotuloCota.textContent = textoCota;
      rotuloCota.style.display = "";
      rotuloCota.style.left = `${(50 * (ma[0] + mb[0])) / ancho}%`;
      rotuloCota.style.top = `${(50 * (ma[1] + mb[1])) / alto}%`;
    } else {
      cota.style.display = "none";
      rotuloCota.style.display = "none";
    }
  }
  new ResizeObserver(pintar).observe(contenedor);

  function elegir(id, avisar = true) {
    if (!lineas[id] || id === elegida) return;
    elegida = id;
    pintar();
    if (avisar && eventos.alElegir) eventos.alElegir(id);
  }

  // ------------------------------------------------------------------ arrastre
  svg.addEventListener("pointerdown", (e) => {
    if (dibujo) return;
    const objetivo = e.target.closest("[data-linea]");
    if (!objetivo || e.button > 0) return;
    const id = objetivo.dataset.linea;
    const punto = objetivo.dataset.punto;
    objetivo.setPointerCapture(e.pointerId);
    arrastre = { id, punto, inicio: aVideo(e), copia: lineas[id].map((p) => [...p]), objetivo };
    elegir(id);
    contenedor.focus({ preventScroll: true });
    e.preventDefault();
  });
  svg.addEventListener("pointermove", (e) => {
    if (dibujo && dibujo.paso === 1) {                      // vista previa mientras se dibuja
      lineas[dibujo.id][1] = acotar(aVideo(e));
      pintar();
      return;
    }
    if (!arrastre) return;
    const [x, y] = aVideo(e);
    const { id, punto, copia, inicio } = arrastre;
    if (punto === "todo") {
      // Se mueve la linea entera; el desplazamiento se limita para que ningun extremo salga del video.
      let dx = x - inicio[0], dy = y - inicio[1];
      dx = Math.max(-Math.min(copia[0][0], copia[1][0]), Math.min(ancho - Math.max(copia[0][0], copia[1][0]), dx));
      dy = Math.max(-Math.min(copia[0][1], copia[1][1]), Math.min(alto - Math.max(copia[0][1], copia[1][1]), dy));
      lineas[id] = copia.map(([px, py]) => [Math.round(px + dx), Math.round(py + dy)]);
    } else {
      lineas[id][Number(punto)] = acotar([x, y]);
    }
    pintar();
    if (eventos.alCambiar) eventos.alCambiar(id);
  });
  const soltar = (e) => {
    if (!arrastre) return;
    try { arrastre.objetivo.releasePointerCapture(e.pointerId); } catch { /* ya liberado */ }
    arrastre = null;
  };
  svg.addEventListener("pointerup", soltar);
  svg.addEventListener("pointercancel", soltar);

  // ------------------------------------------------------------------ dibujar con dos clics
  svg.addEventListener("click", (e) => {
    if (!dibujo) return;
    const punto = acotar(aVideo(e));
    if (dibujo.paso === 0) {
      lineas[dibujo.id] = [punto, punto];
      dibujo.paso = 1;
      pintar();
    } else {
      lineas[dibujo.id][1] = punto;
      const id = dibujo.id;
      terminarDibujo();
      pintar();
      if (eventos.alCambiar) eventos.alCambiar(id);
    }
  });
  function terminarDibujo() {
    dibujo = null;
    contenedor.classList.remove("dibujando");
  }

  // ------------------------------------------------------------------ teclado
  contenedor.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && dibujo) {
      lineas[dibujo.id] = dibujo.respaldo;
      terminarDibujo();
      pintar();
      return;
    }
    const mov = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!mov || !lineas[elegida]) return;
    e.preventDefault();
    const paso = e.shiftKey ? PASO_TECLA_GRANDE : PASO_TECLA;
    const l = lineas[elegida];
    // Una linea no puede salirse del video: el movimiento se ajusta al borde mas cercano.
    const dx = Math.max(-Math.min(l[0][0], l[1][0]), Math.min(ancho - Math.max(l[0][0], l[1][0]), mov[0] * paso));
    const dy = Math.max(-Math.min(l[0][1], l[1][1]), Math.min(alto - Math.max(l[0][1], l[1][1]), mov[1] * paso));
    lineas[elegida] = l.map(([x, y]) => [x + dx, y + dy]);
    pintar();
    if (eventos.alCambiar) eventos.alCambiar(elegida);
  });

  // ------------------------------------------------------------------ API publica
  return {
    /** Muestra un cuadro; el tamano del video fija el sistema de coordenadas. */
    cargarImagen(url, anchoVideo, altoVideo) {
      ancho = anchoVideo; alto = altoVideo;
      svg.setAttribute("viewBox", `0 0 ${ancho} ${alto}`);
      fondo.setAttribute("width", ancho); fondo.setAttribute("height", alto);
      contenedor.style.aspectRatio = `${ancho} / ${alto}`;
      pintar();
      return new Promise((resolver) => {
        contenedor.classList.add("cargando");
        const previa = new Image();
        previa.onload = () => { img.src = url; contenedor.classList.remove("cargando"); resolver(true); };
        previa.onerror = () => { contenedor.classList.remove("cargando"); resolver(false); };
        previa.src = url;
      });
    },
    /** Reemplaza las lineas (copias) y repinta sin disparar `alCambiar`. */
    poner(nuevas) {
      for (const id of Object.keys(lineas)) {
        if (id in nuevas) lineas[id] = nuevas[id] ? nuevas[id].map((p) => [...p]) : null;
      }
      if (!lineas[elegida]) elegida = "conteo";
      pintar();
    },
    obtener: () => Object.fromEntries(Object.entries(lineas).map(([id, l]) => [id, l ? l.map((p) => [...p]) : null])),
    elegir: (id) => elegir(id, false),
    elegida: () => elegida,
    /** Empieza a dibujar la linea `id` con dos clics (Esc cancela). */
    dibujar(id) {
      if (!(id in lineas)) return;
      dibujo = { id, paso: 0, respaldo: lineas[id] ? lineas[id].map((p) => [...p]) : null };
      elegida = id;
      contenedor.classList.add("dibujando");
      contenedor.focus({ preventScroll: true });
    },
    dibujando: () => dibujo !== null,
    /** Texto de la cota entre A y B (por ejemplo "4,7 m"); vacio la oculta. */
    ponerCota(texto) { textoCota = texto; pintar(); },
    tamano: () => ({ ancho, alto }),
  };
}
