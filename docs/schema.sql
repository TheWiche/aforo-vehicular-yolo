-- Esquema relacional SQLite (generado desde src/aforo/persistencia/db.py)
-- Modo recomendado: PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS cruces (
    id             INTEGER PRIMARY KEY,
    track_id       INTEGER,
    tipo           TEXT,
    momento        TIMESTAMP,
    velocidad_kmh  REAL,
    camara         TEXT
);
CREATE INDEX IF NOT EXISTS idx_cruces_camara_momento ON cruces (camara, momento);

CREATE TABLE IF NOT EXISTS alertas (
    id           INTEGER PRIMARY KEY,
    camara       TEXT      NOT NULL,
    momento      TIMESTAMP NOT NULL,
    tipo         TEXT      NOT NULL,     -- EXCESO_VELOCIDAD | TRAFICO_DETENIDO
    track_id     INTEGER,                -- vehiculo implicado (NULL si la alerta es de la via)
    valor        REAL,                   -- velocidad medida (km/h) o vehiculos detenidos
    umbral       REAL,                   -- limite que se supero
    descripcion  TEXT
);
CREATE INDEX IF NOT EXISTS idx_alertas_camara_momento ON alertas (camara, momento);

CREATE TABLE IF NOT EXISTS lecturas_trafico (
    id                 INTEGER PRIMARY KEY,
    camara             TEXT      NOT NULL,
    momento            TIMESTAMP NOT NULL,
    vehiculos_roi      REAL,             -- promedio de vehiculos dentro de la ROI en el intervalo
    ratio_movimiento   REAL,             -- fraccion (0..1) de pixeles de la ROI en movimiento (promedio)
    estado             TEXT              -- LIBRE | FLUIDO | DETENIDO al cierre del intervalo
);
CREATE INDEX IF NOT EXISTS idx_lecturas_camara_momento ON lecturas_trafico (camara, momento);

CREATE TABLE IF NOT EXISTS ejecuciones (
    id            INTEGER PRIMARY KEY,
    camara        TEXT      NOT NULL,
    video         TEXT      NOT NULL,
    inicio_video  TIMESTAMP NOT NULL,   -- hora real asignada al primer frame
    fps           REAL,
    frames        INTEGER,
    procesado_en  TIMESTAMP NOT NULL    -- cuando se corrio aforo procesar
);

CREATE TABLE IF NOT EXISTS metricas (
    id            INTEGER PRIMARY KEY,
    camara        TEXT      NOT NULL,
    evaluado_en   TIMESTAMP NOT NULL,
    metrica       TEXT      NOT NULL,     -- p. ej. precision, recall, f1, mae_velocidad_kmh
    valor         REAL,
    detalle       TEXT
);

CREATE VIEW IF NOT EXISTS v_aforo_por_minuto AS
SELECT camara,
       strftime('%Y-%m-%d %H:%M', momento) AS minuto,
       tipo,
       COUNT(*)                            AS vehiculos,
       ROUND(AVG(velocidad_kmh), 1)        AS velocidad_promedio_kmh
FROM cruces
GROUP BY camara, minuto, tipo;
