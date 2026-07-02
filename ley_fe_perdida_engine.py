# src/ley_fe_perdida_engine.py
# -*- coding: utf-8 -*-
"""
⚖️ LEY DE LA FE PERDIDA — ENGINE v1
=====================================
Motor de predicción basado en el péndulo del hincha.

Método: Lookup table empírica (42,452 partidos, 37 ligas).
- Calcula péndulo de fe para cada equipo (ventana 5 partidos)
- Calcula gap = péndulo_local - péndulo_visitante
- Asigna flags de oportunidad basado en umbrales calibrados
- Sugiere mercados (1X2, Team to Score, Hándicap Europeo)

Modo híbrido: usa odds si están disponibles, proxy de goles si no.

Autor: Gerson (desarrollado con Claude)
Fecha: Febrero 2026
"""

import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


# =============================================================================
# RESOLUCIÓN DE RUTAS Y CONEXIÓN A BD
# =============================================================================

def _find_base_dir() -> str:
    """Encuentra la raíz del proyecto (donde está sad.db)."""
    this_dir = os.path.dirname(os.path.abspath(__file__))
    # Si estamos en src/ o src/ui/
    for candidate in [
        os.path.dirname(this_dir),      # src/ → raíz
        os.path.dirname(os.path.dirname(this_dir)),  # src/ui/ → raíz
        this_dir,                        # mismo directorio
    ]:
        if os.path.exists(os.path.join(candidate, 'sad.db')):
            return candidate
    return os.path.dirname(this_dir)


try:
    from data.database_manager import ORIG_ENGINE, BASE_DIR
except ImportError:
    BASE_DIR = _find_base_dir()
    ORIG_ENGINE = create_engine(f'sqlite:///{os.path.join(BASE_DIR, "sad.db")}', echo=False)


# =============================================================================
# ENUMS
# =============================================================================

class TeamStature(Enum):
    """Estatura del equipo: define cómo siente el hincha cada resultado."""
    GRANDE = "grande"    # Hincha espera GANAR siempre
    MEDIO = "medio"      # Hincha espera no perder
    CHICO = "chico"      # Hincha espera competir
    UNKNOWN = "unknown"


class PendulumZone(Enum):
    """Zona emocional del péndulo."""
    FE_DESTRUIDA = "fe_destruida"
    FRUSTRACION = "frustracion"
    TENSION = "tension"
    NEUTRAL = "neutral"
    CONFIANZA = "confianza"
    EUFORIA = "euforia"


class FlagType(Enum):
    """Flag de oportunidad basado en el gap."""
    HOME_STRONG = "HOME_STRONG"
    HOME = "HOME"
    NONE = "NONE"
    AWAY = "AWAY"
    AWAY_STRONG = "AWAY_STRONG"


class GoalFlag(Enum):
    """Flag de goles basado en péndulo absoluto."""
    SCORES = "scores"         # Equipo eufórico → 86% anota
    SECO = "seco"             # Equipo en crisis → baja probabilidad de anotar
    NORMAL = "normal"         # Sin señal especial


# =============================================================================
# TABLA EMPÍRICA — Calibrada con 42,452 partidos de 37 ligas
# =============================================================================

# Tasas base por rango de gap (del backtest)
GAP_LOOKUP = {
    # (gap_min, gap_max): (home_win%, draw%, away_win%, avg_margin, goleada%)
    (-200, -35): (0.311, 0.280, 0.409, -0.24, 0.125),
    (-35, -25):  (0.347, 0.273, 0.381, +0.00, 0.126),
    (-25, -15):  (0.388, 0.270, 0.342, +0.12, 0.116),
    (-15, -5):   (0.415, 0.272, 0.313, +0.25, 0.125),
    (-5, +5):    (0.452, 0.270, 0.278, +0.35, 0.130),   # BASELINE
    (+5, +15):   (0.462, 0.278, 0.260, +0.43, 0.136),
    (+15, +25):  (0.498, 0.271, 0.230, +0.50, 0.138),
    (+25, +35):  (0.562, 0.249, 0.189, +0.71, 0.152),
    (+35, +200): (0.630, 0.214, 0.155, +0.96, 0.175),
}

# Baseline (gap -5 a +5)
BASELINE = {
    'home_win': 0.452,
    'draw': 0.270,
    'away_win': 0.278,
    'margin': 0.35,
    'goleada': 0.130,
}

# Hándicap europeo del underdog por flag (del backtest)
HANDICAP_LOOKUP = {
    # flag: {handicap: (underdog_wins%, underdog_draws%)}
    FlagType.HOME_STRONG: {
        1: (0.388, 0.271),  # Visitante +1
        2: (0.659, 0.184),  # Visitante +2
        3: (0.843, 0.088),  # Visitante +3
    },
    FlagType.HOME: {
        1: (0.475, 0.243),
        2: (0.717, 0.151),
        3: (0.868, 0.081),
    },
    FlagType.AWAY_STRONG: {
        1: (0.599, 0.000),  # Local +1 (invertido)
        2: (0.804, 0.000),
        3: (0.912, 0.000),
    },
    FlagType.AWAY: {
        1: (0.637, 0.000),
        2: (0.845, 0.000),
        3: (0.933, 0.000),
    },
}

# Team to Score por zona de péndulo (del backtest)
GOAL_LOOKUP = {
    # zona: (team_scores%, opponent_scores%)
    # LOCAL
    'home_euforia':     (0.859, 0.599),  # local anota 86%, rival anota 60%
    'home_confianza':   (0.807, 0.613),
    'home_neutral':     (0.763, 0.660),
    'home_negativo':    (0.695, 0.732),  # local anota 70%, rival anota 73%
    # VISITANTE
    'away_euforia':     (0.738, 0.599),  # visit anota 74%, local anota 60% (aprox)
    'away_confianza':   (0.664, 0.643),
    'away_neutral':     (0.660, 0.763),
    'away_negativo':    (0.551, 0.810),  # visit no anota en 45%, local anota 81%
}

# Margen esperado por gap del underdog (para sugerencia de hándicap)
MARGIN_BY_GAP = {
    # gap_abs_range: margin_promedio (absoluto, del favorito)
    (0, 15):   0.38,
    (15, 25):  0.50,
    (25, 35):  0.71,
    (35, 200): 0.96,
}


# =============================================================================
# DATACLASSES DE OUTPUT
# =============================================================================

@dataclass
class TeamPendulum:
    """Péndulo calculado de un equipo."""
    team_id: int
    team_name: str
    league_id: int
    stature: TeamStature
    pendulum_score: float          # -100 a +100
    zone: PendulumZone
    mode: str                      # 'odds' o 'proxy'
    last_results: List[str] = field(default_factory=list)  # ['W','D','L',...]
    faith_details: List[Dict] = field(default_factory=list)
    goal_flag: GoalFlag = GoalFlag.NORMAL
    team_scores_pct: float = 0.76  # % probabilidad de que anote


