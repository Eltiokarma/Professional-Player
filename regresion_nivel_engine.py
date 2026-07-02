# src/regresion_nivel_engine.py
# -*- coding: utf-8 -*-
"""
Motor de la Ley de la Regresion al Nivel.
==========================================

Funciones:
  - Cargar modelo entrenado (.joblib)
  - Calcular gap para cualquier equipo
  - Predecir P(Win) para un partido
  - Entrenar/reentrenar modelo
  - Obtener info de validacion

Estructura esperada:
  D:\\VSCode Ejercicios 02\\          <- ROOT (sad.db)
  +-- src\\
      +-- regresion_nivel_engine.py   <- ESTE ARCHIVO
      +-- levels.db
      +-- regresion_nivel_output\\
          +-- regresion_nivel_v2.joblib
          +-- ml_results_v2.json

Autor: Sistema de Analisis Deportivo
"""

import os
import logging
import time
import json
import numpy as np
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  DATACLASSES
# ══════════════════════════════════════════════════════════

@dataclass
class NivelPrediction:
    """Prediccion para un partido desde la perspectiva de ambos equipos."""
    home_team: str
    away_team: str
    home_id: int
    away_id: int
    # Probabilidades
    p_home_win: float
    p_away_win: float
    p_draw_approx: float
    # Gap info
    gap_home: float
    gap_away: float
    gap_diff: float
    # Niveles
    level_home: float
    level_away: float
    level_diff: float
    # Mu (puntos esperados)
    mu_home: float
    mu_away: float
    # Forma reciente
    pts_recent_home: float
    pts_recent_away: float
    # Temporada
    season_ppg_home: Optional[float]
    season_ppg_away: Optional[float]
    season_progress: float
    is_international: bool
    # Meta
    confidence: str   # 'ALTA', 'MEDIA', 'BAJA'
    recommendation: str


@dataclass
class TrainingResult:
    """Resultado de entrenamiento."""
    success: bool
    message: str
    n_records: int
    n_train: int
    n_test: int
    accuracy: float
    auc_roc: float
    log_loss: float
    mejora_pct: float
    elapsed_seconds: float
    model_path: str
    timestamp: str


# ══════════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════════

MU_COEFS = {
    'intercept': 1.110,
    'level_team': 0.686,
    'level_opponent': -0.669,
    'is_home': 0.422,
}

LIGAS_SAD = [
    128, 129, 71, 72, 239, 265, 281, 268, 242, 262, 263,
    13, 11, 2, 3, 848,
    39, 40, 140, 141, 135, 136, 78, 79, 61, 62, 94, 144,
]

LIGAS_INTERNACIONALES = {13, 11, 2, 3, 848}

FEATURE_NAMES = [
    'gap_team', 'gap_opponent', 'level_team', 'level_opponent',
    'level_diff', 'is_home', 'mu', 'pts_recent_team',
    'pts_recent_opponent', 'gap_diff',
    'season_progress', 'season_ppg_team', 'season_ppg_opponent',
    'is_international', 'season_match_num',
]

WINDOW = 5
DEFAULT_TRAIN_MAX_SEASON = 2024


# ══════════════════════════════════════════════════════════
#  UTILIDADES DE RUTA
# ══════════════════════════════════════════════════════════

