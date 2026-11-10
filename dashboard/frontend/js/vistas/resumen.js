// Vista "Resumen". Responde una pregunta: cuanto trafico pasa por esta via y a que velocidad
// respecto al limite. El hallazgo va en la frase bajo el titulo; el grafico mayor lo demuestra
// vehiculo por vehiculo y el riel muestra la evidencia: el cuadro del video de ese vehiculo.

import { crearEvidencia } from "../componentes/evidencia.js";
import { segmentos } from "../componentes/segmentos.js";
import { poner } from "../componentes/texto.js";
import { conSigno, dec1, entero, esc, fecha, hora, nombreTipo, tipoConArticulo } from "../formato.js";
import { alRedimensionar } from "../graficos/base.js";
import { columnas } from "../graficos/columnas.js";
import { dispersion } from "../graficos/dispersion.js";
import { histograma } from "../graficos/histograma.js";

const FILAS_EXCESOS = 5;
const $ = (id) => document.getElementById(id);
const sinCero = (v) => dec1(v).replace(/,0$/, "");

/** Senal reglamentaria de velocidad maxima, dibujada con el limite de esta via. */
function senal(limite) {
  const texto = sinCero(limite);
  return `<svg width="100%" height="100%" viewBox="0 0 52 52" role="img" aria-label="Límite de velocidad: ${texto} km/h">
    <circle cx="26" cy="26" r="22.5" fill="#ffffff" stroke="var(--negative)" stroke-width="6"/>
    <text x="26" y="${texto.length > 2 ? 31 : 32.5}" text-anchor="middle" font-family="var(--font)" font-weight="600"
      font-size="${texto.length > 2 ? 15 : 19}" fill="var(--text)" style="font-variant-numeric: tabular-nums">${esc(texto)}</text>
  </svg>`;
}