@dataclass
class HandicapSuggestion:
    """Sugerencia de hándicap europeo."""
    team_name: str                   # Equipo underdog
    handicap: int                    # +1, +2, +3
    win_pct: float                   # Prob de ganar con ese hándicap
    draw_pct: float                  # Prob de empate con ese hándicap
    suggested: bool = False          # Si es la sugerencia principal


@dataclass
class MarketSuggestion:
    """Sugerencia de mercado específico."""
    market: str                      # "Home Win", "Away +2", "Team to Score"
    probability: float               # Probabilidad empírica
    baseline: float                  # Probabilidad baseline
    edge_pp: float                   # Edge en pp sobre baseline
    description: str = ""


@dataclass 
class MatchAnalysis:
    """Análisis completo de un partido."""
    fixture_id: Optional[int]
    match_date: str
    league_id: int
    league_name: str
    
    # Péndulos
    home: TeamPendulum
    away: TeamPendulum
    
    # Gap y flag
    gap: float                       # home_pendulum - away_pendulum
    flag: FlagType
    flag_emoji: str
    flag_description: str
    edge_pp: float                   # Ventaja principal en pp
    
    # Probabilidades ajustadas
    prob_home: float
    prob_draw: float
    prob_away: float
    
    # Margen esperado
    expected_margin: float
    goleada_pct: float               # Prob de 3+ goles diferencia
    
    # Sugerencias
    handicap_suggestions: List[HandicapSuggestion] = field(default_factory=list)
    market_suggestions: List[MarketSuggestion] = field(default_factory=list)
    
    # Odds (si disponibles)
    odds_home: Optional[float] = None
    odds_draw: Optional[float] = None
    odds_away: Optional[float] = None
    value_bets: List[str] = field(default_factory=list)


# =============================================================================
# CONSTANTES DEL PÉNDULO
# =============================================================================

PENDULUM_THRESHOLDS = {
    PendulumZone.FE_DESTRUIDA:  (-100, -35),
    PendulumZone.FRUSTRACION:   (-35, -18),
    PendulumZone.TENSION:       (-18, -6),
    PendulumZone.NEUTRAL:       (-6, 6),
    PendulumZone.CONFIANZA:     (6, 18),
    PendulumZone.EUFORIA:       (18, 100),
}

FLAG_THRESHOLDS = {
    FlagType.HOME_STRONG: (+35, +200),
    FlagType.HOME:        (+25, +35),
    FlagType.NONE:        (-25, +25),
    FlagType.AWAY:        (-35, -25),
    FlagType.AWAY_STRONG: (-200, -35),
}

FLAG_EMOJIS = {
    FlagType.HOME_STRONG: "🟢",
    FlagType.HOME: "🔵",
    FlagType.NONE: "⚪",
    FlagType.AWAY: "🔴",
    FlagType.AWAY_STRONG: "🟣",
}

FLAG_DESCRIPTIONS = {
    FlagType.HOME_STRONG: "Local domina — racha caliente vs rival en crisis",
    FlagType.HOME: "Ventaja clara del local por forma reciente",
    FlagType.NONE: "Sin señal — partido equilibrado en forma",
    FlagType.AWAY: "Visitante en mejor forma que el local",
    FlagType.AWAY_STRONG: "Visitante domina — local vulnerable",
}

ZONE_EMOJIS = {
    PendulumZone.FE_DESTRUIDA: "💀",
    PendulumZone.FRUSTRACION: "😡",
    PendulumZone.TENSION: "😤",
    PendulumZone.NEUTRAL: "😐",
    PendulumZone.CONFIANZA: "👍",
    PendulumZone.EUFORIA: "🎉",
}

STATURE_EMOJIS = {
    TeamStature.GRANDE: "🏟️",
    TeamStature.MEDIO: "🔵",
    TeamStature.CHICO: "🏚️",
    TeamStature.UNKNOWN: "❓",
}

WINDOW = 5
DECAY = 0.88


# =============================================================================
# ENGINE
# =============================================================================

