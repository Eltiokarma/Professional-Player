#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pre_match_analysis_window.py

ANÁLISIS PRE-PARTIDO - Dashboard Consolidado
=============================================

Ventana que consolida:
1. Simulación de Constantes (K) - con probabilidades detalladas ↑/↔/↓
2. Ley Anticulebra (ICF, probabilidades 1X2, Score ML v6)
3. Ley de la Regresión al Nivel (gap, P(Win), tendencia)
4. Ley del Marcador (xG, marcadores probables)
5. Ley de la Fe Perdida (péndulo del hincha, flags)
6. Historial H2H — Cards + Barra de dominio
7. Forma Reciente — Círculos Flashscore + Tooltips

Autor: Gerson (desarrollado con Claude)
Fecha: Enero 2026
Actualizado: Febrero 2026 - Score ML v6 + Probabilidades detalladas constantes
             Febrero 2026 - Método load_fixture() para carga directa desde Visor
             Febrero 2026 - Integración Ley de la Regresión al Nivel
             Febrero 2026 - Visual upgrade: H2H cards + Forma Flashscore circles
             Febrero 2026 - Fix: auto-refresh ticket odds after OddsWorker finishes
             Febrero 2026 - Integración Ley de la Fe Perdida (péndulo del hincha)
             Febrero 2026 - Botón Exportar Burbujas (gráficos + CSV en background)
"""

import os
import re
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, text

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QGroupBox, QGridLayout, QFrame, QHeaderView, QMessageBox,
    QProgressBar, QApplication, QCompleter, QScrollArea,
    QSizePolicy, QRadioButton, QButtonGroup, QLineEdit, QSpinBox,
    QDoubleSpinBox, QInputDialog, QCheckBox, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QBrush, QPixmap, QPainter

logger = logging.getLogger(__name__)

# Intentar importar la ventana de constantes/burbujas
BUBBLES_AVAILABLE = False
try:
    from ui.ultra_fast_constants_window import UltraFastConstantsWindow
    BUBBLES_AVAILABLE = True
except ImportError:
    try:
        from ultra_fast_constants_window import UltraFastConstantsWindow
        BUBBLES_AVAILABLE = True
    except ImportError:
        logger.warning("UltraFastConstantsWindow no disponible")

# Intentar importar el SAD Dashboard (Fase 1 Extracción)
SAD_DASHBOARD_AVAILABLE = False
try:
    from ui.sad_dashboard_window import SADDashboardWindow
    SAD_DASHBOARD_AVAILABLE = True
except ImportError:
    try:
        from sad_dashboard_window import SADDashboardWindow
        SAD_DASHBOARD_AVAILABLE = True
    except ImportError:
        logger.warning("SADDashboardWindow no disponible — requiere PySide6-WebEngineWidgets")

# Intentar importar la ventana de Marcador por K (Dixon-Coles)
K_SCORELINE_AVAILABLE = False
try:
    from ui.k_scoreline_window import KScorelineWindow
    K_SCORELINE_AVAILABLE = True
except ImportError:
    try:
        from k_scoreline_window import KScorelineWindow
        K_SCORELINE_AVAILABLE = True
    except ImportError:
        logger.warning("KScorelineWindow no disponible")


# =============================================================================
# UTILIDADES
# =============================================================================

def find_project_root() -> str:
    """Encuentra la raíz del proyecto."""
    this_file = os.path.abspath(__file__)
    this_dir = os.path.dirname(this_file)
    
    if this_dir.replace('\\', '/').endswith('/ui') or this_dir.endswith('\\ui'):
        project_root = os.path.dirname(os.path.dirname(this_dir))
        if os.path.exists(os.path.join(project_root, 'sad.db')):
            return project_root
    
    current = this_dir
    for _ in range(5):
        sad_path = os.path.join(current, 'sad.db')
        if os.path.exists(sad_path):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    
    return os.path.dirname(os.path.dirname(this_dir))


def get_prediction_label(probs: Dict[str, float]) -> str:
    """Determina la etiqueta de predicción basada en probabilidades."""
    incr = probs.get('incremento', 0)
    reset = probs.get('reset', 0)
    decr = probs.get('decremento', 0)
    
    max_prob = max(incr, reset, decr)
    
    if max_prob == incr:
        return 'incr'
    elif max_prob == decr:
        return 'decr'
    else:
        return 'rese'


def get_prediction_color(label: str) -> QColor:
    """Retorna el color según la predicción."""
    colors = {
        'incr': QColor(40, 167, 69),    # Verde
        'decr': QColor(220, 53, 69),    # Rojo
        'rese': QColor(255, 193, 7),    # Amarillo
    }
    return colors.get(label, QColor(128, 128, 128))


# =============================================================================
# WORKERS
# =============================================================================

class ConstantsWorker(QThread):
    """Worker para predicción de constantes K con probabilidades detalladas."""
    finished = Signal(dict)
    progress = Signal(str)
    error = Signal(str)
    
    def __init__(self, team_id: int, rival_id: int, is_home: bool, 
                 league_id: int, fixture_date, model_mode: str = 'auto'):
        super().__init__()
        self.team_id = team_id
        self.rival_id = rival_id
        self.is_home = is_home
        self.league_id = league_id
        self.fixture_date = fixture_date
        self.model_mode = model_mode
    
    def run(self):
        try:
            from utils.ml_data_collector import MLDataCollector
            from utils.global_constant_predictor import GlobalConstantPredictor
            
            predictor = GlobalConstantPredictor()
            
            if self.model_mode == 'global':
                predictor.load_models(load_global=True)
            elif self.model_mode == 'league':
                predictor.load_models(league_id=self.league_id, load_global=True)
            else:
                predictor.load_models(league_id=self.league_id, load_global=True)
            
            with MLDataCollector() as collector:
                # ═══════════════════════════════════════════════════════════
                # PREDICCIONES PARA EL EQUIPO SELECCIONADO
                # ═══════════════════════════════════════════════════════════
                is_home_val = 1 if self.is_home else 0
                team_constants = predictor.get_applicable_constants(is_home_val)
                
                team_predictions = {}
                team_models = {}
                
                for const_type in team_constants:
                    try:
                        inputs = collector.get_prediction_inputs(
                            team_id=self.team_id,
                            rival_id=self.rival_id,
                            fixture_date=self.fixture_date,
                            fixture_id=0,
                            is_home=self.is_home,
                            constant_type=const_type,
                            league_id=self.league_id,
                        )
                        
                        if inputs:
                            use_league = self.league_id if self.model_mode != 'global' else None
                            pred = predictor.predict(
                                constant_type=const_type,
                                nivel_equipo=inputs['nivel_equipo'],
                                nivel_rival=inputs['nivel_rival'],
                                k_prev=inputs['k_prev'],
                                nivel_rival_prev=inputs['nivel_rival_prev'],
                                k_rival_approx=inputs['k_rival_approx'],
                                league_id=use_league,
                                is_home=inputs['is_home'],
                            )
                            
                            if pred is not None and isinstance(pred, dict):
                                team_predictions[const_type] = {
                                    'incremento': pred.get('incremento', 0),
                                    'reset': pred.get('reset', 0),
                                    'decremento': pred.get('decremento', 0),
                                }
                                team_models[const_type] = predictor.get_model_for_prediction(
                                    const_type, use_league
                                )
                    except Exception as e:
                        logger.warning(f"Error prediciendo {const_type}: {e}")
                
                # ═══════════════════════════════════════════════════════════
                # PREDICCIONES PARA EL RIVAL
                # ═══════════════════════════════════════════════════════════
                is_home_rival = 0 if self.is_home else 1
                rival_constants = predictor.get_applicable_constants(is_home_rival)
                
                rival_predictions = {}
                rival_models = {}
                
                for const_type in rival_constants:
                    try:
                        inputs = collector.get_prediction_inputs(
                            team_id=self.rival_id,
                            rival_id=self.team_id,
                            fixture_date=self.fixture_date,
                            fixture_id=0,
                            is_home=not self.is_home,
                            constant_type=const_type,
                            league_id=self.league_id,
                        )
                        
                        if inputs:
                            use_league = self.league_id if self.model_mode != 'global' else None
                            pred = predictor.predict(
                                constant_type=const_type,
                                nivel_equipo=inputs['nivel_equipo'],
                                nivel_rival=inputs['nivel_rival'],
                                k_prev=inputs['k_prev'],
                                nivel_rival_prev=inputs['nivel_rival_prev'],
                                k_rival_approx=inputs['k_rival_approx'],
                                league_id=use_league,
                                is_home=inputs['is_home'],
                            )
                            
                            if pred is not None and isinstance(pred, dict):
                                rival_predictions[const_type] = {
                                    'incremento': pred.get('incremento', 0),
                                    'reset': pred.get('reset', 0),
                                    'decremento': pred.get('decremento', 0),
                                }
                                rival_models[const_type] = predictor.get_model_for_prediction(
                                    const_type, use_league
                                )
                    except Exception as e:
                        logger.warning(f"Error prediciendo {const_type}: {e}")
            
            self.finished.emit({
                'team_predictions': team_predictions,
                'team_models': team_models,
                'rival_predictions': rival_predictions,
                'rival_models': rival_models,
            })
            
        except Exception as e:
            logger.error(f"Error en ConstantsWorker: {e}")
            self.error.emit(str(e))


class AnticulebrasWorker(QThread):
    """Worker para análisis Anticulebra con Score ML v6."""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, home_team_id: int, away_team_id: int, 
                 match_date: datetime, league_id: int, fixture_id: int,
                 home_team_name: str = "", away_team_name: str = ""):
        super().__init__()
        self.home_team_id = home_team_id
        self.away_team_id = away_team_id
        self.match_date = match_date
        self.league_id = league_id
        self.fixture_id = fixture_id
        self.home_team_name = home_team_name
        self.away_team_name = away_team_name
    
    def run(self):
        try:
            engine = None
            try:
                from ui.anticulebra.anticulebra_engine import AnticulebraEngine
                engine = AnticulebraEngine()
            except ImportError:
                try:
                    from ui.anticulebra.anticulebra_engine import AnticulebraEngine
                    engine = AnticulebraEngine()
                except ImportError:
                    project_root = find_project_root()
                    if project_root not in sys.path:
                        sys.path.insert(0, project_root)
                    src_dir = os.path.join(project_root, 'src')
                    if src_dir not in sys.path:
                        sys.path.insert(0, src_dir)
                    from ui.anticulebra.anticulebra_engine import AnticulebraEngine
                    engine = AnticulebraEngine()
            
            prediction = engine.predict_match(
                fixture_id=self.fixture_id,
                home_team_id=self.home_team_id,
                away_team_id=self.away_team_id,
                match_date=self.match_date,
                league_id=self.league_id,
                home_team_name=self.home_team_name,
                away_team_name=self.away_team_name,
            )
            
            ml_score = 0.0
            ml_type = "unknown"
            
            prediction.position_in_day = 1
            prediction.position_normalized = 0.5
            prediction.is_simultaneous = False
            prediction.accumulated_tension = 0.0
            
            prediction.n_matches_day = 1
            prediction.joint_prob_all_favs = prediction.favorite_prob if prediction.favorite != "none" else 0.5
            prediction.min_favorite_prob_day = prediction.favorite_prob if prediction.favorite != "none" else 0.5
            prediction.mean_favorite_prob_day = prediction.favorite_prob if prediction.favorite != "none" else 0.5
            prediction.weakest_link_rank = 0.5
            prediction.n_tight_matches_day = 1 if prediction.favorite_prob < 0.55 else 0
            
            try:
                ml_score, ml_type = engine.predict_break_probability(prediction)
            except Exception as e:
                logger.warning(f"Error calculando ML score: {e}")
                ml_score = prediction.prob_break_total
                ml_type = "draw" if prediction.prob_draw > 0.25 else "underdog"
            
            self.finished.emit({
                'icf_home': prediction.icf_home,
                'icf_away': prediction.icf_away,
                'icf_diff': prediction.icf_diff,
                'prob_home': prediction.prob_home,
                'prob_draw': prediction.prob_draw,
                'prob_away': prediction.prob_away,
                'favorite': prediction.favorite,
                'favorite_prob': prediction.favorite_prob,
                'prob_break_total': prediction.prob_break_total,
                'ml_score': ml_score,
                'ml_type': ml_type,
            })
            
        except Exception as e:
            logger.error(f"Error en AnticulebrasWorker: {e}")
            self.error.emit(str(e))


class MarcadorWorker(QThread):
    """Worker para predicción de goles."""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, home_team_id: int, away_team_id: int, 
                 match_date: datetime, project_root: str):
        super().__init__()
        self.home_team_id = home_team_id
        self.away_team_id = away_team_id
        self.match_date = match_date
        self.project_root = project_root
    
    def run(self):
        try:
            src_dir = os.path.join(self.project_root, 'src')
            if os.path.exists(src_dir) and src_dir not in sys.path:
                sys.path.insert(0, src_dir)
            if self.project_root not in sys.path:
                sys.path.insert(0, self.project_root)
            
            from ml_goals_predictor_v6 import MLGoalsPredictorV6
            
            predictor = MLGoalsPredictorV6(self.project_root)
            
            if not predictor.load_model():
                self.error.emit("Modelo de goles no encontrado")
                return
            
            pred = predictor.predict(self.home_team_id, self.away_team_id, self.match_date)
            
            if pred is None:
                self.error.emit("Error en predicción de goles")
                return
            
            top_scores_raw = pred.get('top_scores', [])
            top_scores = [(f"{h}-{a}", prob) for h, a, prob in top_scores_raw]
            
            self.finished.emit({
                'lambda_home': pred['lambda_home'],
                'lambda_away': pred['lambda_away'],
                'lambda_total': pred['lambda_total'],
                'probs': pred['probs'],
                'top_scores': top_scores,
            })
            
        except Exception as e:
            logger.error(f"Error en MarcadorWorker: {e}")
            self.error.emit(str(e))


class H2HWorker(QThread):
    """Worker para historial H2H."""
    finished = Signal(list)
    error = Signal(str)
    
    def __init__(self, team1_id: int, team2_id: int, sad_engine):
        super().__init__()
        self.team1_id = team1_id
        self.team2_id = team2_id
        self.sad_engine = sad_engine
    
    def run(self):
        try:
            query = text("""
                SELECT f.date, ht.name as home_name, at.name as away_name,
                       f.goals_home, f.goals_away, l.name as league_name
                FROM fixtures f
                JOIN teams ht ON f.home_team_id = ht.id
                JOIN teams at ON f.away_team_id = at.id
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE ((f.home_team_id = :t1 AND f.away_team_id = :t2) 
                    OR (f.home_team_id = :t2 AND f.away_team_id = :t1))
                  AND f.status_short = 'FT' AND f.goals_home IS NOT NULL
                ORDER BY f.date DESC LIMIT 5
            """)
            
            with self.sad_engine.connect() as conn:
                results = conn.execute(query, {'t1': self.team1_id, 't2': self.team2_id}).fetchall()
            
            h2h_list = [{'date': r.date, 'home_name': r.home_name, 'away_name': r.away_name,
                        'goals_home': r.goals_home, 'goals_away': r.goals_away,
                        'league_name': (r.league_name or '').strip() if r.league_name else ''} for r in results]
            
            self.finished.emit(h2h_list)
        except Exception as e:
            self.error.emit(str(e))


class OddsWorker(QThread):
    """Worker para odds - múltiples mercados."""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, fixture_id: int, sad_engine):
        super().__init__()
        self.fixture_id = fixture_id
        self.sad_engine = sad_engine
    
    def run(self):
        try:
            check_table = text("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='odds'
            """)
            
            with self.sad_engine.connect() as conn:
                table_exists = conn.execute(check_table).fetchone()
                
                if not table_exists:
                    logger.warning("Tabla 'odds' no existe en la base de datos")
                    self.finished.emit({
                        'match_winner': [],
                        'goals_ou': [],
                        'handicap': [],
                        'btts': [],
                        'double_chance': [],
                        'error_msg': 'Tabla odds no existe. Extraer cuotas primero.'
                    })
                    return
                
                count_query = text("SELECT COUNT(*) FROM odds WHERE fixture_id = :fixture_id")
                count = conn.execute(count_query, {'fixture_id': self.fixture_id}).fetchone()[0]
                
                if count == 0:
                    logger.info(f"No hay odds para fixture {self.fixture_id}")
                    self.finished.emit({
                        'match_winner': [],
                        'goals_ou': [],
                        'handicap': [],
                        'btts': [],
                        'double_chance': [],
                        'error_msg': f'Sin cuotas (extraer desde Extracción de Datos)'
                    })
                    return
                
                # Incluir bet_id para filtrar mercados exactos
                query = text("""
                    SELECT bookmaker_name, bet_name, value, odd,
                           COALESCE(bet_id, 0) as bet_id
                    FROM odds
                    WHERE fixture_id = :fixture_id 
                    ORDER BY bookmaker_name, bet_id, value
                """)
                
                results = conn.execute(query, {'fixture_id': self.fixture_id}).fetchall()
                logger.info(f"Encontradas {len(results)} filas de odds para fixture {self.fixture_id}")
                
                bet_names_query = text("""
                    SELECT DISTINCT COALESCE(bet_id, 0) as bid, bet_name 
                    FROM odds WHERE fixture_id = :fixture_id ORDER BY bid
                """)
                bet_names = conn.execute(bet_names_query, {'fixture_id': self.fixture_id}).fetchall()
                logger.info(f"Mercados disponibles: {[(b[0], b[1]) for b in bet_names]}")
            
            match_winner = {}
            goals_ou = {}
            handicap = {}
            btts = {}
            double_chance = {}
            
            # ═══════════════════════════════════════════════════════════
            # API-Football bet_id reference:
            #   1 = Match Winner (1X2)
            #   5 = Goals Over/Under (TOTAL) ← el correcto
            #   6 = Goals Over/Under First Half ← NO
            #   8 = Both Teams Score (BTTS)
            #  16 = Home Team Goals O/U ← NO (cuotas ~8x, inflaban %)
            #  17 = Away Team Goals O/U ← NO
            #  10 = Handicap Result
            #  28 = Asian Handicap
            # ═══════════════════════════════════════════════════════════
            
            for row in results:
                bm = row.bookmaker_name
                bet = row.bet_name or ''
                value = row.value or ''
                odd = row.odd or 0
                bid = row.bet_id or 0
                
                bet_lower = bet.lower()
                
                # ── Match Winner / 1X2 (bet_id=1) ──
                is_1x2 = (bid == 1) or ('match winner' in bet_lower) or (bet_lower == '1x2')
                if is_1x2:
                    if bm not in match_winner:
                        match_winner[bm] = {'bookmaker': bm, 'home': 0, 'draw': 0, 'away': 0}
                    val_lower = value.lower()
                    if val_lower == 'home' or value == '1':
                        match_winner[bm]['home'] = odd
                    elif val_lower == 'draw' or value.lower() == 'x':
                        match_winner[bm]['draw'] = odd
                    elif val_lower == 'away' or value == '2':
                        match_winner[bm]['away'] = odd
                    continue
                
                # ── Goals Over/Under TOTAL (bet_id=5 ONLY) ──
                # EXCLUIR: First Half(6), Home Team(16), Away Team(17)
                is_goals_total = (bid == 5)
                if not is_goals_total and bid == 0:
                    # Fallback por texto: solo si NO tiene modificadores
                    is_goals_total = (
                        ('over' in bet_lower or 'under' in bet_lower)
                        and 'goal' in bet_lower
                        and 'first' not in bet_lower
                        and 'second' not in bet_lower
                        and 'half' not in bet_lower
                        and 'home' not in bet_lower
                        and 'away' not in bet_lower
                        and 'team' not in bet_lower
                        and 'exact' not in bet_lower
                        and 'alternative' not in bet_lower
                        and 'corner' not in bet_lower
                        and 'card' not in bet_lower
                    )
                
                if is_goals_total:
                    if bm not in goals_ou:
                        goals_ou[bm] = {'bookmaker': bm, 'over_25': 0, 'under_25': 0, 
                                        'over_35': 0, 'under_35': 0, 'over_15': 0, 'under_15': 0}
                    val_lower = value.lower()
                    if 'over 2.5' in val_lower or value == 'Over 2.5':
                        goals_ou[bm]['over_25'] = odd
                    elif 'under 2.5' in val_lower or value == 'Under 2.5':
                        goals_ou[bm]['under_25'] = odd
                    elif 'over 3.5' in val_lower or value == 'Over 3.5':
                        goals_ou[bm]['over_35'] = odd
                    elif 'under 3.5' in val_lower or value == 'Under 3.5':
                        goals_ou[bm]['under_35'] = odd
                    elif 'over 1.5' in val_lower or value == 'Over 1.5':
                        goals_ou[bm]['over_15'] = odd
                    elif 'under 1.5' in val_lower or value == 'Under 1.5':
                        goals_ou[bm]['under_15'] = odd
                    continue
                
                # ── Handicap (bet_id 10 o 28) ──
                is_handicap = (bid in (10, 28)) or ('handicap' in bet_lower)
                if is_handicap:
                    if bm not in handicap:
                        handicap[bm] = {'bookmaker': bm, 'lines': []}
                    handicap[bm]['lines'].append({'value': value, 'odd': odd})
                    continue
                
                # ── Both Teams To Score / BTTS (bet_id=8) ──
                is_btts = (bid == 8) or ('both teams' in bet_lower and 'score' in bet_lower)
                if is_btts:
                    if bm not in btts:
                        btts[bm] = {'bookmaker': bm, 'yes': 0, 'no': 0}
                    val_lower = value.lower()
                    if val_lower == 'yes' or val_lower == 'sí' or val_lower == 'si':
                        btts[bm]['yes'] = odd
                    elif val_lower == 'no':
                        btts[bm]['no'] = odd
                    continue
                
                # â"€â"€ Double Chance / Doble Oportunidad (bet_id=12) â"€â"€
                is_dc = (bid == 12) or ('double chance' in bet_lower) or ('doble oportunidad' in bet_lower)
                if is_dc:
                    if bm not in double_chance:
                        double_chance[bm] = {'bookmaker': bm, 'home_draw': 0, 'home_away': 0, 'draw_away': 0}
                    val_lower = value.lower()
                    if val_lower in ('home/draw', '1x', 'home draw'):
                        double_chance[bm]['home_draw'] = odd
                    elif val_lower in ('home/away', '12', 'home away'):
                        double_chance[bm]['home_away'] = odd
                    elif val_lower in ('draw/away', 'x2', 'draw away'):
                        double_chance[bm]['draw_away'] = odd
            
            logger.info(f"Procesados: {len(match_winner)} 1X2, {len(goals_ou)} O/U, {len(handicap)} handicap, {len(btts)} BTTS, {len(double_chance)} DC")
            
            self.finished.emit({
                'match_winner': list(match_winner.values())[:5],
                'goals_ou': list(goals_ou.values())[:5],
                'handicap': list(handicap.values())[:5],
                'btts': list(btts.values())[:5],
                'double_chance': list(double_chance.values())[:5],
                'error_msg': None
            })
        except Exception as e:
            logger.error(f"Error en OddsWorker: {e}")
            self.error.emit(str(e))


