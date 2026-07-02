#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
marcador_window.py

LEY DEL MARCADOR - Predictor de Goles V6 (Poisson)
===================================================

Ventana para:
- Seleccionar equipo
- Ver historial de predicciones vs resultados reales
- Verificar precisión del modelo por equipo
- Ver predicción del próximo partido

Autor: Gerson (desarrollado con Claude)
Fecha: Enero 2026
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QGroupBox, QGridLayout, QFrame, QHeaderView, QMessageBox,
    QProgressBar, QApplication, QCompleter, QSplitter
)
from PySide6.QtCore import Qt, QThread, Signal, QSortFilterProxyModel, QStringListModel
from PySide6.QtGui import QFont, QColor, QBrush

logger = logging.getLogger(__name__)


def find_project_root() -> str:
    """
    Encuentra la raíz del proyecto (donde está sad.db y el modelo .pkl).
    
    Estructura esperada:
    D:\\VSCode Ejercicios 02\\          ← RAÍZ (sad.db, modelo.pkl)
    └── src\\
        ├── ml_goals_predictor_v6.py
        └── ui\\
            └── marcador_window.py      ← Este archivo
    """
    # Directorio de este archivo
    this_file = os.path.abspath(__file__)
    this_dir = os.path.dirname(this_file)
    
    logger.info(f"find_project_root - Este archivo: {this_file}")
    logger.info(f"find_project_root - Este directorio: {this_dir}")
    
    # Método 1: Si estamos en algo/ui/, subir dos niveles
    if this_dir.replace('\\', '/').endswith('/ui') or this_dir.endswith('\\ui'):
        # Estamos en src/ui/, subir a src/, luego a raíz
        project_root = os.path.dirname(os.path.dirname(this_dir))
        logger.info(f"find_project_root - Detectado en ui/, raíz calculada: {project_root}")
        
        # Verificar que existe el modelo o sad.db
        if os.path.exists(os.path.join(project_root, 'ml_goals_predictor_v6_model.pkl')):
            logger.info(f"find_project_root - ✓ Modelo encontrado en: {project_root}")
            return project_root
        if os.path.exists(os.path.join(project_root, 'sad.db')):
            logger.info(f"find_project_root - ✓ sad.db encontrado en: {project_root}")
            return project_root
    
    # Método 2: Buscar hacia arriba el modelo o sad.db
    current = this_dir
    for _ in range(5):
        model_path = os.path.join(current, 'ml_goals_predictor_v6_model.pkl')
        sad_path = os.path.join(current, 'sad.db')
        
        logger.info(f"find_project_root - Buscando en: {current}")
        
        if os.path.exists(model_path):
            logger.info(f"find_project_root - ✓ Modelo encontrado")
            return current
        if os.path.exists(sad_path):
            logger.info(f"find_project_root - ✓ sad.db encontrado")
            return current
        
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    
    # Fallback
    fallback = os.path.dirname(os.path.dirname(this_dir))
    logger.warning(f"find_project_root - Usando fallback: {fallback}")
    return fallback


def find_src_dir() -> str:
    """Encuentra el directorio src/ donde está ml_goals_predictor_v6.py"""
    project_root = find_project_root()
    src_dir = os.path.join(project_root, 'src')
    if os.path.exists(src_dir):
        return src_dir
    return project_root


class PredictorLoader(QThread):
    """Carga el predictor en background."""
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, project_root: str):
        super().__init__()
        self.project_root = project_root
    
    def run(self):
        try:
            logger.info(f"PredictorLoader - Usando project_root: {self.project_root}")
            
            # Agregar src/ al path para encontrar ml_goals_predictor_v6.py
            src_dir = os.path.join(self.project_root, 'src')
            if os.path.exists(src_dir) and src_dir not in sys.path:
                sys.path.insert(0, src_dir)
                logger.info(f"PredictorLoader - Agregado src al path: {src_dir}")
            
            # También agregar project_root por si acaso
            if self.project_root not in sys.path:
                sys.path.insert(0, self.project_root)
            
            # Importar el predictor
            from ml_goals_predictor_v6 import MLGoalsPredictorV6
            
            # El predictor usa project_root para encontrar las DBs y el modelo
            logger.info(f"PredictorLoader - Creando predictor con raíz: {self.project_root}")
            predictor = MLGoalsPredictorV6(self.project_root)
            
            # Verificar ruta del modelo
            logger.info(f"PredictorLoader - Model path del predictor: {predictor.model_path}")
            
            if predictor.load_model():
                self.finished.emit(predictor)
            else:
                self.error.emit("No se encontró el modelo entrenado.\n\nEjecuta primero:\npython ml_goals_predictor_v6.py")
        except ImportError as e:
            self.error.emit(f"No se encontró ml_goals_predictor_v6.py\n\nBuscado en:\n- {self.project_root}\n- {os.path.join(self.project_root, 'src')}\n\nError: {str(e)}")
        except Exception as e:
            import traceback
            logger.error(f"PredictorLoader error: {traceback.format_exc()}")
            self.error.emit(f"Error cargando modelo:\n{str(e)}")