class FePerdidaEngine:
    """
    Motor de la Ley de la Fe Perdida.
    
    Calcula péndulo de fe para equipos y genera flags de oportunidad
    basado en lookup tables empíricas de 42,452 partidos.
    """
    
    def __init__(self):
        """Inicializa el motor."""
        self.orig_engine = ORIG_ENGINE
        self.base_dir = BASE_DIR
        
        # Pendulum DB para cache
        pend_db_path = os.path.join(self.base_dir, 'pendulum.db')
        self.pend_engine = create_engine(f'sqlite:///{pend_db_path}', echo=False)
        self._init_pendulum_db()
        
        # Cache en memoria
        self._stature_cache: Dict[Tuple[int, int], TeamStature] = {}
        self._league_stature_ranking: Dict[int, Dict[int, TeamStature]] = {}  # league_id -> {team_id: stature}
        self._league_names: Dict[int, str] = {}
        self._load_league_names()
        
        logger.info("[OK] FePerdidaEngine v1 inicializado")
    
    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================
    
    def _init_pendulum_db(self):
        """Crea tablas en pendulum.db si no existen."""
        create_sql = [
            """
            CREATE TABLE IF NOT EXISTS pendulum_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                league_id INTEGER NOT NULL,
                fixture_id INTEGER NOT NULL,
                pendulum_score REAL,
                zone TEXT,
                stature TEXT,
                mode TEXT,
                calculated_at TEXT,
                UNIQUE(team_id, fixture_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS match_flags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fixture_id INTEGER UNIQUE NOT NULL,
                home_team_id INTEGER,
                away_team_id INTEGER,
                home_pendulum REAL,
                away_pendulum REAL,
                gap REAL,
                flag TEXT,
                edge_pp REAL,
                calculated_at TEXT
            )
            """,
        ]
        with self.pend_engine.connect() as conn:
            for sql in create_sql:
                conn.execute(text(sql))
            conn.commit()
    
    def _load_league_names(self):
        """Carga nombres de ligas desde CSV."""
        csv_path = os.path.join(self.base_dir, 'leagues2024.csv')
        if not os.path.exists(csv_path):
            csv_path = os.path.join(self.base_dir, 'src', 'leagues2024.csv')
        
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                for _, row in df.iterrows():
                    lid = int(row['League ID'])
                    lname = str(row['League Name'])
                    country = str(row.get('Country Name', ''))
                    self._league_names[lid] = f"{lname} ({country})" if country else lname
            except Exception as e:
                logger.warning(f"Error cargando CSV de ligas: {e}")
    
    def get_league_name(self, league_id: int) -> str:
        """Nombre de liga, con fallback a la DB."""
        if league_id in self._league_names:
            return self._league_names[league_id]
        
        try:
            q = text("SELECT name FROM leagues WHERE id = :lid")
            with self.orig_engine.connect() as conn:
                row = conn.execute(q, {'lid': league_id}).fetchone()
                if row:
                    return row[0]
        except Exception:
            pass
        
        return f"Liga {league_id}"
    
    # =========================================================================
    # ESTATURA
    # =========================================================================
    
    def get_team_stature(self, team_id: int, league_id: int) -> TeamStature:
        """
        Determina la estatura del equipo.
        Modo híbrido: usa odds si hay, proxy si no.
        """
        cache_key = (team_id, league_id)
        if cache_key in self._stature_cache:
            return self._stature_cache[cache_key]
        
        stature = self._stature_from_odds(team_id, league_id)
        if stature is None:
            stature = self._stature_from_proxy(team_id, league_id)
        
        self._stature_cache[cache_key] = stature
        return stature
    
    def _stature_from_odds(self, team_id: int, league_id: int) -> Optional[TeamStature]:
        """Estatura basada en ranking de odds dentro de la liga.
        
        En vez de umbrales fijos (que fallan en ligas competitivas como Premier),
        rankeamos al equipo dentro de su liga: tercio superior = GRANDE,
        tercio medio = MEDIO, tercio inferior = CHICO.
        """
        # Revisar cache de ranking de liga
        if league_id not in self._league_stature_ranking:
            self._build_league_stature_ranking(league_id)
        
        ranking = self._league_stature_ranking.get(league_id, {})
        return ranking.get(team_id)
    
    def _build_league_stature_ranking(self, league_id: int):
        """Construye el ranking de estatura para toda la liga (una sola query)."""
        # Intentar con odds
        q = text("""
            SELECT f.home_team_id, AVG(o.odd) as avg_odd, COUNT(*) as n
            FROM fixtures f
            JOIN odds o ON f.id = o.fixture_id
            WHERE f.league_id = :lid
              AND o.bet_name = 'Match Winner' AND o.value = 'Home'
              AND f.status_short IN ('FT', 'AET', 'PEN')
            GROUP BY f.home_team_id
            HAVING n >= 3
            ORDER BY avg_odd ASC
        """)
        try:
            with self.orig_engine.connect() as conn:
                rows = conn.execute(q, {'lid': league_id}).fetchall()
            
            if len(rows) >= 3:
                ranking = {}
                n = len(rows)
                for i, r in enumerate(rows):
                    pct = i / n
                    if pct <= 0.30:
                        ranking[r[0]] = TeamStature.GRANDE
                    elif pct <= 0.70:
                        ranking[r[0]] = TeamStature.MEDIO
                    else:
                        ranking[r[0]] = TeamStature.CHICO
                self._league_stature_ranking[league_id] = ranking
                return
        except Exception:
            pass
        
        # Fallback: proxy
        q2 = text("""
            SELECT f.home_team_id, 
                   SUM(CASE WHEN f.goals_home > f.goals_away THEN 1.0 ELSE 0.0 END) / COUNT(*) as wr,
                   COUNT(*) as n
            FROM fixtures f
            WHERE f.league_id = :lid
              AND f.status_short IN ('FT', 'AET', 'PEN')
            GROUP BY f.home_team_id
            HAVING n >= 3
            ORDER BY wr DESC
        """)
        try:
            with self.orig_engine.connect() as conn:
                rows = conn.execute(q2, {'lid': league_id}).fetchall()
            
            if len(rows) >= 3:
                ranking = {}
                n = len(rows)
                for i, r in enumerate(rows):
                    pct = i / n
                    if pct <= 0.30:
                        ranking[r[0]] = TeamStature.GRANDE
                    elif pct <= 0.70:
                        ranking[r[0]] = TeamStature.MEDIO
                    else:
                        ranking[r[0]] = TeamStature.CHICO
                self._league_stature_ranking[league_id] = ranking
        except Exception:
            pass
    
    def _stature_from_proxy(self, team_id: int, league_id: int) -> TeamStature:
        """Fallback: estatura por ranking de win rate (ya construido en cache)."""
        # _build_league_stature_ranking ya incluye fallback a proxy
        ranking = self._league_stature_ranking.get(league_id, {})
        return ranking.get(team_id, TeamStature.MEDIO)
    
    # =========================================================================
    # FAITH — El corazón del péndulo
    # =========================================================================
    
    def calculate_faith(self, result: str, team_scored: bool, both_scored: bool,
                        team_goals: int, opp_goals: int,
                        team_prob: float, stature: TeamStature,
                        mode: str = 'proxy') -> Tuple[float, float]:
        """
        Calcula la fe de un resultado para el hincha.
        
        El faith depende de la ESTATURA: el hincha grande sufre un empate,
        el hincha chico celebra un empate.
        
        El weight depende de la EXPECTATIVA: si el equipo era muy favorito
        y pierde, duele más (weight alto).
        
        Args:
            result: 'W', 'D', 'L'
            team_scored: True si el equipo anotó
            both_scored: True si ambos anotaron
            team_goals: Goles del equipo
            opp_goals: Goles del rival
            team_prob: Probabilidad de ganar (de odds o proxy)
            stature: Estatura del equipo
            mode: 'odds' o 'proxy'
        
        Returns:
            (faith, weight): fe del resultado y su peso emocional
        """
        if stature == TeamStature.GRANDE:
            # Hincha grande: ganar es OBLIGACIÓN, empate = dolor
            if result == 'W':
                faith = +1.0
            elif result == 'D':
                faith = -0.5
            else:
                faith = -1.0
            weight = team_prob if mode == 'odds' else team_prob
            
        elif stature == TeamStature.MEDIO:
            # Hincha medio: ganar alegra, empate aceptable, perder duele
            if result == 'W':
                faith = +1.0
            elif result == 'D':
                faith = +0.3
            else:
                faith = -0.7 if team_scored else -1.0
            weight = 0.5 + (team_prob * 0.5)
            
        elif stature == TeamStature.CHICO:
            # Hincha chico: ganar es fiesta, empate buenísimo, 
            # perder por poco aceptable si al menos anotó
            if result == 'W':
                faith = +1.5
            elif result == 'D':
                faith = +0.8
            elif result == 'L' and team_scored and (opp_goals - team_goals) <= 1:
                faith = +0.1   # "al menos competimos"
            elif result == 'L' and team_scored:
                faith = -0.3   # "al menos anotamos"
            else:
                faith = -0.8   # "goleada sin anotar"
            weight = 0.3 + (team_prob * 0.3)
            
        else:
            faith = +1.0 if result == 'W' else (-0.5 if result == 'D' else -1.0)
            weight = 0.5
        
        return faith, weight
    
    # =========================================================================
    # PÉNDULO — Score normalizado de fe
    # =========================================================================
    
    def calculate_pendulum(self, faith_weights: List[Tuple[float, float]]) -> float:
        """
        Calcula el péndulo desde una lista de (faith, weight) por partido.
        
        Aplica decay exponencial: partidos recientes pesan más.
        Normaliza a rango [-100, +100].
        
        Args:
            faith_weights: Lista de (faith, weight) en orden cronológico
                          (más antiguo primero, más reciente al final)
        
        Returns:
            Péndulo normalizado [-100, +100]
        """
        n = len(faith_weights)
        if n == 0:
            return 0.0
        
        score = 0.0
        for i, (faith, weight) in enumerate(faith_weights):
            decay = DECAY ** (n - 1 - i)  # Más reciente = decay más alto
            score += faith * weight * decay
        
        max_possible = sum(1.5 * 1.0 * (DECAY ** (n - 1 - i)) for i in range(n))
        
        if max_possible > 0:
            normalized = (score / max_possible) * 100
        else:
            normalized = 0.0
        
        return max(-100.0, min(100.0, normalized))
    
    def get_pendulum_zone(self, score: float) -> PendulumZone:
        """Clasifica un score en zona del péndulo."""
        for zone, (lo, hi) in PENDULUM_THRESHOLDS.items():
            if lo <= score <= hi:
                return zone
        return PendulumZone.NEUTRAL
    
    # =========================================================================
    # HISTORIAL DE EQUIPO — Datos para calcular péndulo
    # =========================================================================
    
    def get_team_history(self, team_id: int, league_id: int,
                         before_date: Optional[str] = None,
                         before_fixture_id: Optional[int] = None,
                         limit: int = WINDOW) -> pd.DataFrame:
        """
        Obtiene los últimos N partidos de un equipo en una liga.
        
        Modo híbrido: intenta cargar con odds, si no hay, usa proxy.
        
        Returns:
            DataFrame con columnas: fixture_id, date, team_role, team_goals,
            opp_goals, result, team_scored, both_scored, team_prob, opp_name, mode
        """
        # Intentar con odds primero
        df = self._history_with_odds(team_id, league_id, before_date,
                                      before_fixture_id, limit)
        mode = 'odds'
        
        if df.empty or len(df) < 3:
            df = self._history_proxy(team_id, league_id, before_date,
                                      before_fixture_id, limit)
            mode = 'proxy'
        
        if not df.empty:
            df['mode'] = mode
        
        return df
    
    def _history_with_odds(self, team_id: int, league_id: int,
                            before_date: Optional[str],
                            before_fixture_id: Optional[int],
                            limit: int) -> pd.DataFrame:
        """Historial con odds reales."""
        date_filter = ""
        params = {'tid': team_id, 'lid': league_id, 'limit': limit}
        
        if before_fixture_id:
            date_filter = "AND f.id < :before_fid"
            params['before_fid'] = before_fixture_id
        elif before_date:
            date_filter = "AND f.date < :before_date"
            params['before_date'] = before_date
        
        q = text(f"""
            SELECT f.id as fixture_id, f.date,
                   f.home_team_id, f.away_team_id,
                   f.goals_home, f.goals_away,
                   COALESCE(ht.name, 'Eq ' || f.home_team_id) as home_name,
                   COALESCE(at.name, 'Eq ' || f.away_team_id) as away_name,
                   MAX(CASE WHEN o.value = 'Home' THEN o.odd END) as odd_home,
                   MAX(CASE WHEN o.value = 'Away' THEN o.odd END) as odd_away
            FROM fixtures f
            LEFT JOIN teams ht ON f.home_team_id = ht.id
            LEFT JOIN teams at ON f.away_team_id = at.id
            JOIN odds o ON f.id = o.fixture_id AND o.bet_name = 'Match Winner'
            WHERE (f.home_team_id = :tid OR f.away_team_id = :tid)
              AND f.league_id = :lid
              AND f.status_short IN ('FT', 'AET', 'PEN')
              {date_filter}
            GROUP BY f.id
            HAVING odd_home IS NOT NULL
            ORDER BY f.date DESC
            LIMIT :limit
        """)
        
        try:
            with self.orig_engine.connect() as conn:
                df = pd.read_sql(q, conn, params=params)
        except Exception:
            return pd.DataFrame()
        
        if df.empty:
            return df
        
        return self._process_history(df, team_id, mode='odds')
    
    def _history_proxy(self, team_id: int, league_id: int,
                        before_date: Optional[str],
                        before_fixture_id: Optional[int],
                        limit: int) -> pd.DataFrame:
        """Historial con proxy (sin odds)."""
        date_filter = ""
        params = {'tid': team_id, 'lid': league_id, 'limit': limit}
        
        if before_fixture_id:
            date_filter = "AND f.id < :before_fid"
            params['before_fid'] = before_fixture_id
        elif before_date:
            date_filter = "AND f.date < :before_date"
            params['before_date'] = before_date
        
        q = text(f"""
            SELECT f.id as fixture_id, f.date,
                   f.home_team_id, f.away_team_id,
                   f.goals_home, f.goals_away,
                   COALESCE(ht.name, 'Eq ' || f.home_team_id) as home_name,
                   COALESCE(at.name, 'Eq ' || f.away_team_id) as away_name
            FROM fixtures f
            LEFT JOIN teams ht ON f.home_team_id = ht.id
            LEFT JOIN teams at ON f.away_team_id = at.id
            WHERE (f.home_team_id = :tid OR f.away_team_id = :tid)
              AND f.league_id = :lid
              AND f.status_short IN ('FT', 'AET', 'PEN')
              {date_filter}
            ORDER BY f.date DESC
            LIMIT :limit
        """)
        
        try:
            with self.orig_engine.connect() as conn:
                df = pd.read_sql(q, conn, params=params)
        except Exception:
            return pd.DataFrame()
        
        if df.empty:
            return df
        
        return self._process_history(df, team_id, mode='proxy')
    
    def _process_history(self, df: pd.DataFrame, team_id: int,
                          mode: str) -> pd.DataFrame:
        """Procesa historial crudo en formato uniforme."""
        records = []
        
        # Ordenar cronológicamente para calcular rolling WR
        df_sorted = df.sort_values('date').reset_index(drop=True)
        win_buffer = []
        
        for _, row in df_sorted.iterrows():
            is_home = row['home_team_id'] == team_id
            tg = int(row['goals_home']) if is_home else int(row['goals_away'])
            og = int(row['goals_away']) if is_home else int(row['goals_home'])
            result = 'W' if tg > og else ('D' if tg == og else 'L')
            
            win_buffer.append(1 if result == 'W' else 0)
            if len(win_buffer) > 10:
                win_buffer.pop(0)
            rolling_wr = sum(win_buffer) / len(win_buffer) if len(win_buffer) >= 3 else 0.5
            
            # Probabilidad del equipo
            if mode == 'odds' and 'odd_home' in row.index:
                odd = row['odd_home'] if is_home else row.get('odd_away', 3.0)
                if odd and odd > 0:
                    team_prob = 1.0 / odd
                else:
                    team_prob = rolling_wr
            else:
                team_prob = rolling_wr
            
            opp_name = row['away_name'] if is_home else row['home_name']
            
            records.append({
                'fixture_id': row['fixture_id'],
                'date': row['date'],
                'team_role': 'home' if is_home else 'away',
                'team_goals': tg,
                'opp_goals': og,
                'result': result,
                'team_scored': tg > 0,
                'both_scored': tg > 0 and og > 0,
                'team_prob': min(0.95, max(0.05, team_prob)),
                'opp_name': opp_name,
                'rolling_wr': rolling_wr,
            })
        
        result_df = pd.DataFrame(records)
        # Volver a DESC (más reciente primero)
        result_df = result_df.sort_values('date', ascending=False).reset_index(drop=True)
        return result_df
    
    # =========================================================================
    # PÉNDULO COMPLETO DE UN EQUIPO
    # =========================================================================
    
    def compute_team_pendulum(self, team_id: int, league_id: int,
                               before_date: Optional[str] = None,
                               before_fixture_id: Optional[int] = None) -> TeamPendulum:
        """
        Calcula el péndulo completo de un equipo.
        
        Returns:
            TeamPendulum con score, zona, estatura, detalles
        """
        # Estatura
        stature = self.get_team_stature(team_id, league_id)
        
        # Historial
        history = self.get_team_history(team_id, league_id,
                                         before_date=before_date,
                                         before_fixture_id=before_fixture_id,
                                         limit=WINDOW)
        
        if history.empty:
            team_name = self._get_team_name(team_id)
            return TeamPendulum(
                team_id=team_id, team_name=team_name,
                league_id=league_id, stature=stature,
                pendulum_score=0.0, zone=PendulumZone.NEUTRAL,
                mode='proxy'
            )
        
        mode = history.iloc[0].get('mode', 'proxy') if 'mode' in history.columns else 'proxy'
        team_name = self._get_team_name(team_id)
        
        # Calcular faith para cada partido (cronológico: antiguo → reciente)
        history_chrono = history.iloc[::-1].reset_index(drop=True)
        faith_weights = []
        faith_details = []
        last_results = []
        
        for _, row in history_chrono.iterrows():
            faith, weight = self.calculate_faith(
                result=row['result'],
                team_scored=row['team_scored'],
                both_scored=row['both_scored'],
                team_goals=row['team_goals'],
                opp_goals=row['opp_goals'],
                team_prob=row['team_prob'],
                stature=stature,
                mode=mode
            )
            faith_weights.append((faith, weight))
            faith_details.append({
                'date': row['date'],
                'opp': row['opp_name'],
                'role': row['team_role'],
                'score': f"{row['team_goals']}-{row['opp_goals']}",
                'result': row['result'],
                'faith': round(faith, 2),
                'weight': round(weight, 2),
            })
            last_results.append(row['result'])
        
        # Péndulo
        pendulum_score = self.calculate_pendulum(faith_weights)
        zone = self.get_pendulum_zone(pendulum_score)
        
        # Invertir para que el más reciente esté primero en display
        last_results = list(reversed(last_results))
        faith_details = list(reversed(faith_details))
        
        # Goal flag
        goal_flag, scores_pct = self._get_goal_flag(
            pendulum_score, is_home=True)  # se actualiza en analyze_match
        
        return TeamPendulum(
            team_id=team_id,
            team_name=team_name,
            league_id=league_id,
            stature=stature,
            pendulum_score=round(pendulum_score, 1),
            zone=zone,
            mode=mode,
            last_results=last_results,
            faith_details=faith_details,
            goal_flag=goal_flag,
            team_scores_pct=scores_pct,
        )
    
    def _get_goal_flag(self, pendulum: float, is_home: bool) -> Tuple[GoalFlag, float]:
        """Determina flag de goles basado en péndulo absoluto."""
        if is_home:
            if pendulum >= 18:
                return GoalFlag.SCORES, 0.859
            elif pendulum <= -18:
                return GoalFlag.SECO, 0.695
            else:
                return GoalFlag.NORMAL, 0.763
        else:
            if pendulum >= 18:
                return GoalFlag.SCORES, 0.738
            elif pendulum <= -18:
                return GoalFlag.SECO, 0.551
            else:
                return GoalFlag.NORMAL, 0.660
    
    def _get_team_name(self, team_id: int) -> str:
        """Obtiene nombre del equipo."""
        try:
            q = text("SELECT name FROM teams WHERE id = :tid")
            with self.orig_engine.connect() as conn:
                row = conn.execute(q, {'tid': team_id}).fetchone()
                if row:
                    return row[0]
        except Exception:
            pass
        return f"Equipo {team_id}"
    
    # =========================================================================
    # GAP Y FLAG
    # =========================================================================
    
    def calculate_gap(self, home_pendulum: float, away_pendulum: float) -> float:
        """Calcula el gap de péndulo."""
        return round(home_pendulum - away_pendulum, 1)
    
    def get_flag(self, gap: float) -> FlagType:
        """Asigna flag basado en gap."""
        for flag, (lo, hi) in FLAG_THRESHOLDS.items():
            if lo <= gap < hi:
                return flag
        return FlagType.NONE
    
    def get_edge_pp(self, flag: FlagType) -> float:
        """Retorna el edge en pp del flag sobre baseline."""
        edges = {
            FlagType.HOME_STRONG: +16.0,
            FlagType.HOME: +10.0,
            FlagType.NONE: 0.0,
            FlagType.AWAY: +10.0,
            FlagType.AWAY_STRONG: +12.0,
        }
        return edges.get(flag, 0.0)
    
    # =========================================================================
    # PROBABILIDADES Y MERCADOS
    # =========================================================================
    
    def get_probabilities(self, gap: float) -> Tuple[float, float, float]:
        """
        Retorna (prob_home, prob_draw, prob_away) basado en el gap.
        Interpolación lineal entre rangos de la lookup table.
        """
        for (lo, hi), (hw, dr, aw, _, _) in GAP_LOOKUP.items():
            if lo <= gap < hi:
                return (hw, dr, aw)
        return (BASELINE['home_win'], BASELINE['draw'], BASELINE['away_win'])
    
    def get_expected_margin(self, gap: float) -> float:
        """Margen esperado basado en gap."""
        for (lo, hi), (_, _, _, margin, _) in GAP_LOOKUP.items():
            if lo <= gap < hi:
                return margin
        return BASELINE['margin']
    
    def get_goleada_pct(self, gap: float) -> float:
        """Probabilidad de goleada (3+ goles diferencia)."""
        for (lo, hi), (_, _, _, _, gol) in GAP_LOOKUP.items():
            if lo <= gap < hi:
                return gol
        return BASELINE['goleada']
    
    def _build_handicap_suggestions(self, flag: FlagType,
                                     home_name: str, away_name: str) -> List[HandicapSuggestion]:
        """Construye sugerencias de hándicap europeo."""
        suggestions = []
        
        if flag in (FlagType.HOME_STRONG, FlagType.HOME):
            lookup = HANDICAP_LOOKUP.get(flag, {})
            for h in [1, 2, 3]:
                win_pct, draw_pct = lookup.get(h, (0.5, 0.2))
                suggestions.append(HandicapSuggestion(
                    team_name=away_name,
                    handicap=h,
                    win_pct=win_pct,
                    draw_pct=draw_pct,
                    suggested=(h == 2 if flag == FlagType.HOME_STRONG else h == 1),
                ))
        
        elif flag in (FlagType.AWAY_STRONG, FlagType.AWAY):
            lookup = HANDICAP_LOOKUP.get(flag, {})
            for h in [1, 2, 3]:
                win_pct, draw_pct = lookup.get(h, (0.5, 0.2))
                suggestions.append(HandicapSuggestion(
                    team_name=home_name,
                    handicap=h,
                    win_pct=win_pct,
                    draw_pct=draw_pct,
                    suggested=(h == 2 if flag == FlagType.AWAY_STRONG else h == 1),
                ))
        
        return suggestions
    
    def _build_market_suggestions(self, flag: FlagType, gap: float,
                                    home: TeamPendulum, away: TeamPendulum,
                                    prob_h: float, prob_d: float, prob_a: float,
                                    odds_home: Optional[float] = None,
                                    odds_draw: Optional[float] = None,
                                    odds_away: Optional[float] = None) -> List[MarketSuggestion]:
        """Construye sugerencias de mercado."""
        suggestions = []
        base = BASELINE
        
        # 1X2 principal
        if flag in (FlagType.HOME_STRONG, FlagType.HOME):
            edge = prob_h - base['home_win']
            suggestions.append(MarketSuggestion(
                market="Home Win",
                probability=prob_h,
                baseline=base['home_win'],
                edge_pp=round(edge * 100, 0),
                description=f"{home.team_name} gana {prob_h*100:.0f}% (base {base['home_win']*100:.0f}%)"
            ))
        elif flag in (FlagType.AWAY_STRONG, FlagType.AWAY):
            edge = prob_a - base['away_win']
            suggestions.append(MarketSuggestion(
                market="Away Win",
                probability=prob_a,
                baseline=base['away_win'],
                edge_pp=round(edge * 100, 0),
                description=f"{away.team_name} gana {prob_a*100:.0f}% (base {base['away_win']*100:.0f}%)"
            ))
        
        # Team to Score
        if home.goal_flag == GoalFlag.SCORES:
            suggestions.append(MarketSuggestion(
                market=f"{home.team_name} Anota",
                probability=home.team_scores_pct,
                baseline=0.763,
                edge_pp=round((home.team_scores_pct - 0.763) * 100, 0),
                description=f"Eufórico: anota en {home.team_scores_pct*100:.0f}% de partidos"
            ))
        elif home.goal_flag == GoalFlag.SECO:
            suggestions.append(MarketSuggestion(
                market=f"{home.team_name} NO Anota",
                probability=1 - home.team_scores_pct,
                baseline=1 - 0.763,
                edge_pp=round((1 - home.team_scores_pct - (1 - 0.763)) * 100, 0),
                description=f"En crisis: no anota en {(1-home.team_scores_pct)*100:.0f}%"
            ))
        
        if away.goal_flag == GoalFlag.SCORES:
            suggestions.append(MarketSuggestion(
                market=f"{away.team_name} Anota",
                probability=away.team_scores_pct,
                baseline=0.660,
                edge_pp=round((away.team_scores_pct - 0.660) * 100, 0),
                description=f"Eufórico: anota de visita en {away.team_scores_pct*100:.0f}%"
            ))
        elif away.goal_flag == GoalFlag.SECO:
            suggestions.append(MarketSuggestion(
                market=f"{away.team_name} NO Anota",
                probability=1 - away.team_scores_pct,
                baseline=1 - 0.660,
                edge_pp=round((1 - away.team_scores_pct - (1 - 0.660)) * 100, 0),
                description=f"En crisis: no anota de visita en {(1-away.team_scores_pct)*100:.0f}%"
            ))
        
        # Value bets — DESACTIVADO
        # Nota: las probabilidades del lookup table son promedios genéricos de 42k partidos.
        # Compararlas con odds específicas de ESTE partido es engañoso porque las odds
        # ya incorporan información específica (calidad de equipos, lesiones, etc.)
        # que nuestro modelo genérico no tiene.
        # El edge real está en el FLAG (efecto validado de +10 a +16pp sobre baseline),
        # no en la comparación directa con odds del mercado.
        
        return suggestions
    
    # =========================================================================
    # ANÁLISIS DE PARTIDO COMPLETO
    # =========================================================================
    
    def analyze_match(self, home_team_id: int, away_team_id: int,
                      league_id: int,
                      fixture_id: Optional[int] = None,
                      match_date: Optional[str] = None,
                      odds_home: Optional[float] = None,
                      odds_draw: Optional[float] = None,
                      odds_away: Optional[float] = None) -> MatchAnalysis:
        """
        Análisis completo de un partido.
        
        Este es el método principal. Calcula péndulos, gap, flag, 
        y genera todas las sugerencias.
        
        Args:
            home_team_id: ID del equipo local
            away_team_id: ID del equipo visitante
            league_id: ID de la liga
            fixture_id: ID del fixture (para filtrar historial)
            match_date: Fecha del partido (alternativa a fixture_id)
            odds_home/draw/away: Odds si disponibles
            
        Returns:
            MatchAnalysis completo
        """
        # Péndulos
        home_pend = self.compute_team_pendulum(
            home_team_id, league_id,
            before_date=match_date,
            before_fixture_id=fixture_id
        )
        
        away_pend = self.compute_team_pendulum(
            away_team_id, league_id,
            before_date=match_date,
            before_fixture_id=fixture_id
        )
        
        # Actualizar goal flags con contexto home/away
        home_pend.goal_flag, home_pend.team_scores_pct = self._get_goal_flag(
            home_pend.pendulum_score, is_home=True)
        away_pend.goal_flag, away_pend.team_scores_pct = self._get_goal_flag(
            away_pend.pendulum_score, is_home=False)
        
        # Gap y flag
        gap = self.calculate_gap(home_pend.pendulum_score, away_pend.pendulum_score)
        flag = self.get_flag(gap)
        edge = self.get_edge_pp(flag)
        
        # Probabilidades
        prob_h, prob_d, prob_a = self.get_probabilities(gap)
        margin = self.get_expected_margin(gap)
        goleada = self.get_goleada_pct(gap)
        
        # Sugerencias
        handicap_sugs = self._build_handicap_suggestions(
            flag, home_pend.team_name, away_pend.team_name)
        
        market_sugs = self._build_market_suggestions(
            flag, gap, home_pend, away_pend,
            prob_h, prob_d, prob_a,
            odds_home, odds_draw, odds_away)
        
        # League name
        league_name = self.get_league_name(league_id)
        
        analysis = MatchAnalysis(
            fixture_id=fixture_id,
            match_date=match_date or "",
            league_id=league_id,
            league_name=league_name,
            home=home_pend,
            away=away_pend,
            gap=gap,
            flag=flag,
            flag_emoji=FLAG_EMOJIS[flag],
            flag_description=FLAG_DESCRIPTIONS[flag],
            edge_pp=edge,
            prob_home=prob_h,
            prob_draw=prob_d,
            prob_away=prob_a,
            expected_margin=margin,
            goleada_pct=goleada,
            handicap_suggestions=handicap_sugs,
            market_suggestions=market_sugs,
            odds_home=odds_home,
            odds_draw=odds_draw,
            odds_away=odds_away,
        )
        
        # Guardar en cache
        self._cache_analysis(analysis)
        
        return analysis
    
    def _cache_analysis(self, analysis: MatchAnalysis):
        """Guarda análisis en pendulum.db."""
        if not analysis.fixture_id:
            return
        
        try:
            now = datetime.now().isoformat()
            
            # Péndulos
            for pend in [analysis.home, analysis.away]:
                q = text("""
                    INSERT OR REPLACE INTO pendulum_history
                    (team_id, league_id, fixture_id, pendulum_score, zone, stature, mode, calculated_at)
                    VALUES (:tid, :lid, :fid, :score, :zone, :stature, :mode, :now)
                """)
                with self.pend_engine.connect() as conn:
                    conn.execute(q, {
                        'tid': pend.team_id, 'lid': pend.league_id,
                        'fid': analysis.fixture_id,
                        'score': pend.pendulum_score,
                        'zone': pend.zone.value,
                        'stature': pend.stature.value,
                        'mode': pend.mode, 'now': now,
                    })
                    conn.commit()
            
            # Flag del partido
            q = text("""
                INSERT OR REPLACE INTO match_flags
                (fixture_id, home_team_id, away_team_id, home_pendulum, away_pendulum,
                 gap, flag, edge_pp, calculated_at)
                VALUES (:fid, :htid, :atid, :hp, :ap, :gap, :flag, :edge, :now)
            """)
            with self.pend_engine.connect() as conn:
                conn.execute(q, {
                    'fid': analysis.fixture_id,
                    'htid': analysis.home.team_id,
                    'atid': analysis.away.team_id,
                    'hp': analysis.home.pendulum_score,
                    'ap': analysis.away.pendulum_score,
                    'gap': analysis.gap,
                    'flag': analysis.flag.value,
                    'edge': analysis.edge_pp,
                    'now': now,
                })
                conn.commit()
                
        except Exception as e:
            logger.warning(f"Error cacheando análisis: {e}")
    
    # =========================================================================
    # PRÓXIMOS PARTIDOS
    # =========================================================================
    
    def get_upcoming_matches(self, league_id: int,
                              days_ahead: int = 7) -> List[Dict]:
        """Obtiene próximos partidos de una liga."""
        today = date.today()
        end = today + timedelta(days=days_ahead)
        
        q = text("""
            SELECT f.id as fixture_id, f.date, f.league_id,
                   f.home_team_id, f.away_team_id,
                   f.status_short,
                   COALESCE(ht.name, 'Eq ' || f.home_team_id) as home_name,
                   COALESCE(at.name, 'Eq ' || f.away_team_id) as away_name
            FROM fixtures f
            LEFT JOIN teams ht ON f.home_team_id = ht.id
            LEFT JOIN teams at ON f.away_team_id = at.id
            WHERE f.league_id = :lid
              AND f.status_short = 'NS'
              AND DATE(f.date) >= :start
              AND DATE(f.date) <= :end
            ORDER BY f.date ASC
        """)
        
        try:
            with self.orig_engine.connect() as conn:
                rows = conn.execute(q, {
                    'lid': league_id,
                    'start': today.strftime('%Y-%m-%d'),
                    'end': end.strftime('%Y-%m-%d'),
                }).fetchall()
        except Exception:
            return []
        
        cols = ['fixture_id', 'date', 'league_id', 'home_team_id',
                'away_team_id', 'status', 'home_name', 'away_name']
        return [dict(zip(cols, r)) for r in rows]
    
    # Ligas excluidas: amistosos y torneos sin presión real del hincha
    EXCLUDED_LEAGUES = {
        667,    # Friendlies Clubs
        10,     # Friendlies Nations
        15,     # FIFA Intercontinental Cup
        46,     # EFL Trophy
    }
    
    # Ligas prioritarias (las que mejor conocemos)
    PRIORITY_LEAGUES = [281, 39, 140, 135, 78, 61, 128, 71, 262, 239, 265, 94]
    
    def get_available_leagues(self, include_all: bool = False) -> List[Dict]:
        """Retorna ligas con partidos disponibles (sin amistosos)."""
        q = text("""
            SELECT f.league_id, COUNT(*) as total,
                   SUM(CASE WHEN f.status_short = 'NS' THEN 1 ELSE 0 END) as upcoming
            FROM fixtures f
            GROUP BY f.league_id
            HAVING total >= 20
            ORDER BY upcoming DESC, total DESC
        """)
        
        try:
            with self.orig_engine.connect() as conn:
                rows = conn.execute(q).fetchall()
        except Exception:
            return []
        
        leagues = []
        for r in rows:
            lid = r[0]
            if not include_all and lid in self.EXCLUDED_LEAGUES:
                continue
            leagues.append({
                'league_id': lid,
                'name': self.get_league_name(lid),
                'total_matches': r[1],
                'upcoming': r[2],
                'priority': self.PRIORITY_LEAGUES.index(lid) if lid in self.PRIORITY_LEAGUES else 999,
            })
        
        # Ordenar: primero por prioridad, luego por upcoming
        leagues.sort(key=lambda x: (x['priority'], -x['upcoming']))
        return leagues
    
    def analyze_upcoming(self, league_id: int,
                          days_ahead: int = 7) -> List[MatchAnalysis]:
        """Analiza todos los próximos partidos de una liga."""
        matches = self.get_upcoming_matches(league_id, days_ahead)
        analyses = []
        
        for m in matches:
            # Buscar odds si existen
            odds = self._get_match_odds(m['fixture_id'])
            
            analysis = self.analyze_match(
                home_team_id=m['home_team_id'],
                away_team_id=m['away_team_id'],
                league_id=league_id,
                fixture_id=m['fixture_id'],
                match_date=m['date'],
                odds_home=odds.get('home'),
                odds_draw=odds.get('draw'),
                odds_away=odds.get('away'),
            )
            analyses.append(analysis)
        
        return analyses
    
    def _get_match_odds(self, fixture_id: int) -> Dict[str, Optional[float]]:
        """Obtiene odds de un partido si existen."""
        q = text("""
            SELECT
                MAX(CASE WHEN value = 'Home' THEN odd END) as odd_home,
                MAX(CASE WHEN value = 'Draw' THEN odd END) as odd_draw,
                MAX(CASE WHEN value = 'Away' THEN odd END) as odd_away
            FROM odds
            WHERE fixture_id = :fid AND bet_name = 'Match Winner'
        """)
        try:
            with self.orig_engine.connect() as conn:
                row = conn.execute(q, {'fid': fixture_id}).fetchone()
                if row and row[0]:
                    return {'home': row[0], 'draw': row[1], 'away': row[2]}
        except Exception:
            pass
        return {'home': None, 'draw': None, 'away': None}
    
    # =========================================================================
    # FORMATEO DE TEXTO (para consola / debug)
    # =========================================================================
    
    def format_analysis(self, a: MatchAnalysis) -> str:
        """Formatea un análisis como texto legible."""
        lines = []
        sep = "=" * 70
        
        lines.append(f"\n{sep}")
        lines.append(f"  ⚖️ LEY DE LA FE PERDIDA — {a.home.team_name} vs {a.away.team_name}")
        lines.append(f"  {a.league_name} | {a.match_date}")
        lines.append(sep)
        
        # Péndulos
        hz = ZONE_EMOJIS[a.home.zone]
        az = ZONE_EMOJIS[a.away.zone]
        hs = STATURE_EMOJIS[a.home.stature]
        as_ = STATURE_EMOJIS[a.away.stature]
        
        lines.append(f"\n  LOCAL: {a.home.team_name}")
        lines.append(f"    {hs} Estatura: {a.home.stature.value.upper()}")
        lines.append(f"    {hz} Péndulo: {a.home.pendulum_score:+.1f} ({a.home.zone.value}) [{a.home.mode}]")
        racha_h = "".join(a.home.last_results[:5])
        lines.append(f"    Racha: {racha_h}")
        
        lines.append(f"\n  VISITANTE: {a.away.team_name}")
        lines.append(f"    {as_} Estatura: {a.away.stature.value.upper()}")
        lines.append(f"    {az} Péndulo: {a.away.pendulum_score:+.1f} ({a.away.zone.value}) [{a.away.mode}]")
        racha_a = "".join(a.away.last_results[:5])
        lines.append(f"    Racha: {racha_a}")
        
        # Gap y flag
        lines.append(f"\n  {'─'*50}")
        lines.append(f"  GAP: {a.gap:+.1f}")
        lines.append(f"  {a.flag_emoji} FLAG: {a.flag.value} — {a.flag_description}")
        
        if a.flag != FlagType.NONE:
            lines.append(f"  Edge: +{a.edge_pp:.0f}pp sobre baseline")
        
        # Probabilidades
        lines.append(f"\n  📊 Probabilidades (lookup table empírica):")
        lines.append(f"    Home {a.prob_home*100:.0f}% | Draw {a.prob_draw*100:.0f}% | Away {a.prob_away*100:.0f}%")
        lines.append(f"    Baseline: Home 45% | Draw 27% | Away 28%")
        
        if a.odds_home:
            lines.append(f"    Odds: Home {a.odds_home:.2f} | Draw {a.odds_draw:.2f} | Away {a.odds_away:.2f}")
        
        # Margen
        lines.append(f"\n  📏 Margen esperado: {a.expected_margin:+.2f} goles")
        lines.append(f"  💥 Goleada (3+): {a.goleada_pct*100:.1f}%")
        
        # Sugerencias de mercado
        if a.market_suggestions:
            lines.append(f"\n  💰 ¿QUÉ SE LLEVA EL HINCHA?")
            for ms in a.market_suggestions:
                lines.append(f"    ⚽ {ms.market}: {ms.probability*100:.0f}% "
                            f"(base {ms.baseline*100:.0f}%, {ms.edge_pp:+.0f}pp)")
        
        # Hándicap
        if a.handicap_suggestions:
            lines.append(f"\n  🎯 HÁNDICAP EUROPEO (underdog):")
            for hs in a.handicap_suggestions:
                star = " ⭐" if hs.suggested else ""
                lines.append(f"    {hs.team_name} +{hs.handicap}: gana {hs.win_pct*100:.0f}%{star}")
        
        lines.append(sep)
        return "\n".join(lines)


