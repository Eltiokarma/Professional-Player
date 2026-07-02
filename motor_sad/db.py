# motor_sad/db.py
"""
Organización de las bases de datos del motor SAD (versión portable, solo stdlib).

Cuatro SQLite encadenadas en pipeline unidireccional:

    sad.db ──► levels.db ──► constants.db ──► discreto.db

Todas las conexiones activan WAL + busy_timeout, igual que el proyecto original
(data/database_manager.py), para poder convivir con una UI que lee en paralelo.
"""
import os
import sqlite3

FINISHED_STATUS = 'Match Finished'

# Nivel por defecto cuando un equipo aún no tiene 20 partidos (levels.db)
DEFAULT_LEVEL = 0.5
# Fallback de nivel del RIVAL al calcular constantes (¡deliberadamente 1.0, no 0.5!)
CONSTANTS_LEVEL_FALLBACK = 1.0
# Factor que premia/castiga más los resultados de visitante
VISITOR_MULTIPLIER = 1.4

SAD_DB = 'sad.db'
LEVELS_DB = 'levels.db'
CONSTANTS_DB = 'constants.db'
DISCRETO_DB = 'discreto.db'


def connect(path: str) -> sqlite3.Connection:
    """Conexión SQLite con los PRAGMA estándar del SAD."""
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def db_path(base_dir: str, name: str) -> str:
    return os.path.join(base_dir, name)


# ----------------------------------------------------------------------
# DDL
# ----------------------------------------------------------------------

# Esquema MÍNIMO de sad.db que el motor necesita (la fuente real puede tener
# más columnas; estas son las que consume el pipeline).
SAD_SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id      INTEGER PRIMARY KEY,
    name    TEXT,
    country TEXT
);
CREATE TABLE IF NOT EXISTS fixtures (
    id            INTEGER PRIMARY KEY,
    date          DATETIME,
    status_long   TEXT,
    status_short  TEXT,
    league_id     INTEGER,
    league_season INTEGER,
    home_team_id  INTEGER REFERENCES teams(id),
    away_team_id  INTEGER REFERENCES teams(id),
    goals_home    INTEGER,
    goals_away    INTEGER
);
CREATE INDEX IF NOT EXISTS ix_fixtures_home_status ON fixtures(home_team_id, status_long);
CREATE INDEX IF NOT EXISTS ix_fixtures_away_status ON fixtures(away_team_id, status_long);
CREATE INDEX IF NOT EXISTS ix_fixtures_date ON fixtures(date);
"""

LEVELS_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_levels (
    id         INTEGER PRIMARY KEY,
    team_id    INTEGER NOT NULL,
    fixture_id INTEGER NOT NULL,
    date       DATETIME NOT NULL,
    level      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_levels_team_date ON team_levels(team_id, date);
CREATE INDEX IF NOT EXISTS ix_levels_fixture ON team_levels(fixture_id);
"""

CONSTANTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS constants (
    id INTEGER PRIMARY KEY,
    team_id    INTEGER NOT NULL,
    fixture_id INTEGER NOT NULL,
    date       DATETIME NOT NULL,
    q_local REAL, q_visita REAL, q_negativo REAL,
    q_goles_anotado REAL, q_goles_recibido REAL,
    q_goles_local_anotado REAL, q_goles_local_recibido REAL,
    q_goles_visita_anotado REAL, q_goles_visita_recibido REAL,
    k_positivo REAL, k_negativo REAL,
    k_positivo_local REAL, k_negativo_local REAL,
    k_positivo_visita REAL, k_negativo_visita REAL,
    k_goles_anotado REAL, k_goles_recibido REAL,
    k_goles_local_anotado REAL, k_goles_local_recibido REAL,
    k_goles_visita_anotado REAL, k_goles_visita_recibido REAL
);
CREATE INDEX IF NOT EXISTS ix_constants_team_date    ON constants(team_id, date);
CREATE INDEX IF NOT EXISTS ix_constants_fixture_team ON constants(fixture_id, team_id);
"""

DISCRETO_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_matches (
    id INTEGER PRIMARY KEY,
    fecha DATETIME NOT NULL,
    fixture_id INTEGER NOT NULL,
    equipo_id INTEGER NOT NULL,
    equipo_nombre TEXT NOT NULL,
    rival_id INTEGER NOT NULL,
    rival_nombre TEXT NOT NULL,
    condicion TEXT,
    status_long TEXT,
    league_id INTEGER,
    league_season TEXT,
    goals_home INTEGER,
    goals_away INTEGER,
    nivel_equipo INTEGER,
    nivel_rival  INTEGER,
    k REAL, k_local REAL, k_visita REAL,
    k_goles_anotado REAL, k_goles_recibido REAL,
    k_goles_local_anotado REAL, k_goles_local_recibido REAL,
    k_goles_visita_anotado REAL, k_goles_visita_recibido REAL,
    processed_at DATETIME,
    UNIQUE(fixture_id, equipo_id)
);
CREATE INDEX IF NOT EXISTS idx_fecha_equipo ON processed_matches(fecha, equipo_id);
CREATE INDEX IF NOT EXISTS idx_status  ON processed_matches(status_long);
CREATE INDEX IF NOT EXISTS idx_fixture ON processed_matches(fixture_id);
CREATE INDEX IF NOT EXISTS idx_league  ON processed_matches(league_id);
"""


def init_all(base_dir: str) -> None:
    """Crea (si no existen) los esquemas de las cuatro bases."""
    for name, schema in (
        (SAD_DB, SAD_SCHEMA),
        (LEVELS_DB, LEVELS_SCHEMA),
        (CONSTANTS_DB, CONSTANTS_SCHEMA),
        (DISCRETO_DB, DISCRETO_SCHEMA),
    ):
        conn = connect(db_path(base_dir, name))
        try:
            conn.executescript(schema)
            conn.commit()
        finally:
            conn.close()
