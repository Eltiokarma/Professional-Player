#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
k_scoreline_window.py

VENTANA DE MARCADORES POR CONSTANTES K
=======================================

UI para el motor de predicción de marcadores basado en dinámica de K.

Características:
- Selector de equipos local/visitante con búsqueda
- Nivel de rival ajustable
- Visualización de distribuciones de goles (barras)
- Matriz de marcador heatmap
- Probabilidades derivadas (1X2, O/U, BTTS)
- Detalle de scores por variable K

Autor: Gerson (desarrollado con Claude)
Fecha: Marzo 2026
"""

import os
import sys
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QGroupBox, QFrame, QScrollArea,
    QDoubleSpinBox, QSpinBox, QSplitter, QApplication, QCompleter,
    QSizePolicy, QToolTip, QMessageBox, QProgressBar
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QStringListModel, QSize
from PySide6.QtGui import (
    QFont, QColor, QPainter, QLinearGradient, QPen, QBrush,
    QPaintEvent, QMouseEvent, QFontMetrics, QPalette, QPixmap
)

logger = logging.getLogger(__name__)


# ============================================================================
# PALETA DE COLORES
# ============================================================================

class Colors:
    BG_DARK = "#0D1117"
    BG_PANEL = "#161B22"
    BG_CARD = "#1C2333"
    BG_INPUT = "#21262D"
    BORDER = "#30363D"
    TEXT = "#E6EDF3"
    TEXT_DIM = "#8B949E"
    TEXT_MUTED = "#484F58"
    
    # Acentos
    GREEN = "#3FB950"
    GREEN_DIM = "#238636"
    RED = "#F85149"
    RED_DIM = "#DA3633"
    BLUE = "#58A6FF"
    BLUE_DIM = "#1F6FEB"
    ORANGE = "#D29922"
    PURPLE = "#BC8CFF"
    CYAN = "#39D2C0"
    YELLOW = "#F0C000"
    
    # Heatmap (frío a caliente)
    HEATMAP = [
        "#0D1117", "#132034", "#1A3050", "#1F406D",  
        "#1F6FEB", "#58A6FF", "#39D2C0", "#3FB950",  
        "#D29922", "#F0C000", "#F85149", "#FF6E76",  
    ]


# ============================================================================
# WIDGETS PERSONALIZADOS
# ============================================================================

class DistributionBarWidget(QWidget):
    """Widget que dibuja barras de distribución de goles."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = np.zeros(6)
        self.labels = ["0", "1", "2", "3", "4", "5"]
        self.title = ""
        self.color = Colors.BLUE
        self.setMinimumHeight(140)
        self.setMinimumWidth(200)
    
    def set_data(self, values: np.ndarray, title: str = "", color: str = None):
        self.values = values
        self.title = title
        if color:
            self.color = color
        self.update()
    
    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        w, h = self.width(), self.height()
        margin_top = 28 if self.title else 8
        margin_bottom = 24
        margin_lr = 12
        bar_area_h = h - margin_top - margin_bottom
        bar_area_w = w - 2 * margin_lr
        
        # Fondo
        p.fillRect(self.rect(), QColor(Colors.BG_CARD))
        
        # Título
        if self.title:
            p.setPen(QColor(Colors.TEXT_DIM))
            font = QFont("Segoe UI", 9, QFont.Bold)
            p.setFont(font)
            p.drawText(margin_lr, 18, self.title)
        
        n = len(self.values)
        if n == 0 or np.sum(self.values) == 0:
            p.setPen(QColor(Colors.TEXT_MUTED))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(self.rect(), Qt.AlignCenter, "Sin datos")
            p.end()
            return
        
        max_val = max(np.max(self.values), 0.01)
        bar_width = bar_area_w / n * 0.65
        gap = bar_area_w / n
        
        color_base = QColor(self.color)
        
        for i, val in enumerate(self.values):
            x = margin_lr + i * gap + (gap - bar_width) / 2
            bar_h = (val / max_val) * bar_area_h * 0.85
            y = margin_top + bar_area_h - bar_h
            
            # Gradiente vertical
            gradient = QLinearGradient(x, y, x, margin_top + bar_area_h)
            gradient.setColorAt(0, color_base)
            c_dark = QColor(color_base)
            c_dark.setAlpha(120)
            gradient.setColorAt(1, c_dark)
            
            p.setBrush(QBrush(gradient))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(int(x), int(y), int(bar_width), int(bar_h), 3, 3)
            
            # Valor encima de la barra
            p.setPen(QColor(Colors.TEXT))
            font = QFont("Segoe UI", 8, QFont.Bold)
            p.setFont(font)
            text = f"{val:.0%}" if val >= 0.01 else "<1%"
            fm = QFontMetrics(font)
            tw = fm.horizontalAdvance(text)
            p.drawText(int(x + bar_width / 2 - tw / 2), int(y - 4), text)
            
            # Label debajo
            p.setPen(QColor(Colors.TEXT_DIM))
            p.setFont(QFont("Segoe UI", 9))
            label = self.labels[i] if i < len(self.labels) else str(i)
            lw = fm.horizontalAdvance(label)
            p.drawText(int(x + bar_width / 2 - lw / 2), h - 6, label)
        
        p.end()


