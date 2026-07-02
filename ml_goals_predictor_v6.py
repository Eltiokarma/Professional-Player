#!/usr/bin/env python3
"""
ml_goals_predictor_v6.py

PREDICTOR DE GOLES V6 - MODELO POISSON
======================================

Mejoras vs V5:
- Predice λ (lambda) = goles esperados para cada equipo
- Deriva TODAS las probabilidades de forma matemáticamente consistente
- Garantiza P(Over N+1) <= P(Over N) por construcción
- Incluye resultados más probables (1-0, 2-1, etc.)

Modelo:
- Regresión para predecir λ_home y λ_away
- Distribución Poisson: P(k goles) = (λ^k × e^(-λ)) / k!
- Over/Under derivados: P(Over N) = 1 - Σ P(k) para k=0..N

Predicciones:
- LOCAL: Over/Under 0.5, 1.5, 2.5 (derivado de λ_home)
- VISITANTE: Over/Under 0.5, 1.5, 2.5 (derivado de λ_away)
- TOTAL: Over/Under 2.5, 3.5 (convolución de Poisson)
- BTTS: P(home≥1) × P(away≥1)
- RESULTADOS: Top 5 marcadores más probables

Autor: Gerson (desarrollado con Claude)
Fecha: Enero 2026
"""

import os
import sqlite3
import logging
import numpy as np
import pandas as pd
import joblib
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import StandardScaler
from scipy.stats import poisson
from math import factorial, exp
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def find_project_root() -> str:
    """Encuentra la raíz del proyecto."""
    current = os.path.dirname(os.path.abspath(__file__))
    
    for _ in range(5):
        constants_path = os.path.join(current, 'constants.db')
        if os.path.exists(constants_path):
            try:
                conn = sqlite3.connect(constants_path)
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='constants'"
                )
                if cursor.fetchone():
                    conn.close()
                    return current
                conn.close()
            except:
                pass
        
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    
    return os.getcwd()


