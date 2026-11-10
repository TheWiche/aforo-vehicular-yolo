// Formato de cifras, horas y nombres. Un solo lugar para que toda la pantalla escriba igual.

const LOCAL = "es-CO";
const fEntero = new Intl.NumberFormat(LOCAL, { maximumFractionDigits: 0 });
const fDec1 = new Intl.NumberFormat(LOCAL, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fDec2 = new Intl.NumberFormat(LOCAL, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const entero = (n) => fEntero.format(n);
export const dec1 = (v) => fDec1.format(v);
export const dec2 = (v) => fDec2.format(v);

/** Diferencia con signo y un decimal: +7,1 / −2,4 / 0,0 (con el signo menos tipografico). */
export const conSigno = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + dec1(Math.abs(v));

/** '2026-11-10 14:07:31.018' -> Date en hora local. */
export const fecha = (texto) => new Date(String(texto).replace(" ", "T"));

const dos = (n) => String(n).padStart(2, "0");
/** Hora del dia HH:MM o HH:MM:SS a partir de un Date o del texto de la base. */
export function hora(valor, conSegundos = true) {
  const d = valor instanceof Date ? valor : fecha(valor);
  return `${dos(d.getHours())}:${dos(d.getMinutes())}${conSegundos ? ":" + dos(d.getSeconds()) : ""}`;
}

/** 1070 s -> '17 min 50 s'; 21 s -> '21 s'. */
export function duracion(segundos) {
  const s = Math.round(segundos);
  const min = Math.floor(s / 60);
  return min ? `${entero(min)} min${s % 60 ? ` ${s % 60} s` : ""}` : `${s} s`;
}

const NOMBRES = { Camion: "Camión" };
const CON_ARTICULO = { Moto: "una moto", Auto: "un auto", Bus: "un bus", Camion: "un camión" };
export const nombreTipo = (tipo) => NOMBRES[tipo] || tipo;
export const tipoConArticulo = (tipo) => CON_ARTICULO[tipo] || `un vehículo tipo ${tipo}`;

/** Todo texto que viene de la base se escapa antes de entrar en innerHTML. */
export const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** Tiempo que tarda un vehiculo en recorrer el tramo: distancia (m) / velocidad (km/h -> m/s). */
export const segundosEnTramo = (distanciaM, kmh) => (distanciaM && kmh ? distanciaM / (kmh / 3.6) : null);
