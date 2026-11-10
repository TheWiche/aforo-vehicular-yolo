/* Escalas y marcas de eje: "ticks bonitos" (1, 2, 5, 10...) y marcas de tiempo redondas. */

/** Escala lineal: dominio [d0, d1] -> rango [r0, r1]. */
export const lineal = (d0, d1, r0, r1) => {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (v) => r0 + (v - d0) * k;
};

/** Paso "bonito" >= paso crudo, de la familia 1, 2, 2.5, 5, 10 x 10^n. */
const pasoBonito = (crudo) => {
  const exp = Math.pow(10, Math.floor(Math.log10(crudo)));
  const f = crudo / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
};

/** Marcas numericas redondas que cubren [min, max] (la ultima supera al maximo). */
export function ticksNumericos(min, max, cuantas = 5) {
  if (max <= min) max = min + 1;
  const paso = pasoBonito((max - min) / (cuantas - 1));
  const inicio = Math.floor(min / paso) * paso;
  const fin = Math.ceil(max / paso) * paso;
  const marcas = [];
  for (let v = inicio; v <= fin + paso / 1e6; v += paso) marcas.push(Math.round(v * 1e6) / 1e6);
  return marcas;
}

const PASOS_TIEMPO_S = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400];

/** Marcas de tiempo (ms) en multiplos redondos de un paso, entre t0 y t1 (ms), de 3 a `max`. */
export function ticksTiempo(t0, t1, max = 6) {
  const span = Math.max((t1 - t0) / 1000, 1);
  const paso = PASOS_TIEMPO_S.find((p) => span / p <= max) ?? 86400;
  const desfase = new Date(t0).getTimezoneOffset() * 60000;           // alinear a la hora LOCAL
  const primero = Math.ceil((t0 - desfase) / (paso * 1000)) * paso * 1000 + desfase;
  const marcas = [];
  for (let t = primero; t <= t1; t += paso * 1000) marcas.push(t);
  return { marcas, paso };
}

const dos = (n) => String(n).padStart(2, "0");

/** HH:MM:SS (o HH:MM si el paso es de al menos un minuto). */
export function etiquetaTiempo(ms, paso) {
  const d = new Date(ms);
  const hm = `${dos(d.getHours())}:${dos(d.getMinutes())}`;
  return paso >= 60 ? hm : `${hm}:${dos(d.getSeconds())}`;
}