class MLGoalsPredictorV6:
    """
    Predictor de goles V6 - Modelo POISSON.
    
    En lugar de clasificadores binarios independientes, predice:
    - λ_home: Goles esperados del local
    - λ_away: Goles esperados del visitante
    
    Todas las probabilidades se derivan matemáticamente de λ,
    garantizando consistencia jerárquica.
    """
    
    MODEL_FILENAME = 'ml_goals_predictor_v6_model.pkl'
    
    # Bins fijos para discretización de niveles (heredado de V5)
    LEVEL_BINS = [0.0, 0.6, 1.3, 1.6, 1.9, 2.1, 2.35, 2.55, 2.85, 3.2, float('inf')]
    LEVEL_LABELS = [
        'Sin datos', 'Muy débil', 'Débil', 'Regular bajo', 'Promedio bajo',
        'Promedio', 'Promedio alto', 'Fuerte', 'Muy fuerte', 'Elite',
    ]
    
    # Umbrales para sugerencias (CALIBRADOS para V6 Poisson)
    THRESHOLDS = {
        'home_over_05': {'high': 0.91, 'medium': 0.84},
        'home_under_05': {'high': 0.50, 'medium': 0.58},
        'home_over_15': {'high': 0.70, 'medium': 0.63},
        'home_under_15': {'high': 0.46, 'medium': 0.54},
        'home_over_25': {'high': 0.51, 'medium': 0.44},
        'home_under_25': {'high': 0.21, 'medium': 0.29},
        'away_over_05': {'high': 0.86, 'medium': 0.79},
        'away_under_05': {'high': 0.50, 'medium': 0.58},
        'away_over_15': {'high': 0.61, 'medium': 0.54},
        'away_under_15': {'high': 0.21, 'medium': 0.29},
        'away_over_25': {'high': 0.50, 'medium': 0.43},
        'away_under_25': {'high': 0.06, 'medium': 0.14},
        'total_over_25': {'high': 0.70, 'medium': 0.63},
        'total_under_25': {'high': 0.41, 'medium': 0.49},
        'total_over_35': {'high': 0.67, 'medium': 0.60},
        'total_under_35': {'high': 0.21, 'medium': 0.29},
        'btts_yes': {'high': 0.78, 'medium': 0.71},
        'btts_no': {'high': 0.28, 'medium': 0.36},
    }
    
    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = find_project_root()
        
        self.project_root = project_root
        self.constants_db = os.path.join(project_root, 'constants.db')
        self.sad_db = os.path.join(project_root, 'sad.db')
        self.levels_db = os.path.join(project_root, 'levels.db')
        
        self.constants_engine = create_engine(f'sqlite:///{self.constants_db}', echo=False)
        self.sad_engine = create_engine(f'sqlite:///{self.sad_db}', echo=False)
        self.levels_engine = create_engine(f'sqlite:///{self.levels_db}', echo=False)
        
        self._team_names_cache = {}
        self._team_stats_cache = {}
        self._level_cache = {}
        
        # Modelos de regresión para λ
        self.model_home = None  # Predice λ_home
        self.model_away = None  # Predice λ_away
        self.scaler = StandardScaler()
        self.feature_cols = None
        self.is_trained = False
        
        self.model_path = os.path.join(project_root, self.MODEL_FILENAME)
        
        logger.info(f"MLGoalsPredictorV6 (Poisson) inicializado - Raíz: {project_root}")
    
    # =========================================================================
    # UTILIDADES (heredadas de V5)
    # =========================================================================
    
    def get_team_name(self, team_id: int) -> str:
        if team_id in self._team_names_cache:
            return self._team_names_cache[team_id]
        
        query = text("SELECT name FROM teams WHERE id = :team_id")
        try:
            with self.sad_engine.connect() as conn:
                result = conn.execute(query, {'team_id': team_id}).fetchone()
            name = result[0] if result else f"Team_{team_id}"
        except:
            name = f"Team_{team_id}"
        
        self._team_names_cache[team_id] = name
        return name
    
    def discretize_level(self, level: float) -> int:
        for i, threshold in enumerate(self.LEVEL_BINS[1:], 0):
            if level < threshold:
                return i
        return 9
    
    def get_level_description(self, level_bin: int) -> str:
        if 0 <= level_bin < len(self.LEVEL_LABELS):
            return self.LEVEL_LABELS[level_bin]
        return "Desconocido"
    
    def get_team_level(self, team_id: int, before_date: datetime) -> float:
        if isinstance(before_date, str):
            before_date = pd.to_datetime(before_date)
        
        cache_key = (team_id, before_date.strftime('%Y-%m-%d'))
        if cache_key in self._level_cache:
            return self._level_cache[cache_key]
        
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
                    'before_date': before_date.strftime('%Y-%m-%d %H:%M:%S')
                }).fetchone()
            level = result[0] if result else 0.5
        except:
            level = 0.5
        
        self._level_cache[cache_key] = level
        return level
    
    def get_team_stats(self, team_id: int, before_date: datetime, n_matches: int = 10) -> Dict:
        """Estadísticas históricas de un equipo."""
        if isinstance(before_date, str):
            before_date = pd.to_datetime(before_date)
        
        cache_key = (team_id, before_date.strftime('%Y-%m-%d'), n_matches)
        if cache_key in self._team_stats_cache:
            return self._team_stats_cache[cache_key]
        
        query = text("""
            SELECT 
                f.home_team_id, f.away_team_id,
                f.goals_home, f.goals_away
            FROM fixtures f
            WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
              AND f.status_long = 'Match Finished'
              AND f.goals_home IS NOT NULL
              AND f.date < :before_date
            ORDER BY f.date DESC
            LIMIT :n_matches
        """)
        
        df = pd.read_sql_query(query, self.sad_engine, params={
            'team_id': team_id,
            'before_date': before_date.strftime('%Y-%m-%d'),
            'n_matches': n_matches
        })
        
        if len(df) < 5:
            return None
        
        df['is_home'] = (df['home_team_id'] == team_id).astype(int)
        df['goals_for'] = np.where(df['is_home'] == 1, df['goals_home'], df['goals_away'])
        df['goals_against'] = np.where(df['is_home'] == 1, df['goals_away'], df['goals_home'])
        
        stats = {
            'avg_gf': df['goals_for'].mean(),
            'avg_ga': df['goals_against'].mean(),
            'std_gf': df['goals_for'].std(),
            'rate_clean_sheet': (df['goals_against'] == 0).mean(),
            'rate_failed_to_score': (df['goals_for'] == 0).mean(),
        }
        
        # Stats como local
        home_df = df[df['is_home'] == 1]
        if len(home_df) >= 3:
            stats['home_avg_gf'] = home_df['goals_for'].mean()
            stats['home_avg_ga'] = home_df['goals_against'].mean()
        else:
            stats['home_avg_gf'] = stats['avg_gf']
            stats['home_avg_ga'] = stats['avg_ga']
        
        # Stats como visitante
        away_df = df[df['is_home'] == 0]
        if len(away_df) >= 3:
            stats['away_avg_gf'] = away_df['goals_for'].mean()
            stats['away_avg_ga'] = away_df['goals_against'].mean()
        else:
            stats['away_avg_gf'] = stats['avg_gf'] * 0.85
            stats['away_avg_ga'] = stats['avg_ga'] * 1.1
        
        self._team_stats_cache[cache_key] = stats
        return stats
    
    def get_team_k_stats(self, team_id: int, before_date: datetime, n_matches: int = 10) -> Dict:
        if isinstance(before_date, str):
            before_date = pd.to_datetime(before_date)
        
        query = text("""
            SELECT k_goles_anotado, k_goles_recibido
            FROM constants
            WHERE team_id = :team_id AND date < :before_date
            ORDER BY date DESC
            LIMIT :n_matches
        """)
        
        df = pd.read_sql_query(query, self.constants_engine, params={
            'team_id': team_id,
            'before_date': before_date.strftime('%Y-%m-%d'),
            'n_matches': n_matches
        })
        
        if len(df) < 3:
            return {'k_for': 10, 'k_against': 10, 'k_ratio': 1.0}
        
        return {
            'k_for': df['k_goles_anotado'].mean(),
            'k_against': df['k_goles_recibido'].mean(),
            'k_ratio': df['k_goles_anotado'].mean() / (df['k_goles_recibido'].mean() + 0.1),
        }
    
    def get_h2h_stats(self, team1_id: int, team2_id: int, before_date: datetime) -> Dict:
        if isinstance(before_date, str):
            before_date = pd.to_datetime(before_date)
        
        query = text("""
            SELECT goals_home, goals_away, home_team_id
            FROM fixtures
            WHERE ((home_team_id = :t1 AND away_team_id = :t2)
                OR (home_team_id = :t2 AND away_team_id = :t1))
              AND status_long = 'Match Finished'
              AND goals_home IS NOT NULL
              AND date < :before_date
            ORDER BY date DESC
            LIMIT 10
        """)
        
        df = pd.read_sql_query(query, self.sad_engine, params={
            't1': team1_id, 't2': team2_id,
            'before_date': before_date.strftime('%Y-%m-%d')
        })
        
        if len(df) == 0:
            return {
                'h2h_matches': 0,
                'h2h_avg_home': 1.3,
                'h2h_avg_away': 1.1,
            }
        
        return {
            'h2h_matches': len(df),
            'h2h_avg_home': df['goals_home'].mean(),
            'h2h_avg_away': df['goals_away'].mean(),
        }
    
    # =========================================================================
    # FEATURES (simplificadas para regresión)
    # =========================================================================
    
    def create_features(self, home_id: int, away_id: int, match_date: datetime) -> Dict:
        """Crea features para predicción de λ."""
        if isinstance(match_date, str):
            match_date = pd.to_datetime(match_date)
        
        home_stats = self.get_team_stats(home_id, match_date)
        away_stats = self.get_team_stats(away_id, match_date)
        
        if home_stats is None or away_stats is None:
            return None
        
        home_k = self.get_team_k_stats(home_id, match_date)
        away_k = self.get_team_k_stats(away_id, match_date)
        h2h = self.get_h2h_stats(home_id, away_id, match_date)
        
        home_level = self.get_team_level(home_id, match_date)
        away_level = self.get_team_level(away_id, match_date)
        
        home_level_bin = self.discretize_level(home_level)
        away_level_bin = self.discretize_level(away_level)
        
        f = {}
        
        # Niveles
        f['home_level'] = home_level
        f['away_level'] = away_level
        f['home_level_bin'] = home_level_bin
        f['away_level_bin'] = away_level_bin
        f['level_diff'] = home_level - away_level
        
        # Ataque y defensa
        f['home_attack'] = home_stats['home_avg_gf']
        f['home_defense'] = home_stats['home_avg_ga']
        f['away_attack'] = away_stats['away_avg_gf']
        f['away_defense'] = away_stats['away_avg_ga']
        
        # Interacciones clave para goles
        f['home_attack_vs_away_def'] = home_stats['home_avg_gf'] * away_stats['away_avg_ga']
        f['away_attack_vs_home_def'] = away_stats['away_avg_gf'] * home_stats['home_avg_ga']
        
        # K stats
        f['home_k_for'] = home_k['k_for']
        f['home_k_against'] = home_k['k_against']
        f['away_k_for'] = away_k['k_for']
        f['away_k_against'] = away_k['k_against']
        
        # Clean sheets y fallos
        f['home_clean_sheet_rate'] = home_stats['rate_clean_sheet']
        f['away_clean_sheet_rate'] = away_stats['rate_clean_sheet']
        f['home_failed_rate'] = home_stats['rate_failed_to_score']
        f['away_failed_rate'] = away_stats['rate_failed_to_score']
        
        # H2H
        f['h2h_home_avg'] = h2h['h2h_avg_home']
        f['h2h_away_avg'] = h2h['h2h_avg_away']
        
        return f
    
    def get_feature_columns(self) -> List[str]:
        return [
            'home_level', 'away_level', 'home_level_bin', 'away_level_bin', 'level_diff',
            'home_attack', 'home_defense', 'away_attack', 'away_defense',
            'home_attack_vs_away_def', 'away_attack_vs_home_def',
            'home_k_for', 'home_k_against', 'away_k_for', 'away_k_against',
            'home_clean_sheet_rate', 'away_clean_sheet_rate',
            'home_failed_rate', 'away_failed_rate',
            'h2h_home_avg', 'h2h_away_avg',
        ]
    
    # =========================================================================
    # MATEMÁTICAS POISSON
    # =========================================================================
    
    def poisson_prob(self, k: int, lam: float) -> float:
        """P(X = k) para distribución Poisson con parámetro λ."""
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return poisson.pmf(k, lam)
    
    def poisson_over(self, n: float, lam: float) -> float:
        """P(X > n) = 1 - P(X <= n) para Poisson."""
        if lam <= 0:
            return 0.0
        return 1 - poisson.cdf(n, lam)
    
    def total_goals_prob(self, total: int, lam_home: float, lam_away: float) -> float:
        """P(home + away = total) usando convolución de Poisson."""
        prob = 0.0
        for h in range(total + 1):
            a = total - h
            prob += self.poisson_prob(h, lam_home) * self.poisson_prob(a, lam_away)
        return prob
    
    def total_over(self, n: float, lam_home: float, lam_away: float) -> float:
        """P(home + away > n) para total de goles."""
        # Calcular P(total <= n) y restar de 1
        prob_under = 0.0
        for total in range(int(n) + 1):
            prob_under += self.total_goals_prob(total, lam_home, lam_away)
        return 1 - prob_under
    
    def derive_probabilities(self, lam_home: float, lam_away: float) -> Dict:
        """Deriva TODAS las probabilidades de λ_home y λ_away."""
        
        # Asegurar λ mínimo para evitar problemas numéricos
        lam_home = max(0.1, lam_home)
        lam_away = max(0.1, lam_away)
        
        probs = {}
        
        # HOME Over/Under (derivado de λ_home)
        probs['home_over_05'] = self.poisson_over(0.5, lam_home)  # P(home >= 1)
        probs['home_over_15'] = self.poisson_over(1.5, lam_home)  # P(home >= 2)
        probs['home_over_25'] = self.poisson_over(2.5, lam_home)  # P(home >= 3)
        
        # AWAY Over/Under (derivado de λ_away)
        probs['away_over_05'] = self.poisson_over(0.5, lam_away)
        probs['away_over_15'] = self.poisson_over(1.5, lam_away)
        probs['away_over_25'] = self.poisson_over(2.5, lam_away)
        
        # TOTAL Over/Under (convolución)
        probs['total_over_25'] = self.total_over(2.5, lam_home, lam_away)
        probs['total_over_35'] = self.total_over(3.5, lam_home, lam_away)
        
        # BTTS = P(home >= 1) × P(away >= 1)
        probs['btts'] = probs['home_over_05'] * probs['away_over_05']
        
        return probs
    
    def get_score_matrix(self, lam_home: float, lam_away: float, max_goals: int = 6) -> np.ndarray:
        """Matriz de probabilidades de marcadores."""
        matrix = np.zeros((max_goals + 1, max_goals + 1))
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                matrix[h, a] = self.poisson_prob(h, lam_home) * self.poisson_prob(a, lam_away)
        return matrix
    
    def get_top_scores(self, lam_home: float, lam_away: float, top_n: int = 5) -> List[Tuple]:
        """Top N marcadores más probables."""
        matrix = self.get_score_matrix(lam_home, lam_away)
        scores = []
        for h in range(matrix.shape[0]):
            for a in range(matrix.shape[1]):
                scores.append((h, a, matrix[h, a]))
        scores.sort(key=lambda x: x[2], reverse=True)
        return scores[:top_n]
    
    # =========================================================================
    # ENTRENAMIENTO
    # =========================================================================
    
    def prepare_data(self, team_ids: List[int] = None, max_matches: int = None):
        """Prepara datos para regresión de λ."""
        print("\n⏳ Preparando datos para modelo Poisson...")
        
        if team_ids:
            placeholders = ','.join(str(t) for t in team_ids)
            query = text(f"""
                SELECT id, date, home_team_id, away_team_id, goals_home, goals_away
                FROM fixtures
                WHERE status_long = 'Match Finished'
                  AND goals_home IS NOT NULL
                  AND home_team_id IN ({placeholders})
                  AND away_team_id IN ({placeholders})
                ORDER BY date ASC
            """)
        else:
            query = text("""
                SELECT id, date, home_team_id, away_team_id, goals_home, goals_away
                FROM fixtures
                WHERE status_long = 'Match Finished'
                  AND goals_home IS NOT NULL
                ORDER BY date ASC
            """)
        
        matches = pd.read_sql_query(query, self.sad_engine)
        matches['date'] = pd.to_datetime(matches['date'])
        
        if max_matches:
            matches = matches.head(max_matches)
        
        print(f"   Partidos cargados: {len(matches)}")
        
        X_data = []
        y_home = []  # Goles del local (target para λ_home)
        y_away = []  # Goles del visitante (target para λ_away)
        feature_cols = self.get_feature_columns()
        
        for idx, row in matches.iterrows():
            features = self.create_features(row['home_team_id'], row['away_team_id'], row['date'])
            
            if features is None:
                continue
            
            fv = []
            valid = True
            for col in feature_cols:
                val = features.get(col, 0)
                if pd.isna(val):
                    valid = False
                    break
                fv.append(val)
            
            if not valid:
                continue
            
            X_data.append(fv)
            y_home.append(row['goals_home'])
            y_away.append(row['goals_away'])
            
            if len(X_data) % 1000 == 0:
                print(f"      {len(X_data)} procesados...")
        
        print(f"   ✓ {len(X_data)} partidos listos")
        
        return np.array(X_data), np.array(y_home), np.array(y_away), feature_cols
    
    def train(self, team_ids: List[int] = None, max_matches: int = None, test_ratio: float = 0.2):
        """Entrena modelos de regresión para λ_home y λ_away."""
        print("\n" + "="*70)
        print("🎓 ENTRENANDO PREDICTOR V6 - MODELO POISSON")
        print("="*70)
        
        X, y_home, y_away, feature_cols = self.prepare_data(team_ids, max_matches)
        
        if len(X) < 100:
            print("   ⚠️ Datos insuficientes")
            return
        
        split_idx = int(len(X) * (1 - test_ratio))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_home_train, y_home_test = y_home[:split_idx], y_home[split_idx:]
        y_away_train, y_away_test = y_away[:split_idx], y_away[split_idx:]
        
        print(f"\n   Train: {len(X_train)} | Test: {len(X_test)}")
        
        self.scaler.fit(X_train)
        X_train_scaled = self.scaler.transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        self.feature_cols = feature_cols
        
        # Entrenar modelo para λ_home
        print("\n   Entrenando modelo λ_home...")
        self.model_home = GradientBoostingRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.1,
            min_samples_split=20, random_state=42
        )
        self.model_home.fit(X_train_scaled, y_home_train)
        
        # Entrenar modelo para λ_away
        print("   Entrenando modelo λ_away...")
        self.model_away = GradientBoostingRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.1,
            min_samples_split=20, random_state=42
        )
        self.model_away.fit(X_train_scaled, y_away_train)
        
        # Evaluar
        y_home_pred = self.model_home.predict(X_test_scaled)
        y_away_pred = self.model_away.predict(X_test_scaled)
        
        print(f"\n   {'Modelo':<10} {'MAE':>8} {'RMSE':>8} {'R²':>8} {'Avg Real':>10} {'Avg Pred':>10}")
        print("   " + "-"*60)
        
        mae_home = mean_absolute_error(y_home_test, y_home_pred)
        rmse_home = np.sqrt(mean_squared_error(y_home_test, y_home_pred))
        r2_home = r2_score(y_home_test, y_home_pred)
        
        mae_away = mean_absolute_error(y_away_test, y_away_pred)
        rmse_away = np.sqrt(mean_squared_error(y_away_test, y_away_pred))
        r2_away = r2_score(y_away_test, y_away_pred)
        
        print(f"   {'λ_home':<10} {mae_home:>7.3f} {rmse_home:>8.3f} {r2_home:>7.3f} {y_home_test.mean():>10.2f} {y_home_pred.mean():>10.2f}")
        print(f"   {'λ_away':<10} {mae_away:>7.3f} {rmse_away:>8.3f} {r2_away:>7.3f} {y_away_test.mean():>10.2f} {y_away_pred.mean():>10.2f}")
        
        # Evaluar probabilidades derivadas
        print("\n   Evaluando probabilidades derivadas...")
        self._evaluate_derived_probs(X_test_scaled, y_home_test, y_away_test)
        
        self.is_trained = True
        self.save_model()
        
        # Feature importance
        print("\n   🔬 TOP 10 FEATURES (avg importance):")
        importances = (self.model_home.feature_importances_ + self.model_away.feature_importances_) / 2
        feat_imp = list(zip(feature_cols, importances))
        feat_imp.sort(key=lambda x: x[1], reverse=True)
        
        for i, (feat, imp) in enumerate(feat_imp[:10], 1):
            print(f"      {i:2d}. {feat:<25} {imp:.1%}")
        
        return {'mae_home': mae_home, 'mae_away': mae_away, 'r2_home': r2_home, 'r2_away': r2_away}
    
    def _evaluate_derived_probs(self, X_test, y_home_test, y_away_test):
        """Evalúa las probabilidades derivadas vs realidad."""
        y_home_pred = self.model_home.predict(X_test)
        y_away_pred = self.model_away.predict(X_test)
        
        # Calcular accuracy de Over/Under
        stats = {
            'home_over_05': {'correct': 0, 'total': 0},
            'home_over_15': {'correct': 0, 'total': 0},
            'away_over_05': {'correct': 0, 'total': 0},
            'away_over_15': {'correct': 0, 'total': 0},
            'total_over_25': {'correct': 0, 'total': 0},
            'total_over_35': {'correct': 0, 'total': 0},
            'btts': {'correct': 0, 'total': 0},
        }
        
        for i in range(len(X_test)):
            lam_h = max(0.1, y_home_pred[i])
            lam_a = max(0.1, y_away_pred[i])
            
            probs = self.derive_probabilities(lam_h, lam_a)
            
            gh = y_home_test[i]
            ga = y_away_test[i]
            total = gh + ga
            
            actuals = {
                'home_over_05': gh >= 1,
                'home_over_15': gh >= 2,
                'away_over_05': ga >= 1,
                'away_over_15': ga >= 2,
                'total_over_25': total >= 3,
                'total_over_35': total >= 4,
                'btts': gh >= 1 and ga >= 1,
            }
            
            for key, actual in actuals.items():
                predicted = probs[key] >= 0.5
                stats[key]['total'] += 1
                if predicted == actual:
                    stats[key]['correct'] += 1
        
        print(f"\n   {'Línea':<15} {'Accuracy':>10}")
        print("   " + "-"*30)
        
        for key in ['home_over_05', 'home_over_15', 'away_over_05', 'away_over_15', 
                    'total_over_25', 'total_over_35', 'btts']:
            s = stats[key]
            if s['total'] > 0:
                acc = s['correct'] / s['total']
                print(f"   {key:<15} {acc:>9.1%}")
    
    def save_model(self):
        if not self.is_trained:
            return
        
        joblib.dump({
            'model_home': self.model_home,
            'model_away': self.model_away,
            'scaler': self.scaler,
            'feature_cols': self.feature_cols,
            'trained_at': datetime.now().isoformat(),
            'version': 'V6.1-Poisson-Calibrado',
        }, self.model_path)
        print(f"\n   💾 Modelo guardado: {self.model_path}")
    
    def load_model(self) -> bool:
        if not os.path.exists(self.model_path):
            return False
        
        try:
            data = joblib.load(self.model_path)
            self.model_home = data['model_home']
            self.model_away = data['model_away']
            self.scaler = data['scaler']
            self.feature_cols = data['feature_cols']
            self.is_trained = True
            print(f"   ✓ Modelo V6 Poisson cargado ({data['trained_at']})")
            return True
        except Exception as e:
            print(f"   ⚠️ Error: {e}")
            return False
    
    # =========================================================================
    # PREDICCIÓN
    # =========================================================================
    
    def predict(self, home_id: int, away_id: int, match_date: datetime = None) -> Dict:
        """Predice λ y deriva todas las probabilidades."""
        if not self.is_trained:
            raise ValueError("Modelo no entrenado")
        
        if match_date is None:
            match_date = datetime.now()
        
        features = self.create_features(home_id, away_id, match_date)
        if features is None:
            return None
        
        fv = [features.get(col, 0) for col in self.feature_cols]
        X = self.scaler.transform([fv])
        
        # Predecir λ
        lam_home = max(0.1, self.model_home.predict(X)[0])
        lam_away = max(0.1, self.model_away.predict(X)[0])
        
        # Derivar probabilidades
        probs = self.derive_probabilities(lam_home, lam_away)
        
        # Top marcadores
        top_scores = self.get_top_scores(lam_home, lam_away, top_n=5)
        
        home_level = features['home_level']
        away_level = features['away_level']
        home_level_bin = int(features['home_level_bin'])
        away_level_bin = int(features['away_level_bin'])
        
        return {
            'home_id': home_id,
            'away_id': away_id,
            'home_name': self.get_team_name(home_id),
            'away_name': self.get_team_name(away_id),
            'lambda_home': lam_home,
            'lambda_away': lam_away,
            'lambda_total': lam_home + lam_away,
            'home_level': home_level,
            'away_level': away_level,
            'home_level_bin': home_level_bin,
            'away_level_bin': away_level_bin,
            'level_bin_diff': home_level_bin - away_level_bin,
            'probs': probs,
            'top_scores': top_scores,
        }
    
    def generate_suggestions(self, probs: Dict, home_bin: int, away_bin: int) -> List[Dict]:
        """Genera sugerencias de apuestas."""
        suggestions = []
        
        def add_suggestion(key, prob, is_over=True):
            th = self.THRESHOLDS.get(key, {'high': 0.7, 'medium': 0.6})
            
            if is_over:
                if prob >= th['high']:
                    confidence = '🔥 ALTA'
                elif prob >= th['medium']:
                    confidence = '⚠️ MEDIA'
                else:
                    return
            else:
                if prob <= th['high']:
                    confidence = '🔥 ALTA'
                elif prob <= th['medium']:
                    confidence = '⚠️ MEDIA'
                else:
                    return
            
            suggestions.append({
                'tipo': key.upper().replace('_', ' '),
                'prob': prob if is_over else (1 - prob),
                'confianza': confidence,
            })
        
        p = probs
        
        # HOME
        add_suggestion('home_over_05', p['home_over_05'], True)
        add_suggestion('home_under_05', p['home_over_05'], False)
        add_suggestion('home_over_15', p['home_over_15'], True)
        add_suggestion('home_under_15', p['home_over_15'], False)
        add_suggestion('home_over_25', p['home_over_25'], True)
        add_suggestion('home_under_25', p['home_over_25'], False)
        
        # AWAY
        add_suggestion('away_over_05', p['away_over_05'], True)
        add_suggestion('away_under_05', p['away_over_05'], False)
        add_suggestion('away_over_15', p['away_over_15'], True)
        add_suggestion('away_under_15', p['away_over_15'], False)
        add_suggestion('away_over_25', p['away_over_25'], True)
        add_suggestion('away_under_25', p['away_over_25'], False)
        
        # TOTAL
        add_suggestion('total_over_25', p['total_over_25'], True)
        add_suggestion('total_under_25', p['total_over_25'], False)
        add_suggestion('total_over_35', p['total_over_35'], True)
        add_suggestion('total_under_35', p['total_over_35'], False)
        
        # BTTS
        add_suggestion('btts_yes', p['btts'], True)
        add_suggestion('btts_no', p['btts'], False)
        
        suggestions.sort(key=lambda x: x['prob'], reverse=True)
        return suggestions
    
    def format_prediction(self, pred: Dict) -> str:
        """Formatea predicción con formato compatible V5 + extendido."""
        p = pred['probs']
        home = pred['home_name']
        away = pred['away_name']
        
        lam_home = pred['lambda_home']
        lam_away = pred['lambda_away']
        lam_total = pred['lambda_total']
        
        home_lvl = pred['home_level']
        away_lvl = pred['away_level']
        home_bin = pred['home_level_bin']
        away_bin = pred['away_level_bin']
        bin_diff = pred['level_bin_diff']
        
        lines = []
        lines.append(f"\n{'═'*75}")
        lines.append(f"⚽ {home} vs {away}")
        lines.append(f"{'═'*75}")
        
        # === FORMATO EXTENDIDO: Goles esperados (λ) ===
        lines.append(f"\n📊 GOLES ESPERADOS (λ):")
        lines.append(f"   {home[:20]:<20} λ = {lam_home:.2f} goles")
        lines.append(f"   {away[:20]:<20} λ = {lam_away:.2f} goles")
        lines.append(f"   {'Total':<20} λ = {lam_total:.2f} goles")
        
        # Niveles con bins
        lines.append(f"\n📊 NIVELES:")
        lines.append(f"   {home[:20]:<20} Bin {home_bin}/9 ({home_lvl:.2f}) - {self.get_level_description(home_bin)}")
        lines.append(f"   {away[:20]:<20} Bin {away_bin}/9 ({away_lvl:.2f}) - {self.get_level_description(away_bin)}")
        
        if abs(bin_diff) >= 3:
            favorito = home if bin_diff > 0 else away
            lines.append(f"   → Favorito claro: {favorito} (diff: {bin_diff:+d} bins)")
        elif abs(bin_diff) >= 1:
            favorito = home if bin_diff > 0 else away
            lines.append(f"   → Leve ventaja: {favorito} (diff: {bin_diff:+d} bins)")
        else:
            lines.append(f"   → Partido equilibrado (diff: {bin_diff:+d} bins)")
        
        # === FORMATO COMPATIBLE V5: Tabla de probabilidades ===
        lines.append(f"\n┌─────────────────────┬─────────┬─────────┬─────────┐")
        lines.append(f"│                     │ Over 0.5│ Over 1.5│ Over 2.5│")
        lines.append(f"├─────────────────────┼─────────┼─────────┼─────────┤")
        lines.append(f"│ {home[:19]:<19} │  {p['home_over_05']:>5.0%}  │  {p['home_over_15']:>5.0%}  │  {p['home_over_25']:>5.0%}  │")
        lines.append(f"│ {away[:19]:<19} │  {p['away_over_05']:>5.0%}  │  {p['away_over_15']:>5.0%}  │  {p['away_over_25']:>5.0%}  │")
        lines.append(f"└─────────────────────┴─────────┴─────────┴─────────┘")
        
        lines.append(f"\n📊 TOTAL: Over 2.5 = {p['total_over_25']:.0%} | Over 3.5 = {p['total_over_35']:.0%}")
        lines.append(f"📊 BTTS (ambos anotan): {p['btts']:.0%}")
        
        # === FORMATO EXTENDIDO: Resultados más probables ===
        lines.append(f"\n🎯 RESULTADOS MÁS PROBABLES:")
        for h, a, prob in pred['top_scores']:
            lines.append(f"   {int(h)}-{int(a)}: {prob:.1%}")
        
        # Sugerencias
        suggestions = self.generate_suggestions(p, home_bin, away_bin)
        
        if suggestions:
            lines.append(f"\n💰 SUGERENCIAS DE APUESTAS:")
            for s in suggestions[:8]:
                lines.append(f"   {s['confianza']} {s['tipo']:<20} ({s['prob']:.0%})")
        else:
            lines.append(f"\n💰 Sin sugerencias claras (probabilidades muy equilibradas)")
        
        return '\n'.join(lines)
    
    # =========================================================================
    # BACKTESTING
    # =========================================================================
    
    def backtest(self, n_teams: int = 10, n_matches: int = 5):
        """Backtesting del modelo Poisson."""
        if not self.is_trained:
            if not self.load_model():
                print("⚠️ Entrena primero")
                return
        
        print("\n" + "="*75)
        print(f"🎯 BACKTESTING V6 POISSON: {n_teams} equipos × {n_matches} partidos")
        print("="*75)
        
        query = text("""
            SELECT team_id, COUNT(*) as n FROM constants
            GROUP BY team_id ORDER BY n DESC LIMIT :limit
        """)
        
        with self.constants_engine.connect() as conn:
            top_teams = [r[0] for r in conn.execute(query, {'limit': n_teams}).fetchall()]
        
        stats = {
            'home_over_05': {'correct': 0, 'total': 0},
            'home_over_15': {'correct': 0, 'total': 0},
            'home_over_25': {'correct': 0, 'total': 0},
            'away_over_05': {'correct': 0, 'total': 0},
            'away_over_15': {'correct': 0, 'total': 0},
            'away_over_25': {'correct': 0, 'total': 0},
            'total_over_25': {'correct': 0, 'total': 0},
            'total_over_35': {'correct': 0, 'total': 0},
            'btts': {'correct': 0, 'total': 0},
        }
        stats['suggestions'] = {'correct': 0, 'total': 0}
        stats['lambda_errors'] = []
        
        all_matches = []
        
        for team_id in top_teams:
            query = text("""
                SELECT id, date, home_team_id, away_team_id, goals_home, goals_away
                FROM fixtures
                WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                  AND status_long = 'Match Finished'
                ORDER BY date DESC
                LIMIT :n
            """)
            
            matches = pd.read_sql_query(query, self.sad_engine, 
                                        params={'team_id': team_id, 'n': n_matches})
            
            for _, row in matches.iterrows():
                if row['id'] in [m['id'] for m in all_matches]:
                    continue
                all_matches.append(row.to_dict())
        
        print(f"\n   Evaluando {len(all_matches)} partidos únicos...")
        
        for match in all_matches:
            pred = self.predict(match['home_team_id'], match['away_team_id'], match['date'])
            if pred is None:
                continue
            
            p = pred['probs']
            gh = match['goals_home']
            ga = match['goals_away']
            total = gh + ga
            
            # Error de λ
            stats['lambda_errors'].append({
                'home_error': abs(pred['lambda_home'] - gh),
                'away_error': abs(pred['lambda_away'] - ga),
            })
            
            actuals = {
                'home_over_05': gh >= 1,
                'home_over_15': gh >= 2,
                'home_over_25': gh >= 3,
                'away_over_05': ga >= 1,
                'away_over_15': ga >= 2,
                'away_over_25': ga >= 3,
                'total_over_25': total >= 3,
                'total_over_35': total >= 4,
                'btts': gh >= 1 and ga >= 1,
            }
            
            for name, actual in actuals.items():
                predicted = p[name] >= 0.5
                stats[name]['total'] += 1
                if predicted == actual:
                    stats[name]['correct'] += 1
            
            # Evaluar sugerencias
            suggestions = self.generate_suggestions(p, pred['home_level_bin'], pred['away_level_bin'])
            for s in suggestions:
                stats['suggestions']['total'] += 1
                tipo = s['tipo'].lower().replace(' ', '_')
                
                acerto = False
                if 'home_over_05' in tipo and gh >= 1:
                    acerto = True
                elif 'home_under_05' in tipo and gh == 0:
                    acerto = True
                elif 'home_over_15' in tipo and gh >= 2:
                    acerto = True
                elif 'home_under_15' in tipo and gh <= 1:
                    acerto = True
                elif 'home_over_25' in tipo and gh >= 3:
                    acerto = True
                elif 'home_under_25' in tipo and gh <= 2:
                    acerto = True
                elif 'away_over_05' in tipo and ga >= 1:
                    acerto = True
                elif 'away_under_05' in tipo and ga == 0:
                    acerto = True
                elif 'away_over_15' in tipo and ga >= 2:
                    acerto = True
                elif 'away_under_15' in tipo and ga <= 1:
                    acerto = True
                elif 'away_over_25' in tipo and ga >= 3:
                    acerto = True
                elif 'away_under_25' in tipo and ga <= 2:
                    acerto = True
                elif 'total_over_25' in tipo and total >= 3:
                    acerto = True
                elif 'total_under_25' in tipo and total <= 2:
                    acerto = True
                elif 'total_over_35' in tipo and total >= 4:
                    acerto = True
                elif 'total_under_35' in tipo and total <= 3:
                    acerto = True
                elif 'btts_yes' in tipo and (gh >= 1 and ga >= 1):
                    acerto = True
                elif 'btts_no' in tipo and (gh == 0 or ga == 0):
                    acerto = True
                
                if acerto:
                    stats['suggestions']['correct'] += 1
        
        # Resultados
        print(f"\n{'─'*75}")
        print(f"📊 ERROR DE λ (goles esperados)")
        print(f"{'─'*75}")
        
        if stats['lambda_errors']:
            home_errors = [e['home_error'] for e in stats['lambda_errors']]
            away_errors = [e['away_error'] for e in stats['lambda_errors']]
            print(f"\n   λ_home MAE: {np.mean(home_errors):.3f} goles")
            print(f"   λ_away MAE: {np.mean(away_errors):.3f} goles")
        
        print(f"\n{'─'*75}")
        print(f"📊 RESULTADOS POR LÍNEA")
        print(f"{'─'*75}")
        
        print(f"\n   {'Línea':<15} {'Aciertos':>12} {'Accuracy':>10}")
        print("   " + "-"*42)
        
        for name in ['home_over_05', 'home_over_15', 'home_over_25',
                     'away_over_05', 'away_over_15', 'away_over_25',
                     'total_over_25', 'total_over_35', 'btts']:
            s = stats[name]
            if s['total'] > 0:
                acc = s['correct'] / s['total']
                print(f"   {name:<15} {s['correct']:>4}/{s['total']:<5} {acc:>9.1%}")
        
        print(f"\n{'─'*75}")
        s = stats['suggestions']
        if s['total'] > 0:
            acc = s['correct'] / s['total']
            print(f"💰 SUGERENCIAS: {s['correct']}/{s['total']} ({acc:.1%})")
        print(f"{'─'*75}")
        
        return stats
    
    def predict_upcoming(self, limit: int = 10):
        """Predice próximos partidos."""
        if not self.is_trained:
            if not self.load_model():
                return
        
        print("\n" + "="*75)
        print("🔮 PRÓXIMOS PARTIDOS (MODELO POISSON)")
        print("="*75)
        
        query = text("""
            SELECT id, date, home_team_id, away_team_id, league_id
            FROM fixtures
            WHERE status_long IN ('Not Started', 'Scheduled')
              AND date >= date('now')
              AND date <= date('now', '+7 days')
            ORDER BY date ASC
            LIMIT :limit
        """)
        
        upcoming = pd.read_sql_query(query, self.sad_engine, params={'limit': limit * 2})
        
        if upcoming.empty:
            print("   No hay partidos programados")
            return
        
        count = 0
        for _, row in upcoming.iterrows():
            pred = self.predict(row['home_team_id'], row['away_team_id'])
            if pred is None:
                continue
            
            print(self.format_prediction(pred))
            count += 1
            
            if count >= limit:
                break
    
    # =========================================================================
    # MÉTODOS PARA INTEGRACIÓN UI
    # =========================================================================
    
    def predict_fixture(self, fixture_id: int) -> Optional[Dict]:
        """
        Predice un partido por su ID.
        Útil para integración con UI.
        
        Args:
            fixture_id: ID del fixture en sad.db
            
        Returns:
            Dict con predicción completa o None
        """
        if not self.is_trained:
            if not self.load_model():
                return None
        
        query = text("""
            SELECT id, date, home_team_id, away_team_id, league_id
            FROM fixtures
            WHERE id = :fixture_id
        """)
        
        with self.sad_engine.connect() as conn:
            result = conn.execute(query, {'fixture_id': fixture_id}).fetchone()
        
        if not result:
            return None
        
        fixture_id, date, home_id, away_id, league_id = result
        
        pred = self.predict(home_id, away_id, date)
        if pred:
            pred['fixture_id'] = fixture_id
            pred['league_id'] = league_id
            pred['date'] = date
        
        return pred
    
    def predict_fixtures_batch(self, fixture_ids: List[int]) -> List[Dict]:
        """
        Predice múltiples partidos.
        
        Args:
            fixture_ids: Lista de IDs de fixtures
            
        Returns:
            Lista de predicciones
        """
        results = []
        for fid in fixture_ids:
            pred = self.predict_fixture(fid)
            if pred:
                results.append(pred)
        return results
    
    def get_upcoming_fixtures(self, days: int = 7, league_id: int = None) -> pd.DataFrame:
        """
        Obtiene próximos partidos con predicciones.
        
        Args:
            days: Días hacia adelante
            league_id: Filtrar por liga (opcional)
            
        Returns:
            DataFrame con partidos y predicciones
        """
        if not self.is_trained:
            if not self.load_model():
                return pd.DataFrame()
        
        if league_id:
            query = text("""
                SELECT id, date, home_team_id, away_team_id, league_id
                FROM fixtures
                WHERE status_long IN ('Not Started', 'Scheduled')
                  AND date >= date('now')
                  AND date <= date('now', :days || ' days')
                  AND league_id = :league_id
                ORDER BY date ASC
            """)
            params = {'days': days, 'league_id': league_id}
        else:
            query = text("""
                SELECT id, date, home_team_id, away_team_id, league_id
                FROM fixtures
                WHERE status_long IN ('Not Started', 'Scheduled')
                  AND date >= date('now')
                  AND date <= date('now', :days || ' days')
                ORDER BY date ASC
            """)
            params = {'days': days}
        
        fixtures = pd.read_sql_query(query, self.sad_engine, params=params)
        
        if fixtures.empty:
            return pd.DataFrame()
        
        predictions = []
        for _, row in fixtures.iterrows():
            pred = self.predict(row['home_team_id'], row['away_team_id'])
            if pred is None:
                continue
            
            predictions.append({
                'fixture_id': row['id'],
                'date': row['date'],
                'league_id': row['league_id'],
                'home_name': pred['home_name'],
                'away_name': pred['away_name'],
                'lambda_home': pred['lambda_home'],
                'lambda_away': pred['lambda_away'],
                'lambda_total': pred['lambda_total'],
                'home_level_bin': pred['home_level_bin'],
                'away_level_bin': pred['away_level_bin'],
                'home_over_05': pred['probs']['home_over_05'],
                'home_over_15': pred['probs']['home_over_15'],
                'away_over_05': pred['probs']['away_over_05'],
                'away_over_15': pred['probs']['away_over_15'],
                'total_over_25': pred['probs']['total_over_25'],
                'total_over_35': pred['probs']['total_over_35'],
                'btts': pred['probs']['btts'],
                'top_score_1': f"{pred['top_scores'][0][0]}-{pred['top_scores'][0][1]}",
                'top_score_1_prob': pred['top_scores'][0][2],
            })
        
        return pd.DataFrame(predictions)
    
    def export_predictions_csv(self, output_path: str, days: int = 7, league_id: int = None):
        """
        Exporta predicciones a CSV.
        
        Args:
            output_path: Ruta del archivo CSV
            days: Días hacia adelante
            league_id: Filtrar por liga (opcional)
        """
        df = self.get_upcoming_fixtures(days=days, league_id=league_id)
        
        if df.empty:
            print("   No hay predicciones para exportar")
            return
        
        df.to_csv(output_path, index=False)
        print(f"   ✓ Exportado: {output_path} ({len(df)} partidos)")


