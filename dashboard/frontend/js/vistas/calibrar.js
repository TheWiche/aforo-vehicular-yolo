// Vista "Calibrar": se colocan las tres lineas sobre un cuadro del video arrastrandolas, o escribiendo
// sus coordenadas, y se indica cuantos metros hay entre A y B. Se guarda en datos/calibraciones.json.

import { ErrorApi, guardarCalibracion, pedirCalibracion, pedirVideos, urlCuadroVideo } from "../api.js";
import { crearEditor } from "../componentes/editorLineas.js";
import { dec1, dec2, entero, esc } from "../formato.js";
import { recordarVideo, videoRecordado } from "../estado.js";

const $ = (id) => document.getElementById(id);
const LINEAS = [
  { id: "conteo", nombre: "Línea de conteo", clase: "conteo",
    desc: "Cada vehículo que la cruza se cuenta una vez. Colócala dentro del tramo A–B." },
  { id: "a", nombre: "Línea A", clase: "punteada", desc: "Inicio del tramo medido: se anota el instante en que el vehículo la cruza." },
  { id: "b", nombre: "Línea B", clase: "punteada", desc: "Fin del tramo. Velocidad = distancia entre A y B ÷ tiempo entre A y B." },
];
const PATRON_CAMARA = /^[A-Za-z0-9_-]{1,40}$/;
const num = (v) => { const n = Number(String(v).replace(",", ".")); return Number.isFinite(n) ? n : NaN; };
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function crearCalibrar({ irA }) {
  let videos = [];
  let info = null;              // propiedades del video y perfil guardado
  let sucio = false;            // hay cambios sin guardar
  let regla = { visible: false, metros: null };
  let temporizador = 0;

  const editor = crearEditor($("cal-lienzo"), {
    alCambiar: () => { marcarSucio(); alMoverLineas(); },
    alElegir: () => pintarFilasElegida(),
  });

  // ------------------------------------------------------------------ filas de lineas (rail)
  function construirFilas() {
    $("cal-lineas").innerHTML = LINEAS.map((l) => `
      <div class="linea-fila" data-linea="${l.id}">
        <div class="linea-cab" data-accion="elegir">
          <svg class="linea-muestra" viewBox="0 0 28 10" aria-hidden="true"><line x1="2" y1="5" x2="26" y2="5" ${l.clase === "punteada" ? 'stroke-dasharray="5 4"' : 'style="stroke-width:3.5"'}/></svg>
          <span class="linea-nombre">${l.nombre}</span>
          <button class="enlace" type="button" data-accion="dibujar" style="margin-left:auto;font-weight:400;font-size:12px">Dibujar de nuevo</button>
        </div>
        <p class="linea-desc">${l.desc}</p>
        <div class="linea-coords">
          ${["x1", "y1", "x2", "y2"].map((c, i) => `<label>${c.toUpperCase()}<input class="entrada num" type="number" step="1" inputmode="numeric" data-i="${i}" aria-label="${l.nombre}, coordenada ${c}"></label>`).join("")}
        </div>
      </div>`).join("");
  }
  construirFilas();

  $("cal-lineas").addEventListener("click", (e) => {
    const fila = e.target.closest(".linea-fila");
    if (!fila) return;
    const id = fila.dataset.linea;
    if (e.target.closest('[data-accion="dibujar"]')) { editor.dibujar(id); pintarFilasElegida(); return; }
    if (e.target.closest('[data-accion="elegir"]')) { editor.elegir(id); pintarFilasElegida(); }
  });
  $("cal-lineas").addEventListener("focusin", (e) => {
    const fila = e.target.closest(".linea-fila");
    if (fila) { editor.elegir(fila.dataset.linea); pintarFilasElegida(); }
  });
  $("cal-lineas").addEventListener("input", (e) => {
    const campo = e.target.closest("input[data-i]");
    if (!campo) return;
    const id = campo.closest(".linea-fila").dataset.linea;
    const { ancho, alto } = editor.tamano();
    const l = editor.obtener()[id].map((p) => [...p]);
    const i = Number(campo.dataset.i);
    const v = Math.round(num(campo.value));
    if (!Number.isFinite(v)) return;
    const tope = i % 2 === 0 ? ancho : alto;
    l[i >> 1][i % 2] = Math.max(0, Math.min(tope, v));
    editor.poner({ [id]: l });
    marcarSucio();
    alMoverLineas(campo);
  });

  function pintarFilasElegida() {
    const elegida = editor.elegida();
    document.querySelectorAll("#cal-lineas .linea-fila").forEach((f) => f.classList.toggle("elegida", f.dataset.linea === elegida));
  }

  /** Copia las coordenadas del editor a los campos numericos (salvo el que se esta editando). */
  function volcarCoordenadas(salvo = null) {
    const lineas = editor.obtener();
    document.querySelectorAll("#cal-lineas .linea-fila").forEach((fila) => {
      const l = lineas[fila.dataset.linea];
      fila.querySelectorAll("input[data-i]").forEach((campo) => {
        if (campo === salvo || !l) return;
        const i = Number(campo.dataset.i);
        campo.value = l[i >> 1][i % 2];
      });
    });
  }

  // ------------------------------------------------------------------ calculos y avisos
  function lineasActuales() {
    const l = editor.obtener();
    return { conteo: l.conteo, a: l.a, b: l.b, regla: l.regla };
  }
  const medio = (l) => [(l[0][0] + l[1][0]) / 2, (l[0][1] + l[1][1]) / 2];
  const largo = (l) => Math.hypot(l[1][0] - l[0][0], l[1][1] - l[0][1]);

  function valores() {
    return {
      distancia: num($("cal-distancia").value), limite: num($("cal-limite").value),
      maxima: num($("cal-max").value), camara: $("cal-camara").value.trim(),
    };
  }

  /** Lista de problemas (mal), sospechas (aviso) y confirmaciones (bien) con los valores actuales. */
  function revisar() {
    const { conteo, a, b } = lineasActuales();
    const v = valores();
    const mal = [], aviso = [];
    for (const [nombre, l] of [["La línea de conteo", conteo], ["La línea A", a], ["La línea B", b]]) {
      if (largo(l) < 10) mal.push(`${nombre} es demasiado corta: alárgala arrastrando uno de sus extremos.`);
    }
    const ma = medio(a), mb = medio(b);
    const eje = [mb[0] - ma[0], mb[1] - ma[1]];
    const largo2 = eje[0] ** 2 + eje[1] ** 2;
    if (largo2 < 400) {
      mal.push("A y B están casi en el mismo sitio: sepáralas a lo largo de la calle.");
    } else {
      const mc = medio(conteo);
      const t = ((mc[0] - ma[0]) * eje[0] + (mc[1] - ma[1]) * eje[1]) / largo2;
      if (t < 0 || t > 1) aviso.push("La línea de conteo debería quedar entre A y B: así cada vehículo se cuenta dentro del tramo medido.");
    }
    if (!(v.distancia >= 0.5 && v.distancia <= 1000)) mal.push("Indica la distancia real entre A y B (entre 0,5 y 1000 m).");
    if (!(v.limite >= 1 && v.limite <= 400)) mal.push("Indica el límite de velocidad de la vía (entre 1 y 400 km/h).");
    if (!(v.maxima >= 1 && v.maxima <= 400)) mal.push("Indica la velocidad máxima creíble (entre 1 y 400 km/h).");
    else if (v.maxima <= v.limite) mal.push("La velocidad máxima creíble debe ser mayor que el límite.");
    if (!PATRON_CAMARA.test(v.camara)) mal.push("El nombre de la cámara solo puede tener letras, números, guion y guion bajo.");
    return { mal, aviso };
  }

  function pintarAvisos() {
    const { mal, aviso } = revisar();
    const items = [...mal.map((t) => ["mal", t]), ...aviso.map((t) => ["", t])];
    if (!items.length) items.push(["bien", "Todo en orden: las líneas están dentro del video y los valores son coherentes."]);
    $("cal-avisos").innerHTML = items.map(([c, t]) => `<li class="${c}">${esc(t)}</li>`).join("");
    $("cal-guardar-boton").disabled = mal.length > 0;
    for (const id of ["cal-distancia", "cal-limite", "cal-max", "cal-camara"]) $(id).removeAttribute("aria-invalid");
    const v = valores();
    if (!(v.distancia >= 0.5 && v.distancia <= 1000)) $("cal-distancia").setAttribute("aria-invalid", "true");
    if (!PATRON_CAMARA.test(v.camara)) $("cal-camara").setAttribute("aria-invalid", "true");
  }

  function pintarEjemplo() {
    const { a, b } = lineasActuales();
    const { distancia } = valores();
    if (!(distancia > 0)) { $("cal-ejemplo").textContent = "Indica la distancia real entre A y B para ver un ejemplo."; return; }
    const px = Math.hypot(medio(b)[0] - medio(a)[0], medio(b)[1] - medio(a)[1]);
    const tipico = 0.6;
    const v = (distancia / tipico) * 3.6;
    $("cal-ejemplo").innerHTML =
      `El sistema anota en qué cuadro cada vehículo cruza la línea <b>A</b> y en cuál cruza la <b>B</b>. `
      + `Con tu calibración, un vehículo que tarda <b>${dec2(tipico)} s</b> en recorrer los <b>${dec1(distancia)} m</b> entre ellas va a `
      + `<b>${dec1(v)} km/h</b> (distancia ÷ tiempo). Por eso la distancia real es el dato más importante: si está mal, `
      + `todas las velocidades salen mal en la misma proporción. En el video, A y B están separadas por <b>${entero(px)} píxeles</b>`
      + ` (${dec1(px / distancia)} píxeles por metro).`;
  }

  function actualizarCota() {
    const d = valores().distancia;
    editor.ponerCota(d > 0 ? `${dec1(d)} m` : "");
  }

  // ------------------------------------------------------------------ regla de referencia
  function pintarRegla() {
    const l = editor.obtener().regla;
    const m = num($("cal-regla-m").value);
    const resultado = $("cal-regla-res");
    $("cal-regla-usar").disabled = true;
    if (!regla.visible || !l) { resultado.textContent = ""; return; }
    const px = largo(l);
    if (!(m > 0)) { resultado.textContent = "Indica cuánto mide en la realidad el objeto que marcaste."; return; }
    const pxm = px / m;
    const { a, b } = lineasActuales();
    const ma = medio(a), mb = medio(b);
    const u = [(l[1][0] - l[0][0]) / px, (l[1][1] - l[0][1]) / px];
    const entre = Math.abs((mb[0] - ma[0]) * u[0] + (mb[1] - ma[1]) * u[1]);
    const d = Math.round((entre / pxm) * 10) / 10;
    resultado.innerHTML = `La referencia mide <b>${entero(px)} px</b>, o sea <b>${dec1(pxm)} px por metro</b>. `
      + `Entre A y B hay <b>${entero(entre)} px</b> en esa dirección: unos <b>${dec1(d)} m</b>. `
      + `La perspectiva puede cambiar el valor: usa un objeto cercano a la zona de medición.`;
    $("cal-regla-usar").disabled = !(d >= 0.5);
    $("cal-regla-usar").dataset.valor = String(d);
  }
  $("cal-regla-boton").addEventListener("click", () => {
    regla.visible = !regla.visible;
    $("cal-regla-boton").setAttribute("aria-expanded", String(regla.visible));
    $("cal-regla-detalle").hidden = !regla.visible;
    const { ancho, alto } = editor.tamano();
    if (regla.visible && !editor.obtener().regla) {
      editor.poner({ regla: [[Math.round(ancho * 0.35), Math.round(alto * 0.85)], [Math.round(ancho * 0.55), Math.round(alto * 0.85)]] });
    }
    if (!regla.visible) editor.poner({ regla: null });
    else editor.elegir("regla");
    pintarRegla();
  });
  $("cal-regla-m").addEventListener("input", () => { regla.metros = num($("cal-regla-m").value); pintarRegla(); marcarSucio(); });
  $("cal-regla-usar").addEventListener("click", () => {
    $("cal-distancia").value = $("cal-regla-usar").dataset.valor;
    alCambiarValores();
  });

  // ------------------------------------------------------------------ cambios
  function marcarSucio() {
    sucio = true;
    $("cal-guardado").hidden = true;
  }
  function alMoverLineas(salvo = null) {
    volcarCoordenadas(salvo);
    pintarAvisos();
    pintarEjemplo();
    pintarRegla();
  }
  function alCambiarValores() {
    marcarSucio();
    actualizarCota();
    pintarAvisos();
    pintarEjemplo();
    pintarRegla();
  }
  for (const id of ["cal-distancia", "cal-limite", "cal-max", "cal-camara"]) $(id).addEventListener("input", alCambiarValores);

  // ------------------------------------------------------------------ cuadro del video
  function mostrarCuadro() {
    if (!info) return;
    const t = Number($("cal-t").value);
    $("cal-reloj").textContent = `${clock(t)} / ${clock(info.duracion_s || 0)}`;
    clearTimeout(temporizador);
    temporizador = setTimeout(() => editor.cargarImagen(urlCuadroVideo(info.video, t, Math.min(1280, info.ancho)), info.ancho, info.alto), 120);
  }
  $("cal-t").addEventListener("input", mostrarCuadro);
  const saltar = (s) => {
    const campo = $("cal-t");
    campo.value = String(Math.max(0, Math.min(Number(campo.max), Number(campo.value) + s)));
    mostrarCuadro();
  };
  $("cal-menos").addEventListener("click", () => saltar(-5));
  $("cal-mas").addEventListener("click", () => saltar(5));

  // ------------------------------------------------------------------ guardar
  $("cal-guardar-boton").addEventListener("click", async () => {
    const boton = $("cal-guardar-boton");
    const { conteo, a, b, regla: lr } = lineasActuales();
    const v = valores();
    boton.disabled = true;
    boton.textContent = "Guardando…";
    try {
      const resp = await guardarCalibracion({
        video: info.video, camara: v.camara, linea_conteo: conteo, linea_a: a, linea_b: b,
        distancia_m: v.distancia, limite_kmh: v.limite, velocidad_max_kmh: v.maxima,
        regla: regla.visible && lr && regla.metros > 0 ? { puntos: lr, metros: regla.metros } : null,
        nota: info.perfil && info.perfil.nota ? info.perfil.nota : null,
      });
      sucio = false;
      info.calibrado = true;
      info.perfil = { ...(info.perfil || {}), CAMARA: v.camara };
      const aviso = resp.avisos && resp.avisos.length ? ` Ojo: ${esc(resp.avisos[0])}` : "";
      $("cal-guardado").innerHTML = `Calibración guardada. <a href="#/procesar?video=${encodeURIComponent(info.video)}">Procesar este video →</a>${aviso}`;
      $("cal-guardado").hidden = false;
    } catch (error) {
      const lista = error instanceof ErrorApi && error.detalles.length ? error.detalles : [error.message];
      $("cal-avisos").innerHTML = lista.map((t) => `<li class="mal">${esc(t)}</li>`).join("");
    } finally {
      boton.textContent = "Guardar calibración";
      pintarAvisos();
    }
  });

  // ------------------------------------------------------------------ carga de un video
  async function cargarVideo(nombre) {
    $("cal-guardado").hidden = true;
    let datos;
    try {
      datos = await pedirCalibracion(nombre);
    } catch (error) {
      $("cal-avisos").innerHTML = `<li class="mal">${esc(error.message)}</li>`;
      return;
    }
    info = datos;
    recordarVideo(nombre);
    const p = datos.perfil, s = datos.sugerido;
    const origen = p && p.LINEA_CONTEO ? p : s;
    editor.poner({
      conteo: origen.LINEA_CONTEO || s.LINEA_CONTEO, a: origen.LINEA_VELOCIDAD_A || s.LINEA_VELOCIDAD_A,
      b: origen.LINEA_VELOCIDAD_B || s.LINEA_VELOCIDAD_B, regla: null,
    });
    $("cal-distancia").value = (p && p.DISTANCIA_REAL_METROS) ?? s.DISTANCIA_REAL_METROS;
    $("cal-limite").value = (p && p.LIMITE_VELOCIDAD_KMH) ?? s.LIMITE_VELOCIDAD_KMH;
    $("cal-max").value = (p && p.VELOCIDAD_MAX_KMH) ?? s.VELOCIDAD_MAX_KMH;
    $("cal-camara").value = (p && p.CAMARA) || datos.camara_sugerida;
    regla = { visible: false, metros: null };
    $("cal-regla-detalle").hidden = true;
    $("cal-regla-boton").setAttribute("aria-expanded", "false");
    $("cal-regla-m").value = "";
    if (p && p.REGLA && p.REGLA.puntos) {
      regla = { visible: true, metros: p.REGLA.metros };
      $("cal-regla-detalle").hidden = false;
      $("cal-regla-boton").setAttribute("aria-expanded", "true");
      $("cal-regla-m").value = p.REGLA.metros;
      editor.poner({ regla: p.REGLA.puntos });
    }
    const duracion = Math.max(1, Math.floor(datos.duracion_s || 1));
    $("cal-t").max = String(duracion);
    $("cal-t").value = String(Math.min(duracion, Math.round(duracion * 0.1)));
    $("cal-consejo").textContent = datos.calibrado
      ? "Este video ya estaba calibrado. Ajusta lo que necesites y vuelve a guardar."
      : "Este video aún no está calibrado: las líneas son una sugerencia. Colócalas sobre la calle y mide la distancia entre A y B.";
    sucio = false;
    editor.elegir("conteo");
    pintarFilasElegida();
    mostrarCuadro();
    actualizarCota();
    alMoverLineas();
  }

  $("cal-video").addEventListener("change", (e) => {
    if (sucio && !confirm("Hay cambios sin guardar. ¿Descartarlos y cambiar de video?")) {
      e.target.value = info.video;
      return;
    }
    irA("calibrar", { video: e.target.value });
  });

  return {
    /** Muestra la vista para el video de la direccion (o el ultimo usado). */
    async mostrar(parametros) {
      try {
        videos = (await pedirVideos()).videos;
      } catch (error) {
        $("cal-avisos").innerHTML = `<li class="mal">${esc(error.message)}</li>`;
        return;
      }
      $("cal-video").innerHTML = videos.map((v) => `<option value="${esc(v.nombre)}">${esc(v.nombre)}${v.calibrado ? " · calibrado" : ""}</option>`).join("");
      const elegido = videos.find((v) => v.nombre === parametros.video) || videos.find((v) => v.nombre === videoRecordado())
        || videos.find((v) => v.legible) || videos[0];
      if (!elegido) {
        $("cal-consejo").innerHTML = 'No hay videos todavía. <a class="enlace" href="#/videos">Agrega uno</a> para calibrarlo.';
        return;
      }
      $("cal-video").value = elegido.nombre;
      if (!info || info.video !== elegido.nombre) await cargarVideo(elegido.nombre);
      else mostrarCuadro();
    },
    haySinGuardar: () => sucio,
  };
}
