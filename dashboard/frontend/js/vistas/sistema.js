// Vista "Sistema": diagnostico del entorno (solo lectura). La instalacion de paquetes y de la version
// de PyTorch con CUDA la hace iniciar.py, que pregunta antes; aqui se explica el estado y se da el comando.

import { pedirSistema } from "../api.js";
import { entero, esc } from "../formato.js";

const $ = (id) => document.getElementById(id);
const chip = (clase, texto) => `<span class="chip ${clase}">${texto}</span>`;
const fila = (titulo, detalle, estado) =>
  `<div class="sis-fila"><div><span>${titulo}</span>${detalle ? `<span class="l2">${detalle}</span>` : ""}</div>${estado}</div>`;

export function crearSistema() {
  function pintar(d) {
    const faltan = d.paquetes.filter((p) => !p.ok);
    const gpu = d.gpu;
    const gpuEstado = { gpu: ["ok", "Activa"], cpu_con_gpu: ["aviso", "Sin usar"], cpu: ["", "No hay GPU NVIDIA"], desconocido: ["", "Desconocido"] }[gpu.modo] || ["", gpu.modo];

    $("sis-resumen").textContent = !faltan.length && d.python_ok
      ? (gpu.modo === "gpu" ? `Todo listo. El análisis usará la GPU (${gpu.nombre}).` : "Todo listo para analizar.")
      : "Hay cosas por resolver; mira las tarjetas de abajo.";

    const gpuTexto = {
      gpu: `<p class="sis-nota">PyTorch ve la tarjeta <b>${esc(gpu.nombre)}</b> y el análisis la usa automáticamente. Con ella, el modo «En vivo» sigue el video a velocidad normal sin perder vehículos.</p>`,
      cpu_con_gpu: `<p class="sis-nota">Tienes una <b>${esc(gpu.nombre)}</b>, pero PyTorch está instalado sin CUDA, así que el análisis corre en CPU (varias veces más lento). Cierra el panel y vuelve a ejecutar <b>python iniciar.py</b>: lo detecta y lo corrige solo (instala la versión con CUDA). O hazlo a mano:
        <code class="cmd" id="cmd-gpu">${esc(gpu.comando)}</code>
        <button class="boton contorno" id="copiar-gpu" type="button" style="margin-top:8px">Copiar comando</button></p>`,
      cpu: `<p class="sis-nota">No se detectó una GPU NVIDIA, así que el análisis corre en CPU. Funciona, pero más lento: usa el modo «Rápido, sin vista previa» para videos largos.</p>`,
    }[gpu.modo] || "";

    $("sis-rejilla").innerHTML = `
      <section class="tarjeta" aria-labelledby="s-entorno">
        <div class="sis-cab"><h2 id="s-entorno">Entorno</h2></div>
        ${fila(`Python ${esc(d.python)}`, "Se necesita la versión 3.10 o superior", d.python_ok ? chip("ok", "Correcto") : chip("mal", "Muy antiguo"))}
        ${fila("Entorno virtual", "Recomendado para no mezclar paquetes", d.entorno_virtual ? chip("ok", "Activo") : chip("", "No activo"))}
        ${fila("Base de datos", `${esc(d.base_de_datos.ruta)}`, d.base_de_datos.existe ? chip("ok", `${d.base_de_datos.mb} MB`) : chip("aviso", "Aún no existe"))}
        ${Object.entries(d.base_de_datos.camaras).map(([c, n]) => fila(`Cámara «${esc(c)}»`, "", chip("", `${entero(n)} ${n === 1 ? "cruce" : "cruces"}`))).join("")}
      </section>

      <section class="tarjeta" aria-labelledby="s-gpu">
        <div class="sis-cab"><h2 id="s-gpu">Aceleración por GPU</h2><p>Hace que el análisis sea varias veces más rápido.</p></div>
        ${fila(gpu.nombre ? esc(gpu.nombre) : "Tarjeta gráfica NVIDIA", "", chip(gpuEstado[0], gpuEstado[1]))}
        ${gpuTexto}
      </section>

      <section class="tarjeta" aria-labelledby="s-paq">
        <div class="sis-cab"><h2 id="s-paq">Paquetes de Python</h2><p>${faltan.length ? `Faltan ${faltan.length}: ejecuta python iniciar.py para instalarlos.` : "Todos instalados."}</p></div>
        ${d.paquetes.map((p) => fila(esc(p.paquete), esc(p.para), p.ok ? chip("ok", "Instalado") : chip("mal", "Falta"))).join("")}
      </section>

      <section class="tarjeta" aria-labelledby="s-mod">
        <div class="sis-cab"><h2 id="s-mod">Modelos de detección (YOLO)</h2><p>Pesos preentrenados con las clases de vehículos.</p></div>
        ${d.pesos.length ? d.pesos.map((p) => fila(esc(p.nombre), "", chip("ok", `${p.mb} MB`))).join("")
          : `<p class="sis-nota">Aún no hay pesos: se descargan solos la primera vez que se procesa (necesita internet, unos 22 MB).</p>`}
      </section>`;

    const boton = document.getElementById("copiar-gpu");
    if (boton) boton.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(gpu.comando); boton.textContent = "Copiado"; } catch { boton.textContent = "Selecciona y copia el comando de arriba"; }
    });
  }

  async function cargar() {
    $("sis-rejilla").innerHTML = `<section class="tarjeta"><p class="sis-nota" style="border:0">Comprobando el entorno…</p></section>`;
    try {
      pintar(await pedirSistema());
    } catch (error) {
      $("sis-rejilla").innerHTML = `<section class="tarjeta"><p class="sis-nota" style="border:0">${esc(error.message)}</p></section>`;
    }
  }
  $("sis-reintentar").addEventListener("click", cargar);
  return { mostrar: cargar };
}
