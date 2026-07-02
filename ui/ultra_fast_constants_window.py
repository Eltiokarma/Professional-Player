#!/usr/bin/env python3
# src/ui/ultra_fast_constants_window.py
"""
🚀 Ventana ultra-rápida para mostrar constantes de equipos.

VERSIÓN 3.0 - PyQtGraph:
- Crosshair vertical con panel lateral contextual
- Info de partido: fecha, rival, resultado, liga
- Valores con cambio vs partido anterior
- Zoom/pan nativo y fluido
- Modos de visualización preconfigurados
"""

from PySide6.QtWidgets import (QMainWindow, QSplitter, QWidget, QListWidget,
                               QListWidgetItem, QTabWidget, QVBoxLayout, QHBoxLayout,
                               QTableView, QPushButton, QFileDialog, QMessageBox,
                               QLineEdit, QLabel, QProgressBar, QStatusBar,
                               QGroupBox, QButtonGroup, QFrame, QGridLayout,
                               QScrollArea, QSizePolicy, QDoubleSpinBox, QToolButton)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QColor, QCursor
import pyqtgraph as pg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import logging

from utils.constants_calculator import ConstantsCalculator
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from data.database_manager import engine, CONST_ENGINE
from data.data_models.teams import Team
from ui.pandas_model import PandasModel
import os

Session = sessionmaker(bind=engine)
logger = logging.getLogger(__name__)

# Cargar CSV de ligas (una sola vez)
LEAGUES_DF = None