class TeamFormWorker(QThread):
    """Worker para forma reciente y próximos partidos de un equipo."""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, team_id: int, team_name: str, sad_engine, current_fixture_date,
                 levels_db_path: str = None):
        super().__init__()
        self.team_id = team_id
        self.team_name = team_name
        self.sad_engine = sad_engine
        self.current_fixture_date = current_fixture_date
        self.levels_db_path = levels_db_path
    
    def run(self):
        try:
            last_matches_query = text("""
                SELECT f.date, f.home_team_id, f.away_team_id, 
                       ht.name as home_name, at.name as away_name,
                       f.goals_home, f.goals_away, l.name as league_name
                FROM fixtures f
                JOIN teams ht ON f.home_team_id = ht.id
                JOIN teams at ON f.away_team_id = at.id
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
                  AND f.status_short = 'FT'
                  AND f.goals_home IS NOT NULL
                  AND f.date < :current_date
                ORDER BY f.date DESC
                LIMIT 3
            """)
            
            next_matches_query = text("""
                SELECT f.date, f.home_team_id, f.away_team_id,
                       ht.name as home_name, at.name as away_name,
                       l.name as league_name
                FROM fixtures f
                JOIN teams ht ON f.home_team_id = ht.id
                JOIN teams at ON f.away_team_id = at.id
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
                  AND f.status_short IN ('NS', 'TBD', 'SCHEDULED')
                  AND f.date > :current_date
                ORDER BY f.date ASC
                LIMIT 4
            """)
            
            with self.sad_engine.connect() as conn:
                last_results = conn.execute(last_matches_query, {
                    'team_id': self.team_id,
                    'current_date': self.current_fixture_date
                }).fetchall()
                
                next_results = conn.execute(next_matches_query, {
                    'team_id': self.team_id,
                    'current_date': self.current_fixture_date
                }).fetchall()
            
            last_matches = []
            for r in last_results:
                is_home = r.home_team_id == self.team_id
                opponent = r.away_name if is_home else r.home_name
                goals_for = r.goals_home if is_home else r.goals_away
                goals_against = r.goals_away if is_home else r.goals_home
                
                if goals_for > goals_against:
                    result = 'W'
                elif goals_for < goals_against:
                    result = 'L'
                else:
                    result = 'D'
                
                last_matches.append({
                    'date': r.date,
                    'opponent': opponent,
                    'is_home': is_home,
                    'goals_for': goals_for,
                    'goals_against': goals_against,
                    'result': result,
                    'league': (r.league_name or '').strip() if r.league_name else ''
                })
            
            next_matches = []
            for r in next_results:
                is_home = r.home_team_id == self.team_id
                opponent = r.away_name if is_home else r.home_name
                opponent_id = r.away_team_id if is_home else r.home_team_id
                
                next_matches.append({
                    'date': r.date,
                    'opponent': opponent,
                    'opponent_id': opponent_id,
                    'is_home': is_home,
                    'league': (r.league_name or '').strip() if r.league_name else ''
                })
            
            # ── Consultar niveles de rivales futuros desde levels.db ──
            if next_matches and self.levels_db_path and os.path.exists(self.levels_db_path):
                try:
                    levels_engine = create_engine(
                        f'sqlite:///{self.levels_db_path}', echo=False
                    )
                    levels_map = {}
                    with levels_engine.connect() as conn:
                        for m in next_matches:
                            oid = m['opponent_id']
                            row = conn.execute(text(
                                "SELECT level FROM team_levels "
                                "WHERE team_id = :tid ORDER BY date DESC LIMIT 1"
                            ), {'tid': oid}).fetchone()
                            if row:
                                levels_map[oid] = row[0]
                    
                    for m in next_matches:
                        m['opponent_level'] = levels_map.get(m['opponent_id'])
                    
                    logger.info(f"Niveles de rivales futuros: {levels_map}")
                except Exception as e:
                    logger.warning(f"No se pudieron obtener niveles de levels.db: {e}")
            
            self.finished.emit({
                'team_id': self.team_id,
                'team_name': self.team_name,
                'last_matches': last_matches,
                'next_matches': next_matches
            })
            
        except Exception as e:
            logger.error(f"Error en TeamFormWorker: {e}")
            self.error.emit(str(e))


class RegresionNivelWorker(QThread):
    """Worker para predicción de Regresión al Nivel."""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, home_id: int, away_id: int, league_id: int,
                 season: int, match_date, project_root: str = None):
        super().__init__()
        self.home_id = home_id
        self.away_id = away_id
        self.league_id = league_id
        self.season = season
        self.match_date = match_date
        self.project_root = project_root
    
    def run(self):
        try:
            from regresion_nivel_engine import RegresionNivelEngine
            
            sad_path = None
            if self.project_root:
                sad_path = os.path.join(self.project_root, 'sad.db')
            
            engine = RegresionNivelEngine(sad_db_path=sad_path)
            
            if not engine.load_model():
                self.error.emit("Modelo Regresión al Nivel no encontrado")
                return
            
            date_str = None
            if self.match_date:
                if isinstance(self.match_date, datetime):
                    date_str = self.match_date.isoformat()
                else:
                    date_str = str(self.match_date)
            
            pred = engine.predict_match(
                home_id=self.home_id,
                away_id=self.away_id,
                league_id=self.league_id,
                season=self.season,
                date=date_str,
            )
            
            if pred is None:
                self.error.emit("Sin datos suficientes (niveles o forma reciente)")
                return
            
            self.finished.emit({
                'home_team': pred.home_team,
                'away_team': pred.away_team,
                'p_home_win': pred.p_home_win,
                'p_away_win': pred.p_away_win,
                'p_draw_approx': pred.p_draw_approx,
                'gap_home': pred.gap_home,
                'gap_away': pred.gap_away,
                'gap_diff': pred.gap_diff,
                'level_home': pred.level_home,
                'level_away': pred.level_away,
                'level_diff': pred.level_diff,
                'mu_home': pred.mu_home,
                'mu_away': pred.mu_away,
                'pts_recent_home': pred.pts_recent_home,
                'pts_recent_away': pred.pts_recent_away,
                'confidence': pred.confidence,
                'recommendation': pred.recommendation,
                'is_international': pred.is_international,
                'season_progress': pred.season_progress,
            })
            
        except ImportError:
            self.error.emit("Módulo regresion_nivel_engine no disponible")
        except Exception as e:
            logger.error(f"Error en RegresionNivelWorker: {e}")
            self.error.emit(str(e))


class FePerdidaWorker(QThread):
    """Worker para analisis de Ley de la Fe Perdida (pendulo del hincha)."""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, home_id: int, away_id: int, league_id: int,
                 fixture_id: int, match_date, project_root: str = None):
        super().__init__()
        self.home_id = home_id
        self.away_id = away_id
        self.league_id = league_id
        self.fixture_id = fixture_id
        self.match_date = match_date
        self.project_root = project_root
    
    def run(self):
        try:
            from ley_fe_perdida_engine import FePerdidaEngine
            
            engine = FePerdidaEngine()
            odds = engine._get_match_odds(self.fixture_id) if self.fixture_id else {}
            
            analysis = engine.analyze_match(
                home_team_id=self.home_id,
                away_team_id=self.away_id,
                league_id=self.league_id,
                fixture_id=self.fixture_id,
                match_date=str(self.match_date),
                odds_home=odds.get('home'),
                odds_draw=odds.get('draw'),
                odds_away=odds.get('away'),
            )
            
            if analysis is None:
                self.error.emit("Sin datos suficientes para Fe Perdida")
                return
            
            result = {
                'home_name': analysis.home.team_name,
                'away_name': analysis.away.team_name,
                'home_pendulum': analysis.home.pendulum_score,
                'away_pendulum': analysis.away.pendulum_score,
                'home_zone': analysis.home.zone.value,
                'away_zone': analysis.away.zone.value,
                'home_stature': analysis.home.stature.value,
                'away_stature': analysis.away.stature.value,
                'home_racha': ''.join(analysis.home.last_results[:5]),
                'away_racha': ''.join(analysis.away.last_results[:5]),
                'home_mode': analysis.home.mode,
                'away_mode': analysis.away.mode,
                'gap': analysis.gap,
                'flag': analysis.flag.value,
                'flag_emoji': analysis.flag_emoji,
                'flag_description': analysis.flag_description,
                'edge_pp': analysis.edge_pp,
                'prob_home': analysis.prob_home,
                'prob_draw': analysis.prob_draw,
                'prob_away': analysis.prob_away,
                'expected_margin': analysis.expected_margin,
                'goleada_pct': analysis.goleada_pct,
                'home_goal_flag': analysis.home.goal_flag.value if analysis.home.goal_flag else 'none',
                'away_goal_flag': analysis.away.goal_flag.value if analysis.away.goal_flag else 'none',
                'home_scores_pct': analysis.home.team_scores_pct,
                'away_scores_pct': analysis.away.team_scores_pct,
            }
            self.finished.emit(result)
            
        except ImportError:
            self.error.emit("Modulo ley_fe_perdida_engine no disponible")
        except Exception as e:
            logger.error(f"Error en FePerdidaWorker: {e}")
            self.error.emit(str(e))




class PreviousOddsWorker(QThread):
    """Worker para obtener odds de los 2 partidos anteriores de cada equipo."""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, home_id: int, away_id: int, home_name: str, away_name: str,
                 sad_engine, current_fixture_date):
        super().__init__()
        self.home_id = home_id
        self.away_id = away_id
        self.home_name = home_name
        self.away_name = away_name
        self.sad_engine = sad_engine
        self.current_fixture_date = current_fixture_date

    def _get_last_fixtures(self, team_id, conn):
        """Obtiene los 2 últimos partidos terminados de un equipo."""
        q = text("""
            SELECT f.id as fixture_id, f.date, f.home_team_id, f.away_team_id,
                   ht.name as home_name, at.name as away_name,
                   f.goals_home, f.goals_away
            FROM fixtures f
            JOIN teams ht ON f.home_team_id = ht.id
            JOIN teams at ON f.away_team_id = at.id
            WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
              AND f.status_short = 'FT'
              AND f.goals_home IS NOT NULL
              AND f.date < :current_date
            ORDER BY f.date DESC
            LIMIT 2
        """)
        return conn.execute(q, {
            'team_id': team_id,
            'current_date': self.current_fixture_date
        }).fetchall()

    def _get_fixture_odds(self, fixture_id, conn):
        """Obtiene odds de un fixture: 1X2, O2.5, BTTS, DC."""
        q = text("""
            SELECT bookmaker_name, bet_name, value, odd,
                   COALESCE(bet_id, 0) as bet_id
            FROM odds
            WHERE fixture_id = :fid
            ORDER BY bookmaker_name, bet_id, value
        """)
        rows = conn.execute(q, {'fid': fixture_id}).fetchall()

        odds_1x2 = {}
        odds_ou25 = {}
        odds_btts = {}
        odds_dc = {}

        for row in rows:
            bm = row.bookmaker_name
            bid = row.bet_id or 0
            value = (row.value or '').lower()
            odd = row.odd or 0

            # 1X2 (bet_id=1)
            if bid == 1:
                if bm not in odds_1x2:
                    odds_1x2[bm] = {'home': 0, 'draw': 0, 'away': 0}
                if value in ('home', '1'):
                    odds_1x2[bm]['home'] = odd
                elif value in ('draw', 'x'):
                    odds_1x2[bm]['draw'] = odd
                elif value in ('away', '2'):
                    odds_1x2[bm]['away'] = odd

            # Over/Under (bet_id=5)
            elif bid == 5:
                if bm not in odds_ou25:
                    odds_ou25[bm] = {'over': 0, 'under': 0}
                if 'over' in value and '2.5' in value:
                    odds_ou25[bm]['over'] = odd
                elif 'under' in value and '2.5' in value:
                    odds_ou25[bm]['under'] = odd

            # BTTS (bet_id=8)
            elif bid == 8:
                if bm not in odds_btts:
                    odds_btts[bm] = {'yes': 0, 'no': 0}
                if value == 'yes':
                    odds_btts[bm]['yes'] = odd
                elif value == 'no':
                    odds_btts[bm]['no'] = odd

            # Double Chance (bet_id=12)
            elif bid == 12:
                if bm not in odds_dc:
                    odds_dc[bm] = {'1x': 0, '12': 0, 'x2': 0}
                if value in ('home/draw', '1x'):
                    odds_dc[bm]['1x'] = odd
                elif value in ('home/away', '12'):
                    odds_dc[bm]['12'] = odd
                elif value in ('draw/away', 'x2'):
                    odds_dc[bm]['x2'] = odd

        def pick_best(d):
            if not d:
                return None
            for bm in d:
                if 'bet365' in bm.lower():
                    return d[bm]
            return list(d.values())[0]

        return {
            '1x2': pick_best(odds_1x2),
            'ou25': pick_best(odds_ou25),
            'btts': pick_best(odds_btts),
            'dc': pick_best(odds_dc),
        }

    def run(self):
        try:
            with self.sad_engine.connect() as conn:
                # Check odds table exists
                table_check = conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='odds'"
                )).fetchone()
                has_odds_table = table_check is not None

                result = {'home': [], 'away': []}

                for side, team_id, team_name in [
                    ('home', self.home_id, self.home_name),
                    ('away', self.away_id, self.away_name),
                ]:
                    fixtures = self._get_last_fixtures(team_id, conn)
                    for fx in fixtures:
                        is_home = fx.home_team_id == team_id
                        opponent = fx.away_name if is_home else fx.home_name
                        gf = fx.goals_home if is_home else fx.goals_away
                        ga = fx.goals_away if is_home else fx.goals_home

                        if gf > ga:
                            res = 'W'
                        elif gf < ga:
                            res = 'L'
                        else:
                            res = 'D'

                        total_goals = fx.goals_home + fx.goals_away
                        btts_hit = fx.goals_home > 0 and fx.goals_away > 0

                        # Determine winning outcome for 1X2
                        if fx.goals_home > fx.goals_away:
                            outcome_1x2 = 'home'
                        elif fx.goals_home < fx.goals_away:
                            outcome_1x2 = 'away'
                        else:
                            outcome_1x2 = 'draw'

                        # Determine DC outcome
                        dc_outcomes = set()
                        if outcome_1x2 in ('home', 'draw'):
                            dc_outcomes.add('1x')
                        if outcome_1x2 in ('home', 'away'):
                            dc_outcomes.add('12')
                        if outcome_1x2 in ('draw', 'away'):
                            dc_outcomes.add('x2')

                        match_data = {
                            'fixture_id': fx.fixture_id,
                            'date': fx.date,
                            'opponent': opponent,
                            'is_home': is_home,
                            'goals_for': gf,
                            'goals_against': ga,
                            'result': res,
                            'outcome_1x2': outcome_1x2,
                            'over25_hit': total_goals > 2.5,
                            'btts_hit': btts_hit,
                            'dc_outcomes': dc_outcomes,
                            'odds': {},
                        }

                        if has_odds_table:
                            match_data['odds'] = self._get_fixture_odds(fx.fixture_id, conn)

                        result[side].append(match_data)

            self.finished.emit(result)

        except Exception as e:
            logger.error(f"Error en PreviousOddsWorker: {e}")
            self.error.emit(str(e))


class BubbleExporterWorker(QThread):
    """Worker para exportar burbujas (gráficos + CSV) en background."""
    finished = Signal(dict)
    progress = Signal(str, int)  # message, percent
    error = Signal(str)
    
    def __init__(self, team_id: int, output_dir: str, project_root: str):
        super().__init__()
        self.team_id = team_id
        self.output_dir = output_dir
        self.project_root = project_root
    
    def run(self):
        try:
            from utils.bubble_exporter import BubbleExporter
            
            exporter = BubbleExporter(self.project_root)
            
            results = exporter.export_all(
                team_id=self.team_id,
                output_dir=self.output_dir,
                progress_callback=lambda msg, pct: self.progress.emit(msg, pct),
            )
            
            self.finished.emit(results)
            
        except ImportError:
            self.error.emit("Módulo bubble_exporter no disponible")
        except Exception as e:
            logger.error(f"Error en BubbleExporterWorker: {e}")
            self.error.emit(str(e))


# =============================================================================
# VENTANA PRINCIPAL
# =============================================================================

