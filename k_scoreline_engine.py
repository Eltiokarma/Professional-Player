#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
k_scoreline_engine.py

MOTOR DE MARCADORES POR CONSTANTES K
=====================================

EJE:  -5  -4  -3  -2  -1  0 | 0  +1  +2  +3  +4  +5
      ←── GOLES RECIBIDOS ──┤├── GOLES ANOTADOS ──→

6 FILAS POR EQUIPO (ejemplo LOCAL):
  Fila   Variable DB              Lado        Fórmula K_next (g goles)
  ─────────────────────────────────────────────────────────────────────
  K      k_positivo               DERECHO     K + mult × g × nivel
  K      |k_negativo|             IZQUIERDO   |K| + mult × g × nivel
  KL     k_positivo_local         DERECHO     K + mult × g × nivel
  KgA    k_goles_anotado          DERECHO     K + g × nivel
  KgR    k_goles_recibido         IZQUIERDO   K + g × nivel
  KgAL   k_goles_local_anotado    DERECHO     K + g × nivel
  KgRL   k_goles_local_recibido   IZQUIERDO   K + g × nivel

SCORING:
  Para g > 0:  #{valores históricos >= K_next} / #{total valores}
  Para g = 0:  #{valores == 0} / #{total valores}

  mult = 1.0 (local) o 1.4 (visita)

Fórmulas exactas de constants_calculator.py:
  q_local  = dif × res × nivel          (home)
  q_visita = 1.4 × dif × res × nivel    (away)
  q_negativo = dif × res × nivel         si res=-1, sino 0
  q_ga = gf × nivel
  q_gr = -ga × nivel  → almacenado como +ga×nivel