class TeamHistoryWorker(QThread):
    """Calcula historial de predicciones para un equipo."""
    finished = Signal(list, dict)
    progress = Signal(int)
    error = Signal(str)
    
    def __init__(self, predictor, team_id: int, n_matches: int = 20):
        super().__init__()
        self.predictor = predictor
        self.team_id = team_id
        self.n_matches = n_matches
    
    def run(self):
        try:
            query = text("""
                SELECT id, date, home_team_id, away_team_id, goals_home, goals_away
                FROM fixtures
                WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                  AND status_long = 'Match Finished'
                  AND goals_home IS NOT NULL
                ORDER BY date DESC
                LIMIT :n
            """)
            
            matches = pd.read_sql_query(
                query, self.predictor.sad_engine,
                params={'team_id': self.team_id, 'n': self.n_matches}
            )
            
            results = []
            stats = {
                'total': 0,
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
            
            for idx, row in matches.iterrows():
                self.progress.emit(int((idx + 1) / len(matches) * 100))
                
                pred = self.predictor.predict(
                    row['home_team_id'], 
                    row['away_team_id'], 
                    row['date']
                )
                
                if pred is None:
                    continue
                
                gh = row['goals_home']
                ga = row['goals_away']
                total = gh + ga
                p = pred['probs']
                
                # Determinar si el equipo seleccionado es local o visitante
                is_home = row['home_team_id'] == self.team_id
                
                result = {
                    'date': row['date'],
                    'home_name': pred['home_name'],
                    'away_name': pred['away_name'],
                    'is_home': is_home,
                    'goals_home': gh,
                    'goals_away': ga,
                    'total_goals': total,
                    'lambda_home': pred['lambda_home'],
                    'lambda_away': pred['lambda_away'],
                    'lambda_total': pred['lambda_total'],
                    # Probabilidades Home
                    'pred_home_over_05': p['home_over_05'],
                    'pred_home_over_15': p['home_over_15'],
                    'pred_home_over_25': p['home_over_25'],
                    # Probabilidades Away
                    'pred_away_over_05': p['away_over_05'],
                    'pred_away_over_15': p['away_over_15'],
                    'pred_away_over_25': p['away_over_25'],
                    # Probabilidades Total
                    'pred_total_over_25': p['total_over_25'],
                    'pred_total_over_35': p['total_over_35'],
                    # BTTS
                    'pred_btts': p['btts'],
                }
                
                # Calcular aciertos para cada línea
                stats['total'] += 1
                
                # Home Over 0.5
                pred_h05 = p['home_over_05'] >= 0.5
                actual_h05 = gh >= 1
                stats['home_over_05']['total'] += 1
                if pred_h05 == actual_h05:
                    stats['home_over_05']['correct'] += 1
                result['home_over_05_correct'] = pred_h05 == actual_h05
                
                # Home Over 1.5
                pred_h15 = p['home_over_15'] >= 0.5
                actual_h15 = gh >= 2
                stats['home_over_15']['total'] += 1
                if pred_h15 == actual_h15:
                    stats['home_over_15']['correct'] += 1
                result['home_over_15_correct'] = pred_h15 == actual_h15
                
                # Home Over 2.5
                pred_h25 = p['home_over_25'] >= 0.5
                actual_h25 = gh >= 3
                stats['home_over_25']['total'] += 1
                if pred_h25 == actual_h25:
                    stats['home_over_25']['correct'] += 1
                result['home_over_25_correct'] = pred_h25 == actual_h25
                
                # Away Over 0.5
                pred_a05 = p['away_over_05'] >= 0.5
                actual_a05 = ga >= 1
                stats['away_over_05']['total'] += 1
                if pred_a05 == actual_a05:
                    stats['away_over_05']['correct'] += 1
                result['away_over_05_correct'] = pred_a05 == actual_a05
                
                # Away Over 1.5
                pred_a15 = p['away_over_15'] >= 0.5
                actual_a15 = ga >= 2
                stats['away_over_15']['total'] += 1
                if pred_a15 == actual_a15:
                    stats['away_over_15']['correct'] += 1
                result['away_over_15_correct'] = pred_a15 == actual_a15
                
                # Away Over 2.5
                pred_a25 = p['away_over_25'] >= 0.5
                actual_a25 = ga >= 3
                stats['away_over_25']['total'] += 1
                if pred_a25 == actual_a25:
                    stats['away_over_25']['correct'] += 1
                result['away_over_25_correct'] = pred_a25 == actual_a25
                
                # Total Over 2.5
                pred_t25 = p['total_over_25'] >= 0.5
                actual_t25 = total >= 3
                stats['total_over_25']['total'] += 1
                if pred_t25 == actual_t25:
                    stats['total_over_25']['correct'] += 1
                result['total_over_25_correct'] = pred_t25 == actual_t25
                
                # Total Over 3.5
                pred_t35 = p['total_over_35'] >= 0.5
                actual_t35 = total >= 4
                stats['total_over_35']['total'] += 1
                if pred_t35 == actual_t35:
                    stats['total_over_35']['correct'] += 1
                result['total_over_35_correct'] = pred_t35 == actual_t35
                
                # BTTS
                pred_btts = p['btts'] >= 0.5
                actual_btts = gh >= 1 and ga >= 1
                stats['btts']['total'] += 1
                if pred_btts == actual_btts:
                    stats['btts']['correct'] += 1
                result['btts_correct'] = pred_btts == actual_btts
                
                # Contar aciertos totales
                result['correct_count'] = sum([
                    result['home_over_05_correct'],
                    result['home_over_15_correct'],
                    result['home_over_25_correct'],
                    result['away_over_05_correct'],
                    result['away_over_15_correct'],
                    result['away_over_25_correct'],
                    result['total_over_25_correct'],
                    result['total_over_35_correct'],
                    result['btts_correct'],
                ])
                
                results.append(result)
            
            self.finished.emit(results, stats)
            
        except Exception as e:
            import traceback
            logger.error(f"TeamHistoryWorker error: {traceback.format_exc()}")
            self.error.emit(str(e))


class MarcadorWindow(QMainWindow):
    """Ventana principal de Ley del Marcador."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚽ Ley del Marcador - Predictor de Goles V6")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 700)
        
        self.project_root = find_project_root()
        logger.info(f"MarcadorWindow - project_root detectado: {self.project_root}")
        
        # Verificar que existe el modelo
        model_path = os.path.join(self.project_root, 'ml_goals_predictor_v6_model.pkl')
        logger.info(f"MarcadorWindow - Buscando modelo en: {model_path}")
        logger.info(f"MarcadorWindow - ¿Existe? {os.path.exists(model_path)}")
        
        # Agregar src/ al path para imports
        src_dir = os.path.join(self.project_root, 'src')
        if os.path.exists(src_dir) and src_dir not in sys.path:
            sys.path.insert(0, src_dir)
            logger.info(f"MarcadorWindow - Agregado al path: {src_dir}")
        if self.project_root not in sys.path:
            sys.path.insert(0, self.project_root)
        
        self.predictor = None
        self.teams_df = None
        self.current_team_id = None
        
        self._build_ui()
        self._load_predictor()
    
    def _build_ui(self):
        """Construye la interfaz."""
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(10)
        
        # ═══════════════════════════════════════════════════════
        # HEADER COMPACTO
        # ═══════════════════════════════════════════════════════
        header = QHBoxLayout()
        
        title = QLabel("⚽ LEY DEL MARCADOR")
        title.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
            color: #1a1a2e;
        """)
        header.addWidget(title)
        
        header.addStretch()
        
        # Status
        self.status_label = QLabel("⏳ Cargando...")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        header.addWidget(self.status_label)
        
        layout.addLayout(header)
        
        # ═══════════════════════════════════════════════════════
        # SELECTOR DE EQUIPO
        # ═══════════════════════════════════════════════════════
        selector_layout = QHBoxLayout()
        
        selector_layout.addWidget(QLabel("Equipo:"))
        
        self.combo_teams = QComboBox()
        self.combo_teams.setMinimumWidth(300)
        self.combo_teams.setEnabled(False)
        self.combo_teams.setEditable(True)
        self.combo_teams.setInsertPolicy(QComboBox.NoInsert)
        self.combo_teams.lineEdit().setPlaceholderText("Escribe para buscar...")
        self.combo_teams.currentIndexChanged.connect(self._on_team_selected)
        selector_layout.addWidget(self.combo_teams)
        
        self.btn_analyze = QPushButton("🔍 Analizar")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setStyleSheet("""
            QPushButton {
                background-color: #007BFF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0056b3; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.btn_analyze.clicked.connect(self._analyze_team)
        selector_layout.addWidget(self.btn_analyze)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setVisible(False)
        selector_layout.addWidget(self.progress_bar)
        
        selector_layout.addStretch()
        
        # Precisión general
        self.general_accuracy_label = QLabel("--")
        self.general_accuracy_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #007BFF;")
        selector_layout.addWidget(QLabel("📊 Precisión:"))
        selector_layout.addWidget(self.general_accuracy_label)
        
        layout.addLayout(selector_layout)
        
        # ═══════════════════════════════════════════════════════
        # ESTADÍSTICAS COMPACTAS
        # ═══════════════════════════════════════════════════════
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)
        
        self.stats_labels = {}
        stats_items = [
            ('home_over_05', 'H>0.5'),
            ('home_over_15', 'H>1.5'),
            ('home_over_25', 'H>2.5'),
            ('away_over_05', 'A>0.5'),
            ('away_over_15', 'A>1.5'),
            ('away_over_25', 'A>2.5'),
            ('total_over_25', 'T>2.5'),
            ('total_over_35', 'T>3.5'),
            ('btts', 'BTTS'),
        ]
        
        for key, label in stats_items:
            lbl = QLabel(f"{label}: --")
            lbl.setStyleSheet("font-size: 10px; color: #666;")
            self.stats_labels[key] = lbl
            stats_layout.addWidget(lbl)
        
        stats_layout.addStretch()
        layout.addLayout(stats_layout)
        
        # ═══════════════════════════════════════════════════════
        # SPLITTER VERTICAL: Tabla + Próximo Partido
        # ═══════════════════════════════════════════════════════
        splitter = QSplitter(Qt.Vertical)
        
        # --- TABLA DE HISTORIAL ---
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)
        
        self.table_history = QTableWidget()
        self.table_history.setColumnCount(14)
        self.table_history.setHorizontalHeaderLabels([
            "Fecha", "Partido", "Res", "λ Tot",
            "H>0.5", "H>1.5", "H>2.5",
            "A>0.5", "A>1.5", "A>2.5",
            "T>2.5", "T>3.5", "BTTS", "✓"
        ])
        header_view = self.table_history.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Interactive)
        header_view.setStretchLastSection(True)
        self.table_history.setColumnWidth(0, 80)
        self.table_history.setColumnWidth(1, 160)
        self.table_history.setColumnWidth(2, 40)
        self.table_history.setColumnWidth(3, 45)
        for i in range(4, 13):
            self.table_history.setColumnWidth(i, 45)
        self.table_history.setColumnWidth(13, 35)
        
        self.table_history.setAlternatingRowColors(True)
        self.table_history.setSortingEnabled(True)
        self.table_history.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 3px;
            }
        """)
        table_layout.addWidget(self.table_history)
        splitter.addWidget(table_widget)
        
        # --- PRÓXIMO PARTIDO ---
        next_widget = QWidget()
        next_widget.setMinimumHeight(120)
        next_layout = QVBoxLayout(next_widget)
        next_layout.setContentsMargins(10, 5, 10, 5)
        next_layout.setSpacing(5)
        
        next_header = QLabel("🔮 Próximo Partido")
        next_header.setStyleSheet("font-weight: bold; font-size: 14px; color: #1a1a2e;")
        next_layout.addWidget(next_header)
        
        # Frame contenedor con borde
        next_frame = QFrame()
        next_frame.setFrameStyle(QFrame.StyledPanel)
        next_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 8px;
            }
        """)
        frame_layout = QHBoxLayout(next_frame)
        frame_layout.setContentsMargins(15, 10, 15, 10)
        frame_layout.setSpacing(20)
        
        # Columna izquierda: Info del partido
        left_info = QVBoxLayout()
        left_info.setSpacing(3)
        
        self.next_match_teams = QLabel("Selecciona un equipo")
        self.next_match_teams.setStyleSheet("font-size: 15px; font-weight: bold; color: #1a1a2e;")
        left_info.addWidget(self.next_match_teams)
        
        self.next_match_date = QLabel("")
        self.next_match_date.setStyleSheet("font-size: 12px; color: #666;")
        left_info.addWidget(self.next_match_date)
        
        self.next_match_status = QLabel("")
        self.next_match_status.setStyleSheet("font-size: 11px; color: #007BFF; font-weight: bold;")
        left_info.addWidget(self.next_match_status)
        
        left_info.addStretch()
        frame_layout.addLayout(left_info)
        
        # Separador vertical
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setStyleSheet("color: #ddd;")
        frame_layout.addWidget(separator)
        
        # Columna central: Lambdas y probabilidades principales
        center_info = QVBoxLayout()
        center_info.setSpacing(2)
        
        self.next_lambda_label = QLabel("")
        self.next_lambda_label.setStyleSheet("font-size: 11px;")
        center_info.addWidget(self.next_lambda_label)
        
        self.next_home_probs = QLabel("")
        self.next_home_probs.setStyleSheet("font-size: 11px;")
        center_info.addWidget(self.next_home_probs)
        
        self.next_away_probs = QLabel("")
        self.next_away_probs.setStyleSheet("font-size: 11px;")
        center_info.addWidget(self.next_away_probs)
        
        self.next_total_probs = QLabel("")
        self.next_total_probs.setStyleSheet("font-size: 11px;")
        center_info.addWidget(self.next_total_probs)
        
        center_info.addStretch()
        frame_layout.addLayout(center_info)
        
        # Separador vertical
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.VLine)
        separator2.setStyleSheet("color: #ddd;")
        frame_layout.addWidget(separator2)
        
        # Columna derecha: Top scores
        right_info = QVBoxLayout()
        right_info.setSpacing(2)
        
        top_label = QLabel("🎯 Marcadores probables")
        top_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #333;")
        right_info.addWidget(top_label)
        
        self.next_top_scores = QLabel("")
        self.next_top_scores.setStyleSheet("font-size: 12px;")
        right_info.addWidget(self.next_top_scores)
        
        right_info.addStretch()
        frame_layout.addLayout(right_info)
        
        frame_layout.addStretch()
        
        next_layout.addWidget(next_frame)
        splitter.addWidget(next_widget)
        
        # Configurar splitter
        splitter.setChildrenCollapsible(False)  # No permitir colapsar completamente
        splitter.setSizes([450, 150])
        splitter.setStretchFactor(0, 1)  # Tabla se estira
        splitter.setStretchFactor(1, 0)  # Panel inferior tamaño fijo
        
        layout.addWidget(splitter, stretch=1)
        
        self.setCentralWidget(central)
        
        # Estilo global
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f8f9fa;
            }
            QSplitter::handle:vertical {
                background-color: #e0e0e0;
                height: 6px;
                border-radius: 3px;
                margin: 2px 50px;
            }
            QSplitter::handle:vertical:hover {
                background-color: #007BFF;
            }
        """)
    
    def _load_predictor(self):
        """Carga el predictor en background."""
        self.loader = PredictorLoader(self.project_root)
        self.loader.finished.connect(self._on_predictor_loaded)
        self.loader.error.connect(self._on_predictor_error)
        self.loader.start()
    
    def _on_predictor_loaded(self, predictor):
        """Callback cuando el predictor está listo."""
        self.predictor = predictor
        self.status_label.setText("✓ Modelo cargado")
        self.status_label.setStyleSheet("color: #28a745; font-size: 12px;")
        
        self._load_teams()
    
    def _on_predictor_error(self, error_msg):
        """Callback cuando hay error cargando el predictor."""
        self.status_label.setText(f"❌ Error: {error_msg}")
        self.status_label.setStyleSheet("color: #dc3545; font-size: 12px;")
        
        QMessageBox.critical(
            self, "Error",
            f"No se pudo cargar el modelo:\n\n{error_msg}\n\n"
            "Ejecuta primero:\npython ml_goals_predictor_v6.py"
        )
    
    def _load_teams(self):
        """Carga la lista de equipos."""
        try:
            # Obtener equipos con suficientes datos
            query = text("""
                SELECT DISTINCT t.id, t.name
                FROM teams t
                JOIN fixtures f ON (f.home_team_id = t.id OR f.away_team_id = t.id)
                WHERE f.status_long = 'Match Finished'
                GROUP BY t.id
                HAVING COUNT(*) >= 10
                ORDER BY t.name
            """)
            
            self.teams_df = pd.read_sql_query(query, self.predictor.sad_engine)
            
            self.combo_teams.clear()
            self.combo_teams.addItem("-- Seleccionar equipo --", None)
            
            for _, row in self.teams_df.iterrows():
                self.combo_teams.addItem(row['name'], row['id'])
            
            self.combo_teams.setEnabled(True)
            self.btn_analyze.setEnabled(True)
            
            # Configurar el completer para búsqueda
            completer = self.combo_teams.completer()
            if completer:
                completer.setCompletionMode(QCompleter.PopupCompletion)
                completer.setFilterMode(Qt.MatchContains)
            
            self.status_label.setText(f"✓ {len(self.teams_df)} equipos disponibles")
            self.status_label.setStyleSheet("color: #28a745; font-size: 11px;")
            
        except Exception as e:
            logger.error(f"Error cargando equipos: {e}")
            QMessageBox.warning(self, "Error", f"Error cargando equipos:\n{str(e)}")
    
    def _on_team_selected(self, index):
        """Callback cuando se selecciona un equipo."""
        team_id = self.combo_teams.currentData()
        self.current_team_id = team_id
    
    def _analyze_team(self):
        """Analiza el equipo seleccionado."""
        if self.current_team_id is None:
            QMessageBox.warning(self, "Atención", "Selecciona un equipo primero")
            return
        
        self.btn_analyze.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Limpiar tabla
        self.table_history.setRowCount(0)
        
        # Iniciar worker
        self.history_worker = TeamHistoryWorker(
            self.predictor, self.current_team_id, n_matches=20
        )
        self.history_worker.finished.connect(self._on_history_loaded)
        self.history_worker.progress.connect(self.progress_bar.setValue)
        self.history_worker.error.connect(self._on_history_error)
        self.history_worker.start()
        
        # Cargar próximo partido
        self._load_next_match()
    
    def _on_history_loaded(self, results: list, stats: dict):
        """Callback cuando el historial está listo."""
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        
        # Llenar tabla
        self.table_history.setRowCount(len(results))
        
        for i, r in enumerate(results):
            # Fecha
            date_str = pd.to_datetime(r['date']).strftime('%Y-%m-%d')
            self.table_history.setItem(i, 0, QTableWidgetItem(date_str))
            
            # Partido
            match_str = f"{r['home_name'][:12]} vs {r['away_name'][:12]}"
            item = QTableWidgetItem(match_str)
            if r['is_home']:
                item.setBackground(QBrush(QColor(232, 245, 233)))  # Verde claro - Local
            else:
                item.setBackground(QBrush(QColor(227, 242, 253)))  # Azul claro - Visitante
            item.setToolTip(f"{r['home_name']} vs {r['away_name']}")
            self.table_history.setItem(i, 1, item)
            
            # Resultado
            result_str = f"{int(r['goals_home'])}-{int(r['goals_away'])}"
            self.table_history.setItem(i, 2, QTableWidgetItem(result_str))
            
            # λ Total
            lambda_str = f"{r['lambda_total']:.2f}"
            self.table_history.setItem(i, 3, QTableWidgetItem(lambda_str))
            
            # Helper para crear celdas con recomendación O/U
            def create_recommendation_cell(prob: float, correct: bool, is_btts: bool = False) -> QTableWidgetItem:
                """
                Muestra O (Over) si prob >= 50%, U (Under) si < 50%
                Para BTTS: Y (Yes) o N (No)
                Color verde si acertó, rojo si falló
                """
                is_over = prob >= 0.5
                if is_btts:
                    text = "Y" if is_over else "N"
                    tooltip = f"{'Yes' if is_over else 'No'} ({prob:.0%})"
                else:
                    text = "O" if is_over else "U"
                    tooltip = f"{'Over' if is_over else 'Under'} ({prob:.0%})"
                
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(tooltip)
                
                if correct:
                    item.setForeground(QBrush(QColor(255, 255, 255)))  # Texto blanco
                    item.setBackground(QBrush(QColor(40, 167, 69)))   # Fondo verde
                else:
                    item.setForeground(QBrush(QColor(255, 255, 255)))  # Texto blanco
                    item.setBackground(QBrush(QColor(220, 53, 69)))   # Fondo rojo
                return item
            
            # Home Over 0.5, 1.5, 2.5
            self.table_history.setItem(i, 4, create_recommendation_cell(r['pred_home_over_05'], r['home_over_05_correct']))
            self.table_history.setItem(i, 5, create_recommendation_cell(r['pred_home_over_15'], r['home_over_15_correct']))
            self.table_history.setItem(i, 6, create_recommendation_cell(r['pred_home_over_25'], r['home_over_25_correct']))
            
            # Away Over 0.5, 1.5, 2.5
            self.table_history.setItem(i, 7, create_recommendation_cell(r['pred_away_over_05'], r['away_over_05_correct']))
            self.table_history.setItem(i, 8, create_recommendation_cell(r['pred_away_over_15'], r['away_over_15_correct']))
            self.table_history.setItem(i, 9, create_recommendation_cell(r['pred_away_over_25'], r['away_over_25_correct']))
            
            # Total Over 2.5, 3.5
            self.table_history.setItem(i, 10, create_recommendation_cell(r['pred_total_over_25'], r['total_over_25_correct']))
            self.table_history.setItem(i, 11, create_recommendation_cell(r['pred_total_over_35'], r['total_over_35_correct']))
            
            # BTTS (Yes/No)
            self.table_history.setItem(i, 12, create_recommendation_cell(r['pred_btts'], r['btts_correct'], is_btts=True))
            
            # Estado general (aciertos/total)
            correct_count = r['correct_count']
            status_str = f"{correct_count}/9"
            status_item = QTableWidgetItem(status_str)
            status_item.setTextAlignment(Qt.AlignCenter)
            if correct_count >= 7:
                status_item.setBackground(QBrush(QColor(212, 237, 218)))  # Verde
            elif correct_count >= 5:
                status_item.setBackground(QBrush(QColor(255, 243, 205)))  # Amarillo
            else:
                status_item.setBackground(QBrush(QColor(248, 215, 218)))  # Rojo
            self.table_history.setItem(i, 13, status_item)
        
        # Actualizar estadísticas
        self._update_stats(stats)
    
    def _on_history_error(self, error_msg):
        """Callback cuando hay error."""
        self.progress_bar.setVisible(False)
        self.btn_analyze.setEnabled(True)
        QMessageBox.warning(self, "Error", f"Error analizando equipo:\n{error_msg}")
    
    def _update_stats(self, stats: dict):
        """Actualiza las estadísticas de precisión."""
        total_correct = 0
        total_predictions = 0
        
        key_to_label = {
            'home_over_05': 'H>0.5',
            'home_over_15': 'H>1.5',
            'home_over_25': 'H>2.5',
            'away_over_05': 'A>0.5',
            'away_over_15': 'A>1.5',
            'away_over_25': 'A>2.5',
            'total_over_25': 'T>2.5',
            'total_over_35': 'T>3.5',
            'btts': 'BTTS',
        }
        
        for key, label_widget in self.stats_labels.items():
            s = stats.get(key, {'correct': 0, 'total': 0})
            short_name = key_to_label.get(key, key)
            
            if s['total'] > 0:
                acc = s['correct'] / s['total'] * 100
                label_widget.setText(f"{short_name}: {acc:.0f}%")
                
                if acc >= 70:
                    label_widget.setStyleSheet("font-size: 10px; color: #28a745; font-weight: bold;")
                elif acc >= 55:
                    label_widget.setStyleSheet("font-size: 10px; color: #856404;")
                else:
                    label_widget.setStyleSheet("font-size: 10px; color: #dc3545;")
                
                total_correct += s['correct']
                total_predictions += s['total']
            else:
                label_widget.setText(f"{short_name}: --")
                label_widget.setStyleSheet("font-size: 10px; color: #666;")
        
        # Precisión general
        if total_predictions > 0:
            general_acc = total_correct / total_predictions * 100
            self.general_accuracy_label.setText(f"{general_acc:.1f}%")
            
            if general_acc >= 65:
                self.general_accuracy_label.setStyleSheet(
                    "font-size: 16px; font-weight: bold; color: #28a745;"
                )
            elif general_acc >= 50:
                self.general_accuracy_label.setStyleSheet(
                    "font-size: 16px; font-weight: bold; color: #856404;"
                )
            else:
                self.general_accuracy_label.setStyleSheet(
                    "font-size: 16px; font-weight: bold; color: #dc3545;"
                )
    
    def _load_next_match(self):
        """Carga el próximo partido del equipo."""
        if self.current_team_id is None:
            return
        
        # Reset labels
        self._reset_next_match_labels()
        
        try:
            team_name = self.predictor.get_team_name(self.current_team_id)
            
            # 1. Encontrar el último partido JUGADO de este equipo
            last_played_query = text("""
                SELECT date
                FROM fixtures
                WHERE (home_team_id = :team_id OR away_team_id = :team_id)
                  AND status_long = 'Match Finished'
                  AND goals_home IS NOT NULL
                ORDER BY date DESC
                LIMIT 1
            """)
            
            last_played = pd.read_sql_query(
                last_played_query, self.predictor.sad_engine,
                params={'team_id': self.current_team_id}
            )
            
            if last_played.empty:
                self.next_match_teams.setText(f"⚠️ No hay partidos jugados")
                self.next_match_teams.setStyleSheet("font-size: 13px; color: #856404;")
                return
            
            last_date = last_played['date'].iloc[0]
            
            # 2. Buscar el SIGUIENTE partido después del último jugado (sin resultado)
            next_query = text("""
                SELECT f.id, f.date, f.home_team_id, f.away_team_id, f.league_id, 
                       f.status_long, t1.name as home_name, t2.name as away_name
                FROM fixtures f
                LEFT JOIN teams t1 ON f.home_team_id = t1.id
                LEFT JOIN teams t2 ON f.away_team_id = t2.id
                WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
                  AND f.date > :last_date
                  AND (f.goals_home IS NULL OR f.status_long = 'Not Started')
                ORDER BY f.date ASC
                LIMIT 1
            """)
            
            result = pd.read_sql_query(
                next_query, self.predictor.sad_engine,
                params={'team_id': self.current_team_id, 'last_date': last_date}
            )
            
            if result.empty:
                self.next_match_teams.setText(f"⚠️ No hay próximos partidos")
                self.next_match_teams.setStyleSheet("font-size: 13px; color: #856404;")
                self.next_match_date.setText(f"después de {pd.to_datetime(last_date).strftime('%d/%m/%Y')}")
                return
            
            row = result.iloc[0]
            home_id = int(row['home_team_id'])
            away_id = int(row['away_team_id'])
            home_name = row['home_name'] or f"Team_{home_id}"
            away_name = row['away_name'] or f"Team_{away_id}"
            match_date = pd.to_datetime(row['date'])
            date_str = match_date.strftime('%d/%m/%Y %H:%M')
            is_home = home_id == self.current_team_id
            
            # Mostrar info básica del partido
            self.next_match_teams.setText(f"🏟️ {home_name} vs {away_name}")
            self.next_match_teams.setStyleSheet("font-size: 15px; font-weight: bold; color: #1a1a2e;")
            self.next_match_date.setText(f"📅 {date_str}")
            self.next_match_status.setText(f"{'🏠 LOCAL' if is_home else '✈️ VISITANTE'}")
            self.next_match_status.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {'#28a745' if is_home else '#007BFF'};")
            
            # Intentar predecir
            pred = self.predictor.predict(home_id, away_id, match_date)
            
            if pred is None:
                # Diagnóstico detallado
                home_stats = self.predictor.get_team_stats(home_id, match_date)
                away_stats = self.predictor.get_team_stats(away_id, match_date)
                
                home_ok = "✓" if home_stats is not None else "✗"
                away_ok = "✓" if away_stats is not None else "✗"
                
                home_count = self._count_team_matches(home_id, match_date)
                away_count = self._count_team_matches(away_id, match_date)
                
                self.next_lambda_label.setText("⚠️ Sin datos suficientes")
                self.next_lambda_label.setStyleSheet("font-size: 12px; color: #856404; font-weight: bold;")
                self.next_home_probs.setText(f"• {home_name}: {home_count} partidos {home_ok}")
                self.next_away_probs.setText(f"• {away_name}: {away_count} partidos {away_ok}")
                self.next_total_probs.setText("Se necesitan mín. 5 partidos")
                self.next_total_probs.setStyleSheet("font-size: 10px; color: #666; font-style: italic;")
                return
            
            # Mostrar predicción completa
            p = pred['probs']
            top_scores = pred['top_scores']
            
            # Lambdas
            self.next_lambda_label.setText(
                f"<b>λ:</b> {pred['home_name'][:12]}=<b>{pred['lambda_home']:.2f}</b> | "
                f"{pred['away_name'][:12]}=<b>{pred['lambda_away']:.2f}</b> | "
                f"Total=<b>{pred['lambda_total']:.2f}</b>"
            )
            
            # Home probs
            self.next_home_probs.setText(
                f"<b>Home:</b> O0.5=<span style='color:#28a745'>{p['home_over_05']:.0%}</span> | "
                f"O1.5=<span style='color:#ffc107'>{p['home_over_15']:.0%}</span> | "
                f"O2.5=<span style='color:#dc3545'>{p['home_over_25']:.0%}</span>"
            )
            
            # Away probs
            self.next_away_probs.setText(
                f"<b>Away:</b> O0.5=<span style='color:#28a745'>{p['away_over_05']:.0%}</span> | "
                f"O1.5=<span style='color:#ffc107'>{p['away_over_15']:.0%}</span> | "
                f"O2.5=<span style='color:#dc3545'>{p['away_over_25']:.0%}</span>"
            )
            
            # Total probs
            self.next_total_probs.setText(
                f"<b>Total:</b> O2.5=<span style='color:#007BFF'>{p['total_over_25']:.0%}</span> | "
                f"O3.5=<span style='color:#6f42c1'>{p['total_over_35']:.0%}</span> | "
                f"BTTS=<span style='color:#e83e8c'>{p['btts']:.0%}</span>"
            )
            
            # Top scores
            scores_text = ""
            for i, (h, a, prob) in enumerate(top_scores[:3]):
                scores_text += f"<b>{int(h)}-{int(a)}</b> ({prob:.0%})"
                if i < 2:
                    scores_text += " | "
            self.next_top_scores.setText(scores_text)
            
        except Exception as e:
            import traceback
            logger.error(f"Error cargando próximo partido: {traceback.format_exc()}")
            self.next_match_teams.setText(f"❌ Error: {str(e)[:50]}")
            self.next_match_teams.setStyleSheet("font-size: 12px; color: #dc3545;")
    
    def _reset_next_match_labels(self):
        """Resetea los labels del próximo partido."""
        self.next_match_teams.setText("Cargando...")
        self.next_match_teams.setStyleSheet("font-size: 13px; color: #666;")
        self.next_match_date.setText("")
        self.next_match_status.setText("")
        self.next_lambda_label.setText("")
        self.next_home_probs.setText("")
        self.next_away_probs.setText("")
        self.next_total_probs.setText("")
        self.next_top_scores.setText("")
    
    def _count_team_matches(self, team_id: int, before_date: datetime = None) -> int:
        """Cuenta partidos históricos de un equipo."""
        try:
            team_id = int(team_id)  # Asegurar int nativo
            
            if before_date is None:
                query = text("""
                    SELECT COUNT(*) as cnt
                    FROM fixtures
                    WHERE (home_team_id = :tid OR away_team_id = :tid)
                      AND status_long = 'Match Finished'
                      AND goals_home IS NOT NULL
                """)
                result = pd.read_sql_query(query, self.predictor.sad_engine, params={'tid': team_id})
            else:
                if hasattr(before_date, 'strftime'):
                    date_str = before_date.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    date_str = str(before_date)
                
                query = text("""
                    SELECT COUNT(*) as cnt
                    FROM fixtures
                    WHERE (home_team_id = :tid OR away_team_id = :tid)
                      AND status_long = 'Match Finished'
                      AND goals_home IS NOT NULL
                      AND date < :before_date
                """)
                result = pd.read_sql_query(query, self.predictor.sad_engine, params={
                    'tid': team_id,
                    'before_date': date_str
                })
                
            return int(result['cnt'].iloc[0])
        except Exception as e:
            logger.error(f"Error contando partidos para team {team_id}: {e}")
            return -1


def main():
    """Función principal para testing."""
    app = QApplication(sys.argv)
    window = MarcadorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()