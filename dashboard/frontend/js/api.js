// Acceso a la API del backend (solo lectura).

async function pedir(ruta, parametros = {}) {
  const consulta = new URLSearchParams();
  for (const [clave, valor] of Object.entries(parametros)) {
    if (valor !== null && valor !== undefined && valor !== "") consulta.set(clave, valor);
  }
  const respuesta = await fetch(`${ruta}?${consulta}`, { headers: { Accept: "application/json" } });
  if (!respuesta.ok) throw new Error(`El servidor respondió ${respuesta.status}`);
  return respuesta.json();
}

/** Resumen de una camara (o de todas si no se indica). El percentil 85 es la V85 de transito. */
export const pedirPanel = (camara) => pedir("/api/panel", { camaras: camara, percentil: 85 });

/** Una pagina del registro de vehiculos. */
export const pedirCruces = (parametros) => pedir("/api/cruces", parametros);

/** Direccion del cuadro del video en el instante `momento`. */
export const urlFotograma = (camara, momento) =>
  `/api/fotograma?${new URLSearchParams({ camara, ...(momento ? { t: momento } : {}) })}`;
