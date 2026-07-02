# src/utils/global_constant_predictor.py
"""
GlobalConstantPredictor - Sistema de predicción de constantes K.

IMPORTANTE: Los modelos se entrenan con niveles DISCRETOS (0-9).
Este predictor convierte automáticamente niveles continuos a discretos
usando el mismo discretizer que se usó en el entrenamiento.

Estructura de archivos:
    src/model_exports/
    ├── model_registry.json
    ├── level_discretizer.joblib  ← Discretizer para convertir niveles
    ├── global/
    │   ├── k.joblib
    │   └── ...
    └── leagues/
        └── ...
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import KBinsDiscretizer
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import f1_score, accuracy_score

import joblib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


class GlobalConstantPredictor:
    """
    Sistema de predicción de constantes K con modelos por liga.
    
    Características:
    - Convierte niveles continuos a discretos automáticamente
    - Maneja modelos globales y por liga
    - Valida coherencia constante vs condición
    """
    
    CONSTANTS = [
        'k', 'k_local', 'k_visita',
        'k_goles_anotado', 'k_goles_recibido',
        'k_goles_local_anotado', 'k_goles_local_recibido',
        'k_goles_visita_anotado', 'k_goles_visita_recibido',
    ]
    
    LOCAL_CONSTANTS = ['k_local', 'k_goles_local_anotado', 'k_goles_local_recibido']
    VISITA_CONSTANTS = ['k_visita', 'k_goles_visita_anotado', 'k_goles_visita_recibido']
    BINARY_CONSTANTS = [
        'k_goles_anotado', 'k_goles_recibido',
        'k_goles_local_anotado', 'k_goles_local_recibido',
        'k_goles_visita_anotado', 'k_goles_visita_recibido',
    ]
    
    RESET_THRESHOLD = 0.05
    MIN_SAMPLES_LEAGUE = 500
    MIN_SAMPLES_GLOBAL = 1000
    MIN_CLASS_SAMPLES = 10
    
    def __init__(self, discreto_db_path: str = None, model_base_dir: str = None, levels_db_path: str = None):
        """Inicializa el predictor."""
        self.src_dir = os.path.dirname(os.path.dirname(__file__))
        self.project_dir = os.path.dirname(self.src_dir)
        
        # Base de datos discreto
        if discreto_db_path is None:
            discreto_db_path = os.path.join(self.project_dir, 'discreto.db')
        if not os.path.exists(discreto_db_path):
            discreto_db_path = 'discreto.db'
        self.discreto_db_path = discreto_db_path
        self.engine = create_engine(f'sqlite:///{discreto_db_path}', echo=False)
        
        # Base de datos levels (para calibrar discretizer si no existe)
        if levels_db_path is None:
            levels_db_path = os.path.join(self.project_dir, 'levels.db')
        if not os.path.exists(levels_db_path):
            levels_db_path = 'levels.db'
        self.levels_db_path = levels_db_path
        
        # Directorio de modelos
        if model_base_dir is None:
            model_base_dir = os.path.join(self.src_dir, 'model_exports')
        self.model_base_dir = model_base_dir
        self.global_model_dir = os.path.join(model_base_dir, 'global')
        self.league_model_dir = os.path.join(model_base_dir, 'leagues')
        self.registry_path = os.path.join(model_base_dir, 'model_registry.json')
        self.discretizer_path = os.path.join(model_base_dir, 'level_discretizer.joblib')
        
        os.makedirs(self.global_model_dir, exist_ok=True)
        os.makedirs(self.league_model_dir, exist_ok=True)
        
        self.models: Dict[str, RandomForestClassifier] = {}
        self.metadata: Dict[str, dict] = {}
        self.registry = self._load_registry()
        
        # Discretizer para convertir niveles continuos → discretos
        self.level_discretizer: Optional[KBinsDiscretizer] = None
        self._load_or_create_discretizer()
        
        logger.info(f"GlobalConstantPredictor inicializado")
        logger.info(f"  DB: {discreto_db_path}")
        logger.info(f"  Modelos: {model_base_dir}")
    
    # =========================================================================
    # DISCRETIZER DE NIVELES
    # =========================================================================
    
    def _load_or_create_discretizer(self):
        """Carga el discretizer existente o crea uno nuevo calibrado con levels.db."""
        if os.path.exists(self.discretizer_path):
            try:
                self.level_discretizer = joblib.load(self.discretizer_path)
                logger.info(f"  Discretizer cargado: {self.discretizer_path}")
                return
            except Exception as e:
                logger.warning(f"Error cargando discretizer: {e}")
        
        # Crear nuevo discretizer
        self._create_discretizer()
    
    def _create_discretizer(self):
        """Crea y calibra el discretizer con todos los niveles históricos."""
        logger.info("Creando discretizer de niveles...")
        
        try:
            # Cargar niveles de levels.db
            if os.path.exists(self.levels_db_path):
                levels_engine = create_engine(f'sqlite:///{self.levels_db_path}', echo=False)
                
                query = text("SELECT level FROM team_levels WHERE level IS NOT NULL")
                with levels_engine.connect() as conn:
                    df = pd.read_sql_query(query, conn)
                
                if not df.empty:
                    levels_array = df['level'].values.reshape(-1, 1)
                    
                    # Crear discretizer con 10 bins uniformes (igual que discretizer_db.py)
                    self.level_discretizer = KBinsDiscretizer(
                        n_bins=10, 
                        encode='ordinal', 
                        strategy='uniform'
                    )
                    self.level_discretizer.fit(levels_array)
                    
                    # Guardar
                    joblib.dump(self.level_discretizer, self.discretizer_path)
                    
                    # Log de bins
                    edges = self.level_discretizer.bin_edges_[0]
                    logger.info(f"  Discretizer creado con {len(edges)-1} bins")
                    logger.info(f"  Rango: {edges[0]:.2f} - {edges[-1]:.2f}")
                    
                    return
            
            logger.warning("No se pudo crear discretizer - levels.db no disponible")
            
        except Exception as e:
            logger.error(f"Error creando discretizer: {e}")
    
    def discretize_level(self, continuous_level: float) -> int:
        """
        Convierte un nivel continuo (0.5-3.5) a discreto (0-9).
        
        Args:
            continuous_level: Nivel continuo de levels.db
            
        Returns:
            Nivel discreto (0-9) compatible con el modelo entrenado
        """
        if self.level_discretizer is None:
            # Fallback: escalar linealmente (aproximado)
            # Asumiendo rango típico 0.5-3.5 → 0-9
            scaled = (continuous_level - 0.5) / (3.5 - 0.5) * 9
            return int(np.clip(scaled, 0, 9))
        
        try:
            # Usar discretizer calibrado
            result = self.level_discretizer.transform([[continuous_level]])
            return int(result[0][0])
        except Exception as e:
            logger.warning(f"Error discretizando {continuous_level}: {e}")
            return int(np.clip(continuous_level * 3, 0, 9))
    
    def is_level_discrete(self, level: float) -> bool:
        """Detecta si un nivel ya es discreto (entero 0-9) o continuo."""
        return isinstance(level, int) or (level == int(level) and 0 <= level <= 9)
    
    def ensure_discrete_level(self, level: float) -> int:
        """Asegura que el nivel sea discreto, convirtiendo si es necesario."""
        if self.is_level_discrete(level):
            return int(level)
        return self.discretize_level(level)
    
    # =========================================================================
    # REGISTRO DE MODELOS
    # =========================================================================
    
    def _load_registry(self) -> Dict:
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {'last_updated': None, 'global_models': {}, 'league_models': {}, 'league_info': {}}
    
    def _save_registry(self):
        self.registry['last_updated'] = datetime.now().isoformat()
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry, f, indent=2)
        logger.info(f"Registro guardado: {self.registry_path}")
    
    def _register_model(self, constant_type: str, metrics: Dict, league_id: Optional[int] = None):
        entry = {
            'f1_macro': metrics.get('f1_macro', 0),
            'accuracy': metrics.get('accuracy', 0),
            'n_samples': metrics.get('n_samples', 0),
            'n_classes': metrics.get('n_classes', 3),
            'trained_at': metrics.get('trained_at', datetime.now().isoformat()),
        }
        
        if league_id is None:
            entry['path'] = f"global/{constant_type}.joblib"
            self.registry['global_models'][constant_type] = entry
        else:
            league_key = str(league_id)
            if league_key not in self.registry['league_models']:
                self.registry['league_models'][league_key] = {}
            entry['path'] = f"leagues/{league_id}/{constant_type}.joblib"
            self.registry['league_models'][league_key][constant_type] = entry
    
    # =========================================================================
    # INFORMACIÓN DE LIGAS
    # =========================================================================
    
    def get_available_leagues(self) -> List[Dict]:
        query = text("""
            SELECT league_id, COUNT(*) as total_matches, COUNT(DISTINCT equipo_id) as total_teams
            FROM processed_matches
            WHERE league_id IS NOT NULL
            GROUP BY league_id
            HAVING COUNT(*) >= :min_samples
            ORDER BY total_matches DESC
        """)
        with self.engine.connect() as conn:
            df = pd.read_sql_query(query, conn, params={'min_samples': self.MIN_SAMPLES_LEAGUE})
        return df.to_dict('records')
    
    def get_league_info(self, league_id: int) -> Dict:
        query = text("""
            SELECT COUNT(*) as total_matches, COUNT(DISTINCT equipo_id) as total_teams
            FROM processed_matches WHERE league_id = :league_id
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {'league_id': league_id}).fetchone()
        if result:
            return {'league_id': league_id, 'total_matches': result[0], 'total_teams': result[1]}
        return {}
    
    # =========================================================================
    # VALIDACIÓN DE COHERENCIA
    # =========================================================================
    
    def validate_constant_condition(self, constant_type: str, is_home: int) -> Tuple[bool, str]:
        if constant_type in self.LOCAL_CONSTANTS and is_home == 0:
            return False, f"{constant_type} solo aplica para LOCAL"
        if constant_type in self.VISITA_CONSTANTS and is_home == 1:
            return False, f"{constant_type} solo aplica para VISITA"
        return True, ""
    
    def get_applicable_constants(self, is_home: int) -> List[str]:
        if is_home == 1:
            return [c for c in self.CONSTANTS if c not in self.VISITA_CONSTANTS]
        else:
            return [c for c in self.CONSTANTS if c not in self.LOCAL_CONSTANTS]
    
    # =========================================================================
    # CARGA DE DATOS (ENTRENAMIENTO)
    # =========================================================================
    
    def load_training_data(self, constant_type: str, league_id: Optional[int] = None) -> Tuple[pd.DataFrame, pd.Series, bool]:
        """Carga datos de entrenamiento (ya discretizados en discreto.db)."""
        league_filter = f"AND league_id = {league_id}" if league_id else ""
        
        query = text(f"""
            SELECT id, fecha, fixture_id, equipo_id, rival_id, condicion, league_id,
                   nivel_equipo, nivel_rival,
                   k, k_local, k_visita,
                   k_goles_anotado, k_goles_recibido,
                   k_goles_local_anotado, k_goles_local_recibido,
                   k_goles_visita_anotado, k_goles_visita_recibido
            FROM processed_matches
            WHERE 1=1 {league_filter}
            ORDER BY equipo_id, fecha
        """)
        
        with self.engine.connect() as conn:
            df = pd.read_sql_query(query, conn)
        
        if df.empty:
            raise ValueError("No hay datos")
        
        logger.info(f"Cargados {len(df)} registros (niveles ya discretos 0-9)")
        
        if constant_type not in df.columns:
            raise ValueError(f"Columna {constant_type} no existe")
        
        # Filtrar por condición
        if constant_type in self.LOCAL_CONSTANTS:
            df = df[df['condicion'] == 'Local'].copy()
        elif constant_type in self.VISITA_CONSTANTS:
            df = df[df['condicion'] == 'Visita'].copy()
        
        df = df.sort_values(['equipo_id', 'fecha']).reset_index(drop=True)
        
        # Features
        df['k_prev'] = df.groupby('equipo_id')[constant_type].shift(1)
        df['nivel_rival_prev'] = df.groupby('equipo_id')['nivel_rival'].shift(1)
        df['k_rival_approx'] = df.groupby('rival_id')[constant_type].transform(lambda x: x.shift(1).fillna(0))
        
        df = df.dropna(subset=['k_prev'])
        
        is_binary = constant_type in self.BINARY_CONSTANTS
        
        def calc_target(row):
            k_current = row[constant_type]
            k_prev = row['k_prev']
            if pd.isna(k_current) or pd.isna(k_prev):
                return None
            if abs(k_current) < self.RESET_THRESHOLD:
                return 0
            diff = k_current - k_prev
            if is_binary:
                return 1 if diff >= 0 else 0
            else:
                return 1 if diff > 0 else (-1 if diff < 0 else 1)
        
        df['target'] = df.apply(calc_target, axis=1)
        df = df.dropna(subset=['target'])
        df['target'] = df['target'].astype(int)
        
        # Verificar clases
        class_counts = df['target'].value_counts()
        if not is_binary and class_counts.min() < self.MIN_CLASS_SAMPLES:
            logger.info(f"Convirtiendo a binario (clase minoritaria: {class_counts.min()})")
            df['target'] = df['target'].apply(lambda x: 1 if x == 1 else 0)
            is_binary = True
        
        feature_cols = ['nivel_equipo', 'nivel_rival', 'k_prev', 'nivel_rival_prev', 'k_rival_approx']
        
        if constant_type not in self.LOCAL_CONSTANTS and constant_type not in self.VISITA_CONSTANTS:
            df['is_home'] = (df['condicion'] == 'Local').astype(int)
            feature_cols.append('is_home')
        
        for col in feature_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0)
        
        X = df[feature_cols].copy()
        y = df['target']
        
        logger.info(f"Samples: {len(X)} | Modo: {'binario' if is_binary else 'ternario'}")
        
        return X, y, is_binary
    
    # =========================================================================
    # ENTRENAMIENTO
    # =========================================================================
    
    def _train_single_model(self, constant_type: str, league_id: Optional[int] = None) -> Optional[Dict]:
        scope = f"Liga {league_id}" if league_id else "Global"
        logger.info(f"\n{'─'*50}")
        logger.info(f"Entrenando {constant_type} ({scope})")
        
        try:
            X, y, is_binary = self.load_training_data(constant_type, league_id)
            
            min_samples = self.MIN_SAMPLES_LEAGUE if league_id else self.MIN_SAMPLES_GLOBAL
            if len(X) < min_samples:
                logger.warning(f"Datos insuficientes: {len(X)} < {min_samples}")
                return None
            
            if len(y.unique()) < 2:
                logger.warning(f"Solo {len(y.unique())} clase(s)")
                return None
            
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
            
            model = RandomForestClassifier(
                n_estimators=200, max_depth=15, min_samples_split=10, min_samples_leaf=5,
                class_weight='balanced', random_state=42, n_jobs=-1
            )
            model.fit(X_train, y_train)
            
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            f1_macro = f1_score(y_test, y_pred, average='macro')
            cv_scores = cross_val_score(model, X, y, cv=5, scoring='f1_macro')
            
            logger.info(f"  Accuracy: {accuracy:.4f} | F1: {f1_macro:.4f} | CV: {cv_scores.mean():.4f}")
            
            # Guardar
            if league_id:
                model_dir = os.path.join(self.league_model_dir, str(league_id))
                os.makedirs(model_dir, exist_ok=True)
                model_path = os.path.join(model_dir, f"{constant_type}.joblib")
                params_path = os.path.join(model_dir, f"params_{constant_type}.json")
            else:
                model_path = os.path.join(self.global_model_dir, f"{constant_type}.joblib")
                params_path = os.path.join(self.global_model_dir, f"params_{constant_type}.json")
            
            joblib.dump(model, model_path)
            
            metrics = {
                'constant_type': constant_type,
                'league_id': league_id,
                'n_samples': len(X),
                'n_classes': len(model.classes_),
                'is_binary': is_binary,
                'accuracy': float(accuracy),
                'f1_macro': float(f1_macro),
                'cv_f1_mean': float(cv_scores.mean()),
                'feature_names': list(X.columns),
                'classes': model.classes_.tolist(),
                'trained_at': datetime.now().isoformat(),
                'uses_discrete_levels': True,  # Marcador importante
            }
            
            with open(params_path, 'w') as f:
                json.dump(metrics, f, indent=2)
            
            self._register_model(constant_type, metrics, league_id)
            
            model_key = f"{league_id}_{constant_type}" if league_id else f"global_{constant_type}"
            self.models[model_key] = model
            self.metadata[model_key] = metrics
            
            logger.info(f"  ✓ Guardado: {model_path}")
            return metrics
            
        except Exception as e:
            logger.error(f"Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def train_global_models(self) -> Dict[str, Dict]:
        logger.info("\n" + "="*60)
        logger.info("ENTRENANDO MODELOS GLOBALES")
        logger.info("="*60)
        
        # Asegurar que el discretizer está guardado
        if self.level_discretizer and not os.path.exists(self.discretizer_path):
            joblib.dump(self.level_discretizer, self.discretizer_path)
            logger.info(f"Discretizer guardado: {self.discretizer_path}")
        
        results = {}
        for const in self.CONSTANTS:
            result = self._train_single_model(const, league_id=None)
            results[const] = result if result else {'error': 'Fallido'}
        
        self._save_registry()
        return results
    
    def train_league_models(self, league_id: int) -> Dict[str, Dict]:
        logger.info(f"\nENTRENANDO LIGA {league_id}")
        
        league_info = self.get_league_info(league_id)
        self.registry['league_info'][str(league_id)] = league_info
        
        results = {}
        for const in self.CONSTANTS:
            result = self._train_single_model(const, league_id=league_id)
            results[const] = result if result else {'error': 'Fallido'}
        
        self._save_registry()
        return results
    
    def train_all_leagues(self, min_samples: int = None) -> Dict[int, Dict]:
        if min_samples is None:
            min_samples = self.MIN_SAMPLES_LEAGUE
        
        self.train_global_models()
        
        leagues = self.get_available_leagues()
        eligible = [l for l in leagues if l['total_matches'] >= min_samples]
        
        logger.info(f"\nENTRENANDO {len(eligible)} LIGAS")
        
        all_results = {}
        for i, league in enumerate(eligible, 1):
            league_id = league['league_id']
            logger.info(f"\n[{i}/{len(eligible)}] Liga {league_id}")
            results = self.train_league_models(league_id)
            all_results[league_id] = results
        
        return all_results
    
    # =========================================================================
    # CARGA DE MODELOS
    # =========================================================================
    
    def load_models(self, league_id: Optional[int] = None, load_global: bool = True):
        loaded_global = 0
        loaded_league = 0
        
        if load_global:
            for const in self.CONSTANTS:
                model_path = os.path.join(self.global_model_dir, f"{const}.joblib")
                params_path = os.path.join(self.global_model_dir, f"params_{const}.json")
                
                if os.path.exists(model_path):
                    try:
                        self.models[f"global_{const}"] = joblib.load(model_path)
                        if os.path.exists(params_path):
                            with open(params_path) as f:
                                self.metadata[f"global_{const}"] = json.load(f)
                        loaded_global += 1
                    except Exception as e:
                        logger.warning(f"Error cargando global_{const}: {e}")
        
        if league_id:
            league_dir = os.path.join(self.league_model_dir, str(league_id))
            if os.path.exists(league_dir):
                for const in self.CONSTANTS:
                    model_path = os.path.join(league_dir, f"{const}.joblib")
                    params_path = os.path.join(league_dir, f"params_{const}.json")
                    
                    if os.path.exists(model_path):
                        try:
                            self.models[f"{league_id}_{const}"] = joblib.load(model_path)
                            if os.path.exists(params_path):
                                with open(params_path) as f:
                                    self.metadata[f"{league_id}_{const}"] = json.load(f)
                            loaded_league += 1
                        except Exception as e:
                            logger.warning(f"Error cargando {league_id}_{const}: {e}")
        
        total = loaded_global + loaded_league
        if total > 0:
            if loaded_league > 0:
                logger.info(f"Cargados {loaded_global} globales + {loaded_league} de liga {league_id}")
            else:
                logger.info(f"Cargados {loaded_global} modelos globales")
        
        return total
    
    # =========================================================================
    # PREDICCIÓN
    # =========================================================================
    
    def predict(
        self,
        constant_type: str,
        nivel_equipo: float,  # Puede ser continuo o discreto
        nivel_rival: float,   # Puede ser continuo o discreto
        k_prev: float,
        nivel_rival_prev: float = None,
        k_rival_approx: float = 0.0,
        league_id: int = None,
        is_home: int = None
    ) -> Optional[Dict[str, float]]:
        """
        Predice la evolución de una constante K.
        
        IMPORTANTE: Convierte automáticamente niveles continuos a discretos.
        
        Args:
            nivel_equipo: Nivel del equipo (continuo 0.5-3.5 o discreto 0-9)
            nivel_rival: Nivel del rival (continuo 0.5-3.5 o discreto 0-9)
            ...
            
        Returns:
            Dict: {'incremento': %, 'reset': %, 'decremento': %}
            None: Si la constante no aplica para la condición
        """
        # Validar coherencia
        if is_home is not None:
            is_valid, error_msg = self.validate_constant_condition(constant_type, is_home)
            if not is_valid:
                logger.debug(f"Predicción omitida: {error_msg}")
                return None
        
        # =====================================================================
        # CONVERTIR NIVELES A DISCRETOS
        # =====================================================================
        nivel_equipo_discrete = self.ensure_discrete_level(nivel_equipo)
        nivel_rival_discrete = self.ensure_discrete_level(nivel_rival)
        
        if nivel_rival_prev is not None:
            nivel_rival_prev_discrete = self.ensure_discrete_level(nivel_rival_prev)
        else:
            nivel_rival_prev_discrete = nivel_rival_discrete
        
        # Log solo si hubo conversión
        if nivel_equipo != nivel_equipo_discrete or nivel_rival != nivel_rival_discrete:
            logger.debug(f"Niveles discretizados: {nivel_equipo:.2f}→{nivel_equipo_discrete}, {nivel_rival:.2f}→{nivel_rival_discrete}")
        
        # =====================================================================
        # SELECCIONAR MODELO
        # =====================================================================
        model_key = None
        
        if league_id:
            league_key = f"{league_id}_{constant_type}"
            if league_key in self.models:
                model_key = league_key
            elif f"global_{constant_type}" not in self.models:
                self.load_models(league_id=league_id, load_global=True)
                if league_key in self.models:
                    model_key = league_key
        
        if not model_key:
            global_key = f"global_{constant_type}"
            if global_key in self.models:
                model_key = global_key
            elif not self.models:
                self.load_models(load_global=True)
                if global_key in self.models:
                    model_key = global_key
        
        if not model_key:
            logger.warning(f"No hay modelo para {constant_type}")
            return {'incremento': 33.3, 'reset': 33.3, 'decremento': 33.4}
        
        model = self.models[model_key]
        metadata = self.metadata.get(model_key, {})
        feature_names = metadata.get('feature_names', [])
        is_binary = metadata.get('is_binary', False)
        
        # =====================================================================
        # PREPARAR FEATURES (con niveles ya discretos)
        # =====================================================================
        features = {
            'nivel_equipo': nivel_equipo_discrete,
            'nivel_rival': nivel_rival_discrete,
            'k_prev': k_prev,
            'nivel_rival_prev': nivel_rival_prev_discrete,
            'k_rival_approx': k_rival_approx,
        }
        
        if 'is_home' in feature_names:
            if is_home is None:
                is_home = 1 if constant_type in self.LOCAL_CONSTANTS else 0
            features['is_home'] = is_home
        
        X = pd.DataFrame([features])
        
        if feature_names:
            for col in feature_names:
                if col not in X.columns:
                    X[col] = 0
            X = X[feature_names]
        
        # =====================================================================
        # EJECUTAR PREDICCIÓN
        # =====================================================================
        try:
            probas = model.predict_proba(X)[0]
            classes = model.classes_
            
            result = {'incremento': 0.0, 'reset': 0.0, 'decremento': 0.0}
            
            if is_binary:
                for cls, prob in zip(classes, probas):
                    if cls == 1:
                        result['incremento'] = float(prob * 100)
                    else:
                        result['reset'] = float(prob * 100)
            else:
                for cls, prob in zip(classes, probas):
                    if cls == 1:
                        result['incremento'] = float(prob * 100)
                    elif cls == 0:
                        result['reset'] = float(prob * 100)
                    elif cls == -1:
                        result['decremento'] = float(prob * 100)
            
            return result
            
        except Exception as e:
            logger.error(f"Error en predicción: {e}")
            return {'incremento': 33.3, 'reset': 33.3, 'decremento': 33.4}
    
    def get_model_for_prediction(self, constant_type: str, league_id: int = None) -> str:
        if league_id:
            if f"{league_id}_{constant_type}" in self.models:
                return f"league_{league_id}"
        if f"global_{constant_type}" in self.models:
            return "global"
        return "none"
    
    # =========================================================================
    # UTILIDADES
    # =========================================================================
    
    def get_model_status(self) -> Dict:
        self.registry = self._load_registry()
        
        return {
            'last_updated': self.registry.get('last_updated'),
            'global_models': {
                const: {'f1': info.get('f1_macro', 0), 'n_samples': info.get('n_samples', 0)}
                for const, info in self.registry.get('global_models', {}).items()
            },
            'league_models': {
                lid: {'models': {c: {'f1': i.get('f1_macro', 0)} for c, i in models.items()}}
                for lid, models in self.registry.get('league_models', {}).items()
            },
            'models_in_memory': list(self.models.keys()),
            'model_directory': self.model_base_dir,
            'discretizer_available': self.level_discretizer is not None,
        }
    
    def get_discretizer_info(self) -> Dict:
        """Retorna información del discretizer."""
        if self.level_discretizer is None:
            return {'available': False}
        
        edges = self.level_discretizer.bin_edges_[0]
        return {
            'available': True,
            'n_bins': len(edges) - 1,
            'bin_edges': edges.tolist(),
            'example_conversions': {
                f"{v:.1f}": self.discretize_level(v) 
                for v in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
            }
        }


# =============================================================================
# SCRIPT PRINCIPAL
# =============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Predictor de constantes K')
    parser.add_argument('--mode', choices=['global', 'league', 'all', 'status', 'discretizer'], default='status')
    parser.add_argument('--league', type=int, default=None)
    parser.add_argument('--min-samples', type=int, default=500)
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("SISTEMA DE PREDICCIÓN DE CONSTANTES K")
    print("="*60 + "\n")
    
    predictor = GlobalConstantPredictor()
    
    if args.mode == 'status':
        status = predictor.get_model_status()
        print(json.dumps(status, indent=2))
    elif args.mode == 'discretizer':
        info = predictor.get_discretizer_info()
        print("DISCRETIZER INFO:")
        print(json.dumps(info, indent=2))
    elif args.mode == 'global':
        predictor.train_global_models()
    elif args.mode == 'league':
        if not args.league:
            print("❌ Especifica --league")
            return
        predictor.train_league_models(args.league)
    elif args.mode == 'all':
        predictor.train_all_leagues(min_samples=args.min_samples)
    
    print("\n✅ Completado")


if __name__ == "__main__":
    main()