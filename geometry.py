"""
geometry.py
===========
Primitivas geometricas 2D compartidas por el contador de aforo y el
estimador de velocidad.

Idea central de todo el proyecto
--------------------------------
Un video NO es continuo: es una secuencia de fotogramas (frames). De un
vehiculo solo conocemos su posicion en instantes discretos (frame N, N+1, ...).
Por eso NO preguntamos "¿el vehiculo esta sobre la linea?" (casi nunca caera
exactamente encima), sino:

    "¿El SEGMENTO que une la posicion anterior con la posicion actual
     CORTA el segmento de la linea virtual?"

Esa pregunta se responde con una interseccion de segmentos, que se resuelve
con el producto cruz 2D (ver `segment_intersection`).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# Un punto es simplemente una tupla (x, y) en pixeles. Se usa un alias de tipo
# para que las firmas de las funciones sean mas legibles.
Point = Tuple[float, float]

# Tolerancia numerica: por debajo de este valor consideramos que dos vectores
# son paralelos (el producto cruz "casi cero" no permite dividir con seguridad).
_EPSILON: float = 1e-9


def cross_2d(a: Point, b: Point) -> float:
    """
    Producto cruz 2D (componente z del producto cruz 3D) entre los vectores a y b.

        a x b = a.x * b.y - a.y * b.x

    Interpretacion geometrica:
        * > 0  -> b esta a la IZQUIERDA de a (giro antihorario).
        * < 0  -> b esta a la DERECHA de a (giro horario).
        * = 0  -> a y b son paralelos (colineales).
    Su magnitud es el area del paralelogramo formado por ambos vectores.
    """
    return a[0] * b[1] - a[1] * b[0]


def sub(a: Point, b: Point) -> Point:
    """Resta de vectores a - b. Devuelve el vector que va de b hacia a."""
    return (a[0] - b[0], a[1] - b[1])


def segment_intersection(
    p_start: Point, p_end: Point, q_start: Point, q_end: Point
) -> Optional[Tuple[float, float]]:
    """
    Calcula la interseccion entre el segmento P (trayectoria del vehiculo) y el
    segmento Q (linea virtual).

    Planteamiento matematico
    ------------------------
    Parametrizamos ambos segmentos:

        P(t) = p_start + t * r      con r = p_end - p_start,  t en [0, 1]
        Q(u) = q_start + u * s      con s = q_end - q_start,  u en [0, 1]

    Se cortan cuando P(t) = Q(u). Multiplicando (con producto cruz) ambos lados
    por s y luego por r se despejan los parametros:

        t = ((q_start - p_start) x s) / (r x s)
        u = ((q_start - p_start) x r) / (r x s)

    Los segmentos se intersectan SOLO si t y u estan ambos en [0, 1]; si estan
    fuera, las rectas infinitas se cruzan pero los segmentos finitos no.

    Si (r x s) == 0 los segmentos son paralelos: no hay un unico punto de
    corte, asi que se descarta (devuelve None).

    Returns
    -------
    Optional[Tuple[float, float]]
        (t, signo) donde
          * t     = fraccion del recorrido P en la que ocurre el cruce
                    (0 = justo en p_start, 1 = justo en p_end). Es lo que
                    permite calcular el INSTANTE EXACTO del cruce entre dos
                    frames (interpolacion sub-frame).
          * signo = +1.0 / -1.0 segun el sentido del cruce, deducido del signo
                    de (r x s). Permite distinguir sentido de circulacion.
        o None si no hay cruce.
    """
    r = sub(p_end, p_start)
    s = sub(q_end, q_start)

    denominador = cross_2d(r, s)
    if abs(denominador) < _EPSILON:
        # Trayectoria paralela a la linea (o vehiculo detenido: r = 0).
        return None

    qp = sub(q_start, p_start)
    t = cross_2d(qp, s) / denominador
    u = cross_2d(qp, r) / denominador

    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t, (1.0 if denominador > 0 else -1.0)
    return None


def poligono_entre_lineas(
    linea_a: Tuple[Point, Point], linea_b: Tuple[Point, Point]
) -> List[Point]:
    """
    Cuadrilatero (la ROI) delimitado por dos lineas: A.p -> A.q -> B.q -> B.p.

    Si el usuario definio las lineas con los puntos en orden "cruzado" (p. ej. A de
    izquierda a derecha y B de derecha a izquierda) ese recorrido quedaria con
    forma de "corbatin" (lados que se cortan). Se detecta ese caso, con la misma
    interseccion de segmentos usada en todo el proyecto, y se invierte B.
    """
    a1, a2 = linea_a
    b1, b2 = linea_b
    if segment_intersection(a2, b2, b1, a1) is not None:
        b1, b2 = b2, b1
    return [a1, a2, b2, b1]


def euclidean_distance(a: Point, b: Point) -> float:
    """Distancia euclidiana entre dos puntos (teorema de Pitagoras)."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