export function crearResumen() {
  const evidencia = crearEvidencia($("evidencia"));
  let panel = null;
  let puntos = [];
  let tipo = "todos";
  let seleccion = null;         // track elegido por la persona (null = el mas rapido)

  const elDispersion = $("g-dispersion"), elAforo = $("g-aforo"), elHisto = $("g-histograma");
  alRedimensionar(elDispersion, dibujarDispersion);
  alRedimensionar(elAforo, dibujarAforo);
  alRedimensionar(elHisto, dibujarHistograma);

  function dominio() {
    if (panel.ejecucion && panel.ejecucion.duracion_s) {
      const inicio = fecha(panel.ejecucion.inicio).getTime();
      return [inicio, inicio + panel.ejecucion.duracion_s * 1000];
    }
    const tiempos = panel.cruces.map((c) => fecha(c.t).getTime());
    const t0 = Math.min(...tiempos), t1 = Math.max(...tiempos);
    return [t0, Math.max(t1, t0 + 1000)];
  }

  const masRapido = () => puntos.reduce((mejor, p) => (!mejor || p.v > mejor.v ? p : mejor), null);
  const elegido = () => puntos.find((p) => p.id === seleccion) || masRapido();

  function dibujarDispersion() {
    if (!panel) return;
    const actual = elegido();
    dispersion(elDispersion, {
      puntos, limite: panel.limite_kmh, dominio: dominio(), tipo,
      seleccion: actual ? actual.id : null,
      alElegir: (p) => elegir(p.id),
    });
  }
  function dibujarAforo() {
    if (!panel) return;
    columnas(elAforo, {
      minutos: panel.por_minuto.map((m) => ({ t: fecha(m.t + ":00").getTime(), n: m.n })),
      lecturas: panel.lecturas.map((l) => ({ t: fecha(l.t).getTime(), estado: l.estado })),
      dominio: dominio(),
    });
  }
  function dibujarHistograma() {
    if (!panel) return;
    histograma(elHisto, { velocidades: puntos.map((p) => p.v), limite: panel.limite_kmh, v85: panel.umbral_pico });
  }

  function elegir(track) {
    seleccion = track;
    pintarEvidencia();
    pintarExcesos();
    dibujarDispersion();
  }

  function pintarEvidencia() {
    const v = elegido();
    const esElMasRapido = v && v === masRapido();
    evidencia.mostrar({
      camara: panel.camara,
      vehiculo: v ? { track: v.id, tipo: v.tipo, t: v.momento, v: v.v } : null,
      limite: panel.limite_kmh,
      fps: panel.ejecucion ? panel.ejecucion.fps : null,
      motivo: esElMasRapido ? "El más rápido" : "Seleccionado",
      acciones: v
        ? `<a class="enlace" href="#/vehiculos?id=${encodeURIComponent(v.id)}">Abrir en el registro</a>${
            esElMasRapido ? "" : `<button class="enlace" type="button" data-accion="mas-rapido">Volver al más rápido</button>`}`
        : "",
    });
  }
  $("evidencia").addEventListener("click", (e) => {
    if (e.target.closest('[data-accion="mas-rapido"]')) elegir(null);
  });

  function pintarExcesos() {
    const lista = $("lista-excesos");
    const excesos = puntos.filter((p) => p.v > panel.limite_kmh).sort((a, b) => b.v - a.v).slice(0, FILAS_EXCESOS);
    const actual = elegido();
    $("ver-excesos").hidden = panel.velocidad.excesos <= excesos.length;
    $("ver-excesos").textContent = `Ver los ${entero(panel.velocidad.excesos)} excesos`;
    if (!excesos.length) {
      lista.innerHTML = `<li class="lista-vacia">${puntos.length
        ? `Ningún vehículo superó el límite de ${sinCero(panel.limite_kmh)} km/h.`
        : "Todavía no hay velocidades medidas."}</li>`;
      return;
    }
    lista.innerHTML = excesos.map((p) => `<li>
      <button class="lista-fila" type="button" data-track="${esc(p.id)}" aria-pressed="${actual && actual.id === p.id}">
        <span><span>${esc(nombreTipo(p.tipo))} <span class="id">#${esc(p.id)}</span></span><span class="l2">${hora(p.momento)}</span></span>
        <span class="der"><span>${dec1(p.v)} <span class="suave">km/h</span></span><span class="l2">${conSigno(p.v - panel.limite_kmh)}</span></span>
      </button></li>`).join("");
  }
  $("lista-excesos").addEventListener("click", (e) => {
    const fila = e.target.closest(".lista-fila");
    if (fila) elegir(Number(fila.dataset.track));
  });

  function pintarTipos() {
    const media = Object.fromEntries(panel.por_tipo.map((t) => [t.tipo, t.promedio]));
    const filas = [...panel.tipos].sort((a, b) => b.total - a.total);
    const mayor = Math.max(1, ...filas.map((f) => f.total));
    $("tabla-tipos").tBodies[0].innerHTML = filas.map((f, i) => `<tr>
      <td>${esc(nombreTipo(f.nombre))}<span class="barra-fina${i === 0 && f.total ? " mayor" : ""}" style="width:${f.total ? Math.max(3, (100 * f.total) / mayor) : 0}%"></span></td>
      <td class="num">${entero(f.total)}</td>
      <td class="num suave">${entero(f.pct)} %</td>
      <td class="num">${media[f.nombre] !== undefined ? `${dec1(media[f.nombre])} <span class="suave">km/h</span>` : '<span class="suave">—</span>'}</td>
    </tr>`).join("");
  }

  function pintarCifras() {
    const v = panel.velocidad, limite = panel.limite_kmh, limiteTexto = sinCero(limite);
    $("senal").innerHTML = senal(limite);
    $("leyenda-limite").lastElementChild.textContent = `Límite de ${limiteTexto} km/h`;

    // --- El hallazgo: la frase que se lee primero ---
    const rapido = masRapido();
    let frase;
    if (!v.mediciones) {
      frase = `Se contaron <b>${entero(panel.total)}</b> vehículos; ninguno completó el tramo de medición, así que no hay velocidades.`;
    } else if (!v.excesos) {
      frase = `Ninguno de los <b>${entero(v.mediciones)}</b> vehículos medidos superó el límite de ${limiteTexto} km/h. El más rápido, ${tipoConArticulo(rapido.tipo)}, pasó a <b>${dec1(rapido.v)} km/h</b>.`;
    } else {
      frase = `<b>${entero(v.excesos)} de ${entero(v.mediciones)}</b> vehículos medidos superaron el límite de ${limiteTexto} km/h. El más rápido, ${tipoConArticulo(rapido.tipo)}, pasó a <b>${dec1(rapido.v)} km/h</b> a las ${hora(rapido.momento, false)}.`;
    }
    $("hallazgo").innerHTML = frase;

    const accion = $("accion-excesos");
    accion.hidden = !v.excesos;
    accion.textContent = `Revisar ${entero(v.excesos)} ${v.excesos === 1 ? "exceso" : "excesos"}`;

    // --- Indicadores ---
    poner($("k-total"), entero(panel.total));
    const dur = panel.ejecucion && panel.ejecucion.duracion_s;
    $("k-total-nota").textContent = dur
      ? `${dec1(panel.total / (dur / 60))} por minuto`
      : `último cruce a las ${hora(panel.ultimo_cruce)}`;

    poner($("k-media"), v.promedio !== null ? dec1(v.promedio) : "—");
    $("k-media-u").textContent = v.promedio !== null ? "km/h" : "";
    $("k-media-nota").textContent = `${entero(v.mediciones)} de ${entero(panel.total)} con medición`;

    const v85 = panel.umbral_pico;
    poner($("k-v85"), v85 !== null ? dec1(v85) : "—");
    $("k-v85-u").textContent = v85 !== null ? "km/h" : "";
    $("k-v85-nota").innerHTML = v85 === null ? "sin mediciones"
      : v85 > limite ? `<span class="malo">${conSigno(v85 - limite)}</span> sobre el límite`
      : "dentro del límite";

    poner($("k-exceso"), v.pct_excesos !== null ? entero(v.pct_excesos) : "—");
    $("k-exceso-u").textContent = v.pct_excesos !== null ? "%" : "";
    $("k-exceso-nota").textContent = v.mediciones ? `${entero(v.excesos)} de ${entero(v.mediciones)} medidos` : "sin mediciones";
  }

  function pintarFiltroDeTipos() {
    const presentes = panel.tipos.filter((t) => puntos.some((p) => p.tipo === t.nombre));
    if (tipo !== "todos" && !presentes.some((t) => t.nombre === tipo)) tipo = "todos";
    const raiz = $("seg-tipos");
    raiz.hidden = presentes.length < 2;
    if (presentes.length < 2) return;
    segmentos(raiz, [
      { valor: "todos", texto: "Todos", cuenta: entero(puntos.length) },
      ...presentes.map((t) => ({ valor: t.nombre, texto: nombreTipo(t.nombre), cuenta: entero(puntos.filter((p) => p.tipo === t.nombre).length) })),
    ], tipo, (valor) => { tipo = valor; pintarFiltroDeTipos(); dibujarDispersion(); }, "Tipo de vehículo en el gráfico");
  }

  function pintarLeyendaVia() {
    const presentes = ["LIBRE", "FLUIDO", "DETENIDO"].filter((e) => panel.lecturas.some((l) => l.estado === e));
    const nombres = { LIBRE: "Libre", FLUIDO: "Fluido", DETENIDO: "Detenido" };
    $("leyenda-via").innerHTML = presentes.length
      ? `<li>Estado de la vía</li>${presentes.map((e) => `<li><span class="tira via-${e}"></span>${nombres[e]}</li>`).join("")}`
      : "";
  }

  /** Pinta la vista completa con un panel nuevo. */
  function pintar(nuevo, cambioDeCamara) {
    panel = nuevo;
    puntos = panel.puntos.map((p) => ({ t: fecha(p.t).getTime(), momento: p.t, v: p.v, tipo: p.tipo, id: p.id }));
    if (cambioDeCamara) { seleccion = null; tipo = "todos"; }
    pintarCifras();
    pintarFiltroDeTipos();
    pintarLeyendaVia();
    pintarTipos();
    pintarExcesos();
    pintarEvidencia();
    redibujar();
  }

  function redibujar() {
    dibujarDispersion();
    dibujarAforo();
    dibujarHistograma();
  }

  return { pintar, redibujar };
}
