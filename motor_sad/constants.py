# motor_sad/constants.py
"""
Motor de constantes K (port fiel de utils/constants_calculator.py, solo stdlib).

Dos pasos por partido, en orden cronológico estricto:

1. Valores instantáneos q*  (impacto del resultado ponderado por nivel del rival):
       dif = |gf - ga| ;  res = +1 / 0 / -1
       q_local    = dif * res * nivel          (solo LOCAL, si no NULL)
       q_visita   = 1.4 * dif * res * nivel    (solo VISITA, si no NULL)
       q_negativo = dif * res * nivel          (solo derrota, si no 0)
       q_goles_anotado  = +gf * nivel ;  q_goles_recibido = -ga * nivel
       (+ variantes local/visita, NULL fuera de su condición)

2. Acumuladores k* (rachas con reseteo): suman mientras el signo se mantiene,
   se resetean a 0 al cambiar. Las variantes local/visita solo se actualizan en
   partidos de su condición (conservan valor en los demás). k_goles_recibido
   acumula el valor ABSOLUTO.

El nivel del rival es el CONTINUO de levels.db (no el discretizado), con
fallback 1.0 si el rival no tiene registros.
"""
import bisect
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from .db import (
    connect, db_path, SAD_DB, LEVELS_DB, CONSTANTS_DB, CONSTANTS_SCHEMA,
    FINISHED_STATUS, CONSTANTS_LEVEL_FALLBACK, VISITOR_MULTIPLIER,
)

logger = logging.getLogger(__name__)

K_FIELDS = [
    'k_positivo', 'k_negativo',
    'k_positivo_local', 'k_negativo_local',
    'k_positivo_visita', 'k_negativo_visita',
    'k_goles_anotado', 'k_goles_recibido',
    'k_goles_local_anotado', 'k_goles_local_recibido',
    'k_goles_visita_anotado', 'k_goles_visita_recibido',
]

Q_FIELDS = [
    'q_local', 'q_visita', 'q_negativo',
    'q_goles_anotado', 'q_goles_recibido',
    'q_goles_local_anotado', 'q_goles_local_recibido',
    'q_goles_visita_anotado', 'q_goles_visita_recibido',
]

ALL_FIELDS = ['team_id', 'fixture_id', 'date'] + Q_FIELDS + K_FIELDS


