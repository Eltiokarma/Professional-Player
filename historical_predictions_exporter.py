# -*- coding: utf-8 -*-
"""
historical_predictions_exporter.py
===================================
EXPORTADOR DE PREDICCIONES HISTORICAS - SAD v6

Recorre partidos YA JUGADOS y genera predicciones retroactivas
de los 3 modelos ML como si fuera antes del partido.

MODELOS INTEGRADOS:
  1. Ley de las Culebras (AnticulebraEngine) - ml_break_score, ICF, 1X2
  2. Ley del Marcador (MLGoalsPredictorV6) - lambdas Poisson, Over/Under, BTTS
  3. Ley de las Constantes (GlobalConstantPredictor) - cambio de K predicho

SALIDA:
  - SQLite: historical_predictions.db (tabla principal + tabla de constantes)
  - CSV: historical_predictions_main.csv (una fila por partido)
  - CSV: historical_predictions_constants.csv (una fila por equipo/partido/constante)

Autor: SAD v6
Fecha: Febrero 2026
"""

import os
import sys
import logging
import sqlite3
import traceback
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# BUSCAR RAIZ DEL PROYECTO
# ============================================================================

def find_project_root() -> str:
    """Encuentra la raiz del proyecto (donde estan sad.db, constants.db).
    
    IMPORTANTE: Las bases de datos estan al MISMO NIVEL que la carpeta src/,
    NO dentro de ella. Estructura esperada:
        D:/VSCode Ejercicios 02/
            sad.db          <-- AQUI
            constants.db    <-- AQUI
            levels.db       <-- AQUI
            src/
                historical_predictions_exporter.py  (este archivo)
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    
    logger.info(f"[ROOT] script_dir: {script_dir}")
    logger.info(f"[ROOT] parent_dir: {parent_dir}")
    
    # Si estamos dentro de src/, las DBs estan en el padre
    if os.path.basename(script_dir).lower() == 'src':
        if os.path.exists(os.path.join(parent_dir, 'sad.db')):
            logger.info(f"[ROOT] -> Usando padre de src/: {parent_dir}")
            return parent_dir
    
    # Prioridad 1: Padre del directorio del script
    if os.path.exists(os.path.join(parent_dir, 'sad.db')):
        logger.info(f"[ROOT] -> Padre tiene sad.db: {parent_dir}")
        return parent_dir
    
    # Prioridad 2: Directorio del script mismo
    if os.path.exists(os.path.join(script_dir, 'sad.db')):
        logger.info(f"[ROOT] -> Script dir tiene sad.db: {script_dir}")
        return script_dir
    
    # Prioridad 3: CWD y busqueda hacia arriba
    cwd = os.getcwd()
    check = cwd
    for _ in range(6):
        if os.path.exists(os.path.join(check, 'sad.db')):
            logger.info(f"[ROOT] -> Encontrado buscando arriba: {check}")
            return check
        check = os.path.dirname(check)
    
    logger.warning(f"[ROOT] sad.db no encontrado! Usando: {parent_dir}")
    return parent_dir


# ============================================================================
# CLASE PRINCIPAL
# ============================================================================

class HistoricalPredictionsExporter:
    """
    Exportador de predicciones historicas para los 3 modelos ML de SAD.
    
    Uso:
        exporter = HistoricalPredictionsExporter()
        exporter.run(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            league_ids=[128, 129, 130, ...],
            progress_callback=my_callback
        )
    """
    
    # Constantes K a predecir y su tipo
    K_CONSTANTS_HOME = [
        'k',             # General (ternario)
        'k_local',       # Solo local (ternario)
        'k_goles_anotado',         # General goles (binario)
        'k_goles_recibido',        # General goles (binario)
        'k_goles_local_anotado',   # Solo local goles (binario)
        'k_goles_local_recibido',  # Solo local goles (binario)
    ]
    
    K_CONSTANTS_AWAY = [
        'k',             # General (ternario)
        'k_visita',      # Solo visita (ternario)
        'k_goles_anotado',         # General goles (binario)
        'k_goles_recibido',        # General goles (binario)
        'k_goles_visita_anotado',  # Solo visita goles (binario)
        'k_goles_visita_recibido', # Solo visita goles (binario)
    ]
    
    BINARY_CONSTANTS = [
        'k_goles_anotado', 'k_goles_recibido',
        'k_goles_local_anotado', 'k_goles_local_recibido',
        'k_goles_visita_anotado', 'k_goles_visita_recibido',
    ]
    
    # Mapeo de constant_type a columna en constants.db
    K_COL_MAP = {
        'k': 'k_positivo',
        'k_local': 'k_positivo_local',
        'k_visita': 'k_positivo_visita',
        'k_goles_anotado': 'k_goles_anotado',
        'k_goles_recibido': 'k_goles_recibido',
        'k_goles_local_anotado': 'k_goles_local_anotado',
        'k_goles_local_recibido': 'k_goles_local_recibido',
        'k_goles_visita_anotado': 'k_goles_visita_anotado',
        'k_goles_visita_recibido': 'k_goles_visita_recibido',
    }
    
    RESET_THRESHOLD = 0.05
    
    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = find_project_root()
        
        # ============================================================
        # DEFENSA: Si estamos dentro de src/ y el padre tiene sad.db,
        # preferir el padre (la DB principal es mas grande/completa)
        # ============================================================
        parent_candidate = os.path.dirname(project_root)
        parent_sad = os.path.join(parent_candidate, 'sad.db')
        current_sad = os.path.join(project_root, 'sad.db')
        
        if os.path.exists(parent_sad) and os.path.exists(current_sad):
            # Hay sad.db en ambos dirs - usar el mas grande (el principal)
            parent_size = os.path.getsize(parent_sad)
            current_size = os.path.getsize(current_sad)
            logger.info(f"[ROOT] sad.db en padre: {parent_size:,} bytes ({parent_candidate})")
            logger.info(f"[ROOT] sad.db en actual: {current_size:,} bytes ({project_root})")
            if parent_size > current_size:
                logger.info(f"[ROOT] -> Usando padre (DB mas grande)")
                project_root = parent_candidate
        elif os.path.exists(parent_sad) and not os.path.exists(current_sad):
            logger.info(f"[ROOT] sad.db solo en padre -> usando: {parent_candidate}")
            project_root = parent_candidate
        
        self.project_root = project_root
        self.sad_db = os.path.join(project_root, 'sad.db')
        self.constants_db = os.path.join(project_root, 'constants.db')
        self.levels_db = os.path.join(project_root, 'levels.db')
        self.discreto_db = os.path.join(project_root, 'discreto.db')
        
        # Validar que existan las DBs
        for db_name, db_path in [('sad.db', self.sad_db), ('constants.db', self.constants_db)]:
            if not os.path.exists(db_path):
                raise FileNotFoundError(f"No se encontro {db_name} en {db_path}")
        
        # Engines
        self.sad_engine = create_engine(f'sqlite:///{self.sad_db}', echo=False)
        self.const_engine = create_engine(f'sqlite:///{self.constants_db}', echo=False)
        
        if os.path.exists(self.levels_db):
            self.levels_engine = create_engine(f'sqlite:///{self.levels_db}', echo=False)
        else:
            self.levels_engine = None
            logger.warning("levels.db no encontrado - niveles no disponibles")
        
        # Modelos (se cargan lazy)
        self._culebras_engine = None
        self._goals_predictor = None
        self._constants_predictor = None
        
        # Caches
        self._team_names_cache = {}
        self._league_names_cache = {}
        self._constants_cache = {}  # (team_id, date_str) -> dict
        self._levels_cache = {}     # (team_id, date_str) -> float
        
        # Output dir
        self.output_dir = os.path.join(project_root, 'historical_exports')
        os.makedirs(self.output_dir, exist_ok=True)
        
        logger.info(f"HistoricalPredictionsExporter inicializado")
        logger.info(f"  Raiz: {project_root}")
        logger.info(f"  sad.db: {os.path.exists(self.sad_db)} ({self.sad_db})")
        logger.info(f"  constants.db: {os.path.exists(self.constants_db)}")
        logger.info(f"  levels.db: {os.path.exists(self.levels_db)}")
        logger.info(f"  Output: {self.output_dir}")
        
        # Diagnostico: verificar contenido de sad.db
        try:
            with self.sad_engine.connect() as conn:
                from sqlalchemy import text as _t
                r1 = conn.execute(_t("SELECT COUNT(*) FROM fixtures")).fetchone()
                r2 = conn.execute(_t("SELECT COUNT(*) FROM fixtures WHERE status_long = 'Match Finished'")).fetchone()
                r3 = conn.execute(_t("SELECT MIN(date), MAX(date) FROM fixtures WHERE status_long = 'Match Finished'")).fetchone()
                logger.info(f"  [DIAG] Total fixtures: {r1[0]}, Terminados: {r2[0]}")
                if r3[0]:
                    logger.info(f"  [DIAG] Rango fechas: {r3[0][:19]} a {r3[1][:19]}")
                else:
                    logger.warning("  [DIAG] No hay partidos con status_long='Match Finished'")
        except Exception as e:
            logger.warning(f"  [DIAG] Error verificando sad.db: {e}")
    
    # ========================================================================
    # CARGA LAZY DE MODELOS
    # ========================================================================
    
    def _get_culebras_engine(self):
        """Carga el motor de culebras (lazy)."""
        if self._culebras_engine is None:
            try:
                # Intentar import relativo primero
                try:
                    from ui.anticulebra.anticulebra_engine import AnticulebraEngine
                except ImportError:
                    try:
                        from ui.anticulebra.anticulebra_engine import AnticulebraEngine
                    except ImportError:
                        # Agregar src al path
                        src_dir = os.path.join(self.project_root, 'src')
                        if src_dir not in sys.path:
                            sys.path.insert(0, src_dir)
                        from ui.anticulebra.anticulebra_engine import AnticulebraEngine
                
                self._culebras_engine = AnticulebraEngine()
                logger.info("[OK] Motor Culebras cargado")
            except Exception as e:
                logger.error(f"Error cargando motor Culebras: {e}")
                self._culebras_engine = None
        return self._culebras_engine
    
    def _get_goals_predictor(self):
        """Carga el predictor de goles (lazy)."""
        if self._goals_predictor is None:
            try:
                try:
                    from ml_goals_predictor_v6 import MLGoalsPredictorV6
                except ImportError:
                    try:
                        from ml_goals_predictor_v6 import MLGoalsPredictorV6
                    except ImportError:
                        src_dir = os.path.join(self.project_root, 'src')
                        if src_dir not in sys.path:
                            sys.path.insert(0, src_dir)
                        from ml_goals_predictor_v6 import MLGoalsPredictorV6
                
                predictor = MLGoalsPredictorV6(project_root=self.project_root)
                if not predictor.is_trained:
                    if not predictor.load_model():
                        logger.warning("Modelo de goles no entrenado - entrenando...")
                        predictor.train(team_ids=None, max_matches=None, test_ratio=0.15)
                
                self._goals_predictor = predictor
                logger.info("[OK] Predictor de Goles V6 cargado")
            except Exception as e:
                logger.error(f"Error cargando predictor de goles: {e}")
                self._goals_predictor = None
        return self._goals_predictor
    
    def _get_constants_predictor(self):
        """Carga el predictor de constantes (lazy)."""
        if self._constants_predictor is None:
            try:
                try:
                    from utils.global_constant_predictor import GlobalConstantPredictor
                except ImportError:
                    try:
                        from utils.global_constant_predictor import GlobalConstantPredictor
                    except ImportError:
                        src_dir = os.path.join(self.project_root, 'src')
                        if src_dir not in sys.path:
                            sys.path.insert(0, src_dir)
                        from utils.global_constant_predictor import GlobalConstantPredictor
                
                predictor = GlobalConstantPredictor()
                predictor.load_models(load_global=True)
                
                self._constants_predictor = predictor
                logger.info("[OK] Predictor de Constantes cargado")
            except Exception as e:
                logger.error(f"Error cargando predictor de constantes: {e}")
                self._constants_predictor = None
        return self._constants_predictor
    
    # ========================================================================
    # UTILIDADES DE DATOS
    # ========================================================================
    
    def get_team_name(self, team_id: int) -> str:
        if team_id in self._team_names_cache:
            return self._team_names_cache[team_id]
        try:
            query = text("SELECT name FROM teams WHERE id = :tid")
            with self.sad_engine.connect() as conn:
                result = conn.execute(query, {'tid': team_id}).fetchone()
            name = result[0] if result else f"Team_{team_id}"
        except:
            name = f"Team_{team_id}"
        self._team_names_cache[team_id] = name
        return name
    
    def get_league_name(self, league_id: int) -> str:
        if league_id in self._league_names_cache:
            return self._league_names_cache[league_id]
        try:
            query = text("SELECT name FROM leagues WHERE id = :lid")
            with self.sad_engine.connect() as conn:
                result = conn.execute(query, {'lid': league_id}).fetchone()
            name = result[0] if result else f"Liga_{league_id}"
        except:
            name = f"Liga_{league_id}"
        self._league_names_cache[league_id] = name
        return name
    
    def get_constants_before_date(self, team_id: int, before_date: str) -> Optional[Dict]:
        """Obtiene constantes de un equipo antes de una fecha."""
        cache_key = (team_id, before_date[:10])
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
                df = pd.read_sql_query(query, conn, params={
                    'team_id': team_id,
                    'before_date': before_date
                })
            if not df.empty:
                data = df.iloc[0].to_dict()
                self._constants_cache[cache_key] = data
                return data
        except Exception as e:
            logger.debug(f"Sin constantes para team {team_id}: {e}")
        return None
    
    def get_constants_at_fixture(self, team_id: int, fixture_id: int) -> Optional[Dict]:
        """Obtiene constantes de un equipo DESPUES de un fixture."""
        query = text("""
            SELECT *
            FROM constants
            WHERE team_id = :team_id AND fixture_id = :fixture_id
        """)
        try:
            with self.const_engine.connect() as conn:
                df = pd.read_sql_query(query, conn, params={
                    'team_id': team_id,
                    'fixture_id': fixture_id
                })
            if not df.empty:
                return df.iloc[0].to_dict()
        except:
            pass
        return None
    
    def get_team_level(self, team_id: int, before_date: str) -> float:
        """Obtiene nivel continuo de levels.db."""
        cache_key = (team_id, before_date[:10])
        if cache_key in self._levels_cache:
            return self._levels_cache[cache_key]
        
        if self.levels_engine is None:
            return 0.5
        
        query = text("""
            SELECT level FROM team_levels
            WHERE team_id = :team_id AND date <= :before_date
            ORDER BY date DESC
            LIMIT 1
        """)
        try:
            with self.levels_engine.connect() as conn:
                result = conn.execute(query, {
                    'team_id': team_id,
                    'before_date': before_date
                }).fetchone()
            level = float(result[0]) if result else 0.5
        except:
            level = 0.5
        
        self._levels_cache[cache_key] = level
        return level
    
    # ========================================================================
    # OBTENER PARTIDOS
    # ========================================================================
    
    def get_finished_fixtures(
        self,
        start_date: date,
        end_date: date,
        league_ids: List[int] = None,
    ) -> pd.DataFrame:
        """Obtiene todos los partidos terminados en el rango."""
        
        conditions = [
            "f.status_long = 'Match Finished'",
            "f.goals_home IS NOT NULL",
            "f.date >= :start_date",
            "f.date <= :end_date",
        ]
        params = {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': (end_date + timedelta(days=1)).strftime('%Y-%m-%d'),
        }
        
        if league_ids:
            placeholders = ','.join(str(lid) for lid in league_ids)
            conditions.append(f"f.league_id IN ({placeholders})")
        
        where_clause = " AND ".join(conditions)
        
        query = text(f"""
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
                COALESCE(ht.name, 'Team_' || f.home_team_id) as home_team_name,
                COALESCE(at.name, 'Team_' || f.away_team_id) as away_team_name
            FROM fixtures f
            LEFT JOIN teams ht ON f.home_team_id = ht.id
            LEFT JOIN teams at ON f.away_team_id = at.id
            WHERE {where_clause}
            ORDER BY f.date ASC, f.league_id ASC
        """)
        
        with self.sad_engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        logger.info(f"Partidos encontrados: {len(df)}")
        return df
    
    def get_available_leagues_in_range(self, start_date: date, end_date: date) -> List[Dict]:
        """Obtiene ligas con partidos en el rango."""
        query = text("""
            SELECT 
                f.league_id,
                l.name as league_name,
                COUNT(*) as fixture_count
            FROM fixtures f
            LEFT JOIN leagues l ON f.league_id = l.id
            WHERE f.status_long = 'Match Finished'
              AND f.date >= :start_date
              AND f.date <= :end_date
            GROUP BY f.league_id
            HAVING COUNT(*) >= 10
            ORDER BY fixture_count DESC
        """)
        
        with self.sad_engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params={
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': (end_date + timedelta(days=1)).strftime('%Y-%m-%d'),
            })
        
        return df.to_dict('records')
    
    # ========================================================================
    # PREDICCION CULEBRAS
    # ========================================================================
    
    def _predict_culebras(self, fixture: Dict) -> Dict:
        """Genera prediccion del modelo Culebras para un partido."""
        engine = self._get_culebras_engine()
        if engine is None:
            return self._empty_culebras()
        
        try:
            match_dt = pd.to_datetime(fixture['date'])
            
            pred = engine.predict_match(
                fixture_id=fixture['fixture_id'],
                home_team_id=fixture['home_team_id'],
                away_team_id=fixture['away_team_id'],
                match_date=match_dt,
                home_team_name=fixture.get('home_team_name', ''),
                away_team_name=fixture.get('away_team_name', ''),
                league_id=fixture['league_id'],
                goals_home=fixture['goals_home'],
                goals_away=fixture['goals_away'],
                round_str=fixture.get('league_round'),
            )
            
            # Para obtener el ml_break_score necesitamos contexto de dia
            # Simulamos posicion normalizada = 0.5 (medio) como baseline
            pred.position_normalized = 0.5
            pred.is_simultaneous = False
            pred.accumulated_tension = 0.0
            
            ml_score, ml_type = engine.predict_break_probability(pred)
            
            return {
                'cul_icf_home': round(pred.icf_home, 4),
                'cul_icf_away': round(pred.icf_away, 4),
                'cul_icf_diff': round(pred.icf_diff, 4),
                'cul_prob_home': round(pred.prob_home, 4),
                'cul_prob_draw': round(pred.prob_draw, 4),
                'cul_prob_away': round(pred.prob_away, 4),
                'cul_odds_home': round(pred.odds_home, 2),
                'cul_odds_draw': round(pred.odds_draw, 2),
                'cul_odds_away': round(pred.odds_away, 2),
                'cul_favorite': pred.favorite,
                'cul_favorite_prob': round(pred.favorite_prob, 4),
                'cul_prob_underdog': round(pred.prob_underdog, 4),
                'cul_prob_break_total': round(pred.prob_break_total, 4),
                'cul_prob_break_draw': round(pred.prob_break_by_draw, 4),
                'cul_prob_break_underdog': round(pred.prob_break_by_underdog, 4),
                'cul_ml_break_score': round(ml_score, 4),
                'cul_ml_break_type': ml_type,
                'cul_match_importance': round(pred.match_importance, 2),
                'cul_season_phase': pred.season_phase,
                'cul_rest_days_home': pred.rest_days_home,
                'cul_rest_days_away': pred.rest_days_away,
                'cul_rest_days_diff': round(pred.rest_days_diff, 4),
                # Resultado real
                'cul_favorite_won': pred.favorite_won,
                'cul_broke_snake': pred.broke_snake,
                'cul_break_type': pred.break_type,
            }
        except Exception as e:
            logger.debug(f"Error culebras fixture {fixture['fixture_id']}: {e}")
            return self._empty_culebras()
    
    def _empty_culebras(self) -> Dict:
        return {k: None for k in [
            'cul_icf_home', 'cul_icf_away', 'cul_icf_diff',
            'cul_prob_home', 'cul_prob_draw', 'cul_prob_away',
            'cul_odds_home', 'cul_odds_draw', 'cul_odds_away',
            'cul_favorite', 'cul_favorite_prob', 'cul_prob_underdog',
            'cul_prob_break_total', 'cul_prob_break_draw', 'cul_prob_break_underdog',
            'cul_ml_break_score', 'cul_ml_break_type',
            'cul_match_importance', 'cul_season_phase',
            'cul_rest_days_home', 'cul_rest_days_away', 'cul_rest_days_diff',
            'cul_favorite_won', 'cul_broke_snake', 'cul_break_type',
        ]}
    
    # ========================================================================
    # PREDICCION GOLES
    # ========================================================================
    
    def _predict_goals(self, fixture: Dict) -> Dict:
        """Genera prediccion del modelo de Goles Poisson."""
        predictor = self._get_goals_predictor()
        if predictor is None or not predictor.is_trained:
            return self._empty_goals()
        
        try:
            match_dt = pd.to_datetime(fixture['date'])
            
            pred = predictor.predict(
                home_id=fixture['home_team_id'],
                away_id=fixture['away_team_id'],
                match_date=match_dt
            )
            
            if pred is None:
                return self._empty_goals()
            
            probs = pred['probs']
            top_scores = pred.get('top_scores', [])
            
            # Resultado real para comparacion
            gh = fixture['goals_home']
            ga = fixture['goals_away']
            total = gh + ga
            
            result = {
                'gol_lambda_home': round(pred['lambda_home'], 4),
                'gol_lambda_away': round(pred['lambda_away'], 4),
                'gol_lambda_total': round(pred['lambda_total'], 4),
                'gol_home_level': round(pred['home_level'], 4),
                'gol_away_level': round(pred['away_level'], 4),
                'gol_home_level_bin': pred['home_level_bin'],
                'gol_away_level_bin': pred['away_level_bin'],
                'gol_level_bin_diff': pred['level_bin_diff'],
                # Probabilidades predichas
                'gol_p_home_over_05': round(probs['home_over_05'], 4),
                'gol_p_home_over_15': round(probs['home_over_15'], 4),
                'gol_p_home_over_25': round(probs['home_over_25'], 4),
                'gol_p_away_over_05': round(probs['away_over_05'], 4),
                'gol_p_away_over_15': round(probs['away_over_15'], 4),
                'gol_p_away_over_25': round(probs['away_over_25'], 4),
                'gol_p_total_over_25': round(probs['total_over_25'], 4),
                'gol_p_total_over_35': round(probs['total_over_35'], 4),
                'gol_p_btts': round(probs['btts'], 4),
                # Top score predicho
                'gol_top_score': f"{int(top_scores[0][0])}-{int(top_scores[0][1])}" if top_scores else None,
                'gol_top_score_prob': round(top_scores[0][2], 4) if top_scores else None,
                # Resultados reales (para comparar)
                'gol_actual_home_over_05': 1 if gh > 0 else 0,
                'gol_actual_home_over_15': 1 if gh > 1 else 0,
                'gol_actual_home_over_25': 1 if gh > 2 else 0,
                'gol_actual_away_over_05': 1 if ga > 0 else 0,
                'gol_actual_away_over_15': 1 if ga > 1 else 0,
                'gol_actual_away_over_25': 1 if ga > 2 else 0,
                'gol_actual_total_over_25': 1 if total > 2 else 0,
                'gol_actual_total_over_35': 1 if total > 3 else 0,
                'gol_actual_btts': 1 if (gh > 0 and ga > 0) else 0,
                'gol_actual_top_score_hit': 1 if (top_scores and int(top_scores[0][0]) == gh and int(top_scores[0][1]) == ga) else 0,
            }
            
            return result
        
        except Exception as e:
            logger.debug(f"Error goles fixture {fixture['fixture_id']}: {e}")
            return self._empty_goals()
    
    def _empty_goals(self) -> Dict:
        keys = [
            'gol_lambda_home', 'gol_lambda_away', 'gol_lambda_total',
            'gol_home_level', 'gol_away_level',
            'gol_home_level_bin', 'gol_away_level_bin', 'gol_level_bin_diff',
            'gol_p_home_over_05', 'gol_p_home_over_15', 'gol_p_home_over_25',
            'gol_p_away_over_05', 'gol_p_away_over_15', 'gol_p_away_over_25',
            'gol_p_total_over_25', 'gol_p_total_over_35', 'gol_p_btts',
            'gol_top_score', 'gol_top_score_prob',
            'gol_actual_home_over_05', 'gol_actual_home_over_15', 'gol_actual_home_over_25',
            'gol_actual_away_over_05', 'gol_actual_away_over_15', 'gol_actual_away_over_25',
            'gol_actual_total_over_25', 'gol_actual_total_over_35',
            'gol_actual_btts', 'gol_actual_top_score_hit',
        ]
        return {k: None for k in keys}
    
    # ========================================================================
    # PREDICCION CONSTANTES
    # ========================================================================
    
    def _predict_constants_for_team(
        self,
        team_id: int,
        rival_id: int,
        fixture_id: int,
        match_date: str,
        is_home: bool,
        league_id: int,
    ) -> List[Dict]:
        """
        Genera predicciones de constantes para UN equipo en un partido.
        
        Retorna una lista de dicts (uno por constante aplicable).
        """
        predictor = self._get_constants_predictor()
        results = []
        
        # Seleccionar constantes aplicables segun condicion
        k_constants = self.K_CONSTANTS_HOME if is_home else self.K_CONSTANTS_AWAY
        
        # Obtener constantes antes del partido
        constants_before = self.get_constants_before_date(team_id, match_date)
        if not constants_before:
            return results
        
        # Obtener constantes despues del partido (resultado real)
        constants_after = self.get_constants_at_fixture(team_id, fixture_id)
        
        # Obtener constantes del rival
        rival_constants = self.get_constants_before_date(rival_id, match_date)
        
        # Nivel del equipo y rival
        nivel_equipo = self.get_team_level(team_id, match_date)
        nivel_rival = self.get_team_level(rival_id, match_date)
        
        for const_type in k_constants:
            try:
                # Obtener K previa
                k_col = self.K_COL_MAP.get(const_type, const_type)
                k_prev = float(constants_before.get(k_col, 0) or 0)
                
                # K rival aproximada
                k_rival_approx = 0.0
                if rival_constants:
                    # Usar la constante "espejo" del rival
                    rival_k_col = k_col
                    if 'local' in k_col:
                        rival_k_col = k_col.replace('local', 'visita')
                    elif 'visita' in k_col:
                        rival_k_col = k_col.replace('visita', 'local')
                    k_rival_approx = float(rival_constants.get(rival_k_col, 0) or 0)
                
                # Prediccion ML
                pred_incr = None
                pred_reset = None
                pred_decr = None
                pred_winner = None
                
                if predictor is not None:
                    pred_result = predictor.predict(
                        constant_type=const_type,
                        nivel_equipo=nivel_equipo,
                        nivel_rival=nivel_rival,
                        k_prev=k_prev,
                        nivel_rival_prev=nivel_rival,
                        k_rival_approx=k_rival_approx,
                        league_id=league_id,
                        is_home=1 if is_home else 0,
                    )
                    
                    if pred_result is not None:
                        pred_incr = round(pred_result.get('incremento', 0), 2)
                        pred_reset = round(pred_result.get('reset', 0), 2)
                        pred_decr = round(pred_result.get('decremento', 0), 2)
                        
                        # Determinar prediccion ganadora
                        max_pred = max(pred_result.items(), key=lambda x: x[1])
                        pred_winner = max_pred[0]
                
                # Resultado real
                actual_change = None
                k_after = None
                if constants_after:
                    k_after_val = float(constants_after.get(k_col, 0) or 0)
                    k_after = k_after_val
                    
                    is_binary = const_type in self.BINARY_CONSTANTS
                    
                    if abs(k_after_val) < self.RESET_THRESHOLD:
                        actual_change = 'reset'
                    elif k_after_val > k_prev:
                        actual_change = 'incremento'
                    elif k_after_val < k_prev:
                        if is_binary:
                            actual_change = 'reset'  # Binarios no decrementan
                        else:
                            actual_change = 'decremento'
                    else:
                        actual_change = 'incremento'  # Sin cambio = racha continua
                
                # Verificar si prediccion es correcta
                pred_correct = None
                if pred_winner and actual_change:
                    pred_correct = 1 if pred_winner == actual_change else 0
                
                results.append({
                    'fixture_id': fixture_id,
                    'team_id': team_id,
                    'team_name': self.get_team_name(team_id),
                    'is_home': 1 if is_home else 0,
                    'constant_type': const_type,
                    'is_binary': 1 if const_type in self.BINARY_CONSTANTS else 0,
                    'nivel_equipo': round(nivel_equipo, 4),
                    'nivel_rival': round(nivel_rival, 4),
                    'k_prev': round(k_prev, 2),
                    'k_rival_approx': round(k_rival_approx, 2),
                    'pred_incremento': pred_incr,
                    'pred_reset': pred_reset,
                    'pred_decremento': pred_decr,
                    'pred_winner': pred_winner,
                    'k_after': round(k_after, 2) if k_after is not None else None,
                    'k_change': round(k_after - k_prev, 2) if k_after is not None else None,
                    'actual_change': actual_change,
                    'pred_correct': pred_correct,
                })
                
            except Exception as e:
                logger.debug(f"Error constante {const_type} team {team_id}: {e}")
                continue
        
        return results
    
    # ========================================================================
    # EJECUTAR EXPORTACION
    # ========================================================================
    
    def run(
        self,
        start_date: date = None,
        end_date: date = None,
        league_ids: List[int] = None,
        enable_culebras: bool = True,
        enable_goals: bool = True,
        enable_constants: bool = True,
        progress_callback=None,
        max_fixtures: int = None,
    ) -> Dict:
        """
        Ejecuta la exportacion completa.
        
        Args:
            start_date: Fecha inicio (default: 2024-01-01)
            end_date: Fecha fin (default: 2024-12-31)
            league_ids: Lista de IDs de ligas (None = todas)
            enable_culebras: Activar modelo Culebras
            enable_goals: Activar modelo Goles
            enable_constants: Activar modelo Constantes
            progress_callback: func(percent, message) para reportar progreso
            max_fixtures: Limitar numero de partidos (para pruebas)
            
        Returns:
            Dict con estadisticas de la exportacion
        """
        if start_date is None:
            start_date = date(2024, 1, 1)
        if end_date is None:
            end_date = date(2024, 12, 31)
        
        logger.info("=" * 70)
        logger.info("EXPORTADOR DE PREDICCIONES HISTORICAS - SAD v6")
        logger.info("=" * 70)
        logger.info(f"Periodo: {start_date} a {end_date}")
        logger.info(f"Modelos: Culebras={enable_culebras}, Goles={enable_goals}, Constantes={enable_constants}")
        
        if progress_callback:
            progress_callback(0, "Obteniendo partidos...")
        
        # 1. Obtener partidos
        fixtures_df = self.get_finished_fixtures(start_date, end_date, league_ids)
        
        if fixtures_df.empty:
            logger.warning("No se encontraron partidos en el rango")
            return {'error': 'No fixtures found', 'total': 0}
        
        if max_fixtures:
            fixtures_df = fixtures_df.head(max_fixtures)
            logger.info(f"Limitado a {max_fixtures} partidos (modo prueba)")
        
        total = len(fixtures_df)
        logger.info(f"Total partidos a procesar: {total}")
        
        # Pre-computar descansos si Culebras esta activo
        if enable_culebras:
            culebras = self._get_culebras_engine()
            if culebras:
                if progress_callback:
                    progress_callback(2, "Pre-calculando dias de descanso...")
                league_ids_in_data = fixtures_df['league_id'].unique()
                for lid in league_ids_in_data:
                    culebras.precompute_rest_days_batch(lid)
        
        # 2. Procesar cada partido
        main_rows = []
        constants_rows = []
        
        errors = {'culebras': 0, 'goals': 0, 'constants': 0}
        successes = {'culebras': 0, 'goals': 0, 'constants': 0}
        
        for idx, fixture in fixtures_df.iterrows():
            fx = fixture.to_dict()
            
            if progress_callback and idx % 50 == 0:
                pct = int((idx / total) * 90) + 5
                progress_callback(pct, f"Procesando {idx+1}/{total}...")
            
            if idx % 500 == 0 and idx > 0:
                logger.info(f"  Progreso: {idx}/{total} ({idx/total*100:.1f}%)")
            
            # --- Info basica del partido ---
            gh = int(fx['goals_home']) if pd.notna(fx['goals_home']) else 0
            ga = int(fx['goals_away']) if pd.notna(fx['goals_away']) else 0
            total_goals = gh + ga
            
            if gh > ga:
                outcome = '1'
            elif gh < ga:
                outcome = '2'
            else:
                outcome = 'X'
            
            row = {
                'fixture_id': fx['fixture_id'],
                'date': str(fx['date'])[:19],
                'league_id': fx['league_id'],
                'league_name': self.get_league_name(fx['league_id']),
                'league_round': fx.get('league_round', ''),
                'home_team_id': fx['home_team_id'],
                'home_team_name': fx.get('home_team_name', ''),
                'away_team_id': fx['away_team_id'],
                'away_team_name': fx.get('away_team_name', ''),
                'goals_home': gh,
                'goals_away': ga,
                'total_goals': total_goals,
                'outcome': outcome,
            }
            
            # --- Culebras ---
            if enable_culebras:
                try:
                    cul_pred = self._predict_culebras(fx)
                    row.update(cul_pred)
                    if cul_pred.get('cul_ml_break_score') is not None:
                        successes['culebras'] += 1
                    else:
                        errors['culebras'] += 1
                except Exception as e:
                    row.update(self._empty_culebras())
                    errors['culebras'] += 1
            
            # --- Goles ---
            if enable_goals:
                try:
                    gol_pred = self._predict_goals(fx)
                    row.update(gol_pred)
                    if gol_pred.get('gol_lambda_home') is not None:
                        successes['goals'] += 1
                    else:
                        errors['goals'] += 1
                except Exception as e:
                    row.update(self._empty_goals())
                    errors['goals'] += 1
            
            main_rows.append(row)
            
            # --- Constantes (tabla separada) ---
            if enable_constants:
                match_date_str = str(fx['date'])[:19]
                try:
                    # Equipo local
                    home_consts = self._predict_constants_for_team(
                        team_id=fx['home_team_id'],
                        rival_id=fx['away_team_id'],
                        fixture_id=fx['fixture_id'],
                        match_date=match_date_str,
                        is_home=True,
                        league_id=fx['league_id'],
                    )
                    constants_rows.extend(home_consts)
                    
                    # Equipo visitante
                    away_consts = self._predict_constants_for_team(
                        team_id=fx['away_team_id'],
                        rival_id=fx['home_team_id'],
                        fixture_id=fx['fixture_id'],
                        match_date=match_date_str,
                        is_home=False,
                        league_id=fx['league_id'],
                    )
                    constants_rows.extend(away_consts)
                    
                    if home_consts or away_consts:
                        successes['constants'] += 1
                    else:
                        errors['constants'] += 1
                except Exception as e:
                    errors['constants'] += 1
        
        if progress_callback:
            progress_callback(92, "Guardando resultados...")
        
        # 3. Crear DataFrames
        main_df = pd.DataFrame(main_rows)
        constants_df = pd.DataFrame(constants_rows) if constants_rows else pd.DataFrame()
        
        # 4. Guardar
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # CSV principal
        csv_main_path = os.path.join(self.output_dir, f'predictions_main_{timestamp}.csv')
        main_df.to_csv(csv_main_path, index=False)
        logger.info(f"[OK] CSV principal: {csv_main_path} ({len(main_df)} filas)")
        
        # CSV constantes
        csv_const_path = None
        if not constants_df.empty:
            csv_const_path = os.path.join(self.output_dir, f'predictions_constants_{timestamp}.csv')
            constants_df.to_csv(csv_const_path, index=False)
            logger.info(f"[OK] CSV constantes: {csv_const_path} ({len(constants_df)} filas)")
        
        # SQLite
        db_path = os.path.join(self.output_dir, f'historical_predictions_{timestamp}.db')
        export_engine = create_engine(f'sqlite:///{db_path}', echo=False)
        main_df.to_sql('predictions_main', export_engine, if_exists='replace', index=False)
        if not constants_df.empty:
            constants_df.to_sql('predictions_constants', export_engine, if_exists='replace', index=False)
        logger.info(f"[OK] SQLite: {db_path}")
        
        # Tambien guardar un "latest" symlink/copy
        latest_main = os.path.join(self.output_dir, 'predictions_main_latest.csv')
        latest_const = os.path.join(self.output_dir, 'predictions_constants_latest.csv')
        latest_db = os.path.join(self.output_dir, 'historical_predictions_latest.db')
        
        main_df.to_csv(latest_main, index=False)
        if not constants_df.empty:
            constants_df.to_csv(latest_const, index=False)
        main_df.to_sql('predictions_main', create_engine(f'sqlite:///{latest_db}'), if_exists='replace', index=False)
        if not constants_df.empty:
            constants_df.to_sql('predictions_constants', create_engine(f'sqlite:///{latest_db}'), if_exists='replace', index=False)
        
        if progress_callback:
            progress_callback(98, "Generando resumen...")
        
        # 5. Resumen de resultados
        stats = self._compute_summary(main_df, constants_df)
        stats.update({
            'total_fixtures': len(main_df),
            'total_constants_rows': len(constants_df),
            'successes': successes,
            'errors': errors,
            'csv_main': csv_main_path,
            'csv_constants': csv_const_path,
            'sqlite_db': db_path,
            'period': f"{start_date} - {end_date}",
            'timestamp': timestamp,
        })
        
        # Guardar resumen como JSON
        import json
        summary_path = os.path.join(self.output_dir, f'summary_{timestamp}.json')
        with open(summary_path, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        
        if progress_callback:
            progress_callback(100, "Exportacion completada!")
        
        logger.info("=" * 70)
        logger.info("RESUMEN DE EXPORTACION")
        logger.info("=" * 70)
        logger.info(f"  Partidos procesados: {stats['total_fixtures']}")
        logger.info(f"  Culebras OK: {successes['culebras']}, Err: {errors['culebras']}")
        logger.info(f"  Goles OK: {successes['goals']}, Err: {errors['goals']}")
        logger.info(f"  Constantes OK: {successes['constants']}, Err: {errors['constants']}")
        
        if 'culebras_accuracy' in stats:
            logger.info(f"  [Culebras] Accuracy favorito: {stats.get('culebras_favorite_accuracy', 'N/A')}")
        if 'goals_over25_accuracy' in stats:
            logger.info(f"  [Goles] Over 2.5 accuracy: {stats.get('goals_over25_accuracy', 'N/A')}")
        if 'constants_accuracy' in stats:
            logger.info(f"  [Constantes] Accuracy global: {stats.get('constants_accuracy', 'N/A')}")
        
        logger.info(f"\n  Archivos en: {self.output_dir}")
        
        return stats
    
    # ========================================================================
    # RESUMEN ESTADISTICO
    # ========================================================================
    
    def _compute_summary(self, main_df: pd.DataFrame, constants_df: pd.DataFrame) -> Dict:
        """Computa estadisticas de rendimiento de las predicciones."""
        stats = {}
        
        # --- Culebras ---
        if 'cul_favorite' in main_df.columns:
            fav_df = main_df[main_df['cul_favorite_won'].notna()].copy()
            if not fav_df.empty:
                fav_df['cul_favorite_won'] = fav_df['cul_favorite_won'].astype(bool)
                stats['culebras_favorite_accuracy'] = round(fav_df['cul_favorite_won'].mean(), 4)
                stats['culebras_total_with_favorite'] = len(fav_df)
                
                # ml_break_score stats
                ml_df = main_df[main_df['cul_ml_break_score'].notna()]
                if not ml_df.empty:
                    stats['culebras_ml_score_mean'] = round(ml_df['cul_ml_break_score'].mean(), 4)
                    stats['culebras_ml_score_std'] = round(ml_df['cul_ml_break_score'].std(), 4)
                    stats['culebras_ml_score_min'] = round(ml_df['cul_ml_break_score'].min(), 4)
                    stats['culebras_ml_score_max'] = round(ml_df['cul_ml_break_score'].max(), 4)
                    stats['culebras_ml_score_p25'] = round(ml_df['cul_ml_break_score'].quantile(0.25), 4)
                    stats['culebras_ml_score_p50'] = round(ml_df['cul_ml_break_score'].quantile(0.50), 4)
                    stats['culebras_ml_score_p75'] = round(ml_df['cul_ml_break_score'].quantile(0.75), 4)
        
        # --- Goles ---
        if 'gol_p_total_over_25' in main_df.columns:
            gol_df = main_df[main_df['gol_p_total_over_25'].notna()].copy()
            if not gol_df.empty:
                # Over 2.5 accuracy (umbral 0.5)
                gol_df['pred_over25'] = (gol_df['gol_p_total_over_25'] > 0.5).astype(int)
                stats['goals_over25_accuracy'] = round(
                    (gol_df['pred_over25'] == gol_df['gol_actual_total_over_25']).mean(), 4
                )
                
                # Over 3.5 accuracy
                gol_df['pred_over35'] = (gol_df['gol_p_total_over_35'] > 0.5).astype(int)
                stats['goals_over35_accuracy'] = round(
                    (gol_df['pred_over35'] == gol_df['gol_actual_total_over_35']).mean(), 4
                )
                
                # BTTS accuracy
                gol_df['pred_btts'] = (gol_df['gol_p_btts'] > 0.5).astype(int)
                stats['goals_btts_accuracy'] = round(
                    (gol_df['pred_btts'] == gol_df['gol_actual_btts']).mean(), 4
                )
                
                # Lambda stats
                stats['goals_lambda_home_mean'] = round(gol_df['gol_lambda_home'].mean(), 4)
                stats['goals_lambda_away_mean'] = round(gol_df['gol_lambda_away'].mean(), 4)
                stats['goals_total_predicted'] = len(gol_df)
                
                # Top score hit rate
                if 'gol_actual_top_score_hit' in gol_df.columns:
                    stats['goals_top_score_hit_rate'] = round(
                        gol_df['gol_actual_top_score_hit'].mean(), 4
                    )
        
        # --- Constantes ---
        if not constants_df.empty and 'pred_correct' in constants_df.columns:
            valid_const = constants_df[constants_df['pred_correct'].notna()]
            if not valid_const.empty:
                stats['constants_accuracy'] = round(valid_const['pred_correct'].mean(), 4)
                stats['constants_total_predictions'] = len(valid_const)
                
                # Accuracy por tipo
                for const_type in valid_const['constant_type'].unique():
                    type_df = valid_const[valid_const['constant_type'] == const_type]
                    acc = round(type_df['pred_correct'].mean(), 4)
                    stats[f'constants_accuracy_{const_type}'] = acc
        
        return stats


# ============================================================================
# SCRIPT PRINCIPAL
# ============================================================================

def main():
    """Ejecuta la exportacion desde linea de comandos."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Exportador de predicciones historicas SAD v6')
    parser.add_argument('--start', type=str, default='2024-01-01', help='Fecha inicio (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2024-12-31', help='Fecha fin (YYYY-MM-DD)')
    parser.add_argument('--leagues', type=str, default=None, help='IDs de ligas separados por coma')
    parser.add_argument('--max', type=int, default=None, help='Max fixtures (para pruebas)')
    parser.add_argument('--no-culebras', action='store_true', help='Desactivar modelo Culebras')
    parser.add_argument('--no-goals', action='store_true', help='Desactivar modelo Goles')
    parser.add_argument('--no-constants', action='store_true', help='Desactivar modelo Constantes')
    parser.add_argument('--project-root', type=str, default=None, help='Ruta raiz del proyecto')
    
    args = parser.parse_args()
    
    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)
    
    league_ids = None
    if args.leagues:
        league_ids = [int(x.strip()) for x in args.leagues.split(',')]
    
    def progress(pct, msg):
        print(f"  [{pct:3d}%] {msg}")
    
    exporter = HistoricalPredictionsExporter(project_root=args.project_root)
    
    stats = exporter.run(
        start_date=start_date,
        end_date=end_date,
        league_ids=league_ids,
        enable_culebras=not args.no_culebras,
        enable_goals=not args.no_goals,
        enable_constants=not args.no_constants,
        progress_callback=progress,
        max_fixtures=args.max,
    )
    
    print("\n" + "=" * 70)
    print("EXPORTACION COMPLETADA")
    print("=" * 70)
    
    import json
    print(json.dumps(stats, indent=2, default=str))


if __name__ == "__main__":
    main()