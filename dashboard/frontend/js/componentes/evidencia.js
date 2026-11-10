// Evidencia: el cuadro del video en el instante en que el vehiculo cruzo la linea de conteo,
// con las lineas de medicion (A y B), la linea de conteo y la distancia real dibujadas encima.
// Es lo que hace creible cada cifra: se ve el vehiculo exacto que produjo la medicion.

import { urlFotograma } from "../api.js";
import { conSigno, dec1, dec2, esc, hora, nombreTipo, segundosEnTramo } from "../formato.js";

const sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)");

/** Lineas de calibracion como SVG (coordenadas en pixeles del video) y sus rotulos en HTML. */
function capaDeLineas(camara) {
  const { lineas, ancho, alto, distancia_m: distancia } = camara;
  if (!lineas || !ancho || !alto) return "";
  const trazo = ([p, q], clase) =>
    `<path class="trazo-base ${clase}" d="M${p[0]} ${p[1]}L${q[0]} ${q[1]}"/><path class="trazo ${clase}" d="M${p[0]} ${p[1]}L${q[0]} ${q[1]}"/>`;
  // El rotulo va en el extremo mas alto de cada linea; la cota une los extremos finales de A y B.
  const arriba = ([p, q]) => (p[1] <= q[1] ? p : q);
  const rotulo = ([x, y], texto, clase = "") =>
    `<span class="rotulo ${clase}" style="left:${(100 * x / ancho).toFixed(2)}%;top:${(100 * y / alto).toFixed(2)}%">${texto}</span>`;
  const a2 = lineas.a[1], b2 = lineas.b[1];
  const medio = [(a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2];
  return `<svg viewBox="0 0 ${ancho} ${alto}" preserveAspectRatio="none" aria-hidden="true">
      ${trazo(lineas.a, "medida")}${trazo(lineas.b, "medida")}${trazo([a2, b2], "cota")}${trazo(lineas.conteo, "conteo")}
    </svg>
    ${rotulo(arriba(lineas.a), "A")}${rotulo(arriba(lineas.b), "B")}${rotulo(arriba(lineas.conteo), "Conteo")}
    ${distancia ? rotulo(medio, `${dec1(distancia)} m`, "abajo") : ""}`;
}

/**
 * Crea la tarjeta de evidencia dentro de `raiz` y devuelve `mostrar(...)` para cambiar de vehiculo.
 */
export function crearEvidencia(raiz) {
  raiz.innerHTML = `
    <figure class="foto">
      <img alt="" hidden>
      <div class="foto-capa"></div>
      <p class="foto-vacia" hidden></p>
    </figure>
    <div class="evi-texto">
      <p class="evi-l1"><span class="evi-quien"></span><span class="evi-vel"></span></p>
      <p class="evi-l2"></p>
      <p class="evi-acciones"></p>
    </div>`;
  const foto = raiz.querySelector(".foto");
  const img = raiz.querySelector("img");
  const capa = raiz.querySelector(".foto-capa");
  const vacia = raiz.querySelector(".foto-vacia");
  let pedido = 0;
  let firmaCapa = "";

  /**
   * @param {object} o
   * @param {object|null} o.camara     contexto de la camara (lineas, distancia, si hay video)
   * @param {object|null} o.vehiculo   {track, tipo, t, v}
   * @param {number} o.limite          limite de velocidad en km/h
   * @param {number|null} o.fps        cuadros por segundo del video
   * @param {string} o.motivo          por que se muestra este vehiculo ("El más rápido", ...)
   * @param {string} [o.acciones]      HTML de acciones bajo el texto
   */
  function mostrar({ camara, vehiculo, limite, fps, motivo, acciones = "" }) {
    const hayFoto = Boolean(camara && camara.fotograma);
    if (camara && camara.ancho && camara.alto) foto.style.aspectRatio = `${camara.ancho} / ${camara.alto}`;

    // --- Imagen ---
    const turno = ++pedido;
    if (!hayFoto) {
      img.hidden = true;
      capa.innerHTML = "";
      firmaCapa = "";
      vacia.hidden = false;
      vacia.textContent = camara && camara.video
        ? `El video ${camara.video} no está en datos/videos, así que no hay cuadro que mostrar.`
        : "Esta cámara no tiene un video asociado.";
    } else {
      vacia.hidden = true;
      const firma = JSON.stringify([camara.lineas, camara.ancho, camara.alto, camara.distancia_m]);
      if (firma !== firmaCapa) { capa.innerHTML = capaDeLineas(camara); firmaCapa = firma; }
      const url = urlFotograma(camara.camara, vehiculo ? vehiculo.t : null);
      if (img.dataset.url !== url) {
        img.dataset.url = url;
        foto.classList.add("cargando");
        const previa = new Image();
        previa.onload = () => {
          if (turno !== pedido) return;            // llego tarde: ya se pidio otro vehiculo
          img.src = url;
          img.hidden = false;
          foto.classList.remove("cargando");
          if (!sinMovimiento.matches && img.animate) {
            img.animate([{ opacity: 0.5, filter: "blur(2px)" }, { opacity: 1, filter: "blur(0)" }],
              { duration: 250, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
          }
        };
        previa.onerror = () => {
          if (turno !== pedido) return;
          foto.classList.remove("cargando");
          img.hidden = true;
          vacia.hidden = false;
          vacia.textContent = "No se pudo leer el cuadro del video.";
        };
        previa.src = url;
      }
      img.alt = vehiculo
        ? `Cuadro del video a las ${hora(vehiculo.t)}: ${nombreTipo(vehiculo.tipo)} sobre la línea de conteo`
        : "Vista de la cámara con las líneas de medición";
    }

    // --- Texto ---
    const quien = raiz.querySelector(".evi-quien");
    const vel = raiz.querySelector(".evi-vel");
    const l2 = raiz.querySelector(".evi-l2");
    if (!vehiculo) {
      quien.textContent = "Vista de la cámara";
      vel.textContent = "";
      l2.textContent = camara && camara.distancia_m
        ? `Tramo de medición A–B: ${dec1(camara.distancia_m)} m. Aún no hay vehículos con velocidad medida.`
        : "Aún no hay vehículos con velocidad medida.";
    } else {
      quien.innerHTML = `${esc(nombreTipo(vehiculo.tipo))}<span class="id">#${esc(vehiculo.track)}</span>`;
      const partes = [`${motivo ? esc(motivo) + " · " : ""}${hora(vehiculo.t)}`];
      if (vehiculo.v === null || vehiculo.v === undefined) {
        vel.innerHTML = `<span class="unidad">sin medición</span>`;
        partes.push("no completó el tramo A–B");
      } else {
        vel.innerHTML = `${dec1(vehiculo.v)}<span class="unidad">km/h</span>`;
        const delta = vehiculo.v - limite;
        partes.push(delta > 0 ? `<span class="malo">${conSigno(delta)} km/h sobre el límite</span>` : "dentro del límite");
        const s = segundosEnTramo(camara && camara.distancia_m, vehiculo.v);
        if (s) partes.push(`${dec2(s)} s en los ${dec1(camara.distancia_m)} m${fps ? ` (${Math.round(s * fps)} cuadros)` : ""}`);
      }
      l2.innerHTML = partes.join(" · ");
    }
    raiz.querySelector(".evi-acciones").innerHTML = acciones;
    raiz.querySelector(".evi-acciones").hidden = !acciones;
  }

  return { mostrar };
}
