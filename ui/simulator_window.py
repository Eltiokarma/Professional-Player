# src/ui/simulator_window.py
"""
Ventana de simulación y predicción ML.

Pestañas:
1. Validación Histórica - Compara predicciones ML vs resultados reales
2. Próximo Partido - Predicción para el siguiente partido (equipo + rival)
3. Simulación Manual - Seleccionar rival y simular
4. Entrenar ML - Entrenar modelos con barra de progreso
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableView, QPushButton, QLabel, QGroupBox, QComboBox,
    QMessageBox, QProgressBar, QHeaderView, QFileDialog,
    QSpinBox, QRadioButton, QButtonGroup, QTextEdit,
    QFrame, QGridLayout, QSizePolicy, QSplitter
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor, QColor

from ui.pandas_model import PandasModel
from data.data_models.teams import Team
from sqlalchemy.orm import sessionmaker
from data.database_manager import engine

import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
Session = sessionmaker(bind=engine)


# =============================================================================
# WORKERS
# =============================================================================

class ValidationWorker(QThread):
    """Worker para validación histórica."""
    finished = Signal(list, str)
    progress = Signal(str)
    error = Signal(str)
    
    def __init__(self, team_id: int, constant_type: str, n_matches: int = 5, 
                 model_mode: str = 'auto', force_league_id: int = None):
        super().__init__()
        self.team_id = team_id
        self.constant_type = constant_type
        self.n_matches = n_matches
        self.model_mode = model_mode
        self.force_league_id = force_league_id
    
    def run(self):
        try:
            from utils.ml_data_collector import MLDataCollector
            from utils.global_constant_predictor import GlobalConstantPredictor
            
            self.progress.emit("Cargando datos...")
            
            with MLDataCollector() as collector:
                team_leagues = collector.get_team_leagues(self.team_id)
                primary_league = team_leagues[0] if team_leagues else None
                
                predictor = GlobalConstantPredictor()
                
                if self.model_mode == 'global':
                    predictor.load_models(load_global=True)
                    model_used = "global (forzado)"
                elif self.model_mode == 'league' and self.force_league_id:
                    predictor.load_models(league_id=self.force_league_id, load_global=True)
                    model_used = f"league_{self.force_league_id} (forzado)"
                else:
                    predictor.load_models(league_id=primary_league, load_global=True)
                    model_used = predictor.get_model_for_prediction(self.constant_type, primary_league)
                
                self.progress.emit(f"Validando con modelo: {model_used}...")
                
                # Pasar predictor pre-cargado y configuración de modo
                results = collector.validate_historical_predictions(
                    self.team_id, 
                    n=self.n_matches,
                    constant_type=self.constant_type,
                    predictor=predictor,
                    model_mode=self.model_mode,
                    force_league_id=self.force_league_id
                )
                
                self.finished.emit(results, model_used)
                
        except Exception as e:
            logger.error(f"Error en validación: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class NextMatchWorker(QThread):
    """Worker para predicción del próximo partido (equipo + rival)."""
    finished = Signal(dict)
    progress = Signal(str)
    error = Signal(str)
    
    def __init__(self, team_id: int, model_mode: str = 'auto', force_league_id: int = None):
        super().__init__()
        self.team_id = team_id
        self.model_mode = model_mode
        self.force_league_id = force_league_id
    
    def run(self):
        try:
            from utils.ml_data_collector import MLDataCollector
            from utils.global_constant_predictor import GlobalConstantPredictor
            
            self.progress.emit("Buscando próximo partido...")
            
            with MLDataCollector() as collector:
                next_fixture = collector.get_next_fixture(self.team_id)
                
                if not next_fixture:
                    self.finished.emit({'error': 'No hay próximo partido programado'})
                    return
                
                league_id = next_fixture.get('league_id')
                rival_id = next_fixture['rival_id']
                
                self.progress.emit("Cargando modelos...")
                predictor = GlobalConstantPredictor()
                
                if self.model_mode == 'global':
                    predictor.load_models(load_global=True)
                elif self.model_mode == 'league' and self.force_league_id:
                    predictor.load_models(league_id=self.force_league_id, load_global=True)
                    league_id = self.force_league_id
                else:
                    predictor.load_models(league_id=league_id, load_global=True)
                
                self.progress.emit("Generando predicciones del equipo...")
                
                # PREDICCIONES DEL EQUIPO
                team_predictions = {}
                team_models = {}
                
                is_home_team = 1 if next_fixture['is_home'] else 0
                team_constants = predictor.get_applicable_constants(is_home_team)
                
                for const_type in team_constants:
                    try:
                        inputs = collector.get_prediction_inputs(
                            team_id=self.team_id,
                            rival_id=rival_id,
                            fixture_date=next_fixture['date'],
                            fixture_id=next_fixture['fixture_id'],
                            is_home=next_fixture['is_home'],
                            constant_type=const_type,
                            league_id=league_id,
                        )
                        
                        if inputs:
                            pred_result = predictor.predict(
                                constant_type=const_type,
                                nivel_equipo=inputs['nivel_equipo'],
                                nivel_rival=inputs['nivel_rival'],
                                k_prev=inputs['k_prev'],
                                nivel_rival_prev=inputs['nivel_rival_prev'],
                                k_rival_approx=inputs['k_rival_approx'],
                                league_id=league_id if self.model_mode != 'global' else None,
                                is_home=inputs['is_home'],
                            )
                            if pred_result is not None:
                                team_predictions[const_type] = pred_result
                                team_models[const_type] = predictor.get_model_for_prediction(
                                    const_type, league_id if self.model_mode != 'global' else None
                                )
                    except Exception as e:
                        logger.warning(f"Error prediciendo {const_type} para equipo: {e}")
                
                # PREDICCIONES DEL RIVAL
                self.progress.emit("Generando predicciones del rival...")
                
                rival_predictions = {}
                rival_models = {}
                
                is_home_rival = 0 if next_fixture['is_home'] else 1
                rival_constants = predictor.get_applicable_constants(is_home_rival)
                
                for const_type in rival_constants:
                    try:
                        inputs = collector.get_prediction_inputs(
                            team_id=rival_id,
                            rival_id=self.team_id,
                            fixture_date=next_fixture['date'],
                            fixture_id=next_fixture['fixture_id'],
                            is_home=not next_fixture['is_home'],
                            constant_type=const_type,
                            league_id=league_id,
                        )
                        
                        if inputs:
                            pred_result = predictor.predict(
                                constant_type=const_type,
                                nivel_equipo=inputs['nivel_equipo'],
                                nivel_rival=inputs['nivel_rival'],
                                k_prev=inputs['k_prev'],
                                nivel_rival_prev=inputs['nivel_rival_prev'],
                                k_rival_approx=inputs['k_rival_approx'],
                                league_id=league_id if self.model_mode != 'global' else None,
                                is_home=inputs['is_home'],
                            )
                            if pred_result is not None:
                                rival_predictions[const_type] = pred_result
                                rival_models[const_type] = predictor.get_model_for_prediction(
                                    const_type, league_id if self.model_mode != 'global' else None
                                )
                    except Exception as e:
                        logger.warning(f"Error prediciendo {const_type} para rival: {e}")
                
                team_info = collector.get_team_info(self.team_id)
                rival_info = collector.get_team_info(rival_id)
                
                self.finished.emit({
                    'fixture': next_fixture,
                    'team_name': team_info['name'] if team_info else f'ID {self.team_id}',
                    'rival_name': rival_info['name'] if rival_info else f'ID {rival_id}',
                    'team_predictions': team_predictions,
                    'team_models': team_models,
                    'rival_predictions': rival_predictions,
                    'rival_models': rival_models,
                    'model_mode': self.model_mode,
                })
                
        except Exception as e:
            logger.error(f"Error: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class ManualPredictionWorker(QThread):
    """Worker para predicción manual."""
    finished = Signal(dict)
    progress = Signal(str)
    error = Signal(str)
    
    def __init__(self, team_id: int, rival_id: int, is_home: bool, constant_type: str, 
                 league_id: int = None, model_mode: str = 'auto'):
        super().__init__()
        self.team_id = team_id
        self.rival_id = rival_id
        self.is_home = is_home
        self.constant_type = constant_type
        self.league_id = league_id
        self.model_mode = model_mode
    
    def run(self):
        try:
            from utils.ml_data_collector import MLDataCollector
            from utils.global_constant_predictor import GlobalConstantPredictor
            
            self.progress.emit("Validando coherencia...")
            
            predictor = GlobalConstantPredictor()
            is_home_val = 1 if self.is_home else 0
            is_valid, error_msg = predictor.validate_constant_condition(self.constant_type, is_home_val)
            
            if not is_valid:
                self.finished.emit({
                    'error': f"⚠️ {error_msg}\n\nSelecciona una constante coherente."
                })
                return
            
            self.progress.emit("Preparando datos...")
            
            with MLDataCollector() as collector:
                last_fixtures = collector.get_last_n_fixtures(self.team_id, 1)
                fixture_id = last_fixtures[0]['fixture_id'] if last_fixtures else 0
                
                if not self.league_id:
                    team_leagues = collector.get_team_leagues(self.team_id)
                    self.league_id = team_leagues[0] if team_leagues else None
                
                inputs = collector.get_prediction_inputs(
                    team_id=self.team_id,
                    rival_id=self.rival_id,
                    fixture_date=datetime.now(),
                    fixture_id=fixture_id,
                    is_home=self.is_home,
                    constant_type=self.constant_type,
                    league_id=self.league_id,
                )
                
                if not inputs:
                    self.finished.emit({'error': 'No se pudieron preparar los datos'})
                    return
                
                self.progress.emit("Ejecutando predicción...")
                
                if self.model_mode == 'global':
                    predictor.load_models(load_global=True)
                    use_league = None
                else:
                    predictor.load_models(league_id=self.league_id, load_global=True)
                    use_league = self.league_id
                
                pred_result = predictor.predict(
                    constant_type=self.constant_type,
                    nivel_equipo=inputs['nivel_equipo'],
                    nivel_rival=inputs['nivel_rival'],
                    k_prev=inputs['k_prev'],
                    nivel_rival_prev=inputs['nivel_rival_prev'],
                    k_rival_approx=inputs['k_rival_approx'],
                    league_id=use_league,
                    is_home=inputs['is_home'],
                )
                
                if pred_result is None:
                    self.finished.emit({
                        'error': f"La constante {self.constant_type} no aplica"
                    })
                    return
                
                model_used = predictor.get_model_for_prediction(self.constant_type, use_league)
                
                team_info = collector.get_team_info(self.team_id)
                rival_info = collector.get_team_info(self.rival_id)
                
                self.finished.emit({
                    'prediction': pred_result,
                    'inputs': inputs,
                    'team_name': team_info['name'] if team_info else f'ID {self.team_id}',
                    'rival_name': rival_info['name'] if rival_info else f'ID {self.rival_id}',
                    'condition': 'Local' if self.is_home else 'Visita',
                    'model_used': model_used,
                    'league_id': self.league_id,
                })
                
        except Exception as e:
            logger.error(f"Error: {e}")
            self.error.emit(str(e))


class TrainingWorker(QThread):
    """Worker para entrenamiento ML."""
    finished = Signal(dict)
    progress = Signal(int, str)
    log_message = Signal(str)
    error = Signal(str)
    
    def __init__(self, mode: str, league_id: int = None, min_samples: int = 500):
        super().__init__()
        self.mode = mode
        self.league_id = league_id
        self.min_samples = min_samples
        self._stop_requested = False
    
    def stop(self):
        self._stop_requested = True
    
    def run(self):
        try:
            from utils.global_constant_predictor import GlobalConstantPredictor
            
            predictor = GlobalConstantPredictor()
            
            if self.mode == 'global':
                self._train_global(predictor)
            elif self.mode == 'league':
                self._train_league(predictor)
            elif self.mode == 'all':
                self._train_all(predictor)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            self.error.emit(str(e))
    
    def _train_global(self, predictor):
        self.log_message.emit("═"*50)
        self.log_message.emit("  ENTRENANDO MODELOS GLOBALES")
        self.log_message.emit("═"*50 + "\n")
        
        constants = predictor.CONSTANTS
        results = {}
        
        for i, const in enumerate(constants):
            if self._stop_requested:
                self.log_message.emit("\n⚠️ Cancelado")
                return
            
            progress = int((i / len(constants)) * 100)
            self.progress.emit(progress, f"Entrenando {const}...")
            self.log_message.emit(f"📊 {const}...")
            
            result = predictor._train_single_model(const, league_id=None)
            
            if result:
                mode = "2cl" if result.get('is_binary') else "3cl"
                self.log_message.emit(f"   ✅ F1={result.get('f1_macro', 0):.4f} | {mode}")
                results[const] = result
            else:
                self.log_message.emit(f"   ❌ Error")
                results[const] = {'error': 'Fallido'}
        
        predictor._save_registry()
        self.progress.emit(100, "✅ Completado")
        
        success = sum(1 for r in results.values() if 'error' not in r)
        self.log_message.emit(f"\n✅ {success}/{len(constants)} modelos")
        
        self.finished.emit({'mode': 'global', 'results': results})
    
    def _train_league(self, predictor):
        self.log_message.emit(f"Entrenando Liga {self.league_id}...\n")
        
        results = {}
        for i, const in enumerate(predictor.CONSTANTS):
            if self._stop_requested:
                return
            
            self.progress.emit(int((i / 9) * 100), const)
            result = predictor._train_single_model(const, league_id=self.league_id)
            
            if result:
                self.log_message.emit(f"  ✅ {const}: F1={result.get('f1_macro', 0):.3f}")
            else:
                self.log_message.emit(f"  ⚠️ {const}: sin datos")
            results[const] = result or {'error': 'Fallido'}
        
        predictor._save_registry()
        self.progress.emit(100, "✅ Completado")
        self.finished.emit({'mode': 'league', 'league_id': self.league_id})
    
    def _train_all(self, predictor):
        self.log_message.emit("ENTRENAMIENTO COMPLETO\n")
        
        self._train_global(predictor)
        if self._stop_requested:
            return
        
        leagues = predictor.get_available_leagues()
        eligible = [l for l in leagues if l['total_matches'] >= self.min_samples]
        
        self.log_message.emit(f"\n🏆 {len(eligible)} Ligas\n")
        
        for i, league in enumerate(eligible):
            if self._stop_requested:
                return
            
            lid = league['league_id']
            self.progress.emit(int((i / len(eligible)) * 100), f"Liga {lid}")
            self.log_message.emit(f"\nLiga {lid}:")
            
            for const in predictor.CONSTANTS:
                if self._stop_requested:
                    return
                result = predictor._train_single_model(const, league_id=lid)
                if result:
                    self.log_message.emit(f"  ✅ {const}")
        
        predictor._save_registry()
        self.progress.emit(100, "✅ Completado")
        self.finished.emit({'mode': 'all', 'leagues': len(eligible)})


# =============================================================================
# VENTANA PRINCIPAL
# =============================================================================

class SimulatorWindow(QDialog):
    """Ventana de simulación y predicción ML."""
    
    def __init__(self, parent, team_id: int):
        super().__init__(parent)
        self.team_id = team_id
        self.team_name = ""
        self.team_leagues = []
        
        self.validation_worker = None
        self.next_match_worker = None
        self.manual_worker = None
        self.training_worker = None
        
        self.validation_data = None
        self.next_match_data = None
        self.teams_list = []
        self.available_leagues = []
        
        self.setWindowTitle("🎯 Predicción ML")
        self.resize(1200, 850)
        self.setModal(True)
        
        self._build_ui()
        self._load_initial_data()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Header
        header = QFrame()
        header.setStyleSheet("QFrame { background-color: #2E86AB; border-radius: 8px; padding: 10px; }")
        header_layout = QHBoxLayout(header)
        
        self.team_info_label = QLabel("Cargando...")
        self.team_info_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        header_layout.addWidget(self.team_info_label)
        
        header_layout.addStretch()
        
        self.league_info_label = QLabel("")
        self.league_info_label.setStyleSheet("color: #E8E8E8; font-size: 12px;")
        header_layout.addWidget(self.league_info_label)
        
        layout.addWidget(header)
        
        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        
        self._build_validation_tab()
        self._build_next_match_tab()
        self._build_manual_tab()
        self._build_training_tab()
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status
        self.status_label = QLabel("✅ Listo")
        self.status_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(self.status_label)
        
        # Botones
        btn_layout = QHBoxLayout()
        btn_export = QPushButton("📁 Exportar")
        btn_export.clicked.connect(self._export_results)
        btn_layout.addWidget(btn_export)
        btn_layout.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)
    
    def _build_validation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Controles
        controls = QGroupBox("⚙️ Configuración")
        controls_layout = QGridLayout(controls)
        
        controls_layout.addWidget(QLabel("Constante:"), 0, 0)
        self.combo_const_validation = QComboBox()
        self.combo_const_validation.addItems([
            'k', 'k_local', 'k_visita',
            'k_goles_anotado', 'k_goles_recibido',
            'k_goles_local_anotado', 'k_goles_local_recibido',
            'k_goles_visita_anotado', 'k_goles_visita_recibido'
        ])
        controls_layout.addWidget(self.combo_const_validation, 0, 1)
        
        controls_layout.addWidget(QLabel("Partidos:"), 0, 2)
        self.spin_validation_matches = QSpinBox()
        self.spin_validation_matches.setRange(3, 20)
        self.spin_validation_matches.setValue(5)
        controls_layout.addWidget(self.spin_validation_matches, 0, 3)
        
        # Selector de modelo
        controls_layout.addWidget(QLabel("Modelo:"), 1, 0)
        self.combo_model_validation = QComboBox()
        self.combo_model_validation.addItem("🔄 Auto", "auto")
        self.combo_model_validation.addItem("🌍 Global", "global")
        self.combo_model_validation.addItem("🏆 Liga:", "league")
        self.combo_model_validation.currentIndexChanged.connect(
            lambda: self.combo_league_validation.setEnabled(
                self.combo_model_validation.currentData() == 'league'
            )
        )
        controls_layout.addWidget(self.combo_model_validation, 1, 1)
        
        self.combo_league_validation = QComboBox()
        self.combo_league_validation.setEnabled(False)
        controls_layout.addWidget(self.combo_league_validation, 1, 2)
        
        btn_validate = QPushButton("🔍 Validar")
        btn_validate.clicked.connect(self._run_validation)
        btn_validate.setStyleSheet("background-color: #17a2b8; color: white; padding: 8px 16px;")
        controls_layout.addWidget(btn_validate, 1, 3)
        
        layout.addWidget(controls)
        
        # Info modelo
        info_layout = QHBoxLayout()
        self.model_used_label = QLabel("🤖 Modelo: --")
        info_layout.addWidget(self.model_used_label)
        info_layout.addStretch()
        self.accuracy_label = QLabel("📊 Precisión: --")
        info_layout.addWidget(self.accuracy_label)
        layout.addLayout(info_layout)
        
        # Tabla
        self.validation_table = QTableView()
        self.validation_table.setAlternatingRowColors(True)
        layout.addWidget(self.validation_table, 1)
        
        self.tabs.addTab(tab, "📊 Validación")
    
    def _build_next_match_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Controles
        controls = QGroupBox("📅 Próximo Partido")
        controls_layout = QHBoxLayout(controls)
        
        controls_layout.addWidget(QLabel("Modelo:"))
        self.combo_model_next = QComboBox()
        self.combo_model_next.addItem("🔄 Auto", "auto")
        self.combo_model_next.addItem("🌍 Global", "global")
        self.combo_model_next.addItem("🏆 Liga:", "league")
        self.combo_model_next.currentIndexChanged.connect(
            lambda: self.combo_league_next.setEnabled(
                self.combo_model_next.currentData() == 'league'
            )
        )
        controls_layout.addWidget(self.combo_model_next)
        
        self.combo_league_next = QComboBox()
        self.combo_league_next.setEnabled(False)
        controls_layout.addWidget(self.combo_league_next)
        
        controls_layout.addStretch()
        
        btn_refresh = QPushButton("🔄 Actualizar")
        btn_refresh.clicked.connect(self._load_next_match_prediction)
        btn_refresh.setStyleSheet("background-color: #28a745; color: white; padding: 8px 16px;")
        controls_layout.addWidget(btn_refresh)
        
        layout.addWidget(controls)
        
        # Info partido
        self.next_match_info = QLabel("Cargando...")
        self.next_match_info.setStyleSheet("padding: 10px; background: #e9ecef; border-radius: 4px;")
        self.next_match_info.setWordWrap(True)
        layout.addWidget(self.next_match_info)
        
        # Tablas lado a lado
        splitter = QSplitter(Qt.Horizontal)
        
        team_group = QGroupBox("🏠 Equipo")
        team_layout = QVBoxLayout(team_group)
        self.team_pred_table = QTableView()
        self.team_pred_table.setAlternatingRowColors(True)
        team_layout.addWidget(self.team_pred_table)
        splitter.addWidget(team_group)
        
        rival_group = QGroupBox("🆚 Rival")
        rival_layout = QVBoxLayout(rival_group)
        self.rival_pred_table = QTableView()
        self.rival_pred_table.setAlternatingRowColors(True)
        rival_layout.addWidget(self.rival_pred_table)
        splitter.addWidget(rival_group)
        
        layout.addWidget(splitter, 1)
        
        legend = QLabel("↑ Sube | ⟳ Reset | ↓ Baja — Compara K_local vs K_visita de ambos equipos")
        legend.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(legend)
        
        self.tabs.addTab(tab, "🎯 Próximo Partido")
    
    def _build_manual_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        config = QGroupBox("🔧 Configuración")
        config_layout = QGridLayout(config)
        
        config_layout.addWidget(QLabel("Rival:"), 0, 0)
        self.combo_rival = QComboBox()
        self.combo_rival.setEditable(True)
        self.combo_rival.setMinimumWidth(250)
        config_layout.addWidget(self.combo_rival, 0, 1, 1, 3)
        
        config_layout.addWidget(QLabel("Condición:"), 1, 0)
        self.combo_condition = QComboBox()
        self.combo_condition.addItems(["Local", "Visita"])
        self.combo_condition.currentTextChanged.connect(self._update_constants_combo)
        config_layout.addWidget(self.combo_condition, 1, 1)
        
        config_layout.addWidget(QLabel("Constante:"), 1, 2)
        self.combo_const_manual = QComboBox()
        self._update_constants_combo("Local")
        config_layout.addWidget(self.combo_const_manual, 1, 3)
        
        config_layout.addWidget(QLabel("Modelo:"), 2, 0)
        self.combo_model_manual = QComboBox()
        self.combo_model_manual.addItem("🔄 Auto", "auto")
        self.combo_model_manual.addItem("🌍 Global", "global")
        config_layout.addWidget(self.combo_model_manual, 2, 1)
        
        layout.addWidget(config)
        
        btn_sim = QPushButton("🚀 Ejecutar Predicción")
        btn_sim.clicked.connect(self._run_manual_prediction)
        btn_sim.setStyleSheet("background-color: #dc3545; color: white; padding: 12px 24px; font-weight: bold;")
        layout.addWidget(btn_sim)
        
        result_group = QGroupBox("📊 Resultado")
        result_layout = QVBoxLayout(result_group)
        self.manual_result_label = QLabel("Selecciona un rival")
        self.manual_result_label.setStyleSheet("padding: 30px; background: #f8f9fa; border-radius: 8px;")
        self.manual_result_label.setWordWrap(True)
        self.manual_result_label.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(self.manual_result_label)
        layout.addWidget(result_group, 1)
        
        self.tabs.addTab(tab, "🔧 Manual")
    
    def _build_training_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        config = QGroupBox("⚙️ Configuración")
        config_layout = QVBoxLayout(config)
        
        mode_layout = QHBoxLayout()
        self.btn_group_mode = QButtonGroup()
        
        self.radio_global = QRadioButton("🌍 Global")
        self.radio_global.setChecked(True)
        self.btn_group_mode.addButton(self.radio_global)
        mode_layout.addWidget(self.radio_global)
        
        self.radio_league = QRadioButton("🏆 Liga:")
        self.btn_group_mode.addButton(self.radio_league)
        mode_layout.addWidget(self.radio_league)
        
        self.combo_league_train = QComboBox()
        self.combo_league_train.setEnabled(False)
        mode_layout.addWidget(self.combo_league_train)
        
        self.radio_all = QRadioButton("🚀 Todas")
        self.btn_group_mode.addButton(self.radio_all)
        mode_layout.addWidget(self.radio_all)
        
        mode_layout.addStretch()
        config_layout.addLayout(mode_layout)
        
        self.radio_league.toggled.connect(lambda c: self.combo_league_train.setEnabled(c))
        
        samples_layout = QHBoxLayout()
        samples_layout.addWidget(QLabel("Min partidos:"))
        self.spin_min_samples = QSpinBox()
        self.spin_min_samples.setRange(100, 5000)
        self.spin_min_samples.setValue(500)
        samples_layout.addWidget(self.spin_min_samples)
        samples_layout.addStretch()
        config_layout.addLayout(samples_layout)
        
        btn_layout = QHBoxLayout()
        self.btn_train = QPushButton("🚀 Entrenar")
        self.btn_train.clicked.connect(self._start_training)
        self.btn_train.setStyleSheet("background-color: #6f42c1; color: white; padding: 10px 20px;")
        btn_layout.addWidget(self.btn_train)
        
        self.btn_stop = QPushButton("⏹️ Detener")
        self.btn_stop.clicked.connect(self._stop_training)
        self.btn_stop.setEnabled(False)
        btn_layout.addWidget(self.btn_stop)
        
        self.btn_status = QPushButton("📊 Estado")
        self.btn_status.clicked.connect(self._show_model_status)
        btn_layout.addWidget(self.btn_status)
        btn_layout.addStretch()
        config_layout.addLayout(btn_layout)
        
        layout.addWidget(config)
        
        progress_group = QGroupBox("📈 Progreso")
        progress_layout = QVBoxLayout(progress_group)
        self.training_progress = QProgressBar()
        progress_layout.addWidget(self.training_progress)
        self.training_status = QLabel("Listo")
        progress_layout.addWidget(self.training_status)
        layout.addWidget(progress_group)
        
        log_group = QGroupBox("📋 Log")
        log_layout = QVBoxLayout(log_group)
        self.training_log = QTextEdit()
        self.training_log.setReadOnly(True)
        self.training_log.setFont(QFont("Consolas", 10))
        self.training_log.setStyleSheet("background: #1e1e1e; color: #dcdcdc;")
        log_layout.addWidget(self.training_log)
        layout.addWidget(log_group, 1)
        
        self.tabs.addTab(tab, "⚙️ Entrenar")
        
        QTimer.singleShot(500, self._load_available_leagues)
    
    # =========================================================================
    # CARGA DE DATOS
    # =========================================================================
    
    def _load_initial_data(self):
        self._load_team_info()
        QTimer.singleShot(100, self._load_teams_list)
        QTimer.singleShot(200, self._load_next_match_prediction)
    
    def _load_team_info(self):
        session = Session()
        try:
            team = session.query(Team).filter_by(id=self.team_id).first()
            if team:
                self.team_name = team.name
                self.team_info_label.setText(f"🏆 {team.name}")
                self.setWindowTitle(f"🎯 ML - {team.name}")
                
                try:
                    from utils.ml_data_collector import MLDataCollector
                    with MLDataCollector() as collector:
                        self.team_leagues = collector.get_team_leagues(self.team_id)
                        if self.team_leagues:
                            self.league_info_label.setText(f"Liga: {self.team_leagues[0]} | ID: {self.team_id}")
                except:
                    pass
        finally:
            session.close()
    
    def _load_teams_list(self):
        try:
            from utils.ml_data_collector import MLDataCollector
            with MLDataCollector() as collector:
                self.teams_list = collector.get_all_teams(limit=2000)
            
            self.combo_rival.clear()
            for team in self.teams_list:
                if team['id'] != self.team_id:
                    self.combo_rival.addItem(team['name'], team['id'])
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def _load_available_leagues(self):
        try:
            from utils.global_constant_predictor import GlobalConstantPredictor
            predictor = GlobalConstantPredictor()
            self.available_leagues = predictor.get_available_leagues()
            
            for combo in [self.combo_league_validation, self.combo_league_next, self.combo_league_train]:
                combo.clear()
                for league in self.available_leagues[:50]:
                    combo.addItem(f"Liga {league['league_id']} ({league['total_matches']:,})", league['league_id'])
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def _update_constants_combo(self, condition: str):
        self.combo_const_manual.clear()
        if condition == "Local":
            self.combo_const_manual.addItems(['k', 'k_local', 'k_goles_anotado', 'k_goles_recibido',
                                              'k_goles_local_anotado', 'k_goles_local_recibido'])
        else:
            self.combo_const_manual.addItems(['k', 'k_visita', 'k_goles_anotado', 'k_goles_recibido',
                                              'k_goles_visita_anotado', 'k_goles_visita_recibido'])
    
    # =========================================================================
    # VALIDACIÓN
    # =========================================================================
    
    def _run_validation(self):
        if self.validation_worker and self.validation_worker.isRunning():
            return
        
        const_type = self.combo_const_validation.currentText()
        n = self.spin_validation_matches.value()
        model_mode = self.combo_model_validation.currentData()
        force_league = self.combo_league_validation.currentData() if model_mode == 'league' else None
        
        self.status_label.setText("🔄 Validando...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        self.validation_worker = ValidationWorker(self.team_id, const_type, n, model_mode, force_league)
        self.validation_worker.progress.connect(lambda m: self.status_label.setText(m))
        self.validation_worker.finished.connect(self._on_validation_finished)
        self.validation_worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self.validation_worker.start()
    
    def _on_validation_finished(self, results, model_used):
        self.progress_bar.setVisible(False)
        self.validation_data = results
        self.model_used_label.setText(f"🤖 Modelo: {model_used}")
        
        if not results:
            self.accuracy_label.setText("📊 Precisión: N/A")
            return
        
        df_data = []
        correct = sum(1 for r in results if r.get('ml_correct') is True)
        total = sum(1 for r in results if r.get('ml_correct') is not None)
        
        for r in results:
            status = "✅" if r.get('ml_correct') is True else ("❌" if r.get('ml_correct') is False else "⚪")
            df_data.append({
                'Fecha': str(r['date'])[:10],
                'Rival': r['rival_name'][:15],
                'Score': f"{r['goals_for']}-{r['goals_against']}",
                'K→': f"{r['k_before']:.1f}→{r['k_after']:.1f}",
                'Real': r['real_change'],
                'ML': r.get('ml_prediction', '-'),
                '✓': status,
            })
        
        df = pd.DataFrame(df_data)
        self.validation_table.setModel(PandasModel(df))
        self.validation_table.resizeColumnsToContents()
        
        if total > 0:
            acc = (correct / total) * 100
            self.accuracy_label.setText(f"📊 {correct}/{total} ({acc:.0f}%)")
        
        self.status_label.setText("✅ Validación completada")
    
    # =========================================================================
    # PRÓXIMO PARTIDO
    # =========================================================================
    
    def _load_next_match_prediction(self):
        if self.next_match_worker and self.next_match_worker.isRunning():
            return
        
        self.next_match_info.setText("🔄 Buscando...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        
        model_mode = self.combo_model_next.currentData()
        force_league = self.combo_league_next.currentData() if model_mode == 'league' else None
        
        self.next_match_worker = NextMatchWorker(self.team_id, model_mode, force_league)
        self.next_match_worker.progress.connect(lambda m: self.status_label.setText(m))
        self.next_match_worker.finished.connect(self._on_next_match_finished)
        self.next_match_worker.error.connect(lambda e: self.next_match_info.setText(f"❌ {e}"))
        self.next_match_worker.start()
    
    def _on_next_match_finished(self, result):
        self.progress_bar.setVisible(False)
        self.next_match_data = result
        
        if 'error' in result:
            self.next_match_info.setText(f"⚠️ {result['error']}")
            return
        
        fixture = result['fixture']
        team_name = result['team_name']
        rival_name = result['rival_name']
        condition = fixture['condition']
        
        self.next_match_info.setText(f"""
            <b>📅 {str(fixture['date'])[:16]}</b> | 
            <b>{fixture['home_team_name']}</b> vs <b>{fixture['away_team_name']}</b> | 
            Liga: {fixture.get('league_id', 'N/A')} | Modelo: {result.get('model_mode', 'auto')}
        """)
        
        # Tabla equipo
        team_preds = result.get('team_predictions', {})
        team_data = []
        for const, pred in team_preds.items():
            max_p = max(pred.items(), key=lambda x: x[1])
            team_data.append({
                'Const': const.replace('k_', ''),
                '↑': f"{pred.get('incremento', 0):.0f}%",
                '⟳': f"{pred.get('reset', 0):.0f}%",
                '↓': f"{pred.get('decremento', 0):.0f}%",
                'Pred': max_p[0][:4],
            })
        
        if team_data:
            self.team_pred_table.setModel(PandasModel(pd.DataFrame(team_data)))
            self.team_pred_table.resizeColumnsToContents()
        self.team_pred_table.parent().setTitle(f"🏠 {team_name} ({condition})")
        
        # Tabla rival
        rival_preds = result.get('rival_predictions', {})
        rival_data = []
        for const, pred in rival_preds.items():
            max_p = max(pred.items(), key=lambda x: x[1])
            rival_data.append({
                'Const': const.replace('k_', ''),
                '↑': f"{pred.get('incremento', 0):.0f}%",
                '⟳': f"{pred.get('reset', 0):.0f}%",
                '↓': f"{pred.get('decremento', 0):.0f}%",
                'Pred': max_p[0][:4],
            })
        
        if rival_data:
            self.rival_pred_table.setModel(PandasModel(pd.DataFrame(rival_data)))
            self.rival_pred_table.resizeColumnsToContents()
        rival_cond = "Visita" if condition == "Local" else "Local"
        self.rival_pred_table.parent().setTitle(f"🆚 {rival_name} ({rival_cond})")
        
        self.status_label.setText("✅ Predicciones cargadas")
    
    # =========================================================================
    # MANUAL
    # =========================================================================
    
    def _run_manual_prediction(self):
        if self.manual_worker and self.manual_worker.isRunning():
            return
        
        rival_id = self.combo_rival.currentData()
        if not rival_id:
            QMessageBox.warning(self, "Error", "Selecciona un rival")
            return
        
        is_home = self.combo_condition.currentText() == "Local"
        const_type = self.combo_const_manual.currentText()
        model_mode = self.combo_model_manual.currentData()
        league_id = self.team_leagues[0] if self.team_leagues else None
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.manual_result_label.setText("🔄 Calculando...")
        
        self.manual_worker = ManualPredictionWorker(self.team_id, rival_id, is_home, const_type, league_id, model_mode)
        self.manual_worker.finished.connect(self._on_manual_finished)
        self.manual_worker.error.connect(lambda e: self.manual_result_label.setText(f"❌ {e}"))
        self.manual_worker.start()
    
    def _on_manual_finished(self, result):
        self.progress_bar.setVisible(False)
        
        if 'error' in result:
            self.manual_result_label.setText(f"<p style='color:red;'>{result['error']}</p>")
            return
        
        pred = result['prediction']
        max_p = max(pred.items(), key=lambda x: x[1])
        colors = {'incremento': '#28a745', 'reset': '#ffc107', 'decremento': '#dc3545'}
        
        self.manual_result_label.setText(f"""
        <div style='text-align:center;'>
            <h3>{result['team_name']} vs {result['rival_name']}</h3>
            <p>{result['condition']} | Liga: {result.get('league_id', '-')} | Modelo: {result.get('model_used', '-')}</p>
            <hr>
            <table style='margin:20px auto;'>
                <tr>
                    <td style='padding:15px;text-align:center;'><span style='color:{colors['incremento']};font-size:24px;'>↑</span><br><b>Sube</b><br>{pred.get('incremento',0):.1f}%</td>
                    <td style='padding:15px;text-align:center;'><span style='color:{colors['reset']};font-size:24px;'>⟳</span><br><b>Reset</b><br>{pred.get('reset',0):.1f}%</td>
                    <td style='padding:15px;text-align:center;'><span style='color:{colors['decremento']};font-size:24px;'>↓</span><br><b>Baja</b><br>{pred.get('decremento',0):.1f}%</td>
                </tr>
            </table>
            <p style='font-size:18px;'><b>Predicción:</b> <span style='color:{colors[max_p[0]]};'>{max_p[0].upper()}</span> ({max_p[1]:.1f}%)</p>
        </div>
        """)
        self.status_label.setText("✅ Completado")
    
    # =========================================================================
    # ENTRENAMIENTO
    # =========================================================================
    
    def _start_training(self):
        if self.training_worker and self.training_worker.isRunning():
            return
        
        if self.radio_global.isChecked():
            mode, league_id = 'global', None
        elif self.radio_league.isChecked():
            mode = 'league'
            league_id = self.combo_league_train.currentData()
            if not league_id:
                QMessageBox.warning(self, "Error", "Selecciona liga")
                return
        else:
            mode, league_id = 'all', None
            if QMessageBox.question(self, "Confirmar", "¿Entrenar TODO?") != QMessageBox.Yes:
                return
        
        self.training_log.clear()
        self.training_progress.setValue(0)
        self.btn_train.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.training_worker = TrainingWorker(mode, league_id, self.spin_min_samples.value())
        self.training_worker.progress.connect(lambda p, m: (self.training_progress.setValue(p), self.training_status.setText(m)))
        self.training_worker.log_message.connect(lambda m: self.training_log.append(m))
        self.training_worker.finished.connect(self._on_training_finished)
        self.training_worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self.training_worker.start()
    
    def _stop_training(self):
        if self.training_worker:
            self.training_worker.stop()
    
    def _on_training_finished(self, result):
        self.btn_train.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.training_status.setText("✅ Completado")
        QMessageBox.information(self, "✅", f"Completado: {result.get('mode')}")
    
    def _show_model_status(self):
        try:
            from utils.global_constant_predictor import GlobalConstantPredictor
            predictor = GlobalConstantPredictor()
            status = predictor.get_model_status()
            
            self.training_log.clear()
            self.training_log.append("ESTADO DE MODELOS\n")
            self.training_log.append(f"Actualizado: {status.get('last_updated', 'N/A')}\n")
            
            for const, info in status.get('global_models', {}).items():
                self.training_log.append(f"  {const}: F1={info.get('f1', 0):.3f}")
            
            leagues = status.get('league_models', {})
            self.training_log.append(f"\nLigas entrenadas: {len(leagues)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
    
    # =========================================================================
    # UTILIDADES
    # =========================================================================
    
    def _export_results(self):
        tab = self.tabs.currentIndex()
        if tab == 0 and self.validation_data:
            df = pd.DataFrame(self.validation_data)
            name = f"validacion_{self.team_name}.csv"
        elif tab == 1 and self.next_match_data:
            data = []
            for k, v in self.next_match_data.get('team_predictions', {}).items():
                data.append({'who': 'team', 'const': k, **v})
            for k, v in self.next_match_data.get('rival_predictions', {}).items():
                data.append({'who': 'rival', 'const': k, **v})
            df = pd.DataFrame(data)
            name = f"prediccion_{self.team_name}.csv"
        else:
            QMessageBox.warning(self, "Sin datos", "No hay datos")
            return
        
        path, _ = QFileDialog.getSaveFileName(self, "Exportar", name, "CSV (*.csv)")
        if path:
            df.to_csv(path, index=False, encoding='utf-8-sig')
            QMessageBox.information(self, "✅", f"Guardado: {path}")
    
    def closeEvent(self, event):
        for w in [self.validation_worker, self.next_match_worker, self.manual_worker, self.training_worker]:
            if w and w.isRunning():
                w.quit()
                w.wait(2000)
        event.accept()