def main():
    predictor = MLGoalsPredictorV6()
    
    print("\n🚀 PREDICTOR V6.1 - MODELO POISSON (ENTRENAMIENTO COMPLETO)")
    
    # Entrenar con TODA la DB (sin filtros)
    predictor.train(team_ids=None, max_matches=None, test_ratio=0.2)
    
    # Backtest ampliado
    predictor.backtest(n_teams=20, n_matches=10)
    
    # Próximos partidos
    predictor.predict_upcoming(limit=5)
    
    print("\n" + "="*75)
    print("✅ COMPLETADO")
    print("="*75)


def train_full_db():
    """
    Entrenamiento completo para uso en producción.
    Diseñado para ser llamado desde UI.
    
    Returns:
        MLGoalsPredictorV6: Predictor entrenado
    """
    predictor = MLGoalsPredictorV6()
    
    print("\n" + "="*70)
    print("🎓 ENTRENAMIENTO COMPLETO V6 POISSON")
    print("="*70)
    
    # Contar partidos disponibles
    query = text("""
        SELECT COUNT(*) FROM fixtures 
        WHERE status_long = 'Match Finished' AND goals_home IS NOT NULL
    """)
    
    with predictor.sad_engine.connect() as conn:
        total_matches = conn.execute(query).scalar()
    
    print(f"\n   📊 Partidos disponibles: {total_matches:,}")
    
    # Entrenar
    results = predictor.train(team_ids=None, max_matches=None, test_ratio=0.15)
    
    if results:
        print(f"\n   ✓ Modelo entrenado exitosamente")
        print(f"   ✓ MAE λ_home: {results['mae_home']:.3f}")
        print(f"   ✓ MAE λ_away: {results['mae_away']:.3f}")
    
    return predictor


if __name__ == "__main__":
    main()