class HeatmapWidget(QWidget):
    """Widget que dibuja la matriz de marcador como heatmap."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.matrix = np.zeros((6, 6))
        self.home_name = "Local"
        self.away_name = "Visita"
        self.setMinimumHeight(300)
        self.setMinimumWidth(300)
        self.setMouseTracking(True)
        self._hover_cell = (-1, -1)
    
    def set_data(self, matrix: np.ndarray, home_name: str = "", away_name: str = ""):
        self.matrix = matrix
        if home_name:
            self.home_name = home_name
        if away_name:
            self.away_name = away_name
        self.update()
    
    def _get_heatmap_color(self, value: float, vmin: float, vmax: float) -> QColor:
        if vmax == vmin:
            return QColor(Colors.BG_CARD)
        
        ratio = (value - vmin) / (vmax - vmin)
        ratio = max(0.0, min(1.0, ratio))
        
        # Interpolación entre colores del heatmap
        colors = Colors.HEATMAP
        idx = ratio * (len(colors) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(colors) - 1)
        frac = idx - lo
        
        c1 = QColor(colors[lo])
        c2 = QColor(colors[hi])
        
        r = int(c1.red() * (1 - frac) + c2.red() * frac)
        g = int(c1.green() * (1 - frac) + c2.green() * frac)
        b = int(c1.blue() * (1 - frac) + c2.blue() * frac)
        
        return QColor(r, g, b)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        # Calcular celda bajo el cursor
        w, h = self.width(), self.height()
        margin = 50
        rows, cols = self.matrix.shape
        cell_w = (w - margin - 10) / cols
        cell_h = (h - margin - 10) / rows
        
        mx, my = event.position().x(), event.position().y()
        col = int((mx - margin) / cell_w) if mx >= margin else -1
        row = int((my - margin) / cell_h) if my >= margin else -1
        
        if 0 <= row < rows and 0 <= col < cols:
            if (row, col) != self._hover_cell:
                self._hover_cell = (row, col)
                val = self.matrix[row, col]
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{self.home_name} {row} - {col} {self.away_name}\n"
                    f"Probabilidad: {val:.2%}"
                )
                self.update()
        else:
            self._hover_cell = (-1, -1)
            self.update()
    
    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        w, h = self.width(), self.height()
        margin = 50
        
        p.fillRect(self.rect(), QColor(Colors.BG_CARD))
        
        rows, cols = self.matrix.shape
        cell_w = (w - margin - 10) / cols
        cell_h = (h - margin - 10) / rows
        
        vmin = np.min(self.matrix)
        vmax = max(np.max(self.matrix), 0.001)
        
        # Dibujar celdas
        for r in range(rows):
            for c in range(cols):
                x = margin + c * cell_w
                y = margin + r * cell_h
                val = self.matrix[r, c]
                
                color = self._get_heatmap_color(val, vmin, vmax)
                
                # Highlight hover
                if (r, c) == self._hover_cell:
                    color = color.lighter(140)
                
                p.fillRect(int(x) + 1, int(y) + 1, int(cell_w) - 2, int(cell_h) - 2, color)
                
                # Texto
                if val >= 0.005:
                    p.setPen(QColor("#FFFFFF"))
                    p.setFont(QFont("Consolas", 9, QFont.Bold))
                    p.drawText(
                        int(x), int(y), int(cell_w), int(cell_h),
                        Qt.AlignCenter, f"{val:.1%}"
                    )
                
                # Borde diagonal (empates)
                if r == c:
                    p.setPen(QPen(QColor(Colors.YELLOW), 2))
                    p.drawRect(int(x) + 1, int(y) + 1, int(cell_w) - 2, int(cell_h) - 2)
        
        # Labels columnas (arriba = goles visitante)
        p.setPen(QColor(Colors.RED))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        for c in range(cols):
            x = margin + c * cell_w
            p.drawText(int(x), 10, int(cell_w), 20, Qt.AlignCenter, str(c))
        
        # Nombre visitante arriba
        p.setPen(QColor(Colors.RED_DIM))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(margin, 30, int(cols * cell_w), 16, Qt.AlignCenter, 
                    f"← Goles {self.away_name} →")
        
        # Labels filas (izquierda = goles local)
        p.setPen(QColor(Colors.GREEN))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        for r in range(rows):
            y = margin + r * cell_h
            p.drawText(5, int(y), 35, int(cell_h), Qt.AlignCenter, str(r))
        
        # Nombre local a la izquierda (rotado)
        p.save()
        p.setPen(QColor(Colors.GREEN_DIM))
        p.setFont(QFont("Segoe UI", 8))
        p.translate(12, margin + rows * cell_h / 2)
        p.rotate(-90)
        p.drawText(-50, 0, 100, 16, Qt.AlignCenter, f"Goles {self.home_name}")
        p.restore()
        
        p.end()


class ProbabilityCard(QFrame):
    """Tarjeta que muestra una probabilidad con label."""
    
    def __init__(self, title: str, color: str = Colors.BLUE, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
                padding: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        
        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Segoe UI", 8))
        self.title_label.setStyleSheet(f"color: {Colors.TEXT_DIM}; border: none;")
        self.title_label.setAlignment(Qt.AlignCenter)
        
        self.value_label = QLabel("—")
        self.value_label.setFont(QFont("Consolas", 18, QFont.Bold))
        self.value_label.setStyleSheet(f"color: {color}; border: none;")
        self.value_label.setAlignment(Qt.AlignCenter)
        
        self.odds_label = QLabel("")
        self.odds_label.setFont(QFont("Consolas", 10))
        self.odds_label.setStyleSheet(f"color: {Colors.TEXT_MUTED}; border: none;")
        self.odds_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.odds_label)
    
    def set_value(self, prob: float, show_odds: bool = True):
        self.value_label.setText(f"{prob:.1%}")
        if show_odds and prob > 0.005:
            odds = 1.0 / prob
            self.odds_label.setText(f"@{odds:.2f}")
        else:
            self.odds_label.setText("")


class TopScoresWidget(QFrame):
    """Widget que muestra los marcadores más probables."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {Colors.BG_CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
            }}
        """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 8, 12, 8)
        self.layout.setSpacing(4)
        
        title = QLabel("⚽ Marcadores más probables")
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT}; border: none;")
        self.layout.addWidget(title)
        
        self.scores_container = QVBoxLayout()
        self.layout.addLayout(self.scores_container)
    
    def set_scores(self, scores: List[Tuple], home_name: str, away_name: str):
        # Limpiar
        while self.scores_container.count():
            item = self.scores_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        for i, (h, a, prob) in enumerate(scores[:8]):
            row = QHBoxLayout()
            
            # Ranking
            rank_lbl = QLabel(f"#{i+1}")
            rank_lbl.setFont(QFont("Consolas", 9))
            rank_lbl.setStyleSheet(f"color: {Colors.TEXT_MUTED}; border: none;")
            rank_lbl.setFixedWidth(28)
            
            # Marcador
            score_lbl = QLabel(f"{h} - {a}")
            score_lbl.setFont(QFont("Consolas", 12, QFont.Bold))
            # Color por resultado
            if h > a:
                color = Colors.GREEN
            elif h == a:
                color = Colors.YELLOW
            else:
                color = Colors.RED
            score_lbl.setStyleSheet(f"color: {color}; border: none;")
            score_lbl.setFixedWidth(55)
            
            # Barra de probabilidad
            bar = QFrame()
            bar.setFixedHeight(14)
            bar_width = max(5, int(prob * 800))
            bar.setFixedWidth(min(bar_width, 200))
            bar.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {color}, stop:1 transparent);
                    border-radius: 3px;
                    border: none;
                }}
            """)
            
            # Porcentaje
            pct_lbl = QLabel(f"{prob:.1%}")
            pct_lbl.setFont(QFont("Consolas", 9, QFont.Bold))
            pct_lbl.setStyleSheet(f"color: {Colors.TEXT}; border: none;")
            pct_lbl.setFixedWidth(50)
            
            # Cuota
            odds_lbl = QLabel(f"@{1/prob:.1f}" if prob > 0.005 else "")
            odds_lbl.setFont(QFont("Consolas", 9))
            odds_lbl.setStyleSheet(f"color: {Colors.TEXT_MUTED}; border: none;")
            odds_lbl.setFixedWidth(45)
            
            row.addWidget(rank_lbl)
            row.addWidget(score_lbl)
            row.addWidget(bar)
            row.addStretch()
            row.addWidget(pct_lbl)
            row.addWidget(odds_lbl)
            
            container = QWidget()
            container.setLayout(row)
            container.setStyleSheet("border: none;")
            self.scores_container.addWidget(container)


