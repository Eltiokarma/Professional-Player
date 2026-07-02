# motor_sad/discretizer.py
"""
Fusión de constantes + discretización de niveles (port de data/discretizer_db.py,
sin pandas ni scikit-learn).

Genera discreto.db/processed_matches: la tabla que consume el ML.

- Fusión:  k = k_positivo + k_negativo (NULL -> 0). Ídem k_local y k_visita.
  Como los acumuladores se resetean mutuamente, la suma neta refleja el momentum
  sin ambigüedad (k>0 racha, k=0 reset, k<0 mala racha).
- Nivel discretizado 0-9: discretizador uniforme de 10 bins calibrado sobre
  TODOS los niveles históricos (equivalente exacto de
  sklearn KBinsDiscretizer(n_bins=10, encode='ordinal', strategy='uniform')).
- Inserción idempotente: UNIQUE(fixture_id, equipo_id) + ON CONFLICT DO NOTHING.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .db import (
    connect, db_path, SAD_DB, LEVELS_DB, CONSTANTS_DB, DISCRETO_DB,
    DISCRETO_SCHEMA, FINISHED_STATUS, DEFAULT_LEVEL,
)

logger = logging.getLogger(__name__)

N_BINS = 10

# Bins fijos de la Ley del Marcador v6 (umbrales calibrados empíricamente).
# bin i cubre [FIXED_BIN_EDGES[i-1], FIXED_BIN_EDGES[i]); bin 0 = sin datos.
FIXED_BIN_EDGES = [0.6, 1.3, 1.6, 1.9, 2.1, 2.35, 2.55, 2.85, 3.2]
FIXED_BIN_LABELS = [
    'Sin datos', 'Muy débil', 'Débil', 'Regular bajo', 'Promedio bajo',
    'Promedio', 'Promedio alto', 'Fuerte', 'Muy fuerte', 'Élite',
]


def fixed_bin(level: float) -> int:
    """Discretización con los 10 bins fijos del Marcador v6."""
    for i, edge in enumerate(FIXED_BIN_EDGES):
        if level < edge:
            return i
    return 9


def linear_fallback_bin(level: float) -> int:
    """Fallback lineal documentado: (nivel - 0.5) / 3.0 * 9, recortado a [0, 9]."""
    b = int((level - 0.5) / (3.5 - 0.5) * 9)
    return max(0, min(9, b))


class UniformDiscretizer:
    """Equivalente stdlib de KBinsDiscretizer(strategy='uniform', encode='ordinal')."""

    def __init__(self, n_bins: int = N_BINS):
        self.n_bins = n_bins
        self.min_: Optional[float] = None
        self.max_: Optional[float] = None

    def fit(self, values: List[float]) -> 'UniformDiscretizer':
        if not values:
            raise ValueError("No hay niveles para calibrar el discretizador")
        self.min_, self.max_ = min(values), max(values)
        return self

    def transform_one(self, x: float) -> int:
        if self.min_ is None:
            raise RuntimeError("Discretizador no calibrado (llamar fit primero)")
        width = self.max_ - self.min_
        if width <= 0:
            return 0
        b = int((x - self.min_) / width * self.n_bins)
        return max(0, min(self.n_bins - 1, b))


def fuse(pos: Optional[float], neg: Optional[float]) -> float:
    """k fusionada = k_positivo + k_negativo, tratando NULL como 0."""
    return (pos or 0.0) + (neg or 0.0)


class DiscreteProcessor:
    def __init__(self, base_dir: str = '.',
                 sad_db_path: Optional[str] = None,
                 levels_db_path: Optional[str] = None,
                 constants_db_path: Optional[str] = None,
                 discreto_db_path: Optional[str] = None):
        self.sad = connect(sad_db_path or db_path(base_dir, SAD_DB))
        self.levels = connect(levels_db_path or db_path(base_dir, LEVELS_DB))
        self.const = connect(constants_db_path or db_path(base_dir, CONSTANTS_DB))
        self.discreto = connect(discreto_db_path or db_path(base_dir, DISCRETO_DB))
        self.discreto.executescript(DISCRETO_SCHEMA)
        self.discreto.commit()
        self.discretizer: Optional[UniformDiscretizer] = None

    def close(self):
        for conn in (self.sad, self.levels, self.const, self.discreto):
            conn.close()

    # ------------------------------------------------------------------
    def create_discretizer(self):
        if self.discretizer is None:
            values = [v for (v,) in self.levels.execute(
                "SELECT level FROM team_levels WHERE level IS NOT NULL")]
            self.discretizer = UniformDiscretizer().fit(values)
            logger.info("Discretizador calibrado: min=%.3f max=%.3f",
                        self.discretizer.min_, self.discretizer.max_)

    def _level_for(self, team_id: int, fixture_id: int, fecha: str) -> float:
        """Nivel exacto por fixture; si no, último <= fecha; si no, 0.5."""
        row = self.levels.execute(
            "SELECT level FROM team_levels WHERE team_id = ? AND fixture_id = ? LIMIT 1",
            (team_id, fixture_id),
        ).fetchone()
        if row:
            return float(row[0])
        row = self.levels.execute(
            """
            SELECT level FROM team_levels
            WHERE team_id = ? AND date <= ?
            ORDER BY date DESC LIMIT 1
            """,
            (team_id, fecha),
        ).fetchone()
        return float(row[0]) if row else DEFAULT_LEVEL

    # ------------------------------------------------------------------
    def process_team(self, team_id: int, team_name: str) -> int:
        matches = self.sad.execute(
            """
            SELECT f.id, f.date, f.league_id, f.league_season,
                   f.goals_home, f.goals_away, f.status_long,
                   CASE WHEN f.home_team_id = :tid THEN f.away_team_id ELSE f.home_team_id END,
                   CASE WHEN f.home_team_id = :tid THEN at.name ELSE ht.name END,
                   CASE WHEN f.home_team_id = :tid THEN 'Local' ELSE 'Visita' END
            FROM fixtures f
            JOIN teams ht ON f.home_team_id = ht.id
            JOIN teams at ON f.away_team_id = at.id
            WHERE (f.home_team_id = :tid OR f.away_team_id = :tid)
              AND f.status_long = :status
            """,
            {'tid': team_id, 'status': FINISHED_STATUS},
        ).fetchall()
        if not matches:
            return 0

        fixture_ids = [m[0] for m in matches]
        ph = ",".join("?" * len(fixture_ids))
        constants = {
            row[0]: row for row in self.const.execute(
                f"""
                SELECT fixture_id,
                       k_positivo, k_negativo,
                       k_positivo_local, k_negativo_local,
                       k_positivo_visita, k_negativo_visita,
                       k_goles_anotado, k_goles_recibido,
                       k_goles_local_anotado, k_goles_local_recibido,
                       k_goles_visita_anotado, k_goles_visita_recibido
                FROM constants
                WHERE team_id = ? AND fixture_id IN ({ph})
                """,
                [team_id] + fixture_ids,
            )
        }

        self.create_discretizer()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        rows = []
        for (fid, fecha, league_id, league_season, gh, ga, status,
             rival_id, rival_nombre, condicion) in matches:
            c = constants.get(fid)
            nivel_eq = self._level_for(team_id, fid, fecha)
            nivel_rv = self._level_for(rival_id, fid, fecha)
            rows.append((
                fecha, fid, team_id, team_name, rival_id, rival_nombre,
                condicion, status, league_id,
                str(league_season) if league_season is not None else '',
                gh, ga,
                self.discretizer.transform_one(nivel_eq),
                self.discretizer.transform_one(nivel_rv),
                fuse(c[1], c[2]) if c else 0.0,        # k
                fuse(c[3], c[4]) if c else 0.0,        # k_local
                fuse(c[5], c[6]) if c else 0.0,        # k_visita
                (c[7] or 0.0) if c else 0.0,           # k_goles_anotado
                (c[8] or 0.0) if c else 0.0,           # k_goles_recibido
                (c[9] or 0.0) if c else 0.0,
                (c[10] or 0.0) if c else 0.0,
                (c[11] or 0.0) if c else 0.0,
                (c[12] or 0.0) if c else 0.0,
                now,
            ))

        self.discreto.executemany(
            """
            INSERT INTO processed_matches (
                fecha, fixture_id, equipo_id, equipo_nombre, rival_id, rival_nombre,
                condicion, status_long, league_id, league_season, goals_home, goals_away,
                nivel_equipo, nivel_rival, k, k_local, k_visita,
                k_goles_anotado, k_goles_recibido,
                k_goles_local_anotado, k_goles_local_recibido,
                k_goles_visita_anotado, k_goles_visita_recibido, processed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fixture_id, equipo_id) DO NOTHING
            """,
            rows,
        )
        self.discreto.commit()
        return len(rows)

    def process_all_teams(self) -> int:
        self.create_discretizer()
        teams = self.sad.execute(
            """
            SELECT DISTINCT t.id, t.name FROM teams t
            WHERE EXISTS (
                SELECT 1 FROM fixtures f
                WHERE (f.home_team_id = t.id OR f.away_team_id = t.id)
                  AND f.status_long = ?
            )
            ORDER BY t.name
            """,
            (FINISHED_STATUS,),
        ).fetchall()

        total = 0
        for team_id, name in teams:
            try:
                total += self.process_team(team_id, name)
            except Exception as e:
                logger.error("Error procesando equipo %s: %s", name, e)
        logger.info("Procesamiento discreto completado: %d registros", total)
        return total
