# -*- coding: utf-8 -*-
"""
# MOTOR ANTICULEBRAS v6.1 - LEY DE LAS CULEBRAS
Sistema de prediccion con Machine Learning optimizado.

MEJORAS v6.1 (vs v6):
- 4 nuevas features DINAMICAS de contexto en vivo (live context)
- El ML score se RECALCULA cuando hay resultados reales intra-dia
- Si ya se jugaron 3 de 4 partidos, el 4to usa esos resultados
- Retrocompatible con modelo v6 (14 features) - detecta automaticamente
- Nuevo metodo: recalculate_live() para refrescar scores

Features v6 conservadas (14):
  prob_draw, prob_underdog, icf_diff, accumulated_tension,
  rest_days_diff, is_simultaneous, position_normalized,
  match_importance, n_matches_day, joint_prob_all_favs,
  min_favorite_prob_day, mean_favorite_prob_day,
  weakest_link_rank, n_tight_matches_day

Features v6.1 nuevas (4 dinamicas):
  n_decided_before      - partidos ya terminados antes de este
  n_breaks_before       - favoritos que ya perdieron antes de este
  fav_win_rate_before   - tasa de acierto de favoritos hasta ahora
  snake_intact_before   - 1.0 si la culebra sigue viva, 0.0 si ya se rompio

Autor: Sistema de Analisis Deportivo
"""

import os
import logging
import pickle
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

# ML imports
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report
from sklearn.calibration import CalibratedClassifierCV

# Imports del proyecto
try:
    from data.database_manager import ORIG_ENGINE, CONST_ENGINE, BASE_DIR
except ImportError:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    ORIG_ENGINE = create_engine(f'sqlite:///{os.path.join(BASE_DIR, "sad.db")}')
    CONST_ENGINE = create_engine(f'sqlite:///{os.path.join(BASE_DIR, "constants.db")}')

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class Outcome(Enum):
    HOME = "1"
    DRAW = "X"
    AWAY = "2"
    UNKNOWN = None


class BreakType(Enum):
    BY_DRAW = "draw"
    BY_UNDERDOG = "underdog"
    NOT_BROKEN = None


class FavoriteType(Enum):
    HOME = "home"
    DRAW = "draw"
    AWAY = "away"
    NONE = "none"


class SeasonPhase(Enum):
    EARLY = "early_season"
    MID = "mid_season"
    LATE = "late_season"
    DECISIVE = "decisive"
    PLAYOFF = "playoff"
    FINAL = "final"
    UNKNOWN = "unknown"


# =============================================================================
# CONSTANTES PARA IMPORTANCIA DE PARTIDO
# =============================================================================

PHASE_IMPORTANCE = {
    'early_season': 0.3,
    'mid_season': 0.5,
    'late_season': 0.7,
    'decisive': 0.9,
    'playoff': 0.95,
    'final': 1.0,
    'unknown': 0.5,
}


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class MatchPrediction:
    """Prediccion completa para un partido."""
    fixture_id: int
    date: datetime
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str
    league_id: int
    league_name: str = ""
    
    # ICF calculados
    icf_home: float = 0.0
    icf_away: float = 0.0
    icf_diff: float = 0.0
    
    # Probabilidades 1X2
    prob_home: float = 0.0
    prob_draw: float = 0.0
    prob_away: float = 0.0
    
    # Cuotas sinteticas
    odds_home: float = 0.0
    odds_draw: float = 0.0
    odds_away: float = 0.0
    
    # Favorito
    favorite: str = "none"
    favorite_prob: float = 0.0
    
    # Feature ML: probabilidad del no-favorito
    prob_underdog: float = 0.0
    
    # Probabilidades de ruptura (para compatibilidad, se mantienen)
    prob_break_by_draw: float = 0.0
    prob_break_by_underdog: float = 0.0
    prob_break_total: float = 0.0
    
    # ML: Probabilidad de que ESTE partido rompa la culebra
    ml_break_score: float = 0.0
    ml_break_type_pred: str = ""
    
    # Resultado real
    goals_home: Optional[int] = None
    goals_away: Optional[int] = None
    outcome: Optional[str] = None
    favorite_won: Optional[bool] = None
    broke_snake: Optional[bool] = None
    break_type: Optional[str] = None
    
    # Contexto temporal
    position_in_day: int = 0
    position_normalized: float = 0.0
    is_simultaneous: bool = False
    accumulated_tension: float = 0.0
    inherited_tension: float = 0.0
    
    # IMPORTANCIA DEL PARTIDO
    match_importance: float = 0.5
    season_phase: str = "mid_season"
    jornada_in_season: Optional[int] = None
    total_jornadas: Optional[int] = None
    is_playoff: bool = False
    
    # DIAS DE DESCANSO
    rest_days_home: Optional[int] = None
    rest_days_away: Optional[int] = None
    rest_days_diff: float = 0.0
    
    # [v6] MATCHDAY CONTEXT FEATURES
    n_matches_day: int = 0
    joint_prob_all_favs: float = 0.0
    min_favorite_prob_day: float = 0.0
    mean_favorite_prob_day: float = 0.0
    weakest_link_rank: float = 0.0
    n_tight_matches_day: int = 0
    
    # [v6.1] LIVE/DYNAMIC CONTEXT FEATURES
    # Estas features cambian cuando se actualizan resultados reales
    n_decided_before: int = 0           # partidos ya terminados (FT) antes de este
    n_breaks_before: int = 0            # favoritos que perdieron antes de este
    fav_win_rate_before: float = 0.5    # tasa de acierto de favoritos (0-1)
    snake_intact_before: float = 1.0    # 1.0 = culebra viva, 0.0 = ya se rompio
    
    def get_outcome_display(self) -> str:
        if self.goals_home is None:
            return "vs"
        return f"{self.goals_home} - {self.goals_away}"
    
    def get_favorite_display(self) -> str:
        if self.favorite == "home":
            return f"1 ({self.home_team_name[:15]})"
        elif self.favorite == "away":
            return f"2 ({self.away_team_name[:15]})"
        elif self.favorite == "draw":
            return "X (Empate)"
        return "Parejo"


@dataclass
class DayAnalysis:
    """Analisis de culebra para un dia."""
    date: date
    league_id: int
    league_name: str
    
    matches: List[MatchPrediction] = field(default_factory=list)
    
    # Metricas
    total_matches: int = 0
    matches_with_favorite: int = 0
    
    # Probabilidades
    snake_potential: float = 0.0
    prob_break_total: float = 0.0
    prob_break_by_draw: float = 0.0
    prob_break_by_underdog: float = 0.0
    
    # Tension
    base_tension: float = 0.0
    inherited_tension: float = 0.0
    total_tension: float = 0.0
    
    # Resultado real
    snake_broke: Optional[bool] = None
    break_match_id: Optional[int] = None
    break_type: Optional[str] = None
    break_match_position: Optional[int] = None
    
    # Prediccion
    predicted_break: bool = False
    predicted_break_type: Optional[str] = None
    prediction_correct: Optional[bool] = None
    break_type_correct: Optional[bool] = None
    
    # ML Candidato
    ml_candidate_match: Optional[MatchPrediction] = None
    ml_candidate_position: Optional[int] = None
    ml_candidate_score: float = 0.0
    ml_candidate_reasons: List[str] = field(default_factory=list)
    
    # Ranking ML
    matches_ranked_by_ml: List[Tuple[int, MatchPrediction, float]] = field(default_factory=list)
    
    # [v6.1] Info de contexto en vivo
    n_decided: int = 0          # partidos ya terminados
    n_pending: int = 0          # partidos pendientes
    has_live_context: bool = False  # True si hay mezcla de FT y NS


@dataclass
class JornadaAnalysis:
    """Analisis de jornada completa."""
    league_id: int
    league_name: str
    jornada_num: Optional[int]
    date_start: date
    date_end: date
    
    days: List[DayAnalysis] = field(default_factory=list)
    total_matches: int = 0
    total_days: int = 0
    
    weekly_snake_potential: float = 0.0
    weekly_prob_break: float = 0.0
    
    snake_broke: Optional[bool] = None
    break_day: Optional[date] = None
    break_type: Optional[str] = None
    
    predicted_break_day: Optional[date] = None
    prediction_correct: Optional[bool] = None


@dataclass
class CalibrationResult:
    """Resultado de calibracion."""
    weights: Dict[str, float]
    scale_k: float
    mae: float
    correlation: float
    brier_score: float
    n_samples: int
    leagues_included: List[int]
    timestamp: datetime = field(default_factory=datetime.now)
    n_with_full_constants: int = 0
    n_with_fallback: int = 0
    date_range: str = ""


@dataclass
class MLTrainingResult:
    """Resultado del entrenamiento ML."""
    model_type: str
    accuracy: float
    auc_roc: float
    precision_break: float
    recall_break: float
    n_samples: int
    n_breaks: int
    feature_importances: Dict[str, float]
    timestamp: datetime = field(default_factory=datetime.now)
    cross_val_scores: List[float] = field(default_factory=list)


@dataclass
class ValidationMetrics:
    """Metricas de validacion."""
    total_days: int = 0
    days_snake_broken: int = 0
    days_snake_complete: int = 0
    breaks_by_draw: int = 0
    breaks_by_underdog: int = 0
    correct_break_predictions: int = 0
    correct_break_type_predictions: int = 0
    correct_candidate_predictions: int = 0
    total_jornadas: int = 0
    jornadas_broken: int = 0
    metrics_by_league: Dict[int, Dict] = field(default_factory=dict)


# =============================================================================
# MOTOR PRINCIPAL
# =============================================================================

