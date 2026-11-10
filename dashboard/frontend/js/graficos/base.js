/* Montaje comun de los graficos SVG: se redibujan al cambiar el ancho del contenedor. */

/**
 * Dibuja un grafico dentro de `contenedor`. `dibujar(ancho)` devuelve el SVG como texto.
 * Se vuelve a dibujar cada vez que cambia el ancho disponible (ventana, rejilla responsiva).
 */
export function montar(contenedor, dibujar) {
  contenedor.classList.add("grafico");
  const pintar = () => {
    const ancho = Math.floor(contenedor.clientWidth);
    if (ancho > 0) contenedor.innerHTML = dibujar(ancho);
  };
  pintar();
  new ResizeObserver(pintar).observe(contenedor);
}

/** Cuadricula horizontal con las etiquetas del eje Y (sin linea de eje, 4-5 marcas tenues). */
export function rejillaY(marcas, escalaY, izq, der, formato = (v) => v) {
  return marcas
    .map((v) => {
      const y = escalaY(v).toFixed(1);
      return `<line class="g-rejilla" x1="${izq}" x2="${der}" y1="${y}" y2="${y}"/>` +
        `<text x="${izq - 8}" y="${Number(y) + 4}" text-anchor="end">${formato(v)}</text>`;
    })
    .join("");
}
