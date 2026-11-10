// Vista "Vehículos": el registro completo de cruces de la camara, con filtros, y a su lado el
// detalle del vehiculo elegido: su cuadro del video y como se obtuvo su velocidad.

import { pedirCruces } from "../api.js";
import { crearEvidencia } from "../componentes/evidencia.js";
import { segmentos } from "../componentes/segmentos.js";
import { conSigno, dec1, dec2, entero, esc, hora, nombreTipo, segundosEnTramo } from "../formato.js";

const PAGINA = 50;
const $ = (id) => document.getElementById(id);
const sinCero = (v) => dec1(v).replace(/,0$/, "");
const telefono = window.matchMedia("(max-width: 640px)");

/**
 * @param {(parametros: object) => void} navegar  cambia los filtros en la direccion (#/vehiculos?...)
 */
export function crearVehiculos(navegar) {
  const evidencia = crearEvidencia($("evidencia-detalle"));
  const cuerpo = $("tabla-registro").tBodies[0];
  let panel = null;
  let parametros = { filtro: "todos", tipo: "", id: "", orden: "hora" };
  let filas = [], total = 0, elegida = -1;
  let firma = "", turno = 0;

  const cambiar = (cambios) => navegar({ ...parametros, ...cambios });

  $("v-tipo").addEventListener("change", (e) => cambiar({ tipo: e.target.value }));
  $("v-orden").addEventListener("change", (e) => cambiar({ orden: e.target.value }));
  $("v-id").addEventListener("click", () => cambiar({ id: "" }));
  $("v-mas").addEventListener("click", () => cargar(filas.length));
  $("detalle-volver").addEventListener("click", () => document.body.classList.remove("detalle-abierto"));

  cuerpo.addEventListener("click", (e) => {
    const fila = e.target.closest("tr[data-i]");
    if (fila) elegir(Number(fila.dataset.i), true);
  });
  cuerpo.addEventListener("keydown", (e) => {
    const fila = e.target.closest("tr[data-i]");
    if (!fila) return;
    const i = Number(fila.dataset.i);
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); elegir(i, true); }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const destino = Math.max(0, Math.min(filas.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)));
      elegir(destino, false);
      cuerpo.querySelector(`tr[data-i="${destino}"]`)?.focus();
    }
  });

  function elegir(i, abrirEnTelefono) {
    elegida = i;
    cuerpo.querySelectorAll("tr[data-i]").forEach((tr) => tr.setAttribute("aria-selected", String(Number(tr.dataset.i) === i)));
    pintarDetalle();
    if (abrirEnTelefono && telefono.matches) document.body.classList.add("detalle-abierto");
  }

  function pintarDetalle() {
    const f = filas[elegida];
    const limite = panel.limite_kmh;
    const camara = panel.camara;
    const fps = panel.ejecucion ? panel.ejecucion.fps : null;
    $("detalle").hidden = !f;
    if (!f) return;
    evidencia.mostrar({ camara, vehiculo: { track: f.track, tipo: f.tipo, t: f.t, v: f.v }, limite, fps, motivo: "" });

    const kv = (clave, valor) => `<div class="kv"><dt>${clave}</dt><dd>${valor}</dd></div>`;
    const lineas = [
      kv("ID de seguimiento", `<span class="id">#${esc(f.track)}</span>`),
      kv("Tipo", esc(nombreTipo(f.tipo))),
      kv("Hora del cruce", hora(f.t)),
    ];
    let formula = "No completó el tramo A–B (entró a la imagen ya dentro del tramo o se perdió el seguimiento), así que se contó pero no tiene velocidad.";
    if (f.v !== null) {
      const delta = f.v - limite;
      const s = segundosEnTramo(camara && camara.distancia_m, f.v);
      lineas.push(kv("Velocidad media en el tramo", `${dec1(f.v)} km/h`));
      lineas.push(kv(`Respecto al límite de ${sinCero(limite)} km/h`, delta > 0 ? `<span class="malo">${conSigno(delta)} km/h</span>` : `${conSigno(delta)} km/h`));
      if (s) {
        lineas.push(kv(`Tiempo en los ${dec1(camara.distancia_m)} m del tramo`, `≈ ${dec2(s)} s${fps ? ` · ${Math.round(s * fps)} cuadros` : ""}`));
        formula = `La velocidad es la distancia real entre las líneas A y B (${dec1(camara.distancia_m)} m) dividida entre el tiempo que el vehículo tardó en ir de una a otra, medido en cuadros de video${fps ? ` a ${sinCero(fps)} cuadros por segundo` : ""}.`;
      } else {
        formula = "La velocidad es la distancia real entre las líneas A y B dividida entre el tiempo que el vehículo tardó en ir de una a otra.";
      }
    }
    $("ficha-vehiculo").innerHTML = `<dl>${lineas.join("")}</dl><p class="formula">${formula}</p>`;
  }

  function pintarFilas() {
    const limite = panel.limite_kmh;
    if (!filas.length) {
      cuerpo.innerHTML = `<tr class="fila-vacia"><td colspan="5">${parametros.id
        ? `Ningún vehículo con el ID ${esc(parametros.id)} en esta cámara.`
        : "Ningún vehículo cumple estos filtros."}</td></tr>`;
    } else {
      cuerpo.innerHTML = filas.map((f, i) => {
        const delta = f.v === null ? null : f.v - limite;
        return `<tr data-i="${i}" tabindex="0" aria-selected="${i === elegida}">
          <td><span class="id">#${esc(f.track)}</span></td>
          <td>${esc(nombreTipo(f.tipo))}</td>
          <td>${hora(f.t)}</td>
          <td class="num">${f.v === null ? '<span class="suave">—</span>' : `${dec1(f.v)} <span class="suave">km/h</span>`}</td>
          <td class="num">${delta === null ? '<span class="suave">—</span>' : delta > 0 ? conSigno(delta) : `<span class="suave">${conSigno(delta)}</span>`}</td>
        </tr>`;
      }).join("");
    }
    $("v-rango").textContent = total ? `1–${entero(filas.length)} de ${entero(total)}` : "0 vehículos";
    const faltan = total - filas.length;
    $("v-mas").hidden = faltan <= 0;
    $("v-mas").textContent = `Cargar ${entero(Math.min(PAGINA, faltan))} más`;
  }

  async function cargar(desde) {
    const miTurno = ++turno;
    const pagina = await pedirCruces({
      camara: panel.seleccion[0], filtro: parametros.filtro, tipo: parametros.tipo,
      track: parametros.id, orden: parametros.orden, cuantos: PAGINA, desde,
    });
    if (miTurno !== turno) return;
    filas = desde ? [...filas, ...pagina.filas] : pagina.filas;
    total = pagina.total;
    if (!desde) elegida = filas.length && !telefono.matches ? 0 : -1;
    pintarFilas();
    pintarDetalle();
  }

  function pintarControles() {
    const limite = sinCero(panel.limite_kmh);
    const c = panel.filtros;
    const conCuentas = !parametros.tipo && !parametros.id;       // las cuentas valen para la vista sin mas filtros
    segmentos($("seg-filtro"), [
      { valor: "todos", texto: "Todos", ...(conCuentas ? { cuenta: entero(c.todos) } : {}) },
      { valor: "excesos", texto: "Sobre el límite", ...(conCuentas ? { cuenta: entero(c.excesos) } : {}) },
      { valor: "sin_medir", texto: "Sin medición", ...(conCuentas ? { cuenta: entero(c.sin_medir) } : {}) },
    ], parametros.filtro, (valor) => cambiar({ filtro: valor }), "Filtrar vehículos");

    const tipos = panel.tipos.filter((t) => t.total > 0);
    $("v-tipo").innerHTML = `<option value="">Todos los tipos</option>${tipos.map((t) =>
      `<option value="${esc(t.nombre)}">${esc(nombreTipo(t.nombre))}</option>`).join("")}`;
    $("v-tipo").value = tipos.some((t) => t.nombre === parametros.tipo) ? parametros.tipo : "";
    $("v-orden").value = parametros.orden;
    $("v-id").hidden = !parametros.id;
    $("v-id").textContent = `ID ${parametros.id}`;
    $("v-id").setAttribute("aria-label", `Quitar el filtro por ID ${parametros.id}`);

    $("v-resumen").innerHTML = `<b>${entero(c.todos)}</b> cruces registrados por la cámara ${esc(panel.seleccion[0])}: `
      + `<b>${entero(c.excesos)}</b> sobre el límite de ${limite} km/h y <b>${entero(c.sin_medir)}</b> sin medición de velocidad.`;
  }

  /**
   * Muestra la vista con el panel y los filtros de la direccion. Solo vuelve a pedir datos
   * si algo cambio (o si `forzar`, cuando llegan cruces nuevos).
   */
  function mostrar(nuevoPanel, nuevos, forzar = false) {
    panel = nuevoPanel;
    parametros = {
      filtro: ["todos", "excesos", "sin_medir"].includes(nuevos.filtro) ? nuevos.filtro : "todos",
      tipo: nuevos.tipo || "",
      id: /^\d+$/.test(nuevos.id || "") ? nuevos.id : "",
      orden: nuevos.orden === "velocidad" ? "velocidad" : "hora",
    };
    pintarControles();
    const nuevaFirma = JSON.stringify([panel.seleccion, parametros, panel.total, panel.ultimo_cruce]);
    if (!forzar && nuevaFirma === firma) return;
    firma = nuevaFirma;
    cargar(0).catch(() => {
      cuerpo.innerHTML = `<tr class="fila-vacia"><td colspan="5">No se pudo cargar el registro. <button class="enlace" type="button" id="v-reintentar">Reintentar</button></td></tr>`;
      $("v-reintentar").addEventListener("click", () => { firma = ""; mostrar(panel, parametros); });
    });
  }

  return { mostrar };
}
