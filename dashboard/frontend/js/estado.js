/* Estado de la pantalla (filtros) y su persistencia. El navegador puede negar localStorage
   (modo privado, datos bloqueados): todo acceso va en try/catch y la pagina funciona sin el. */

const CLAVE = "aforo-vial/v1";

const porDefecto = () => ({ camaras: null, percentil: 90, auto: false });

export function cargarEstado() {
  try {
    return { ...porDefecto(), ...JSON.parse(localStorage.getItem(CLAVE) ?? "{}") };
  } catch {
    return porDefecto();
  }
}

export function guardarEstado(estado) {
  try {
    localStorage.setItem(CLAVE, JSON.stringify(estado));
  } catch {
    /* sin persistencia: no pasa nada */
  }
}

/** Alterna una camara en la seleccion. `null` significa "todas". */
export function alternarCamara(seleccion, camara, todas) {
  const actuales = seleccion ?? todas;
  if (seleccion === null) return [camara];                       // desde "todas", elegir una la aisla
  const nuevas = actuales.includes(camara) ? actuales.filter((c) => c !== camara) : [...actuales, camara];
  return nuevas.length === 0 || nuevas.length === todas.length ? null : nuevas;
}
