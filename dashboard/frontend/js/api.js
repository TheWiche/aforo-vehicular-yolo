/* Acceso a la API del backend. Convierte los fallos de red en un Error con mensaje legible. */

export async function obtenerPanel({ camaras, percentil }) {
  const parametros = new URLSearchParams({ percentil: String(percentil) });
  if (camaras && camaras.length) parametros.set("camaras", camaras.join(","));
  let respuesta;
  try {
    respuesta = await fetch(`/api/panel?${parametros}`, { headers: { Accept: "application/json" } });
  } catch {
    throw new Error("No se pudo contactar con el servidor del dashboard.");
  }
  if (!respuesta.ok) throw new Error(`El servidor respondió ${respuesta.status}.`);
  return respuesta.json();
}
