# src/ui/anticulebra/anticulebra_window.py
# -*- coding: utf-8 -*-
"""
🗲 VENTANA LEY DE LAS CULEBRAS v4
Interface con ML real, tabla compacta y splitter arrastrable.

Autor: Sistema de Análisis Deportivo
"""

import logging
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QFrame, QScrollArea, QSplitter, QSpinBox,
    QTextEdit, QSlider, QDoubleSpinBox, QMessageBox, QSizePolicy,
    QApplication, QRadioButton, QButtonGroup, QCheckBox, QAbstractItemView
)
from PySide6.QtCore import Qt, QDate, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPalette, QBrush

from .anticulebra_engine import (
    AnticulebraEngine, MatchPrediction, DayAnalysis, JornadaAnalysis,
    CalibrationResult, ValidationMetrics, MLTrainingResult,
    format_probability, format_odds, get_tension_color, 
    get_break_type_emoji, get_outcome_emoji
)

logger = logging.getLogger(__name__)


# =============================================================================
# COLORES
# =============================================================================

class Colors:
    PRIMARY = "#1a1a2e"
    SECONDARY = "#16213e"
    ACCENT = "#FF6B35"
    SNAKE = "#6B5B95"
    
    SUCCESS = "#28A745"
    WARNING = "#FFC107"
    DANGER = "#DC3545"
    INFO = "#17A2B8"
    
    DRAW = "#9B59B6"
    UNDERDOG = "#E74C3C"
    
    CARD_BG = "#FFFFFF"
    TEXT_PRIMARY = "#212529"
    TEXT_SECONDARY = "#6C757D"
    BACKGROUND = "#F8F9FA"
    
    GOLD = "#FFD700"
    SILVER = "#C0C0C0"
    BRONZE = "#CD7F32"


STYLESHEET = """
QMainWindow { background-color: #F8F9FA; }
QTabWidget::pane {
    border: 1px solid #E0E0E0;
    background-color: white;
    border-radius: 8px;
}
QTabBar::tab {
    padding: 10px 20px;
    margin-right: 2px;
    background-color: #E9ECEF;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QTabBar::tab:selected {
    background-color: #6B5B95;
    color: white;
    font-weight: bold;
}
QGroupBox {
    font-weight: bold;
    border: 2px solid #E0E0E0;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 10px;
    background-color: white;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 10px;
    color: #6B5B95;
}
QPushButton {
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 500;
}
QPushButton#primaryBtn {
    background-color: #6B5B95;
    color: white;
    border: none;
}
QPushButton#primaryBtn:hover { background-color: #5a4a84; }
QPushButton#successBtn {
    background-color: #28A745;
    color: white;
    border: none;
}
QPushButton#dangerBtn {
    background-color: #DC3545;
    color: white;
    border: none;
}
QPushButton#mlBtn {
    background-color: #17A2B8;
    color: white;
    border: none;
}
QPushButton#mlBtn:hover { background-color: #138496; }
QTableWidget {
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    gridline-color: #F0F0F0;
    font-size: 12px;
}
QTableWidget::item { padding: 6px; }
QHeaderView::section {
    background-color: #6B5B95;
    color: white;
    padding: 8px;
    border: none;
    font-weight: bold;
    font-size: 11px;
}
QProgressBar {
    border: 1px solid #E0E0E0;
    border-radius: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #6B5B95;
    border-radius: 3px;
}
QSplitter::handle {
    background-color: #E0E0E0;
}
QSplitter::handle:horizontal {
    width: 6px;
}
QSplitter::handle:vertical {
    height: 6px;
}
QSplitter::handle:hover {
    background-color: #6B5B95;
}
"""


# =============================================================================
# WIDGETS
# =============================================================================