# =============================================================================
# PARA USO STANDALONE
# =============================================================================

if __name__ == "__main__":
    engine = FePerdidaEngine()
    
    # Listar ligas disponibles (sin amistosos)
    leagues = engine.get_available_leagues()
    print("\n⚖️ LEY DE LA FE PERDIDA — Engine v1")
    print("=" * 50)
    print(f"\nLigas disponibles ({len(leagues)}):")
    for lg in leagues[:15]:
        marker = " ⭐" if lg['league_id'] in engine.PRIORITY_LEAGUES else ""
        print(f"  [{lg['league_id']}] {lg['name']} — "
              f"{lg['total_matches']} partidos, {lg['upcoming']} próximos{marker}")
    
    # Analizar próximos de las ligas prioritarias
    analyzed = 0
    for lg in leagues:
        if lg['upcoming'] > 0 and analyzed < 3:
            print(f"\n⏳ Analizando próximos de {lg['name']}...")
            analyses = engine.analyze_upcoming(lg['league_id'], days_ahead=14)
            
            flags_found = 0
            for a in analyses[:8]:
                print(engine.format_analysis(a))
                if a.flag != FlagType.NONE:
                    flags_found += 1
            
            if flags_found == 0 and len(analyses) > 0:
                print(f"\n  ℹ️ {len(analyses)} partidos analizados, ningún flag activo")
            elif flags_found > 0:
                print(f"\n  🚩 {flags_found} flags activos de {len(analyses)} partidos")
            
            analyzed += 1