class AnticulebraEngine:
    """Motor Anticulebras v6.1 con features dinamicas en vivo."""
    
    DEFAULT_WEIGHTS = {
        'k_local': 1.0,
        'k_visita': 1.0,
        'k_positivo': 0.5,
        'k_goles_anotado': 0.8,
        'k_goles_recibido': 0.6,
        'k_negativo': 0.3,
        'nivel': 1.2,
    }
    
    DEFAULT_SCALE_K = 0.15
    FAVORITE_THRESHOLD = 0.40
    TENSION_INHERITANCE_FACTOR = 0.7
    
    # [v6.1] Features ML (14 de v6 + 4 dinamicas = 18 total)
    ML_FEATURES = [
        # === Individual match features (v5) ===
        'prob_draw',
        'prob_underdog',
        'icf_diff',
        'position_normalized',
        'is_simultaneous',
        'accumulated_tension',
        'match_importance',
        'rest_days_diff',
        # === Matchday context features (v6) ===
        'n_matches_day',
        'joint_prob_all_favs',
        'min_favorite_prob_day',
        'mean_favorite_prob_day',
        'weakest_link_rank',
        'n_tight_matches_day',
        # === Live dynamic features (v6.1 NEW) ===
        'n_decided_before',       # cuantos partidos ya terminaron antes de este
        'n_breaks_before',        # cuantos favoritos perdieron antes de este
        'fav_win_rate_before',    # tasa de acierto de favoritos hasta ahora
        'snake_intact_before',    # 1.0 = culebra viva, 0.0 = ya se rompio
    ]
    
    # [v6.1] Features del modelo v6 (para retrocompatibilidad)
    ML_FEATURES_V6 = ML_FEATURES[:14]
    
    def __init__(self, model_path: Optional[str] = None):
        """Inicializa el motor."""
        self.orig_engine = ORIG_ENGINE
        self.const_engine = CONST_ENGINE
        
        self.weights = self.DEFAULT_WEIGHTS.copy()
        self.scale_k = self.DEFAULT_SCALE_K
        self.calibration_result: Optional[CalibrationResult] = None
        
        # Modelos ML
        self.ml_break_model = None
        self.ml_type_model = None
        self.ml_scaler = None
        self.ml_training_result: Optional[MLTrainingResult] = None
        self._ml_model_version = 'v6'  # [v6.1] Track loaded model version
        
        self.model_path = model_path or os.path.join(BASE_DIR, 'anticulebra_model.pkl')
        self.ml_model_path = os.path.join(BASE_DIR, 'anticulebra_ml_model_v6.1.pkl')
        
        # Backward compat: try v6.1, then v6, then v5
        if not os.path.exists(self.ml_model_path):
            for fallback in ['anticulebra_ml_model_v6.pkl', 'anticulebra_ml_model_v5.pkl']:
                fallback_path = os.path.join(BASE_DIR, fallback)
                if os.path.exists(fallback_path):
                    self.ml_model_path = fallback_path
                    logger.info(f"[i] Usando modelo {fallback} (v6.1 no encontrado, reentrenar para upgrade)")
                    break
        
        self._ml_base_model = None
        
        self._load_model()
        self._load_ml_model()
        
        # Cache
        self._constants_cache: Dict[Tuple[int, str], Dict] = {}
        self._levels_cache: Dict[Tuple[int, str], float] = {}
        self._leagues_cache: Dict[int, str] = {}
        self._rest_days_cache: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
        
        logger.info("[OK] AnticulebraEngine v6.1 (dynamic live features) inicializado")
    
    def _load_model(self):
        """Carga modelo de calibracion."""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    data = pickle.load(f)
                    self.weights = data.get('weights', self.DEFAULT_WEIGHTS)
                    self.scale_k = data.get('scale_k', self.DEFAULT_SCALE_K)
                    self.calibration_result = data.get('calibration_result')
                    logger.info(f"[OK] Modelo calibracion cargado")
            except Exception as e:
                logger.warning(f"[!] Error cargando modelo: {e}")
    
    def _save_model(self):
        """Guarda modelo de calibracion."""
        try:
            data = {
                'weights': self.weights,
                'scale_k': self.scale_k,
                'calibration_result': self.calibration_result,
            }
            with open(self.model_path, 'wb') as f:
                pickle.dump(data, f)
            logger.info(f"[OK] Modelo calibracion guardado")
        except Exception as e:
            logger.error(f"Error guardando modelo: {e}")
    
    def _load_ml_model(self):
        """Carga modelo ML entrenado (v5, v6 o v6.1)."""
        if os.path.exists(self.ml_model_path):
            try:
                with open(self.ml_model_path, 'rb') as f:
                    data = pickle.load(f)
                    self.ml_break_model = data.get('break_model')
                    self.ml_type_model = data.get('type_model')
                    self.ml_scaler = data.get('scaler')
                    self.ml_training_result = data.get('training_result')
                    self._ml_base_model = data.get('base_model')
                    version = data.get('version', 'v5')
                    self._ml_model_version = version
                    
                    # [v6.1] Detectar cuantas features espera el modelo
                    if self.ml_scaler is not None:
                        n_features = self.ml_scaler.n_features_in_
                        logger.info(f"[OK] Modelo ML {version} cargado ({n_features} features)")
                    else:
                        logger.info(f"[OK] Modelo ML {version} cargado")
            except Exception as e:
                logger.warning(f"[!] Error cargando modelo ML: {e}")
    
    def _save_ml_model(self):
        """Guarda modelo ML v6.1."""
        try:
            self.ml_model_path = os.path.join(BASE_DIR, 'anticulebra_ml_model_v6.1.pkl')
            data = {
                'break_model': self.ml_break_model,
                'base_model': self._ml_base_model,
                'type_model': self.ml_type_model,
                'scaler': self.ml_scaler,
                'training_result': self.ml_training_result,
                'version': 'v6.1',
                'features': self.ML_FEATURES,
            }
            with open(self.ml_model_path, 'wb') as f:
                pickle.dump(data, f)
            self._ml_model_version = 'v6.1'
            logger.info(f"[OK] Modelo ML v6.1 guardado en {self.ml_model_path}")
        except Exception as e:
            logger.error(f"Error guardando modelo ML: {e}")
    
    # =========================================================================
    # OBTENCION DE DATOS
    # =========================================================================
    
    def get_league_name(self, league_id: int) -> str:
        """Obtiene nombre de liga."""
        if league_id in self._leagues_cache:
            return self._leagues_cache[league_id]
        
        query = text("SELECT name FROM leagues WHERE id = :lid")
        try:
            with self.orig_engine.connect() as conn:
                result = conn.execute(query, {'lid': league_id}).fetchone()
                name = result[0] if result else f"Liga {league_id}"
                self._leagues_cache[league_id] = name
                return name
        except:
            return f"Liga {league_id}"
    
    def get_data_period(self) -> Dict:
        """Obtiene periodo de datos disponibles."""
        query = text("""
            SELECT 
                MIN(f.date) as min_date,
                MAX(f.date) as max_date,
                COUNT(DISTINCT f.id) as total_fixtures,
                COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN f.id END) as total_with_odds
            FROM fixtures f
            LEFT JOIN odds o ON f.id = o.fixture_id AND o.bet_name = 'Match Winner'
            WHERE f.status_short = 'FT'
        """)
        
        with self.orig_engine.connect() as conn:
            result = conn.execute(query).fetchone()
        
        if result:
            min_date = result[0]
            max_date = result[1]
            
            if isinstance(min_date, str):
                try:
                    min_date = datetime.fromisoformat(min_date.replace('Z', '+00:00'))
                except:
                    min_date = None
            if isinstance(max_date, str):
                try:
                    max_date = datetime.fromisoformat(max_date.replace('Z', '+00:00'))
                except:
                    max_date = None
            
            return {
                'min_date': min_date,
                'max_date': max_date,
                'min_year': min_date.year if min_date else None,
                'max_year': max_date.year if max_date else None,
                'total_fixtures': result[2] or 0,
                'total_with_odds': result[3] or 0,
            }
        
        return {'min_date': None, 'max_date': None, 'min_year': None, 
                'max_year': None, 'total_fixtures': 0, 'total_with_odds': 0}
    
    def get_available_leagues(self, require_odds: bool = False) -> List[Dict]:
        """Obtiene ligas disponibles."""
        if require_odds:
            query = text("""
                SELECT DISTINCT 
                    f.league_id,
                    l.name as league_name,
                    l.country as country,
                    COUNT(DISTINCT f.id) as fixture_count,
                    COUNT(DISTINCT o.fixture_id) as fixtures_with_odds
                FROM fixtures f
                LEFT JOIN leagues l ON f.league_id = l.id
                LEFT JOIN odds o ON f.id = o.fixture_id AND o.bet_name = 'Match Winner'
                WHERE f.status_short = 'FT'
                GROUP BY f.league_id
                HAVING fixtures_with_odds > 0
                ORDER BY fixtures_with_odds DESC
            """)
        else:
            query = text("""
                SELECT DISTINCT 
                    f.league_id,
                    l.name as league_name,
                    l.country as country,
                    COUNT(DISTINCT f.id) as fixture_count,
                    0 as fixtures_with_odds
                FROM fixtures f
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE f.status_short = 'FT'
                GROUP BY f.league_id
                HAVING fixture_count >= 50
                ORDER BY fixture_count DESC
            """)
        
        with self.orig_engine.connect() as conn:
            result = conn.execute(query).fetchall()
        
        return [
            {
                'league_id': r[0],
                'league_name': r[1] or f'Liga {r[0]}',
                'country': r[2] or 'Desconocido',
                'fixture_count': r[3],
                'fixtures_with_odds': r[4],
            }
            for r in result
        ]
    
    def get_fixtures_with_odds(self, league_id: int = None, 
                               start_date: datetime = None,
                               end_date: datetime = None,
                               limit: int = None) -> pd.DataFrame:
        """Obtiene fixtures con cuotas."""
        conditions = ["f.status_short = 'FT'", "o.bet_name = 'Match Winner'"]
        params = {}
        
        if league_id:
            conditions.append("f.league_id = :league_id")
            params['league_id'] = league_id
        
        if start_date:
            conditions.append("f.date >= :start_date")
            params['start_date'] = start_date.strftime('%Y-%m-%d')
        
        if end_date:
            conditions.append("f.date <= :end_date")
            params['end_date'] = end_date.strftime('%Y-%m-%d')
        
        where_clause = " AND ".join(conditions)
        limit_clause = f"LIMIT :limit" if limit else ""
        
        query = text(f"""
            SELECT 
                f.id as fixture_id,
                f.date,
                f.league_id,
                f.home_team_id,
                f.away_team_id,
                f.goals_home,
                f.goals_away,
                ht.name as home_team_name,
                at.name as away_team_name,
                MAX(CASE WHEN o.value = 'Home' THEN o.odd END) as odd_home,
                MAX(CASE WHEN o.value = 'Draw' THEN o.odd END) as odd_draw,
                MAX(CASE WHEN o.value = 'Away' THEN o.odd END) as odd_away
            FROM fixtures f
            JOIN teams ht ON f.home_team_id = ht.id
            JOIN teams at ON f.away_team_id = at.id
            JOIN odds o ON f.id = o.fixture_id
            WHERE {where_clause}
            GROUP BY f.id
            HAVING odd_home IS NOT NULL AND odd_draw IS NOT NULL AND odd_away IS NOT NULL
            ORDER BY f.date DESC
            {limit_clause}
        """)
        
        if limit:
            params['limit'] = limit
        
        with self.orig_engine.connect() as conn:
            df = pd.read_sql(query, conn, params=params)
        
        if df.empty:
            return df
        
        df['prob_home_raw'] = 1 / df['odd_home']
        df['prob_draw_raw'] = 1 / df['odd_draw']
        df['prob_away_raw'] = 1 / df['odd_away']
        df['margin'] = df['prob_home_raw'] + df['prob_draw_raw'] + df['prob_away_raw']
        
        df['prob_home_norm'] = df['prob_home_raw'] / df['margin']
        df['prob_draw_norm'] = df['prob_draw_raw'] / df['margin']
        df['prob_away_norm'] = df['prob_away_raw'] / df['margin']
        
        return df
    
    def get_fixtures_for_date(self, league_id: int, target_date: date) -> List[Dict]:
        """Obtiene fixtures de un dia (terminados y programados)."""
        query = text("""
            SELECT 
                f.id as fixture_id,
                f.date,
                f.league_id,
                f.home_team_id,
                f.away_team_id,
                f.goals_home,
                f.goals_away,
                f.status_short,
                f.league_round,
                COALESCE(ht.name, 'Equipo ' || f.home_team_id) as home_team_name,
                COALESCE(at.name, 'Equipo ' || f.away_team_id) as away_team_name
            FROM fixtures f
            LEFT JOIN teams ht ON f.home_team_id = ht.id
            LEFT JOIN teams at ON f.away_team_id = at.id
            WHERE f.league_id = :league_id
              AND DATE(f.date) = :target_date
              AND f.status_short IN ('FT', 'NS')
            ORDER BY f.date ASC
        """)
        
        with self.orig_engine.connect() as conn:
            result = conn.execute(query, {
                'league_id': league_id,
                'target_date': target_date.strftime('%Y-%m-%d'),
            }).fetchall()
        
        columns = ['fixture_id', 'date', 'league_id', 'home_team_id', 'away_team_id',
                   'goals_home', 'goals_away', 'status', 'round', 'home_team_name', 'away_team_name']
        
        return [dict(zip(columns, r)) for r in result]
    
    def get_available_dates(self, league_id: int, 
                            start_date: date = None,
                            end_date: date = None) -> List[date]:
        """Obtiene fechas con partidos."""
        conditions = ["f.league_id = :league_id", "f.status_short = 'FT'"]
        params = {'league_id': league_id}
        
        if start_date:
            conditions.append("DATE(f.date) >= :start_date")
            params['start_date'] = start_date.strftime('%Y-%m-%d')
        if end_date:
            conditions.append("DATE(f.date) <= :end_date")
            params['end_date'] = end_date.strftime('%Y-%m-%d')
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
            SELECT DISTINCT DATE(f.date) as match_date
            FROM fixtures f
            WHERE {where_clause}
            ORDER BY match_date DESC
        """)
        
        with self.orig_engine.connect() as conn:
            result = conn.execute(query, params).fetchall()
        
        dates = []
        for r in result:
            if r[0]:
                if isinstance(r[0], str):
                    dates.append(datetime.strptime(r[0], '%Y-%m-%d').date())
                else:
                    dates.append(r[0])
        
        return dates
    
    def get_constants_before_date(self, team_id: int, before_date: datetime) -> Optional[Dict]:
        """Obtiene constantes de un equipo."""
        cache_key = (team_id, before_date.strftime('%Y-%m-%d'))
        if cache_key in self._constants_cache:
            return self._constants_cache[cache_key]
        
        query = text("""
            SELECT *
            FROM constants
            WHERE team_id = :team_id AND date < :before_date
            ORDER BY date DESC
            LIMIT 1
        """)
        
        try:
            with self.const_engine.connect() as conn:
                result = conn.execute(query, {
                    'team_id': team_id,
                    'before_date': before_date.strftime('%Y-%m-%d %H:%M:%S')
                }).fetchone()
            
            if result:
                columns = ['id', 'team_id', 'fixture_id', 'date',
                          'q_local', 'q_visita', 'q_negativo',
                          'q_goles_anotado', 'q_goles_recibido',
                          'q_goles_local_anotado', 'q_goles_local_recibido',
                          'q_goles_visita_anotado', 'q_goles_visita_recibido',
                          'k_positivo', 'k_negativo',
                          'k_positivo_local', 'k_negativo_local',
                          'k_positivo_visita', 'k_negativo_visita',
                          'k_goles_anotado', 'k_goles_recibido',
                          'k_goles_local_anotado', 'k_goles_local_recibido',
                          'k_goles_visita_anotado', 'k_goles_visita_recibido']
                
                data = dict(zip(columns, result))
                self._constants_cache[cache_key] = data
                return data
        except Exception as e:
            logger.debug(f"Sin constantes para team {team_id}: {e}")
        
        return None
    
    def get_team_level(self, team_id: int, at_date: datetime) -> float:
        """Obtiene nivel de un equipo."""
        cache_key = (team_id, at_date.strftime('%Y-%m-%d'))
        if cache_key in self._levels_cache:
            return self._levels_cache[cache_key]
        
        levels_db_path = os.path.join(BASE_DIR, 'levels.db')
        if not os.path.exists(levels_db_path):
            return 1.0
        
        try:
            levels_engine = create_engine(f'sqlite:///{levels_db_path}')
            query = text("""
                SELECT level
                FROM team_levels
                WHERE team_id = :team_id AND date <= :at_date
                ORDER BY date DESC
                LIMIT 1
            """)
            
            with levels_engine.connect() as conn:
                result = conn.execute(query, {
                    'team_id': team_id,
                    'at_date': at_date.strftime('%Y-%m-%d')
                }).fetchone()
            
            level = result[0] if result else 1.0
            self._levels_cache[cache_key] = level
            return level
        except:
            return 1.0
    
    # =========================================================================
    # CALCULO DE DIAS DE DESCANSO
    # =========================================================================
    
    def calculate_rest_days(self, team_id: int, match_date: datetime,
                            max_lookback_days: int = 30) -> Optional[int]:
        """Calcula dias de descanso desde el ultimo partido."""
        query = text("""
            SELECT MAX(date) as last_match
            FROM fixtures
            WHERE (home_team_id = :team_id OR away_team_id = :team_id)
              AND date < :match_date
              AND date >= :min_date
              AND status_short = 'FT'
        """)
        
        min_date = match_date - timedelta(days=max_lookback_days)
        
        try:
            with self.orig_engine.connect() as conn:
                result = conn.execute(query, {
                    'team_id': team_id,
                    'match_date': match_date.strftime('%Y-%m-%d %H:%M:%S'),
                    'min_date': min_date.strftime('%Y-%m-%d'),
                }).fetchone()
            
            if result and result[0]:
                last_match = result[0]
                if isinstance(last_match, str):
                    last_match = datetime.fromisoformat(last_match.replace('Z', '+00:00'))
                
                delta = match_date - last_match
                return delta.days
        except Exception as e:
            logger.debug(f"Error calculando descanso para team {team_id}: {e}")
        
        return None
    
    def calculate_rest_days_diff(self, rest_home: Optional[int],
                                  rest_away: Optional[int],
                                  favorite: str) -> float:
        """Calcula diferencia de descanso desde perspectiva del favorito."""
        if rest_home is None or rest_away is None:
            return 0.0
        
        diff = rest_home - rest_away
        diff_normalized = np.clip(diff / 7.0, -1.0, 1.0)
        
        if favorite == "away":
            diff_normalized = -diff_normalized
        elif favorite in ("draw", "none"):
            diff_normalized = -abs(diff_normalized)
        
        return diff_normalized
    
    def precompute_rest_days_batch(self, league_id: int = None) -> Dict[int, Tuple[Optional[int], Optional[int]]]:
        """Pre-calcula dias de descanso para todos los partidos (eficiente)."""
        conditions = ["status_short = 'FT'"]
        params = {}
        
        if league_id:
            conditions.append("league_id = :league_id")
            params['league_id'] = league_id
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
            SELECT id, date, home_team_id, away_team_id
            FROM fixtures
            WHERE {where_clause}
            ORDER BY date ASC
        """)
        
        with self.orig_engine.connect() as conn:
            all_fixtures = pd.read_sql(query, conn, params=params)
        
        if all_fixtures.empty:
            return {}
        
        team_last_match: Dict[int, datetime] = {}
        fixture_rest: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
        
        for _, row in all_fixtures.iterrows():
            fx_id = row['id']
            match_date = pd.to_datetime(row['date'])
            home_id = row['home_team_id']
            away_id = row['away_team_id']
            
            rest_home = None
            rest_away = None
            
            if home_id in team_last_match:
                delta = (match_date - team_last_match[home_id]).days
                if 0 < delta <= 30:
                    rest_home = delta
            
            if away_id in team_last_match:
                delta = (match_date - team_last_match[away_id]).days
                if 0 < delta <= 30:
                    rest_away = delta
            
            fixture_rest[fx_id] = (rest_home, rest_away)
            
            team_last_match[home_id] = match_date
            team_last_match[away_id] = match_date
        
        self._rest_days_cache.update(fixture_rest)
        
        return fixture_rest
    
    # =========================================================================
    # CALCULO DE IMPORTANCIA DEL PARTIDO
    # =========================================================================
    
    def calculate_match_importance(self, fixture_id: int, league_id: int,
                                    match_date: datetime,
                                    round_str: Optional[str] = None) -> Tuple[float, str]:
        """Calcula la importancia del partido (0-1)."""
        if round_str:
            round_lower = round_str.lower()
            if 'final' in round_lower and 'semi' not in round_lower:
                return (1.0, "final")
            elif 'semi' in round_lower:
                return (0.95, "playoff")
            elif 'quarter' in round_lower or 'cuartos' in round_lower:
                return (0.9, "playoff")
            elif any(x in round_lower for x in ['playoff', 'liguilla', 'eliminat']):
                return (0.85, "playoff")
        
        jornada, total = self._get_jornada_info(fixture_id, league_id, match_date, round_str)
        
        if jornada is None or total is None:
            return self._importance_by_month(match_date)
        
        progress = jornada / total
        
        if progress <= 0.25:
            return (0.3, "early_season")
        elif progress <= 0.70:
            return (0.5, "mid_season")
        elif progress <= 0.85:
            return (0.7, "late_season")
        else:
            return (0.9, "decisive")
    
    def _get_jornada_info(self, fixture_id: int, league_id: int,
                          match_date: datetime,
                          round_str: Optional[str] = None) -> Tuple[Optional[int], Optional[int]]:
        """Extrae numero de jornada del round string."""
        if round_str and "Regular Season" in round_str:
            parts = round_str.split("-")
            if len(parts) >= 2:
                try:
                    jornada = int(parts[-1].strip())
                    total = self._estimate_total_jornadas(league_id, match_date)
                    return (jornada, total)
                except ValueError:
                    pass
        
        return (None, None)
    
    def _estimate_total_jornadas(self, league_id: int, at_date: datetime) -> int:
        """Estima total de jornadas basado en estructura tipica."""
        year = at_date.year
        if at_date.month < 7:
            season_start = datetime(year - 1, 7, 1)
        else:
            season_start = datetime(year, 7, 1)
        
        query = text("""
            SELECT COUNT(DISTINCT id) as total_matches
            FROM fixtures
            WHERE league_id = :league_id
              AND date >= :season_start
              AND status_short = 'FT'
        """)
        
        try:
            with self.orig_engine.connect() as conn:
                result = conn.execute(query, {
                    'league_id': league_id,
                    'season_start': season_start.strftime('%Y-%m-%d'),
                }).fetchone()
            
            if result:
                matches = result[0] or 0
                if matches > 300:
                    return 38
                elif matches > 250:
                    return 34
                elif matches > 150:
                    return 30
                else:
                    return 18
        except:
            pass
        
        return 38
    
    def _importance_by_month(self, match_date: datetime) -> Tuple[float, str]:
        """Heuristica de importancia por mes."""
        month = match_date.month
        
        if month in [8, 9, 10]:
            return (0.3, "early_season")
        elif month in [11, 12, 1, 2]:
            return (0.5, "mid_season")
        elif month in [3, 4]:
            return (0.7, "late_season")
        else:
            return (0.9, "decisive")
    
    # =========================================================================
    # CALCULO DE ICF Y PROBABILIDADES
    # =========================================================================
    
    @staticmethod
    def _safe_k(value, default=0.0):
        '''Obtiene valor de constante k: None -> default, 0 se respeta como 0 (racha rota).'''
        if value is None:
            return default
        return float(value)
    
    @staticmethod
    def _compress_k(k: float) -> float:
        '''
        Comprime constantes k con log para evitar que rachas largas
        dominen el ICF. k son acumuladores sin techo (hasta 30+),
        mientras que nivel va de 1-3.5. Sin compresion,
        0.21 x 29.7 = 6.24 aplasta a 1.0 x 2.5 del nivel.
        log(1+k): k=0->0, k=1->0.69, k=10->2.40, k=30->3.43
        '''
        return np.log1p(abs(k))
    
    def calculate_icf(self, team_id: int, is_home: bool, before_date: datetime) -> float:
        """
        Calcula el Indice Compuesto de Favoritismo.
        
        Fixes aplicados:
        - FIX 1: Log compression en k (evita que rachas extremas dominen)
        - FIX 2: Usa peso k_visita para visitante (antes siempre usaba k_local)
        - FIX 3: k=0 se respeta como racha rota (antes 'or 1.0' lo convertia a 1.0)
        """
        constants = self.get_constants_before_date(team_id, before_date)
        
        if not constants:
            constants = {
                'k_positivo_local': 0.0, 'k_positivo_visita': 0.0,
                'k_goles_local_anotado': 0.0, 'k_goles_local_recibido': 0.0,
                'k_goles_visita_anotado': 0.0, 'k_goles_visita_recibido': 0.0,
                'k_negativo_local': 0.0, 'k_negativo_visita': 0.0,
            }
        
        nivel = self.get_team_level(team_id, before_date)
        if nivel == 0:
            nivel = 1.0
        
        # FIX 3: _safe_k respeta k=0 como racha rota (antes 'or 1.0' lo convertia)
        if is_home:
            k_base = self._safe_k(constants.get('k_positivo_local'))
            k_goles_a = self._safe_k(constants.get('k_goles_local_anotado'))
            k_goles_r = self._safe_k(constants.get('k_goles_local_recibido'))
            k_neg = self._safe_k(constants.get('k_negativo_local'))
        else:
            k_base = self._safe_k(constants.get('k_positivo_visita'))
            k_goles_a = self._safe_k(constants.get('k_goles_visita_anotado'))
            k_goles_r = self._safe_k(constants.get('k_goles_visita_recibido'))
            k_neg = self._safe_k(constants.get('k_negativo_visita'))
        
        # FIX 1: Comprimir k con log para que rachas extremas no dominen
        k_base_c = self._compress_k(k_base)
        k_goles_a_c = self._compress_k(k_goles_a)
        k_goles_r_c = self._compress_k(k_goles_r)
        k_neg_c = self._compress_k(k_neg)
        
        w = self.weights
        # FIX 2: Usar k_visita para visitante (antes siempre usaba k_local)
        w_base = w.get('k_local', 1.0) if is_home else w.get('k_visita', 1.0)
        
        icf = (
            w_base * k_base_c +
            w.get('k_goles_anotado', 0.8) * k_goles_a_c -
            w.get('k_goles_recibido', 0.6) * k_goles_r_c -
            w.get('k_negativo', 0.3) * k_neg_c +
            w.get('nivel', 1.2) * nivel
        )
        
        return icf
    
    def icf_to_probability(self, icf_home: float, icf_away: float) -> Tuple[float, float, float]:
        """Convierte ICF a probabilidades 1X2."""
        delta = icf_home - icf_away
        
        home_strength = 1 / (1 + np.exp(-self.scale_k * delta))
        
        draw_factor = np.exp(-0.3 * abs(delta))
        base_draw = 0.26
        prob_draw = base_draw * (0.5 + draw_factor)
        prob_draw = min(max(prob_draw, 0.15), 0.40)
        
        remaining = 1 - prob_draw
        prob_home = home_strength * remaining
        prob_away = (1 - home_strength) * remaining
        
        total = prob_home + prob_draw + prob_away
        
        return (prob_home/total, prob_draw/total, prob_away/total)
    
    def determine_favorite(self, prob_home: float, prob_draw: float, 
                           prob_away: float) -> Tuple[str, float]:
        """Determina el favorito."""
        probs = {'home': prob_home, 'draw': prob_draw, 'away': prob_away}
        max_type = max(probs, key=probs.get)
        max_prob = probs[max_type]
        
        if max_prob < self.FAVORITE_THRESHOLD:
            return ("none", max_prob)
        
        return (max_type, max_prob)
    
    def calculate_prob_underdog(self, favorite: str, prob_home: float,
                                 prob_draw: float, prob_away: float) -> float:
        """Calcula probabilidad del no-favorito (underdog)."""
        if favorite == "home":
            return prob_away
        elif favorite == "away":
            return prob_home
        elif favorite == "draw":
            return max(prob_home, prob_away)
        else:
            return min(prob_home, prob_away)
    
    def calculate_break_probabilities(self, favorite: str, 
                                       prob_home: float, prob_draw: float, 
                                       prob_away: float) -> Tuple[float, float, float]:
        """Calcula probabilidades de ruptura (para compatibilidad)."""
        if favorite == "home":
            return (prob_draw, prob_away, prob_draw + prob_away)
        elif favorite == "away":
            return (prob_draw, prob_home, prob_draw + prob_home)
        elif favorite == "draw":
            return (0.0, prob_home + prob_away, prob_home + prob_away)
        else:
            return (prob_draw, max(prob_home, prob_away), 0.5)
    
    def determine_outcome(self, goals_home: int, goals_away: int) -> str:
        """Determina el resultado 1X2."""
        if goals_home > goals_away:
            return "1"
        elif goals_home < goals_away:
            return "2"
        else:
            return "X"
    
    def check_favorite_won(self, favorite: str, outcome: str) -> Tuple[bool, Optional[str]]:
        """Verifica si gano el favorito."""
        if favorite == "none":
            return (None, None)
        
        favorite_outcome_map = {"home": "1", "draw": "X", "away": "2"}
        expected_outcome = favorite_outcome_map.get(favorite)
        
        if outcome == expected_outcome:
            return (True, None)
        else:
            if outcome == "X" and favorite != "draw":
                return (False, "draw")
            else:
                return (False, "underdog")
    
    # =========================================================================
    # PREDICCION DE PARTIDO
    # =========================================================================
    
    def predict_match(self, fixture_id: int = None,
                      home_team_id: int = None, away_team_id: int = None,
                      match_date: datetime = None,
                      home_team_name: str = "", away_team_name: str = "",
                      league_id: int = None,
                      goals_home: int = None, goals_away: int = None,
                      round_str: str = None) -> MatchPrediction:
        """Genera prediccion para un partido."""
        if match_date is None:
            match_date = datetime.now()
        
        icf_home = self.calculate_icf(home_team_id, is_home=True, before_date=match_date)
        icf_away = self.calculate_icf(away_team_id, is_home=False, before_date=match_date)
        
        prob_home, prob_draw, prob_away = self.icf_to_probability(icf_home, icf_away)
        favorite, favorite_prob = self.determine_favorite(prob_home, prob_draw, prob_away)
        
        prob_underdog = self.calculate_prob_underdog(favorite, prob_home, prob_draw, prob_away)
        
        prob_break_draw, prob_break_under, prob_break_total = self.calculate_break_probabilities(
            favorite, prob_home, prob_draw, prob_away
        )
        
        match_importance, season_phase = self.calculate_match_importance(
            fixture_id, league_id, match_date, round_str
        )
        
        if fixture_id and fixture_id in self._rest_days_cache:
            rest_home, rest_away = self._rest_days_cache[fixture_id]
        else:
            rest_home = self.calculate_rest_days(home_team_id, match_date)
            rest_away = self.calculate_rest_days(away_team_id, match_date)
        
        rest_days_diff = self.calculate_rest_days_diff(rest_home, rest_away, favorite)
        
        pred = MatchPrediction(
            fixture_id=fixture_id or 0,
            date=match_date,
            home_team_id=home_team_id,
            home_team_name=home_team_name,
            away_team_id=away_team_id,
            away_team_name=away_team_name,
            league_id=league_id or 0,
            league_name=self.get_league_name(league_id) if league_id else "",
            icf_home=icf_home,
            icf_away=icf_away,
            icf_diff=abs(icf_home - icf_away),
            prob_home=prob_home,
            prob_draw=prob_draw,
            prob_away=prob_away,
            prob_underdog=prob_underdog,
            odds_home=1/prob_home if prob_home > 0.01 else 99,
            odds_draw=1/prob_draw if prob_draw > 0.01 else 99,
            odds_away=1/prob_away if prob_away > 0.01 else 99,
            favorite=favorite,
            favorite_prob=favorite_prob,
            prob_break_by_draw=prob_break_draw,
            prob_break_by_underdog=prob_break_under,
            prob_break_total=prob_break_total,
            goals_home=goals_home,
            goals_away=goals_away,
            match_importance=match_importance,
            season_phase=season_phase,
            rest_days_home=rest_home,
            rest_days_away=rest_away,
            rest_days_diff=rest_days_diff,
        )
        
        if goals_home is not None and goals_away is not None:
            pred.outcome = self.determine_outcome(goals_home, goals_away)
            pred.favorite_won, pred.break_type = self.check_favorite_won(favorite, pred.outcome)
            pred.broke_snake = not pred.favorite_won if pred.favorite_won is not None else None
        
        return pred
    
    # =========================================================================
    # [v6] MATCHDAY CONTEXT FEATURES
    # =========================================================================
    
    def _compute_matchday_features(self, predictions: List[MatchPrediction]):
        """[v6] Computa features de contexto de jornada."""
        if not predictions:
            return
        
        with_fav = [p for p in predictions if p.favorite != "none"]
        n_total = len(predictions)
        n_with_fav = len(with_fav)
        
        if n_with_fav == 0:
            for p in predictions:
                p.n_matches_day = n_total
                p.joint_prob_all_favs = 0.0
                p.min_favorite_prob_day = 0.0
                p.mean_favorite_prob_day = 0.0
                p.weakest_link_rank = 0.5
                p.n_tight_matches_day = 0
            return
        
        fav_probs = [p.favorite_prob for p in with_fav]
        
        joint_prob = 1.0
        for fp in fav_probs:
            joint_prob *= max(fp, 0.01)
        
        min_fav_prob = min(fav_probs)
        mean_fav_prob = sum(fav_probs) / len(fav_probs)
        n_tight = sum(1 for fp in fav_probs if fp < 0.55)
        
        sorted_by_risk = sorted(predictions, key=lambda p: p.favorite_prob if p.favorite != "none" else 1.0)
        risk_ranks = {}
        for rank, p in enumerate(sorted_by_risk):
            risk_ranks[p.fixture_id] = 1.0 - (rank / max(len(sorted_by_risk) - 1, 1))
        
        for p in predictions:
            p.n_matches_day = n_total
            p.joint_prob_all_favs = joint_prob
            p.min_favorite_prob_day = min_fav_prob
            p.mean_favorite_prob_day = mean_fav_prob
            p.weakest_link_rank = risk_ranks.get(p.fixture_id, 0.5)
            p.n_tight_matches_day = n_tight
    
    # =========================================================================
    # [v6.1] LIVE DYNAMIC CONTEXT FEATURES
    # =========================================================================
    
    def _compute_live_context_features(self, predictions: List[MatchPrediction]):
        """
        [v6.1] Computa features DINAMICAS basadas en resultados reales.
        
        Recorre los partidos en orden cronologico. Para cada partido:
        - Cuenta cuantos anteriores ya terminaron (FT)
        - Cuenta cuantos favoritos ya perdieron
        - Calcula tasa de acierto de favoritos
        - Indica si la culebra sigue intacta
        
        CLAVE: Estas features CAMBIAN cuando se actualizan resultados.
        Si el partido 1 y 2 ya terminaron y se rompio la culebra,
        el partido 3 (pendiente) vera n_breaks_before=1, snake_intact=0.0
        
        Para entrenamiento: todos los partidos son FT, asi que las features
        reflejan el contexto real en el momento de cada partido.
        
        Para prediccion en vivo: los partidos FT informan a los NS.
        """
        if not predictions:
            return
        
        n_decided = 0        # partidos ya terminados
        n_fav_decided = 0    # de esos, cuantos tenian favorito definido
        n_fav_wins = 0       # favoritos que ganaron
        n_breaks = 0         # favoritos que perdieron
        snake_intact = True  # la culebra sigue viva?
        
        for p in predictions:
            # === ASIGNAR features ANTES de procesar este partido ===
            p.n_decided_before = n_decided
            p.n_breaks_before = n_breaks
            
            # Tasa de acierto: solo sobre partidos con favorito definido
            if n_fav_decided > 0:
                p.fav_win_rate_before = n_fav_wins / n_fav_decided
            else:
                p.fav_win_rate_before = 0.5  # prior neutral
            
            p.snake_intact_before = 1.0 if snake_intact else 0.0
            
            # === PROCESAR resultado de este partido (si existe) ===
            if p.outcome is not None:
                n_decided += 1
                
                if p.favorite != "none":
                    n_fav_decided += 1
                    if p.favorite_won:
                        n_fav_wins += 1
                    else:
                        n_breaks += 1
                        snake_intact = False
    
    # =========================================================================
    # GENERACION DE DATASET ML
    # =========================================================================
    
    def generate_ml_dataset(self, league_ids: List[int] = None,
                            start_date: date = None,
                            end_date: date = None,
                            min_matches_per_day: int = 2,
                            progress_callback=None) -> pd.DataFrame:
        """Genera dataset para entrenar el modelo ML v6.1 con features dinamicas."""
        logger.info("[i] Generando dataset ML v6.1...")
        
        EXCLUDE_LEAGUES = {667}  # Ligas excluidas del entrenamiento
        
        if league_ids is None:
            leagues = self.get_available_leagues(require_odds=False)
            league_ids = [l['league_id'] for l in leagues[:20]]
        
        league_ids = [lid for lid in league_ids if lid not in EXCLUDE_LEAGUES]
        logger.info(f"[i] Ligas seleccionadas: {league_ids}")
        
        if start_date is None:
            period = self.get_data_period()
            start_date = period['min_date'].date() if period['min_date'] else date(2022, 1, 1)
            logger.info(f"[i] Fecha inicio: {start_date}")
        
        if end_date is None:
            end_date = date.today()
            logger.info(f"[i] Fecha fin: {end_date}")
        
        logger.info("[i] Pre-calculando dias de descanso...")
        for league_id in league_ids:
            self.precompute_rest_days_batch(league_id)
        
        all_rows = []
        total_days = 0
        total_breaks = 0
        leagues_processed = 0
        
        for league_idx, league_id in enumerate(league_ids):
            if progress_callback:
                progress_callback(int(league_idx / len(league_ids) * 100), 
                                 f"Procesando liga {league_id}...")
            
            available_dates = self.get_available_dates(league_id, start_date, end_date)
            
            if not available_dates:
                logger.debug(f"Liga {league_id}: sin fechas disponibles")
                continue
            
            logger.debug(f"Liga {league_id}: {len(available_dates)} fechas disponibles")
            league_rows = 0
            
            for d in sorted(available_dates):
                try:
                    day_rows, broke, break_pos, break_type = self._analyze_day_for_dataset(
                        league_id, d, min_matches_per_day
                    )
                    
                    if day_rows:
                        total_days += 1
                        if broke:
                            total_breaks += 1
                        all_rows.extend(day_rows)
                        league_rows += len(day_rows)
                        
                except Exception as e:
                    logger.debug(f"Error procesando {d}: {e}")
                    continue
            
            if league_rows > 0:
                leagues_processed += 1
                logger.info(f"Liga {league_id}: {league_rows} filas generadas")
        
        if not all_rows:
            logger.warning(f"[!] No se generaron datos.")
            return pd.DataFrame()
        
        df = pd.DataFrame(all_rows)
        
        logger.info(f"[OK] Dataset v6.1 generado:")
        logger.info(f"   - {len(df)} muestras totales")
        logger.info(f"   - {total_days} dias analizados")
        logger.info(f"   - {total_breaks} rupturas detectadas ({total_breaks/total_days*100:.1f}%)")
        logger.info(f"   - {leagues_processed} ligas procesadas")
        
        return df
    
    def _analyze_day_for_dataset(self, league_id: int, target_date: date, 
                                   min_matches: int = 2) -> Tuple[List[Dict], bool, int, str]:
        """Analiza un dia para generar filas del dataset."""
        fixtures = self.get_fixtures_for_date(league_id, target_date)
        
        if not fixtures or len(fixtures) < min_matches:
            return [], False, 0, ""
        
        # Generar predicciones
        predictions = []
        for i, fx in enumerate(fixtures):
            match_dt = pd.to_datetime(fx['date']) if fx['date'] else datetime.combine(target_date, datetime.min.time())
            
            pred = self.predict_match(
                fixture_id=fx['fixture_id'],
                home_team_id=fx['home_team_id'],
                away_team_id=fx['away_team_id'],
                match_date=match_dt,
                home_team_name=fx['home_team_name'],
                away_team_name=fx['away_team_name'],
                league_id=league_id,
                goals_home=fx['goals_home'],
                goals_away=fx['goals_away'],
                round_str=fx.get('round'),
            )
            
            pred.position_in_day = i + 1
            pred.position_normalized = (i + 1) / len(fixtures)
            predictions.append(pred)
        
        # Detectar simultaneos y calcular tension
        self._mark_simultaneous(predictions)
        self._calculate_accumulated_tension(predictions, 0.0)
        
        # [v6] Computar features de contexto de jornada
        self._compute_matchday_features(predictions)
        
        # [v6.1] Computar features DINAMICAS (usa resultados reales)
        self._compute_live_context_features(predictions)
        
        # Verificar cual rompio
        snake_broke = False
        break_position = 0
        break_type = ""
        
        for i, p in enumerate(predictions):
            if p.broke_snake:
                snake_broke = True
                break_position = i + 1
                break_type = p.break_type or ""
                break
        
        # [v6.1 FIX] Generar filas para TODOS los partidos del dia,
        # incluyendo los posteriores a la ruptura.
        # Los post-ruptura reciben broke_snake=0, snake_intact_before=0.0
        # Asi el modelo aprende: "culebra ya rota = no rompe de nuevo"
        rows = []
        for i, p in enumerate(predictions):
            
            row = {
                'date': target_date,
                'league_id': league_id,
                'fixture_id': p.fixture_id,
                'home_team': p.home_team_name,
                'away_team': p.away_team_name,
                
                # Features individuales (v5)
                'prob_draw': p.prob_draw,
                'prob_underdog': p.prob_underdog,
                'icf_diff': p.icf_diff,
                'position_normalized': p.position_normalized,
                'is_simultaneous': 1 if p.is_simultaneous else 0,
                'accumulated_tension': p.accumulated_tension,
                'match_importance': p.match_importance,
                'rest_days_diff': p.rest_days_diff,
                
                # [v6] Features de contexto de jornada
                'n_matches_day': p.n_matches_day,
                'joint_prob_all_favs': p.joint_prob_all_favs,
                'min_favorite_prob_day': p.min_favorite_prob_day,
                'mean_favorite_prob_day': p.mean_favorite_prob_day,
                'weakest_link_rank': p.weakest_link_rank,
                'n_tight_matches_day': p.n_tight_matches_day,
                
                # [v6.1] Features DINAMICAS
                'n_decided_before': p.n_decided_before,
                'n_breaks_before': p.n_breaks_before,
                'fav_win_rate_before': p.fav_win_rate_before,
                'snake_intact_before': p.snake_intact_before,
                
                # Target
                'broke_snake': 1 if (snake_broke and (i + 1) == break_position) else 0,
                'break_type': break_type if (snake_broke and (i + 1) == break_position) else "",
                
                # Meta (para analisis)
                'total_matches_day': len(fixtures),
                'outcome': p.outcome or "",
                'favorite': p.favorite,
                'favorite_prob': p.favorite_prob,
                'season_phase': p.season_phase,
                'rest_days_home': p.rest_days_home,
                'rest_days_away': p.rest_days_away,
            }
            rows.append(row)
        
        return rows, snake_broke, break_position, break_type
    
    # =========================================================================
    # ENTRENAMIENTO ML
    # =========================================================================
    
    def train_ml_model(self, df: pd.DataFrame = None,
                       test_size: float = 0.2,
                       use_smote: bool = False,
                       progress_callback=None) -> MLTrainingResult:
        """
        [v6.1] Entrena GradientBoosting + CalibratedClassifierCV con 18 features.
        
        Ahora incluye 4 features dinamicas que capturan resultados intra-dia.
        """
        logger.info("[v6.1] Entrenando modelo ML v6.1 (con features dinamicas)...")
        
        if df is None:
            if progress_callback:
                progress_callback(5, "Generando dataset v6.1...")
            df = self.generate_ml_dataset(progress_callback=progress_callback)
        
        if df.empty or len(df) < 100:
            raise ValueError(f"Dataset insuficiente: {len(df)} muestras")
        
        if progress_callback:
            progress_callback(50, "Preparando features v6.1 (18 features)...")
        
        feature_cols = self.ML_FEATURES
        X = df[feature_cols].fillna(0)
        y = df['broke_snake'].values
        
        n_breaks = int(y.sum())
        n_total = len(y)
        logger.info(f"[i] Balance: {n_breaks} rupturas de {n_total} ({n_breaks/n_total*100:.1f}%)")
        logger.info(f"[i] Features: {len(feature_cols)} ({feature_cols})")
        
        # Split temporal 3-way: 70% train, 15% calibracion, 15% test
        split_train = int(len(X) * 0.70)
        split_cal = int(len(X) * 0.85)
        
        X_train = X.iloc[:split_train]
        X_cal = X.iloc[split_train:split_cal]
        X_test = X.iloc[split_cal:]
        y_train = y[:split_train]
        y_cal = y[split_train:split_cal]
        y_test = y[split_cal:]
        
        logger.info(f"[i] Split: train={len(X_train)}, cal={len(X_cal)}, test={len(X_test)}")
        
        # SMOTE opcional (solo en train)
        if use_smote:
            try:
                from imblearn.over_sampling import SMOTE
                if progress_callback:
                    progress_callback(55, "Aplicando SMOTE...")
                smote = SMOTE(sampling_strategy=0.5, k_neighbors=5, random_state=42)
                X_train_values, y_train = smote.fit_resample(X_train.values, y_train)
                X_train = pd.DataFrame(X_train_values, columns=feature_cols)
                logger.info(f"[i] Post-SMOTE: {sum(y_train)} rupturas de {len(y_train)}")
            except ImportError:
                logger.warning("[!] imblearn no instalado, continuando sin SMOTE")
        
        # Scaler
        self.ml_scaler = StandardScaler()
        X_train_scaled = self.ml_scaler.fit_transform(X_train)
        X_cal_scaled = self.ml_scaler.transform(X_cal)
        X_test_scaled = self.ml_scaler.transform(X_test)
        
        if progress_callback:
            progress_callback(60, "Entrenando GradientBoosting v6.1...")
        
        # Modelo base: GradientBoosting con regularizacion agresiva
        base_model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            min_samples_split=30,
            min_samples_leaf=15,
            subsample=0.8,
            max_features='sqrt',
            random_state=42,
        )
        
        base_model.fit(X_train_scaled, y_train)
        self._ml_base_model = base_model
        
        if progress_callback:
            progress_callback(75, "Calibrando probabilidades...")
        
        # Calibrar con CalibratedClassifierCV
        calibrated_model = CalibratedClassifierCV(
            base_model,
            cv='prefit',
            method='isotonic',
        )
        calibrated_model.fit(X_cal_scaled, y_cal)
        self.ml_break_model = calibrated_model
        
        if progress_callback:
            progress_callback(85, "Evaluando modelo v6.1...")
        
        # Evaluar en TEST set
        y_pred_proba = self.ml_break_model.predict_proba(X_test_scaled)[:, 1]
        y_pred = (y_pred_proba >= 0.5).astype(int)
        
        accuracy = accuracy_score(y_test, y_pred)
        auc_roc = roc_auc_score(y_test, y_pred_proba) if len(np.unique(y_test)) > 1 else 0.5
        
        # Cross validation en base model
        cv_scores = cross_val_score(
            GradientBoostingClassifier(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                min_samples_split=30, min_samples_leaf=15,
                subsample=0.8, max_features='sqrt', random_state=42,
            ),
            self.ml_scaler.fit_transform(X),
            y,
            cv=5,
            scoring='roc_auc'
        )
        
        # Feature importance
        importances = dict(zip(feature_cols, base_model.feature_importances_))
        importances = dict(sorted(importances.items(), key=lambda x: x[1], reverse=True))
        
        # Classification report
        report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
        
        logger.info(f"[v6.1] TEST Results:")
        logger.info(f"   AUC-ROC: {auc_roc:.4f}")
        logger.info(f"   Accuracy: {accuracy:.4f}")
        logger.info(f"   CV Scores: {cv_scores}")
        logger.info(f"   CV Mean: {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")
        
        # Calibracion check
        from sklearn.calibration import calibration_curve
        try:
            prob_true, prob_pred = calibration_curve(y_test, y_pred_proba, n_bins=10, strategy='uniform')
            cal_error = np.mean(np.abs(prob_true - prob_pred))
            logger.info(f"   Calibration Error: {cal_error:.4f}")
        except Exception:
            cal_error = None
        
        # [v6.1] Log de importancia de features dinamicas
        live_features = ['n_decided_before', 'n_breaks_before', 'fav_win_rate_before', 'snake_intact_before']
        live_imp = {k: importances.get(k, 0) for k in live_features}
        logger.info(f"[v6.1] Live feature importances: {live_imp}")
        
        if progress_callback:
            progress_callback(92, "Entrenando modelo de tipo...")
        
        # Modelo secundario: Tipo de ruptura
        df_breaks = df[df['broke_snake'] == 1].copy()
        if len(df_breaks) > 50:
            df_breaks['break_type_binary'] = (df_breaks['break_type'] == 'draw').astype(int)
            X_type = df_breaks[feature_cols].fillna(0)
            y_type = df_breaks['break_type_binary'].values
            X_type_scaled = self.ml_scaler.transform(X_type)
            
            self.ml_type_model = RandomForestClassifier(
                n_estimators=50, max_depth=5,
                class_weight='balanced', random_state=42
            )
            self.ml_type_model.fit(X_type_scaled, y_type)
        
        # Guardar resultado
        self.ml_training_result = MLTrainingResult(
            model_type='GradientBoosting_v6.1_dynamic',
            accuracy=accuracy,
            auc_roc=auc_roc,
            precision_break=report.get('1', {}).get('precision', 0),
            recall_break=report.get('1', {}).get('recall', 0),
            n_samples=len(df),
            n_breaks=n_breaks,
            feature_importances=importances,
            cross_val_scores=cv_scores.tolist(),
        )
        
        # Guardar modelo
        self._save_ml_model()
        
        if progress_callback:
            progress_callback(100, "Entrenamiento v6.1 completado!")
        
        logger.info(f"[OK] Modelo v6.1 entrenado: AUC={auc_roc:.3f}, Accuracy={accuracy:.3f}")
        logger.info(f"[i] Top features: {dict(list(importances.items())[:5])}")
        
        return self.ml_training_result

    def predict_break_probability(self, match: MatchPrediction) -> Tuple[float, str]:
        """
        [v6.1] Predice probabilidad de ruptura.
        
        RETROCOMPATIBLE: Detecta si el modelo cargado es v6 (14 features)
        o v6.1 (18 features) y ajusta automaticamente.
        """
        if self.ml_break_model is None or self.ml_scaler is None:
            return self._heuristic_break_score(match)
        
        # [v6.1] Detectar cuantas features espera el modelo cargado
        n_expected = self.ml_scaler.n_features_in_
        
        if n_expected >= 18:
            # === Modelo v6.1: usar las 18 features (incluye dinamicas) ===
            features = np.array([[
                # Individual (v5)
                match.prob_draw,
                match.prob_underdog,
                match.icf_diff,
                match.position_normalized,
                1 if match.is_simultaneous else 0,
                match.accumulated_tension,
                match.match_importance,
                match.rest_days_diff,
                # Matchday context (v6)
                match.n_matches_day,
                match.joint_prob_all_favs,
                match.min_favorite_prob_day,
                match.mean_favorite_prob_day,
                match.weakest_link_rank,
                match.n_tight_matches_day,
                # Live dynamic (v6.1)
                match.n_decided_before,
                match.n_breaks_before,
                match.fav_win_rate_before,
                match.snake_intact_before,
            ]])
        elif n_expected >= 14:
            # === Modelo v6: solo 14 features (sin dinamicas) ===
            features = np.array([[
                match.prob_draw,
                match.prob_underdog,
                match.icf_diff,
                match.position_normalized,
                1 if match.is_simultaneous else 0,
                match.accumulated_tension,
                match.match_importance,
                match.rest_days_diff,
                match.n_matches_day,
                match.joint_prob_all_favs,
                match.min_favorite_prob_day,
                match.mean_favorite_prob_day,
                match.weakest_link_rank,
                match.n_tight_matches_day,
            ]])
        else:
            # === Modelo v5: 8 features ===
            features = np.array([[
                match.prob_draw,
                match.prob_underdog,
                match.icf_diff,
                match.position_normalized,
                1 if match.is_simultaneous else 0,
                match.accumulated_tension,
                match.match_importance,
                match.rest_days_diff,
            ]])
        
        try:
            features_scaled = self.ml_scaler.transform(features)
            prob_break = self.ml_break_model.predict_proba(features_scaled)[0, 1]
        except Exception as e:
            logger.warning(f"[!] Error en prediccion ML: {e}")
            return self._heuristic_break_score(match)
        
        # [v6.1] Si usamos modelo v6 (sin dynamic features), aplicar ajuste post-hoc
        if n_expected < 18:
            prob_break = self._apply_live_adjustment(prob_break, match)
        
        # Predecir tipo
        predicted_type = "draw"
        if self.ml_type_model is not None:
            try:
                type_pred = self.ml_type_model.predict(features_scaled)[0]
                predicted_type = "draw" if type_pred == 1 else "underdog"
            except Exception:
                pass
        elif match.prob_break_by_draw > match.prob_break_by_underdog:
            predicted_type = "draw"
        else:
            predicted_type = "underdog"
        
        return prob_break, predicted_type
    
    def _apply_live_adjustment(self, base_prob: float, match: MatchPrediction) -> float:
        """
        [v6.1] Ajuste post-hoc para modelos v6/v5 que no tienen features dinamicas.
        
        Si no hay modelo v6.1 entrenado, usa este ajuste heuristico
        sobre el score del modelo existente.
        """
        if match.n_decided_before == 0:
            return base_prob  # Sin datos en vivo, no ajustar
        
        adjustment = 0.0
        
        # Si la culebra ya se rompio, el partido pendiente tiene MENOS riesgo
        if match.snake_intact_before < 0.5:
            # La culebra ya se rompio antes - reducir probabilidad de ruptura
            # (ya no tiene sentido hablar de "romper" algo roto)
            adjustment -= 0.15
        
        # Si todos los favoritos ganaron hasta ahora, la tension sube
        if match.fav_win_rate_before >= 0.9 and match.n_decided_before >= 2:
            adjustment += 0.08  # Culebra viva con muchos aciertos = mas tension
        
        # Si ya hubo breaks, la probabilidad de otro break baja
        # (regresion a la media: dias con muchos upsets son raros)
        if match.n_breaks_before >= 2:
            adjustment -= 0.10
        elif match.n_breaks_before == 1 and match.n_decided_before >= 3:
            adjustment -= 0.05
        
        adjusted = np.clip(base_prob + adjustment, 0.01, 0.99)
        
        if abs(adjustment) > 0.01:
            logger.debug(
                f"[v6.1] Live adjustment: {base_prob:.3f} -> {adjusted:.3f} "
                f"(decided={match.n_decided_before}, breaks={match.n_breaks_before}, "
                f"intact={match.snake_intact_before})"
            )
        
        return adjusted
    
    def _heuristic_break_score(self, match: MatchPrediction) -> Tuple[float, str]:
        """Fallback heuristico si no hay modelo ML."""
        score = match.prob_break_total
        
        if match.prob_draw >= 0.28:
            score += 0.12
        if match.icf_diff < 0.3:
            score += 0.08
        if match.accumulated_tension > 0.5:
            score += 0.05
        if match.is_simultaneous:
            score += 0.03
        if match.prob_underdog > 0.30:
            score += 0.06
        
        if match.match_importance >= 0.7:
            score += 0.05
        if match.rest_days_diff < -0.3:
            score += 0.04
        
        # [v6.1] Ajustes heuristicos por contexto en vivo
        if match.n_decided_before > 0:
            if match.snake_intact_before < 0.5:
                score -= 0.15  # Culebra ya rota = menos riesgo
            if match.fav_win_rate_before >= 0.9 and match.n_decided_before >= 2:
                score += 0.08  # Todos ganando = mas tension
            if match.n_breaks_before >= 2:
                score -= 0.10
        
        score = min(max(score, 0.01), 1.0)
        
        pred_type = "draw" if match.prob_draw > match.prob_underdog else "underdog"
        
        return score, pred_type
    
    # =========================================================================
    # ANALISIS POR DIA
    # =========================================================================
    
    def analyze_day(self, league_id: int, target_date: date,
                    inherited_tension: float = 0.0) -> DayAnalysis:
        """
        [v6.1] Analiza la culebra de un dia con features DINAMICAS.
        
        Si hay partidos ya terminados (FT) mezclados con pendientes (NS),
        los partidos pendientes reciben features actualizadas con los
        resultados reales de los partidos ya jugados.
        """
        fixtures = self.get_fixtures_for_date(league_id, target_date)
        league_name = self.get_league_name(league_id)
        
        analysis = DayAnalysis(
            date=target_date,
            league_id=league_id,
            league_name=league_name,
            inherited_tension=inherited_tension,
        )
        
        if not fixtures:
            return analysis
        
        # Generar predicciones
        predictions = []
        for i, fx in enumerate(fixtures):
            match_dt = pd.to_datetime(fx['date']) if fx['date'] else datetime.combine(target_date, datetime.min.time())
            
            pred = self.predict_match(
                fixture_id=fx['fixture_id'],
                home_team_id=fx['home_team_id'],
                away_team_id=fx['away_team_id'],
                match_date=match_dt,
                home_team_name=fx['home_team_name'],
                away_team_name=fx['away_team_name'],
                league_id=league_id,
                goals_home=fx['goals_home'],
                goals_away=fx['goals_away'],
                round_str=fx.get('round'),
            )
            
            pred.position_in_day = i + 1
            pred.position_normalized = (i + 1) / len(fixtures)
            pred.inherited_tension = inherited_tension
            predictions.append(pred)
        
        # Detectar simultaneos y calcular tension
        self._mark_simultaneous(predictions)
        self._calculate_accumulated_tension(predictions, inherited_tension)
        
        # [v6] Computar features de jornada ANTES del ML
        self._compute_matchday_features(predictions)
        
        # [v6.1] Computar features DINAMICAS (usa resultados reales)
        self._compute_live_context_features(predictions)
        
        # Aplicar ML a cada partido
        for pred in predictions:
            ml_score, ml_type = self.predict_break_probability(pred)
            pred.ml_break_score = ml_score
            pred.ml_break_type_pred = ml_type
        
        analysis.matches = predictions
        analysis.total_matches = len(predictions)
        
        # [v6.1] Info de contexto en vivo
        n_decided = sum(1 for p in predictions if p.outcome is not None)
        n_pending = sum(1 for p in predictions if p.outcome is None)
        analysis.n_decided = n_decided
        analysis.n_pending = n_pending
        analysis.has_live_context = n_decided > 0 and n_pending > 0
        
        if analysis.has_live_context:
            logger.info(
                f"[v6.1] Contexto en vivo: {n_decided} terminados, {n_pending} pendientes "
                f"(league={league_id}, date={target_date})"
            )
        
        # Calcular metricas de culebra
        matches_with_fav = [p for p in predictions if p.favorite != "none"]
        analysis.matches_with_favorite = len(matches_with_fav)
        
        if matches_with_fav:
            snake_potential = 1.0
            for p in matches_with_fav:
                snake_potential *= p.favorite_prob
            
            analysis.snake_potential = snake_potential
            analysis.prob_break_total = 1 - snake_potential
            
            avg_draw_break = np.mean([p.prob_break_by_draw for p in matches_with_fav])
            avg_under_break = np.mean([p.prob_break_by_underdog for p in matches_with_fav])
            total_break_contrib = avg_draw_break + avg_under_break
            
            if total_break_contrib > 0:
                analysis.prob_break_by_draw = analysis.prob_break_total * (avg_draw_break / total_break_contrib)
                analysis.prob_break_by_underdog = analysis.prob_break_total * (avg_under_break / total_break_contrib)
            else:
                avg_draw_prob = np.mean([p.prob_draw for p in matches_with_fav])
                avg_non_draw = 1 - avg_draw_prob
                if avg_draw_prob + avg_non_draw > 0:
                    analysis.prob_break_by_draw = analysis.prob_break_total * (avg_draw_prob / (avg_draw_prob + avg_non_draw))
                    analysis.prob_break_by_underdog = analysis.prob_break_total * (avg_non_draw / (avg_draw_prob + avg_non_draw))
                else:
                    analysis.prob_break_by_draw = analysis.prob_break_total * 0.5
                    analysis.prob_break_by_underdog = analysis.prob_break_total * 0.5
        
        # Tension
        analysis.base_tension = analysis.prob_break_total
        analysis.total_tension = min(1.0, analysis.base_tension + inherited_tension * self.TENSION_INHERITANCE_FACTOR)
        
        # Prediccion de ruptura
        analysis.predicted_break = analysis.total_tension > 0.5
        if analysis.predicted_break:
            analysis.predicted_break_type = "draw" if analysis.prob_break_by_draw > analysis.prob_break_by_underdog else "underdog"
        
        # Ranking ML
        self._rank_matches_by_ml(analysis, predictions)
        
        # Verificar resultado real
        self._check_day_result(analysis)
        
        return analysis
    
    def _rank_matches_by_ml(self, analysis: DayAnalysis, predictions: List[MatchPrediction]):
        """Rankea partidos por score ML y determina candidato."""
        if not predictions:
            return
        
        ranked = [(p.position_in_day, p, p.ml_break_score) for p in predictions]
        ranked.sort(key=lambda x: x[2], reverse=True)
        
        analysis.matches_ranked_by_ml = ranked
        
        if ranked:
            pos, candidate, score = ranked[0]
            analysis.ml_candidate_match = candidate
            analysis.ml_candidate_position = pos
            analysis.ml_candidate_score = score
            
            # Generar razones
            reasons = []
            
            type_emoji = "=" if candidate.ml_break_type_pred == "draw" else "X"
            type_name = "EMPATE" if candidate.ml_break_type_pred == "draw" else "UNDERDOG"
            reasons.append(f"{type_emoji} Mayor riesgo de {type_name}")
            
            if candidate.prob_draw >= 0.28:
                reasons.append(f"Alta prob. empate ({candidate.prob_draw*100:.0f}%)")
            if candidate.prob_underdog >= 0.30:
                reasons.append(f"Underdog peligroso ({candidate.prob_underdog*100:.0f}%)")
            if candidate.icf_diff < 0.3:
                reasons.append(f"Equipos parejos (ICF diff: {candidate.icf_diff:.2f})")
            if candidate.accumulated_tension > 0.4:
                reasons.append(f"Tension acumulada ({candidate.accumulated_tension*100:.0f}%)")
            if candidate.match_importance >= 0.7:
                reasons.append(f"Partido importante ({candidate.season_phase})")
            if candidate.rest_days_diff < -0.2:
                reasons.append(f"Favorito cansado (diff: {candidate.rest_days_diff:.1f})")
            if candidate.is_simultaneous:
                reasons.append("Partido simultaneo")
            
            # [v6.1] Razones por contexto en vivo
            if candidate.n_decided_before > 0:
                if candidate.snake_intact_before > 0.5:
                    reasons.append(f"Culebra VIVA ({candidate.n_decided_before} ok)")
                else:
                    reasons.append(f"Culebra YA ROTA ({candidate.n_breaks_before} breaks)")
                
                if candidate.fav_win_rate_before < 0.5 and candidate.n_decided_before >= 2:
                    reasons.append(f"Dia de upsets ({candidate.fav_win_rate_before*100:.0f}% favs)")
            
            if candidate.favorite != "none":
                fav_name = candidate.home_team_name if candidate.favorite == "home" else candidate.away_team_name
                reasons.append(f"Favorito: {fav_name[:15]} ({candidate.favorite_prob*100:.0f}%)")
            
            analysis.ml_candidate_reasons = reasons[:6]  # Maximo 6 razones
    
    def _mark_simultaneous(self, predictions: List[MatchPrediction]):
        """Marca partidos simultaneos."""
        for i, p1 in enumerate(predictions):
            for j, p2 in enumerate(predictions):
                if i >= j:
                    continue
                if p1.date and p2.date:
                    time_diff = abs((p1.date - p2.date).total_seconds())
                    if time_diff <= 900:
                        p1.is_simultaneous = True
                        p2.is_simultaneous = True
    
    def _calculate_accumulated_tension(self, predictions: List[MatchPrediction], 
                                        inherited: float = 0.0):
        """Calcula tension acumulada."""
        accumulated = 1.0
        
        for p in predictions:
            p.inherited_tension = inherited
            if p.favorite != "none":
                accumulated *= p.favorite_prob
            p.accumulated_tension = (1 - accumulated) + inherited * self.TENSION_INHERITANCE_FACTOR
            p.accumulated_tension = min(1.0, p.accumulated_tension)
    
    def _check_day_result(self, analysis: DayAnalysis):
        """Verifica resultado real del dia."""
        snake_broken = False
        break_match_id = None
        break_type = None
        break_position = None
        
        for i, p in enumerate(analysis.matches):
            if p.broke_snake:
                snake_broken = True
                break_match_id = p.fixture_id
                break_type = p.break_type
                break_position = i + 1
                break
        
        has_results = any(p.outcome is not None for p in analysis.matches)
        
        if has_results:
            analysis.snake_broke = snake_broken
            analysis.break_match_id = break_match_id
            analysis.break_type = break_type
            analysis.break_match_position = break_position
            
            analysis.prediction_correct = (analysis.predicted_break == analysis.snake_broke)
            if analysis.snake_broke and analysis.predicted_break:
                analysis.break_type_correct = (analysis.predicted_break_type == analysis.break_type)
    
    # =========================================================================
    # ANALISIS POR JORNADA
    # =========================================================================
    
    def analyze_jornada(self, league_id: int, start_date: date,
                        end_date: date = None, jornada_num: int = None) -> JornadaAnalysis:
        """Analiza jornada completa."""
        if end_date is None:
            end_date = start_date + timedelta(days=6)
        
        league_name = self.get_league_name(league_id)
        available_dates = self.get_available_dates(league_id, start_date, end_date)
        
        analysis = JornadaAnalysis(
            league_id=league_id,
            league_name=league_name,
            jornada_num=jornada_num,
            date_start=start_date,
            date_end=end_date,
        )
        
        if not available_dates:
            return analysis
        
        inherited_tension = 0.0
        days = []
        
        for d in sorted(available_dates):
            day_analysis = self.analyze_day(league_id, d, inherited_tension)
            
            if day_analysis.total_matches > 0:
                days.append(day_analysis)
                
                if day_analysis.snake_broke is False:
                    inherited_tension += day_analysis.base_tension * self.TENSION_INHERITANCE_FACTOR
                elif day_analysis.snake_broke is True:
                    inherited_tension = 0.0
        
        analysis.days = days
        analysis.total_days = len(days)
        analysis.total_matches = sum(d.total_matches for d in days)
        
        if days:
            weekly_potential = 1.0
            for d in days:
                weekly_potential *= d.snake_potential if d.snake_potential > 0 else 1.0
            
            analysis.weekly_snake_potential = weekly_potential
            analysis.weekly_prob_break = 1 - weekly_potential
            
            for d in days:
                if d.snake_broke:
                    analysis.snake_broke = True
                    analysis.break_day = d.date
                    analysis.break_type = d.break_type
                    break
            
            if analysis.snake_broke is None and any(d.snake_broke is not None for d in days):
                analysis.snake_broke = False
        
        return analysis
    
    # =========================================================================
    # CALIBRACION
    # =========================================================================
    
    def calibrate(self, min_samples: int = 100, test_size: float = 0.2) -> CalibrationResult:
        """Calibra pesos del ICF."""
        logger.info("[i] Calibrando modelo...")
        
        df = self.get_fixtures_with_odds()
        
        if len(df) < min_samples:
            raise ValueError(f"Insuficientes muestras: {len(df)} < {min_samples}")
        
        features = []
        targets_home = []
        
        DEFAULT_CONSTANTS = {
            'k_positivo_local': 0.0, 'k_positivo_visita': 0.0,
            'k_goles_local_anotado': 0.0, 'k_goles_local_recibido': 0.0,
            'k_goles_visita_anotado': 0.0, 'k_goles_visita_recibido': 0.0,
            'k_negativo_local': 0.0, 'k_negativo_visita': 0.0,
        }
        
        used_fallback = 0
        
        for _, row in df.iterrows():
            try:
                match_date = pd.to_datetime(row['date'])
                
                const_home = self.get_constants_before_date(row['home_team_id'], match_date)
                const_away = self.get_constants_before_date(row['away_team_id'], match_date)
                
                home_has = const_home is not None
                away_has = const_away is not None
                
                if not home_has:
                    const_home = DEFAULT_CONSTANTS
                    used_fallback += 1
                if not away_has:
                    const_away = DEFAULT_CONSTANTS
                    if home_has:
                        used_fallback += 1
                
                nivel_home = self.get_team_level(row['home_team_id'], match_date) or 1.0
                nivel_away = self.get_team_level(row['away_team_id'], match_date) or 1.0
                
                # ALINEADO con calculate_icf(): _safe_k + _compress_k
                feature_row = {
                    'k_local_home': self._compress_k(self._safe_k(const_home.get('k_positivo_local'))),
                    'k_goles_a_home': self._compress_k(self._safe_k(const_home.get('k_goles_local_anotado'))),
                    'k_goles_r_home': self._compress_k(self._safe_k(const_home.get('k_goles_local_recibido'))),
                    'k_neg_home': self._compress_k(self._safe_k(const_home.get('k_negativo_local'))),
                    'nivel_home': nivel_home,
                    'k_visita_away': self._compress_k(self._safe_k(const_away.get('k_positivo_visita'))),
                    'k_goles_a_away': self._compress_k(self._safe_k(const_away.get('k_goles_visita_anotado'))),
                    'k_goles_r_away': self._compress_k(self._safe_k(const_away.get('k_goles_visita_recibido'))),
                    'k_neg_away': self._compress_k(self._safe_k(const_away.get('k_negativo_visita'))),
                    'nivel_away': nivel_away,
                    'league_id': row['league_id'],
                    'has_full_constants': home_has and away_has,
                }
                
                features.append(feature_row)
                targets_home.append(row['prob_home_norm'])
                
            except Exception:
                continue
        
        if len(features) < min_samples:
            raise ValueError(f"Insuficientes muestras: {len(features)}")
        
        full_constants = sum(1 for f in features if f.get('has_full_constants', False))
        
        X = pd.DataFrame(features)
        y_home = np.array(targets_home)
        
        icf_features = ['k_local_home', 'k_goles_a_home', 'k_goles_r_home',
                        'k_neg_home', 'nivel_home',
                        'k_visita_away', 'k_goles_a_away', 'k_goles_r_away',
                        'k_neg_away', 'nivel_away']
        
        X_train, X_test, y_train, y_test = train_test_split(
            X[icf_features], y_home, test_size=test_size, random_state=42
        )
        
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        model = Ridge(alpha=1.0)
        model.fit(X_train_scaled, y_train)
        
        coefs = model.coef_
        self.weights = {
            'k_local': abs(coefs[0]),
            'k_goles_anotado': abs(coefs[1]),
            'k_goles_recibido': abs(coefs[2]),
            'k_negativo': abs(coefs[3]),
            'nivel': abs(coefs[4]),
            'k_visita': abs(coefs[5]),
            'k_positivo': (abs(coefs[0]) + abs(coefs[5])) / 2,
        }
        
        max_w = max(self.weights.values())
        if max_w > 0:
            self.weights = {k: v/max_w for k, v in self.weights.items()}
        
        y_pred_train = model.predict(X_train_scaled)
        self.scale_k = self._optimize_scale_k(y_pred_train, y_train)
        
        y_pred = model.predict(X_test_scaled)
        mae = np.mean(np.abs(y_pred - y_test))
        correlation = np.corrcoef(y_pred, y_test)[0, 1] if len(y_test) > 1 else 0
        brier = np.mean((y_pred - y_test) ** 2)
        
        min_date = df['date'].min()
        max_date = df['date'].max()
        date_range = f"{min_date} a {max_date}"
        
        self.calibration_result = CalibrationResult(
            weights=self.weights,
            scale_k=self.scale_k,
            mae=mae,
            correlation=correlation,
            brier_score=brier,
            n_samples=len(features),
            leagues_included=X['league_id'].unique().tolist(),
            n_with_full_constants=full_constants,
            n_with_fallback=len(features) - full_constants,
            date_range=date_range,
        )
        
        self._save_model()
        logger.info(f"[OK] Calibracion completada: MAE={mae:.4f}")
        
        return self.calibration_result
    
    def _optimize_scale_k(self, predictions: np.ndarray, targets: np.ndarray) -> float:
        """Encuentra scale_k optimo."""
        best_k = 0.15
        best_error = float('inf')
        
        for k in np.arange(0.05, 0.5, 0.01):
            adjusted = 1 / (1 + np.exp(-k * (predictions - 0.5)))
            error = np.mean((adjusted - targets) ** 2)
            if error < best_error:
                best_error = error
                best_k = k
        
        return best_k
    
    # =========================================================================
    # VALIDACION
    # =========================================================================
    
    def validate_by_day(self, league_id: int, start_date: date,
                        end_date: date) -> ValidationMetrics:
        """Valida el modelo dia por dia."""
        metrics = ValidationMetrics()
        available_dates = self.get_available_dates(league_id, start_date, end_date)
        
        inherited_tension = 0.0
        
        for d in sorted(available_dates):
            try:
                day = self.analyze_day(league_id, d, inherited_tension)
                
                if day.total_matches == 0:
                    continue
                
                metrics.total_days += 1
                
                if day.snake_broke is True:
                    metrics.days_snake_broken += 1
                    
                    if day.break_type == "draw":
                        metrics.breaks_by_draw += 1
                    else:
                        metrics.breaks_by_underdog += 1
                    
                    if day.prediction_correct:
                        metrics.correct_break_predictions += 1
                    if day.break_type_correct:
                        metrics.correct_break_type_predictions += 1
                    
                    if day.ml_candidate_position == day.break_match_position:
                        metrics.correct_candidate_predictions += 1
                    
                    inherited_tension = 0.0
                    
                elif day.snake_broke is False:
                    metrics.days_snake_complete += 1
                    if not day.predicted_break:
                        metrics.correct_break_predictions += 1
                    inherited_tension += day.base_tension * self.TENSION_INHERITANCE_FACTOR
                
            except Exception as e:
                logger.warning(f"Error dia {d}: {e}")
                continue
        
        return metrics
    
    # =========================================================================
    # ESTADISTICAS
    # =========================================================================
    
    def get_global_stats(self) -> Dict:
        """Obtiene estadisticas globales."""
        stats = {
            'model_version': 'v6.1',
            'model_calibrated': self.calibration_result is not None,
            'ml_model_trained': self.ml_break_model is not None,
            'ml_model_version': self._ml_model_version,
            'ml_features': self.ML_FEATURES,
            'n_features': len(self.ML_FEATURES),
            'calibration_date': None,
            'calibration_samples': 0,
            'calibration_mae': 0,
            'calibration_correlation': 0,
            'ml_auc_roc': 0,
            'ml_accuracy': 0,
            'ml_n_samples': 0,
            'ml_feature_importances': {},
            'total_leagues': 0,
            'total_fixtures_with_odds': 0,
            'weights': self.weights,
            'scale_k': self.scale_k,
            'n_with_full_constants': 0,
            'n_with_fallback': 0,
            'date_range': '',
        }
        
        if self.calibration_result:
            stats['calibration_date'] = self.calibration_result.timestamp
            stats['calibration_samples'] = self.calibration_result.n_samples
            stats['calibration_mae'] = self.calibration_result.mae
            stats['calibration_correlation'] = self.calibration_result.correlation
            stats['n_with_full_constants'] = self.calibration_result.n_with_full_constants
            stats['n_with_fallback'] = self.calibration_result.n_with_fallback
            stats['date_range'] = self.calibration_result.date_range
        
        if self.ml_training_result:
            stats['ml_auc_roc'] = self.ml_training_result.auc_roc
            stats['ml_accuracy'] = self.ml_training_result.accuracy
            stats['ml_n_samples'] = self.ml_training_result.n_samples
            stats['ml_feature_importances'] = self.ml_training_result.feature_importances
        
        leagues = self.get_available_leagues()
        stats['total_leagues'] = len(leagues)
        stats['total_fixtures_with_odds'] = sum(l['fixtures_with_odds'] for l in leagues)
        
        period = self.get_data_period()
        if not stats['date_range'] and period['min_date']:
            stats['date_range'] = f"{period['min_year']}-{period['max_year']}"
        
        return stats