Autor: Gerson (desarrollado con Claude)
Fecha: Marzo 2026
"""

import sqlite3
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_GOALS = 5
WINDOW_SIZE = 20
DEFAULT_LEVEL = 1.0
AWAY_MULTIPLIER = 1.4


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class KSnapshot:
    team_id: int
    team_name: str
    condition: str
    k_positivo: float = 0.0
    k_negativo: float = 0.0
    k_pos_ctx: float = 0.0
    k_neg_ctx: float = 0.0
    k_ga: float = 0.0
    k_gr: float = 0.0
    k_ga_ctx: float = 0.0
    k_gr_ctx: float = 0.0


@dataclass
class ScoreTable:
    """Tabla de scores como en el Excel."""
    # Cada variable: lista de scores [0..MAX_GOALS]
    right_vars: Dict[str, List[float]] = field(default_factory=dict)
    left_vars: Dict[str, List[float]] = field(default_factory=dict)
    right_sums: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))
    left_sums: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))
    p_scored: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))
    p_conceded: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))
    n_general: int = 0       # Registros usados en variables generales
    n_contextual: int = 0    # Registros usados en variables contextuales


@dataclass
class TeamDistribution:
    team_id: int
    team_name: str
    condition: str
    opponent_level: float = DEFAULT_LEVEL
    score_table: ScoreTable = None
    snapshot: KSnapshot = None
    p_scored: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))
    p_conceded: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))


@dataclass
class MatchPrediction:
    home_team: str
    away_team: str
    home_dist: TeamDistribution = None
    away_dist: TeamDistribution = None
    match_matrix: np.ndarray = field(default_factory=lambda: np.zeros((MAX_GOALS + 1, MAX_GOALS + 1)))
    p_home: float = 0.0
    p_draw: float = 0.0
    p_away: float = 0.0
    p_over_15: float = 0.0
    p_over_25: float = 0.0
    p_over_35: float = 0.0
    p_btts: float = 0.0
    lambda_home: float = 0.0
    lambda_away: float = 0.0
    top_scores: List[Tuple] = field(default_factory=list)
    rho: float = 0.0
    p_home_goals: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))
    p_away_goals: np.ndarray = field(default_factory=lambda: np.zeros(MAX_GOALS + 1))
    label: str = ""  # "K Resultados" o "K Goles"


@dataclass
class DualPrediction:
    """Dos predicciones separadas: K de resultados y K de goles."""
    by_results: MatchPrediction = None   # K+, KL+, K-, KL-
    by_goals: MatchPrediction = None     # KgA, KgAL, KgR, KgRL


# ============================================================================
# SCORING: FRECUENCIA EMPÍRICA SOBRE TODOS LOS VALORES
# ============================================================================

def score_for_goals(k_next: float, k_series: np.ndarray) -> float:
    """
    Para g > 0: #{valores >= K_next} / #{total}
    """
    valid = k_series[~np.isnan(k_series)]
    if len(valid) == 0:
        return 0.5
    return float(np.sum(valid >= k_next)) / float(len(valid))


def score_for_zero(k_series: np.ndarray) -> float:
    """
    Para g = 0 (reset): #{valores == 0} / #{total}
    """
    valid = k_series[~np.isnan(k_series)]
    if len(valid) == 0:
        return 0.5
    return float(np.sum(np.abs(valid) < 0.001)) / float(len(valid))


# ============================================================================
# MOTOR
# ============================================================================

class KScorelineEngine:

    def __init__(self, constants_db_path: str, sad_db_path: str,
                 levels_db_path: str = None):
        self.constants_db = constants_db_path
        self.sad_db = sad_db_path
        self.levels_db = levels_db_path

    def _conn(self, path: str) -> sqlite3.Connection:
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    # ── consultas ──

    def get_team_name(self, team_id: int) -> str:
        c = self._conn(self.sad_db)
        try:
            r = c.execute("SELECT name FROM teams WHERE id=?", (team_id,)).fetchone()
            return r['name'] if r else f"#{team_id}"
        finally:
            c.close()

    def get_teams_list(self) -> List[Tuple[int, str]]:
        cc = self._conn(self.constants_db)
        cs = self._conn(self.sad_db)
        try:
            ids = cc.execute("SELECT DISTINCT team_id FROM constants").fetchall()
            result = []
            for row in ids:
                t = row['team_id']
                n = cs.execute("SELECT name FROM teams WHERE id=?", (t,)).fetchone()
                result.append((t, n['name'] if n else f"#{t}"))
            return sorted(result, key=lambda x: x[1])
        finally:
            cc.close(); cs.close()

    def get_team_level(self, team_id: int) -> float:
        if not self.levels_db:
            return DEFAULT_LEVEL
        try:
            c = self._conn(self.levels_db)
            r = c.execute(
                "SELECT level FROM team_levels WHERE team_id=? AND level IS NOT NULL ORDER BY date DESC LIMIT 1",
                (team_id,)
            ).fetchone()
            c.close()
            return float(r['level']) if r and r['level'] else DEFAULT_LEVEL
        except Exception:
            return DEFAULT_LEVEL

    def get_team_record_count(self, team_id: int) -> int:
        """Cantidad total de registros en constants para un equipo."""
        c = self._conn(self.constants_db)
        try:
            r = c.execute(
                "SELECT COUNT(*) as n FROM constants WHERE team_id=?", (team_id,)
            ).fetchone()
            return r['n'] if r else 0
        finally:
            c.close()

    def get_previous_match(self, team_id: int) -> Optional[Dict]:
        """
        Obtiene el partido anterior del equipo.
        Returns: {home_id, away_id, home_name, away_name, score, date} o None
        """
        cs = self._conn(self.sad_db)
        try:
            row = cs.execute("""
                SELECT id, date, home_team_id, away_team_id, goals_home, goals_away
                FROM fixtures
                WHERE (home_team_id = ? OR away_team_id = ?)
                  AND status_long = 'Match Finished'
                  AND goals_home IS NOT NULL
                ORDER BY date DESC
                LIMIT 1
            """, (team_id, team_id)).fetchone()
            
            if not row:
                return None
            
            home_name = self.get_team_name(row['home_team_id'])
            away_name = self.get_team_name(row['away_team_id'])
            
            return {
                'fixture_id': row['id'],
                'date': row['date'],
                'home_id': row['home_team_id'],
                'away_id': row['away_team_id'],
                'home_name': home_name,
                'away_name': away_name,
                'score': f"{row['goals_home']}-{row['goals_away']}",
            }
        finally:
            cs.close()

    def get_k_history(self, team_id: int, window: int = WINDOW_SIZE) -> List[Dict]:
        """Últimos `window` registros, etiquetados con is_home."""
        cc = self._conn(self.constants_db)
        cs = self._conn(self.sad_db)
        try:
            rows = cc.execute(
                "SELECT * FROM constants WHERE team_id=? ORDER BY date DESC LIMIT ?",
                (team_id, window)
            ).fetchall()
            
            tagged = []
            for r in reversed(rows):
                d = dict(r)
                # Etiquetar is_home consultando fixtures
                fid = d.get('fixture_id')
                if fid:
                    fx = cs.execute(
                        "SELECT home_team_id FROM fixtures WHERE id=?", (fid,)
                    ).fetchone()
                    d['is_home'] = (fx['home_team_id'] == team_id) if fx else None
                else:
                    d['is_home'] = None
                tagged.append(d)
            
            return tagged
        finally:
            cc.close()
            cs.close()

    def get_k_snapshot(self, team_id: int, condition: str) -> KSnapshot:
        c = self._conn(self.constants_db)
        try:
            r = c.execute(
                "SELECT * FROM constants WHERE team_id=? ORDER BY date DESC LIMIT 1",
                (team_id,)
            ).fetchone()
            name = self.get_team_name(team_id)
            if not r:
                return KSnapshot(team_id=team_id, team_name=name, condition=condition)
            home = condition == 'local'
            return KSnapshot(
                team_id=team_id, team_name=name, condition=condition,
                k_positivo=r['k_positivo'] or 0,
                k_negativo=r['k_negativo'] or 0,
                k_pos_ctx=(r['k_positivo_local'] if home else r['k_positivo_visita']) or 0,
                k_neg_ctx=(r['k_negativo_local'] if home else r['k_negativo_visita']) or 0,
                k_ga=r['k_goles_anotado'] or 0,
                k_gr=r['k_goles_recibido'] or 0,
                k_ga_ctx=(r['k_goles_local_anotado'] if home else r['k_goles_visita_anotado']) or 0,
                k_gr_ctx=(r['k_goles_local_recibido'] if home else r['k_goles_visita_recibido']) or 0,
            )
        finally:
            c.close()

    def _extract_series(self, history: List[Dict], condition: str) -> Dict[str, np.ndarray]:
        """
        Extrae series históricas de cada variable K.
        
        CLAVE: Las variables contextuales (KL, KL-, KgAL, KgRL) solo usan
        registros donde el equipo jugó en esa condición, para evitar
        false-zero contamination por valores repetidos.
        
        Las variables generales (K, K-, KgA, KgR) usan TODOS los registros.
        """
        home = condition == 'local'
        s = lambda v: float(v) if v is not None else 0.0

        # Series generales: todos los registros
        gen = {
            'k_positivo': [],
            'k_negativo_abs': [],
            'k_ga': [],
            'k_gr': [],
        }
        # Series contextuales: solo registros de la condición correcta
        ctx = {
            'k_pos_ctx': [],
            'k_neg_ctx_abs': [],
            'k_ga_ctx': [],
            'k_gr_ctx': [],
        }

        for h in history:
            # Generales: siempre
            gen['k_positivo'].append(s(h['k_positivo']))
            gen['k_negativo_abs'].append(abs(s(h['k_negativo'])))
            gen['k_ga'].append(s(h['k_goles_anotado']))
            gen['k_gr'].append(s(h['k_goles_recibido']))

            # Contextuales: solo si el partido fue en la condición correcta
            match_condition = h.get('is_home')
            if match_condition is None:
                continue  # Sin datos de fixture, saltar para contextuales

            if home and match_condition:
                # Equipo jugó de LOCAL → valores locales son reales
                ctx['k_pos_ctx'].append(s(h['k_positivo_local']))
                ctx['k_neg_ctx_abs'].append(abs(s(h['k_negativo_local'])))
                ctx['k_ga_ctx'].append(s(h['k_goles_local_anotado']))
                ctx['k_gr_ctx'].append(s(h['k_goles_local_recibido']))
            elif not home and not match_condition:
                # Equipo jugó de VISITA → valores visitante son reales
                ctx['k_pos_ctx'].append(s(h['k_positivo_visita']))
                ctx['k_neg_ctx_abs'].append(abs(s(h['k_negativo_visita'])))
                ctx['k_ga_ctx'].append(s(h['k_goles_visita_anotado']))
                ctx['k_gr_ctx'].append(s(h['k_goles_visita_recibido']))
            # else: partido en condición opuesta → no agregar a contextuales

        out = {}
        for k, v in gen.items():
            out[k] = np.array(v)
        for k, v in ctx.items():
            out[k] = np.array(v) if v else np.array([0.0])  # Fallback si no hay datos

        return out

    # ── K_next por fórmula exacta de constants_calculator.py ──

    def _k_next_positive(self, k_current: float, g: int,
                          nivel: float, is_home: bool) -> float:
        """
        k_positivo / k_pos_ctx: victoria g-0
        q = mult × dif × res × nivel = mult × g × 1 × nivel
        Si q > 0: K += q.  Si g=0: empate 0-0 → q=0 → reset.
        """
        if g == 0:
            return 0.0  # reset
        mult = 1.0 if is_home else AWAY_MULTIPLIER
        q = mult * g * 1 * nivel  # dif=g, res=+1
        return k_current + q

    def _k_next_negative_abs(self, k_neg_abs: float, g: int,
                              nivel: float, is_home: bool) -> float:
        """
        |k_negativo| GENERAL: derrota 0-g
        q_negativo = dif × res × nivel  (SIN multiplicador)
        """
        if g == 0:
            return 0.0
        return k_neg_abs + g * nivel

    def _k_next_negative_ctx_abs(self, k_neg_abs: float, g: int,
                                  nivel: float, is_home: bool) -> float:
        """
        |k_negativo_local/visita| CONTEXTUAL: derrota 0-g
        Usa q_local = dif × res × nivel  (mult=1.0)
        o   q_visita = 1.4 × dif × res × nivel  (mult=1.4)
        → CON multiplicador contextual.
        """
        if g == 0:
            return 0.0
        mult = 1.0 if is_home else AWAY_MULTIPLIER
        return k_neg_abs + mult * g * nivel

    def _k_next_goals(self, k_current: float, g: int, nivel: float) -> float:
        """
        KgA / KgR / KgA_ctx / KgR_ctx
        q_ga = g × nivel   (para anotados)
        q_gr almacena +ga×nivel   (para recibidos)
        Si g > 0: K += g × nivel.  Si g=0: reset.
        """
        if g == 0:
            return 0.0
        return k_current + g * nivel

    # ── distribuciones ──

    def calculate_team_distribution(
        self, team_id: int, condition: str,
        opponent_level: float = None,
        window: int = WINDOW_SIZE,
        mode: str = 'results'
    ) -> TeamDistribution:
        """
        mode='results' → K+, KL+, K-, KL-  (rachas de resultados)
        mode='goals'   → KgA, KgAL, KgR, KgRL  (rachas de goles)
        """
        is_home = condition == 'local'
        name = self.get_team_name(team_id)
        snap = self.get_k_snapshot(team_id, condition)
        hist = self.get_k_history(team_id, window)

        if opponent_level is None:
            opponent_level = DEFAULT_LEVEL

        if not hist:
            d = TeamDistribution(team_id=team_id, team_name=name,
                                 condition=condition, opponent_level=opponent_level,
                                 snapshot=snap)
            d.p_scored = np.ones(MAX_GOALS + 1) / (MAX_GOALS + 1)
            d.p_conceded = np.ones(MAX_GOALS + 1) / (MAX_GOALS + 1)
            return d

        series = self._extract_series(hist, condition)
        table = ScoreTable()
        table.n_general = len(series['k_positivo'])
        table.n_contextual = len(series['k_pos_ctx'])
        nivel = opponent_level

        if mode == 'results':
            # ═══════════════════════════════════════
            # MARCADOR POR K DE RESULTADOS
            # ═══════════════════════════════════════

            # DERECHO: K+ (victoria g-0)
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_positivo']))
                else:
                    k_next = self._k_next_positive(snap.k_positivo, g, nivel, is_home)
                    scores.append(score_for_goals(k_next, series['k_positivo']))
            table.right_vars['K'] = scores

            # DERECHO: KL+ / KV+
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_pos_ctx']))
                else:
                    k_next = self._k_next_positive(snap.k_pos_ctx, g, nivel, is_home)
                    scores.append(score_for_goals(k_next, series['k_pos_ctx']))
            table.right_vars['KL' if is_home else 'KV'] = scores

            # IZQUIERDO: K- (derrota 0-g)
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_negativo_abs']))
                else:
                    k_next = self._k_next_negative_abs(abs(snap.k_negativo), g, nivel, is_home)
                    scores.append(score_for_goals(k_next, series['k_negativo_abs']))
            table.left_vars['K'] = scores

            # IZQUIERDO: KL- / KV-
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_neg_ctx_abs']))
                else:
                    k_next = self._k_next_negative_ctx_abs(abs(snap.k_neg_ctx), g, nivel, is_home)
                    scores.append(score_for_goals(k_next, series['k_neg_ctx_abs']))
            table.left_vars['KL-' if is_home else 'KV-'] = scores

        else:  # mode == 'goals'
            # ═══════════════════════════════════════
            # MARCADOR POR K DE GOLES
            # ═══════════════════════════════════════

            # DERECHO: KgA
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_ga']))
                else:
                    k_next = self._k_next_goals(snap.k_ga, g, nivel)
                    scores.append(score_for_goals(k_next, series['k_ga']))
            table.right_vars['KgA'] = scores

            # DERECHO: KgAL / KgAV
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_ga_ctx']))
                else:
                    k_next = self._k_next_goals(snap.k_ga_ctx, g, nivel)
                    scores.append(score_for_goals(k_next, series['k_ga_ctx']))
            table.right_vars['KgAL' if is_home else 'KgAV'] = scores

            # IZQUIERDO: KgR
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_gr']))
                else:
                    k_next = self._k_next_goals(snap.k_gr, g, nivel)
                    scores.append(score_for_goals(k_next, series['k_gr']))
            table.left_vars['KgR'] = scores

            # IZQUIERDO: KgRL / KgRV
            scores = []
            for g in range(MAX_GOALS + 1):
                if g == 0:
                    scores.append(score_for_zero(series['k_gr_ctx']))
                else:
                    k_next = self._k_next_goals(snap.k_gr_ctx, g, nivel)
                    scores.append(score_for_goals(k_next, series['k_gr_ctx']))
            table.left_vars['KgRL' if is_home else 'KgRV'] = scores

        # ═══════════════════════════════════════
        # SUMAR Y NORMALIZAR
        # ═══════════════════════════════════════

        for var_scores in table.right_vars.values():
            table.right_sums += np.array(var_scores)
        for var_scores in table.left_vars.values():
            table.left_sums += np.array(var_scores)

        rs = np.sum(table.right_sums)
        ls = np.sum(table.left_sums)
        table.p_scored = table.right_sums / rs if rs > 0 else np.ones(MAX_GOALS + 1) / (MAX_GOALS + 1)
        table.p_conceded = table.left_sums / ls if ls > 0 else np.ones(MAX_GOALS + 1) / (MAX_GOALS + 1)

        return TeamDistribution(
            team_id=team_id, team_name=name, condition=condition,
            opponent_level=opponent_level, score_table=table, snapshot=snap,
            p_scored=table.p_scored, p_conceded=table.p_conceded,
        )

    # ── Dixon-Coles ──

    @staticmethod
    def dixon_coles_tau(x, y, lam, mu, rho):
        if x == 0 and y == 0: return 1 - lam * mu * rho
        if x == 1 and y == 0: return 1 + mu * rho
        if x == 0 and y == 1: return 1 + lam * rho
        if x == 1 and y == 1: return 1 - rho
        return 1.0

    @staticmethod
    def estimate_rho(lam, mu):
        avg = (lam + mu) / 2
        if avg < 0.8:   return -0.12
        elif avg < 1.2: return -0.09
        elif avg < 1.8: return -0.06
        else:           return -0.03

    def combine_dixon_coles(self, home_dist, away_dist):
        p_hg = 0.5 * home_dist.p_scored + 0.5 * away_dist.p_conceded
        p_ag = 0.5 * away_dist.p_scored + 0.5 * home_dist.p_conceded
        p_hg /= np.sum(p_hg)
        p_ag /= np.sum(p_ag)

        g = np.arange(MAX_GOALS + 1)
        lam = float(np.sum(g * p_hg))
        mu = float(np.sum(g * p_ag))
        rho = self.estimate_rho(lam, mu)

        n = MAX_GOALS + 1
        mx = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                mx[i, j] = p_hg[i] * p_ag[j] * self.dixon_coles_tau(i, j, lam, mu, rho)
        mx /= np.sum(mx)

        p_h = sum(mx[i, j] for i in range(n) for j in range(n) if i > j)
        p_d = sum(mx[i, i] for i in range(n))
        p_a = sum(mx[i, j] for i in range(n) for j in range(n) if i < j)
        p_o15 = sum(mx[i, j] for i in range(n) for j in range(n) if i+j > 1.5)
        p_o25 = sum(mx[i, j] for i in range(n) for j in range(n) if i+j > 2.5)
        p_o35 = sum(mx[i, j] for i in range(n) for j in range(n) if i+j > 3.5)
        p_btts = sum(mx[i, j] for i in range(1, n) for j in range(1, n))

        sc = [(i, j, mx[i, j]) for i in range(n) for j in range(n)]
        sc.sort(key=lambda x: x[2], reverse=True)

        return MatchPrediction(
            home_team=home_dist.team_name, away_team=away_dist.team_name,
            home_dist=home_dist, away_dist=away_dist, match_matrix=mx,
            p_home=p_h, p_draw=p_d, p_away=p_a,
            p_over_15=p_o15, p_over_25=p_o25, p_over_35=p_o35, p_btts=p_btts,
            lambda_home=lam, lambda_away=mu, top_scores=sc[:10], rho=rho,
            p_home_goals=p_hg, p_away_goals=p_ag,
        )

    # ── API principal ──

    def predict_match(self, home_id, away_id,
                      level_home=None, level_away=None,
                      window=WINDOW_SIZE) -> DualPrediction:
        """
        Retorna DOS predicciones separadas:
        - by_results: basada en K+, KL+, K-, KL- (rachas de resultados)
        - by_goals: basada en KgA, KgAL, KgR, KgRL (rachas de goles)
        """
        if level_home is None:
            level_home = self.get_team_level(away_id)
        if level_away is None:
            level_away = self.get_team_level(home_id)

        # Marcador por K de Resultados
        hd_r = self.calculate_team_distribution(home_id, 'local', level_home, window, mode='results')
        ad_r = self.calculate_team_distribution(away_id, 'visita', level_away, window, mode='results')
        pred_results = self.combine_dixon_coles(hd_r, ad_r)
        pred_results.label = "K Resultados"

        # Marcador por K de Goles
        hd_g = self.calculate_team_distribution(home_id, 'local', level_home, window, mode='goals')
        ad_g = self.calculate_team_distribution(away_id, 'visita', level_away, window, mode='goals')
        pred_goals = self.combine_dixon_coles(hd_g, ad_g)
        pred_goals.label = "K Goles"

        logger.info(f"K Resultados — 1X2: {pred_results.p_home:.1%}/{pred_results.p_draw:.1%}/{pred_results.p_away:.1%}")
        logger.info(f"K Goles      — 1X2: {pred_goals.p_home:.1%}/{pred_goals.p_draw:.1%}/{pred_goals.p_away:.1%}")

        return DualPrediction(by_results=pred_results, by_goals=pred_goals)

    # ── Impresión tipo Excel ──

    def print_score_table(self, dist):
        t = dist.score_table
        if not t:
            return
        sn = dist.snapshot

        print(f"\n{'═'*75}")
        print(f"  {dist.team_name} ({dist.condition.upper()}) │ Nivel rival: {dist.opponent_level:.2f}")
        print(f"  N general: {t.n_general} │ N contextual: {t.n_contextual}")
        print(f"{'═'*75}")

        # ── DERECHO (anotados) ──
        hdr = "  ".join(f"{g:>5}" for g in range(MAX_GOALS + 1))
        print(f"\n  GOLES ANOTADOS →     {hdr}")
        print(f"  {'─'*60}")
        for var, scores in t.right_vars.items():
            vals = "  ".join(f"{s:>5.2f}" for s in scores)
            print(f"  {var:<8}             {vals}")
        sums = "  ".join(f"{s:>5.2f}" for s in t.right_sums)
        pcts = "  ".join(f"{p:>4.0%} " for p in t.p_scored)
        print(f"  {'─'*60}")
        print(f"  {'SUMA':<8}             {sums}")
        print(f"  {'%':<8}             {pcts}")

        # ── IZQUIERDO (recibidos) ──
        print(f"\n  GOLES RECIBIDOS →    {hdr}")
        print(f"  {'─'*60}")
        for var, scores in t.left_vars.items():
            vals = "  ".join(f"{s:>5.2f}" for s in scores)
            print(f"  {var:<8}             {vals}")
        sums = "  ".join(f"{s:>5.2f}" for s in t.left_sums)
        pcts = "  ".join(f"{p:>4.0%} " for p in t.p_conceded)
        print(f"  {'─'*60}")
        print(f"  {'SUMA':<8}             {sums}")
        print(f"  {'%':<8}             {pcts}")

        print(f"\n  K+={sn.k_positivo:.1f}  K-={sn.k_negativo:.1f}  "
              f"Kctx+={sn.k_pos_ctx:.1f}  Kctx-={sn.k_neg_ctx:.1f}  "
              f"KgA={sn.k_ga:.1f}  KgR={sn.k_gr:.1f}  "
              f"KgActx={sn.k_ga_ctx:.1f}  KgRctx={sn.k_gr_ctx:.1f}")


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cp, sp, lp = [os.path.join(base, f) for f in ('constants.db', 'sad.db', 'levels.db')]
    if not os.path.exists(cp):
        print(f"No: {cp}"); exit(1)
    eng = KScorelineEngine(cp, sp, lp)
    teams = eng.get_teams_list()
    if len(teams) >= 2:
        dual = eng.predict_match(teams[0][0], teams[1][0])

        for pred in [dual.by_results, dual.by_goals]:
            print(f"\n{'▓'*75}")
            print(f"  {pred.label}")
            print(f"{'▓'*75}")
            eng.print_score_table(pred.home_dist)
            eng.print_score_table(pred.away_dist)
            print(f"\n  {pred.home_team} vs {pred.away_team}")
            print(f"  1X2: {pred.p_home:.1%}/{pred.p_draw:.1%}/{pred.p_away:.1%}")
            print(f"  O2.5={pred.p_over_25:.1%}  BTTS={pred.p_btts:.1%}")
            for h, a, pr in pred.top_scores[:5]:
                print(f"    {h}-{a}: {pr:.1%}")