class PreMatchAnalysisWindow(QMainWindow):
    """Ventana de Análisis Pre-Partido."""
    
    TOTAL_WORKERS = 10
    
    def __init__(self, fixture_id: int = None):
        super().__init__()
        self.setWindowTitle("⚽ Análisis Pre-Partido")
        
        self.project_root = find_project_root()
        self.sad_engine = create_engine(f'sqlite:///{os.path.join(self.project_root, "sad.db")}', echo=False)
        
        self.teams_data = []
        self.current_fixture = None
        self.pending_workers = 0
        self.loaded_odds_data = {}
        self._current_odds_map = {}  # FIX: Inicializar aquí para evitar AttributeError
        
        # Toggle % ↔ cuotas
        self._show_as_odds = False
        self._raw_probabilities = {}   # {label_attr: prob_decimal, ...}
        self._raw_odds_bookmaker = {}  # {market_key: bookmaker_odd, ...}
        
        # Datos de forma para sincronizar con Fe Perdida
        self._form_results_home = []
        self._form_results_away = []

        # Nombres de equipos para H2H
        self._h2h_home_name = ''
        self._h2h_away_name = ''
        
        self._build_ui()
        self._load_teams()
        self._adjust_window_size()
        
        if fixture_id:
            QTimer.singleShot(100, lambda: self.load_fixture(fixture_id))
    
    def load_fixture(self, fixture_id: int):
        """Carga un partido específico por su fixture_id."""
        logger.info(f"Cargando fixture_id: {fixture_id}")
        
        try:
            query = text("""
                SELECT 
                    f.id as fixture_id, f.date,
                    f.home_team_id, f.away_team_id,
                    f.league_id, f.league_season, f.status_short,
                    ht.name as home_team_name,
                    at.name as away_team_name,
                    l.name as league_name
                FROM fixtures f
                JOIN teams ht ON f.home_team_id = ht.id
                JOIN teams at ON f.away_team_id = at.id
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE f.id = :fixture_id
            """)
            
            with self.sad_engine.connect() as conn:
                result = conn.execute(query, {'fixture_id': fixture_id}).fetchone()
            
            if not result:
                QMessageBox.warning(self, "Error", f"No se encontró el partido (ID: {fixture_id})")
                return
            
            match_date = result.date
            if isinstance(match_date, str):
                try:
                    match_date = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
                except:
                    match_date = datetime.now()
            
            fixture = {
                'fixture_id': result.fixture_id,
                'date': match_date,
                'home_team_id': result.home_team_id,
                'away_team_id': result.away_team_id,
                'home_team_name': result.home_team_name,
                'away_team_name': result.away_team_name,
                'league_id': result.league_id,
                'league_season': getattr(result, 'league_season', None),
                'is_home': True,
                'rival_id': result.away_team_id,
            }
            
            self.current_fixture = fixture
            
            index = self.team_combo.findData(result.home_team_id)
            if index >= 0:
                self.team_combo.setCurrentIndex(index)
            
            self._update_match_info(fixture, result.home_team_id)
            
            self.analyze_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Analizando partido...")
            
            self._start_analysis(fixture, result.home_team_id)
            
            self.bubbles_btn.setEnabled(BUBBLES_AVAILABLE)
            self.sad_dashboard_btn.setEnabled(SAD_DASHBOARD_AVAILABLE)
            self.k_scoreline_btn.setEnabled(K_SCORELINE_AVAILABLE)
            self.export_team_btn.setEnabled(True)
            self.export_rival_btn.setEnabled(True)
            
            logger.info(f"Fixture cargado: {result.home_team_name} vs {result.away_team_name}")
            
        except Exception as e:
            logger.error(f"Error cargando fixture {fixture_id}: {e}")
            QMessageBox.critical(self, "Error", f"Error al cargar partido:\n{str(e)}")
    
    def _adjust_window_size(self):
        screen = QApplication.primaryScreen().availableGeometry()
        desired_width = min(950, screen.width() - 50)
        desired_height = min(720, screen.height() - 80)
        self.resize(desired_width, desired_height)
        self.setMinimumSize(750, 500)
        x = (screen.width() - desired_width) // 2
        y = (screen.height() - desired_height) // 2
        self.move(max(10, x), max(10, y))
    
    def _build_ui(self):
        """Construye la interfaz con scroll general."""
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # ═══════════════════════════════════════════════════════════════════
        # HEADER FIJO
        # ═══════════════════════════════════════════════════════════════════
        header = QWidget()
        header.setStyleSheet("background-color: #f8f9fa; border-bottom: 1px solid #dee2e6;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        header_layout.addWidget(QLabel("Equipo:"))
        self.team_combo = QComboBox()
        self.team_combo.setEditable(True)
        self.team_combo.setMinimumWidth(280)
        self.team_combo.setPlaceholderText("Escribe para buscar...")
        header_layout.addWidget(self.team_combo)
        
        self.analyze_btn = QPushButton("🔎 Analizar Próximo Partido")
        self.analyze_btn.setStyleSheet("""
            QPushButton { background-color: #17A2B8; color: white; font-weight: bold;
                         padding: 8px 16px; border-radius: 5px; border: none; }
            QPushButton:hover { background-color: #138496; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.analyze_btn.clicked.connect(self._on_analyze_clicked)
        header_layout.addWidget(self.analyze_btn)
        
        # Botón Ver Burbujas (Constantes K)
        self.bubbles_btn = QPushButton("📊 Ver Burbujas")
        self.bubbles_btn.setStyleSheet("""
            QPushButton { background-color: #6f42c1; color: white; font-weight: bold;
                         padding: 8px 16px; border-radius: 5px; border: none; }
            QPushButton:hover { background-color: #5a32a3; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.bubbles_btn.setToolTip("Abrir gráficos de evolución de constantes K para ambos equipos")
        self.bubbles_btn.clicked.connect(self._open_bubbles)
        self.bubbles_btn.setEnabled(False)
        header_layout.addWidget(self.bubbles_btn)
        
        # Botón SAD Dashboard (Fase 1 Extracción)
        self.sad_dashboard_btn = QPushButton("📊 SAD Dashboard")
        self.sad_dashboard_btn.setStyleSheet("""
            QPushButton { background-color: #0a1628; color: #3b82f6; font-weight: bold;
                         padding: 8px 16px; border-radius: 5px; border: 1px solid #3b82f6; }
            QPushButton:hover { background-color: #1a2235; color: #60a5fa; }
            QPushButton:disabled { background-color: #6c757d; color: #aaa; border-color: #6c757d; }
        """)
        self.sad_dashboard_btn.setToolTip(
            "Abrir SAD Dashboard — Extracción Fase 1\n"
            "Constantes K con ECG, bursts, goles y tablero de decisiones"
        )
        self.sad_dashboard_btn.clicked.connect(self._open_sad_dashboard)
        self.sad_dashboard_btn.setEnabled(False)
        header_layout.addWidget(self.sad_dashboard_btn)
        
        # Botón Marcador por K (Dixon-Coles)
        self.k_scoreline_btn = QPushButton("⚽ Marcador K")
        self.k_scoreline_btn.setStyleSheet("""
            QPushButton { background-color: #0D1117; color: #58A6FF; font-weight: bold;
                         padding: 8px 16px; border-radius: 5px; border: 1px solid #58A6FF; }
            QPushButton:hover { background-color: #161B22; color: #79C0FF; }
            QPushButton:disabled { background-color: #6c757d; color: #aaa; border-color: #6c757d; }
        """)
        self.k_scoreline_btn.setToolTip(
            "Abrir predictor de marcadores por Constantes K\n"
            "Dixon-Coles desde dinámica de K — Distribuciones, heatmap, top scores"
        )
        self.k_scoreline_btn.clicked.connect(self._open_k_scoreline)
        self.k_scoreline_btn.setEnabled(False)
        header_layout.addWidget(self.k_scoreline_btn)
        
        # Toggle % ↔ Cuotas
        self.odds_toggle = QCheckBox("Mostrar cuotas")
        self.odds_toggle.setToolTip(
            "Convierte todos los porcentajes a cuotas decimales equivalentes.\n"
            "Cuota = 1 / probabilidad  (ej: 50% → @2.00)"
        )
        self.odds_toggle.setStyleSheet("""
            QCheckBox {
                font-size: 11px;
                color: #555;
                spacing: 4px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        self.odds_toggle.toggled.connect(self._on_odds_toggle)
        header_layout.addWidget(self.odds_toggle)
        
        header_layout.addStretch()
        main_layout.addWidget(header)
        
        # ═══════════════════════════════════════════════════════════════════
        # SCROLL AREA GENERAL
        # ═══════════════════════════════════════════════════════════════════
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.scroll_content = QWidget()
        content_layout = QVBoxLayout(self.scroll_content)
        content_layout.setContentsMargins(15, 15, 15, 15)
        content_layout.setSpacing(15)
        
        # INFO DEL PARTIDO
        match_frame = QFrame()
        match_frame.setStyleSheet("background-color: #1a1a2e; border-radius: 8px;")
        match_frame.setFixedHeight(70)
        match_layout = QVBoxLayout(match_frame)
        match_layout.setContentsMargins(20, 10, 20, 10)
        
        self.match_title = QLabel("Selecciona un equipo para ver su próximo partido")
        self.match_title.setAlignment(Qt.AlignCenter)
        self.match_title.setStyleSheet("font-size: 15px; font-weight: bold; color: white;")
        match_layout.addWidget(self.match_title)
        
        self.match_details = QLabel("")
        self.match_details.setAlignment(Qt.AlignCenter)
        self.match_details.setStyleSheet("color: #aaa; font-size: 11px;")
        match_layout.addWidget(self.match_details)
        content_layout.addWidget(match_frame)
        
        # ═══════════════════════════════════════════════════════════════════
        # PANEL: CONSTANTES
        # ═══════════════════════════════════════════════════════════════════
        constants_group = self._create_group("📊 Simulación de Constantes (K)")
        constants_layout = QVBoxLayout()
        
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Modelo:"))
        self.model_btn_group = QButtonGroup(self)
        for i, (text_val, checked) in enumerate([("Auto", True), ("Global", False), ("Liga", False)]):
            rb = QRadioButton(text_val)
            rb.setChecked(checked)
            self.model_btn_group.addButton(rb, i)
            model_row.addWidget(rb)
        model_row.addStretch()
        constants_layout.addLayout(model_row)
        
        tables_row = QHBoxLayout()
        tables_row.setSpacing(15)
        
        team_box = QVBoxLayout()
        self.team_const_label = QLabel("🏠 Equipo (Local)")
        self.team_const_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        team_box.addWidget(self.team_const_label)
        self.team_const_table = self._create_constants_table()
        team_box.addWidget(self.team_const_table)
        self.export_team_btn = QPushButton("📤 Exportar Burbujas")
        self.export_team_btn.setStyleSheet("""
            QPushButton { background-color: #0d6efd; color: white; font-size: 10px;
                         padding: 4px 10px; border-radius: 4px; border: none; }
            QPushButton:hover { background-color: #0b5ed7; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.export_team_btn.setToolTip("Exportar gráficos y CSV de constantes K del equipo local")
        self.export_team_btn.clicked.connect(lambda: self._export_bubbles('home'))
        self.export_team_btn.setEnabled(False)
        team_box.addWidget(self.export_team_btn)
        tables_row.addLayout(team_box)
        
        rival_box = QVBoxLayout()
        self.rival_const_label = QLabel("✈️ Rival (Visitante)")
        self.rival_const_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        rival_box.addWidget(self.rival_const_label)
        self.rival_const_table = self._create_constants_table()
        rival_box.addWidget(self.rival_const_table)
        self.export_rival_btn = QPushButton("📤 Exportar Burbujas")
        self.export_rival_btn.setStyleSheet("""
            QPushButton { background-color: #0d6efd; color: white; font-size: 10px;
                         padding: 4px 10px; border-radius: 4px; border: none; }
            QPushButton:hover { background-color: #0b5ed7; }
            QPushButton:disabled { background-color: #6c757d; }
        """)
        self.export_rival_btn.setToolTip("Exportar gráficos y CSV de constantes K del rival")
        self.export_rival_btn.clicked.connect(lambda: self._export_bubbles('away'))
        self.export_rival_btn.setEnabled(False)
        rival_box.addWidget(self.export_rival_btn)
        tables_row.addLayout(rival_box)
        
        constants_layout.addLayout(tables_row)
        constants_group.setLayout(constants_layout)
        content_layout.addWidget(constants_group)
        
        # ═══════════════════════════════════════════════════════════════════
        # PANEL: ANTICULEBRA
        # ═══════════════════════════════════════════════════════════════════
        anticulebra_group = self._create_group("🐍 Ley Anticulebra (ML v6)")
        anticulebra_layout = QVBoxLayout()
        
        ml_frame = QFrame()
        ml_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        ml_layout = QHBoxLayout(ml_frame)
        ml_layout.setContentsMargins(15, 10, 15, 10)
        
        ml_label = QLabel("âš¡ Score ML:")
        ml_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        ml_layout.addWidget(ml_label)
        
        self.ml_score_label = QLabel("-")
        self.ml_score_label.setStyleSheet("font-weight: bold; font-size: 20px; color: #333;")
        ml_layout.addWidget(self.ml_score_label)
        
        self.ml_recommendation = QLabel("")
        self.ml_recommendation.setStyleSheet("font-size: 13px; margin-left: 20px;")
        ml_layout.addWidget(self.ml_recommendation)
        
        ml_layout.addStretch()
        
        self.ml_type_label = QLabel("")
        self.ml_type_label.setStyleSheet("font-size: 12px; color: #666;")
        ml_layout.addWidget(self.ml_type_label)
        
        anticulebra_layout.addWidget(ml_frame)
        
        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(10)
        
        labels_data = [
            ("ICF Local:", 0, 0), ("ICF Visitante:", 0, 2), ("Diferencia:", 0, 4),
            ("Prob 1:", 1, 0), ("Prob X:", 1, 2), ("Prob 2:", 1, 4),
            ("Favorito:", 2, 0), ("Prob Ruptura (base):", 2, 2)
        ]
        for text_val, row, col in labels_data:
            grid.addWidget(QLabel(text_val), row, col)
        
        self.icf_home = self._create_value_label()
        self.icf_away = self._create_value_label()
        self.icf_diff = self._create_value_label()
        self.prob_home = self._create_value_label("#28a745")
        self.prob_draw = self._create_value_label("#ffc107")
        self.prob_away = self._create_value_label("#dc3545")
        self.favorite = self._create_value_label()
        self.break_prob = self._create_value_label("#e74c3c")
        
        grid.addWidget(self.icf_home, 0, 1)
        grid.addWidget(self.icf_away, 0, 3)
        grid.addWidget(self.icf_diff, 0, 5)
        grid.addWidget(self.prob_home, 1, 1)
        grid.addWidget(self.prob_draw, 1, 3)
        grid.addWidget(self.prob_away, 1, 5)
        grid.addWidget(self.favorite, 2, 1)
        grid.addWidget(self.break_prob, 2, 3)
        
        anticulebra_layout.addLayout(grid)
        
        # ── Odds ──
        odds_frame = QFrame()
        odds_frame.setStyleSheet("""
            QFrame {
                background-color: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        odds_main_layout = QVBoxLayout(odds_frame)
        odds_main_layout.setContentsMargins(10, 8, 10, 8)
        odds_main_layout.setSpacing(6)
        
        odds_header = QHBoxLayout()
        odds_title = QLabel("💰 CUOTAS (% Ganancia)")
        odds_title.setStyleSheet("font-weight: bold; color: #856404; font-size: 12px;")
        odds_header.addWidget(odds_title)
        odds_header.addStretch()
        self.odds_source = QLabel("")
        self.odds_source.setStyleSheet("font-size: 10px; color: #999;")
        odds_header.addWidget(self.odds_source)
        odds_main_layout.addLayout(odds_header)
        
        row1 = QHBoxLayout()
        row1.setSpacing(15)
        lbl_1x2 = QLabel("1X2:")
        lbl_1x2.setStyleSheet("font-weight: bold; color: #555; min-width: 60px;")
        row1.addWidget(lbl_1x2)
        self.odds_1x2 = QLabel("⚠️ Sin datos")
        self.odds_1x2.setStyleSheet("font-size: 12px;")
        row1.addWidget(self.odds_1x2)
        row1.addStretch()
        odds_main_layout.addLayout(row1)
        
        row2 = QHBoxLayout()
        row2.setSpacing(15)
        lbl_goles = QLabel("Goles:")
        lbl_goles.setStyleSheet("font-weight: bold; color: #555; min-width: 60px;")
        row2.addWidget(lbl_goles)
        self.odds_goles = QLabel("-")
        self.odds_goles.setStyleSheet("font-size: 12px;")
        row2.addWidget(self.odds_goles)
        row2.addStretch()
        odds_main_layout.addLayout(row2)
        
        row3 = QHBoxLayout()
        row3.setSpacing(15)
        lbl_hcap = QLabel("Hándicap:")
        lbl_hcap.setStyleSheet("font-weight: bold; color: #555; min-width: 60px;")
        row3.addWidget(lbl_hcap)
        self.odds_handicap = QLabel("-")
        self.odds_handicap.setStyleSheet("font-size: 12px;")
        row3.addWidget(self.odds_handicap)
        row3.addStretch()
        odds_main_layout.addLayout(row3)
        
        row4 = QHBoxLayout()
        row4.setSpacing(15)
        lbl_btts = QLabel("BTTS:")
        lbl_btts.setStyleSheet("font-weight: bold; color: #555; min-width: 60px;")
        row4.addWidget(lbl_btts)
        self.odds_btts = QLabel("-")
        self.odds_btts.setStyleSheet("font-size: 12px;")
        row4.addWidget(self.odds_btts)
        row4.addStretch()
        odds_main_layout.addLayout(row4)
        
        row5 = QHBoxLayout()
        row5.setSpacing(15)
        lbl_dc = QLabel("DC:")
        lbl_dc.setStyleSheet("font-weight: bold; color: #555; min-width: 60px;")
        row5.addWidget(lbl_dc)
        self.odds_dc = QLabel("-")
        self.odds_dc.setStyleSheet("font-size: 12px;")
        row5.addWidget(self.odds_dc)
        row5.addStretch()
        odds_main_layout.addLayout(row5)
        
        anticulebra_layout.addWidget(odds_frame)
        
        
        anticulebra_group.setLayout(anticulebra_layout)
        content_layout.addWidget(anticulebra_group)
        
        
        # ═══════════════════════════════════════════════════════════════════
        # PANEL: FORMA RECIENTE — Círculos Flashscore (NUEVO)
        # ═══════════════════════════════════════════════════════════════════
        form_group = self._create_group("📊 Forma Reciente & Calendario")
        form_main = QHBoxLayout()
        form_main.setSpacing(20)

        # ── Columna HOME ──
        home_col = QVBoxLayout()
        home_col.setSpacing(4)

        self.home_form_title = QLabel("🏠 Local")
        self.home_form_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #28a745;")
        home_col.addWidget(self.home_form_title)

        # Círculos W/D/L
        self.home_circles = QHBoxLayout()
        self.home_circles.setSpacing(6)
        home_col.addLayout(self.home_circles)

        # Resumen (ej: "0V 2E 1D • 2/9 pts")
        self.home_form_summary = QLabel("")
        self.home_form_summary.setStyleSheet("font-size: 11px; margin: 2px 0;")
        home_col.addWidget(self.home_form_summary)

        lbl_last_h = QLabel("Últimos 3:")
        lbl_last_h.setStyleSheet("font-size: 9px; color: #999; margin-top: 4px;")
        home_col.addWidget(lbl_last_h)

        self.home_details = QVBoxLayout()
        self.home_details.setSpacing(1)
        home_col.addLayout(self.home_details)

        lbl_next_h = QLabel("Próximos 3:")
        lbl_next_h.setStyleSheet("font-size: 9px; color: #999; margin-top: 6px;")
        home_col.addWidget(lbl_next_h)

        self.home_next = QVBoxLayout()
        self.home_next.setSpacing(2)
        home_col.addLayout(self.home_next)

        home_col.addStretch()
        form_main.addLayout(home_col)

        # ── Separador ──
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #dee2e6;")
        form_main.addWidget(sep)

        # ── Columna AWAY ──
        away_col = QVBoxLayout()
        away_col.setSpacing(4)

        self.away_form_title = QLabel("✈️ Visitante")
        self.away_form_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #dc3545;")
        away_col.addWidget(self.away_form_title)

        self.away_circles = QHBoxLayout()
        self.away_circles.setSpacing(6)
        away_col.addLayout(self.away_circles)

        self.away_form_summary = QLabel("")
        self.away_form_summary.setStyleSheet("font-size: 11px; margin: 2px 0;")
        away_col.addWidget(self.away_form_summary)

        lbl_last_a = QLabel("Últimos 3:")
        lbl_last_a.setStyleSheet("font-size: 9px; color: #999; margin-top: 4px;")
        away_col.addWidget(lbl_last_a)

        self.away_details = QVBoxLayout()
        self.away_details.setSpacing(1)
        away_col.addLayout(self.away_details)

        lbl_next_a = QLabel("Próximos 3:")
        lbl_next_a.setStyleSheet("font-size: 9px; color: #999; margin-top: 6px;")
        away_col.addWidget(lbl_next_a)

        self.away_next = QVBoxLayout()
        self.away_next.setSpacing(2)
        away_col.addLayout(self.away_next)

        away_col.addStretch()
        form_main.addLayout(away_col)

        form_group.setLayout(form_main)
        content_layout.addWidget(form_group)


        # ═══════════════════════════════════════════════════════════════════
        # PANEL: ODDS DE RIVALES ANTERIORES
        # ═══════════════════════════════════════════════════════════════════
        prev_odds_group = self._create_group("📊 Odds de Rivales Anteriores")
        prev_odds_main = QHBoxLayout()
        prev_odds_main.setSpacing(20)

        # ── Columna HOME ──
        home_prev_col = QVBoxLayout()
        home_prev_col.setSpacing(4)
        self.prev_odds_home_title = QLabel("🏠 Local")
        self.prev_odds_home_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #28a745;")
        home_prev_col.addWidget(self.prev_odds_home_title)
        self.prev_odds_home_content = QVBoxLayout()
        self.prev_odds_home_content.setSpacing(4)
        home_prev_col.addLayout(self.prev_odds_home_content)
        home_prev_col.addStretch()
        prev_odds_main.addLayout(home_prev_col)

        # ── Separador ──
        sep_po = QFrame()
        sep_po.setFrameShape(QFrame.VLine)
        sep_po.setStyleSheet("color: #dee2e6;")
        prev_odds_main.addWidget(sep_po)

        # ── Columna AWAY ──
        away_prev_col = QVBoxLayout()
        away_prev_col.setSpacing(4)
        self.prev_odds_away_title = QLabel("✈️ Visitante")
        self.prev_odds_away_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #dc3545;")
        away_prev_col.addWidget(self.prev_odds_away_title)
        self.prev_odds_away_content = QVBoxLayout()
        self.prev_odds_away_content.setSpacing(4)
        away_prev_col.addLayout(self.prev_odds_away_content)
        away_prev_col.addStretch()
        prev_odds_main.addLayout(away_prev_col)

        prev_odds_group.setLayout(prev_odds_main)
        content_layout.addWidget(prev_odds_group)

        # ═══════════════════════════════════════════════════════════════════
        # PANEL: REGRESIÓN AL NIVEL
        # ═══════════════════════════════════════════════════════════════════
        regresion_group = self._create_group("📉 Ley de la Regresión al Nivel")
        regresion_layout = QVBoxLayout()
        
        rn_main = QHBoxLayout()
        rn_main.setSpacing(20)
        
        rn_home_box = QVBoxLayout()
        rn_home_box.setSpacing(2)
        self.rn_home_label = QLabel("🏠 Local")
        self.rn_home_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #28a745;")
        self.rn_home_label.setAlignment(Qt.AlignCenter)
        rn_home_box.addWidget(self.rn_home_label)
        self.rn_pwin_home = QLabel("-")
        self.rn_pwin_home.setStyleSheet("font-weight: bold; font-size: 26px; color: #009688;")
        self.rn_pwin_home.setAlignment(Qt.AlignCenter)
        rn_home_box.addWidget(self.rn_pwin_home)
        self.rn_gap_home = QLabel("Gap: -")
        self.rn_gap_home.setStyleSheet("font-size: 11px; color: #666;")
        self.rn_gap_home.setAlignment(Qt.AlignCenter)
        rn_home_box.addWidget(self.rn_gap_home)
        self.rn_detail_home = QLabel("")
        self.rn_detail_home.setStyleSheet("font-size: 10px; color: #999;")
        self.rn_detail_home.setAlignment(Qt.AlignCenter)
        rn_home_box.addWidget(self.rn_detail_home)
        rn_main.addLayout(rn_home_box)
        
        rn_vs = QLabel("VS")
        rn_vs.setStyleSheet("font-size: 16px; font-weight: bold; color: #CCC;")
        rn_vs.setAlignment(Qt.AlignCenter)
        rn_vs.setFixedWidth(40)
        rn_main.addWidget(rn_vs)
        
        rn_away_box = QVBoxLayout()
        rn_away_box.setSpacing(2)
        self.rn_away_label = QLabel("✈️ Visitante")
        self.rn_away_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #dc3545;")
        self.rn_away_label.setAlignment(Qt.AlignCenter)
        rn_away_box.addWidget(self.rn_away_label)
        self.rn_pwin_away = QLabel("-")
        self.rn_pwin_away.setStyleSheet("font-weight: bold; font-size: 26px; color: #009688;")
        self.rn_pwin_away.setAlignment(Qt.AlignCenter)
        rn_away_box.addWidget(self.rn_pwin_away)
        self.rn_gap_away = QLabel("Gap: -")
        self.rn_gap_away.setStyleSheet("font-size: 11px; color: #666;")
        self.rn_gap_away.setAlignment(Qt.AlignCenter)
        rn_away_box.addWidget(self.rn_gap_away)
        self.rn_detail_away = QLabel("")
        self.rn_detail_away.setStyleSheet("font-size: 10px; color: #999;")
        self.rn_detail_away.setAlignment(Qt.AlignCenter)
        rn_away_box.addWidget(self.rn_detail_away)
        rn_main.addLayout(rn_away_box)
        
        rn_meta = QVBoxLayout()
        rn_meta.setSpacing(2)
        self.rn_confidence = QLabel("Confianza: -")
        self.rn_confidence.setStyleSheet("font-size: 11px; font-weight: bold; color: #666;")
        self.rn_confidence.setAlignment(Qt.AlignCenter)
        rn_meta.addWidget(self.rn_confidence)
        self.rn_draw = QLabel("P(Draw)≈ -")
        self.rn_draw.setStyleSheet("font-size: 10px; color: #999;")
        self.rn_draw.setAlignment(Qt.AlignCenter)
        rn_meta.addWidget(self.rn_draw)
        rn_main.addLayout(rn_meta)
        
        regresion_layout.addLayout(rn_main)
        
        self.rn_recommendation = QLabel("")
        self.rn_recommendation.setWordWrap(True)
        self.rn_recommendation.setStyleSheet("""
            padding: 8px;
            background: #E0F2F1;
            border-radius: 6px;
            font-size: 11px;
            color: #004D40;
            border-left: 3px solid #009688;
        """)
        self.rn_recommendation.setVisible(False)
        regresion_layout.addWidget(self.rn_recommendation)
        
        regresion_group.setLayout(regresion_layout)
        content_layout.addWidget(regresion_group)
        
        # ═══════════════════════════════════════════════════════════════════
        # PANEL: LEY DE LA FE PERDIDA
        # ═══════════════════════════════════════════════════════════════════
        fe_perdida_group = self._create_group("\u2696\ufe0f Ley de la Fe Perdida")
        fe_layout = QVBoxLayout()
        
        fe_flag_frame = QFrame()
        fe_flag_frame.setStyleSheet(
            "QFrame { background-color: #FFF8E1; border: 2px solid #E8A838;"
            " border-radius: 8px; padding: 10px; }"
        )
        fe_flag_ly = QHBoxLayout(fe_flag_frame)
        fe_flag_ly.setContentsMargins(15, 8, 15, 8)
        
        self.fe_flag_label = QLabel("-")
        self.fe_flag_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        fe_flag_ly.addWidget(self.fe_flag_label)
        
        self.fe_edge_label = QLabel("")
        self.fe_edge_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-left: 15px;")
        fe_flag_ly.addWidget(self.fe_edge_label)
        
        fe_flag_ly.addStretch()
        
        self.fe_flag_desc = QLabel("")
        self.fe_flag_desc.setStyleSheet("font-size: 11px; color: #666; font-style: italic;")
        fe_flag_ly.addWidget(self.fe_flag_desc)
        
        fe_layout.addWidget(fe_flag_frame)
        
        fe_pend = QHBoxLayout()
        fe_pend.setSpacing(20)
        
        for attr_prefix, role_icon, role_color in [
            ("fe_home", "\U0001f3e0", "#28a745"),
            ("fe_away", "\u2708\ufe0f", "#dc3545"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl = QLabel(f"{role_icon} -")
            lbl.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {role_color};")
            lbl.setAlignment(Qt.AlignCenter)
            setattr(self, f"{attr_prefix}_label", lbl)
            col.addWidget(lbl)
            
            score = QLabel("-")
            score.setStyleSheet("font-weight: bold; font-size: 22px; color: #333;")
            score.setAlignment(Qt.AlignCenter)
            setattr(self, f"{attr_prefix}_score", score)
            col.addWidget(score)
            
            zone = QLabel("")
            zone.setStyleSheet("font-size: 10px; color: #666;")
            zone.setAlignment(Qt.AlignCenter)
            setattr(self, f"{attr_prefix}_zone", zone)
            col.addWidget(zone)
            
            racha = QLabel("")
            racha.setStyleSheet("font-size: 12px; font-family: monospace;")
            racha.setAlignment(Qt.AlignCenter)
            setattr(self, f"{attr_prefix}_racha", racha)
            col.addWidget(racha)
            
            goal = QLabel("")
            goal.setStyleSheet("font-size: 10px;")
            goal.setAlignment(Qt.AlignCenter)
            setattr(self, f"{attr_prefix}_goal", goal)
            col.addWidget(goal)
            
            fe_pend.addLayout(col)
        
        gap_col = QVBoxLayout()
        gap_col.setSpacing(2)
        gap_col.addWidget(QLabel(""))
        self.fe_gap_label = QLabel("-")
        self.fe_gap_label.setStyleSheet("font-weight: bold; font-size: 20px; color: #1B2838;")
        self.fe_gap_label.setAlignment(Qt.AlignCenter)
        self.fe_gap_label.setFixedWidth(80)
        gap_col.addWidget(self.fe_gap_label)
        gap_col.addStretch()
        fe_pend.insertLayout(1, gap_col)
        
        prob_col = QVBoxLayout()
        prob_col.setSpacing(2)
        self.fe_prob_home = QLabel("-")
        self.fe_prob_home.setStyleSheet("font-weight: bold; font-size: 12px; color: #28a745;")
        self.fe_prob_home.setAlignment(Qt.AlignCenter)
        prob_col.addWidget(self.fe_prob_home)
        self.fe_prob_draw = QLabel("-")
        self.fe_prob_draw.setStyleSheet("font-weight: bold; font-size: 12px; color: #ffc107;")
        self.fe_prob_draw.setAlignment(Qt.AlignCenter)
        prob_col.addWidget(self.fe_prob_draw)
        self.fe_prob_away = QLabel("-")
        self.fe_prob_away.setStyleSheet("font-weight: bold; font-size: 12px; color: #dc3545;")
        self.fe_prob_away.setAlignment(Qt.AlignCenter)
        prob_col.addWidget(self.fe_prob_away)
        self.fe_margin = QLabel("")
        self.fe_margin.setStyleSheet("font-size: 10px; color: #666;")
        self.fe_margin.setAlignment(Qt.AlignCenter)
        prob_col.addWidget(self.fe_margin)
        fe_pend.addLayout(prob_col)
        
        fe_layout.addLayout(fe_pend)
        fe_perdida_group.setLayout(fe_layout)
        content_layout.addWidget(fe_perdida_group)

        # ═══════════════════════════════════════════════════════════════════
        # PANEL: MARCADOR
        # ═══════════════════════════════════════════════════════════════════
        marcador_group = self._create_group("âš½ Ley del Marcador")
        marcador_layout = QVBoxLayout()
        
        xg_row = QHBoxLayout()
        xg_row.setSpacing(40)
        for label_text, attr_name, color in [("λ Local", "xg_home", "#28a745"), 
                                              ("λ Visitante", "xg_away", "#dc3545"),
                                              ("λ Total", "xg_total", "#17a2b8")]:
            box = QVBoxLayout()
            box.addWidget(QLabel(label_text))
            lbl = QLabel("-")
            lbl.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {color};")
            setattr(self, attr_name, lbl)
            box.addWidget(lbl)
            xg_row.addLayout(box)
        xg_row.addStretch()
        marcador_layout.addLayout(xg_row)
        
        marcador_layout.addSpacing(10)
        
        probs_grid = QGridLayout()
        probs_grid.setHorizontalSpacing(20)
        probs_grid.setVerticalSpacing(8)
        
        probs_grid.addWidget(QLabel(""), 0, 0)
        for col, header_text in enumerate(["O0.5", "O1.5", "O2.5"], 1):
            lbl = QLabel(header_text)
            lbl.setStyleSheet("font-weight: bold; color: #666;")
            lbl.setAlignment(Qt.AlignCenter)
            probs_grid.addWidget(lbl, 0, col)
        
        home_label = QLabel("🏠 Home:")
        home_label.setStyleSheet("font-weight: bold; color: #28a745;")
        probs_grid.addWidget(home_label, 1, 0)
        
        self.home_over05 = QLabel("-")
        self.home_over15 = QLabel("-")
        self.home_over25 = QLabel("-")
        for col, lbl in enumerate([self.home_over05, self.home_over15, self.home_over25], 1):
            lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
            lbl.setAlignment(Qt.AlignCenter)
            probs_grid.addWidget(lbl, 1, col)
        
        away_label = QLabel("✈️ Away:")
        away_label.setStyleSheet("font-weight: bold; color: #dc3545;")
        probs_grid.addWidget(away_label, 2, 0)
        
        self.away_over05 = QLabel("-")
        self.away_over15 = QLabel("-")
        self.away_over25 = QLabel("-")
        for col, lbl in enumerate([self.away_over05, self.away_over15, self.away_over25], 1):
            lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
            lbl.setAlignment(Qt.AlignCenter)
            probs_grid.addWidget(lbl, 2, col)
        
        marcador_layout.addLayout(probs_grid)
        marcador_layout.addSpacing(10)
        
        total_row = QHBoxLayout()
        total_row.setSpacing(30)
        total_label = QLabel("📊 Total:")
        total_label.setStyleSheet("font-weight: bold; color: #17a2b8;")
        total_row.addWidget(total_label)
        
        for label_text, attr_name in [("O2.5", "over25"), ("O3.5", "over35"), ("BTTS", "btts")]:
            box = QHBoxLayout()
            box.setSpacing(5)
            name_lbl = QLabel(f"{label_text}=")
            name_lbl.setStyleSheet("color: #666;")
            box.addWidget(name_lbl)
            val_lbl = QLabel("-")
            val_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
            setattr(self, attr_name, val_lbl)
            box.addWidget(val_lbl)
            total_row.addLayout(box)
        
        total_row.addStretch()
        marcador_layout.addLayout(total_row)
        marcador_layout.addSpacing(10)
        
        scores_row = QHBoxLayout()
        scores_label = QLabel("🎯 Marcadores probables:")
        scores_label.setStyleSheet("font-weight: bold;")
        scores_row.addWidget(scores_label)
        self.scores_inline = QLabel("-")
        self.scores_inline.setStyleSheet("font-size: 13px;")
        scores_row.addWidget(self.scores_inline)
        scores_row.addStretch()
        marcador_layout.addLayout(scores_row)
        
        marcador_group.setLayout(marcador_layout)
        content_layout.addWidget(marcador_group)
        
        # ═══════════════════════════════════════════════════════════════════
        # PANEL: H2H — Cards + Barra de dominio (NUEVO)
        # ═══════════════════════════════════════════════════════════════════
        h2h_group = self._create_group("📜 Historial H2H")
        h2h_outer = QVBoxLayout()
        h2h_outer.setSpacing(6)

        # Contenedor dinámico (se llena en _on_h2h_finished)
        self.h2h_content = QVBoxLayout()
        self.h2h_content.setSpacing(3)

        # Placeholder
        self.h2h_placeholder = QLabel("Esperando datos…")
        self.h2h_placeholder.setAlignment(Qt.AlignCenter)
        self.h2h_placeholder.setStyleSheet("color: #aaa; font-style: italic; padding: 15px;")
        self.h2h_content.addWidget(self.h2h_placeholder)

        h2h_outer.addLayout(self.h2h_content)
        h2h_group.setLayout(h2h_outer)
        content_layout.addWidget(h2h_group)
        
        
        content_layout.addStretch()
        scroll.setWidget(self.scroll_content)
        main_layout.addWidget(scroll, 1)
        
        # ═══════════════════════════════════════════════════════════════════
        # FOOTER
        # ═══════════════════════════════════════════════════════════════════
        footer = QWidget()
        footer.setStyleSheet("background-color: #f8f9fa; border-top: 1px solid #dee2e6;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(15, 8, 15, 8)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("Listo")
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #dee2e6; border-radius: 4px;
                          text-align: center; background: #e9ecef; }
            QProgressBar::chunk { background: #17a2b8; border-radius: 3px; }
        """)
        footer_layout.addWidget(self.progress_bar)
        main_layout.addWidget(footer)
    
    # =========================================================================
    # HELPERS DE UI
    # =========================================================================
    
    def _create_group(self, title: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #dee2e6; border-radius: 6px;
                       margin-top: 10px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        """)
        return group
    
    def _create_constants_table(self) -> QTableWidget:
        table = QTableWidget()
        headers = ["Const", "↑", "↔", "↓", "Pred"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 5):
            header.setSectionResizeMode(i, QHeaderView.Fixed)
            table.setColumnWidth(i, 55)
        
        table.setMinimumHeight(240)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("""
            QTableWidget { font-size: 11px; }
            QTableWidget::item { padding: 3px; }
            QHeaderView::section {
                background-color: #343a40; color: white;
                font-weight: bold; padding: 5px; border: none;
            }
        """)
        return table
    
    def _create_table(self, headers: List[str], min_height: int) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setMinimumHeight(min_height)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("""
            QTableWidget { font-size: 11px; }
            QHeaderView::section {
                background-color: #343a40; color: white;
                font-weight: bold; padding: 5px; border: none;
            }
        """)
        return table
    
    def _create_value_label(self, color: str = None) -> QLabel:
        lbl = QLabel("-")
        style = "font-weight: bold; font-size: 13px;"
        if color:
            style += f" color: {color};"
        lbl.setStyleSheet(style)
        return lbl
    
    # =========================================================================
    # TOGGLE % ↔ CUOTAS
    # =========================================================================
    
    @staticmethod
    def _format_as_odds(prob: float) -> str:
        """Formatea probabilidad como cuota: 0.56 → '@1.79'."""
        if prob <= 0 or prob > 1:
            return "-"
        odds = max(1.0 / prob, 1.01)
        if odds >= 50:
            return f"@{odds:.0f}"
        return f"@{odds:.2f}"
    
    @staticmethod
    def _format_as_pct(prob: float) -> str:
        """Formatea probabilidad como porcentaje: 0.56 → '56%'."""
        if prob <= 0:
            return "-"
        return f"{prob * 100:.0f}%"
    
    def _fmt(self, prob: float) -> str:
        """Formato según el toggle actual: % o cuota."""
        if self._show_as_odds:
            return self._format_as_odds(prob)
        return self._format_as_pct(prob)
    
    def _fmt1(self, prob: float) -> str:
        """Formato con 1 decimal según toggle."""
        if self._show_as_odds:
            return self._format_as_odds(prob)
        return f"{prob * 100:.1f}%"
    
    def _on_odds_toggle(self, checked: bool):
        """Callback del checkbox: alterna entre % y cuotas."""
        self._show_as_odds = checked
        self._refresh_display_mode()
    
    def _refresh_display_mode(self):
        """Re-renderiza todos los valores según el modo actual (% o cuotas)."""
        rp = self._raw_probabilities
        if not rp:
            return
        
        # — ANTICULEBRA —
        if 'ac_prob_home' in rp:
            self.prob_home.setText(self._fmt1(rp['ac_prob_home']))
        if 'ac_prob_draw' in rp:
            self.prob_draw.setText(self._fmt1(rp['ac_prob_draw']))
        if 'ac_prob_away' in rp:
            self.prob_away.setText(self._fmt1(rp['ac_prob_away']))
        if 'ac_favorite_prob' in rp and 'ac_favorite_label' in rp:
            self.favorite.setText(
                f"{rp['ac_favorite_label']} ({self._fmt1(rp['ac_favorite_prob'])})"
            )
        if 'ac_prob_break' in rp:
            self.break_prob.setText(self._fmt1(rp['ac_prob_break']))
        
        # — REGRESIÓN AL NIVEL —
        if 'rn_p_home' in rp:
            self.rn_pwin_home.setText(self._fmt(rp['rn_p_home']))
        if 'rn_p_away' in rp:
            self.rn_pwin_away.setText(self._fmt(rp['rn_p_away']))
        if 'rn_p_draw' in rp and 'rn_gap_diff' in rp:
            self.rn_draw.setText(
                f"P(Draw)\u2248{self._fmt(rp['rn_p_draw'])}  |  Gap diff: {rp['rn_gap_diff']:+.2f}"
            )
        
        # — FE PERDIDA —
        if 'fe_prob_home' in rp:
            self.fe_prob_home.setText(f"1: {self._fmt(rp['fe_prob_home'])}")
        if 'fe_prob_draw' in rp:
            self.fe_prob_draw.setText(f"X: {self._fmt(rp['fe_prob_draw'])}")
        if 'fe_prob_away' in rp:
            self.fe_prob_away.setText(f"2: {self._fmt(rp['fe_prob_away'])}")
        for prefix in ['fe_home', 'fe_away']:
            gf_key = f'{prefix}_goal_flag_type'
            pct_key = f'{prefix}_scores_pct'
            if gf_key in rp and pct_key in rp:
                lbl = getattr(self, f"{prefix}_goal")
                gf = rp[gf_key]
                pct = rp[pct_key]
                if gf == 'scores':
                    lbl.setText(f"\u26bd Anota {self._fmt(pct)}")
                elif gf == 'seco':
                    lbl.setText(f"\U0001f480 Solo {self._fmt(pct)}")
        
        # — MARCADOR (POISSON) —
        poisson_labels = {
            'mc_home_o05': self.home_over05, 'mc_home_o15': self.home_over15,
            'mc_home_o25': self.home_over25,
            'mc_away_o05': self.away_over05, 'mc_away_o15': self.away_over15,
            'mc_away_o25': self.away_over25,
            'mc_total_o25': self.over25, 'mc_total_o35': self.over35,
            'mc_btts': self.btts,
        }
        for key, lbl in poisson_labels.items():
            if key in rp:
                lbl.setText(self._fmt(rp[key]))
        
        # Marcadores probables
        if 'mc_top_scores' in rp:
            top_scores = rp['mc_top_scores']
            if top_scores:
                if self._show_as_odds:
                    parts = [f"<b>{s}</b> ({self._format_as_odds(p)})" for s, p in top_scores[:4]]
                else:
                    parts = [f"<b>{s}</b> ({p*100:.0f}%)" for s, p in top_scores[:4]]
                self.scores_inline.setText(" | ".join(parts))
                self.scores_inline.setTextFormat(Qt.RichText)
        
        # — CONSTANTES K —
        for table_key in ['team_const', 'rival_const']:
            table = getattr(self, f"{table_key}_table", None)
            preds_key = f'{table_key}_predictions'
            if table and preds_key in rp:
                predictions = rp[preds_key]
                for i, (const_type, probs) in enumerate(sorted(predictions.items())):
                    if i >= table.rowCount():
                        break
                    for col, prob_key in [(1, 'incremento'), (2, 'reset'), (3, 'decremento')]:
                        prob_val = probs.get(prob_key, 0) / 100.0
                        item = table.item(i, col)
                        if item:
                            item.setText(self._fmt(prob_val))
        
    def _clear_layout(self, layout):
        """Limpia recursivamente un layout eliminando todos sus widgets."""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            sub = item.layout()
            if sub:
                self._clear_layout(sub)
    
    def _create_result_circle(self, result: str, size: int = 28, tooltip: str = "") -> QLabel:
        """
        Crea un círculo coloreado W/D/L estilo Flashscore.
        result: 'W', 'D' o 'L'
        """
        COLORS = {'W': '#43a047', 'D': '#fbc02d', 'L': '#e53935'}
        LETTERS = {'W': 'V', 'D': 'E', 'L': 'D'}
        radius = size // 2

        circle = QLabel(LETTERS.get(result, '?'))
        circle.setFixedSize(size, size)
        circle.setAlignment(Qt.AlignCenter)
        circle.setStyleSheet(f"""
            background-color: {COLORS.get(result, '#9e9e9e')};
            color: white;
            border-radius: {radius}px;
            font-weight: bold;
            font-size: {size // 3 + 1}px;
        """)
        if tooltip:
            circle.setToolTip(tooltip)
            circle.setCursor(Qt.PointingHandCursor)
        return circle
    
    def _create_h2h_card(self, match: dict, result: str, index: int) -> QFrame:
        """Crea una fila-card visual para un partido H2H."""
        bg = '#ffffff' if index % 2 == 0 else '#f8f9fa'

        card = QFrame()
        card.setFixedHeight(38)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border-radius: 6px;
                border-bottom: 1px solid #eee;
            }}
        """)
        ly = QHBoxLayout(card)
        ly.setContentsMargins(10, 4, 10, 4)
        ly.setSpacing(10)

        # Círculo resultado
        circle = self._create_result_circle(result, size=26)
        ly.addWidget(circle)

        # Fecha
        d = match['date']
        if isinstance(d, str):
            try:
                d = datetime.fromisoformat(d.replace('Z', '+00:00'))
            except:
                pass
        date_str = d.strftime('%d/%m/%y') if isinstance(d, datetime) else str(d)[:8]

        date_lbl = QLabel(date_str)
        date_lbl.setStyleSheet("color: #999; font-size: 10px; min-width: 52px;")
        ly.addWidget(date_lbl)

        # Home (alineado derecha)
        home_lbl = QLabel(match['home_name'][:20])
        home_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        home_lbl.setStyleSheet("font-size: 11px; color: #333;")
        ly.addWidget(home_lbl, 2)

        # Score destacado
        score_lbl = QLabel(f"{match['goals_home']}  -  {match['goals_away']}")
        score_lbl.setAlignment(Qt.AlignCenter)
        score_lbl.setFixedWidth(55)
        score_lbl.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            color: #1a1a2e;
            background-color: #e8eaf6;
            border-radius: 4px;
            padding: 2px 0;
        """)
        ly.addWidget(score_lbl)

        # Away (alineado izquierda)
        away_lbl = QLabel(match['away_name'][:20])
        away_lbl.setStyleSheet("font-size: 11px; color: #333;")
        ly.addWidget(away_lbl, 2)

        # Liga
        league = (match.get('league_name') or '').strip()
        if league:
            league_lbl = QLabel(league[:12])
            league_lbl.setStyleSheet("color: #bbb; font-size: 9px;")
            league_lbl.setFixedWidth(55)
            league_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            ly.addWidget(league_lbl)

        return card
    
    def _populate_form_column(self, circles_layout, summary_label,
                              details_layout, next_layout,
                              last_matches: list, next_matches: list):
        """
        Llena una columna de Forma con:
          • Círculos W/D/L (con tooltip al hover)
          • Resumen de puntos
          • Detalle compacto de cada partido
          • Próximos partidos
        """
        self._clear_layout(circles_layout)
        self._clear_layout(details_layout)
        self._clear_layout(next_layout)

        if not last_matches:
            summary_label.setText("Sin datos")
            return

        # ── Círculos ──
        wins, draws, losses = 0, 0, 0
        for m in last_matches:
            r = m['result']
            if r == 'W':
                wins += 1
            elif r == 'D':
                draws += 1
            else:
                losses += 1

            venue = "🏠" if m['is_home'] else "✈️"
            d = m.get('date', '')
            if isinstance(d, str):
                try:
                    d = datetime.fromisoformat(d.replace('Z', '+00:00'))
                except:
                    pass
            date_tip = d.strftime('%d/%m/%y') if isinstance(d, datetime) else ''

            tooltip = f"{venue} vs {m['opponent']} ({m['goals_for']}-{m['goals_against']})  {date_tip}"
            circle = self._create_result_circle(r, size=28, tooltip=tooltip)
            circles_layout.addWidget(circle)

        circles_layout.addStretch()

        # ── Resumen ──
        total_pts = wins * 3 + draws
        max_pts = len(last_matches) * 3
        summary_label.setText(
            f"<span style='color:#43a047;font-weight:bold;'>{wins}V</span> "
            f"<span style='color:#fbc02d;font-weight:bold;'>{draws}E</span> "
            f"<span style='color:#e53935;font-weight:bold;'>{losses}D</span>"
            f"  •  <b>{total_pts}/{max_pts} pts</b>"
        )
        summary_label.setTextFormat(Qt.RichText)

        # ── Detalle de cada partido ──
        for m in last_matches:
            row = QFrame()
            row.setFixedHeight(24)
            row.setStyleSheet("background: transparent;")
            row_ly = QHBoxLayout(row)
            row_ly.setContentsMargins(4, 2, 4, 2)
            row_ly.setSpacing(6)

            # Letra resultado
            r_colors = {'W': '#43a047', 'D': '#fbc02d', 'L': '#e53935'}
            r_letters = {'W': 'V', 'D': 'E', 'L': 'D'}
            r_lbl = QLabel(r_letters.get(m['result'], '?'))
            r_lbl.setStyleSheet(
                f"color: {r_colors.get(m['result'], '#999')}; "
                f"font-weight: bold; font-size: 11px;"
            )
            r_lbl.setFixedWidth(14)
            row_ly.addWidget(r_lbl)

            # Sede
            venue_lbl = QLabel("🏠" if m['is_home'] else "✈️")
            venue_lbl.setFixedWidth(18)
            venue_lbl.setStyleSheet("font-size: 11px;")
            row_ly.addWidget(venue_lbl)

            # Rival + score
            text_lbl = QLabel(f"vs {m['opponent'][:14]} ({m['goals_for']}-{m['goals_against']})")
            text_lbl.setStyleSheet("font-size: 10px; color: #555;")
            row_ly.addWidget(text_lbl, 1)

            # Fecha
            d = m.get('date', '')
            if isinstance(d, str):
                try:
                    d = datetime.fromisoformat(d.replace('Z', '+00:00'))
                except:
                    pass
            date_str = d.strftime('%d/%m') if isinstance(d, datetime) else ''
            date_lbl = QLabel(date_str)
            date_lbl.setStyleSheet("font-size: 9px; color: #aaa;")
            date_lbl.setFixedWidth(35)
            row_ly.addWidget(date_lbl)

            details_layout.addWidget(row)

        # ── Próximos partidos ──
        for m in next_matches:
            row = QHBoxLayout()
            row.setSpacing(6)

            venue = "🏠" if m['is_home'] else "✈️"
            text_lbl = QLabel(f"{venue} vs {m['opponent'][:15]}")
            text_lbl.setStyleSheet("font-size: 10px; color: #555;")
            row.addWidget(text_lbl)

            # Nivel del rival (desde levels.db)
            opp_level = m.get('opponent_level')
            if opp_level is not None:
                # Color según nivel: rojo=rival fuerte, verde=rival débil
                if opp_level >= 70:
                    lvl_color = '#c62828'    # Rojo fuerte = rival fuerte
                elif opp_level >= 50:
                    lvl_color = '#ef6c00'    # Naranja = rival medio-alto
                elif opp_level >= 30:
                    lvl_color = '#f9a825'    # Amarillo = rival medio
                else:
                    lvl_color = '#2e7d32'    # Verde = rival débil
                
                level_lbl = QLabel(f"Nv {opp_level:.1f}")
                level_lbl.setStyleSheet(
                    f"font-size: 9px; color: white; background: {lvl_color}; "
                    f"border-radius: 3px; padding: 1px 4px; font-weight: bold;"
                )
                level_lbl.setFixedWidth(48)
                level_lbl.setAlignment(Qt.AlignCenter)
                level_lbl.setToolTip(f"Nivel del rival: {opp_level:.2f}")
                row.addWidget(level_lbl)

            d = m.get('date', '')
            if isinstance(d, str):
                try:
                    d = datetime.fromisoformat(d.replace('Z', '+00:00'))
                except:
                    pass
            date_str = d.strftime('%d/%m %H:%M') if isinstance(d, datetime) else str(d)[:10]
            date_lbl = QLabel(date_str)
            date_lbl.setStyleSheet("font-size: 10px; color: #0097a7; font-weight: bold;")
            row.addWidget(date_lbl)
            row.addStretch()

            next_layout.addLayout(row)
    
    # =========================================================================
    # CARGA DE EQUIPOS / ANÁLISIS
    # =========================================================================
    
    def _load_teams(self):
        try:
            query = text("""
                SELECT DISTINCT t.id, t.name FROM teams t
                JOIN fixtures f ON (f.home_team_id = t.id OR f.away_team_id = t.id)
                WHERE t.name IS NOT NULL AND t.name != '' ORDER BY t.name
            """)
            with self.sad_engine.connect() as conn:
                results = conn.execute(query).fetchall()
            
            self.teams_data = [(r.id, r.name) for r in results]
            self.team_combo.clear()
            for team_id, team_name in self.teams_data:
                self.team_combo.addItem(team_name, team_id)
            
            completer = QCompleter([t[1] for t in self.teams_data])
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            self.team_combo.setCompleter(completer)
            
            logger.info(f"Cargados {len(self.teams_data)} equipos")
        except Exception as e:
            logger.error(f"Error cargando equipos: {e}")
    
    def _on_analyze_clicked(self):
        team_id = self.team_combo.currentData()
        if not team_id:
            QMessageBox.warning(self, "Error", "Selecciona un equipo")
            return
        
        self.analyze_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Buscando partido...")
        self._find_next_match(team_id)
    
    def _find_next_match(self, team_id: int):
        try:
            from utils.ml_data_collector import MLDataCollector
            with MLDataCollector() as collector:
                fixture = collector.get_next_fixture(team_id)
            
            if not fixture:
                QMessageBox.information(self, "Info", "No hay próximo partido")
                self.analyze_btn.setEnabled(True)
                self.progress_bar.setFormat("Listo")
                return
            
            self.current_fixture = fixture
            self._update_match_info(fixture, team_id)
            self._start_analysis(fixture, team_id)
            
            self.bubbles_btn.setEnabled(BUBBLES_AVAILABLE)
            self.sad_dashboard_btn.setEnabled(SAD_DASHBOARD_AVAILABLE)
            self.k_scoreline_btn.setEnabled(K_SCORELINE_AVAILABLE)
            self.export_team_btn.setEnabled(True)
            self.export_rival_btn.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.analyze_btn.setEnabled(True)
    
    def _update_match_info(self, fixture: Dict, team_id: int):
        home = fixture['home_team_name']
        away = fixture['away_team_name']
        
        date = fixture['date']
        if isinstance(date, str):
            try:
                date = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except:
                pass
        date_str = date.strftime('%d/%m/%Y %H:%M') if isinstance(date, datetime) else str(date)
        
        league = self._get_league_name(fixture['league_id'])
        
        self.match_title.setText(f"🏟️ {home}  vs  {away}")
        self.match_details.setText(f"📅 {date_str}  |  🏆 {league}")
        
        if fixture['is_home']:
            self.team_const_label.setText(f"🏠 {home} (Local)")
            self.rival_const_label.setText(f"✈️ {away} (Visitante)")
        else:
            self.team_const_label.setText(f"✈️ {away} (Visitante)")
            self.rival_const_label.setText(f"🏠 {home} (Local)")
    
    # =========================================================================
    # BURBUJAS (Constantes K)
    # =========================================================================
    def _open_bubbles(self):
        """Abre ventanas de evolución de constantes K para ambos equipos."""
        if not self.current_fixture:
            QMessageBox.information(self, "Info", "Primero analiza un partido")
            return
        
        if not BUBBLES_AVAILABLE:
            QMessageBox.warning(self, "No disponible",
                                "El módulo de burbujas (UltraFastConstantsWindow) no está disponible.\n"
                                "Verifica que ultra_fast_constants_window.py esté accesible.")
            return
        
        home_id = self.current_fixture.get('home_team_id')
        away_id = self.current_fixture.get('away_team_id')
        home_name = self.current_fixture.get('home_team_name', 'Local')
        away_name = self.current_fixture.get('away_team_name', 'Visitante')
        
        try:
            # Ventana del equipo local
            self._bubbles_home = UltraFastConstantsWindow(self, home_id)
            self._bubbles_home.setWindowTitle(f"📊 Burbujas K — 🏠 {home_name}")
            
            # Ventana del equipo visitante
            self._bubbles_away = UltraFastConstantsWindow(self, away_id)
            self._bubbles_away.setWindowTitle(f"📊 Burbujas K — ✈️ {away_name}")
            
            # Posicionar lado a lado si hay espacio
            screen = QApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                w = geom.width() // 2
                h = int(geom.height() * 0.85)
                
                self._bubbles_home.resize(w, h)
                self._bubbles_home.move(geom.x(), geom.y() + 30)
                
                self._bubbles_away.resize(w, h)
                self._bubbles_away.move(geom.x() + w, geom.y() + 30)
            
            self._bubbles_home.show()
            self._bubbles_away.show()
            
            logger.info(f"Burbujas abiertas: {home_name} (ID:{home_id}) vs {away_name} (ID:{away_id})")
            
        except Exception as e:
            logger.error(f"Error abriendo burbujas: {e}")
            QMessageBox.critical(self, "Error", f"No se pudieron abrir las burbujas:\n{e}")
    
    # =========================================================================
    # SAD DASHBOARD (Fase 1 Extracción)
    # =========================================================================
    
    def _open_sad_dashboard(self):
        """Abre el SAD Dashboard con datos del partido actual."""
        if not self.current_fixture:
            QMessageBox.information(self, "Info", "Primero analiza un partido")
            return
        
        if not SAD_DASHBOARD_AVAILABLE:
            QMessageBox.warning(
                self, "No disponible",
                "El módulo SAD Dashboard no está disponible.\n"
                "Verifica que sad_dashboard_window.py y sad_dashboard_loader.py\n"
                "estén accesibles y que PySide6-WebEngineWidgets esté instalado."
            )
            return
        
        home_id = self.current_fixture.get('home_team_id')
        away_id = self.current_fixture.get('away_team_id')
        home_name = self.current_fixture.get('home_team_name', 'Local')
        away_name = self.current_fixture.get('away_team_name', 'Visitante')
        
        # Construir match_info descriptivo
        date = self.current_fixture.get('date')
        if isinstance(date, datetime):
            date_str = date.strftime('%d/%m/%Y %H:%M')
        elif isinstance(date, str):
            date_str = date[:16]
        else:
            date_str = ''
        
        league_id = self.current_fixture.get('league_id')
        league_name = self._get_league_name(league_id) if league_id else ''
        
        match_info = f"{league_name} · {date_str}".strip(' ·')
        
        try:
            self._sad_dashboard = SADDashboardWindow.from_db(
                home_team_id=home_id,
                away_team_id=away_id,
                match_info=match_info,
                team_predictions=getattr(self, '_stored_team_predictions', None),
                rival_predictions=getattr(self, '_stored_rival_predictions', None),
                parent=None,  # ventana independiente
            )
            self._sad_dashboard.show()
            
            logger.info(
                f"SAD Dashboard abierto: {home_name} (ID:{home_id}) "
                f"vs {away_name} (ID:{away_id})"
            )
            
        except Exception as e:
            logger.error(f"Error abriendo SAD Dashboard: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self, "Error",
                f"No se pudo abrir el SAD Dashboard:\n{e}\n\n"
                f"Verifica que sad.db y constants.db existan en la raíz del proyecto."
            )
    
    # =========================================================================
    # MARCADOR POR K (Dixon-Coles)
    # =========================================================================
    
    def _open_k_scoreline(self):
        """Abre la ventana de predicción de marcadores por constantes K."""
        if not self.current_fixture:
            QMessageBox.information(self, "Info", "Primero analiza un partido")
            return
        
        if not K_SCORELINE_AVAILABLE:
            QMessageBox.warning(
                self, "No disponible",
                "El módulo de Marcador por K (KScorelineWindow) no está disponible.\n"
                "Verifica que k_scoreline_window.py y k_scoreline_engine.py estén accesibles."
            )
            return
        
        home_id = self.current_fixture.get('home_team_id')
        away_id = self.current_fixture.get('away_team_id')
        home_name = self.current_fixture.get('home_team_name', 'Local')
        away_name = self.current_fixture.get('away_team_name', 'Visitante')
        
        try:
            # Resolver rutas de DB
            project_root = find_project_root()
            constants_db = os.path.join(project_root, 'constants.db')
            sad_db = os.path.join(project_root, 'sad.db')
            levels_db = os.path.join(project_root, 'levels.db')
            
            self._k_scoreline_window = KScorelineWindow(
                constants_db=constants_db,
                sad_db=sad_db,
                levels_db=levels_db if os.path.exists(levels_db) else None,
                parent=None,
            )
            
            # Pre-seleccionar los equipos del partido actual
            home_idx = self._k_scoreline_window.combo_home.findData(home_id)
            if home_idx >= 0:
                self._k_scoreline_window.combo_home.setCurrentIndex(home_idx)
            
            away_idx = self._k_scoreline_window.combo_away.findData(away_id)
            if away_idx >= 0:
                self._k_scoreline_window.combo_away.setCurrentIndex(away_idx)
            
            self._k_scoreline_window.show()
            
            logger.info(
                f"Marcador K abierto: {home_name} (ID:{home_id}) "
                f"vs {away_name} (ID:{away_id})"
            )
            
        except Exception as e:
            logger.error(f"Error abriendo Marcador K: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self, "Error",
                f"No se pudo abrir el predictor de Marcador K:\n{e}\n\n"
                f"Verifica que constants.db y sad.db existan en la raíz del proyecto."
            )
    
    # =========================================================================
    # EXPORTAR BURBUJAS (gráficos + CSV)
    # =========================================================================
    
    def _capture_full_screenshot(self, output_path: str) -> bool:
        """
        Captura un screenshot completo del scroll_content (todo el análisis,
        no solo la parte visible en pantalla) y lo guarda como PNG.
        """
        try:
            widget = self.scroll_content

            # Forzar layout para obtener el tamaño real completo
            widget.updateGeometry()
            QApplication.processEvents()

            # Tamaño completo del contenido (no solo lo visible)
            full_size = widget.sizeHint()
            if full_size.width() < 100 or full_size.height() < 100:
                full_size = widget.size()

            width = max(full_size.width(), 900)
            height = max(full_size.height(), 600)

            # Redimensionar temporalmente al tamaño completo
            original_size = widget.size()
            widget.resize(width, height)
            widget.updateGeometry()
            QApplication.processEvents()

            # Capturar con grab() que renderiza todo el widget
            pixmap = widget.grab()

            # Restaurar tamaño original
            widget.resize(original_size)
            QApplication.processEvents()

            saved = pixmap.save(output_path, "PNG")

            if saved:
                logger.info(f"Screenshot guardado: {output_path} ({pixmap.width()}x{pixmap.height()})")
            else:
                logger.error(f"No se pudo guardar screenshot en: {output_path}")

            return saved

        except Exception as e:
            logger.error(f"Error capturando screenshot: {e}")
            return False

    def _build_screenshot_filename(self) -> str:
        """
        Genera un nombre de archivo seguro para el screenshot basado en
        el nombre del partido y la fecha.
        Ejemplo: 'Barcelona vs Real Madrid - 2026-02-15.png'
        """
        if not self.current_fixture:
            return "analisis_pre_partido.png"

        home = self.current_fixture.get('home_team_name', 'Local')
        away = self.current_fixture.get('away_team_name', 'Visitante')

        match_date = self.current_fixture.get('date')
        if isinstance(match_date, datetime):
            date_str = match_date.strftime('%Y-%m-%d')
        elif isinstance(match_date, str):
            try:
                dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d')
            except:
                date_str = match_date[:10]
        else:
            date_str = datetime.now().strftime('%Y-%m-%d')

        raw_name = f"{home} vs {away} - {date_str}.png"
        safe_name = re.sub(r'[<>:"/\\|?*]', '', raw_name)
        safe_name = safe_name.strip('. ')

        return safe_name if safe_name else "analisis_pre_partido.png"

    def _export_bubbles(self, role: str):
        """
        Exporta gráficos y CSV de constantes K para el equipo indicado,
        además de un screenshot completo del análisis pre-partido.

        Args:
            role: 'home' para el equipo local, 'away' para el visitante
        """
        if not self.current_fixture:
            QMessageBox.information(self, "Info", "Primero analiza un partido")
            return

        if role == 'home':
            team_id = self.current_fixture.get('home_team_id')
            team_name = self.current_fixture.get('home_team_name', 'Local')
            btn = self.export_team_btn
        else:
            team_id = self.current_fixture.get('away_team_id')
            team_name = self.current_fixture.get('away_team_name', 'Visitante')
            btn = self.export_rival_btn

        if not team_id:
            QMessageBox.warning(self, "Error", "No se pudo identificar el equipo")
            return

        # Pedir carpeta de destino
        output_dir = QFileDialog.getExistingDirectory(
            self,
            f"Seleccionar carpeta de destino para {team_name}",
            os.path.expanduser("~"),
            QFileDialog.ShowDirsOnly,
        )

        if not output_dir:
            return  # Usuario canceló

        # Deshabilitar botón mientras exporta
        btn.setEnabled(False)
        btn.setText("⏳ Exportando...")
        self.progress_bar.setFormat(f"Exportando burbujas de {team_name}...")
        self.progress_bar.setValue(0)

        # ═══════════════════════════════════════════════════════════
        # SCREENSHOT COMPLETO del análisis (en main thread, síncrono)
        # ═══════════════════════════════════════════════════════════
        screenshot_filename = self._build_screenshot_filename()
        screenshot_path = os.path.join(output_dir, screenshot_filename)

        self.progress_bar.setFormat("📸 Capturando screenshot del análisis...")
        self.progress_bar.setValue(2)
        QApplication.processEvents()

        screenshot_ok = self._capture_full_screenshot(screenshot_path)

        # Guardar la ruta para reportarla al final
        self._last_screenshot_path = screenshot_path if screenshot_ok else None

        # ═══════════════════════════════════════════════════════════
        # BURBUJAS (gráficos K + CSV) en background worker
        # ═══════════════════════════════════════════════════════════
        worker = BubbleExporterWorker(team_id, output_dir, self.project_root)
        worker.progress.connect(lambda msg, pct: self._on_export_progress(msg, pct))
        worker.finished.connect(lambda res: self._on_export_finished(res, role, btn))
        worker.error.connect(lambda err: self._on_export_error(err, role, btn))

        # Guardar referencia para evitar garbage collection
        setattr(self, f'_export_worker_{role}', worker)
        worker.start()

    def _on_export_progress(self, message: str, percent: int):
        """Actualiza la barra de progreso durante la exportación."""
        self.progress_bar.setFormat(message)
        self.progress_bar.setValue(percent)
    
    def _on_export_finished(self, results: dict, role: str, btn: QPushButton):
        """Maneja el fin exitoso de la exportación (burbujas + screenshot)."""
        btn.setEnabled(True)
        btn.setText("📤 Exportar Burbujas")
        self.progress_bar.setFormat("✅ Exportación completa")
        self.progress_bar.setValue(100)

        charts = results.get('charts', {})
        total = charts.get('total_charts', 0)
        csv_path = results.get('csv_path', '')
        output_dir = charts.get('output_dir', '')
        team_name = charts.get('team_name', '?')

        # Info del screenshot
        screenshot_path = getattr(self, '_last_screenshot_path', None)
        screenshot_name = os.path.basename(screenshot_path) if screenshot_path else None

        msg = (f"Exportación de {team_name} completada:\n\n"
               f"📊 {total} gráficos generados\n"
               f"📋 CSV histórico: {'Sí' if csv_path else 'No'}\n"
               f"📸 Screenshot: {screenshot_name if screenshot_name else 'No generado'}\n"
               f"📁 Carpeta: {output_dir}")

        reply = QMessageBox.information(
            self, "✅ Exportación Completa", msg,
            QMessageBox.Open | QMessageBox.Ok,
            QMessageBox.Open,
        )

        # Abrir carpeta si el usuario lo pide
        if reply == QMessageBox.Open and output_dir:
            self._open_folder(output_dir)

    def _on_export_error(self, error_msg: str, role: str, btn: QPushButton):
        """Maneja errores de exportación."""
        btn.setEnabled(True)
        btn.setText("📤 Exportar Burbujas")
        self.progress_bar.setFormat("❌ Error en exportación")
        self.progress_bar.setValue(0)
        
        QMessageBox.critical(
            self, "Error de Exportación",
            f"No se pudo exportar las burbujas:\n\n{error_msg}"
        )
    
    @staticmethod
    def _open_folder(path: str):
        """Abre una carpeta en el explorador de archivos del sistema."""
        import subprocess
        import platform
        
        try:
            system = platform.system()
            if system == 'Windows':
                os.startfile(path)
            elif system == 'Darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            logger.warning(f"No se pudo abrir la carpeta {path}: {e}")
    
    def _get_league_name(self, league_id: int) -> str:
        try:
            with self.sad_engine.connect() as conn:
                r = conn.execute(text("SELECT name FROM leagues WHERE id = :lid"), {'lid': league_id}).fetchone()
            return r.name if r else f"Liga {league_id}"
        except:
            return f"Liga {league_id}"
    
    def _start_analysis(self, fixture: Dict, team_id: int):
        self.progress_bar.setFormat("Analizando...")
        self.progress_bar.setValue(5)
        self.pending_workers = self.TOTAL_WORKERS
        
        # ═══════════════════════════════════════════════════════════════════
        # FIX 1: Resetear odds entre análisis para evitar datos stale
        # ═══════════════════════════════════════════════════════════════════
        self.loaded_odds_data = {}
        self._current_odds_map = {}
        self._raw_probabilities = {}
        self._raw_odds_bookmaker = {}
        self._form_results_home = []
        self._form_results_away = []
        logger.info("Odds data reseteada para nuevo análisis")
        
        home_id = fixture.get('home_team_id', team_id if fixture['is_home'] else fixture['rival_id'])
        away_id = fixture.get('away_team_id', fixture['rival_id'] if fixture['is_home'] else team_id)
        home_name = fixture.get('home_team_name', '')
        away_name = fixture.get('away_team_name', '')
        
        # Guardar nombres para H2H
        self._h2h_home_name = home_name
        self._h2h_away_name = away_name
        
        # Actualizar títulos de forma con nombres de equipos
        self.home_form_title.setText(f"🏠 {home_name}")
        self.away_form_title.setText(f"✈️ {away_name}")
        self.prev_odds_home_title.setText(f"🏠 {home_name}")
        self.prev_odds_away_title.setText(f"✈️ {away_name}")
        
        # Actualizar labels de Regresión al Nivel
        self.rn_home_label.setText(f"🏠 {home_name}")
        self.rn_away_label.setText(f"✈️ {away_name}")
        
        date = fixture['date']
        if isinstance(date, str):
            try:
                date = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except:
                date = datetime.now()
        
        league_id = fixture['league_id']
        fixture_id = fixture.get('fixture_id', 0)
        
        model_mode = ['auto', 'global', 'league'][self.model_btn_group.checkedId()]
        
        # 1. Worker de Constantes
        self.constants_worker = ConstantsWorker(team_id, fixture['rival_id'], fixture['is_home'],
                                                league_id, date, model_mode)
        self.constants_worker.finished.connect(self._on_constants_finished)
        self.constants_worker.error.connect(self._on_constants_error)
        self.constants_worker.start()
        
        # 2. Worker de Anticulebra
        self.anticulebra_worker = AnticulebrasWorker(
            home_id, away_id, date, league_id, fixture_id,
            home_team_name=home_name, away_team_name=away_name
        )
        self.anticulebra_worker.finished.connect(self._on_anticulebra_finished)
        self.anticulebra_worker.error.connect(self._on_anticulebra_error)
        self.anticulebra_worker.start()
        
        # 3. Worker de Marcador
        self.marcador_worker = MarcadorWorker(home_id, away_id, date, self.project_root)
        self.marcador_worker.finished.connect(self._on_marcador_finished)
        self.marcador_worker.error.connect(self._on_marcador_error)
        self.marcador_worker.start()
        
        # 4. Worker de H2H
        self.h2h_worker = H2HWorker(home_id, away_id, self.sad_engine)
        self.h2h_worker.finished.connect(self._on_h2h_finished)
        self.h2h_worker.error.connect(self._on_h2h_error)
        self.h2h_worker.start()
        
        # 5. Worker de Odds
        self.odds_worker = OddsWorker(fixture_id, self.sad_engine)
        self.odds_worker.finished.connect(self._on_odds_finished)
        self.odds_worker.error.connect(self._on_odds_error)
        self.odds_worker.start()
        
        # 6. Worker de Forma Home
        levels_db_path = os.path.join(self.project_root, 'levels.db')
        self.home_form_worker = TeamFormWorker(home_id, home_name, self.sad_engine, date,
                                               levels_db_path=levels_db_path)
        self.home_form_worker.finished.connect(self._on_home_form_finished)
        self.home_form_worker.error.connect(self._on_form_error)
        self.home_form_worker.start()
        
        # 7. Worker de Forma Away
        self.away_form_worker = TeamFormWorker(away_id, away_name, self.sad_engine, date,
                                               levels_db_path=levels_db_path)
        self.away_form_worker.finished.connect(self._on_away_form_finished)
        self.away_form_worker.error.connect(self._on_form_error)
        self.away_form_worker.start()
        
        # 8. Worker de Regresión al Nivel
        season = fixture.get('league_season')
        if season is None:
            try:
                with self.sad_engine.connect() as conn:
                    r = conn.execute(text(
                        "SELECT league_season FROM fixtures WHERE id = :fid"
                    ), {'fid': fixture_id}).fetchone()
                    season = r[0] if r else date.year
            except:
                season = date.year if isinstance(date, datetime) else datetime.now().year
        
        self.regresion_worker = RegresionNivelWorker(home_id, away_id, league_id, season, date,
                                                      project_root=self.project_root)
        self.regresion_worker.finished.connect(self._on_regresion_finished)
        self.regresion_worker.error.connect(self._on_regresion_error)
        self.regresion_worker.start()

        # 9. Worker de Fe Perdida
        self.fe_perdida_worker = FePerdidaWorker(
            home_id, away_id, league_id, fixture_id, date,
            project_root=self.project_root
        )
        self.fe_perdida_worker.finished.connect(self._on_fe_perdida_finished)
        self.fe_perdida_worker.error.connect(self._on_fe_perdida_error)
        self.fe_perdida_worker.start()

        # 10. Worker de Odds de Rivales Anteriores
        self.prev_odds_worker = PreviousOddsWorker(
            home_id, away_id, home_name, away_name,
            self.sad_engine, date
        )
        self.prev_odds_worker.finished.connect(self._on_prev_odds_finished)
        self.prev_odds_worker.error.connect(self._on_prev_odds_error)
        self.prev_odds_worker.start()
    
    def _worker_done(self):
        self.pending_workers -= 1
        self.progress_bar.setValue(int((self.TOTAL_WORKERS - self.pending_workers) / self.TOTAL_WORKERS * 100))
        if self.pending_workers <= 0:
            self.progress_bar.setFormat("✅ Completo")
            self.analyze_btn.setEnabled(True)
    
    # =========================================================================
    # HANDLERS: CONSTANTES
    # =========================================================================
    
    def _populate_constants_table(self, table: QTableWidget, predictions: Dict, models: Dict):
        def friendly_name(const: str) -> str:
            name = const.replace('k_', '') if const != 'k' else 'k'
            return name.replace('_', ' ')
        
        table.setRowCount(len(predictions))
        
        for i, (const_type, probs) in enumerate(sorted(predictions.items())):
            name_item = QTableWidgetItem(friendly_name(const_type))
            table.setItem(i, 0, name_item)
            
            incr = probs.get('incremento', 0)
            incr_val = incr / 100.0
            incr_item = QTableWidgetItem(self._fmt(incr_val))
            incr_item.setTextAlignment(Qt.AlignCenter)
            if incr >= 50:
                incr_item.setForeground(QBrush(QColor(40, 167, 69)))
                incr_item.setFont(QFont("", -1, QFont.Bold))
            table.setItem(i, 1, incr_item)
            
            reset = probs.get('reset', 0)
            reset_val = reset / 100.0
            reset_item = QTableWidgetItem(self._fmt(reset_val))
            reset_item.setTextAlignment(Qt.AlignCenter)
            if reset >= 50:
                reset_item.setForeground(QBrush(QColor(255, 193, 7)))
                reset_item.setFont(QFont("", -1, QFont.Bold))
            table.setItem(i, 2, reset_item)
            
            decr = probs.get('decremento', 0)
            decr_val = decr / 100.0
            decr_item = QTableWidgetItem(self._fmt(decr_val))
            decr_item.setTextAlignment(Qt.AlignCenter)
            if decr >= 50:
                decr_item.setForeground(QBrush(QColor(220, 53, 69)))
                decr_item.setFont(QFont("", -1, QFont.Bold))
            table.setItem(i, 3, decr_item)
            
            pred_label = get_prediction_label(probs)
            pred_item = QTableWidgetItem(pred_label)
            pred_item.setTextAlignment(Qt.AlignCenter)
            pred_item.setFont(QFont("", -1, QFont.Bold))
            pred_color = get_prediction_color(pred_label)
            pred_item.setForeground(QBrush(pred_color))
            table.setItem(i, 4, pred_item)
    
    def _on_constants_finished(self, data: Dict):
        # Almacenar raw para toggle
        self._raw_probabilities['team_const_predictions'] = data['team_predictions']
        self._raw_probabilities['rival_const_predictions'] = data['rival_predictions']
        
        self._populate_constants_table(self.team_const_table, data['team_predictions'], data['team_models'])
        self._populate_constants_table(self.rival_const_table, data['rival_predictions'], data['rival_models'])
        
        # Guardar predicciones para el SAD Dashboard (Resumen K)
        self._stored_team_predictions = data['team_predictions']
        self._stored_rival_predictions = data['rival_predictions']
        
        self._worker_done()
    
    def _on_constants_error(self, e: str):
        self.team_const_table.setRowCount(1)
        self.team_const_table.setItem(0, 0, QTableWidgetItem(f"Error: {e[:40]}"))
        self._worker_done()
    
    # =========================================================================
    # HANDLERS: ANTICULEBRA
    # =========================================================================
    
    def _on_anticulebra_finished(self, d: Dict):
        # Almacenar raw para toggle
        self._raw_probabilities['ac_prob_home'] = d['prob_home']
        self._raw_probabilities['ac_prob_draw'] = d['prob_draw']
        self._raw_probabilities['ac_prob_away'] = d['prob_away']
        self._raw_probabilities['ac_favorite_prob'] = d['favorite_prob']
        self._raw_probabilities['ac_prob_break'] = d['prob_break_total']
        fav_label = {'home': '1 (Local)', 'away': '2 (Visita)', 'draw': 'X'}.get(d['favorite'], '-')
        self._raw_probabilities['ac_favorite_label'] = fav_label
        
        self.icf_home.setText(f"{d['icf_home']:.2f}")
        self.icf_away.setText(f"{d['icf_away']:.2f}")
        self.icf_diff.setText(f"{d['icf_diff']:.2f}")
        self.prob_home.setText(self._fmt1(d['prob_home']))
        self.prob_draw.setText(self._fmt1(d['prob_draw']))
        self.prob_away.setText(self._fmt1(d['prob_away']))
        self.favorite.setText(f"{fav_label} ({self._fmt1(d['favorite_prob'])})")
        self.break_prob.setText(self._fmt1(d['prob_break_total']))
        
        ml_score = d.get('ml_score', 0)
        ml_type = d.get('ml_type', 'unknown')
        favorite = d.get('favorite', 'none')
        favorite_prob = d.get('favorite_prob', 0)
        
        self.ml_score_label.setText(f"{ml_score:.2f}")
        
        # FIX: Verificar si hay un favorito claro ANTES de recomendar
        has_clear_favorite = favorite != 'none' and favorite_prob >= 0.40
        
        if not has_clear_favorite:
            color = "#ffc107"
            recommendation = "⚖️ Partido parejo - Sin favorito claro"
            self.ml_score_label.setStyleSheet(
                f"font-weight: bold; font-size: 20px; color: {color};"
            )
        elif ml_score < 0.10:
            color = "#28a745"
            recommendation = "✅ APOSTAR - Favorito seguro"
            self.ml_score_label.setStyleSheet(
                f"font-weight: bold; font-size: 20px; color: {color};"
            )
        elif ml_score < 0.30:
            color = "#7cb342"
            recommendation = "✅ Apostar con confianza"
            self.ml_score_label.setStyleSheet(
                f"font-weight: bold; font-size: 20px; color: {color};"
            )
        elif ml_score < 0.50:
            color = "#ffc107"
            recommendation = "⚠️ Zona gris - Evaluar"
            self.ml_score_label.setStyleSheet(
                f"font-weight: bold; font-size: 20px; color: {color};"
            )
        else:
            color = "#dc3545"
            recommendation = "❌ NO APOSTAR - Alto riesgo"
            self.ml_score_label.setStyleSheet(
                f"font-weight: bold; font-size: 20px; color: {color};"
            )
        
        self.ml_recommendation.setText(recommendation)
        self.ml_recommendation.setStyleSheet(
            f"font-size: 13px; margin-left: 20px; color: {color}; font-weight: bold;"
        )
        
        type_display = {'draw': '(Empate)', 'underdog': '(Underdog)', 'unknown': ''}.get(ml_type, '')
        self.ml_type_label.setText(f"Tipo: {type_display}" if type_display else "")
        
        self._worker_done()
    
    def _on_anticulebra_error(self, e: str):
        self.icf_home.setText("Error")
        self.ml_score_label.setText("-")
        self.ml_recommendation.setText(f"Error: {e[:40]}")
        self._worker_done()
    
    # =========================================================================
    # HANDLERS: REGRESIÓN AL NIVEL
    # =========================================================================
    
    def _on_regresion_finished(self, d: Dict):
        p_h = d['p_home_win']
        p_a = d['p_away_win']
        
        # Almacenar raw para toggle
        self._raw_probabilities['rn_p_home'] = p_h
        self._raw_probabilities['rn_p_away'] = p_a
        self._raw_probabilities['rn_p_draw'] = d['p_draw_approx']
        self._raw_probabilities['rn_gap_diff'] = d['gap_diff']
        
        def pwin_color(p):
            if p > 0.55:
                return "#27AE60"
            elif p > 0.40:
                return "#F39C12"
            else:
                return "#E74C3C"
        
        self.rn_pwin_home.setText(self._fmt(p_h))
        self.rn_pwin_home.setStyleSheet(f"font-weight: bold; font-size: 26px; color: {pwin_color(p_h)};")
        
        self.rn_pwin_away.setText(self._fmt(p_a))
        self.rn_pwin_away.setStyleSheet(f"font-weight: bold; font-size: 26px; color: {pwin_color(p_a)};")
        
        def gap_text(gap, level, pts):
            if gap > 0.3:
                gap_color = "#27AE60"
            elif gap < -0.3:
                gap_color = "#E74C3C"
            else:
                gap_color = "#666"
            return (f"<span style='color:{gap_color}; font-weight:bold;'>Gap: {gap:+.2f}</span>"
                    f"  Nv={level:.2f}  Forma={pts:.2f}")
        
        self.rn_gap_home.setText(gap_text(d['gap_home'], d['level_home'], d['pts_recent_home']))
        self.rn_gap_home.setTextFormat(Qt.RichText)
        
        self.rn_gap_away.setText(gap_text(d['gap_away'], d['level_away'], d['pts_recent_away']))
        self.rn_gap_away.setTextFormat(Qt.RichText)
        
        self.rn_detail_home.setText(f"μ={d['mu_home']:.2f}")
        self.rn_detail_away.setText(f"μ={d['mu_away']:.2f}")
        
        conf = d['confidence']
        conf_colors = {'ALTA': '#27AE60', 'MEDIA': '#F39C12', 'BAJA': '#999'}
        self.rn_confidence.setText(f"Confianza: {conf}")
        self.rn_confidence.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {conf_colors.get(conf, '#666')};"
        )
        
        self.rn_draw.setText(f"P(Draw)\u2248{self._fmt(d['p_draw_approx'])}  |  Gap diff: {d['gap_diff']:+.2f}")
        
        rec = d.get('recommendation', '')
        if rec:
            self.rn_recommendation.setText(f"💡 {rec}")
            self.rn_recommendation.setVisible(True)
        else:
            self.rn_recommendation.setVisible(False)
        
        self._worker_done()
    
    def _on_regresion_error(self, e: str):
        logger.warning(f"Regresión al Nivel: {e}")
        self.rn_pwin_home.setText("-")
        self.rn_pwin_home.setStyleSheet("font-weight: bold; font-size: 26px; color: #CCC;")
        self.rn_pwin_away.setText("-")
        self.rn_pwin_away.setStyleSheet("font-weight: bold; font-size: 26px; color: #CCC;")
        self.rn_gap_home.setText(f"<span style='color:#999;'>{e[:50]}</span>")
        self.rn_gap_home.setTextFormat(Qt.RichText)
        self.rn_gap_away.setText("")
        self.rn_detail_home.setText("")
        self.rn_detail_away.setText("")
        self.rn_confidence.setText("")
        self.rn_draw.setText("")
        self.rn_recommendation.setVisible(False)
        self._worker_done()
    
    # =========================================================================
    # HANDLERS: LEY DE LA FE PERDIDA
    # =========================================================================
    
    def _on_fe_perdida_finished(self, d: Dict):
        # Almacenar raw para toggle
        self._raw_probabilities['fe_prob_home'] = d['prob_home']
        self._raw_probabilities['fe_prob_draw'] = d['prob_draw']
        self._raw_probabilities['fe_prob_away'] = d['prob_away']
        for prefix, gf_key, pct_key in [('fe_home', 'home_goal_flag', 'home_scores_pct'),
                                          ('fe_away', 'away_goal_flag', 'away_scores_pct')]:
            self._raw_probabilities[f'{prefix}_goal_flag_type'] = d.get(gf_key, 'none')
            self._raw_probabilities[f'{prefix}_scores_pct'] = d.get(pct_key, 0)
        
        FLAG_COLORS = {
            'HOME_STRONG': '#2E7D32', 'HOME': '#1976D2',
            'NONE': '#9E9E9E', 'AWAY': '#D32F2F', 'AWAY_STRONG': '#7B1FA2',
        }
        ZONE_COLORS = {
            'euforia': '#4CAF50', 'confianza': '#8BC34A', 'neutral': '#9E9E9E',
            'tension': '#FF9800', 'frustracion': '#F44336', 'fe_destruida': '#880E4F',
        }
        
        flag = d['flag']
        color = FLAG_COLORS.get(flag, '#9E9E9E')
        edge = d['edge_pp']
        
        self.fe_flag_label.setText(f"{d['flag_emoji']} {flag.replace('_', ' ')}")
        self.fe_flag_label.setStyleSheet(f"font-weight: bold; font-size: 16px; color: {color};")
        
        if edge > 0:
            self.fe_edge_label.setText(f"+{edge:.0f}pp")
            self.fe_edge_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color}; margin-left: 15px;")
        else:
            self.fe_edge_label.setText("Sin ventaja")
            self.fe_edge_label.setStyleSheet("font-size: 12px; color: #999; margin-left: 15px;")
        
        self.fe_flag_desc.setText(d.get('flag_description', '')[:60])
        
        self.fe_home_label.setText(f"\U0001f3e0 {d['home_name'][:18]}")
        self.fe_away_label.setText(f"\u2708\ufe0f {d['away_name'][:18]}")
        
        h_color = ZONE_COLORS.get(d['home_zone'], '#999')
        a_color = ZONE_COLORS.get(d['away_zone'], '#999')
        
        self.fe_home_score.setText(f"{d['home_pendulum']:+.1f}")
        self.fe_home_score.setStyleSheet(f"font-weight: bold; font-size: 22px; color: {h_color};")
        self.fe_home_zone.setText(f"{d['home_zone'].replace('_',' ').title()} [{d['home_mode']}] {d['home_stature'].upper()}")
        
        self.fe_away_score.setText(f"{d['away_pendulum']:+.1f}")
        self.fe_away_score.setStyleSheet(f"font-weight: bold; font-size: 22px; color: {a_color};")
        self.fe_away_zone.setText(f"{d['away_zone'].replace('_',' ').title()} [{d['away_mode']}] {d['away_stature'].upper()}")
        
        def colorize_racha(racha):
            parts = []
            for c in racha:
                if c == 'W': parts.append("<span style='color:#4CAF50;font-weight:bold;'>W</span>")
                elif c == 'D': parts.append("<span style='color:#FF9800;font-weight:bold;'>D</span>")
                elif c == 'L': parts.append("<span style='color:#F44336;font-weight:bold;'>L</span>")
                else: parts.append(c)
            return "".join(parts)
        
        self.fe_home_racha.setText(colorize_racha(d['home_racha']))
        self.fe_home_racha.setTextFormat(Qt.RichText)
        self.fe_away_racha.setText(colorize_racha(d['away_racha']))
        self.fe_away_racha.setTextFormat(Qt.RichText)

        # Sincronizar con datos reales de Forma Reciente si ya están disponibles
        self._sync_fe_racha()
        
        for prefix, gf_key, pct_key in [('fe_home', 'home_goal_flag', 'home_scores_pct'),
                                          ('fe_away', 'away_goal_flag', 'away_scores_pct')]:
            lbl = getattr(self, f"{prefix}_goal")
            gf = d.get(gf_key, 'none')
            pct = d.get(pct_key, 0)
            if gf == 'scores':
                lbl.setText(f"\u26bd Anota {self._fmt(pct)}")
                lbl.setStyleSheet("font-size: 10px; color: #4CAF50; font-weight: bold;")
            elif gf == 'seco':
                lbl.setText(f"\U0001f480 Solo {self._fmt(pct)}")
                lbl.setStyleSheet("font-size: 10px; color: #F44336; font-weight: bold;")
            else:
                lbl.setText("")
        
        gap_color = color if flag != 'NONE' else '#1B2838'
        self.fe_gap_label.setText(f"{d['gap']:+.0f}")
        self.fe_gap_label.setStyleSheet(f"font-weight: bold; font-size: 20px; color: {gap_color};")
        
        self.fe_prob_home.setText(f"1: {self._fmt(d['prob_home'])}")
        self.fe_prob_draw.setText(f"X: {self._fmt(d['prob_draw'])}")
        self.fe_prob_away.setText(f"2: {self._fmt(d['prob_away'])}")
        self.fe_margin.setText(f"Margen: {d['expected_margin']:+.2f}")
        
        self._worker_done()
    
    def _on_fe_perdida_error(self, e: str):
        logger.warning(f"Fe Perdida: {e}")
        self.fe_flag_label.setText("\u26a0\ufe0f No disponible")
        self.fe_flag_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #999;")
        self.fe_edge_label.setText("")
        self.fe_flag_desc.setText(e[:50])
        for attr in ['fe_home_score', 'fe_away_score', 'fe_gap_label']:
            getattr(self, attr).setText("-")
        for attr in ['fe_home_zone', 'fe_away_zone', 'fe_home_racha', 'fe_away_racha',
                     'fe_home_goal', 'fe_away_goal', 'fe_margin']:
            getattr(self, attr).setText("")
        self.fe_prob_home.setText("-")
        self.fe_prob_draw.setText("-")
        self.fe_prob_away.setText("-")
        self._worker_done()

    # =========================================================================
    # HANDLERS: MARCADOR
    # =========================================================================
    
    def _on_marcador_finished(self, d: Dict):
        probs = d['probs']
        
        # Almacenar raw para toggle
        poisson_map = {
            'mc_home_o05': 'home_over_05', 'mc_home_o15': 'home_over_15',
            'mc_home_o25': 'home_over_25',
            'mc_away_o05': 'away_over_05', 'mc_away_o15': 'away_over_15',
            'mc_away_o25': 'away_over_25',
            'mc_total_o25': 'total_over_25', 'mc_total_o35': 'total_over_35',
            'mc_btts': 'btts',
        }
        for rp_key, prob_key in poisson_map.items():
            self._raw_probabilities[rp_key] = probs.get(prob_key, 0)
        self._raw_probabilities['mc_top_scores'] = d.get('top_scores', [])
        
        self.xg_home.setText(f"{d['lambda_home']:.2f}")
        self.xg_away.setText(f"{d['lambda_away']:.2f}")
        self.xg_total.setText(f"{d['lambda_total']:.2f}")
        
        self.home_over05.setText(self._fmt(probs.get('home_over_05', 0)))
        self.home_over15.setText(self._fmt(probs.get('home_over_15', 0)))
        self.home_over25.setText(self._fmt(probs.get('home_over_25', 0)))
        
        self.away_over05.setText(self._fmt(probs.get('away_over_05', 0)))
        self.away_over15.setText(self._fmt(probs.get('away_over_15', 0)))
        self.away_over25.setText(self._fmt(probs.get('away_over_25', 0)))
        
        self.over25.setText(self._fmt(probs.get('total_over_25', 0)))
        self.over35.setText(self._fmt(probs.get('total_over_35', 0)))
        self.btts.setText(self._fmt(probs.get('btts', 0)))
        
        def colorize(label, prob):
            if prob >= 0.7:
                label.setStyleSheet("font-weight: bold; font-size: 13px; color: #28a745;")
            elif prob >= 0.5:
                label.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffc107;")
            else:
                label.setStyleSheet("font-weight: bold; font-size: 13px; color: #666;")
        
        colorize(self.home_over05, probs.get('home_over_05', 0))
        colorize(self.home_over15, probs.get('home_over_15', 0))
        colorize(self.home_over25, probs.get('home_over_25', 0))
        colorize(self.away_over05, probs.get('away_over_05', 0))
        colorize(self.away_over15, probs.get('away_over_15', 0))
        colorize(self.away_over25, probs.get('away_over_25', 0))
        
        top_scores = d.get('top_scores', [])
        if top_scores:
            if self._show_as_odds:
                parts = [f"<b>{s}</b> ({self._format_as_odds(p)})" for s, p in top_scores[:4]]
            else:
                parts = [f"<b>{s}</b> ({p*100:.0f}%)" for s, p in top_scores[:4]]
            self.scores_inline.setText(" | ".join(parts))
            self.scores_inline.setTextFormat(Qt.RichText)
        else:
            self.scores_inline.setText("Sin datos")
        
        self._worker_done()
    
    def _on_marcador_error(self, e: str):
        self.xg_home.setText("Error")
        self.xg_away.setText("-")
        self.xg_total.setText("-")
        self.home_over05.setText("-")
        self.home_over15.setText("-")
        self.home_over25.setText("-")
        self.away_over05.setText("-")
        self.away_over15.setText("-")
        self.away_over25.setText("-")
        self.over25.setText("-")
        self.over35.setText("-")
        self.btts.setText("-")
        self.scores_inline.setText(f"Error: {e[:30]}")
        self._worker_done()
    
    # =========================================================================
    # HANDLERS: H2H — Cards + Barra de dominio (NUEVO)
    # =========================================================================
    
    def _on_h2h_finished(self, h2h: List[Dict]):
        """Construye H2H visual: barra de dominio + match cards."""
        self._clear_layout(self.h2h_content)

        if not h2h:
            lbl = QLabel("Sin historial entre estos equipos")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #999; font-style: italic; padding: 20px;")
            self.h2h_content.addWidget(lbl)
            self._worker_done()
            return

        home_name = self._h2h_home_name
        away_name = self._h2h_away_name

        # ── Calcular W/D/L desde perspectiva del equipo LOCAL actual ──
        wins, draws, losses = 0, 0, 0
        results = []

        for m in h2h:
            gh, ga = m['goals_home'], m['goals_away']
            if m['home_name'] == home_name:
                r = 'W' if gh > ga else ('L' if gh < ga else 'D')
            elif m['away_name'] == home_name:
                r = 'W' if ga > gh else ('L' if ga < gh else 'D')
            else:
                r = 'D'
            results.append(r)
            if r == 'W':
                wins += 1
            elif r == 'D':
                draws += 1
            else:
                losses += 1

        # ══════════════════════════════════════════════════════════════
        # BARRA DE DOMINIO
        # ══════════════════════════════════════════════════════════════
        summary = QFrame()
        summary.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f0fdf4, stop:0.5 #f8f9fa, stop:1 #fef2f2);
                border-radius: 8px;
                border: 1px solid #e0e0e0;
            }
        """)
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(15, 10, 15, 10)
        summary_layout.setSpacing(8)

        # Fila: Nombre_Home — W/D/L badges — Nombre_Away
        top = QHBoxLayout()

        lbl_h = QLabel(home_name[:22])
        lbl_h.setStyleSheet("font-weight: bold; font-size: 13px; color: #1b5e20; background: transparent;")
        top.addWidget(lbl_h)

        top.addStretch()

        record = QLabel(
            f"<span style='color:#28a745;font-weight:bold;'>{wins}V</span>"
            f"  <span style='color:#adb5bd;font-weight:bold;'>{draws}E</span>"
            f"  <span style='color:#dc3545;font-weight:bold;'>{losses}D</span>"
        )
        record.setTextFormat(Qt.RichText)
        record.setStyleSheet("font-size: 13px; background: transparent;")
        record.setAlignment(Qt.AlignCenter)
        top.addWidget(record)

        top.addStretch()

        lbl_a = QLabel(away_name[:22])
        lbl_a.setStyleSheet("font-weight: bold; font-size: 13px; color: #b71c1c; background: transparent;")
        lbl_a.setAlignment(Qt.AlignRight)
        top.addWidget(lbl_a)

        summary_layout.addLayout(top)

        # Barra proporcional coloreada
        bar = QFrame()
        bar.setFixedHeight(10)
        bar.setStyleSheet("background: transparent;")
        bar_ly = QHBoxLayout(bar)
        bar_ly.setContentsMargins(0, 0, 0, 0)
        bar_ly.setSpacing(3)

        for count, color in [(wins, "#43a047"), (draws, "#bdbdbd"), (losses, "#e53935")]:
            if count > 0:
                seg = QFrame()
                seg.setStyleSheet(f"background: {color}; border-radius: 4px;")
                bar_ly.addWidget(seg, count)

        summary_layout.addWidget(bar)
        self.h2h_content.addWidget(summary)

        # ══════════════════════════════════════════════════════════════
        # MATCH CARDS
        # ══════════════════════════════════════════════════════════════
        for i, (m, r) in enumerate(zip(h2h, results)):
            card = self._create_h2h_card(m, r, i)
            self.h2h_content.addWidget(card)

        self._worker_done()
    
    def _on_h2h_error(self, e: str):
        self._worker_done()
    
    # =========================================================================
    # HANDLERS: ODDS
    # =========================================================================
    
    def _on_odds_finished(self, d: Dict):
        self.loaded_odds_data = d
        
        error_msg = d.get('error_msg')
        if error_msg:
            self.odds_1x2.setText(f"<span style='color:#856404;'>⚠️ {error_msg}</span>")
            self.odds_1x2.setTextFormat(Qt.RichText)
            self.odds_goles.setText("-")
            self.odds_handicap.setText("-")
            self.odds_btts.setText("-")
            self.odds_dc.setText("-")
            self.odds_source.setText("")

            self._worker_done()
            return
        
        def to_profit_pct(odd_value):
            if odd_value and odd_value > 0:
                return (odd_value - 1) * 100
            return None
        
        def format_pct(pct, label):
            if pct is None:
                return f"<span style='color:#999;'>{label}: -</span>"
            if pct >= 200:
                color = "#dc3545"
            elif pct >= 100:
                color = "#e67e22"
            elif pct >= 50:
                color = "#ffc107"
            else:
                color = "#28a745"
            return f"<b style='color:{color};'>{label}: +{pct:.0f}%</b>"
        
        def get_best_bookmaker(odds_list):
            if not odds_list:
                return None
            for o in odds_list:
                if 'bet365' in o['bookmaker'].lower():
                    return o
            return odds_list[0]
        
        has_any_odds = False
        source_name = ""
        
        # Almacenar cuotas del bookmaker
        self._raw_odds_bookmaker = {}
        
        match_winner = d.get('match_winner', [])
        if match_winner:
            best = get_best_bookmaker(match_winner)
            if best:
                # Almacenar cuotas
                if best.get('home', 0) > 0:
                    self._raw_odds_bookmaker['bk_1x2_home'] = best['home']
                if best.get('draw', 0) > 0:
                    self._raw_odds_bookmaker['bk_1x2_draw'] = best['draw']
                if best.get('away', 0) > 0:
                    self._raw_odds_bookmaker['bk_1x2_away'] = best['away']
                
                home_pct = to_profit_pct(best.get('home', 0))
                draw_pct = to_profit_pct(best.get('draw', 0))
                away_pct = to_profit_pct(best.get('away', 0))
                text_1x2 = f"{format_pct(home_pct, '1')}  |  {format_pct(draw_pct, 'X')}  |  {format_pct(away_pct, '2')}"
                self.odds_1x2.setText(text_1x2)
                self.odds_1x2.setTextFormat(Qt.RichText)
                has_any_odds = True
                source_name = best['bookmaker']
        else:
            self.odds_1x2.setText("<span style='color:#856404;'>⚠️ Sin datos</span>")
            self.odds_1x2.setTextFormat(Qt.RichText)
        
        goals_ou = d.get('goals_ou', [])
        if goals_ou:
            best = get_best_bookmaker(goals_ou)
            if best:
                # Almacenar cuotas
                for bk_key, raw_key in [('over_25', 'bk_over_25'), ('over_35', 'bk_over_35'),
                                          ('under_25', 'bk_under_25')]:
                    if best.get(bk_key, 0) > 0:
                        self._raw_odds_bookmaker[raw_key] = best[bk_key]
                
                o15 = to_profit_pct(best.get('over_15', 0))
                u15 = to_profit_pct(best.get('under_15', 0))
                o25 = to_profit_pct(best.get('over_25', 0))
                u25 = to_profit_pct(best.get('under_25', 0))
                o35 = to_profit_pct(best.get('over_35', 0))
                u35 = to_profit_pct(best.get('under_35', 0))
                
                parts = []
                if o25 is not None and o25 > 0:
                    parts.append(f"{format_pct(o25, 'O2.5')}")
                if u25 is not None and u25 > 0:
                    parts.append(f"{format_pct(u25, 'U2.5')}")
                if o35 is not None and o35 > 0:
                    parts.append(f"{format_pct(o35, 'O3.5')}")
                if o15 is not None and o15 > 0 and len(parts) < 4:
                    parts.insert(0, f"{format_pct(o15, 'O1.5')}")
                
                if parts:
                    self.odds_goles.setText("  |  ".join(parts[:4]))
                    self.odds_goles.setTextFormat(Qt.RichText)
                    has_any_odds = True
                    if not source_name:
                        source_name = best['bookmaker']
                else:
                    self.odds_goles.setText("-")
        else:
            self.odds_goles.setText("-")
        
        handicap = d.get('handicap', [])
        if handicap:
            best = get_best_bookmaker(handicap)
            if best and best.get('lines'):
                lines = best['lines']
                hcap_parts = []
                for line in lines[:6]:
                    value = line.get('value', '')
                    odd = line.get('odd', 0)
                    pct = to_profit_pct(odd)
                    if pct is not None and value:
                        clean_value = value.replace('Home ', 'L').replace('Away ', 'V').replace('Draw', 'E')
                        hcap_parts.append(f"{format_pct(pct, clean_value[:12])}")
                
                if hcap_parts:
                    self.odds_handicap.setText("  |  ".join(hcap_parts[:4]))
                    self.odds_handicap.setTextFormat(Qt.RichText)
                    has_any_odds = True
                    if not source_name:
                        source_name = best['bookmaker']
                else:
                    self.odds_handicap.setText("-")
            else:
                self.odds_handicap.setText("-")
        else:
            self.odds_handicap.setText("-")
        
        if has_any_odds and source_name:
            self.odds_source.setText(f"📊 {source_name}")
        else:
            self.odds_source.setText("⚠️ Cuotas no actualizadas")
        
        # ── BTTS display ──
        btts_data = d.get('btts', [])
        if btts_data:
            best = get_best_bookmaker(btts_data)
            if best:
                yes_odd = best.get('yes', 0)
                no_odd = best.get('no', 0)
                # Almacenar cuotas
                if yes_odd > 0:
                    self._raw_odds_bookmaker['bk_btts_yes'] = yes_odd
                if no_odd > 0:
                    self._raw_odds_bookmaker['bk_btts_no'] = no_odd
                
                yes_pct = to_profit_pct(yes_odd)
                no_pct = to_profit_pct(no_odd)
                
                parts = []
                if yes_pct is not None and yes_pct > 0:
                    parts.append(f"{format_pct(yes_pct, 'Sí')}")
                if no_pct is not None and no_pct > 0:
                    parts.append(f"{format_pct(no_pct, 'No')}")
                
                if parts:
                    self.odds_btts.setText("  |  ".join(parts))
                    self.odds_btts.setTextFormat(Qt.RichText)
                    has_any_odds = True
                    if not source_name:
                        source_name = best['bookmaker']
                else:
                    self.odds_btts.setText("-")
            else:
                self.odds_btts.setText("-")
        else:
            self.odds_btts.setText("-")
        
        
        # ── Double Chance / Doble Oportunidad display ──
        dc_data = d.get('double_chance', [])
        if dc_data:
            best = get_best_bookmaker(dc_data)
            if best:
                hd_odd = best.get('home_draw', 0)
                ha_odd = best.get('home_away', 0)
                da_odd = best.get('draw_away', 0)
                # Almacenar cuotas
                if hd_odd > 0:
                    self._raw_odds_bookmaker['bk_dc_home_draw'] = hd_odd
                if ha_odd > 0:
                    self._raw_odds_bookmaker['bk_dc_home_away'] = ha_odd
                if da_odd > 0:
                    self._raw_odds_bookmaker['bk_dc_draw_away'] = da_odd
                
                hd_pct = to_profit_pct(hd_odd)
                ha_pct = to_profit_pct(ha_odd)
                da_pct = to_profit_pct(da_odd)
                
                parts = []
                if hd_pct is not None and hd_pct > 0:
                    parts.append(f"{format_pct(hd_pct, '1X')}")
                if ha_pct is not None and ha_pct > 0:
                    parts.append(f"{format_pct(ha_pct, '12')}")
                if da_pct is not None and da_pct > 0:
                    parts.append(f"{format_pct(da_pct, 'X2')}")
                
                if parts:
                    self.odds_dc.setText("  |  ".join(parts))
                    self.odds_dc.setTextFormat(Qt.RichText)
                    has_any_odds = True
                    if not source_name:
                        source_name = best['bookmaker']
                else:
                    self.odds_dc.setText("-")
            else:
                self.odds_dc.setText("-")
        else:
            self.odds_dc.setText("-")


        
        self._worker_done()
    
    def _on_odds_error(self, e: str):
        logger.error(f"Error al obtener odds: {e}")
        self.odds_1x2.setText(f"<span style='color:#856404;'>⚠️ Error: {e[:50]}</span>")
        self.odds_1x2.setTextFormat(Qt.RichText)
        self.odds_goles.setText("-")
        self.odds_handicap.setText("-")
        self.odds_btts.setText("-")
        self.odds_dc.setText("-")
        self.odds_source.setText("")
        self._worker_done()
    
    # =========================================================================
    # HANDLERS: FORMA RECIENTE — Círculos Flashscore (NUEVO)
    # =========================================================================
    
    def _on_home_form_finished(self, data: Dict):
        """Procesa resultados de forma del equipo local con círculos Flashscore."""
        self._form_results_home = data.get('last_matches', [])
        self._populate_form_column(
            self.home_circles, self.home_form_summary,
            self.home_details, self.home_next,
            data.get('last_matches', []),
            data.get('next_matches', []),
        )
        # Sincronizar racha de Fe Perdida si ya terminó
        self._sync_fe_racha()
        self._worker_done()
    
    def _on_away_form_finished(self, data: Dict):
        """Procesa resultados de forma del equipo visitante con círculos Flashscore."""
        self._form_results_away = data.get('last_matches', [])
        self._populate_form_column(
            self.away_circles, self.away_form_summary,
            self.away_details, self.away_next,
            data.get('last_matches', []),
            data.get('next_matches', []),
        )
        # Sincronizar racha de Fe Perdida si ya terminó
        self._sync_fe_racha()
        self._worker_done()
    
    def _sync_fe_racha(self):
        """Sincroniza la racha de Fe Perdida con los datos reales de Forma Reciente."""
        def colorize_racha_from_form(matches):
            parts = []
            for m in matches:
                r = m.get('result', '?')
                if r == 'W':
                    parts.append("<span style='color:#4CAF50;font-weight:bold;'>W</span>")
                elif r == 'D':
                    parts.append("<span style='color:#FF9800;font-weight:bold;'>D</span>")
                elif r == 'L':
                    parts.append("<span style='color:#F44336;font-weight:bold;'>L</span>")
                else:
                    parts.append(r)
            return "".join(parts)

        if self._form_results_home and hasattr(self, 'fe_home_racha'):
            try:
                self.fe_home_racha.setText(colorize_racha_from_form(self._form_results_home))
                self.fe_home_racha.setTextFormat(Qt.RichText)
            except Exception:
                pass

        if self._form_results_away and hasattr(self, 'fe_away_racha'):
            try:
                self.fe_away_racha.setText(colorize_racha_from_form(self._form_results_away))
                self.fe_away_racha.setTextFormat(Qt.RichText)
            except Exception:
                pass

    def _on_prev_odds_finished(self, d: Dict):
        """Puebla la sección de Odds de Rivales Anteriores."""
        for side, content_layout, title_lbl in [
            ('home', self.prev_odds_home_content, self.prev_odds_home_title),
            ('away', self.prev_odds_away_content, self.prev_odds_away_title),
        ]:
            self._clear_layout(content_layout)
            matches = d.get(side, [])

            if not matches:
                lbl = QLabel("Sin datos de partidos anteriores")
                lbl.setStyleSheet("color: #999; font-style: italic; font-size: 10px;")
                content_layout.addWidget(lbl)
                continue

            for m in matches:
                # ── Header del partido ──
                r_colors = {'W': '#43a047', 'D': '#fbc02d', 'L': '#e53935'}
                r_letters = {'W': 'V', 'D': 'E', 'L': 'D'}
                venue = "🏠" if m['is_home'] else "✈️"

                d_val = m.get('date', '')
                if isinstance(d_val, str):
                    try:
                        from datetime import datetime as _dt
                        d_val = _dt.fromisoformat(d_val.replace('Z', '+00:00'))
                    except:
                        pass
                date_str = d_val.strftime('%d/%m') if hasattr(d_val, 'strftime') else str(d_val)[:5]

                r_lbl_text = r_letters.get(m['result'], '?')
                r_color = r_colors.get(m['result'], '#999')

                header = QLabel(
                    f"<span style='color:{r_color};font-weight:bold;'>{r_lbl_text}</span>"
                    f"  {venue} vs {m['opponent'][:18]}"
                    f"  ({m['goals_for']}-{m['goals_against']})"
                    f"  <span style='color:#aaa;font-size:9px;'>{date_str}</span>"
                )
                header.setTextFormat(Qt.RichText)
                header.setStyleSheet("font-size: 11px; color: #333; padding: 2px 0;")
                content_layout.addWidget(header)

                odds = m.get('odds', {})
                if not odds or not any(odds.values()):
                    no_odds = QLabel("   Sin cuotas disponibles")
                    no_odds.setStyleSheet("font-size: 9px; color: #bbb; font-style: italic;")
                    content_layout.addWidget(no_odds)
                else:
                    # ── 1X2 ──
                    o1x2 = odds.get('1x2')
                    if o1x2:
                        outcome = m['outcome_1x2']
                        parts_1x2 = []
                        for key, lbl_text in [('home', '1'), ('draw', 'X'), ('away', '2')]:
                            val = o1x2.get(key, 0)
                            if val > 0:
                                if key == outcome:
                                    parts_1x2.append(
                                        f"<span style='background:#4CAF50;color:white;"
                                        f"font-weight:bold;padding:1px 4px;border-radius:3px;'>"
                                        f"{lbl_text}: {val:.2f}</span>"
                                    )
                                else:
                                    parts_1x2.append(f"<span style='color:#666;'>{lbl_text}: {val:.2f}</span>")
                        if parts_1x2:
                            row_1x2 = QLabel("   1X2: " + "  |  ".join(parts_1x2))
                            row_1x2.setTextFormat(Qt.RichText)
                            row_1x2.setStyleSheet("font-size: 10px;")
                            content_layout.addWidget(row_1x2)

                    # ── O2.5 + BTTS en misma línea ──
                    parts_line2 = []
                    ou25 = odds.get('ou25')
                    if ou25:
                        ov = ou25.get('over', 0)
                        if ov > 0:
                            if m.get('over25_hit'):
                                parts_line2.append(
                                    f"<span style='background:#4CAF50;color:white;"
                                    f"font-weight:bold;padding:1px 4px;border-radius:3px;'>"
                                    f"O2.5: {ov:.2f}</span>"
                                )
                            else:
                                parts_line2.append(f"<span style='color:#666;'>O2.5: {ov:.2f}</span>")
                        un = ou25.get('under', 0)
                        if un > 0:
                            if not m.get('over25_hit'):
                                parts_line2.append(
                                    f"<span style='background:#4CAF50;color:white;"
                                    f"font-weight:bold;padding:1px 4px;border-radius:3px;'>"
                                    f"U2.5: {un:.2f}</span>"
                                )
                            else:
                                parts_line2.append(f"<span style='color:#666;'>U2.5: {un:.2f}</span>")

                    obt = odds.get('btts')
                    if obt:
                        yes_v = obt.get('yes', 0)
                        no_v = obt.get('no', 0)
                        if yes_v > 0:
                            if m.get('btts_hit'):
                                parts_line2.append(
                                    f"<span style='background:#4CAF50;color:white;"
                                    f"font-weight:bold;padding:1px 4px;border-radius:3px;'>"
                                    f"BTTS Sí: {yes_v:.2f}</span>"
                                )
                            else:
                                parts_line2.append(f"<span style='color:#666;'>BTTS Sí: {yes_v:.2f}</span>")
                        if no_v > 0:
                            if not m.get('btts_hit'):
                                parts_line2.append(
                                    f"<span style='background:#4CAF50;color:white;"
                                    f"font-weight:bold;padding:1px 4px;border-radius:3px;'>"
                                    f"BTTS No: {no_v:.2f}</span>"
                                )
                            else:
                                parts_line2.append(f"<span style='color:#666;'>BTTS No: {no_v:.2f}</span>")

                    if parts_line2:
                        row_l2 = QLabel("   " + "  |  ".join(parts_line2))
                        row_l2.setTextFormat(Qt.RichText)
                        row_l2.setStyleSheet("font-size: 10px;")
                        content_layout.addWidget(row_l2)

                    # ── Doble Oportunidad ──
                    odc = odds.get('dc')
                    if odc:
                        dc_outcomes = m.get('dc_outcomes', set())
                        parts_dc = []
                        for key, lbl_text in [('1x', '1X'), ('12', '12'), ('x2', 'X2')]:
                            val = odc.get(key, 0)
                            if val > 0:
                                if key in dc_outcomes:
                                    parts_dc.append(
                                        f"<span style='background:#4CAF50;color:white;"
                                        f"font-weight:bold;padding:1px 4px;border-radius:3px;'>"
                                        f"{lbl_text}: {val:.2f}</span>"
                                    )
                                else:
                                    parts_dc.append(f"<span style='color:#666;'>{lbl_text}: {val:.2f}</span>")
                        if parts_dc:
                            row_dc = QLabel("   DC: " + "  |  ".join(parts_dc))
                            row_dc.setTextFormat(Qt.RichText)
                            row_dc.setStyleSheet("font-size: 10px;")
                            content_layout.addWidget(row_dc)

                # Separador entre partidos
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet("color: #eee;")
                sep.setFixedHeight(1)
                content_layout.addWidget(sep)

        self._worker_done()

    def _on_prev_odds_error(self, e: str):
        """Error en worker de odds anteriores."""
        logger.warning(f"Previous odds: {e}")
        for content_layout in [self.prev_odds_home_content, self.prev_odds_away_content]:
            self._clear_layout(content_layout)
            lbl = QLabel(f"⚠️ {e[:40]}")
            lbl.setStyleSheet("color: #999; font-size: 10px;")
            content_layout.addWidget(lbl)
        self._worker_done()

    def _on_form_error(self, e: str):
        logger.error(f"Error obteniendo forma: {e}")
        self._worker_done()
    

def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = PreMatchAnalysisWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())