# =============================================================================
# UTILIDADES
# =============================================================================

def format_probability(prob: float) -> str:
    return f"{prob * 100:.1f}%"

def format_odds(odds: float) -> str:
    return f"{odds:.2f}"

def get_tension_color(tension: float) -> str:
    if tension >= 0.7:
        return "#DC3545"
    elif tension >= 0.5:
        return "#FFC107"
    elif tension >= 0.3:
        return "#17A2B8"
    else:
        return "#28A745"

def get_break_type_emoji(break_type: str) -> str:
    if break_type == "draw":
        return "="
    elif break_type == "underdog":
        return "X"
    return "-"

def get_outcome_emoji(outcome: str) -> str:
    if outcome == "1":
        return "1"
    elif outcome == "X":
        return "="
    elif outcome == "2":
        return "2"
    return "*"


# =============================================================================
# EJEMPLO DE USO
# =============================================================================

if __name__ == "__main__":
    print("[OK] AnticulebraEngine v6.1 - Dynamic Live Features")
    print("=" * 60)
    
    print(f"\n[i] Features ML v6.1 ({len(AnticulebraEngine.ML_FEATURES)} features):")
    for i, feat in enumerate(AnticulebraEngine.ML_FEATURES, 1):
        marker = " [DYNAMIC]" if feat in ['n_decided_before', 'n_breaks_before', 'fav_win_rate_before', 'snake_intact_before'] else ""
        print(f"  {i:2d}. {feat}{marker}")
    
    print("\n[OK] Cambios vs v6:")
    print("  - 4 nuevas features DINAMICAS que usan resultados reales")
    print("  - ML score se recalcula cuando hay partidos terminados")
    print("  - Retrocompatible con modelos v6 y v5 (ajuste post-hoc)")
    print("  - Contexto en vivo: culebra ya rota -> score baja")
    print("  - Contexto en vivo: todos favoritos OK -> tension sube")