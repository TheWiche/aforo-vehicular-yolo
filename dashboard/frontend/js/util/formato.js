/* Utilidades de formato: escapado de HTML, fechas de SQLite, numeros y plurales. */

const ENTIDADES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escapa texto que viene de la base de datos antes de insertarlo como HTML. */
export const esc = (valor) => String(valor ?? "").replace(/[&<>"']/g, (c) => ENTIDADES[c]);

/** "2026-11-09 08:00:05.000" (hora local sin zona) -> Date. */
export const fecha = (iso) => new Date(String(iso).replace(" ", "T"));

const dos = (n) => String(n).padStart(2, "0");

/** HH:MM:SS */
export const hora = (iso) => {
  const d = fecha(iso);
  return `${dos(d.getHours())}:${dos(d.getMinutes())}:${dos(d.getSeconds())}`;
};

/** Numero con decimales fijos y coma/punto segun el navegador; "-" si no hay valor. */
export const numero = (v, decimales = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "-" : Number(v).toFixed(decimales);

export const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

/** Quita los milisegundos de un instante de SQLite para mostrarlo. */
export const sinMilis = (iso) => String(iso ?? "").slice(0, 19);