class ConstantsEngine:
    def __init__(self, base_dir: str = '.',
                 sad_db_path: Optional[str] = None,
                 levels_db_path: Optional[str] = None,
                 constants_db_path: Optional[str] = None):
        self.sad = connect(sad_db_path or db_path(base_dir, SAD_DB))
        self.levels = connect(levels_db_path or db_path(base_dir, LEVELS_DB))
        self.const = connect(constants_db_path or db_path(base_dir, CONSTANTS_DB))
        self.const.executescript(CONSTANTS_SCHEMA)
        self.const.commit()

        # Cache de niveles: {team_id: ([dates], [levels])} ordenado por fecha.
        # 1 query masivo + bisect elimina ~100K lookups individuales.
        self._levels_cache: Dict[int, tuple] = {}
        self._cache_loaded = False

    def close(self):
        self.sad.close()
        self.levels.close()
        self.const.close()

    # ------------------------------------------------------------------
    # Cache de niveles
    # ------------------------------------------------------------------
    def preload_levels_cache(self):
        if self._cache_loaded:
            return
        self._cache_loaded = True
        grouped = defaultdict(lambda: ([], []))
        for team_id, date, level in self.levels.execute(
            "SELECT team_id, date, level FROM team_levels ORDER BY team_id, date"
        ):
            dates, values = grouped[team_id]
            dates.append(date)
            values.append(level)
        self._levels_cache = dict(grouped)
        logger.info("Cache de niveles: %d equipos", len(self._levels_cache))

    def get_rival_level(self, team_id: int, date: str) -> float:
        """Nivel continuo del rival a la fecha. Fallback 1.0 (no 0.5, a propósito)."""
        if not self._cache_loaded:
            self.preload_levels_cache()
        entry = self._levels_cache.get(team_id)
        if not entry:
            return CONSTANTS_LEVEL_FALLBACK
        dates, values = entry
        idx = bisect.bisect_right(dates, date) - 1
        if idx >= 0:
            return values[idx] or CONSTANTS_LEVEL_FALLBACK
        return CONSTANTS_LEVEL_FALLBACK

    # ------------------------------------------------------------------
    # Paso 1: valores instantáneos q*
    # ------------------------------------------------------------------
    def compute_q_values(self, fixtures: List[tuple], team_id: int) -> List[Dict]:
        """
        fixtures: filas (id, date, home_team_id, away_team_id, goals_home, goals_away)
        ya ordenadas por fecha.
        """
        rows = []
        for fid, date, home_id, away_id, gh, ga_ in fixtures:
            is_local = home_id == team_id
            gf = gh if is_local else ga_
            ga = ga_ if is_local else gh
            rival_id = away_id if is_local else home_id
            nivel = self.get_rival_level(rival_id, date)

            dif = abs((gf or 0) - (ga or 0))
            res = None
            if gf is not None and ga is not None:
                res = 1 if gf > ga else (0 if gf == ga else -1)

            q_local = dif * res * nivel if res is not None and is_local else None
            q_visita = VISITOR_MULTIPLIER * dif * res * nivel if res is not None and not is_local else None
            q_neg = dif * res * nivel if res == -1 else 0

            q_ga = gf * nivel if gf is not None else None
            q_gr = -ga * nivel if ga is not None else None

            rows.append({
                'date': date,
                'fixture_id': fid,
                'q_local': q_local,
                'q_visita': q_visita,
                'q_negativo': q_neg,
                'q_goles_anotado': q_ga,
                'q_goles_recibido': q_gr,
                'q_goles_local_anotado': q_ga if is_local else None,
                'q_goles_local_recibido': q_gr if is_local else None,
                'q_goles_visita_anotado': q_ga if not is_local else None,
                'q_goles_visita_recibido': q_gr if not is_local else None,
            })
        return rows

    # ------------------------------------------------------------------
    # Paso 2: acumuladores k* con reseteo
    # ------------------------------------------------------------------
    @staticmethod
    def accumulate_k_values(q_rows: List[Dict], state: Optional[Dict] = None) -> List[Dict]:
        """
        Acumula k* partiendo de `state` (dict con K_FIELDS), lo que permite el
        modo incremental. Sin state, arranca de cero.
        """
        s = {f: 0 for f in K_FIELDS}
        if state:
            for f in K_FIELDS:
                s[f] = state.get(f) or 0

        result = []
        for r in q_rows:
            ql, qv, qneg = r['q_local'], r['q_visita'], r['q_negativo']
            q_ga, q_gr = r['q_goles_anotado'], r['q_goles_recibido']
            q_gla, q_glr = r['q_goles_local_anotado'], r['q_goles_local_recibido']
            q_gva, q_gvr = r['q_goles_visita_anotado'], r['q_goles_visita_recibido']

            # k general: q_any = q del partido según condición
            q_any = ql if ql is not None else qv
            s['k_positivo'] = s['k_positivo'] + q_any if (q_any is not None and q_any > 0) else 0
            s['k_negativo'] = s['k_negativo'] + qneg if (qneg is not None and qneg < 0) else 0

            # k local: solo se actualiza en partidos de local
            if ql is not None:
                s['k_positivo_local'] = s['k_positivo_local'] + ql if ql > 0 else 0
                s['k_negativo_local'] = s['k_negativo_local'] + ql if ql < 0 else 0

            # k visita: solo se actualiza en partidos de visitante
            if qv is not None:
                s['k_positivo_visita'] = s['k_positivo_visita'] + qv if qv > 0 else 0
                s['k_negativo_visita'] = s['k_negativo_visita'] + qv if qv < 0 else 0

            # k goles (recibido acumula valor ABSOLUTO)
            if q_ga is not None:
                s['k_goles_anotado'] = s['k_goles_anotado'] + q_ga if q_ga > 0 else 0
            if q_gr is not None:
                s['k_goles_recibido'] = s['k_goles_recibido'] + (-q_gr) if q_gr < 0 else 0
            if q_gla is not None:
                s['k_goles_local_anotado'] = s['k_goles_local_anotado'] + q_gla if q_gla > 0 else 0
            if q_glr is not None:
                s['k_goles_local_recibido'] = s['k_goles_local_recibido'] + (-q_glr) if q_glr < 0 else 0
            if q_gva is not None:
                s['k_goles_visita_anotado'] = s['k_goles_visita_anotado'] + q_gva if q_gva > 0 else 0
            if q_gvr is not None:
                s['k_goles_visita_recibido'] = s['k_goles_visita_recibido'] + (-q_gvr) if q_gvr < 0 else 0

            result.append({**r, **s})
        return result

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def _bulk_store(self, team_id: int, rows: List[Dict]) -> int:
        if not rows:
            return 0
        cols = ['team_id', 'fixture_id', 'date'] + Q_FIELDS + K_FIELDS
        sql = "INSERT INTO constants ({}) VALUES ({})".format(
            ",".join(cols), ",".join("?" * len(cols))
        )
        values = [
            tuple([team_id, r['fixture_id'], r['date']]
                  + [r[f] for f in Q_FIELDS] + [r[f] for f in K_FIELDS])
            for r in rows
        ]
        self.const.executemany(sql, values)
        self.const.commit()
        return len(values)

    def _team_finished_fixtures(self, team_id: int, after_date: Optional[str] = None):
        sql = """
            SELECT id, date, home_team_id, away_team_id, goals_home, goals_away
            FROM fixtures
            WHERE (home_team_id = ? OR away_team_id = ?) AND status_long = ?
        """
        params = [team_id, team_id, FINISHED_STATUS]
        if after_date:
            sql += " AND date > ?"
            params.append(after_date)
        sql += " ORDER BY date"
        return self.sad.execute(sql, params).fetchall()

    # ------------------------------------------------------------------
    # Recalculo completo
    # ------------------------------------------------------------------
    def full_recalculate_team(self, team_id: int) -> bool:
        """Borra todo el historial del equipo y lo regenera desde cero."""
        self.const.execute("DELETE FROM constants WHERE team_id = ?", (team_id,))
        self.const.commit()

        fixtures = self._team_finished_fixtures(team_id)
        if not fixtures:
            return False

        q_rows = self.compute_q_values(fixtures, team_id)
        result = self.accumulate_k_values(q_rows)
        count = self._bulk_store(team_id, result)
        logger.info("Recálculo completo equipo %s: %d constantes", team_id, count)
        return count > 0

    # ------------------------------------------------------------------
    # Modo incremental (default post-sync)
    # ------------------------------------------------------------------
    def incremental_calculate_and_store(self, team_id: int) -> bool:
        """
        Inserta solo constantes de partidos nuevos, continuando los acumuladores
        desde la última fila. Si detecta partidos faltantes con fecha ANTERIOR a
        la última constante (hueco retroactivo, p. ej. una copa extraída tarde),
        dispara recálculo completo: la racha quedó invalidada.
        """
        try:
            existing = {
                fid for (fid,) in self.const.execute(
                    "SELECT fixture_id FROM constants WHERE team_id = ?", (team_id,)
                )
            }
            all_finished = self.sad.execute(
                """
                SELECT id, date FROM fixtures
                WHERE (home_team_id = ? OR away_team_id = ?) AND status_long = ?
                """,
                (team_id, team_id, FINISHED_STATUS),
            ).fetchall()

            missing = {fid for fid, _ in all_finished} - existing

            last = self.const.execute(
                "SELECT * FROM constants WHERE team_id = ? ORDER BY date DESC LIMIT 1",
                (team_id,),
            ).fetchone()

            if missing and last is not None:
                last_date = self._row_as_dict(last)['date']
                retro = [fid for fid, fdate in all_finished
                         if fid in missing and fdate <= last_date]
                if retro:
                    logger.warning(
                        "Equipo %s: %d partidos retroactivos -> recálculo completo",
                        team_id, len(retro),
                    )
                    return self.full_recalculate_team(team_id)

            if last is not None:
                state = self._row_as_dict(last)
                start_date = state['date']
            else:
                state = None
                start_date = None
                # limpiar posibles huérfanos
                self.const.execute("DELETE FROM constants WHERE team_id = ?", (team_id,))
                self.const.commit()

            fixtures = self._team_finished_fixtures(team_id, after_date=start_date)
            if not fixtures:
                return True  # nada nuevo, todo OK

            q_rows = self.compute_q_values(fixtures, team_id)
            result = self.accumulate_k_values(q_rows, state=state)
            count = self._bulk_store(team_id, result)
            logger.info("Equipo %s: +%d constantes nuevas", team_id, count)
            return count > 0

        except Exception as e:
            logger.error("Error incremental equipo %s: %s", team_id, e)
            self.const.rollback()
            return False

    def _row_as_dict(self, row) -> Dict:
        cols = [d[0] for d in self.const.execute(
            "SELECT * FROM constants LIMIT 0").description]
        return dict(zip(cols, row))

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------
    def batch_calculate_teams(self, team_ids: List[int], incremental: bool = True,
                              progress_callback=None) -> Dict:
        """Procesa múltiples equipos. Precarga el cache de niveles UNA sola vez."""
        self.preload_levels_cache()
        total, failed_teams = len(team_ids), []
        for i, team_id in enumerate(team_ids, 1):
            try:
                if incremental:
                    self.incremental_calculate_and_store(team_id)
                else:
                    self.full_recalculate_team(team_id)
            except Exception as e:
                failed_teams.append(team_id)
                logger.error("Error equipo %s: %s", team_id, e)
            if progress_callback:
                progress_callback(int(i / total * 100))
        return {'total': total, 'failed': len(failed_teams), 'failed_teams': failed_teams}

    # ------------------------------------------------------------------
    # Mantenimiento
    # ------------------------------------------------------------------
    def cleanup_nan_records(self, team_id: Optional[int] = None) -> int:
        """Elimina filas corruptas (q_local y q_visita nulos con q_negativo = 0)."""
        sql = """
            DELETE FROM constants
            WHERE (q_local IS NULL AND q_visita IS NULL) AND q_negativo = 0
        """
        params = ()
        if team_id is not None:
            sql += " AND team_id = ?"
            params = (team_id,)
        cur = self.const.execute(sql, params)
        self.const.commit()
        return cur.rowcount
