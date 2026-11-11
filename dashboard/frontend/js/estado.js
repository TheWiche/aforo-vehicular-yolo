// Preferencias pequenas que se recuerdan en el navegador (el video elegido, la camara, el refresco).
// El almacenamiento puede fallar (modo privado, datos bloqueados): todo va en try/catch y la
// interfaz funciona igual sin el.

const leer = (clave) => { try { return localStorage.getItem(clave); } catch { return null; } };
const escribir = (clave, valor) => { try { localStorage.setItem(clave, valor); } catch { /* sin almacenamiento */ } };

export const guardado = { leer, escribir };

/** Video con el que se trabajo por ultima vez (para abrir Calibrar y Procesar ya posicionados). */
export const videoRecordado = () => leer("aforo.video");
export const recordarVideo = (nombre) => { if (nombre) escribir("aforo.video", nombre); };
