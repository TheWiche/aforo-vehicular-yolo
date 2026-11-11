// Vista "Videos": los videos disponibles con su estado (calibrado, cruces guardados) y la forma de
// agregar uno nuevo, por ruta (sin copiar) o subiendo el archivo.

import { agregarVideoRuta, pedirVideos, subirVideo, urlCuadroVideo } from "../api.js";
import { recordarVideo } from "../estado.js";
import { entero, esc } from "../formato.js";

const $ = (id) => document.getElementById(id);

const tamano = (bytes) => (bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1).replace(".", ",")} GB` : `${entero(Math.round(bytes / 1e6))} MB`);
const duracion = (s) => {
  if (!s) return "duración desconocida";
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m ? `${entero(m)} min${r ? ` ${r} s` : ""}` : `${r} s`;
};

export function crearVideos() {
  let videos = [];

  function pintar() {
    const lista = $("videos-lista");
    if (!videos.length) {
      lista.innerHTML = `<li class="vacio-lista" style="display:block">Todavía no hay videos. Usa «Agregar un video» para empezar.</li>`;
      return;
    }
    lista.innerHTML = videos.map((v) => {
      const miniatura = v.legible && v.duracion_s
        ? `<img class="miniatura" loading="lazy" alt="" src="${esc(urlCuadroVideo(v.nombre, v.duracion_s * 0.1, 320))}">`
        : `<span class="miniatura-vacia">Sin vista</span>`;
      const meta = [v.ancho ? `${v.ancho}×${v.alto}` : null, duracion(v.duracion_s), v.fps ? `${Math.round(v.fps)} cuadros/s` : null, tamano(v.bytes)]
        .filter(Boolean).join(" · ");
      const chips = [
        v.calibrado ? `<span class="chip ok">Calibrado</span>` : `<span class="chip aviso">Sin calibrar</span>`,
        v.cruces ? `<span class="chip">${entero(v.cruces)} cruces guardados</span>` : `<span class="chip">Sin procesar</span>`,
        v.externo ? `<span class="chip" title="${esc(v.ruta)}">En otra carpeta</span>` : "",
        !v.legible ? `<span class="chip mal">No se puede abrir</span>` : "",
      ].join("");
      const nombre = encodeURIComponent(v.nombre);
      return `<li>
        ${miniatura}
        <div>
          <p class="video-nombre" title="${esc(v.nombre)}">${esc(v.nombre)}</p>
          <p class="video-meta">${esc(meta)}</p>
          <div class="video-chips">${chips}</div>
        </div>
        <div class="video-acciones">
          <a class="boton contorno" href="#/calibrar?video=${nombre}" data-video="${esc(v.nombre)}">${v.calibrado ? "Recalibrar" : "Calibrar"}</a>
          <a class="boton contorno" href="#/procesar?video=${nombre}" data-video="${esc(v.nombre)}">Procesar</a>
          ${v.cruces ? `<a class="boton contorno" href="#/resumen" data-camara="${esc(v.camara)}">Ver resultados</a>` : ""}
        </div>
      </li>`;
    }).join("");
    const sin = videos.filter((v) => !v.calibrado).length;
    $("videos-resumen").textContent = sin
      ? `${videos.length} ${videos.length === 1 ? "video" : "videos"}; ${sin} ${sin === 1 ? "falta" : "faltan"} por calibrar. Cada video recuerda su calibración y sus resultados.`
      : `${videos.length} ${videos.length === 1 ? "video" : "videos"}, todos calibrados.`;
  }

  async function cargar() {
    try {
      videos = (await pedirVideos()).videos;
      pintar();
    } catch (error) {
      $("videos-lista").innerHTML = `<li class="vacio-lista" style="display:block">${esc(error.message)} <button class="enlace" type="button" id="videos-reintentar">Reintentar</button></li>`;
      $("videos-reintentar").addEventListener("click", cargar);
    }
  }

  // Elegir una accion sobre un video lo deja como el "video actual" para Calibrar y Procesar.
  $("videos-lista").addEventListener("click", (e) => {
    const enlace = e.target.closest("a[data-video]");
    if (enlace) recordarVideo(enlace.dataset.video);
    const resultados = e.target.closest("a[data-camara]");
    if (resultados) { try { localStorage.setItem("aforo.camara", resultados.dataset.camara); } catch { /* sin almacenamiento */ } }
  });

  // ------------------------------------------------------------------ agregar
  const mostrarError = (texto) => { $("videos-error").textContent = texto || ""; $("videos-error").hidden = !texto; };
  $("videos-agregar").addEventListener("click", () => {
    const abrir = $("videos-nuevo").hidden;
    $("videos-nuevo").hidden = !abrir;
    $("videos-agregar").setAttribute("aria-expanded", String(abrir));
    if (abrir) $("videos-ruta").focus();
    mostrarError("");
  });
  $("videos-form-ruta").addEventListener("submit", async (e) => {
    e.preventDefault();
    const ruta = $("videos-ruta").value.trim();
    if (!ruta) { mostrarError("Escribe la ruta completa del video."); return; }
    mostrarError("");
    try {
      const { nombre } = await agregarVideoRuta(ruta);
      $("videos-ruta").value = "";
      $("videos-nuevo").hidden = true;
      $("videos-agregar").setAttribute("aria-expanded", "false");
      recordarVideo(nombre);
      await cargar();
    } catch (error) {
      mostrarError(error.message);
    }
  });
  $("videos-archivo").addEventListener("change", async (e) => {
    const archivo = e.target.files[0];
    if (!archivo) return;
    mostrarError("");
    const barra = $("videos-progreso");
    barra.hidden = false;
    $("videos-subida").textContent = `Subiendo ${archivo.name}…`;
    try {
      const { nombre } = await subirVideo(archivo, (f) => {
        barra.firstElementChild.style.width = `${Math.round(f * 100)}%`;
        $("videos-subida").textContent = `Subiendo ${archivo.name}: ${Math.round(f * 100)} %`;
      });
      $("videos-subida").textContent = "";
      $("videos-nuevo").hidden = true;
      $("videos-agregar").setAttribute("aria-expanded", "false");
      recordarVideo(nombre);
      await cargar();
    } catch (error) {
      $("videos-subida").textContent = "";
      mostrarError(error.message);
    } finally {
      barra.hidden = true;
      barra.firstElementChild.style.width = "0";
      e.target.value = "";
    }
  });

  return { mostrar: cargar };
}