# ============================================================================
# WORKER THREAD
# ============================================================================

class PredictionWorker(QThread):
    """Worker para calcular predicción dual en background."""
    finished = Signal(object)  # DualPrediction
    error = Signal(str)
    progress = Signal(str)
    
    def __init__(self, engine, home_id, away_id, level_home, level_away, window):
        super().__init__()
        self.engine = engine
        self.home_id = home_id
        self.away_id = away_id
        self.level_home = level_home
        self.level_away = level_away
        self.window = window
    
    def run(self):
        try:
            self.progress.emit("Calculando distribuciones...")
            dual = self.engine.predict_match(
                self.home_id, self.away_id,
                self.level_home, self.level_away,
                self.window
            )
            self.finished.emit(dual)
        except Exception as e:
            logger.error(f"Error en predicción: {e}", exc_info=True)
            self.error.emit(str(e))


# ============================================================================
# VENTANA PRINCIPAL
# ============================================================================

class KScorelineWindow(QMainWindow):
    """Ventana principal del predictor de marcadores por K."""
    
    def __init__(self, constants_db: str = None, sad_db: str = None,
                 levels_db: str = None, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("⚽ Marcador por Constantes K — Dixon-Coles")
        self.setMinimumSize(1100, 750)
        self.resize(1280, 850)
        
        # Resolver rutas de DB
        if not constants_db or not sad_db:
            base = self._find_project_root()
            constants_db = constants_db or os.path.join(base, 'constants.db')
            sad_db = sad_db or os.path.join(base, 'sad.db')
            levels_db = levels_db or os.path.join(base, 'levels.db')
        
        # Importar engine
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from k_scoreline_engine import KScorelineEngine
        
        self.engine = KScorelineEngine(constants_db, sad_db, levels_db)
        self._db_paths = (constants_db, sad_db, levels_db)
        self.prediction = None
        self.worker = None
        self._child_windows = []
        
        self._setup_style()
        self._setup_ui()
        self._load_teams()
    
    def _find_project_root(self) -> str:
        """Encuentra la raíz del proyecto."""
        current = os.path.dirname(os.path.abspath(__file__))
        for _ in range(5):
            if os.path.exists(os.path.join(current, 'constants.db')):
                return current
            if os.path.exists(os.path.join(current, 'sad.db')):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return os.getcwd()
    
    def _setup_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {Colors.BG_DARK};
            }}
            QWidget {{
                background-color: {Colors.BG_DARK};
                color: {Colors.TEXT};
                font-family: "Segoe UI", "SF Pro Display", sans-serif;
            }}
            QGroupBox {{
                background-color: {Colors.BG_PANEL};
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
                margin-top: 16px;
                padding: 16px;
                padding-top: 28px;
                font-size: 11px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
                color: {Colors.TEXT_DIM};
            }}
            QComboBox {{
                background-color: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                color: {Colors.TEXT};
                min-height: 28px;
            }}
            QComboBox:hover {{
                border-color: {Colors.BLUE_DIM};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                color: {Colors.TEXT};
                selection-background-color: {Colors.BLUE_DIM};
            }}
            QDoubleSpinBox, QSpinBox {{
                background-color: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 4px 8px;
                color: {Colors.TEXT};
                font-size: 12px;
            }}
            QPushButton {{
                background-color: {Colors.BLUE_DIM};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Colors.BLUE};
            }}
            QPushButton:pressed {{
                background-color: {Colors.BLUE_DIM};
            }}
            QPushButton:disabled {{
                background-color: {Colors.BG_INPUT};
                color: {Colors.TEXT_MUTED};
            }}
            QScrollArea {{
                border: none;
            }}
            QLabel {{
                border: none;
            }}
        """)
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)
        
        # === HEADER ===
        header = QHBoxLayout()
        
        title = QLabel("⚽ Marcador por Constantes K")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT};")
        header.addWidget(title)
        
        subtitle = QLabel("Dixon-Coles desde dinámica de K")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet(f"color: {Colors.TEXT_DIM};")
        header.addWidget(subtitle)
        header.addStretch()
        
        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Segoe UI", 9))
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        header.addWidget(self.status_label)
        
        main_layout.addLayout(header)
        
        # === CONTROLES ===
        controls_group = QGroupBox("Selección de partido")
        controls_layout = QGridLayout()
        controls_layout.setSpacing(12)
        
        # Local
        lbl_home = QLabel("🏠 Local")
        lbl_home.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_home.setStyleSheet(f"color: {Colors.GREEN};")
        controls_layout.addWidget(lbl_home, 0, 0)
        
        self.combo_home = QComboBox()
        self.combo_home.setEditable(True)
        self.combo_home.setMinimumWidth(280)
        self.combo_home.setInsertPolicy(QComboBox.NoInsert)
        controls_layout.addWidget(self.combo_home, 0, 1)
        
        lbl_lvl_h = QLabel("Nivel rival:")
        lbl_lvl_h.setStyleSheet(f"color: {Colors.TEXT_DIM};")
        controls_layout.addWidget(lbl_lvl_h, 0, 2)
        
        self.spin_level_home = QDoubleSpinBox()
        self.spin_level_home.setRange(0.1, 5.0)
        self.spin_level_home.setValue(1.0)
        self.spin_level_home.setSingleStep(0.1)
        self.spin_level_home.setDecimals(2)
        self.spin_level_home.setFixedWidth(80)
        self.spin_level_home.setToolTip("Nivel del visitante (rival del local)\nSe importa automáticamente de levels.db")
        controls_layout.addWidget(self.spin_level_home, 0, 3)
        
        # VS
        vs_lbl = QLabel("VS")
        vs_lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        vs_lbl.setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        vs_lbl.setAlignment(Qt.AlignCenter)
        controls_layout.addWidget(vs_lbl, 0, 4)
        
        # Visitante
        lbl_away = QLabel("✈️ Visita")
        lbl_away.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_away.setStyleSheet(f"color: {Colors.RED};")
        controls_layout.addWidget(lbl_away, 0, 5)
        
        self.combo_away = QComboBox()
        self.combo_away.setEditable(True)
        self.combo_away.setMinimumWidth(280)
        self.combo_away.setInsertPolicy(QComboBox.NoInsert)
        controls_layout.addWidget(self.combo_away, 0, 6)
        
        lbl_lvl_a = QLabel("Nivel rival:")
        lbl_lvl_a.setStyleSheet(f"color: {Colors.TEXT_DIM};")
        controls_layout.addWidget(lbl_lvl_a, 0, 7)
        
        self.spin_level_away = QDoubleSpinBox()
        self.spin_level_away.setRange(0.1, 5.0)
        self.spin_level_away.setValue(1.0)
        self.spin_level_away.setSingleStep(0.1)
        self.spin_level_away.setDecimals(2)
        self.spin_level_away.setFixedWidth(80)
        self.spin_level_away.setToolTip("Nivel del local (rival del visitante)\nSe importa automáticamente de levels.db")
        controls_layout.addWidget(self.spin_level_away, 0, 8)
        
        # Ventana
        lbl_window = QLabel("Ventana:")
        lbl_window.setStyleSheet(f"color: {Colors.TEXT_DIM};")
        controls_layout.addWidget(lbl_window, 1, 0)
        
        self.spin_window = QSpinBox()
        self.spin_window.setRange(5, 500)
        self.spin_window.setValue(20)
        self.spin_window.setFixedWidth(80)
        controls_layout.addWidget(self.spin_window, 1, 1)
        
        # Botón calcular
        self.btn_calculate = QPushButton("🔮  Calcular Marcador")
        self.btn_calculate.setFixedHeight(40)
        self.btn_calculate.clicked.connect(self._on_calculate)
        controls_layout.addWidget(self.btn_calculate, 1, 5, 1, 2)
        
        self.btn_prev = QPushButton("📋  Partido Anterior")
        self.btn_prev.setFixedHeight(40)
        self.btn_prev.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_INPUT};
                color: {Colors.TEXT};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                border-color: {Colors.BLUE_DIM};
                background-color: {Colors.BG_CARD};
            }}
        """)
        self.btn_prev.setToolTip("Abre una ventana para el partido anterior de cada equipo")
        self.btn_prev.clicked.connect(self._on_previous_match)
        controls_layout.addWidget(self.btn_prev, 1, 7, 1, 2)
        
        controls_group.setLayout(controls_layout)
        main_layout.addWidget(controls_group)
        
        # === SCROLL AREA PARA RESULTADOS ===
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.results_widget = QWidget()
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(12)
        
        # --- Dos paneles: K Resultados (arriba) y K Goles (abajo) ---
        self.panel_results = self._create_prediction_panel("📊 Marcador por K de Resultados", "res")
        self.results_layout.addWidget(self.panel_results['group'])
        
        self.panel_goals = self._create_prediction_panel("⚽ Marcador por K de Goles", "gol")
        self.results_layout.addWidget(self.panel_goals['group'])
        
        self.results_layout.addStretch()
        
        scroll.setWidget(self.results_widget)
        main_layout.addWidget(scroll)
    
    def _create_prediction_panel(self, title: str, prefix: str) -> Dict:
        """Crea un panel completo de predicción (cards + barras + heatmap + scores)."""
        widgets = {}
        
        group = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        # --- Fila de probabilidades ---
        probs = QHBoxLayout()
        probs.setSpacing(6)
        
        widgets['card_home'] = ProbabilityCard("1", Colors.GREEN)
        widgets['card_draw'] = ProbabilityCard("X", Colors.YELLOW)
        widgets['card_away'] = ProbabilityCard("2", Colors.RED)
        widgets['card_o15'] = ProbabilityCard("O1.5", Colors.CYAN)
        widgets['card_o25'] = ProbabilityCard("O2.5", Colors.BLUE)
        widgets['card_o35'] = ProbabilityCard("O3.5", Colors.PURPLE)
        widgets['card_btts'] = ProbabilityCard("BTTS", Colors.ORANGE)
        widgets['card_lam_h'] = ProbabilityCard("λH", Colors.GREEN_DIM)
        widgets['card_lam_a'] = ProbabilityCard("λA", Colors.RED_DIM)
        
        for key in ['card_home', 'card_draw', 'card_away', 'card_o15',
                     'card_o25', 'card_o35', 'card_btts', 'card_lam_h', 'card_lam_a']:
            probs.addWidget(widgets[key])
        
        layout.addLayout(probs)
        
        # --- Distribuciones + Heatmap + Top scores ---
        splitter = QSplitter(Qt.Horizontal)
        
        # Barras izquierda
        dist_w = QWidget()
        dist_l = QVBoxLayout(dist_w)
        dist_l.setContentsMargins(0, 0, 0, 0)
        dist_l.setSpacing(4)
        
        widgets['bar_h_scored'] = DistributionBarWidget()
        widgets['bar_h_conceded'] = DistributionBarWidget()
        widgets['bar_a_scored'] = DistributionBarWidget()
        widgets['bar_a_conceded'] = DistributionBarWidget()
        
        for key in ['bar_h_scored', 'bar_h_conceded', 'bar_a_scored', 'bar_a_conceded']:
            widgets[key].setMinimumHeight(100)
            dist_l.addWidget(widgets[key])
        
        splitter.addWidget(dist_w)
        
        # Heatmap centro
        widgets['heatmap'] = HeatmapWidget()
        widgets['heatmap'].setMinimumHeight(250)
        splitter.addWidget(widgets['heatmap'])
        
        # Top scores derecha
        widgets['top_scores'] = TopScoresWidget()
        splitter.addWidget(widgets['top_scores'])
        
        splitter.setSizes([280, 350, 270])
        layout.addWidget(splitter)
        
        # Info label
        widgets['info'] = QLabel("")
        widgets['info'].setFont(QFont("Consolas", 8))
        widgets['info'].setStyleSheet(f"color: {Colors.TEXT_MUTED};")
        layout.addWidget(widgets['info'])
        
        group.setLayout(layout)
        widgets['group'] = group
        return widgets
    
    def _load_teams(self):
        """Carga equipos en los combos."""
        try:
            teams = self.engine.get_teams_list()
            
            self.combo_home.clear()
            self.combo_away.clear()
            
            self._teams_data = teams
            
            for tid, name in teams:
                self.combo_home.addItem(f"{name}", tid)
                self.combo_away.addItem(f"{name}", tid)
            
            # Completar con búsqueda
            team_names = [name for _, name in teams]
            
            completer_h = QCompleter(team_names)
            completer_h.setCaseSensitivity(Qt.CaseInsensitive)
            completer_h.setFilterMode(Qt.MatchContains)
            self.combo_home.setCompleter(completer_h)
            
            completer_a = QCompleter(team_names)
            completer_a.setCaseSensitivity(Qt.CaseInsensitive)
            completer_a.setFilterMode(Qt.MatchContains)
            self.combo_away.setCompleter(completer_a)
            
            self.status_label.setText(f"{len(teams)} equipos cargados")
            
            # Auto-importar niveles al cambiar equipo
            self.combo_home.currentIndexChanged.connect(self._on_team_changed)
            self.combo_away.currentIndexChanged.connect(self._on_team_changed)
            
        except Exception as e:
            logger.error(f"Error cargando equipos: {e}")
            self.status_label.setText(f"Error: {e}")
    
    def _on_team_changed(self):
        """Auto-importa niveles y limita ventana al equipo con menos partidos."""
        home_idx = self.combo_home.currentIndex()
        away_idx = self.combo_away.currentIndex()
        
        if home_idx >= 0 and away_idx >= 0:
            home_id = self.combo_home.itemData(home_idx)
            away_id = self.combo_away.itemData(away_idx)
            
            if home_id and away_id:
                # Nivel rival del local = nivel del visitante
                lvl_away = self.engine.get_team_level(away_id)
                self.spin_level_home.setValue(lvl_away)
                
                # Nivel rival del visitante = nivel del local
                lvl_home = self.engine.get_team_level(home_id)
                self.spin_level_away.setValue(lvl_home)
                
                # Limitar ventana al mínimo de registros entre ambos
                n_home = self.engine.get_team_record_count(home_id)
                n_away = self.engine.get_team_record_count(away_id)
                max_window = min(n_home, n_away)
                max_window = max(max_window, 5)  # Mínimo 5
                
                self.spin_window.setMaximum(max_window)
                if self.spin_window.value() > max_window:
                    self.spin_window.setValue(min(20, max_window))
                
                self.status_label.setText(
                    f"Partidos: {n_home} / {n_away} — Ventana máx: {max_window}"
                )
    
    def _on_calculate(self):
        """Inicia el cálculo de predicción."""
        home_idx = self.combo_home.currentIndex()
        away_idx = self.combo_away.currentIndex()
        
        if home_idx < 0 or away_idx < 0:
            return
        
        home_id = self.combo_home.itemData(home_idx)
        away_id = self.combo_away.itemData(away_idx)
        
        if home_id == away_id:
            QMessageBox.warning(self, "Error", "Selecciona equipos diferentes.")
            return
        
        level_h = self.spin_level_home.value()
        level_a = self.spin_level_away.value()
        window = self.spin_window.value()
        
        self.btn_calculate.setEnabled(False)
        self.btn_calculate.setText("⏳ Calculando...")
        self.status_label.setText("Procesando predicción...")
        
        self.worker = PredictionWorker(
            self.engine, home_id, away_id,
            level_h, level_a, window
        )
        self.worker.finished.connect(self._on_prediction_ready)
        self.worker.error.connect(self._on_prediction_error)
        self.worker.start()
    
    def _on_prediction_ready(self, dual):
        """Actualiza ambos paneles con los resultados."""
        self.dual = dual
        
        self._fill_panel(self.panel_results, dual.by_results)
        self._fill_panel(self.panel_goals, dual.by_goals)
        
        self.btn_calculate.setEnabled(True)
        self.btn_calculate.setText("🔮  Calcular Marcador")
        self.status_label.setText(
            f"✅ {dual.by_results.home_team} vs {dual.by_results.away_team} — "
            f"K Res: {dual.by_results.top_scores[0][0]}-{dual.by_results.top_scores[0][1]} "
            f"({dual.by_results.top_scores[0][2]:.1%}) │ "
            f"K Gol: {dual.by_goals.top_scores[0][0]}-{dual.by_goals.top_scores[0][1]} "
            f"({dual.by_goals.top_scores[0][2]:.1%})"
        )
    
    def _fill_panel(self, panel: Dict, pred):
        """Rellena un panel de predicción con datos."""
        # Probabilidades
        panel['card_home'].set_value(pred.p_home)
        panel['card_draw'].set_value(pred.p_draw)
        panel['card_away'].set_value(pred.p_away)
        panel['card_o15'].set_value(pred.p_over_15)
        panel['card_o25'].set_value(pred.p_over_25)
        panel['card_o35'].set_value(pred.p_over_35)
        panel['card_btts'].set_value(pred.p_btts)
        panel['card_lam_h'].value_label.setText(f"{pred.lambda_home:.2f}")
        panel['card_lam_h'].odds_label.setText("goles")
        panel['card_lam_a'].value_label.setText(f"{pred.lambda_away:.2f}")
        panel['card_lam_a'].odds_label.setText("goles")
        
        # Distribuciones
        hd, ad = pred.home_dist, pred.away_dist
        panel['bar_h_scored'].set_data(hd.p_scored, f"🏠 {hd.team_name} — Anotados", Colors.GREEN)
        panel['bar_h_conceded'].set_data(hd.p_conceded, f"🏠 {hd.team_name} — Recibidos", Colors.RED_DIM)
        panel['bar_a_scored'].set_data(ad.p_scored, f"✈️ {ad.team_name} — Anotados", Colors.RED)
        panel['bar_a_conceded'].set_data(ad.p_conceded, f"✈️ {ad.team_name} — Recibidos", Colors.BLUE_DIM)
        
        # Heatmap
        panel['heatmap'].set_data(pred.match_matrix, pred.home_team, pred.away_team)
        
        # Top scores
        panel['top_scores'].set_scores(pred.top_scores, pred.home_team, pred.away_team)
        
        # Info
        ht = hd.score_table
        at = ad.score_table
        panel['info'].setText(
            f"ρ={pred.rho:.3f}  λH={pred.lambda_home:.2f}  λA={pred.lambda_away:.2f}  │  "
            f"Nivel: {hd.opponent_level:.2f}/{ad.opponent_level:.2f}  │  "
            f"N home: {ht.n_general}g/{ht.n_contextual}c  "
            f"N away: {at.n_general}g/{at.n_contextual}c"
        )
    
    def _on_previous_match(self):
        """Abre ventanas para el partido anterior de cada equipo seleccionado."""
        home_idx = self.combo_home.currentIndex()
        away_idx = self.combo_away.currentIndex()
        
        if home_idx < 0 or away_idx < 0:
            QMessageBox.warning(self, "Error", "Selecciona ambos equipos primero.")
            return
        
        home_id = self.combo_home.itemData(home_idx)
        away_id = self.combo_away.itemData(away_idx)
        
        opened = 0
        for team_id, label in [(home_id, "Local"), (away_id, "Visita")]:
            prev = self.engine.get_previous_match(team_id)
            if not prev:
                self.status_label.setText(f"⚠️ Sin partido anterior para {label}")
                continue
            
            # Crear nueva ventana
            win = KScorelineWindow(
                constants_db=self._db_paths[0],
                sad_db=self._db_paths[1],
                levels_db=self._db_paths[2],
            )
            win.setWindowTitle(
                f"📋 Anterior: {prev['home_name']} vs {prev['away_name']} "
                f"({prev['score']}) — {prev['date']}"
            )
            
            # Pre-seleccionar equipos
            for i in range(win.combo_home.count()):
                if win.combo_home.itemData(i) == prev['home_id']:
                    win.combo_home.setCurrentIndex(i)
                    break
            for i in range(win.combo_away.count()):
                if win.combo_away.itemData(i) == prev['away_id']:
                    win.combo_away.setCurrentIndex(i)
                    break
            
            win.show()
            self._child_windows.append(win)
            opened += 1
        
        if opened:
            self.status_label.setText(f"✅ {opened} ventana(s) de partido anterior abierta(s)")
    
    def _on_prediction_error(self, error_msg: str):
        self.btn_calculate.setEnabled(True)
        self.btn_calculate.setText("🔮  Calcular Marcador")
        self.status_label.setText(f"❌ Error: {error_msg}")
        QMessageBox.critical(self, "Error", f"Error en predicción:\n{error_msg}")


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Punto de entrada independiente."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    window = KScorelineWindow()
    window.show()
    
    if not QApplication.instance().property("running"):
        app.setProperty("running", True)
        sys.exit(app.exec())


if __name__ == "__main__":
    main()