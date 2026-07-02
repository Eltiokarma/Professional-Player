# src/utils/ml_data_collector.py
"""
Recolector de datos para el sistema de predicción ML.
Centraliza la obtención de datos desde sad.db, constants.db y levels.db
para alimentar al GlobalConstantPredictor.

🔧 CORREGIDO: Ahora combina k_positivo + k_negativo para el análisis
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

from data.database_manager import engine, CONST_ENGINE, BASE_DIR
from data.data_models.teams import Team

logger = logging.getLogger(__name__)


class MLDataCollector:
    """
    Recolecta y prepara datos para GlobalConstantPredictor.
    
    Responsabilidades:
    - Obtener próximo fixture de un equipo
    - Obtener últimos N partidos jugados
    - Preparar inputs para predicción ML
    - Validar predicciones históricas
    """
    
    # Constantes que el modelo puede predecir
    PREDICTABLE_CONSTANTS = [
        'k_local',
        'k_visita', 
        'k_goles_anotado',
        'k_goles_recibido',
        'k_goles_local_anotado',
        'k_goles_local_recibido',
        'k_goles_visita_anotado',
        'k_goles_visita_recibido',
    ]
    
    def __init__(self):
        """Inicializa conexiones a las bases de datos."""
        self.Session = sessionmaker(bind=engine)
        self.session = self.Session()
        
        # Engine para levels.db
        levels_db_path = os.path.join(BASE_DIR, 'levels.db')
        self.levels_engine = create_engine(f'sqlite:///{levels_db_path}', echo=False)
        
        # Engine para discreto.db (para niveles discretos)
        discreto_db_path = os.path.join(BASE_DIR, 'discreto.db')
        if os.path.exists(discreto_db_path):
            self.discreto_engine = create_engine(f'sqlite:///{discreto_db_path}', echo=False)
        else:
            self.discreto_engine = None
        
        logger.info("MLDataCollector inicializado")
    
    def close(self):
        """Cierra la sesión de base de datos."""
        try:
            self.session.close()
        except:
            pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    # =========================================================================
    # MÉTODOS PARA OBTENER FIXTURES
    # =========================================================================
    
    def get_next_fixture(self, team_id: int) -> Optional[Dict]:
        """
        Obtiene el próximo partido programado del equipo.
        
        🔧 CORREGIDO: Solo busca partidos con fecha FUTURA para evitar
        partidos "fantasma" (status NS pero ya jugados).
        
        Args:
            team_id: ID del equipo
            
        Returns:
            Dict con info del fixture o None si no hay próximo partido
        """
        try:
            from datetime import datetime, timedelta
            
            # Usar fecha actual con margen de 1 día hacia atrás
            cutoff_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
            
            # Buscar fixture con status pendiente y fecha futura
            query = text("""
                SELECT 
                    f.id as fixture_id,
                    f.date,
                    f.home_team_id,
                    f.away_team_id,
                    f.league_id,
                    f.status_short,
                    f.status_long,
                    ht.name as home_team_name,
                    at.name as away_team_name
                FROM fixtures f
                JOIN teams ht ON f.home_team_id = ht.id
                JOIN teams at ON f.away_team_id = at.id
                WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
                  AND f.status_short IN ('NS', 'TBD', 'PST')
                  AND f.date > :cutoff_date
                ORDER BY f.date ASC
                LIMIT 1
            """)
            
            with engine.connect() as conn:
                result = conn.execute(query, {
                    "team_id": team_id,
                    "cutoff_date": cutoff_date
                }).fetchone()
            
            if not result:
                logger.info(f"Equipo {team_id}: No hay próximo partido con fecha futura")
                return None
            
            is_home = result.home_team_id == team_id
            rival_id = result.away_team_id if is_home else result.home_team_id
            rival_name = result.away_team_name if is_home else result.home_team_name
            
            return {
                'fixture_id': result.fixture_id,
                'date': result.date,
                'is_home': is_home,
                'condition': 'Local' if is_home else 'Visita',
                'rival_id': rival_id,
                'rival_name': rival_name,
                'league_id': result.league_id,
                'home_team_name': result.home_team_name,
                'away_team_name': result.away_team_name,
                'status': result.status_long,
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo próximo fixture: {e}")
            return None

    def get_last_n_fixtures(self, team_id: int, n: int = 5) -> List[Dict]:
        """
        Obtiene los últimos N partidos jugados del equipo.
        
        Args:
            team_id: ID del equipo
            n: Número de partidos a obtener
            
        Returns:
            Lista de dicts con info de cada fixture
        """
        try:
            # Usar status_short = 'FT' (Full Time) o status_long = 'Match Finished'
            query = text("""
                SELECT 
                    f.id as fixture_id,
                    f.date,
                    f.home_team_id,
                    f.away_team_id,
                    f.goals_home,
                    f.goals_away,
                    f.league_id,
                    ht.name as home_team_name,
                    at.name as away_team_name
                FROM fixtures f
                JOIN teams ht ON f.home_team_id = ht.id
                JOIN teams at ON f.away_team_id = at.id
                WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
                  AND f.status_short = 'FT'
                ORDER BY f.date DESC
                LIMIT :limit
            """)
            
            with engine.connect() as conn:
                results = conn.execute(query, {"team_id": team_id, "limit": n}).fetchall()
            
            fixtures = []
            for row in results:
                is_home = row.home_team_id == team_id
                rival_id = row.away_team_id if is_home else row.home_team_id
                rival_name = row.away_team_name if is_home else row.home_team_name
                goals_for = row.goals_home if is_home else row.goals_away
                goals_against = row.goals_away if is_home else row.goals_home
                
                fixtures.append({
                    'fixture_id': row.fixture_id,
                    'date': row.date,
                    'is_home': is_home,
                    'condition': 'Local' if is_home else 'Visita',
                    'rival_id': rival_id,
                    'rival_name': rival_name,
                    'goals_for': goals_for,
                    'goals_against': goals_against,
                    'league_id': row.league_id,
                })
            
            return fixtures
            
        except Exception as e:
            logger.error(f"Error obteniendo últimos fixtures: {e}")
            return []
    
    # =========================================================================
    # MÉTODOS PARA OBTENER CONSTANTES
    # =========================================================================
    
    def get_team_constants_at_fixture(self, team_id: int, fixture_id: int) -> Optional[Dict]:
        """
        Obtiene las constantes del equipo para un fixture específico.
        """
        try:
            query = text("""
                SELECT *
                FROM constants
                WHERE team_id = :team_id AND fixture_id = :fixture_id
            """)
            
            df = pd.read_sql_query(query, CONST_ENGINE, params={
                "team_id": team_id, 
                "fixture_id": fixture_id
            })
            
            if df.empty:
                return None
            
            return df.iloc[0].to_dict()
            
        except Exception as e:
            logger.error(f"Error obteniendo constantes en fixture: {e}")
            return None
    
    def get_team_constants_before_date(self, team_id: int, before_date) -> Optional[Dict]:
        """
        Obtiene las últimas constantes del equipo antes de una fecha.
        """
        try:
            if isinstance(before_date, str):
                before_date = datetime.fromisoformat(before_date.replace('Z', '+00:00'))
            
            query = text("""
                SELECT *
                FROM constants
                WHERE team_id = :team_id AND date < :before_date
                ORDER BY date DESC
                LIMIT 1
            """)
            
            date_str = before_date.strftime('%Y-%m-%d %H:%M:%S') if hasattr(before_date, 'strftime') else str(before_date)
            
            df = pd.read_sql_query(query, CONST_ENGINE, params={
                "team_id": team_id,
                "before_date": date_str
            })
            
            if df.empty:
                return None
            
            return df.iloc[0].to_dict()
            
        except Exception as e:
            logger.error(f"Error obteniendo constantes antes de fecha: {e}")
            return None
    
    def get_team_latest_constants(self, team_id: int) -> Optional[Dict]:
        """
        Obtiene las constantes más recientes del equipo.
        """
        try:
            query = text("""
                SELECT *
                FROM constants
                WHERE team_id = :team_id
                ORDER BY date DESC
                LIMIT 1
            """)
            
            df = pd.read_sql_query(query, CONST_ENGINE, params={"team_id": team_id})
            
            if df.empty:
                return None
            
            return df.iloc[0].to_dict()
            
        except Exception as e:
            logger.error(f"Error obteniendo últimas constantes: {e}")
            return None
    
    # =========================================================================
    # 🔧 NUEVO: Método para calcular K combinado (positivo + negativo)
    # =========================================================================
    
    def _get_combined_k(self, constants: Dict, constant_type: str) -> float:
        """
        Calcula el K combinado (positivo + negativo) para un tipo de constante.
        
        Para tipos 'k', 'k_local', 'k_visita': suma positivo + negativo
        Para otros tipos (goles): usa el valor directo
        
        Args:
            constants: Dict con las constantes del equipo
            constant_type: Tipo de constante ('k_local', 'k_visita', etc.)
            
        Returns:
            float: Valor K combinado (puede ser negativo)
        """
        if constants is None:
            return 0.0
        
        # Mapeo de tipo a columnas positivo/negativo
        combined_types = {
            'k': ('k_positivo', 'k_negativo'),
            'k_local': ('k_positivo_local', 'k_negativo_local'),
            'k_visita': ('k_positivo_visita', 'k_negativo_visita'),
        }
        
        if constant_type in combined_types:
            col_pos, col_neg = combined_types[constant_type]
            k_pos = float(constants.get(col_pos, 0) or 0)
            k_neg = float(constants.get(col_neg, 0) or 0)
            return k_pos + k_neg
        else:
            # Para goles y otros, usar el valor directo
            direct_cols = {
                'k_goles_anotado': 'k_goles_anotado',
                'k_goles_recibido': 'k_goles_recibido',
                'k_goles_local_anotado': 'k_goles_local_anotado',
                'k_goles_local_recibido': 'k_goles_local_recibido',
                'k_goles_visita_anotado': 'k_goles_visita_anotado',
                'k_goles_visita_recibido': 'k_goles_visita_recibido',
            }
            col = direct_cols.get(constant_type, 'k_positivo')
            return float(constants.get(col, 0) or 0)
    
    # =========================================================================
    # MÉTODOS PARA OBTENER NIVELES
    # =========================================================================
    
    def get_team_level_at_date(self, team_id: int, at_date) -> float:
        """
        Obtiene el nivel del equipo en una fecha específica.
        Retorna nivel continuo de levels.db.
        """
        try:
            if isinstance(at_date, str):
                at_date = datetime.fromisoformat(at_date.replace('Z', '+00:00'))
            
            query = text("""
                SELECT level
                FROM team_levels
                WHERE team_id = :team_id AND date <= :at_date
                ORDER BY date DESC
                LIMIT 1
            """)
            
            date_str = at_date.strftime('%Y-%m-%d %H:%M:%S') if hasattr(at_date, 'strftime') else str(at_date)
            
            with self.levels_engine.connect() as conn:
                result = conn.execute(query, {
                    "team_id": team_id,
                    "at_date": date_str
                }).fetchone()
            
            return float(result[0]) if result else 0.5
            
        except Exception as e:
            logger.warning(f"Error obteniendo nivel de equipo {team_id}: {e}")
            return 0.5
    
    def get_team_discrete_level(self, team_id: int, fixture_id: int) -> int:
        """
        Obtiene el nivel discreto (0-9) de discreto.db para un fixture.
        """
        if not self.discreto_engine:
            return 5  # Default medio
        
        try:
            query = text("""
                SELECT nivel_equipo
                FROM processed_matches
                WHERE equipo_id = :team_id AND fixture_id = :fixture_id
                LIMIT 1
            """)
            
            with self.discreto_engine.connect() as conn:
                result = conn.execute(query, {
                    "team_id": team_id,
                    "fixture_id": fixture_id
                }).fetchone()
            
            return int(result[0]) if result else 5
            
        except Exception as e:
            logger.warning(f"Error obteniendo nivel discreto: {e}")
            return 5
    
    def get_discrete_levels_for_match(self, team_id: int, rival_id: int, fixture_id: int) -> Dict:
        """
        Obtiene niveles discretos de ambos equipos para un partido.
        """
        if not self.discreto_engine:
            return {'nivel_equipo': 5, 'nivel_rival': 5}
        
        try:
            query = text("""
                SELECT nivel_equipo, nivel_rival
                FROM processed_matches
                WHERE equipo_id = :team_id AND fixture_id = :fixture_id
                LIMIT 1
            """)
            
            with self.discreto_engine.connect() as conn:
                result = conn.execute(query, {
                    "team_id": team_id,
                    "fixture_id": fixture_id
                }).fetchone()
            
            if result:
                return {'nivel_equipo': int(result[0]), 'nivel_rival': int(result[1])}
            
            return {'nivel_equipo': 5, 'nivel_rival': 5}
            
        except Exception as e:
            logger.warning(f"Error obteniendo niveles discretos: {e}")
            return {'nivel_equipo': 5, 'nivel_rival': 5}
    
    # =========================================================================
    # MÉTODOS PARA PREPARAR INPUTS DEL ML
    # =========================================================================
    
    def get_prediction_inputs(
        self, 
        team_id: int, 
        rival_id: int, 
        fixture_date,
        fixture_id: int,
        is_home: bool,
        constant_type: str,
        league_id: int = None
    ) -> Optional[Dict]:
        """
        Prepara todos los inputs necesarios para GlobalConstantPredictor.predict().
        
        🔧 CORREGIDO: Ahora usa _get_combined_k para combinar k_positivo + k_negativo
        
        Args:
            team_id: ID del equipo
            rival_id: ID del rival
            fixture_date: Fecha del partido
            fixture_id: ID del fixture
            is_home: True si el equipo juega de local
            constant_type: Tipo de constante a predecir
            league_id: ID de la liga
            
        Returns:
            Dict con todos los parámetros para predict()
        """
        try:
            if isinstance(fixture_date, str):
                fixture_date = datetime.fromisoformat(fixture_date.replace('Z', '+00:00'))
            
            # Obtener niveles discretos si existen
            levels = self.get_discrete_levels_for_match(team_id, rival_id, fixture_id)
            nivel_equipo = levels['nivel_equipo']
            nivel_rival = levels['nivel_rival']
            
            # Constantes previas del equipo
            team_prev_constants = self.get_team_constants_before_date(team_id, fixture_date)
            if not team_prev_constants:
                logger.warning(f"No hay constantes previas para equipo {team_id}")
                return None
            
            # Constantes previas del rival
            rival_prev_constants = self.get_team_constants_before_date(rival_id, fixture_date)
            
            # 🔧 CORREGIDO: Usar K combinado (positivo + negativo)
            prev_team_k = self._get_combined_k(team_prev_constants, constant_type)
            
            # K del rival (invertir local/visita)
            if rival_prev_constants:
                rival_constant_type = constant_type
                if 'local' in constant_type:
                    rival_constant_type = constant_type.replace('local', 'visita')
                elif 'visita' in constant_type:
                    rival_constant_type = constant_type.replace('visita', 'local')
                k_rival_approx = self._get_combined_k(rival_prev_constants, rival_constant_type)
            else:
                k_rival_approx = 0.0
            
            # Nivel rival previo (aproximación)
            nivel_rival_prev = nivel_rival
            
            return {
                'constant_type': constant_type,
                'nivel_equipo': nivel_equipo,
                'nivel_rival': nivel_rival,
                'k_prev': prev_team_k,
                'nivel_rival_prev': nivel_rival_prev,
                'k_rival_approx': k_rival_approx,
                'league_id': league_id,
                'is_home': 1 if is_home else 0,
            }
            
        except Exception as e:
            logger.error(f"Error preparando inputs de predicción: {e}")
            return None
    
    # =========================================================================
    # MÉTODOS PARA VALIDACIÓN HISTÓRICA
    # =========================================================================
    
    def validate_historical_predictions(
        self, 
        team_id: int, 
        n: int = 5,
        constant_type: str = 'k_local',
        predictor=None,
        model_mode: str = 'auto',
        force_league_id: int = None
    ) -> List[Dict]:
        """
        Valida las predicciones del ML contra los resultados reales.
        
        🔧 CORREGIDO: Ahora usa _get_combined_k para calcular K real
        
        Args:
            team_id: ID del equipo
            n: Número de partidos a validar
            constant_type: Tipo de constante a validar
            predictor: Predictor pre-configurado (opcional)
            model_mode: 'auto', 'global', o 'league'
            force_league_id: Liga específica a usar (si model_mode='league')
        """
        try:
            # Usar predictor externo o crear uno nuevo
            has_ml = False
            
            if predictor is not None:
                has_ml = True
                logger.info(f"Usando predictor externo (mode={model_mode}, league={force_league_id})")
            else:
                try:
                    from utils.global_constant_predictor import GlobalConstantPredictor
                    predictor = GlobalConstantPredictor()
                    
                    # Cargar modelos según configuración
                    if model_mode == 'global':
                        predictor.load_models(load_global=True)
                        logger.info("Validación con modelo GLOBAL (forzado)")
                    elif model_mode == 'league' and force_league_id:
                        predictor.load_models(league_id=force_league_id, load_global=True)
                        logger.info(f"Validación con modelo LIGA {force_league_id} (forzado)")
                    else:
                        # Auto: detectar liga del equipo
                        team_leagues = self.get_team_leagues(team_id)
                        primary_league = team_leagues[0] if team_leagues else None
                        predictor.load_models(league_id=primary_league, load_global=True)
                        logger.info(f"Validación con modelo AUTO (liga={primary_league})")
                    
                    has_ml = True
                except Exception as e:
                    logger.warning(f"No se pudo cargar el predictor ML: {e}")
                    has_ml = False
                    predictor = None
            
            # Obtener últimos n+1 partidos
            fixtures = self.get_last_n_fixtures(team_id, n + 1)
            
            if len(fixtures) < 2:
                logger.warning(f"No hay suficientes partidos para validar ({len(fixtures)})")
                return []
            
            results = []
            
            for i in range(min(n, len(fixtures) - 1)):
                current_fixture = fixtures[i]
                
                # Constantes DESPUÉS del partido
                constants_after = self.get_team_constants_at_fixture(
                    team_id, current_fixture['fixture_id']
                )
                
                # Constantes ANTES del partido
                constants_before = self.get_team_constants_before_date(
                    team_id, current_fixture['date']
                )
                
                if not constants_after or not constants_before:
                    continue
                
                # 🔧 CORREGIDO: Usar K combinado (positivo + negativo)
                k_before = self._get_combined_k(constants_before, constant_type)
                k_after = self._get_combined_k(constants_after, constant_type)
                
                # Determinar cambio real (semántica de rachas)
                # Ahora K puede ser negativo cuando el equipo pierde
                if abs(k_after) < 0.05:  # Reset (cerca de 0)
                    real_change = 'reset'
                elif k_after > k_before:
                    real_change = 'incremento'
                elif k_after < k_before:
                    real_change = 'decremento'
                else:
                    real_change = 'incremento'  # Sin cambio, racha continúa
                
                # Predicción ML
                ml_prediction = None
                ml_prob = None
                ml_correct = None
                model_used = None
                
                if has_ml and predictor:
                    try:
                        # Validar coherencia constante vs condición
                        is_home_val = 1 if current_fixture['is_home'] else 0
                        is_valid, _ = predictor.validate_constant_condition(constant_type, is_home_val)
                        
                        if not is_valid:
                            # Constante no aplica para esta condición, saltar
                            continue
                        
                        inputs = self.get_prediction_inputs(
                            team_id=team_id,
                            rival_id=current_fixture['rival_id'],
                            fixture_date=current_fixture['date'],
                            fixture_id=current_fixture['fixture_id'],
                            is_home=current_fixture['is_home'],
                            constant_type=constant_type,
                            league_id=current_fixture.get('league_id')
                        )
                        
                        if inputs:
                            # Determinar qué league_id usar para la predicción
                            if model_mode == 'global':
                                use_league_id = None  # Forzar global
                            elif model_mode == 'league' and force_league_id:
                                use_league_id = force_league_id  # Forzar liga específica
                            else:
                                use_league_id = inputs['league_id']  # Auto
                            
                            pred_result = predictor.predict(
                                constant_type=constant_type,
                                nivel_equipo=inputs['nivel_equipo'],
                                nivel_rival=inputs['nivel_rival'],
                                k_prev=inputs['k_prev'],
                                nivel_rival_prev=inputs['nivel_rival_prev'],
                                k_rival_approx=inputs['k_rival_approx'],
                                league_id=use_league_id,
                                is_home=inputs['is_home'],
                            )
                            
                            # Verificar que predict() no retornó None
                            if pred_result is not None:
                                max_pred = max(pred_result.items(), key=lambda x: x[1])
                                ml_prediction = max_pred[0]
                                ml_prob = max_pred[1]
                                ml_correct = (ml_prediction == real_change)
                                
                                # Obtener qué modelo se usó realmente
                                model_used = predictor.get_model_for_prediction(constant_type, use_league_id)
                            
                    except Exception as e:
                        logger.warning(f"Error en predicción ML: {e}")
                
                results.append({
                    'fixture_id': current_fixture['fixture_id'],
                    'date': current_fixture['date'],
                    'rival_name': current_fixture['rival_name'],
                    'condition': current_fixture['condition'],
                    'goals_for': current_fixture['goals_for'],
                    'goals_against': current_fixture['goals_against'],
                    'k_before': round(k_before, 2),
                    'k_after': round(k_after, 2),
                    'k_change': round(k_after - k_before, 2),
                    'real_change': real_change,
                    'ml_prediction': ml_prediction,
                    'ml_prob': round(ml_prob, 1) if ml_prob else None,
                    'ml_correct': ml_correct,
                    'model_used': model_used,  # Qué modelo se usó realmente
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Error en validación histórica: {e}")
            return []
    
    def _get_k_column(self, constant_type: str, is_home: bool) -> str:
        """
        DEPRECADA: Usar _get_combined_k() en su lugar.
        Se mantiene por compatibilidad con código existente.
        """
        if 'local' in constant_type or 'visita' in constant_type:
            col_map = {
                'k_local': 'k_positivo_local',
                'k_visita': 'k_positivo_visita',
                'k_goles_local_anotado': 'k_goles_local_anotado',
                'k_goles_local_recibido': 'k_goles_local_recibido',
                'k_goles_visita_anotado': 'k_goles_visita_anotado',
                'k_goles_visita_recibido': 'k_goles_visita_recibido',
            }
            return col_map.get(constant_type, 'k_positivo_local' if is_home else 'k_positivo_visita')
        
        if constant_type == 'k_goles_anotado':
            return 'k_goles_local_anotado' if is_home else 'k_goles_visita_anotado'
        elif constant_type == 'k_goles_recibido':
            return 'k_goles_local_recibido' if is_home else 'k_goles_visita_recibido'
        
        return 'k_positivo_local' if is_home else 'k_positivo_visita'
    
    # =========================================================================
    # MÉTODOS AUXILIARES
    # =========================================================================
    
    def get_all_teams(self, limit: int = 2000) -> List[Dict]:
        """Obtiene lista de todos los equipos."""
        try:
            teams = self.session.query(Team).order_by(Team.name).limit(limit).all()
            return [{'id': t.id, 'name': t.name} for t in teams]
        except Exception as e:
            logger.error(f"Error obteniendo equipos: {e}")
            return []
    
    def get_team_info(self, team_id: int) -> Optional[Dict]:
        """Obtiene información de un equipo."""
        try:
            team = self.session.query(Team).filter_by(id=team_id).first()
            if team:
                return {
                    'id': team.id,
                    'name': team.name,
                    'country': getattr(team, 'country', 'N/A'),
                }
            return None
        except Exception as e:
            logger.error(f"Error obteniendo info de equipo: {e}")
            return None
    
    def get_team_leagues(self, team_id: int) -> List[int]:
        """Obtiene las ligas en las que ha jugado el equipo."""
        try:
            query = text("""
                SELECT DISTINCT league_id
                FROM fixtures
                WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                  AND league_id IS NOT NULL
            """)
            
            with engine.connect() as conn:
                results = conn.execute(query, {"team_id": team_id}).fetchall()
            
            return [row[0] for row in results]
            
        except Exception as e:
            logger.error(f"Error obteniendo ligas del equipo: {e}")
            return []


def get_ml_data_collector() -> MLDataCollector:
    """Función factory para obtener una instancia de MLDataCollector."""
    return MLDataCollector()