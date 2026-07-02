# motor_sad/levels.py
"""
Motor de niveles (port fiel de data/levels_calculator.py, solo stdlib).

Nivel = P + G + 1, sobre ventana móvil de 20 partidos finalizados:
    P = promedio de puntos (3/1/0) en los últimos 20
    G = Σ(dif. goles últimos 5) / Σ(goles totales últimos 5)   (0 si no hay goles)

Reglas:
    - < 20 partidos  → nivel por defecto 0.5 en todos.
    - Partido nº 20  → primer nivel real, asignado retroactivamente a los 20 primeros.
    - Partido 21+    → cada partido recibe su propio nivel.
    - Recalcular un equipo = borrar sus filas y regenerar la historia completa
      (la ventana móvil hace inviable el parcheo parcial).
"""
import logging
from typing import Dict, List, Optional, Set

from .db import connect, db_path, SAD_DB, LEVELS_DB, LEVELS_SCHEMA, FINISHED_STATUS, DEFAULT_LEVEL

logger = logging.getLogger(__name__)

WINDOW = 20          # ventana del componente de puntos
GOALS_WINDOW = 5     # ventana del componente de goles
LEVEL_CONSTANT = 1   # constante de ajuste para que el nivel sea positivo


class LevelsEngine:
    def __init__(self, base_dir: str = '.',
                 sad_db_path: Optional[str] = None,
                 levels_db_path: Optional[str] = None):
        self.sad = connect(sad_db_path or db_path(base_dir, SAD_DB))
        self.levels = connect(levels_db_path or db_path(base_dir, LEVELS_DB))
        self.levels.executescript(LEVELS_SCHEMA)
        self.levels.commit()

    def close(self):
        self.sad.close()
        self.levels.close()

    # ------------------------------------------------------------------
    # Lectura de sad.db
    # ------------------------------------------------------------------
    def _team_matches(self, team_id: int) -> List[Dict]:
        """Partidos terminados del equipo, procesados y ordenados por fecha."""
        rows = self.sad.execute(
            """
            SELECT id, date, home_team_id, goals_home, goals_away
            FROM fixtures
            WHERE (home_team_id = ? OR away_team_id = ?)
              AND status_long = ?
            ORDER BY date
            """,
            (team_id, team_id, FINISHED_STATUS),
        ).fetchall()

        processed = []
        for fid, date, home_id, gh, ga in rows:
            if gh is None or ga is None:
                continue
            is_home = home_id == team_id
            gf, gc = (gh, ga) if is_home else (ga, gh)
            points = 3 if gf > gc else (1 if gf == gc else 0)
            processed.append({
                'fixture_id': fid,
                'date': date,
                'goals_for': gf,
                'goals_against': gc,
                'goal_difference': gf - gc,
                'points': points,
            })
        return processed

    # ------------------------------------------------------------------
    # Cálculo
    # ------------------------------------------------------------------
    def compute_team_levels(self, team_id: int) -> List[Dict]:
        """Historia completa de niveles de un equipo: [{fixture_id, date, level}]."""
        matches = self._team_matches(team_id)
        history = []

        if len(matches) < WINDOW:
            return [
                {'fixture_id': m['fixture_id'], 'date': m['date'], 'level': DEFAULT_LEVEL}
                for m in matches
            ]

        for i in range(WINDOW - 1, len(matches)):
            window = matches[i - (WINDOW - 1): i + 1]

            points_component = sum(m['points'] for m in window) / WINDOW

            last5 = window[-GOALS_WINDOW:]
            total_goals = sum(m['goals_for'] + m['goals_against'] for m in last5)
            goals_component = (
                sum(m['goal_difference'] for m in last5) / total_goals
                if total_goals > 0 else 0
            )

            level = points_component + goals_component + LEVEL_CONSTANT

            if i == WINDOW - 1:
                # Regla retroactiva: el primer nivel real cubre los 20 primeros partidos
                for j in range(WINDOW):
                    history.append({
                        'fixture_id': matches[j]['fixture_id'],
                        'date': matches[j]['date'],
                        'level': level,
                    })
            else:
                history.append({
                    'fixture_id': matches[i]['fixture_id'],
                    'date': matches[i]['date'],
                    'level': level,
                })

        return history

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def update_team(self, team_id: int) -> int:
        """Borra y regenera todos los niveles de un equipo. Devuelve filas insertadas."""
        history = self.compute_team_levels(team_id)
        cur = self.levels.cursor()
        try:
            cur.execute("DELETE FROM team_levels WHERE team_id = ?", (team_id,))
            cur.executemany(
                "INSERT INTO team_levels (team_id, fixture_id, date, level) VALUES (?,?,?,?)",
                [(team_id, h['fixture_id'], h['date'], h['level']) for h in history],
            )
            self.levels.commit()
            return len(history)
        except Exception:
            self.levels.rollback()
            raise

    # ------------------------------------------------------------------
    # Sincronización incremental
    # ------------------------------------------------------------------
    def detect_changes(self) -> Set[int]:
        """Equipos afectados: participantes de fixtures terminados aún no procesados."""
        processed = {
            fid for (fid,) in self.levels.execute(
                "SELECT DISTINCT fixture_id FROM team_levels"
            )
        }
        affected: Set[int] = set()
        for fid, home_id, away_id in self.sad.execute(
            "SELECT id, home_team_id, away_team_id FROM fixtures WHERE status_long = ?",
            (FINISHED_STATUS,),
        ):
            if fid not in processed:
                affected.add(home_id)
                affected.add(away_id)
        return affected

    def calculate_missing_levels(self) -> Dict[str, int]:
        """Recalcula solo los equipos con fixtures nuevos."""
        teams = self.detect_changes()
        inserted = 0
        for team_id in teams:
            try:
                inserted += self.update_team(team_id)
            except Exception as e:
                logger.error("Error actualizando niveles del equipo %s: %s", team_id, e)
        return {'teams_updated': len(teams), 'records_inserted': inserted}

    def force_recalculate_all(self) -> Dict[str, int]:
        """Reconstruye levels.db desde cero para todos los equipos."""
        self.levels.execute("DELETE FROM team_levels")
        self.levels.commit()
        team_ids = [tid for (tid,) in self.sad.execute("SELECT id FROM teams")]
        inserted = 0
        for team_id in team_ids:
            inserted += self.update_team(team_id)
        return {'teams_processed': len(team_ids), 'records_inserted': inserted}

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------
    def get_team_level_at_date(self, team_id: int, date: str) -> float:
        """Nivel más reciente con date <= fecha; 0.5 si no hay datos."""
        row = self.levels.execute(
            """
            SELECT level FROM team_levels
            WHERE team_id = ? AND date <= ?
            ORDER BY date DESC LIMIT 1
            """,
            (team_id, date),
        ).fetchone()
        return row[0] if row else DEFAULT_LEVEL