class KPICard(QFrame):
    def __init__(self, icon: str, title: str, value: str = "0", 
                 color: str = Colors.PRIMARY, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 12px;
                padding: 15px;
            }}
        """)
        self.setMinimumSize(140, 90)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        
        self.icon_label = QLabel(icon)
        self.icon_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(self.icon_label)
        
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color};")
        layout.addWidget(self.value_label)
        
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 10px;")
        layout.addWidget(self.title_label)
    
    def set_value(self, value: str, color: str = None):
        self.value_label.setText(value)
        if color:
            self.value_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color};")


class BreakdownBar(QFrame):
    """Barra de desglose Empate/Underdog."""
    
    def __init__(self, prob_draw: float = 0, prob_underdog: float = 0, parent=None):
        super().__init__(parent)
        self.prob_draw = prob_draw
        self.prob_underdog = prob_underdog
        self.setMinimumHeight(40)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        
        # Calcular porcentajes normalizados (que sumen 100%)
        total = self.prob_draw + self.prob_underdog
        if total > 0:
            draw_pct = self.prob_draw / total
            under_pct = self.prob_underdog / total
        else:
            draw_pct = under_pct = 0.5
        
        labels = QHBoxLayout()
        labels.addWidget(QLabel(f"═ {draw_pct*100:.0f}%"))
        labels.addStretch()
        labels.addWidget(QLabel(f"✖ {under_pct*100:.0f}%"))
        layout.addLayout(labels)
        
        bar = QHBoxLayout()
        bar.setSpacing(2)
        
        
        draw_bar = QFrame()
        draw_bar.setStyleSheet(f"background-color: {Colors.DRAW}; border-radius: 3px;")
        draw_bar.setMinimumHeight(10)
        
        under_bar = QFrame()
        under_bar.setStyleSheet(f"background-color: {Colors.UNDERDOG}; border-radius: 3px;")
        under_bar.setMinimumHeight(10)
        
        bar.addWidget(draw_bar, int(draw_pct * 100))
        bar.addWidget(under_bar, int(under_pct * 100))
        layout.addLayout(bar)
    
    def update_values(self, prob_draw: float, prob_underdog: float):
        self.prob_draw = prob_draw
        self.prob_underdog = prob_underdog
        
        # Eliminar layout anterior completamente
        old_layout = self.layout()
        if old_layout:
            # Eliminar todos los items recursivamente
            def delete_items(layout):
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                    elif item.layout():
                        delete_items(item.layout())
            delete_items(old_layout)
            # Eliminar el layout del widget
            QWidget().setLayout(old_layout)
        
        self._build_ui()


class CandidatePanel(QFrame):
    """Panel destacado del candidato ML con resultado."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
    
    def _build_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #FFF8E7;
                border: 3px solid #FF6B35;
                border-radius: 12px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        
        # Título
        self.title_label = QLabel("⚡ CANDIDATO ML")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #FF6B35;")
        layout.addWidget(self.title_label)
        
        # Partido
        self.match_label = QLabel("Selecciona una fecha")
        self.match_label.setStyleSheet("font-size: 13px; color: #333;")
        self.match_label.setWordWrap(True)
        layout.addWidget(self.match_label)
        
        # Score ML
        self.score_label = QLabel("")
        self.score_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #6B5B95;")
        layout.addWidget(self.score_label)
        
        # Predicción explícita
        self.prediction_label = QLabel("")
        self.prediction_label.setStyleSheet("font-size: 12px; color: #333; background-color: #E9ECEF; padding: 5px; border-radius: 4px;")
        self.prediction_label.setWordWrap(True)
        layout.addWidget(self.prediction_label)
        
        # Resultado (si ya terminó)
        self.result_frame = QFrame()
        self.result_frame.setStyleSheet("background: transparent; border: none;")
        result_layout = QHBoxLayout(self.result_frame)
        result_layout.setContentsMargins(0, 5, 0, 0)
        
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        result_layout.addWidget(self.result_label)
        result_layout.addStretch()
        
        layout.addWidget(self.result_frame)
        
        # Razones
        self.reasons_label = QLabel("")
        self.reasons_label.setStyleSheet("font-size: 10px; color: #666;")
        self.reasons_label.setWordWrap(True)
        layout.addWidget(self.reasons_label)
    
    def update_candidate(self, analysis: DayAnalysis):
        if analysis.ml_candidate_match is None:
            self.title_label.setText("⚡ Sin candidato claro")
            self.match_label.setText("No hay datos suficientes")
            self.score_label.setText("")
            self.prediction_label.setText("")
            self.result_label.setText("")
            self.reasons_label.setText("")
            self.setStyleSheet("""
                QFrame {
                    background-color: #E9ECEF;
                    border: 2px solid #CED4DA;
                    border-radius: 12px;
                    padding: 10px;
                }
            """)
            return
        
        cand = analysis.ml_candidate_match
        
        # Color según tipo predicho
        if cand.ml_break_type_pred == "draw":
            bg_color = "#F3E5F5"
            border_color = Colors.DRAW
            type_emoji = "⚡"
            type_name = "EMPATE"
        else:
            bg_color = "#FFEBEE"
            border_color = Colors.UNDERDOG
            type_emoji = "⚡"
            type_name = "UNDERDOG"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 3px solid {border_color};
                border-radius: 12px;
                padding: 10px;
            }}
        """)
        
        self.title_label.setText(f"⚡ #{analysis.ml_candidate_position} - Riesgo {type_emoji} {type_name}")
        
        # Info del partido
        time_str = cand.date.strftime("%H:%M") if cand.date else "--:--"
        self.match_label.setText(
            f"● {cand.home_team_name} vs {cand.away_team_name}\n"
            f"⚡ {time_str}"
        )
        
        # Score ML
        self.score_label.setText(f"⚡ Score ML: {analysis.ml_candidate_score:.2f}")
        
        # Predicción explícita
        if cand.favorite == "home":
            fav_name = cand.home_team_name
            pred_icon = "⚡ "
        elif cand.favorite == "away":
            fav_name = cand.away_team_name
            pred_icon = "◉"
        elif cand.favorite == "draw":
            fav_name = "Empate"
            pred_icon = "⚡"
        else:
            fav_name = "Nadie (parejo)"
            pred_icon = "≡"
        
        self.prediction_label.setText(
            f"► Predicción: {pred_icon} {fav_name} gana ({cand.favorite_prob*100:.0f}%)\n"
            f"⚡ Prob. 1:{cand.prob_home*100:.0f}% X:{cand.prob_draw*100:.0f}% 2:{cand.prob_away*100:.0f}%"
        )
        
        # Resultado si ya terminó
        if cand.goals_home is not None and cand.goals_away is not None:
            score_text = f"{cand.goals_home}-{cand.goals_away}"
            
            if cand.favorite == "none":
                self.result_label.setText(f"● Resultado: {score_text} (partido parejo)")
                self.result_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #666;")
            elif cand.favorite_won:
                self.result_label.setText(f"✓ Resultado: {score_text} - ¡ACERTÁ“!")
                self.result_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #155724; background-color: #D4EDDA; padding: 5px; border-radius: 4px;")
            else:
                if cand.break_type == "draw":
                    self.result_label.setText(f"🗲✖ Resultado: {score_text} - Rompió aquí (empate)")
                else:
                    self.result_label.setText(f"🗲✖ Resultado: {score_text} - Rompió aquí")
                self.result_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #721C24; background-color: #F8D7DA; padding: 5px; border-radius: 4px;")
        else:
            self.result_label.setText("◔ Partido pendiente")
            self.result_label.setStyleSheet("font-size: 12px; color: #666;")
        
        # Razones
        if analysis.ml_candidate_reasons:
            self.reasons_label.setText("⚡ " + " | ".join(analysis.ml_candidate_reasons[:3]))


class MatchesTable(QTableWidget):
    """Tabla compacta de partidos ordenados por ML."""
    
    COLUMNS = ["Rank", "Partido", "Score", "1", "X", "2", "Predicción", "ML", "Resultado"]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup()
    
    def _setup(self):
        self.setColumnCount(len(self.COLUMNS))
        self.setHorizontalHeaderLabels(self.COLUMNS)
        
        # Rank - pequeño
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        # Partido - expandible
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        # Score - pequeño
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # 1, X, 2 - pequeños
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        # Predicción - mediano
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        # ML Score - pequeño
        self.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        # Resultado - pequeño
        self.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)
    
    def populate(self, analysis: DayAnalysis):
        """Llena la tabla con los partidos rankeados por ML."""
        self.setRowCount(0)
        
        if not analysis.matches_ranked_by_ml:
            return
        
        self.setRowCount(len(analysis.matches_ranked_by_ml))
        
        for row, (pos, match, ml_score) in enumerate(analysis.matches_ranked_by_ml):
            # Rank con medallas
            if row == 0:
                rank_text = "⚡"
            elif row == 1:
                rank_text = "⚡"
            elif row == 2:
                rank_text = "⚡"
            else:
                rank_text = f"#{row + 1}"
            
            rank_item = QTableWidgetItem(rank_text)
            rank_item.setTextAlignment(Qt.AlignCenter)
            if row < 3:
                rank_item.setFont(QFont("", 14))
            self.setItem(row, 0, rank_item)
            
            # Partido (hora + equipos)
            time_str = match.date.strftime("%H:%M") if match.date else "--:--"
            match_text = f"{time_str} {match.home_team_name[:15]} vs {match.away_team_name[:15]}"
            match_item = QTableWidgetItem(match_text)
            if row == 0:
                match_item.setBackground(QColor("#FFF3CD"))
            self.setItem(row, 1, match_item)
            
            # Score del partido (si ya terminó)
            if match.goals_home is not None and match.goals_away is not None:
                score_text = f"{match.goals_home}-{match.goals_away}"
                score_item = QTableWidgetItem(score_text)
                score_item.setTextAlignment(Qt.AlignCenter)
                score_item.setFont(QFont("", 11, QFont.Bold))
                # Color según resultado
                if match.outcome == "X":
                    score_item.setBackground(QColor("#E2D5F1"))  # Empate = morado
                elif match.outcome == "1":
                    score_item.setBackground(QColor("#D4EDDA"))  # Local = verde
                else:
                    score_item.setBackground(QColor("#CFE2FF"))  # Visita = azul
            else:
                score_item = QTableWidgetItem("--")
                score_item.setTextAlignment(Qt.AlignCenter)
                score_item.setForeground(QColor("#999"))
            self.setItem(row, 2, score_item)
            
            # Probabilidades 1X2
            prob_home_item = QTableWidgetItem(f"{match.prob_home*100:.0f}%")
            prob_home_item.setTextAlignment(Qt.AlignCenter)
            if match.favorite == "home":
                prob_home_item.setBackground(QColor("#D4EDDA"))
                prob_home_item.setFont(QFont("", -1, QFont.Bold))
            self.setItem(row, 3, prob_home_item)
            
            prob_draw_item = QTableWidgetItem(f"{match.prob_draw*100:.0f}%")
            prob_draw_item.setTextAlignment(Qt.AlignCenter)
            if match.prob_draw >= 0.28:
                prob_draw_item.setBackground(QColor("#E2D5F1"))
            self.setItem(row, 4, prob_draw_item)
            
            prob_away_item = QTableWidgetItem(f"{match.prob_away*100:.0f}%")
            prob_away_item.setTextAlignment(Qt.AlignCenter)
            if match.favorite == "away":
                prob_away_item.setBackground(QColor("#D4EDDA"))
                prob_away_item.setFont(QFont("", -1, QFont.Bold))
            self.setItem(row, 5, prob_away_item)
            
            # Predicción explícita (a quién le va el modelo)
            if match.favorite == "home":
                fav_name = match.home_team_name[:10]
                pred_text = f"⚡  {fav_name} ({match.favorite_prob*100:.0f}%)"
            elif match.favorite == "away":
                fav_name = match.away_team_name[:10]
                pred_text = f"◉ {fav_name} ({match.favorite_prob*100:.0f}%)"
            elif match.favorite == "draw":
                pred_text = f"⚡ Empate ({match.favorite_prob*100:.0f}%)"
            else:
                pred_text = "≡ Parejo"
            
            pred_item = QTableWidgetItem(pred_text)
            self.setItem(row, 6, pred_item)
            
            # ML Score con indicador de tipo (E=empate, U=underdog)
            ml_type_indicator = ""
            if match.ml_break_type_pred == "draw":
                ml_type_indicator = " (E)"
            elif match.ml_break_type_pred == "underdog":
                ml_type_indicator = " (U)"
            
            ml_item = QTableWidgetItem(f"{ml_score:.2f}{ml_type_indicator}")
            ml_item.setTextAlignment(Qt.AlignCenter)
            if ml_score >= 0.6:
                ml_item.setBackground(QColor("#F8D7DA"))
            elif ml_score >= 0.4:
                ml_item.setBackground(QColor("#FFF3CD"))
            self.setItem(row, 7, ml_item)
            
            # Resultado: ¿Cumplió el modelo?
            if match.outcome is not None:
                if match.favorite == "none":
                    # Partido parejo - no hay predicción clara
                    result_text = "—"
                    result_item = QTableWidgetItem(result_text)
                    result_item.setToolTip("Partido parejo, sin predicción clara")
                elif match.favorite_won is True:
                    result_text = "✓ Cumplió"
                    result_item = QTableWidgetItem(result_text)
                    result_item.setBackground(QColor("#D4EDDA"))
                    result_item.setForeground(QColor("#155724"))
                elif match.favorite_won is False:
                    if match.break_type == "draw":
                        result_text = "🗲✖ Rompió (X)"
                    else:
                        result_text = "🗲✖ Rompió"
                    result_item = QTableWidgetItem(result_text)
                    result_item.setBackground(QColor("#F8D7DA"))
                    result_item.setForeground(QColor("#721C24"))
                else:
                    result_text = "—"
                    result_item = QTableWidgetItem(result_text)
            else:
                # Partido pendiente
                if row == 0:
                    result_text = "⚡ Candidato"
                else:
                    result_text = "◔"
                result_item = QTableWidgetItem(result_text)
                result_item.setForeground(QColor("#666"))
            
            result_item.setTextAlignment(Qt.AlignCenter)
            self.setItem(row, 8, result_item)
        
        self.resizeRowsToContents()


# =============================================================================
# WORKERS
# =============================================================================

class CalibrationWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, engine: AnticulebraEngine):
        super().__init__()
        self.engine = engine
    
    def run(self):
        try:
            self.progress.emit(10, "Cargando datos...")
            result = self.engine.calibrate()
            self.progress.emit(100, "¡Completado!")
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MLTrainingWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, engine: AnticulebraEngine):
        super().__init__()
        self.engine = engine
    
    def run(self):
        try:
            def callback(pct, msg):
                self.progress.emit(pct, msg)
            
            result = self.engine.train_ml_model(progress_callback=callback)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ValidationWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, engine: AnticulebraEngine, league_id: int,
                 start_date: date, end_date: date):
        super().__init__()
        self.engine = engine
        self.league_id = league_id
        self.start_date = start_date
        self.end_date = end_date
    
    def run(self):
        try:
            self.progress.emit(10, "Validando...")
            result = self.engine.validate_by_day(
                self.league_id, self.start_date, self.end_date
            )
            self.progress.emit(100, "¡Completado!")
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# =============================================================================
# PESTAÁ‘AS
# =============================================================================

class DashboardTab(QWidget):
    def __init__(self, engine: AnticulebraEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._build_ui()
        self._load_data()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        title = QLabel("▣ PANEL LEY DE LAS CULEBRAS v4 - ML")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #6B5B95;")
        layout.addWidget(title)
        
        # KPIs
        kpis = QHBoxLayout()
        
        self.kpi_calibration = KPICard("⚡", "Calibración", "--", Colors.SNAKE)
        kpis.addWidget(self.kpi_calibration)
        
        self.kpi_ml = KPICard("⚡", "ML AUC", "--", Colors.INFO)
        kpis.addWidget(self.kpi_ml)
        
        self.kpi_matches = KPICard("●", "Partidos", "--", Colors.SUCCESS)
        kpis.addWidget(self.kpi_matches)
        
        self.kpi_leagues = KPICard("⚡", "Ligas", "--", Colors.WARNING)
        kpis.addWidget(self.kpi_leagues)
        
        layout.addLayout(kpis)
        
        # Info
        splitter = QSplitter(Qt.Horizontal)
        
        # Ligas
        leagues_group = QGroupBox("⚡ Ligas Disponibles")
        leagues_layout = QVBoxLayout(leagues_group)
        
        self.leagues_table = QTableWidget()
        self.leagues_table.setColumnCount(4)
        self.leagues_table.setHorizontalHeaderLabels(["Liga", "Partidos", "Odds", "Cob"])
        self.leagues_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        leagues_layout.addWidget(self.leagues_table)
        
        splitter.addWidget(leagues_group)
        
        # Modelo
        model_group = QGroupBox("◉ Estado del Modelo")
        model_layout = QVBoxLayout(model_group)
        
        self.model_info = QTextEdit()
        self.model_info.setReadOnly(True)
        self.model_info.setMaximumHeight(200)
        model_layout.addWidget(self.model_info)
        
        btn = QPushButton("⚡ Actualizar")
        btn.setObjectName("primaryBtn")
        btn.clicked.connect(self._load_data)
        model_layout.addWidget(btn)
        
        splitter.addWidget(model_group)
        
        layout.addWidget(splitter)
    
    def _load_data(self):
        try:
            stats = self.engine.get_global_stats()
            
            if stats['model_calibrated']:
                self.kpi_calibration.set_value(f"{stats['calibration_correlation']*100:.0f}%", Colors.SUCCESS)
            else:
                self.kpi_calibration.set_value("✗", Colors.DANGER)
            
            if stats['ml_model_trained']:
                self.kpi_ml.set_value(f"{stats['ml_auc_roc']*100:.0f}%", Colors.SUCCESS)
            else:
                self.kpi_ml.set_value("✗", Colors.DANGER)
            
            self.kpi_matches.set_value(str(stats['total_fixtures_with_odds']))
            self.kpi_leagues.set_value(str(stats['total_leagues']))
            
            leagues = self.engine.get_available_leagues()
            self.leagues_table.setRowCount(len(leagues))
            
            for i, league in enumerate(leagues):
                self.leagues_table.setItem(i, 0, QTableWidgetItem(league['league_name'][:25]))
                self.leagues_table.setItem(i, 1, QTableWidgetItem(str(league['fixture_count'])))
                self.leagues_table.setItem(i, 2, QTableWidgetItem(str(league['fixtures_with_odds'])))
                
                cov = league['fixtures_with_odds'] / max(league['fixture_count'], 1) * 100
                self.leagues_table.setItem(i, 3, QTableWidgetItem(f"{cov:.0f}%"))
            
            ml_status = "✓ Entrenado" if stats['ml_model_trained'] else "✗ No entrenado"
            cal_status = "✓ Calibrado" if stats['model_calibrated'] else "✗ No calibrado"
            
            self.model_info.setHtml(f"""
                <h3>Estado</h3>
                <p>Calibración ICF: {cal_status}</p>
                <p>Modelo ML: {ml_status}</p>
                
                {'<h3>ML Info</h3><p>AUC-ROC: ' + f"{stats['ml_auc_roc']:.3f}" + '</p><p>Accuracy: ' + f"{stats['ml_accuracy']:.3f}" + '</p>' if stats['ml_model_trained'] else ''}
                
                <h3>Datos</h3>
                <p>Período: {stats['date_range']}</p>
            """)
            
        except Exception as e:
            logger.error(f"Error: {e}")


class DayAnalysisTab(QWidget):
    """Pestaña de análisis por día con tabla compacta."""
    
    def __init__(self, engine: AnticulebraEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.current_analysis: Optional[DayAnalysis] = None
        self._build_ui()
        self._load_leagues()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Título
        title = QLabel("⚡ ANÁLISIS POR DÍA (ML)")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #6B5B95;")
        layout.addWidget(title)
        
        # Filtros
        filters = QHBoxLayout()
        
        filters.addWidget(QLabel("Liga:"))
        self.combo_league = QComboBox()
        self.combo_league.setMinimumWidth(200)
        filters.addWidget(self.combo_league)
        
        filters.addWidget(QLabel("Fecha:"))
        self.date_edit = QDateEdit()
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        filters.addWidget(self.date_edit)
        
        filters.addStretch()
        
        self.btn_analyze = QPushButton("⚡ Analizar")
        self.btn_analyze.setObjectName("primaryBtn")
        self.btn_analyze.clicked.connect(self._analyze_day)
        filters.addWidget(self.btn_analyze)
        
        layout.addLayout(filters)
        
        # Splitter principal (vertical) - Resumen arriba, Tabla abajo
        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.setHandleWidth(8)
        
        # Panel superior: Resumen + Candidato
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # Splitter horizontal para resumen y candidato
        top_splitter = QSplitter(Qt.Horizontal)
        
        # Resumen
        summary_group = QGroupBox("▣ Resumen del Día")
        summary_layout = QVBoxLayout(summary_group)
        
        self.lbl_stats = QLabel("Partidos: -- | Favoritos: --")
        summary_layout.addWidget(self.lbl_stats)
        
        self.breakdown_bar = BreakdownBar()
        summary_layout.addWidget(self.breakdown_bar)
        
        pred_layout = QHBoxLayout()
        self.lbl_prediction = QLabel("Predicción: --")
        self.lbl_prediction.setStyleSheet("font-weight: bold;")
        pred_layout.addWidget(self.lbl_prediction)
        pred_layout.addStretch()
        self.lbl_result = QLabel("")
        pred_layout.addWidget(self.lbl_result)
        summary_layout.addLayout(pred_layout)
        
        top_splitter.addWidget(summary_group)
        
        # Candidato
        self.candidate_panel = CandidatePanel()
        top_splitter.addWidget(self.candidate_panel)
        
        top_splitter.setSizes([300, 400])
        top_layout.addWidget(top_splitter)
        
        main_splitter.addWidget(top_widget)
        
        # Panel inferior: Tabla de partidos
        table_group = QGroupBox("● Partidos (ordenados por Score ML)")
        table_layout = QVBoxLayout(table_group)
        
        self.matches_table = MatchesTable()
        table_layout.addWidget(self.matches_table)
        
        main_splitter.addWidget(table_group)
        
        # Proporciones del splitter
        main_splitter.setSizes([200, 400])
        
        layout.addWidget(main_splitter, 1)
    
    def _load_leagues(self):
        try:
            leagues = self.engine.get_available_leagues()
            self.combo_league.clear()
            for league in leagues:
                self.combo_league.addItem(league['league_name'], league['league_id'])
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def _analyze_day(self):
        league_id = self.combo_league.currentData()
        if not league_id:
            return
        
        target_date = self.date_edit.date().toPython()
        
        try:
            self.btn_analyze.setEnabled(False)
            QApplication.processEvents()
            
            analysis = self.engine.analyze_day(league_id, target_date)
            self.current_analysis = analysis
            self._update_ui(analysis)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
        finally:
            self.btn_analyze.setEnabled(True)
    
    def _update_ui(self, analysis: DayAnalysis):
        # Stats
        self.lbl_stats.setText(f"Partidos: {analysis.total_matches} | Favoritos: {analysis.matches_with_favorite}")
        
        # Breakdown
        self.breakdown_bar.update_values(analysis.prob_break_by_draw, analysis.prob_break_by_underdog)
        
        # Predicción
        if analysis.predicted_break:
            type_txt = "═ empate" if analysis.predicted_break_type == "draw" else "✖ underdog"
            self.lbl_prediction.setText(f"SE ROMPE por {type_txt} ({analysis.prob_break_total*100:.0f}%)")
            self.lbl_prediction.setStyleSheet(f"font-weight: bold; color: {Colors.DANGER};")
        else:
            self.lbl_prediction.setText(f"NO se rompe ({analysis.prob_break_total*100:.0f}%)")
            self.lbl_prediction.setStyleSheet(f"font-weight: bold; color: {Colors.SUCCESS};")
        
        # Resultado
        if analysis.snake_broke is not None:
            if analysis.snake_broke:
                emoji = get_break_type_emoji(analysis.break_type)
                self.lbl_result.setText(f"🗲 ROTA {emoji} en #{analysis.break_match_position}")
                self.lbl_result.setStyleSheet(f"font-weight: bold; color: {Colors.DANGER};")
            else:
                self.lbl_result.setText("✓ Culebra OK")
                self.lbl_result.setStyleSheet(f"font-weight: bold; color: {Colors.SUCCESS};")
        else:
            self.lbl_result.setText("")
        
        # Candidato
        self.candidate_panel.update_candidate(analysis)
        
        # Tabla
        self.matches_table.populate(analysis)


class JornadaAnalysisTab(QWidget):
    def __init__(self, engine: AnticulebraEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._build_ui()
        self._load_leagues()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        title = QLabel("⚡ ANÁLISIS POR JORNADA")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #6B5B95;")
        layout.addWidget(title)
        
        # Filtros
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Liga:"))
        self.combo_league = QComboBox()
        self.combo_league.setMinimumWidth(200)
        filters.addWidget(self.combo_league)
        
        filters.addWidget(QLabel("Desde:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addDays(-7))
        self.date_from.setCalendarPopup(True)
        filters.addWidget(self.date_from)
        
        filters.addWidget(QLabel("Hasta:"))
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        filters.addWidget(self.date_to)
        
        filters.addStretch()
        
        self.btn_analyze = QPushButton("⚡ Analizar Jornada")
        self.btn_analyze.setObjectName("primaryBtn")
        self.btn_analyze.clicked.connect(self._analyze)
        filters.addWidget(self.btn_analyze)
        
        layout.addLayout(filters)
        
        # Splitter principal
        main_splitter = QSplitter(Qt.Vertical)
        
        # Resumen de la jornada
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame {
                background-color: #6B5B95;
                border-radius: 10px;
                padding: 15px;
            }
        """)
        summary_layout = QVBoxLayout(summary_frame)
        
        self.lbl_jornada_title = QLabel("⚡ Selecciona una jornada para analizar")
        self.lbl_jornada_title.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
        summary_layout.addWidget(self.lbl_jornada_title)
        
        self.lbl_jornada_stats = QLabel("")
        self.lbl_jornada_stats.setStyleSheet("color: white; font-size: 13px;")
        summary_layout.addWidget(self.lbl_jornada_stats)
        
        # KPIs de la jornada
        kpis_layout = QHBoxLayout()
        
        self.kpi_dias = QLabel("")
        self.kpi_dias.setStyleSheet("color: white; background: rgba(255,255,255,0.2); padding: 8px; border-radius: 5px;")
        kpis_layout.addWidget(self.kpi_dias)
        
        self.kpi_partidos = QLabel("")
        self.kpi_partidos.setStyleSheet("color: white; background: rgba(255,255,255,0.2); padding: 8px; border-radius: 5px;")
        kpis_layout.addWidget(self.kpi_partidos)
        
        self.kpi_ruptura = QLabel("")
        self.kpi_ruptura.setStyleSheet("color: white; background: rgba(255,255,255,0.2); padding: 8px; border-radius: 5px;")
        kpis_layout.addWidget(self.kpi_ruptura)
        
        self.kpi_resultado = QLabel("")
        self.kpi_resultado.setStyleSheet("color: white; background: rgba(255,255,255,0.2); padding: 8px; border-radius: 5px; font-weight: bold;")
        kpis_layout.addWidget(self.kpi_resultado)
        
        kpis_layout.addStretch()
        summary_layout.addLayout(kpis_layout)
        
        main_splitter.addWidget(summary_frame)
        
        # Contenido de días
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setSpacing(15)
        
        scroll.setWidget(self.content)
        main_splitter.addWidget(scroll)
        
        main_splitter.setSizes([150, 500])
        layout.addWidget(main_splitter, 1)
    
    def _load_leagues(self):
        try:
            leagues = self.engine.get_available_leagues()
            self.combo_league.clear()
            for league in leagues:
                self.combo_league.addItem(league['league_name'], league['league_id'])
        except:
            pass
    
    def _analyze(self):
        league_id = self.combo_league.currentData()
        if not league_id:
            return
        
        try:
            self.btn_analyze.setEnabled(False)
            self.btn_analyze.setText("◔ Analizando...")
            QApplication.processEvents()
            
            jornada = self.engine.analyze_jornada(
                league_id,
                self.date_from.date().toPython(),
                self.date_to.date().toPython()
            )
            self._update_ui(jornada)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
        finally:
            self.btn_analyze.setEnabled(True)
            self.btn_analyze.setText("⚡ Analizar Jornada")
    
    def _update_ui(self, jornada: JornadaAnalysis):
        # Limpiar contenido
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not jornada.days:
            self.lbl_jornada_title.setText("⚡ No hay partidos en este período")
            self.lbl_jornada_stats.setText("")
            self.kpi_dias.setText("")
            self.kpi_partidos.setText("")
            self.kpi_ruptura.setText("")
            self.kpi_resultado.setText("")
            return
        
        # Resumen
        self.lbl_jornada_title.setText(f"⚡ JORNADA - {jornada.league_name}")
        self.lbl_jornada_stats.setText(f"Del {jornada.date_start.strftime('%d/%m')} al {jornada.date_end.strftime('%d/%m/%Y')}")
        
        # KPIs
        self.kpi_dias.setText(f"⚡ {jornada.total_days} días")
        self.kpi_partidos.setText(f"● {jornada.total_matches} partidos")
        self.kpi_ruptura.setText(f"⚡ Prob. Ruptura: {jornada.weekly_prob_break*100:.0f}%")
        
        if jornada.snake_broke is True:
            emoji = get_break_type_emoji(jornada.break_type)
            self.kpi_resultado.setText(f"🗲 ROTA {emoji} el {jornada.break_day.strftime('%d/%m')}")
            self.kpi_resultado.setStyleSheet("color: #721C24; background: #F8D7DA; padding: 8px; border-radius: 5px; font-weight: bold;")
        elif jornada.snake_broke is False:
            self.kpi_resultado.setText("✓ Culebra COMPLETA")
            self.kpi_resultado.setStyleSheet("color: #155724; background: #D4EDDA; padding: 8px; border-radius: 5px; font-weight: bold;")
        else:
            self.kpi_resultado.setText("◔ En curso")
            self.kpi_resultado.setStyleSheet("color: white; background: rgba(255,255,255,0.2); padding: 8px; border-radius: 5px;")
        
        # Días
        for day in jornada.days:
            day_widget = self._create_day_widget(day)
            self.content_layout.addWidget(day_widget)
        
        self.content_layout.addStretch()
    
    def _create_day_widget(self, day: DayAnalysis) -> QWidget:
        """Crea widget compacto para un día de la jornada."""
        frame = QFrame()
        
        # Color según resultado
        if day.snake_broke is True:
            border_color = Colors.DANGER
            bg_color = "#FFF5F5"
        elif day.snake_broke is False:
            border_color = Colors.SUCCESS
            bg_color = "#F5FFF5"
        else:
            border_color = "#CED4DA"
            bg_color = "white"
        
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        
        layout = QVBoxLayout(frame)
        layout.setSpacing(4)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Header del día (compacto)
        header = QHBoxLayout()
        
        day_name = day.date.strftime('%a %d/%m').capitalize()
        day_label = QLabel(f"⚡ {day_name}")
        day_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #6B5B95;")
        header.addWidget(day_label)
        
        stats_label = QLabel(f"●{day.total_matches} ⚡")
        stats_label.setStyleSheet("color: #666; font-size: 11px;")
        header.addWidget(stats_label)
        
        header.addStretch()
        
        # Resultado del día
        if day.snake_broke is True:
            emoji = get_break_type_emoji(day.break_type)
            result_label = QLabel(f"⚡ {emoji} #{day.break_match_position}")
            result_label.setStyleSheet(f"color: {Colors.DANGER}; font-weight: bold; font-size: 12px;")
        elif day.snake_broke is False:
            result_label = QLabel("✓")
            result_label.setStyleSheet(f"color: {Colors.SUCCESS}; font-weight: bold;")
        else:
            result_label = QLabel("◔")
            result_label.setStyleSheet("color: #666;")
        
        header.addWidget(result_label)
        layout.addLayout(header)
        
        # Lista compacta de partidos (sin tabla con headers)
        matches_widget = self._create_compact_matches_list(day)
        layout.addWidget(matches_widget)
        
        return frame
    
    def _create_compact_matches_list(self, day: DayAnalysis) -> QWidget:
        """Crea lista compacta de partidos sin headers de tabla."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(2)
        layout.setContentsMargins(0, 4, 0, 0)
        
        if not day.matches_ranked_by_ml:
            return container
        
        for rank, (pos, match, ml_score) in enumerate(day.matches_ranked_by_ml):
            row = QFrame()
            row.setStyleSheet("""
                QFrame {
                    background-color: white;
                    border: 1px solid #E0E0E0;
                    border-radius: 4px;
                    padding: 4px;
                }
                QFrame:hover {
                    background-color: #F8F9FA;
                }
            """)
            
            row_layout = QHBoxLayout(row)
            row_layout.setSpacing(8)
            row_layout.setContentsMargins(6, 3, 6, 3)
            
            # Rank (medalla o número)
            if rank == 0:
                rank_text = "⚡"
            elif rank == 1:
                rank_text = "⚡"
            elif rank == 2:
                rank_text = "⚡"
            else:
                rank_text = f"#{rank+1}"
            
            rank_label = QLabel(rank_text)
            rank_label.setFixedWidth(28)
            rank_label.setStyleSheet("font-size: 12px;")
            row_layout.addWidget(rank_label)
            
            # Hora
            time_str = match.date.strftime("%H:%M") if match.date else "--:--"
            time_label = QLabel(time_str)
            time_label.setFixedWidth(40)
            time_label.setStyleSheet("color: #666; font-size: 11px;")
            row_layout.addWidget(time_label)
            
            # Partido
            match_text = f"{match.home_team_name[:12]} vs {match.away_team_name[:12]}"
            match_label = QLabel(match_text)
            match_label.setStyleSheet("font-size: 11px;")
            row_layout.addWidget(match_label, 1)
            
            # Score (si ya terminó)
            if match.goals_home is not None:
                score_text = f"{match.goals_home}-{match.goals_away}"
                score_label = QLabel(score_text)
                score_label.setFixedWidth(35)
                score_label.setAlignment(Qt.AlignCenter)
                
                if match.outcome == "X":
                    score_label.setStyleSheet("background: #E2D5F1; border-radius: 3px; font-weight: bold; font-size: 11px; padding: 2px;")
                elif match.outcome == "1":
                    score_label.setStyleSheet("background: #D4EDDA; border-radius: 3px; font-weight: bold; font-size: 11px; padding: 2px;")
                else:
                    score_label.setStyleSheet("background: #CFE2FF; border-radius: 3px; font-weight: bold; font-size: 11px; padding: 2px;")
            else:
                score_label = QLabel("--")
                score_label.setFixedWidth(35)
                score_label.setAlignment(Qt.AlignCenter)
                score_label.setStyleSheet("color: #999; font-size: 11px;")
            row_layout.addWidget(score_label)
            
            # Probabilidades compactas
            probs_text = f"{match.prob_home*100:.0f}/{match.prob_draw*100:.0f}/{match.prob_away*100:.0f}"
            probs_label = QLabel(probs_text)
            probs_label.setFixedWidth(55)
            probs_label.setStyleSheet("color: #666; font-size: 10px;")
            probs_label.setToolTip(f"1: {match.prob_home*100:.0f}% | X: {match.prob_draw*100:.0f}% | 2: {match.prob_away*100:.0f}%")
            row_layout.addWidget(probs_label)
            
            # Predicción compacta
            if match.favorite == "home":
                pred_text = f"⚡ {match.favorite_prob*100:.0f}%"
            elif match.favorite == "away":
                pred_text = f"◉{match.favorite_prob*100:.0f}%"
            else:
                pred_text = "≡"
            
            pred_label = QLabel(pred_text)
            pred_label.setFixedWidth(45)
            pred_label.setStyleSheet("font-size: 10px;")
            row_layout.addWidget(pred_label)
            
            # ML Score con indicador de tipo
            ml_type_char = ""
            if match.ml_break_type_pred == "draw":
                ml_type_char = "E"
            elif match.ml_break_type_pred == "underdog":
                ml_type_char = "U"
            
            ml_text = f"{ml_score:.2f}" if not ml_type_char else f"{ml_score:.2f}{ml_type_char}"
            ml_label = QLabel(ml_text)
            ml_label.setFixedWidth(45)
            ml_label.setAlignment(Qt.AlignCenter)
            if ml_score >= 0.6:
                ml_label.setStyleSheet("background: #F8D7DA; border-radius: 3px; font-size: 10px; padding: 2px;")
            elif ml_score >= 0.4:
                ml_label.setStyleSheet("background: #FFF3CD; border-radius: 3px; font-size: 10px; padding: 2px;")
            else:
                ml_label.setStyleSheet("font-size: 10px; color: #666;")
            row_layout.addWidget(ml_label)
            
            # Resultado
            if match.outcome is not None:
                if match.favorite == "none":
                    result_text = "—"
                elif match.favorite_won:
                    result_text = "✓"
                else:
                    result_text = "✗"
            else:
                result_text = "⚡" if rank == 0 else "◔"
            
            result_label = QLabel(result_text)
            result_label.setFixedWidth(25)
            result_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(result_label)
            
            # Highlight candidato
            if rank == 0:
                row.setStyleSheet("""
                    QFrame {
                        background-color: #FFF3CD;
                        border: 2px solid #FF6B35;
                        border-radius: 4px;
                        padding: 4px;
                    }
                """)
            
            # Highlight si rompió
            if match.broke_snake:
                row.setStyleSheet("""
                    QFrame {
                        background-color: #F8D7DA;
                        border: 2px solid #DC3545;
                        border-radius: 4px;
                        padding: 4px;
                    }
                """)
            
            layout.addWidget(row)
        
        return container


class RetroactiveTab(QWidget):
    def __init__(self, engine: AnticulebraEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.worker = None
        self._build_ui()
        self._load_leagues()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        title = QLabel("⚡ VALIDACIÁ“N RETROACTIVA")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #6B5B95;")
        layout.addWidget(title)
        
        # Explicación
        explanation = QLabel(
            "▣ Valida el modelo con datos históricos: ¿Predijo bien las rupturas? ¿Cumplió el candidato?"
        )
        explanation.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        
        # Filtros
        filters = QHBoxLayout()
        
        filters.addWidget(QLabel("Liga:"))
        self.combo_league = QComboBox()
        self.combo_league.setMinimumWidth(200)
        filters.addWidget(self.combo_league)
        
        filters.addWidget(QLabel("Desde:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addMonths(-3))
        self.date_from.setCalendarPopup(True)
        filters.addWidget(self.date_from)
        
        filters.addWidget(QLabel("Hasta:"))
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        filters.addWidget(self.date_to)
        
        filters.addStretch()
        
        self.btn_validate = QPushButton("▣ Validar")
        self.btn_validate.setObjectName("primaryBtn")
        self.btn_validate.clicked.connect(self._run)
        filters.addWidget(self.btn_validate)
        
        layout.addLayout(filters)
        
        # KPIs con nombres claros
        kpis_group = QGroupBox("⚡ Resultados de Validación")
        kpis_layout = QGridLayout(kpis_group)
        
        # Fila 1: Datos generales
        kpis_layout.addWidget(QLabel("⚡ Días analizados:"), 0, 0)
        self.kpi_total = QLabel("--")
        self.kpi_total.setStyleSheet("font-weight: bold; font-size: 16px;")
        kpis_layout.addWidget(self.kpi_total, 0, 1)
        
        kpis_layout.addWidget(QLabel("⚡ Días con ruptura:"), 0, 2)
        self.kpi_broken = QLabel("--")
        self.kpi_broken.setStyleSheet("font-weight: bold; font-size: 16px; color: #DC3545;")
        kpis_layout.addWidget(self.kpi_broken, 0, 3)
        
        # Fila 2: Tipo de ruptura
        kpis_layout.addWidget(QLabel("⚡ Rotas por EMPATE:"), 1, 0)
        self.kpi_draw = QLabel("--")
        self.kpi_draw.setStyleSheet("font-weight: bold; font-size: 16px; color: #9B59B6;")
        kpis_layout.addWidget(self.kpi_draw, 1, 1)
        
        kpis_layout.addWidget(QLabel("⚡ Rotas por UNDERDOG:"), 1, 2)
        self.kpi_under = QLabel("--")
        self.kpi_under.setStyleSheet("font-weight: bold; font-size: 16px; color: #E74C3C;")
        kpis_layout.addWidget(self.kpi_under, 1, 3)
        
        # Separador
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #E0E0E0;")
        kpis_layout.addWidget(separator, 2, 0, 1, 4)
        
        # Fila 3: Métricas de precisión con explicación
        lbl1 = QLabel("⚡ ¿Predijo si se rompe?")
        lbl1.setToolTip("¿El modelo predijo correctamente SI habría ruptura o NO?")
        kpis_layout.addWidget(lbl1, 3, 0)
        self.kpi_accuracy = QLabel("--")
        self.kpi_accuracy.setStyleSheet("font-weight: bold; font-size: 20px;")
        kpis_layout.addWidget(self.kpi_accuracy, 3, 1)
        
        lbl2 = QLabel("► ¿Cumplió el candidato?")
        lbl2.setToolTip("De los días con ruptura, ¿el partido #1 del ranking ML fue el que rompió?")
        kpis_layout.addWidget(lbl2, 3, 2)
        self.kpi_ml_acc = QLabel("--")
        self.kpi_ml_acc.setStyleSheet("font-weight: bold; font-size: 20px;")
        kpis_layout.addWidget(self.kpi_ml_acc, 3, 3)
        
        layout.addWidget(kpis_group)
        
        # Explicación de métricas
        metrics_explanation = QFrame()
        metrics_explanation.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; padding: 10px;")
        me_layout = QVBoxLayout(metrics_explanation)
        
        me_title = QLabel("⚡ ¿Qué significan estas métricas?")
        me_title.setStyleSheet("font-weight: bold; color: #6B5B95;")
        me_layout.addWidget(me_title)
        
        me_text = QLabel(
            "• <b>¿Predijo si se rompe?</b> → El modelo dice \"hoy SE ROMPE\" o \"NO se rompe\". "
            "Esta métrica mide cuántas veces acertó esa predicción.\n\n"
            "• <b>¿Cumplió el candidato?</b> → De los días que SÍ se rompieron, ¿el partido #1 del ranking "
            "(el candidato ML) fue realmente el que rompió la culebra?\n\n"
            "⚡ Random sería ~15% (1 de 7 partidos), así que 35-40% indica que el modelo funciona."
        )
        me_text.setWordWrap(True)
        me_text.setStyleSheet("color: #666; font-size: 11px;")
        me_layout.addWidget(me_text)
        
        layout.addWidget(metrics_explanation)
        
        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        layout.addStretch()
    
    def _load_leagues(self):
        try:
            leagues = self.engine.get_available_leagues()
            self.combo_league.clear()
            for league in leagues:
                self.combo_league.addItem(league['league_name'], league['league_id'])
        except:
            pass
    
    def _run(self):
        league_id = self.combo_league.currentData()
        if not league_id:
            return
        
        self.btn_validate.setEnabled(False)
        self.btn_validate.setText("◔ Validando...")
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        
        self.worker = ValidationWorker(
            self.engine, league_id,
            self.date_from.date().toPython(),
            self.date_to.date().toPython()
        )
        self.worker.progress.connect(lambda p, m: None)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()
    
    def _on_finished(self, metrics: ValidationMetrics):
        self.btn_validate.setEnabled(True)
        self.btn_validate.setText("▣ Validar")
        self.progress.setVisible(False)
        
        # Datos generales
        self.kpi_total.setText(str(metrics.total_days))
        self.kpi_broken.setText(f"{metrics.days_snake_broken} ({metrics.days_snake_broken/max(metrics.total_days,1)*100:.0f}%)")
        
        # Tipo de ruptura
        self.kpi_draw.setText(str(metrics.breaks_by_draw))
        self.kpi_under.setText(str(metrics.breaks_by_underdog))
        
        # Precisión de ruptura
        if metrics.total_days > 0:
            acc = metrics.correct_break_predictions / metrics.total_days * 100
            self.kpi_accuracy.setText(f"{acc:.0f}%")
            if acc >= 70:
                self.kpi_accuracy.setStyleSheet("font-weight: bold; font-size: 20px; color: #28A745;")
            elif acc >= 50:
                self.kpi_accuracy.setStyleSheet("font-weight: bold; font-size: 20px; color: #FFC107;")
            else:
                self.kpi_accuracy.setStyleSheet("font-weight: bold; font-size: 20px; color: #DC3545;")
        
        # Precisión del candidato ML
        if metrics.days_snake_broken > 0:
            ml_acc = metrics.correct_candidate_predictions / metrics.days_snake_broken * 100
            self.kpi_ml_acc.setText(f"{ml_acc:.0f}%")
            if ml_acc >= 35:
                self.kpi_ml_acc.setStyleSheet("font-weight: bold; font-size: 20px; color: #28A745;")
            elif ml_acc >= 20:
                self.kpi_ml_acc.setStyleSheet("font-weight: bold; font-size: 20px; color: #FFC107;")
            else:
                self.kpi_ml_acc.setStyleSheet("font-weight: bold; font-size: 20px; color: #DC3545;")
        else:
            self.kpi_ml_acc.setText("N/A")
    
    def _on_error(self, error: str):
        self.btn_validate.setEnabled(True)
        self.btn_validate.setText("▣ Validar")
        self.progress.setVisible(False)
        QMessageBox.critical(self, "Error", error)


class CalibrationTab(QWidget):
    def __init__(self, engine: AnticulebraEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.cal_worker = None
        self.ml_worker = None
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        title = QLabel("◉ CALIBRACIÁ“N Y ENTRENAMIENTO ML")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #6B5B95;")
        layout.addWidget(title)
        
        # Botones principales
        btns = QHBoxLayout()
        
        self.btn_calibrate = QPushButton("⚡ Calibrar ICF")
        self.btn_calibrate.setObjectName("primaryBtn")
        self.btn_calibrate.setMinimumHeight(50)
        self.btn_calibrate.clicked.connect(self._calibrate)
        btns.addWidget(self.btn_calibrate)
        
        self.btn_train_ml = QPushButton("⚡ Entrenar ML")
        self.btn_train_ml.setObjectName("mlBtn")
        self.btn_train_ml.setMinimumHeight(50)
        self.btn_train_ml.clicked.connect(self._train_ml)
        btns.addWidget(self.btn_train_ml)
        
        layout.addLayout(btns)
        
        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        
        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(200)
        self.log.setStyleSheet("font-family: monospace;")
        layout.addWidget(self.log)
        
        # Info del modelo ML
        ml_group = QGroupBox("⚡ Modelo ML")
        ml_layout = QVBoxLayout(ml_group)
        
        self.ml_info = QLabel("No entrenado")
        self.ml_info.setWordWrap(True)
        ml_layout.addWidget(self.ml_info)
        
        layout.addWidget(ml_group)
        
        layout.addStretch()
        
        self._update_info()
    
    def _update_info(self):
        stats = self.engine.get_global_stats()
        
        if stats['ml_model_trained']:
            imp = stats.get('ml_feature_importances', {})
            top3 = list(imp.items())[:3]
            imp_text = ", ".join([f"{k}: {v:.2f}" for k, v in top3])
            
            self.ml_info.setText(
                f"✓ Entrenado\n"
                f"AUC-ROC: {stats['ml_auc_roc']:.3f}\n"
                f"Accuracy: {stats['ml_accuracy']:.3f}\n"
                f"Top features: {imp_text}"
            )
        else:
            self.ml_info.setText("✗ No entrenado - Click 'Entrenar ML'")
    
    def _calibrate(self):
        self.btn_calibrate.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.log.append("⚡ Iniciando calibración ICF...")
        
        self.cal_worker = CalibrationWorker(self.engine)
        self.cal_worker.progress.connect(lambda p, m: self.log.append(m))
        self.cal_worker.finished.connect(self._on_cal_finished)
        self.cal_worker.error.connect(self._on_error)
        self.cal_worker.start()
    
    def _on_cal_finished(self, result: CalibrationResult):
        self.btn_calibrate.setEnabled(True)
        self.progress.setVisible(False)
        
        self.log.append(f"✓ Calibración completada")
        self.log.append(f"   MAE: {result.mae:.4f}")
        self.log.append(f"   Correlación: {result.correlation:.4f}")
        self.log.append(f"   Muestras: {result.n_samples}")
        
        self._update_info()
    
    def _train_ml(self):
        reply = QMessageBox.question(
            self, "Confirmar",
            "¿Entrenar modelo ML?\nEsto puede tomar varios minutos.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self.btn_train_ml.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.log.append("⚡ Iniciando entrenamiento ML...")
        
        self.ml_worker = MLTrainingWorker(self.engine)
        self.ml_worker.progress.connect(self._on_ml_progress)
        self.ml_worker.finished.connect(self._on_ml_finished)
        self.ml_worker.error.connect(self._on_error)
        self.ml_worker.start()
    
    def _on_ml_progress(self, pct: int, msg: str):
        self.progress.setValue(pct)
        self.log.append(f"[{pct}%] {msg}")
    
    def _on_ml_finished(self, result: MLTrainingResult):
        self.btn_train_ml.setEnabled(True)
        self.progress.setVisible(False)
        
        self.log.append(f"\n✓ Entrenamiento ML completado")
        self.log.append(f"   AUC-ROC: {result.auc_roc:.3f}")
        self.log.append(f"   Accuracy: {result.accuracy:.3f}")
        self.log.append(f"   Muestras: {result.n_samples}")
        self.log.append(f"   Rupturas: {result.n_breaks}")
        
        self._update_info()
        
        QMessageBox.information(
            self, "Éxito",
            f"✓ Modelo ML entrenado\n\n"
            f"AUC-ROC: {result.auc_roc:.3f}\n"
            f"Accuracy: {result.accuracy:.3f}"
        )
    
    def _on_error(self, error: str):
        self.btn_calibrate.setEnabled(True)
        self.btn_train_ml.setEnabled(True)
        self.progress.setVisible(False)
        self.log.append(f"✗ Error: {error}")
        QMessageBox.critical(self, "Error", error)


# =============================================================================
# VENTANA PRINCIPAL
# =============================================================================

class AnticulebraWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = AnticulebraEngine()
        self._build_ui()
    
    def _build_ui(self):
        self.setWindowTitle("🗲 LEY DE LAS CULEBRAS v4 - Machine Learning")
        self.resize(1400, 900)
        self.setStyleSheet(STYLESHEET)
        
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header
        header = QHBoxLayout()
        title = QLabel("🗲 LEY DE LAS CULEBRAS v4")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #6B5B95;")
        header.addWidget(title)
        header.addStretch()
        
        ml_badge = QLabel("⚡ ML")
        ml_badge.setStyleSheet("background-color: #17A2B8; color: white; padding: 5px 10px; border-radius: 4px;")
        header.addWidget(ml_badge)
        
        layout.addLayout(header)
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        
        self.tabs.addTab(DashboardTab(self.engine), "⚡ Panel")
        self.tabs.addTab(DayAnalysisTab(self.engine), "⚡ Por Día")
        self.tabs.addTab(JornadaAnalysisTab(self.engine), "⚡ Jornada")
        self.tabs.addTab(RetroactiveTab(self.engine), "▣ Validación")
        self.tabs.addTab(CalibrationTab(self.engine), "◉ ML Training")
        
        layout.addWidget(self.tabs)


def main():
    import sys
    app = QApplication(sys.argv)
    window = AnticulebraWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()