def get_leagues_df():
    """Carga el CSV de ligas (cached)"""
    global LEAGUES_DF
    if LEAGUES_DF is None:
        try:
            # Buscar el CSV en varias ubicaciones posibles
            possible_paths = [
                os.path.join(os.path.dirname(__file__), 'leagues2024.csv'),
                os.path.join(os.path.dirname(__file__), '..', 'leagues2024.csv'),
                os.path.join(os.path.dirname(__file__), '..', 'src', 'leagues2024.csv'),
                r'D:\VSCode Ejercicios 02\src\leagues2024.csv',
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    LEAGUES_DF = pd.read_csv(path)
                    # Normalizar nombres de columnas
                    LEAGUES_DF.columns = [c.strip().lower().replace(' ', '_') for c in LEAGUES_DF.columns]
                    logger.info(f"Ligas cargadas desde: {path}")
                    break
            
            if LEAGUES_DF is None:
                logger.warning("No se encontró leagues2024.csv")
                LEAGUES_DF = pd.DataFrame()
        except Exception as e:
            logger.error(f"Error cargando ligas: {e}")
            LEAGUES_DF = pd.DataFrame()
    
    return LEAGUES_DF

def get_league_name(league_id):
    """Obtiene el nombre de una liga por su ID"""
    if league_id is None:
        return None
    
    df = get_leagues_df()
    if df.empty:
        return None
    
    # Buscar por league_id
    match = df[df['league_id'] == league_id]
    if not match.empty:
        return match.iloc[0].get('league_name', None)
    
    return None


# ============================================================================
# 🎨 CONFIGURACIÓN VISUAL
# ============================================================================

# Configuración global de PyQtGraph
pg.setConfigOptions(antialias=True, background='w', foreground='k')

# Colores para las líneas (palette profesional)
COLORS = {
    'k_positivo': '#2ecc71',           # Verde
    'k_negativo': '#e74c3c',           # Rojo
    'k_positivo_local': '#27ae60',     # Verde oscuro
    'k_negativo_local': '#c0392b',     # Rojo oscuro
    'k_positivo_visita': '#1abc9c',    # Turquesa
    'k_negativo_visita': '#e67e22',    # Naranja
    'k_goles_anotado': '#3498db',      # Azul
    'k_goles_recibido': '#9b59b6',     # Púrpura
    'k_goles_local_anotado': '#2980b9',    # Azul oscuro
    'k_goles_local_recibido': '#8e44ad',   # Púrpura oscuro
    'k_goles_visita_anotado': '#5dade2',   # Azul claro
    'k_goles_visita_recibido': '#af7ac5',  # Púrpura claro
}

# Modos de visualización
VIEW_MODES = {
    "all": {
        "name": "🔄 Todas",
        "tooltip": "Mostrar todas las constantes K",
        "columns": None,
    },
    "global": {
        "name": "📈 Global",
        "tooltip": "Rendimiento general",
        "columns": ["k_positivo", "k_negativo"],
    },
    "local_away": {
        "name": "🏠 Local/Visita",
        "tooltip": "Comparar local vs visitante",
        "columns": ["k_positivo_local", "k_negativo_local", 
                   "k_positivo_visita", "k_negativo_visita"],
    },
    "goals": {
        "name": "⚽ Goles",
        "tooltip": "Métricas de goles",
        "columns": ["k_goles_anotado", "k_goles_recibido",
                   "k_goles_local_anotado", "k_goles_local_recibido",
                   "k_goles_visita_anotado", "k_goles_visita_recibido"],
    },
}


class BackgroundSyncWorker(QThread):
    """Worker para sincronización en background"""
    finished = Signal(bool, int)
    progress = Signal(str)
    
    def __init__(self, team_id, full_recalc=False):
        super().__init__()
        self.team_id = team_id
        self.full_recalc = full_recalc
    
    def run(self):
        try:
            with ConstantsCalculator() as calc:
                if self.full_recalc:
                    self.progress.emit("🔄 Recalculando todo...")
                    success = calc.full_recalculate_team(self.team_id)
                else:
                    self.progress.emit("⚡ Sincronizando...")
                    success = calc.incremental_calculate_and_store(self.team_id)
                
                df = calc.get_stored_constants(self.team_id)
                count = len(df) if df is not None else 0
                self.finished.emit(success, count)
        except Exception as e:
            logger.error(f"Error en sync: {e}")
            self.finished.emit(False, 0)


class MatchInfoPanel(QFrame):
    """
    📊 Panel lateral que muestra información del partido seleccionado
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setMinimumWidth(280)
        self.setMaximumWidth(320)
        
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        
        # === HEADER: Info del partido ===
        self.header_group = QGroupBox("📅 Partido Seleccionado")
        header_layout = QVBoxLayout(self.header_group)
        
        self.lbl_date = QLabel("--")
        self.lbl_date.setFont(QFont("Arial", 12, QFont.Bold))
        header_layout.addWidget(self.lbl_date)
        
        self.lbl_match = QLabel("Mueve el cursor sobre el gráfico")
        self.lbl_match.setWordWrap(True)
        self.lbl_match.setFont(QFont("Arial", 11))
        header_layout.addWidget(self.lbl_match)
        
        self.lbl_result = QLabel("")
        self.lbl_result.setFont(QFont("Arial", 14, QFont.Bold))
        self.lbl_result.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.lbl_result)
        
        self.lbl_league = QLabel("")
        self.lbl_league.setStyleSheet("color: #666; font-style: italic;")
        header_layout.addWidget(self.lbl_league)
        
        layout.addWidget(self.header_group)
        
        # === VALORES: Métricas K ===
        self.values_group = QGroupBox("📊 Valores")
        self.values_layout = QVBoxLayout(self.values_group)
        
        # Scroll area para los valores
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        self.values_container = QWidget()
        self.values_grid = QGridLayout(self.values_container)
        self.values_grid.setSpacing(4)
        
        scroll.setWidget(self.values_container)
        self.values_layout.addWidget(scroll)
        
        layout.addWidget(self.values_group, 1)
        
        # Labels para valores (se crean dinámicamente)
        self.value_labels = {}
    
    def setup_metrics(self, columns):
        """Configura las métricas a mostrar"""
        # Limpiar labels existentes
        for col, label_dict in self.value_labels.items():
            for label in label_dict.values():
                if hasattr(label, 'deleteLater'):
                    label.deleteLater()
        self.value_labels.clear()
        
        # Limpiar grid
        while self.values_grid.count():
            item = self.values_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Crear nuevos labels
        for i, col in enumerate(columns):
            # Nombre de la métrica
            name_label = QLabel(col.replace('k_', ''))
            name_label.setStyleSheet(f"color: {COLORS.get(col, '#333')};")
            name_label.setFont(QFont("Arial", 9, QFont.Bold))
            
            # Valor actual
            value_label = QLabel("--")
            value_label.setAlignment(Qt.AlignRight)
            value_label.setFont(QFont("Consolas", 10))
            
            # Cambio
            change_label = QLabel("")
            change_label.setAlignment(Qt.AlignRight)
            change_label.setFont(QFont("Arial", 9))
            
            self.values_grid.addWidget(name_label, i, 0)
            self.values_grid.addWidget(value_label, i, 1)
            self.values_grid.addWidget(change_label, i, 2)
            
            self.value_labels[col] = {
                'name': name_label,
                'value': value_label,
                'change': change_label
            }
    
    def update_match_info(self, date_str, rival, is_home, goals_for, goals_against, 
                          league_name, round_name):
        """Actualiza la información del partido"""
        self.lbl_date.setText(f"📅 {date_str}")
        
        location = "🏠 Local" if is_home else "✈️ Visita"
        self.lbl_match.setText(f"{location} vs {rival}")
        
        # Resultado con color
        if goals_for is not None and goals_against is not None:
            if goals_for > goals_against:
                result_color = "#27ae60"  # Verde - Victoria
                result_emoji = "✅"
            elif goals_for < goals_against:
                result_color = "#e74c3c"  # Rojo - Derrota
                result_emoji = "❌"
            else:
                result_color = "#f39c12"  # Amarillo - Empate
                result_emoji = "➖"
            
            self.lbl_result.setText(f"{result_emoji} {goals_for} - {goals_against}")
            self.lbl_result.setStyleSheet(f"color: {result_color}; font-size: 18px;")
        else:
            self.lbl_result.setText("--")
            self.lbl_result.setStyleSheet("color: #999;")
        
        league_text = league_name or "Liga desconocida"
        if round_name:
            league_text += f" • {round_name}"
        self.lbl_league.setText(league_text)
    
    def update_values(self, values_dict, changes_dict):
        """Actualiza los valores de las métricas"""
        for col, labels in self.value_labels.items():
            value = values_dict.get(col)
            change = changes_dict.get(col)
            
            if value is not None and not np.isnan(value):
                labels['value'].setText(f"{value:.1f}")
                
                if change is not None and not np.isnan(change):
                    if change > 0:
                        labels['change'].setText(f"↑{change:.1f}")
                        labels['change'].setStyleSheet("color: #27ae60;")
                    elif change < 0:
                        labels['change'].setText(f"↓{abs(change):.1f}")
                        labels['change'].setStyleSheet("color: #e74c3c;")
                    else:
                        labels['change'].setText("→0")
                        labels['change'].setStyleSheet("color: #999;")
                else:
                    labels['change'].setText("")
            else:
                labels['value'].setText("--")
                labels['change'].setText("")
    
    def clear(self):
        """Limpia el panel"""
        self.lbl_date.setText("--")
        self.lbl_match.setText("Mueve el cursor sobre el gráfico")
        self.lbl_result.setText("")
        self.lbl_league.setText("")
        
        for labels in self.value_labels.values():
            labels['value'].setText("--")
            labels['change'].setText("")


class ReferenceLinesPanel(QFrame):
    """
    📏 Panel para gestionar líneas de referencia (horizontales y verticales)
    """
    # Señales para comunicar con el gráfico
    line_added = Signal(str, float)      # tipo ('h' o 'v'), valor
    line_removed = Signal(str, float)    # tipo, valor
    line_moved = Signal(str, float, float)  # tipo, valor_old, valor_new
    clear_all = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        
        self.h_lines = {}  # {valor: widget_row}
        self.v_lines = {}  # {valor: widget_row}
        
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Título
        title = QLabel("📏 Líneas de referencia")
        title.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(title)
        
        # Instrucciones
        instructions = QLabel("Doble-click = horizontal\nShift+Doble-click = vertical")
        instructions.setStyleSheet("color: #888; font-size: 9px;")
        layout.addWidget(instructions)
        
        # === Líneas horizontales ===
        h_group = QGroupBox("━ Horizontales (Y)")
        h_layout = QVBoxLayout(h_group)
        h_layout.setSpacing(2)
        
        # Contenedor scrollable para líneas H
        self.h_container = QWidget()
        self.h_lines_layout = QVBoxLayout(self.h_container)
        self.h_lines_layout.setSpacing(2)
        self.h_lines_layout.setContentsMargins(0, 0, 0, 0)
        self.h_lines_layout.addStretch()
        
        h_scroll = QScrollArea()
        h_scroll.setWidgetResizable(True)
        h_scroll.setWidget(self.h_container)
        h_scroll.setMaximumHeight(100)
        h_scroll.setFrameShape(QFrame.NoFrame)
        h_layout.addWidget(h_scroll)
        
        # Agregar manual horizontal
        h_add_layout = QHBoxLayout()
        self.h_spinbox = QDoubleSpinBox()
        self.h_spinbox.setRange(-1000, 1000)
        self.h_spinbox.setDecimals(1)
        self.h_spinbox.setValue(0)
        h_add_layout.addWidget(self.h_spinbox)
        
        btn_add_h = QToolButton()
        btn_add_h.setText("+")
        btn_add_h.setToolTip("Agregar línea horizontal")
        btn_add_h.clicked.connect(self._add_h_line_manual)
        h_add_layout.addWidget(btn_add_h)
        h_layout.addLayout(h_add_layout)
        
        layout.addWidget(h_group)
        
        # === Líneas verticales ===
        v_group = QGroupBox("│ Verticales (Partido #)")
        v_layout = QVBoxLayout(v_group)
        v_layout.setSpacing(2)
        
        # Contenedor scrollable para líneas V
        self.v_container = QWidget()
        self.v_lines_layout = QVBoxLayout(self.v_container)
        self.v_lines_layout.setSpacing(2)
        self.v_lines_layout.setContentsMargins(0, 0, 0, 0)
        self.v_lines_layout.addStretch()
        
        v_scroll = QScrollArea()
        v_scroll.setWidgetResizable(True)
        v_scroll.setWidget(self.v_container)
        v_scroll.setMaximumHeight(100)
        v_scroll.setFrameShape(QFrame.NoFrame)
        v_layout.addWidget(v_scroll)
        
        # Agregar manual vertical
        v_add_layout = QHBoxLayout()
        self.v_spinbox = QDoubleSpinBox()
        self.v_spinbox.setRange(0, 10000)
        self.v_spinbox.setDecimals(0)
        self.v_spinbox.setValue(0)
        v_add_layout.addWidget(self.v_spinbox)
        
        btn_add_v = QToolButton()
        btn_add_v.setText("+")
        btn_add_v.setToolTip("Agregar línea vertical")
        btn_add_v.clicked.connect(self._add_v_line_manual)
        v_add_layout.addWidget(btn_add_v)
        v_layout.addLayout(v_add_layout)
        
        layout.addWidget(v_group)
        
        # Botón limpiar todo
        btn_clear = QPushButton("🗑️ Limpiar todas")
        btn_clear.clicked.connect(self._clear_all)
        layout.addWidget(btn_clear)
        
        layout.addStretch()
    
    def _add_h_line_manual(self):
        """Agregar línea horizontal desde spinbox"""
        value = self.h_spinbox.value()
        self.add_horizontal_line(value)
        self.line_added.emit('h', value)
    
    def _add_v_line_manual(self):
        """Agregar línea vertical desde spinbox"""
        value = int(self.v_spinbox.value())
        self.add_vertical_line(value)
        self.line_added.emit('v', value)
    
    def add_horizontal_line(self, value):
        """Agrega una línea horizontal al panel"""
        if value in self.h_lines:
            return  # Ya existe
        
        row = self._create_line_row('h', value)
        # Insertar antes del stretch
        self.h_lines_layout.insertWidget(self.h_lines_layout.count() - 1, row)
        self.h_lines[value] = row
    
    def add_vertical_line(self, value):
        """Agrega una línea vertical al panel"""
        value = int(value)
        if value in self.v_lines:
            return  # Ya existe
        
        row = self._create_line_row('v', value)
        # Insertar antes del stretch
        self.v_lines_layout.insertWidget(self.v_lines_layout.count() - 1, row)
        self.v_lines[value] = row
    
    def _create_line_row(self, line_type, value):
        """Crea un widget row para una línea"""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        
        # Color indicator
        color = "#e67e22" if line_type == 'h' else "#9b59b6"
        color_label = QLabel("━" if line_type == 'h' else "│")
        color_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        row_layout.addWidget(color_label)
        
        # Valor
        if line_type == 'h':
            value_label = QLabel(f"{value:.1f}")
        else:
            value_label = QLabel(f"#{int(value)}")
        value_label.setFont(QFont("Consolas", 9))
        row_layout.addWidget(value_label)
        
        row_layout.addStretch()
        
        # Botón eliminar
        btn_remove = QToolButton()
        btn_remove.setText("×")
        btn_remove.setStyleSheet("color: #e74c3c;")
        btn_remove.setToolTip("Eliminar línea")
        btn_remove.clicked.connect(lambda: self._remove_line(line_type, value))
        row_layout.addWidget(btn_remove)
        
        return row
    
    def _remove_line(self, line_type, value):
        """Elimina una línea"""
        if line_type == 'h' and value in self.h_lines:
            self.h_lines[value].deleteLater()
            del self.h_lines[value]
            self.line_removed.emit('h', value)
        elif line_type == 'v' and value in self.v_lines:
            self.v_lines[value].deleteLater()
            del self.v_lines[value]
            self.line_removed.emit('v', value)
    
    def remove_horizontal_line(self, value):
        """Remueve línea horizontal (llamado desde gráfico)"""
        if value in self.h_lines:
            self.h_lines[value].deleteLater()
            del self.h_lines[value]
    
    def remove_vertical_line(self, value):
        """Remueve línea vertical (llamado desde gráfico)"""
        value = int(value)
        if value in self.v_lines:
            self.v_lines[value].deleteLater()
            del self.v_lines[value]
    
    def _clear_all(self):
        """Elimina todas las líneas"""
        for value in list(self.h_lines.keys()):
            self.h_lines[value].deleteLater()
        self.h_lines.clear()
        
        for value in list(self.v_lines.keys()):
            self.v_lines[value].deleteLater()
        self.v_lines.clear()
        
        self.clear_all.emit()
    
    def get_all_lines(self):
        """Retorna todas las líneas actuales"""
        return {
            'horizontal': list(self.h_lines.keys()),
            'vertical': list(self.v_lines.keys())
        }


class UltraFastConstantsWindow(QMainWindow):
    """
    🚀 VENTANA ULTRA-RÁPIDA con PyQtGraph
    
    CARACTERÍSTICAS v3.0:
    - PyQtGraph para gráficos fluidos
    - Crosshair vertical + panel contextual
    - Info completa del partido (rival, resultado, liga)
    - Cambio vs partido anterior
    - Zoom/pan nativo con scroll y drag
    """
    
    def __init__(self, parent, team_id: int):
        super().__init__(parent)
        self.team_id = team_id
        self.team_name = ""
        self.df = None
        self.df_enriched = None  # Con info de partidos
        self.plot_items = {}     # Referencias a las líneas
        self.current_mode = "all"
        self.current_idx = None
        self.background_worker = None
        self.spotlight_active = False
        self.legend_visible = True
        self.legend_item = None
        self.original_pens = {}  # Guardar pens originales para spotlight
        
        # Líneas de referencia
        self.ref_h_lines = {}  # {valor: InfiniteLine}
        self.ref_v_lines = {}  # {valor: InfiniteLine}
        self.dragging_line = None  # Línea siendo arrastrada
        self.drag_line_type = None  # 'h' o 'v'
        self.drag_start_value = None
        
        # Timers
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._perform_search)
        
        self._build_ui()
        self._load_data_immediately()

    def _build_ui(self):
        self.resize(1600, 900)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.sync_progress = QProgressBar()
        self.sync_progress.setMaximumWidth(200)
        self.sync_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.sync_progress)
        
        # Splitter principal
        self.main_splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(self.main_splitter)

        # === PANEL IZQUIERDO: Lista de equipos ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(250)
        
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar equipo...")
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input)
        left_layout.addLayout(search_layout)
        
        self.list_equips = QListWidget()
        self.list_equips.itemDoubleClicked.connect(self._load_another_team)
        left_layout.addWidget(self.list_equips)
        
        self.main_splitter.addWidget(left_panel)

        # === PANEL CENTRAL: Gráfico + controles ===
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        
        # Toolbar de modos
        self._build_mode_toolbar(center_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        center_layout.addWidget(self.tabs, 1)
        
        # TAB 1: Tabla
        tab_table = QWidget()
        self.tabs.addTab(tab_table, "📊 Tabla")
        table_layout = QVBoxLayout(tab_table)
        self.table_view = QTableView()
        table_layout.addWidget(self.table_view)
        
        # TAB 2: Gráfico interactivo
        tab_graph = QWidget()
        self.tabs.addTab(tab_graph, "📈 Gráfico")
        self._build_graph_tab(tab_graph)
        
        # TAB 3: Mini-gráficos
        tab_mini = QWidget()
        self.tabs.addTab(tab_mini, "📊 Mini-gráficos")
        self._build_mini_graphs_tab(tab_mini)
        
        # Botones inferiores
        self._build_bottom_buttons(center_layout)
        
        self.main_splitter.addWidget(center_widget)
        
        # === PANEL DERECHO: Info + Líneas de referencia ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        
        # Panel de info del partido
        self.info_panel = MatchInfoPanel()
        right_layout.addWidget(self.info_panel, 2)
        
        # Panel de líneas de referencia
        self.ref_lines_panel = ReferenceLinesPanel()
        self.ref_lines_panel.line_added.connect(self._on_ref_line_added)
        self.ref_lines_panel.line_removed.connect(self._on_ref_line_removed)
        self.ref_lines_panel.clear_all.connect(self._on_ref_lines_clear)
        right_layout.addWidget(self.ref_lines_panel, 1)
        
        self.main_splitter.addWidget(right_panel)
        
        # Proporciones del splitter
        self.main_splitter.setStretchFactor(0, 1)  # Lista equipos
        self.main_splitter.setStretchFactor(1, 4)  # Gráfico
        self.main_splitter.setStretchFactor(2, 1)  # Info panel

    def _build_mode_toolbar(self, parent_layout):
        """Construye la barra de modos de visualización"""
        toolbar = QHBoxLayout()
        
        mode_group = QGroupBox("Vista rápida")
        mode_layout = QHBoxLayout(mode_group)
        mode_layout.setSpacing(4)
        
        self.mode_buttons = {}
        self.mode_button_group = QButtonGroup(self)
        
        for mode_key, mode_info in VIEW_MODES.items():
            btn = QPushButton(mode_info["name"])
            btn.setToolTip(mode_info["tooltip"])
            btn.setCheckable(True)
            btn.setMinimumWidth(90)
            btn.clicked.connect(lambda checked, m=mode_key: self._set_view_mode(m))
            
            if mode_key == "all":
                btn.setChecked(True)
            
            self.mode_buttons[mode_key] = btn
            self.mode_button_group.addButton(btn)
            mode_layout.addWidget(btn)
        
        toolbar.addWidget(mode_group)
        
        # Controles de zoom
        zoom_group = QGroupBox("Zoom")
        zoom_layout = QHBoxLayout(zoom_group)
        
        btn_reset = QPushButton("🔍 Reset")
        btn_reset.clicked.connect(self._reset_zoom)
        zoom_layout.addWidget(btn_reset)
        
        btn_year = QPushButton("📅 1 año")
        btn_year.clicked.connect(lambda: self._zoom_to_period(365))
        zoom_layout.addWidget(btn_year)
        
        btn_6m = QPushButton("6m")
        btn_6m.clicked.connect(lambda: self._zoom_to_period(180))
        zoom_layout.addWidget(btn_6m)
        
        btn_3m = QPushButton("3m")
        btn_3m.clicked.connect(lambda: self._zoom_to_period(90))
        zoom_layout.addWidget(btn_3m)
        
        toolbar.addWidget(zoom_group)
        
        # Grupo: Opciones
        options_group = QGroupBox("Opciones")
        options_layout = QHBoxLayout(options_group)
        
        self.btn_spotlight = QPushButton("💡 Spotlight")
        self.btn_spotlight.setCheckable(True)
        self.btn_spotlight.setToolTip("Resaltar línea al pasar el mouse")
        self.btn_spotlight.clicked.connect(self._toggle_spotlight)
        options_layout.addWidget(self.btn_spotlight)
        
        self.btn_legend = QPushButton("📋 Leyenda")
        self.btn_legend.setCheckable(True)
        self.btn_legend.setChecked(True)
        self.btn_legend.setToolTip("Mostrar/ocultar leyenda")
        self.btn_legend.clicked.connect(self._toggle_legend)
        options_layout.addWidget(self.btn_legend)
        
        toolbar.addWidget(options_group)
        toolbar.addStretch()
        
        parent_layout.addLayout(toolbar)

    def _build_graph_tab(self, tab_widget):
        """Construye la pestaña del gráfico con PyQtGraph"""
        layout = QHBoxLayout(tab_widget)
        
        # Widget de PyQtGraph
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('left', 'Valor')
        self.plot_widget.setLabel('bottom', 'Partido #')
        
        # Habilitar zoom con scroll y pan con drag
        self.plot_widget.setMouseEnabled(x=True, y=True)
        
        # Línea horizontal en y=0
        self.zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('k', width=1, style=Qt.DashLine))
        self.plot_widget.addItem(self.zero_line)
        
        # Crosshair vertical
        self.crosshair = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen('#3498db', width=2))
        self.crosshair.setVisible(False)
        self.plot_widget.addItem(self.crosshair)
        
        # Punto indicador
        self.hover_point = pg.ScatterPlotItem(size=12, brush=pg.mkBrush('#3498db'))
        self.plot_widget.addItem(self.hover_point)
        
        # Conectar señal de movimiento del mouse
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)
        self.plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)
        
        # Detectar cuando el mouse sale del área del gráfico
        self.plot_widget.leaveEvent = self._on_mouse_leave
        
        layout.addWidget(self.plot_widget, 1)
        
        # Panel de checkboxes (para toggle individual)
        checkbox_panel = QWidget()
        checkbox_panel.setMaximumWidth(180)
        checkbox_layout = QVBoxLayout(checkbox_panel)
        checkbox_layout.addWidget(QLabel("📋 Métricas:"))
        
        self.chk_container = QListWidget()
        self.chk_container.setMaximumWidth(170)
        checkbox_layout.addWidget(self.chk_container)
        
        layout.addWidget(checkbox_panel)

    def _build_mini_graphs_tab(self, tab_widget):
        """📊 Construye la pestaña de mini-gráficos sincronizados"""
        layout = QVBoxLayout(tab_widget)
        
        # Info
        info_label = QLabel("📊 Vista de mini-gráficos: cada métrica en su propio panel")
        info_label.setStyleSheet("color: #666; font-style: italic; padding: 5px;")
        layout.addWidget(info_label)
        
        # Canvas para mini-gráficos (matplotlib)
        self.mini_canvas = FigureCanvasQTAgg(plt.Figure(figsize=(12, 8)))
        layout.addWidget(self.mini_canvas, 1)
        
        # Botón de actualizar
        btn_refresh_mini = QPushButton("🔄 Actualizar mini-gráficos")
        btn_refresh_mini.clicked.connect(self._update_mini_graphs)
        layout.addWidget(btn_refresh_mini)

    def _build_bottom_buttons(self, parent_layout):
        """Construye los botones inferiores"""
        buttons = QHBoxLayout()
        
        btn_sync = QPushButton("🔄 Sincronizar")
        btn_sync.clicked.connect(self._force_sync)
        buttons.addWidget(btn_sync)
        
        btn_recalc = QPushButton("🔁 Recalcular Todo")
        btn_recalc.clicked.connect(self._force_full_recalc)
        btn_recalc.setStyleSheet("background-color: #e74c3c; color: white;")
        buttons.addWidget(btn_recalc)
        
        btn_export = QPushButton("📁 Exportar CSV")
        btn_export.clicked.connect(self._export)
        buttons.addWidget(btn_export)
        
        try:
            from ui.simulator_window import SimulatorWindow
            btn_sim = QPushButton("🎯 Simular")
            btn_sim.clicked.connect(lambda: SimulatorWindow(self, self.team_id).show())
            buttons.addWidget(btn_sim)
        except ImportError:
            pass
        
        buttons.addStretch()
        parent_layout.addLayout(buttons)

    # ========================================================================
    # 📊 CARGA DE DATOS
    # ========================================================================
    
    def _load_data_immediately(self):
        """Carga inicial de datos"""
        try:
            session = Session()
            try:
                team = session.query(Team).filter_by(id=self.team_id).first()
            finally:
                session.close()
            
            if not team:
                QMessageBox.warning(self, "Error", f"Equipo {self.team_id} no encontrado")
                self.close()
                return
            
            self.team_name = team.name
            self.setWindowTitle(f"⚡ Constantes - {team.name}")
            
            self._load_existing_data()
            QTimer.singleShot(100, self._load_teams_list)
            QTimer.singleShot(500, self._auto_sync)
            
        except Exception as e:
            logger.error(f"Error cargando datos: {e}")
            QMessageBox.critical(self, "Error", str(e))

    def _load_existing_data(self):
        """Carga datos de constantes con información de partidos"""
        try:
            # 1. Cargar constantes desde CONST_ENGINE (constants.db)
            query_constants = text("""
                SELECT 
                    date as Fecha,
                    fixture_id,
                    k_positivo, k_negativo,
                    k_positivo_local, k_negativo_local,
                    k_positivo_visita, k_negativo_visita,
                    k_goles_anotado, k_goles_recibido,
                    k_goles_local_anotado, k_goles_local_recibido,
                    k_goles_visita_anotado, k_goles_visita_recibido
                FROM constants
                WHERE team_id = :team_id
                ORDER BY date
            """)
            
            df_constants = pd.read_sql_query(
                query_constants, CONST_ENGINE, 
                params={"team_id": int(self.team_id)}
            )
            
            if df_constants.empty:
                self.status_bar.showMessage("⏳ Sin datos - sincronizando...")
                self._show_no_data()
                return
            
            # 2. Obtener fixture_ids para buscar info de partidos
            fixture_ids = df_constants['fixture_id'].dropna().astype(int).tolist()
            
            if fixture_ids:
                # 3. Cargar info de fixtures desde engine (sad.db)
                # Interpolar IDs directamente (seguro porque son integers)
                ids_str = ','.join(str(int(fid)) for fid in fixture_ids)
                query_fixtures = f"""
                    SELECT 
                        f.id as fixture_id,
                        f.home_team_id, f.away_team_id,
                        f.goals_home, f.goals_away,
                        f.league_id, f.league_round,
                        th.name as home_team_name,
                        ta.name as away_team_name
                    FROM fixtures f
                    LEFT JOIN teams th ON f.home_team_id = th.id
                    LEFT JOIN teams ta ON f.away_team_id = ta.id
                    WHERE f.id IN ({ids_str})
                """
                
                df_fixtures = pd.read_sql_query(query_fixtures, engine)
                
                # 4. Merge en pandas
                self.df_enriched = df_constants.merge(
                    df_fixtures, on='fixture_id', how='left'
                )
            else:
                self.df_enriched = df_constants
            
            # 5. Agregar nombres de ligas desde CSV
            if 'league_id' in self.df_enriched.columns:
                self.df_enriched['league_name'] = self.df_enriched['league_id'].apply(get_league_name)
            else:
                self.df_enriched['league_name'] = None
            
            # 6. Calcular cambios vs partido anterior
            k_cols = [c for c in self.df_enriched.columns if c.startswith('k_')]
            for col in k_cols:
                self.df_enriched[f'{col}_change'] = self.df_enriched[col].diff()
            
            self.df = self.df_enriched  # Compatibilidad
            
            self.status_bar.showMessage(f"✅ {len(self.df_enriched)} partidos cargados")
            self._update_displays()
            
        except Exception as e:
            logger.error(f"Error cargando datos: {e}")
            import traceback
            traceback.print_exc()
            self._show_no_data()

    def _show_no_data(self):
        """Muestra mensaje cuando no hay datos"""
        self.plot_widget.clear()
        text_item = pg.TextItem("⏳ Sin datos\nUsa 'Sincronizar' o 'Recalcular Todo'", 
                               anchor=(0.5, 0.5), color='k')
        text_item.setFont(QFont("Arial", 14))
        self.plot_widget.addItem(text_item)
        text_item.setPos(0, 0)

    # ========================================================================
    # 📈 ACTUALIZACIÓN DEL GRÁFICO
    # ========================================================================
    
    def _update_displays(self):
        """Actualiza tabla y gráfico"""
        if self.df is None or self.df.empty:
            return
        
        # Actualizar tabla
        display_cols = ['Fecha'] + [c for c in self.df.columns if c.startswith('k_') and not c.endswith('_change')]
        display_df = self.df[display_cols].copy()
        display_df['Fecha'] = pd.to_datetime(display_df['Fecha']).dt.strftime('%Y-%m-%d')
        self.table_view.setModel(PandasModel(display_df))
        
        # Actualizar gráfico
        self._update_graph()
        
        # Configurar panel de info
        k_cols = [c for c in self.df.columns if c.startswith('k_') and not c.endswith('_change')]
        self.info_panel.setup_metrics(k_cols)

    def _update_graph(self):
        """Actualiza el gráfico con PyQtGraph"""
        if self.df is None or self.df.empty:
            return
        
        # Limpiar gráfico (mantener crosshair y zero line)
        for item in list(self.plot_items.values()):
            self.plot_widget.removeItem(item)
        self.plot_items.clear()
        self.original_pens.clear()
        
        # Desconectar señal de checkboxes temporalmente
        try:
            self.chk_container.itemChanged.disconnect(self._toggle_line)
        except (RuntimeError, TypeError):
            pass  # No estaba conectada
        
        self.chk_container.clear()
        
        k_columns = [c for c in self.df.columns if c.startswith('k_') and not c.endswith('_change')]
        x = np.arange(len(self.df))
        
        # Obtener columnas del modo actual
        mode_cols = VIEW_MODES[self.current_mode]["columns"]
        
        for col in k_columns:
            if self.df[col].isna().all():
                continue
            
            y = self.df[col].values
            color = COLORS.get(col, '#333333')
            
            # Crear línea con grosor aumentado
            pen = pg.mkPen(color=color, width=3)
            line = self.plot_widget.plot(x, y, pen=pen, name=col)
            self.plot_items[col] = line
            self.original_pens[col] = pen  # Guardar pen original para spotlight
            
            # Visibilidad según modo
            if mode_cols is None or col in mode_cols:
                line.setVisible(True)
            else:
                line.setVisible(False)
            
            # Checkbox
            item = QListWidgetItem(col.replace('k_', ''))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if line.isVisible() else Qt.Unchecked)
            item.setData(Qt.UserRole, col)
            item.setForeground(QColor(color))
            self.chk_container.addItem(item)
        
        # Reconectar señal
        self.chk_container.itemChanged.connect(self._toggle_line)
        
        # Configurar ejes
        self.plot_widget.setTitle(f"Evolución de constantes K - {self.team_name}")
        self.plot_widget.setXRange(0, len(self.df), padding=0.02)
        
        # Leyenda (removida primero si existe)
        if self.legend_item is not None:
            try:
                self.plot_widget.removeItem(self.legend_item)
            except:
                pass
        
        self.legend_item = self.plot_widget.addLegend(offset=(10, 10))
        if not self.legend_visible:
            self.legend_item.setVisible(False)
        
        # Mostrar crosshair
        self.crosshair.setVisible(True)

    def _set_view_mode(self, mode_key):
        """Cambia el modo de visualización"""
        self.current_mode = mode_key
        mode_cols = VIEW_MODES[mode_key]["columns"]
        
        # Actualizar visibilidad de líneas
        for col, line in self.plot_items.items():
            visible = (mode_cols is None or col in mode_cols)
            line.setVisible(visible)
        
        # Actualizar checkboxes
        for i in range(self.chk_container.count()):
            item = self.chk_container.item(i)
            col = item.data(Qt.UserRole)
            visible = (mode_cols is None or col in mode_cols)
            item.setCheckState(Qt.Checked if visible else Qt.Unchecked)
        
        # Actualizar panel con métricas del modo
        if mode_cols:
            self.info_panel.setup_metrics(mode_cols)
        else:
            k_cols = [c for c in self.df.columns if c.startswith('k_') and not c.endswith('_change')]
            self.info_panel.setup_metrics(k_cols)
        
        self.status_bar.showMessage(f"Vista: {VIEW_MODES[mode_key]['name']}")

    def _toggle_line(self, item):
        """Toggle visibilidad de una línea individual"""
        col = item.data(Qt.UserRole)
        if col in self.plot_items:
            visible = item.checkState() == Qt.Checked
            self.plot_items[col].setVisible(visible)

    def _toggle_spotlight(self):
        """💡 Activa/desactiva el modo spotlight"""
        self.spotlight_active = self.btn_spotlight.isChecked()
        
        if not self.spotlight_active:
            # Restaurar todas las líneas a su estado original
            self._restore_all_lines()
        
        status = "activado" if self.spotlight_active else "desactivado"
        self.status_bar.showMessage(f"Spotlight {status}")

    def _toggle_legend(self):
        """📋 Muestra/oculta la leyenda"""
        self.legend_visible = self.btn_legend.isChecked()
        
        if self.legend_item is not None:
            self.legend_item.setVisible(self.legend_visible)
        
        status = "visible" if self.legend_visible else "oculta"
        self.status_bar.showMessage(f"Leyenda {status}")

    def _restore_all_lines(self):
        """Restaura todas las líneas a su estado original"""
        for col, line in self.plot_items.items():
            if col in self.original_pens:
                line.setPen(self.original_pens[col])

    def _highlight_line(self, highlight_col):
        """Resalta una línea y atenúa las demás"""
        for col, line in self.plot_items.items():
            if not line.isVisible():
                continue
            
            color = COLORS.get(col, '#333333')
            
            if col == highlight_col:
                # Línea resaltada: más gruesa y opaca
                pen = pg.mkPen(color=color, width=5)
            else:
                # Otras líneas: más finas y transparentes
                pen = pg.mkPen(color=color, width=1, style=Qt.DotLine)
                pen.setColor(QColor(color).lighter(150))
            
            line.setPen(pen)

    def _update_mini_graphs(self):
        """📊 Actualiza los mini-gráficos sincronizados"""
        if self.df is None or self.df.empty:
            self.status_bar.showMessage("Sin datos para mini-gráficos")
            return
        
        try:
            self.mini_canvas.figure.clear()
            
            k_columns = [c for c in self.df.columns if c.startswith('k_') and not c.endswith('_change')]
            if not k_columns:
                return
            
            # Determinar grid layout (3 columnas)
            n_cols = 3
            n_rows = (len(k_columns) + n_cols - 1) // n_cols
            
            x = np.arange(len(self.df))
            axes = self.mini_canvas.figure.subplots(n_rows, n_cols, sharex=True)
            axes = np.array(axes).flatten()
            
            for i, col in enumerate(k_columns):
                ax = axes[i]
                color = COLORS.get(col, '#333333')
                
                if not self.df[col].isna().all():
                    y = self.df[col].values
                    ax.plot(x, y, color=color, linewidth=1.5)
                    ax.axhline(0, color='black', linewidth=0.5, alpha=0.5)
                    
                    # Áreas coloreadas
                    ax.fill_between(
                        x, 0, y, 
                        where=np.array(y) > 0, 
                        alpha=0.3, color='green',
                        interpolate=True
                    )
                    ax.fill_between(
                        x, 0, y, 
                        where=np.array(y) < 0, 
                        alpha=0.3, color='red',
                        interpolate=True
                    )
                
                ax.set_title(col.replace('k_', ''), fontsize=9, color=color)
                ax.tick_params(axis='both', labelsize=7)
                ax.grid(True, linestyle='--', alpha=0.3)
            
            # Ocultar axes vacíos
            for i in range(len(k_columns), len(axes)):
                axes[i].set_visible(False)
            
            self.mini_canvas.figure.tight_layout()
            self.mini_canvas.draw()
            
            self.status_bar.showMessage("Mini-gráficos actualizados")
            
        except Exception as e:
            logger.error(f"Error en mini-gráficos: {e}")
            self.status_bar.showMessage(f"Error: {e}")

    # ========================================================================
    # 🖱️ INTERACCIÓN CON MOUSE
    # ========================================================================
    
    def _on_mouse_moved(self, pos):
        """Maneja movimiento del mouse - actualiza crosshair y panel"""
        if self.df is None or self.df.empty:
            return
        
        # Convertir posición a coordenadas del plot
        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
        x = int(round(mouse_point.x()))
        
        # Validar rango
        if x < 0 or x >= len(self.df):
            return
        
        # Actualizar crosshair
        self.crosshair.setPos(x)
        
        # Si es el mismo índice, no actualizar
        if x == self.current_idx:
            return
        
        self.current_idx = x
        
        # Obtener datos del partido
        row = self.df_enriched.iloc[x]
        
        # Info del partido
        fecha = pd.to_datetime(row['Fecha']).strftime('%Y-%m-%d')
        
        # Determinar si fue local o visita
        is_home = (row.get('home_team_id') == self.team_id)
        
        if is_home:
            rival = row.get('away_team_name', 'Rival')
            goals_for = row.get('goals_home')
            goals_against = row.get('goals_away')
        else:
            rival = row.get('home_team_name', 'Rival')
            goals_for = row.get('goals_away')
            goals_against = row.get('goals_home')
        
        league_name = row.get('league_name', '')
        round_name = row.get('league_round', '')
        
        # Actualizar panel de info
        self.info_panel.update_match_info(
            fecha, rival or "?", is_home,
            goals_for, goals_against,
            league_name, round_name
        )
        
        # Obtener valores y cambios para métricas del modo actual
        mode_cols = VIEW_MODES[self.current_mode]["columns"]
        if mode_cols is None:
            mode_cols = [c for c in self.df.columns if c.startswith('k_') and not c.endswith('_change')]
        
        values = {}
        changes = {}
        
        for col in mode_cols:
            values[col] = row.get(col)
            changes[col] = row.get(f'{col}_change')
        
        self.info_panel.update_values(values, changes)
        
        # Actualizar punto indicador (en la primera línea visible)
        closest_col = None
        closest_dist = float('inf')
        
        for col in mode_cols:
            if col in self.plot_items and self.plot_items[col].isVisible():
                y_val = row.get(col)
                if y_val is not None and not np.isnan(y_val):
                    # Calcular distancia al cursor para spotlight
                    y_cursor = mouse_point.y()
                    dist = abs(y_val - y_cursor)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_col = col
                    
                    # Primer valor válido para el punto indicador
                    if closest_col == col:
                        self.hover_point.setData([x], [y_val])
        
        # Aplicar spotlight si está activo
        if self.spotlight_active and closest_col:
            self._highlight_line(closest_col)

    def _on_mouse_leave(self, event):
        """Restaura líneas cuando el mouse sale del gráfico"""
        if self.spotlight_active:
            self._restore_all_lines()
        self.current_idx = None

    def _on_mouse_clicked(self, event):
        """Maneja click en el gráfico para líneas de referencia"""
        if self.df is None or self.df.empty:
            return
        
        # Solo procesar doble-click
        if not event.double():
            return
        
        # Obtener posición en coordenadas del plot
        pos = event.scenePos()
        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
        
        # Verificar si se hizo click en una línea de referencia existente (para eliminar)
        clicked_on_existing = self._check_click_on_ref_line(mouse_point)
        if clicked_on_existing:
            return
        
        # Crear nueva línea según modificadores
        modifiers = event.modifiers()
        
        if modifiers & Qt.ShiftModifier:
            # Shift + Doble-click = Línea VERTICAL
            x_val = int(round(mouse_point.x()))
            if 0 <= x_val < len(self.df):
                self._add_vertical_ref_line(x_val)
                self.ref_lines_panel.add_vertical_line(x_val)
                self.status_bar.showMessage(f"Línea vertical agregada en partido #{x_val}")
        else:
            # Doble-click = Línea HORIZONTAL
            y_val = round(mouse_point.y(), 1)
            self._add_horizontal_ref_line(y_val)
            self.ref_lines_panel.add_horizontal_line(y_val)
            self.status_bar.showMessage(f"Línea horizontal agregada en Y={y_val}")

    def _check_click_on_ref_line(self, mouse_point):
        """Verifica si se hizo click en una línea existente y la elimina"""
        tolerance_h = 2  # Tolerancia para detectar click en línea horizontal
        tolerance_v = 3  # Tolerancia para detectar click en línea vertical
        
        # Verificar líneas horizontales
        for y_val, line in list(self.ref_h_lines.items()):
            if abs(mouse_point.y() - y_val) < tolerance_h:
                self._remove_horizontal_ref_line(y_val)
                self.ref_lines_panel.remove_horizontal_line(y_val)
                self.status_bar.showMessage(f"Línea horizontal Y={y_val} eliminada")
                return True
        
        # Verificar líneas verticales
        for x_val, line in list(self.ref_v_lines.items()):
            if abs(mouse_point.x() - x_val) < tolerance_v:
                self._remove_vertical_ref_line(x_val)
                self.ref_lines_panel.remove_vertical_line(x_val)
                self.status_bar.showMessage(f"Línea vertical #{x_val} eliminada")
                return True
        
        return False

    # ========================================================================
    # 📏 LÍNEAS DE REFERENCIA
    # ========================================================================
    
    def _add_horizontal_ref_line(self, y_val):
        """Agrega una línea horizontal de referencia al gráfico"""
        if y_val in self.ref_h_lines:
            return  # Ya existe
        
        pen = pg.mkPen(color='#e67e22', width=2, style=Qt.DashLine)
        line = pg.InfiniteLine(pos=y_val, angle=0, pen=pen, movable=True)
        line.sigPositionChanged.connect(lambda: self._on_h_line_moved(y_val, line))
        
        # Etiqueta
        label = pg.TextItem(f"{y_val:.1f}", color='#e67e22', anchor=(0, 1))
        label.setPos(0, y_val)
        
        self.plot_widget.addItem(line)
        self.plot_widget.addItem(label)
        self.ref_h_lines[y_val] = {'line': line, 'label': label}
    
    def _add_vertical_ref_line(self, x_val):
        """Agrega una línea vertical de referencia al gráfico"""
        x_val = int(x_val)
        if x_val in self.ref_v_lines:
            return  # Ya existe
        
        pen = pg.mkPen(color='#9b59b6', width=2, style=Qt.DashLine)
        line = pg.InfiniteLine(pos=x_val, angle=90, pen=pen, movable=True)
        line.sigPositionChanged.connect(lambda: self._on_v_line_moved(x_val, line))
        
        # Obtener fecha si existe
        label_text = f"#{x_val}"
        if self.df is not None and x_val < len(self.df):
            try:
                fecha = pd.to_datetime(self.df.iloc[x_val]['Fecha']).strftime('%Y-%m-%d')
                label_text = f"#{x_val}\n{fecha}"
            except:
                pass
        
        # Etiqueta
        label = pg.TextItem(label_text, color='#9b59b6', anchor=(0, 0))
        label.setPos(x_val, self.plot_widget.viewRange()[1][1])  # Top del gráfico
        
        self.plot_widget.addItem(line)
        self.plot_widget.addItem(label)
        self.ref_v_lines[x_val] = {'line': line, 'label': label}
    
    def _remove_horizontal_ref_line(self, y_val):
        """Remueve una línea horizontal del gráfico"""
        if y_val in self.ref_h_lines:
            self.plot_widget.removeItem(self.ref_h_lines[y_val]['line'])
            self.plot_widget.removeItem(self.ref_h_lines[y_val]['label'])
            del self.ref_h_lines[y_val]
    
    def _remove_vertical_ref_line(self, x_val):
        """Remueve una línea vertical del gráfico"""
        x_val = int(x_val)
        if x_val in self.ref_v_lines:
            self.plot_widget.removeItem(self.ref_v_lines[x_val]['line'])
            self.plot_widget.removeItem(self.ref_v_lines[x_val]['label'])
            del self.ref_v_lines[x_val]
    
    def _on_h_line_moved(self, old_val, line):
        """Maneja cuando se mueve una línea horizontal arrastrándola"""
        new_val = round(line.value(), 1)
        if new_val != old_val and old_val in self.ref_h_lines:
            # Actualizar diccionario
            data = self.ref_h_lines.pop(old_val)
            self.ref_h_lines[new_val] = data
            
            # Actualizar etiqueta
            data['label'].setText(f"{new_val:.1f}")
            data['label'].setPos(0, new_val)
            
            # Reconectar señal con nuevo valor
            try:
                line.sigPositionChanged.disconnect()
            except:
                pass
            line.sigPositionChanged.connect(lambda: self._on_h_line_moved(new_val, line))
            
            # Actualizar panel
            self.ref_lines_panel.remove_horizontal_line(old_val)
            self.ref_lines_panel.add_horizontal_line(new_val)
    
    def _on_v_line_moved(self, old_val, line):
        """Maneja cuando se mueve una línea vertical arrastrándola"""
        new_val = int(round(line.value()))
        if new_val != old_val and old_val in self.ref_v_lines:
            # Actualizar diccionario
            data = self.ref_v_lines.pop(old_val)
            self.ref_v_lines[new_val] = data
            
            # Actualizar etiqueta
            label_text = f"#{new_val}"
            if self.df is not None and new_val < len(self.df):
                try:
                    fecha = pd.to_datetime(self.df.iloc[new_val]['Fecha']).strftime('%Y-%m-%d')
                    label_text = f"#{new_val}\n{fecha}"
                except:
                    pass
            data['label'].setText(label_text)
            data['label'].setPos(new_val, self.plot_widget.viewRange()[1][1])
            
            # Reconectar señal con nuevo valor
            try:
                line.sigPositionChanged.disconnect()
            except:
                pass
            line.sigPositionChanged.connect(lambda: self._on_v_line_moved(new_val, line))
            
            # Actualizar panel
            self.ref_lines_panel.remove_vertical_line(old_val)
            self.ref_lines_panel.add_vertical_line(new_val)
    
    def _on_ref_line_added(self, line_type, value):
        """Callback cuando se agrega línea desde el panel"""
        if line_type == 'h':
            self._add_horizontal_ref_line(value)
        else:
            self._add_vertical_ref_line(int(value))
    
    def _on_ref_line_removed(self, line_type, value):
        """Callback cuando se elimina línea desde el panel"""
        if line_type == 'h':
            self._remove_horizontal_ref_line(value)
        else:
            self._remove_vertical_ref_line(int(value))
    
    def _on_ref_lines_clear(self):
        """Callback para limpiar todas las líneas"""
        # Limpiar horizontales
        for y_val in list(self.ref_h_lines.keys()):
            self._remove_horizontal_ref_line(y_val)
        
        # Limpiar verticales
        for x_val in list(self.ref_v_lines.keys()):
            self._remove_vertical_ref_line(x_val)

    # ========================================================================
    # 🔍 ZOOM Y NAVEGACIÓN
    # ========================================================================
    
    def _reset_zoom(self):
        """Reset zoom a vista completa"""
        if self.df is not None:
            self.plot_widget.setXRange(0, len(self.df), padding=0.02)
            self.plot_widget.enableAutoRange(axis='y')
        self.status_bar.showMessage("Zoom reseteado")
    
    def _zoom_to_period(self, days):
        """Zoom a los últimos N días"""
        if self.df is None or self.df.empty:
            return
        
        fechas = pd.to_datetime(self.df['Fecha'])
        ultima = fechas.max()
        inicio = ultima - pd.Timedelta(days=days)
        
        mask = fechas >= inicio
        if mask.any():
            idx_start = mask.idxmax()
            self.plot_widget.setXRange(idx_start, len(self.df), padding=0.02)
            self.status_bar.showMessage(f"Mostrando últimos {days} días")

    # ========================================================================
    # 🔄 SINCRONIZACIÓN
    # ========================================================================
    
    def _auto_sync(self):
        self._start_sync(False)
    
    def _force_sync(self):
        if self.background_worker and self.background_worker.isRunning():
            return
        self._start_sync(False)
    
    def _force_full_recalc(self):
        if self.background_worker and self.background_worker.isRunning():
            return
        
        if QMessageBox.question(self, "Confirmar", 
            "¿Recalcular TODAS las constantes?") == QMessageBox.Yes:
            self._start_sync(True)
    
    def _start_sync(self, full_recalc):
        if self.background_worker and self.background_worker.isRunning():
            return
        
        self.sync_progress.setVisible(True)
        self.sync_progress.setRange(0, 0)
        
        self.background_worker = BackgroundSyncWorker(self.team_id, full_recalc)
        self.background_worker.progress.connect(lambda m: self.status_bar.showMessage(m))
        self.background_worker.finished.connect(self._on_sync_finished)
        self.background_worker.start()
    
    def _on_sync_finished(self, success, count):
        self.sync_progress.setVisible(False)
        
        if success and count > 0:
            self.status_bar.showMessage(f"✅ {count} registros")
            self._load_existing_data()
        elif success:
            self.status_bar.showMessage("✅ Sin cambios")
        else:
            self.status_bar.showMessage("❌ Error")

    # ========================================================================
    # 🔧 UTILIDADES
    # ========================================================================
    
    def _load_teams_list(self):
        """Carga lista de equipos"""
        try:
            query = "SELECT id, name FROM teams ORDER BY name"
            teams_df = pd.read_sql_query(query, engine)
            
            self.list_equips.setUpdatesEnabled(False)
            self.list_equips.clear()
            
            current_item = None
            for row in teams_df.itertuples(index=False):
                item = QListWidgetItem(row.name)
                item.setData(256, int(row.id))
                self.list_equips.addItem(item)
                
                if int(row.id) == self.team_id:
                    current_item = item
            
            self.list_equips.setUpdatesEnabled(True)
            
            if current_item:
                current_item.setSelected(True)
                self.list_equips.scrollToItem(current_item)
                
        except Exception as e:
            logger.error(f"Error cargando equipos: {e}")
            self.list_equips.setUpdatesEnabled(True)

    def _on_search_changed(self, text):
        self.search_timer.stop()
        self.search_timer.start(300)

    def _perform_search(self):
        search_text = self.search_input.text().strip().lower()
        
        self.list_equips.setUpdatesEnabled(False)
        for i in range(self.list_equips.count()):
            item = self.list_equips.item(i)
            item.setHidden(len(search_text) >= 2 and search_text not in item.text().lower())
        self.list_equips.setUpdatesEnabled(True)

    def _export(self):
        if self.df is None or self.df.empty:
            QMessageBox.warning(self, "Error", "Sin datos")
            return
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar", f"constantes_{self.team_name}.csv", "CSV (*.csv)")
        
        if path:
            self.df.to_csv(path, index=False)
            QMessageBox.information(self, "✅", f"Exportado: {path}")

    def _load_another_team(self, item):
        new_id = item.data(256)
        if new_id != self.team_id:
            UltraFastConstantsWindow(self.parent(), new_id).show()

    def closeEvent(self, event):
        if self.background_worker and self.background_worker.isRunning():
            self.background_worker.quit()
            self.background_worker.wait(3000)
        event.accept()


# ============================================================================
# 🎯 ALIAS
# ============================================================================

FastConstantsWindow = UltraFastConstantsWindow
OptimizedConstantsResultsWindow = UltraFastConstantsWindow
ConstantsResultsWindow = UltraFastConstantsWindow