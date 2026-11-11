// Vista "Procesar": se elige video y modo, se inicia el analisis (proceso aparte en el servidor) y se
// sigue en vivo: el cuadro anotado, el avance y las cifras. Tambien mantiene el indicador del menu.

import { ErrorApi, detenerProceso, iniciarProceso, pedirProceso, pedirSistema, pedirVideos, urlUltimoCuadro, urlVistaEnVivo } from "../api.js";
import { poner } from "../componentes/texto.js";
import { dec1, duracion, entero, esc, nombreTipo } from "../formato.js";
import { recordarVideo, videoRecordado } from "../estado.js";

const $ = (id) => document.getElementById(id);
const ACTIVO = ["iniciando", "corriendo"];
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/**
 * @param {{alEstado: (datos: object) => void, alTerminar: (datos: object) => void}} ganchos
 *   alEstado: cada vez que cambia el estado o el progreso (para el indicador del menu).
 *   alTerminar: una sola vez cuando un analisis en marcha termina, se detiene o falla.
 */
export function crearProcesar({ alEstado, alTerminar }) {
  let videos = [];
  let gpu = null;                    // "gpu" | "cpu_con_gpu" | "cpu" (se averigua en segundo plano)
  let estado = { estado: "libre" };
  let visible = false;
  let temporizador = 0;
  let viendoEnVivo = false;

  const video = () => videos.find((v) => v.nombre === $("proc-video").value);
  const modo = () => (document.querySelector('input[name="modo"]:checked') || {}).value;
  const activo = () => ACTIVO.includes(estado.estado);

  // ------------------------------------------------------------------ opciones
  function pintarVideos(preferido) {
    $("proc-video").innerHTML = videos.map((v) => `<option value="${esc(v.nombre)}">${esc(v.nombre)}${v.calibrado ? "" : " · sin calibrar"}</option>`).join("");
    const elegido = videos.find((v) => v.nombre === preferido) || videos.find((v) => v.nombre === videoRecordado()) || videos.find((v) => v.calibrado) || videos[0];
    if (elegido) $("proc-video").value = elegido.nombre;
    pintarOpciones();
  }

  function pintarOpciones() {
    const v = video();
    const nota = $("proc-video-nota");
    if (!v) { nota.innerHTML = 'No hay videos. <a class="enlace" href="#/videos">Agrega uno</a>.'; }
    else if (!v.calibrado) nota.innerHTML = 'Este video aún no está calibrado. <a class="enlace" href="#/calibrar?video=' + encodeURIComponent(v.nombre) + '">Calibrarlo →</a>';
    else nota.textContent = `Cámara «${v.camara}»${v.duracion_s ? ` · ${duracion(v.duracion_s)} de video` : ""}`;

    // Modo recomendado segun el hardware: con GPU el modo en vivo es fiable; sin ella, el rapido.
    const recomendado = gpu === "gpu" ? "vivo" : gpu ? "rapido" : null;
    document.querySelectorAll(".modo").forEach((m) => m.classList.toggle("recomendado", m.querySelector("input").value === recomendado));
    if (!modo()) {
      const por_defecto = document.querySelector(`input[name="modo"][value="${recomendado || "vivo"}"]`);
      if (por_defecto) por_defecto.checked = true;
    }
    const m = modo();
    const textoVivo = document.querySelector('input[value="vivo"] + .modo-cuerpo small');
    if (textoVivo) {
      textoVivo.textContent = gpu === "gpu"
        ? "Se ve como un video y casi no pierde vehículos con tu GPU. Se guarda aparte, como «cámara_vivo»."
        : "Se ve como un video, pero sin GPU salta muchos cuadros y pierde vehículos: sirve para demostrar. Se guarda aparte, como «cámara_vivo».";
    }
    // "Reemplazar" solo aplica a los modos que escriben en la camara del video.
    const previos = v ? v.cruces : 0;
    $("proc-reemplazar-fila").hidden = m === "vivo" || !previos;
    $("proc-previos").textContent = previos ? `(hoy tiene ${entero(previos)} cruces)` : "";
    $("proc-guardar-fila").hidden = m !== "completo";
    $("proc-iniciar").disabled = activo() || !v || !v.calibrado || !v.legible;
  }

  $("proc-video").addEventListener("change", () => { recordarVideo($("proc-video").value); pintarOpciones(); });
  $("proc-modos").addEventListener("change", pintarOpciones);

  // ------------------------------------------------------------------ iniciar / detener
  $("proc-iniciar").addEventListener("click", async () => {
    const v = video();
    if (!v) return;
    $("proc-error").hidden = true;
    $("proc-iniciar").disabled = true;
    try {
      estado = await iniciarProceso({
        video: v.nombre, modo: modo(), reemplazar: !$("proc-reemplazar-fila").hidden && $("proc-reemplazar").checked,
        guardar_video: !$("proc-guardar-fila").hidden && $("proc-guardar").checked,
      });
      $("proc-final").hidden = true;
      viendoEnVivo = false;
      pintarEstado();
      sondear();
    } catch (error) {
      $("proc-error").textContent = error instanceof ErrorApi ? error.message : "No se pudo iniciar el análisis.";
      $("proc-error").hidden = false;
      pintarOpciones();
    }
  });
  $("proc-detener").addEventListener("click", async () => {
    $("proc-detener").disabled = true;
    try { estado = await detenerProceso(); } catch { /* el sondeo mostrara el estado real */ }
    pintarEstado();
  });

  // ------------------------------------------------------------------ pintar el estado
  function pintarEstado() {
    const e = estado;
    const enMarcha = activo();
    const progreso = typeof e.progreso === "number" ? e.progreso : 0;
    const pct = Math.round(progreso * 100);
    $("proc-detener").hidden = !enMarcha;
    $("proc-detener").disabled = false;
    $("proc-iniciar").hidden = enMarcha;
    $("proc-video").disabled = $("proc-modos").disabled = enMarcha;
    $("proc-modos").querySelectorAll("input").forEach((i) => { i.disabled = enMarcha; });
    pintarOpciones();

    const barra = $("proc-progreso");
    barra.firstElementChild.style.width = `${e.estado === "terminado" ? 100 : pct}%`;
    barra.classList.toggle("listo", e.estado === "terminado");
    barra.setAttribute("aria-valuenow", String(e.estado === "terminado" ? 100 : pct));

    const fps = e.fps_video || 30;
    const textos = {
      libre: "Sin análisis en curso",
      iniciando: "Cargando el modelo…",
      corriendo: `Analizando · ${mmss((e.frame || 0) / fps)}${e.total_frames ? ` de ${mmss(e.total_frames / fps)}` : ""} del video`,
      terminado: "Análisis terminado",
      detenido: `Detenido al ${pct} %`,
      error: "El análisis falló",
    };
    $("proc-estado").textContent = textos[e.estado] || e.estado;
    $("proc-pct").textContent = e.estado === "corriendo" || e.estado === "detenido" ? `${pct} %` : "";

    // --- Vista en vivo ---
    const imagen = $("proc-img"), vacio = $("proc-vacio");
    if (enMarcha && e.modo !== "rapido") {
      if (!viendoEnVivo && e.estado === "corriendo") {
        imagen.src = urlVistaEnVivo();
        imagen.hidden = false;
        vacio.hidden = true;
        viendoEnVivo = true;
      } else if (e.estado === "iniciando") {
        imagen.hidden = true; vacio.hidden = false;
        $("proc-vacio-texto").textContent = "Cargando el modelo de detección…";
      }
    } else if (enMarcha) {                       // modo rapido: no hay cuadros
      imagen.hidden = true; vacio.hidden = false;
      $("proc-vacio-texto").textContent = "En este modo no se dibuja nada para ir más rápido. Mira el avance abajo.";
    } else if (viendoEnVivo || ["terminado", "detenido"].includes(e.estado)) {
      if (e.modo !== "rapido" && imagen.dataset.final !== "1") { imagen.src = urlUltimoCuadro(); imagen.hidden = false; vacio.hidden = true; imagen.dataset.final = "1"; }
      viendoEnVivo = false;
    }
    if (enMarcha) imagen.dataset.final = "";

    // --- Cifras ---
    const hayCifras = enMarcha || ["terminado", "detenido"].includes(e.estado);
    $("proc-kpis").hidden = !hayCifras;
    if (hayCifras) {
      poner($("p-total"), entero(e.total || 0));
      const clases = Object.entries(e.por_clase || {}).filter(([, n]) => n > 0).map(([t, n]) => `${entero(n)} ${nombreTipo(t).toLowerCase()}`).join(" · ");
      $("p-clases").textContent = clases || "aún ninguno";
      poner($("p-med"), entero(e.mediciones || 0));
      $("p-media").textContent = e.velocidad_media ? `media ${dec1(e.velocidad_media)} km/h` : "sin mediciones aún";
      poner($("p-exc"), entero(e.alertas_exceso || 0));
      $("p-via").textContent = e.estado_via ? { LIBRE: "vía libre", FLUIDO: "tráfico fluido", DETENIDO: "tráfico detenido" }[e.estado_via] || "" : " ";
      poner($("p-cps"), e.cuadros_por_s ? dec1(e.cuadros_por_s) : "0");
      $("p-resto").textContent = e.restante_s && enMarcha ? `quedan ~${duracion(e.restante_s)}` : (e.saltados ? `se saltaron ${entero(e.saltados)} cuadros` : " ");
    }

    // --- Registro tecnico ---
    $("proc-log").textContent = (e.registro && e.registro.length ? e.registro.join("\n") : "Aún no hay registro.");

    // --- Resultado final ---
    const final = $("proc-final");
    if (["terminado", "detenido", "error"].includes(e.estado) && !enMarcha) {
      final.hidden = false;
      final.classList.toggle("mal", e.estado === "error");
      const camara = esc(e.camara || "");
      if (e.estado === "error") {
        final.innerHTML = `<h2>El análisis no pudo terminar</h2><p>${esc(e.mensaje || "Ocurrió un error inesperado.")}</p>
          <p>Revisa el registro técnico de la derecha. Si el mensaje habla de una calibración, <a class="enlace" href="#/calibrar?video=${encodeURIComponent(e.video || "")}">corrígela aquí</a>.</p>`;
      } else {
        final.innerHTML = `<h2>${e.estado === "terminado" ? "Listo" : "Detenido"}: ${entero(e.total || 0)} vehículos contados</h2>
          <p>${e.estado === "detenido" ? "Los datos guardados hasta ese punto ya están en el panel." : "Todo quedó guardado en la base de datos."}
          Cámara «${camara}»${e.mediciones ? `, ${entero(e.mediciones)} con velocidad medida y ${entero(e.alertas_exceso || 0)} excesos` : ""}.</p>
          <div class="acciones"><a class="boton primario" href="#/resumen" data-camara="${camara}">Ver los resultados</a>
          <a class="boton contorno" href="#/vehiculos" data-camara="${camara}">Abrir el registro de vehículos</a></div>`;
      }
    } else {
      final.hidden = true;
    }
    alEstado(e);
  }

  // Al ir a los resultados de la camara recien procesada, el panel debe mostrar esa camara.
  $("proc-final").addEventListener("click", (ev) => {
    const enlace = ev.target.closest("a[data-camara]");
    if (enlace) { try { localStorage.setItem("aforo.camara", enlace.dataset.camara); } catch { /* sin almacenamiento */ } }
  });

  // ------------------------------------------------------------------ sondeo
  async function sondear() {
    clearTimeout(temporizador);
    let anterior = estado.estado;
    try {
      estado = await pedirProceso();
    } catch { /* el servidor esta ocupado; se reintenta */ }
    pintarEstado();
    if (activo()) {
      temporizador = setTimeout(sondear, 800);
    } else if (ACTIVO.includes(anterior)) {
      alTerminar(estado);
    }
  }

  async function averiguarGpu() {
    if (gpu) return;
    try { gpu = (await pedirSistema()).gpu.modo; } catch { gpu = "cpu"; }
    pintarOpciones();
  }

  return {
    /** Al abrir la vista. */
    async mostrar(parametros) {
      visible = true;
      try { videos = (await pedirVideos()).videos; } catch (error) {
        $("proc-error").textContent = error.message; $("proc-error").hidden = false; videos = [];
      }
      pintarVideos(parametros.video);
      averiguarGpu();
      await sondear();
    },
    ocultar() {
      visible = false;
      if (!activo()) clearTimeout(temporizador);
      if (viendoEnVivo) { $("proc-img").removeAttribute("src"); viendoEnVivo = false; }   // no sigue bajando el flujo
    },
    /** Al arrancar la app: si ya habia un analisis en marcha (de otra sesion), se retoma el seguimiento. */
    async retomar() {
      try { estado = await pedirProceso(); } catch { return; }
      alEstado(estado);
      if (activo()) sondear();
    },
    hayAnalisis: activo,
  };
}