def find_project_root() -> str:
    """
    Encuentra la raiz del proyecto (donde esta sad.db).
    
    Estructura:
      ROOT/           <- sad.db aqui
        src/          <- este archivo esta aqui
          levels.db
          regresion_nivel_output/
    """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Si estamos en src/ o src/algo/, subir hasta encontrar sad.db
    current = this_dir
    for _ in range(5):
        if os.path.exists(os.path.join(current, 'sad.db')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    
    # Fallback: asumir que estamos en src/
    return os.path.dirname(this_dir)


def find_src_dir() -> str:
    """Encuentra el directorio src/ donde esta este archivo."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    # Si estamos en src/ui/ o similar, subir
    if os.path.basename(this_dir).lower() in ('ui', 'utils', 'data'):
        return os.path.dirname(this_dir)
    return this_dir


# ══════════════════════════════════════════════════════════
#  ENGINE PRINCIPAL
# ══════════════════════════════════════════════════════════

class RegresionNivelEngine:
    """Motor principal de la Ley de la Regresion al Nivel."""
    
    def __init__(self, sad_db_path: str = None, levels_db_path: str = None,
                 model_dir: str = None):
        root = find_project_root()
        src_dir = find_src_dir()
        
        self.sad_db_path = sad_db_path or os.path.join(root, 'sad.db')
        self.levels_db_path = levels_db_path or os.path.join(src_dir, 'levels.db')
        self.model_dir = model_dir or os.path.join(src_dir, 'regresion_nivel_output')
        
        self.model = None
        self.levels_cache: Dict[int, List[Tuple[str, float]]] = {}
        self.team_names: Dict[int, str] = {}
        self._levels_loaded = False
        
        logger.info(f"RegresionNivelEngine inicializado")
        logger.info(f"  sad.db:    {self.sad_db_path} (existe={os.path.exists(self.sad_db_path)})")
        logger.info(f"  levels.db: {self.levels_db_path} (existe={os.path.exists(self.levels_db_path)})")
        logger.info(f"  model_dir: {self.model_dir}")
    
    # ──────────────────────────────────────────────────────
    #  CARGA DE DATOS
    # ──────────────────────────────────────────────────────
    
    def load_levels(self):
        """Carga niveles de equipos en cache (lazy, una sola vez)."""
        if self._levels_loaded:
            return
        
        import sqlite3
        t0 = time.time()
        conn = sqlite3.connect(self.levels_db_path)
        rows = conn.execute(
            "SELECT team_id, date, level FROM team_levels ORDER BY team_id, date"
        ).fetchall()
        conn.close()
        
        self.levels_cache = {}
        for tid, dt, lv in rows:
            if tid not in self.levels_cache:
                self.levels_cache[tid] = []
            self.levels_cache[tid].append((str(dt), float(lv)))
        
        self._levels_loaded = True
        logger.info(f"Niveles cargados: {len(rows):,} registros, "
                    f"{len(self.levels_cache):,} equipos ({time.time()-t0:.1f}s)")
    
    def load_team_names(self):
        """Carga nombres de equipos desde sad.db."""
        if self.team_names:
            return
        
        import sqlite3
        conn = sqlite3.connect(self.sad_db_path)
        rows = conn.execute("SELECT id, name FROM teams").fetchall()
        conn.close()
        self.team_names = {int(tid): name for tid, name in rows}
        logger.info(f"Nombres cargados: {len(self.team_names):,} equipos")
    
    def load_model(self) -> bool:
        """Carga el modelo entrenado (.joblib)."""
        try:
            import joblib
            path = os.path.join(self.model_dir, 'regresion_nivel_v2.joblib')
            if not os.path.exists(path):
                logger.warning(f"Modelo no encontrado: {path}")
                return False
            data = joblib.load(path)
            self.model = data['model']
            logger.info(f"Modelo cargado: {path}")
            return True
        except Exception as e:
            logger.error(f"Error cargando modelo: {e}")
            return False
    
    # ──────────────────────────────────────────────────────
    #  CALCULOS BASE
    # ──────────────────────────────────────────────────────
    
    def get_level(self, team_id: int, date: str = None) -> Optional[float]:
        """Obtiene nivel de un equipo a una fecha (busqueda binaria)."""
        self.load_levels()
        recs = self.levels_cache.get(team_id)
        if not recs:
            return None
        if date is None:
            return recs[-1][1]
        ds = str(date)[:26]
        lo, hi, result = 0, len(recs) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if recs[mid][0] <= ds:
                result = recs[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return result
    
    @staticmethod
    def calc_mu(level_team: float, level_opp: float, is_home: bool) -> float:
        """Calcula mu (puntos esperados) para un equipo en un partido."""
        mu = (MU_COEFS['intercept']
              + MU_COEFS['level_team'] * level_team
              + MU_COEFS['level_opponent'] * level_opp
              + MU_COEFS['is_home'] * (1.0 if is_home else 0.0))
        return max(0.0, min(3.0, mu))
    
    @staticmethod
    def calc_gap(level_team: float, pts_recent: float) -> float:
        """
        Calcula gap = rendimiento_esperado - forma_reciente.
        
        Gap > 0 = rinde BAJO su nivel (tendencia a mejorar)
        Gap < 0 = rinde SOBRE su nivel (tendencia a empeorar)
        """
        pts_exp = (MU_COEFS['intercept']
                   + MU_COEFS['level_team'] * level_team
                   + MU_COEFS['level_opponent'] * 2.0   # rival promedio
                   + MU_COEFS['is_home'] * 0.5)          # 50% local
        pts_exp = max(0.0, min(3.0, pts_exp))
        return pts_exp - pts_recent
    
    def get_recent_form(self, team_id: int, n: int = WINDOW,
                        before_date: str = None) -> Optional[float]:
        """
        Puntos promedio de los ultimos n partidos.
        Returns: pts/partido promedio, o None si no hay suficientes.
        """
        import sqlite3
        conn = sqlite3.connect(self.sad_db_path)
        
        params = [team_id, team_id]
        date_filter = ""
        if before_date:
            date_filter = "AND date < ?"
            params.append(before_date)
        
        rows = conn.execute(f"""
            SELECT goals_home, goals_away, home_team_id
            FROM fixtures
            WHERE (home_team_id = ? OR away_team_id = ?)
              AND status_short = 'FT'
              AND goals_home IS NOT NULL
              {date_filter}
            ORDER BY date DESC
            LIMIT ?
        """, params + [n]).fetchall()
        conn.close()
        
        if len(rows) < n:
            return None
        
        pts = 0
        for gh, ga, hid in rows:
            if hid == team_id:
                pts += 3 if gh > ga else (1 if gh == ga else 0)
            else:
                pts += 3 if ga > gh else (1 if gh == ga else 0)
        return pts / n
    
    def get_season_context(self, team_id: int, league_id: int,
                           season: int) -> Dict:
        """Obtiene contexto de temporada: match_num, ppg, progress."""
        import sqlite3
        conn = sqlite3.connect(self.sad_db_path)
        rows = conn.execute("""
            SELECT goals_home, goals_away, home_team_id
            FROM fixtures
            WHERE (home_team_id = ? OR away_team_id = ?)
              AND league_id = ? AND league_season = ?
              AND status_short = 'FT'
              AND goals_home IS NOT NULL
            ORDER BY date ASC
        """, [team_id, team_id, league_id, season]).fetchall()
        conn.close()
        
        if not rows:
            return {'match_num': 0, 'ppg': None, 'progress': 0.5}
        
        total_pts = 0
        for gh, ga, hid in rows:
            if hid == team_id:
                total_pts += 3 if gh > ga else (1 if gh == ga else 0)
            else:
                total_pts += 3 if ga > gh else (1 if gh == ga else 0)
        
        match_num = len(rows)
        return {
            'match_num': match_num,
            'ppg': total_pts / match_num,
            'progress': min(1.0, match_num / 38),
        }
    
    # ──────────────────────────────────────────────────────
    #  PREDICCION
    # ──────────────────────────────────────────────────────
    
    def predict_match(self, home_id: int, away_id: int,
                      league_id: int = None, season: int = None,
                      date: str = None) -> Optional[NivelPrediction]:
        """
        Predice P(Win) para ambos equipos en un partido.
        """
        if self.model is None:
            if not self.load_model():
                return None
        
        self.load_levels()
        self.load_team_names()
        
        # --- Datos base ---
        lv_h = self.get_level(home_id, date)
        lv_a = self.get_level(away_id, date)
        if lv_h is None or lv_a is None:
            logger.warning(f"Sin nivel: home={home_id}({lv_h}) away={away_id}({lv_a})")
            return None
        
        pr_h = self.get_recent_form(home_id, WINDOW, date)
        pr_a = self.get_recent_form(away_id, WINDOW, date)
        if pr_h is None or pr_a is None:
            logger.warning(f"Sin forma reciente: home={home_id} away={away_id}")
            return None
        
        gap_h = self.calc_gap(lv_h, pr_h)
        gap_a = self.calc_gap(lv_a, pr_a)
        mu_h = self.calc_mu(lv_h, lv_a, True)
        mu_a = self.calc_mu(lv_a, lv_h, False)
        
        # --- Contexto temporal ---
        is_intl = 1.0 if league_id and league_id in LIGAS_INTERNACIONALES else 0.0
        ppg_h, ppg_a = None, None
        progress = 0.5
        match_num = 15
        
        if league_id and season:
            ctx_h = self.get_season_context(home_id, league_id, season)
            ctx_a = self.get_season_context(away_id, league_id, season)
            ppg_h = ctx_h['ppg']
            ppg_a = ctx_a['ppg']
            progress = ctx_h['progress']
            match_num = ctx_h['match_num']
        
        # --- Features HOME ---
        feat_h = np.array([[
            gap_h, gap_a, lv_h, lv_a, lv_h - lv_a, 1.0, mu_h,
            pr_h, pr_a, gap_h - gap_a,
            progress, ppg_h or 1.3, ppg_a or 1.3, is_intl, match_num,
        ]])
        # --- Features AWAY ---
        feat_a = np.array([[
            gap_a, gap_h, lv_a, lv_h, lv_a - lv_h, 0.0, mu_a,
            pr_a, pr_h, gap_a - gap_h,
            progress, ppg_a or 1.3, ppg_h or 1.3, is_intl, match_num,
        ]])
        
        p_h = float(self.model.predict_proba(feat_h)[0, 1])
        p_a = float(self.model.predict_proba(feat_a)[0, 1])
        p_draw = max(0.0, 1.0 - p_h - p_a)
        
        # --- Confianza ---
        gd = abs(gap_h - gap_a)
        confidence = 'ALTA' if gd > 0.8 else ('MEDIA' if gd > 0.4 else 'BAJA')
        
        # --- Recomendacion ---
        name_h = self.team_names.get(home_id, f"Team {home_id}")
        name_a = self.team_names.get(away_id, f"Team {away_id}")
        recommendation = self._build_recommendation(
            p_h, p_a, gap_h, gap_a, lv_h, lv_a, name_h, name_a)
        
        return NivelPrediction(
            home_team=name_h, away_team=name_a,
            home_id=home_id, away_id=away_id,
            p_home_win=p_h, p_away_win=p_a, p_draw_approx=p_draw,
            gap_home=gap_h, gap_away=gap_a, gap_diff=gap_h - gap_a,
            level_home=lv_h, level_away=lv_a, level_diff=lv_h - lv_a,
            mu_home=mu_h, mu_away=mu_a,
            pts_recent_home=pr_h, pts_recent_away=pr_a,
            season_ppg_home=ppg_h, season_ppg_away=ppg_a,
            season_progress=progress,
            is_international=bool(is_intl),
            confidence=confidence,
            recommendation=recommendation,
        )
    
    def _build_recommendation(self, p_h, p_a, gap_h, gap_a,
                               lv_h, lv_a, name_h, name_a) -> str:
        parts = []
        # Quién tiene gap a favor
        if gap_h > 0.5 and gap_a < -0.2:
            parts.append(
                f"{name_h} rinde bajo su nivel y {name_a} sobre el suyo "
                f"-> Rebote probable de {name_h}"
            )
        elif gap_a > 0.5 and gap_h < -0.2:
            parts.append(
                f"{name_a} rinde bajo su nivel y {name_h} sobre el suyo "
                f"-> Rebote probable de {name_a}"
            )
        elif gap_h > 0.3:
            parts.append(f"{name_h} bajo su nivel (gap={gap_h:+.2f}) -> Tendencia a mejorar")
        elif gap_a > 0.3:
            parts.append(f"{name_a} bajo su nivel (gap={gap_a:+.2f}) -> Tendencia a mejorar")
        
        # Veredicto probabilístico
        if p_h > 0.65:
            parts.append(f"P(Win {name_h})={p_h:.0%} -> Favorito claro")
        elif p_a > 0.65:
            parts.append(f"P(Win {name_a})={p_a:.0%} -> Favorito claro")
        elif abs(p_h - p_a) < 0.08:
            parts.append(f"Equilibrado (H={p_h:.0%}, A={p_a:.0%})")
        
        return " | ".join(parts) if parts else "Sin senal clara de gap"
    
    # ──────────────────────────────────────────────────────
    #  PROXIMOS PARTIDOS
    # ──────────────────────────────────────────────────────
    
    def get_upcoming_matches(self, days_ahead: int = 14) -> List[Dict]:
        """Lista de proximos partidos de ligas SAD."""
        import sqlite3
        conn = sqlite3.connect(self.sad_db_path)
        ph = ','.join('?' * len(LIGAS_SAD))
        
        rows = conn.execute(f"""
            SELECT f.id, f.date, f.league_id, f.league_season,
                   f.home_team_id, f.away_team_id,
                   t1.name AS home_name, t2.name AS away_name,
                   l.name AS league_name
            FROM fixtures f
            LEFT JOIN teams t1 ON f.home_team_id = t1.id
            LEFT JOIN teams t2 ON f.away_team_id = t2.id
            LEFT JOIN leagues l ON f.league_id = l.id
            WHERE f.status_short IN ('NS', 'TBD')
              AND f.league_id IN ({ph})
              AND f.date >= datetime('now')
              AND f.date <= datetime('now', '+{days_ahead} days')
            ORDER BY f.date ASC
            LIMIT 200
        """, LIGAS_SAD).fetchall()
        conn.close()
        
        return [
            {
                'fixture_id': r[0], 'date': r[1], 'league_id': r[2],
                'season': r[3], 'home_id': r[4], 'away_id': r[5],
                'home_name': r[6] or f"Team {r[4]}",
                'away_name': r[7] or f"Team {r[5]}",
                'league_name': r[8] or f"Liga {r[2]}",
            }
            for r in rows
        ]
    
    # ──────────────────────────────────────────────────────
    #  INFO DEL MODELO
    # ──────────────────────────────────────────────────────
    
    def get_model_info(self) -> Dict:
        """Retorna informacion del modelo guardado y sus resultados."""
        model_path = os.path.join(self.model_dir, 'regresion_nivel_v2.joblib')
        results_path = os.path.join(self.model_dir, 'ml_results_v2.json')
        
        info = {
            'exists': os.path.exists(model_path),
            'model_path': model_path,
        }
        
        if not info['exists']:
            return info
        
        try:
            import joblib
            data = joblib.load(model_path)
            info.update({
                'trained_at': data.get('trained_at', '?'),
                'train_seasons': data.get('train_seasons', '?'),
                'window': data.get('window', WINDOW),
                'best_model': data.get('best_model_name', '?'),
            })
        except Exception as e:
            info['load_error'] = str(e)
        
        if os.path.exists(results_path):
            try:
                with open(results_path) as f:
                    info['results'] = json.load(f)
            except Exception:
                pass
        
        return info
    
    # ──────────────────────────────────────────────────────
    #  ENTRENAMIENTO
    # ──────────────────────────────────────────────────────
    
    def train_model(self, max_train_season: int = DEFAULT_TRAIN_MAX_SEASON,
                    progress_callback=None) -> TrainingResult:
        """
        Entrena el modelo desde cero.
        
        Args:
            max_train_season: Ultima temporada para entrenamiento (test = posterior)
            progress_callback: func(message: str, percent: int)
        """
        import sqlite3
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
        
        t0 = time.time()
        
        def report(msg, pct=0):
            if progress_callback:
                progress_callback(msg, pct)
            logger.info(msg)
        
        try:
            # --- Cargar niveles ---
            report("Cargando niveles...", 5)
            self._levels_loaded = False
            self.load_levels()
            
            # --- Cargar fixtures ---
            report("Cargando fixtures...", 10)
            conn = sqlite3.connect(self.sad_db_path)
            ph = ','.join('?' * len(LIGAS_SAD))
            fixtures = conn.execute(f"""
                SELECT id, date, league_id, league_season,
                       home_team_id, away_team_id,
                       goals_home, goals_away
                FROM fixtures
                WHERE status_short = 'FT'
                  AND goals_home IS NOT NULL AND goals_away IS NOT NULL
                  AND league_id IN ({ph})
                ORDER BY date ASC, id ASC
            """, LIGAS_SAD).fetchall()
            conn.close()
            report(f"  {len(fixtures):,} fixtures", 15)
            
            # --- Historial por equipo ---
            report("Construyendo historial por equipo...", 20)
            team_history: Dict[int, list] = defaultdict(list)
            for fid, dt, lid, sea, hid, aid, gh, ga in fixtures:
                pts_h = 3 if gh > ga else (1 if gh == ga else 0)
                pts_a = 3 if ga > gh else (1 if gh == ga else 0)
                team_history[hid].append({
                    'fid': fid, 'points': pts_h, 'lid': lid, 'season': sea
                })
                team_history[aid].append({
                    'fid': fid, 'points': pts_a, 'lid': lid, 'season': sea
                })
            
            # --- Forma reciente y contexto temporal pre-calculados ---
            report("Pre-calculando forma reciente...", 30)
            team_recent: Dict[int, Dict[int, float]] = {}
            team_season_ctx: Dict[Tuple, Dict] = {}
            
            for tid, history in team_history.items():
                team_recent[tid] = {}
                season_tracker = {}
                
                for i, m in enumerate(history):
                    key = (m['lid'], m['season'])
                    if key not in season_tracker:
                        season_tracker[key] = {'matches': 0, 'points': 0}
                    
                    st = season_tracker[key]
                    team_season_ctx[(tid, m['fid'])] = {
                        'match_num': st['matches'],
                        'ppg': st['points'] / st['matches'] if st['matches'] > 0 else None,
                    }
                    st['matches'] += 1
                    st['points'] += m['points']
                    
                    if i >= WINDOW:
                        recent = history[i - WINDOW:i]
                        team_recent[tid][m['fid']] = sum(
                            x['points'] for x in recent) / WINDOW
            
            # --- Season lengths ---
            season_counts: Dict[tuple, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
            for fid, dt, lid, sea, hid, aid, gh, ga in fixtures:
                season_counts[(lid, sea)][hid] += 1
                season_counts[(lid, sea)][aid] += 1
            
            season_len = {}
            for key, tc in season_counts.items():
                season_len[key] = int(np.median(list(tc.values()))) if tc else 38
            
            # --- Construir records ---
            report("Construyendo records...", 40)
            records_X, records_y, records_season = [], [], []
            skipped = 0
            
            for fid, dt, lid, sea, hid, aid, gh, ga in fixtures:
                lv_h = self.get_level(hid, str(dt))
                lv_a = self.get_level(aid, str(dt))
                if lv_h is None or lv_a is None:
                    skipped += 1
                    continue
                
                pr_h = team_recent.get(hid, {}).get(fid)
                pr_a = team_recent.get(aid, {}).get(fid)
                if pr_h is None or pr_a is None:
                    skipped += 1
                    continue
                
                gap_h = self.calc_gap(lv_h, pr_h)
                gap_a = self.calc_gap(lv_a, pr_a)
                mu_h = self.calc_mu(lv_h, lv_a, True)
                mu_a = self.calc_mu(lv_a, lv_h, False)
                
                is_intl = 1.0 if lid in LIGAS_INTERNACIONALES else 0.0
                total = season_len.get((lid, sea), 38)
                
                ctx_h = team_season_ctx.get((hid, fid), {'match_num': 15, 'ppg': None})
                ctx_a = team_season_ctx.get((aid, fid), {'match_num': 15, 'ppg': None})
                prog = min(1.0, ctx_h['match_num'] / total) if total > 0 else 0.5
                
                win_h = 1 if gh > ga else 0
                win_a = 1 if ga > gh else 0
                
                # HOME
                records_X.append([
                    gap_h, gap_a, lv_h, lv_a, lv_h - lv_a, 1.0, mu_h,
                    pr_h, pr_a, gap_h - gap_a, prog,
                    ctx_h['ppg'] if ctx_h['ppg'] else 1.3,
                    ctx_a['ppg'] if ctx_a['ppg'] else 1.3,
                    is_intl, ctx_h['match_num'],
                ])
                records_y.append(win_h)
                records_season.append(sea)
                
                # AWAY
                records_X.append([
                    gap_a, gap_h, lv_a, lv_h, lv_a - lv_h, 0.0, mu_a,
                    pr_a, pr_h, gap_a - gap_h, prog,
                    ctx_a['ppg'] if ctx_a['ppg'] else 1.3,
                    ctx_h['ppg'] if ctx_h['ppg'] else 1.3,
                    is_intl, ctx_a['match_num'],
                ])
                records_y.append(win_a)
                records_season.append(sea)
            
            X = np.array(records_X)
            y = np.array(records_y)
            seasons = np.array(records_season)
            
            report(f"Records: {len(X):,} ({len(X)//2:,} partidos x 2), "
                   f"{skipped:,} saltados", 50)
            
            # --- Split temporal ---
            train_mask = seasons <= max_train_season
            test_mask = seasons > max_train_season
            X_train, y_train = X[train_mask], y[train_mask]
            X_test, y_test = X[test_mask], y[test_mask]
            
            report(f"Train: {len(X_train):,} | Test: {len(X_test):,}", 55)
            
            if len(X_test) == 0:
                return TrainingResult(
                    success=False,
                    message=f"No hay datos de test (seasons > {max_train_season}). "
                            "Reduce la temporada maxima.",
                    n_records=len(X), n_train=len(X_train), n_test=0,
                    accuracy=0, auc_roc=0, log_loss=0, mejora_pct=0,
                    elapsed_seconds=time.time() - t0,
                    model_path="", timestamp=datetime.now().isoformat(),
                )
            
            # --- Entrenar baseline ---
            report("Entrenando baseline (sin gap)...", 60)
            # Indices de features sin gap: quitar gap_team(0), gap_opponent(1), gap_diff(9)
            no_gap_idx = [2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14]
            base_clf = HistGradientBoostingClassifier(
                max_iter=200, max_depth=4, learning_rate=0.05,
                min_samples_leaf=50, random_state=42)
            base_cal = CalibratedClassifierCV(base_clf, method='isotonic', cv=3)
            base_cal.fit(X_train[:, no_gap_idx], y_train)
            base_proba = base_cal.predict_proba(X_test[:, no_gap_idx])[:, 1]
            base_ll = log_loss(y_test, base_proba)
            
            # --- Entrenar modelo completo ---
            report("Entrenando HistGBT + calibracion isotonica...", 70)
            clf = HistGradientBoostingClassifier(
                max_iter=200, max_depth=4, learning_rate=0.05,
                min_samples_leaf=50, random_state=42)
            model = CalibratedClassifierCV(clf, method='isotonic', cv=3)
            model.fit(X_train, y_train)
            
            report("Evaluando...", 85)
            y_proba = model.predict_proba(X_test)[:, 1]
            y_pred = (y_proba >= 0.5).astype(int)
            
            acc = float(accuracy_score(y_test, y_pred))
            auc = float(roc_auc_score(y_test, y_proba))
            ll = float(log_loss(y_test, y_proba))
            mejora = (base_ll - ll) / base_ll * 100
            
            # --- Guardar ---
            report("Guardando modelo...", 90)
            os.makedirs(self.model_dir, exist_ok=True)
            
            import joblib
            model_path = os.path.join(self.model_dir, 'regresion_nivel_v2.joblib')
            joblib.dump({
                'model': model,
                'feature_names': FEATURE_NAMES,
                'mu_coefficients': MU_COEFS,
                'window': WINDOW,
                'best_model_name': 'HistGBT',
                'trained_at': datetime.now().isoformat(),
                'train_seasons': f'<={max_train_season}',
            }, model_path)
            
            self.model = model
            
            elapsed = time.time() - t0
            report(f"Completo: AUC={auc:.3f}, Acc={acc:.1%}, "
                   f"mejora={mejora:+.1f}% en {elapsed:.1f}s", 100)
            
            return TrainingResult(
                success=True,
                message=f"Modelo entrenado. AUC={auc:.3f}, Acc={acc:.1%}, "
                        f"mejora vs sin-gap={mejora:+.1f}%",
                n_records=len(X), n_train=len(X_train), n_test=len(X_test),
                accuracy=acc, auc_roc=auc, log_loss=ll, mejora_pct=mejora,
                elapsed_seconds=elapsed, model_path=model_path,
                timestamp=datetime.now().isoformat(),
            )
        
        except Exception as e:
            logger.error(f"Error en entrenamiento: {e}", exc_info=True)
            return TrainingResult(
                success=False, message=f"Error: {str(e)}",
                n_records=0, n_train=0, n_test=0,
                accuracy=0, auc_roc=0, log_loss=0, mejora_pct=0,
                elapsed_seconds=time.time() - t0,
                model_path="", timestamp=datetime.now().isoformat(),
            )