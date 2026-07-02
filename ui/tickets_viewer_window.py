#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tickets_viewer_window.py

Visor de Tickets de Apuestas
============================

Ventana completa con dos tabs:
- Tab 1: Mis Tickets (dashboard, filtros, tabla, acciones)
- Tab 2: Estadisticas (graficos de bankroll, ROI, win rate, yield, ML)

Autor: Gerson (desarrollado con Claude)
Fecha: Febrero 2026
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLabel, QComboBox, QDateEdit, QFrame,
    QMessageBox, QFileDialog, QSplitter, QGroupBox, QScrollArea,
    QSizePolicy, QAbstractItemView, QSpinBox, QDoubleSpinBox,
    QLineEdit, QApplication,
)
from PySide6.QtCore import Qt, QDate, Signal, QThread
from PySide6.QtGui import QFont, QColor, QIcon

logger = logging.getLogger(__name__)

# Intentar imports de graficos
try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False
    logger.warning("pyqtgraph no disponible - graficos interactivos deshabilitados")

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('QtAgg')
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    logger.warning("matplotlib no disponible - graficos estaticos deshabilitados")


# =============================================================================
# COLORES (consistentes con colors.py del proyecto)
# =============================================================================
class C:
    """Paleta rapida."""
    PRIMARY = '#1a1a2e'
    SECONDARY = '#16213e'
    ACCENT = '#FF6B35'
    BG = '#F8F9FA'
    CARD = '#FFFFFF'
    BORDER = '#DEE2E6'
    TEXT = '#212529'
    TEXT2 = '#6C757D'
    WIN = '#28A745'
    LOSS = '#DC3545'
    PENDING = '#17A2B8'
    VOID = '#FFC107'
    CHART1 = '#007BFF'
    CHART2 = '#28A745'
    CHART3 = '#FFC107'
    CHART4 = '#DC3545'
    CHART5 = '#6F42C1'


# =============================================================================
# ESTILOS
# =============================================================================
VIEWER_STYLES = f"""
QMainWindow {{
    background-color: {C.BG};
}}
QTabWidget::pane {{
    border: 1px solid {C.BORDER};
    border-radius: 4px;
    background: {C.CARD};
}}
QTabBar::tab {{
    background: {C.BG};
    border: 1px solid {C.BORDER};
    padding: 8px 20px;
    margin-right: 2px;
    font-size: 13px;
    font-weight: bold;
}}
QTabBar::tab:selected {{
    background: {C.CARD};
    border-bottom: 3px solid {C.ACCENT};
    color: {C.ACCENT};
}}
QTableWidget {{
    border: 1px solid {C.BORDER};
    border-radius: 4px;
    gridline-color: {C.BORDER};
    font-size: 12px;
    alternate-background-color: #F0F4F8;
}}
QTableWidget::item {{
    padding: 4px 8px;
}}
QTableWidget::item:selected {{
    background-color: #D0E8FF;
    color: {C.TEXT};
}}
QHeaderView::section {{
    background-color: {C.PRIMARY};
    color: white;
    padding: 6px;
    border: none;
    font-weight: bold;
    font-size: 11px;
}}
QPushButton {{
    padding: 6px 14px;
    border-radius: 4px;
    font-weight: bold;
    font-size: 12px;
}}
QComboBox {{
    padding: 4px 8px;
    border: 1px solid {C.BORDER};
    border-radius: 4px;
    font-size: 12px;
    min-width: 100px;
}}
QGroupBox {{
    font-weight: bold;
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 15px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}}
"""


# =============================================================================
# DASHBOARD CARD
# =============================================================================
class DashboardCard(QFrame):
    """Tarjeta individual del dashboard."""

    def __init__(self, title: str, value: str, color: str = C.CHART1, parent=None):
        super().__init__(parent)
        self.setFixedHeight(85)
        self.setMinimumWidth(130)
        self.setStyleSheet(f"""
            QFrame {{
                background: {C.CARD};
                border: 1px solid {C.BORDER};
                border-radius: 8px;
                border-top: 3px solid {color};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"color: {C.TEXT2}; font-size: 11px;")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: {C.TEXT}; font-size: 22px; font-weight: bold;")
        self.value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.value_label)

    def update_value(self, value: str, color: str = None):
        self.value_label.setText(value)
        if color:
            self.value_label.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")


# =============================================================================
# VENTANA PRINCIPAL
# =============================================================================
class TicketsViewerWindow(QMainWindow):
    """Visor completo de tickets de apuestas."""

    def __init__(self, tickets_db_path: str, sad_db_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Visor de Tickets de Apuestas")
        self.resize(1200, 800)
        self.setStyleSheet(VIEWER_STYLES)

        # Adaptar a pantalla
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            if self.width() > geo.width() or self.height() > geo.height():
                self.resize(int(geo.width() * 0.9), int(geo.height() * 0.9))

        # Inicializar manager
        from utils.tickets_manager import TicketsManager
        self.manager = TicketsManager(tickets_db_path, sad_db_path)

        # Cache de tickets para filtros
        self._current_tickets: List = []

        self._build_ui()
        self._connect_signals()

        # Resolver pendientes al abrir
        self._auto_resolve_on_open()

        # Cargar datos
        self._refresh_all()

    # =========================================================================
    # BUILD UI
    # =========================================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Header
        header = self._build_header()
        main_layout.addWidget(header)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # Tab 1: Mis Tickets
        tickets_tab = QWidget()
        self._build_tickets_tab(tickets_tab)
        self.tabs.addTab(tickets_tab, "  Mis Tickets  ")

        # Tab 2: Estadisticas
        stats_tab = QWidget()
        self._build_stats_tab(stats_tab)
        self.tabs.addTab(stats_tab, "  Estadisticas  ")

        main_layout.addWidget(self.tabs, 1)

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C.PRIMARY}, stop:1 {C.SECONDARY});
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        layout = QHBoxLayout(frame)

        title = QLabel("VISOR DE TICKETS")
        title.setStyleSheet("color: white; font-size: 18px; font-weight: bold; letter-spacing: 2px;")
        layout.addWidget(title)

        layout.addStretch()

        # Botones de accion
        self.btn_resolve = QPushButton("Resolver Pendientes")
        self.btn_resolve.setStyleSheet(f"""
            QPushButton {{
                background: {C.PENDING}; color: white; border: none;
                padding: 8px 16px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #138496; }}
        """)
        layout.addWidget(self.btn_resolve)

        self.btn_export = QPushButton("Exportar CSV")
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                background: {C.CHART5}; color: white; border: none;
                padding: 8px 16px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #5A32A3; }}
        """)
        layout.addWidget(self.btn_export)

        return frame

    # =========================================================================
    # TAB 1: MIS TICKETS
    # =========================================================================

    def _build_tickets_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setSpacing(8)

        # Dashboard cards
        self._build_dashboard(layout)

        # Filtros
        self._build_filters(layout)

        # Tabla
        self._build_tickets_table(layout)

        # Acciones de tabla
        self._build_table_actions(layout)

    def _build_dashboard(self, parent_layout):
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)

        self.card_total = DashboardCard("Total Tickets", "0", C.CHART1)
        self.card_winrate = DashboardCard("Win Rate", "0%", C.WIN)
        self.card_roi = DashboardCard("ROI", "0%", C.ACCENT)
        self.card_profit = DashboardCard("Profit Neto", "S/.0", C.WIN)
        self.card_pending = DashboardCard("Pendientes", "0", C.PENDING)

        for card in [self.card_total, self.card_winrate, self.card_roi, self.card_profit, self.card_pending]:
            cards_layout.addWidget(card)

        parent_layout.addLayout(cards_layout)

    def _build_filters(self, parent_layout):
        filters_frame = QFrame()
        filters_frame.setStyleSheet(f"""
            QFrame {{
                background: {C.CARD};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        fl = QHBoxLayout(filters_frame)
        fl.setSpacing(10)

        # Status
        fl.addWidget(QLabel("Status:"))
        self.filter_status = QComboBox()
        self.filter_status.addItems(['Todos', 'pending', 'won', 'lost', 'void', 'cashout'])
        fl.addWidget(self.filter_status)

        # Liga
        fl.addWidget(QLabel("Liga:"))
        self.filter_league = QComboBox()
        self.filter_league.addItem('Todas')
        fl.addWidget(self.filter_league)

        # Tipo apuesta
        fl.addWidget(QLabel("Tipo:"))
        self.filter_type = QComboBox()
        self.filter_type.addItems(['Todos', '1X2', 'O/U', 'BTTS', 'Handicap', 'Marcador', 'Otro'])
        fl.addWidget(self.filter_type)

        # Bookmaker
        fl.addWidget(QLabel("Casa:"))
        self.filter_bookmaker = QComboBox()
        self.filter_bookmaker.addItem('Todos')
        fl.addWidget(self.filter_bookmaker)

        fl.addStretch()

        # Fechas
        fl.addWidget(QLabel("Desde:"))
        self.filter_date_from = QDateEdit()
        self.filter_date_from.setCalendarPopup(True)
        self.filter_date_from.setDate(QDate.currentDate().addMonths(-3))
        self.filter_date_from.setDisplayFormat("dd/MM/yyyy")
        fl.addWidget(self.filter_date_from)

        fl.addWidget(QLabel("Hasta:"))
        self.filter_date_to = QDateEdit()
        self.filter_date_to.setCalendarPopup(True)
        self.filter_date_to.setDate(QDate.currentDate().addDays(7))
        self.filter_date_to.setDisplayFormat("dd/MM/yyyy")
        fl.addWidget(self.filter_date_to)

        # Boton filtrar
        self.btn_filter = QPushButton("Filtrar")
        self.btn_filter.setStyleSheet(f"""
            QPushButton {{
                background: {C.ACCENT}; color: white; border: none;
                padding: 6px 16px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #E55A2B; }}
        """)
        fl.addWidget(self.btn_filter)

        self.btn_clear_filters = QPushButton("Limpiar")
        self.btn_clear_filters.setStyleSheet(f"""
            QPushButton {{
                background: {C.TEXT2}; color: white; border: none;
                padding: 6px 12px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #5A6268; }}
        """)
        fl.addWidget(self.btn_clear_filters)

        parent_layout.addWidget(filters_frame)

    def _build_tickets_table(self, parent_layout):
        self.tickets_table = QTableWidget()
        self.tickets_table.setColumnCount(12)
        self.tickets_table.setHorizontalHeaderLabels([
            'ID', 'Fecha', 'Liga', 'Partido', 'Tipo', 'Seleccion',
            'Cuota', 'Casa', 'Monto', 'P/L', 'Status', 'ML Score'
        ])
        self.tickets_table.setAlternatingRowColors(True)
        self.tickets_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tickets_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tickets_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tickets_table.setSortingEnabled(True)

        header = self.tickets_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # ID
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)   # Fecha
        header.setSectionResizeMode(2, QHeaderView.Interactive)        # Liga
        header.setSectionResizeMode(3, QHeaderView.Stretch)            # Partido
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)   # Tipo
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)   # Seleccion
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)   # Cuota
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)   # Casa
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)   # Monto
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)   # P/L
        header.setSectionResizeMode(10, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(11, QHeaderView.ResizeToContents)  # ML

        self.tickets_table.verticalHeader().setDefaultSectionSize(32)
        self.tickets_table.verticalHeader().setVisible(False)

        parent_layout.addWidget(self.tickets_table, 1)

    def _build_table_actions(self, parent_layout):
        actions = QHBoxLayout()

        self.btn_duplicate = QPushButton("Duplicar Ticket")
        self.btn_duplicate.setStyleSheet(f"""
            QPushButton {{
                background: {C.CHART1}; color: white; border: none;
                padding: 6px 14px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #0056B3; }}
        """)
        actions.addWidget(self.btn_duplicate)

        self.btn_delete = QPushButton("Eliminar")
        self.btn_delete.setStyleSheet(f"""
            QPushButton {{
                background: {C.LOSS}; color: white; border: none;
                padding: 6px 14px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #A71D2A; }}
        """)
        actions.addWidget(self.btn_delete)

        self.btn_mark_won = QPushButton("Marcar Ganado")
        self.btn_mark_won.setStyleSheet(f"""
            QPushButton {{
                background: {C.WIN}; color: white; border: none;
                padding: 6px 14px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #1E7E34; }}
        """)
        actions.addWidget(self.btn_mark_won)

        self.btn_mark_lost = QPushButton("Marcar Perdido")
        self.btn_mark_lost.setStyleSheet(f"""
            QPushButton {{
                background: {C.LOSS}; color: white; border: none;
                padding: 6px 14px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #A71D2A; }}
        """)
        actions.addWidget(self.btn_mark_lost)

        self.btn_mark_void = QPushButton("Anular")
        self.btn_mark_void.setStyleSheet(f"""
            QPushButton {{
                background: {C.VOID}; color: {C.TEXT}; border: none;
                padding: 6px 14px; border-radius: 4px;
            }}
            QPushButton:hover {{ background: #E0A800; }}
        """)
        actions.addWidget(self.btn_mark_void)

        actions.addStretch()

        self.lbl_table_info = QLabel("0 tickets")
        self.lbl_table_info.setStyleSheet(f"color: {C.TEXT2}; font-size: 12px;")
        actions.addWidget(self.lbl_table_info)

        parent_layout.addLayout(actions)

    # =========================================================================
    # TAB 2: ESTADISTICAS
    # =========================================================================

    def _build_stats_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)

        # Boton refrescar graficos
        btn_refresh = QPushButton("Actualizar Graficos")
        btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: {C.ACCENT}; color: white; border: none;
                padding: 8px 20px; border-radius: 4px; font-size: 13px;
            }}
            QPushButton:hover {{ background: #E55A2B; }}
        """)
        btn_refresh.clicked.connect(self._update_all_charts)
        scroll_layout.addWidget(btn_refresh)

        # 1. Evolucion Bankroll (pyqtgraph)
        self._build_bankroll_chart(scroll_layout)

        # 2. ROI por tipo de apuesta (matplotlib)
        self._build_roi_by_type_chart(scroll_layout)

        # 3. Win rate por liga (matplotlib)
        self._build_winrate_by_league_chart(scroll_layout)

        # 4. Yield por rango de cuota (matplotlib)
        self._build_yield_chart(scroll_layout)

        # 5. ML Score vs resultado (matplotlib)
        self._build_ml_correlation_chart(scroll_layout)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def _build_bankroll_chart(self, parent_layout):
        group = QGroupBox("Evolucion del Bankroll")
        gl = QVBoxLayout(group)

        if HAS_PYQTGRAPH:
            self.bankroll_plot = pg.PlotWidget()
            self.bankroll_plot.setBackground('w')
            self.bankroll_plot.showGrid(x=True, y=True, alpha=0.3)
            self.bankroll_plot.setLabel('left', 'Profit Acumulado (S/.)')
            self.bankroll_plot.setLabel('bottom', 'Ticket #')
            self.bankroll_plot.setMouseEnabled(x=True, y=True)

            # Linea de cero
            zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('#999', width=1, style=Qt.DashLine))
            self.bankroll_plot.addItem(zero_line)

            self.bankroll_plot.setMinimumHeight(300)
            gl.addWidget(self.bankroll_plot)
        else:
            gl.addWidget(QLabel("pyqtgraph no disponible"))

        parent_layout.addWidget(group)

    def _build_roi_by_type_chart(self, parent_layout):
        group = QGroupBox("ROI por Tipo de Apuesta")
        gl = QVBoxLayout(group)

        if HAS_MATPLOTLIB:
            self.roi_fig = plt.Figure(figsize=(10, 4), dpi=100)
            self.roi_fig.patch.set_facecolor('white')
            self.roi_canvas = FigureCanvasQTAgg(self.roi_fig)
            self.roi_canvas.setMinimumHeight(280)
            gl.addWidget(self.roi_canvas)
        else:
            gl.addWidget(QLabel("matplotlib no disponible"))

        parent_layout.addWidget(group)

    def _build_winrate_by_league_chart(self, parent_layout):
        group = QGroupBox("Win Rate por Liga")
        gl = QVBoxLayout(group)

        if HAS_MATPLOTLIB:
            self.league_fig = plt.Figure(figsize=(10, 4), dpi=100)
            self.league_fig.patch.set_facecolor('white')
            self.league_canvas = FigureCanvasQTAgg(self.league_fig)
            self.league_canvas.setMinimumHeight(280)
            gl.addWidget(self.league_canvas)
        else:
            gl.addWidget(QLabel("matplotlib no disponible"))

        parent_layout.addWidget(group)

    def _build_yield_chart(self, parent_layout):
        group = QGroupBox("Yield por Rango de Cuota")
        gl = QVBoxLayout(group)

        if HAS_MATPLOTLIB:
            self.yield_fig = plt.Figure(figsize=(10, 4), dpi=100)
            self.yield_fig.patch.set_facecolor('white')
            self.yield_canvas = FigureCanvasQTAgg(self.yield_fig)
            self.yield_canvas.setMinimumHeight(280)
            gl.addWidget(self.yield_canvas)
        else:
            gl.addWidget(QLabel("matplotlib no disponible"))

        parent_layout.addWidget(group)

    def _build_ml_correlation_chart(self, parent_layout):
        group = QGroupBox("ML Score vs Resultado")
        gl = QVBoxLayout(group)

        if HAS_MATPLOTLIB:
            self.ml_fig = plt.Figure(figsize=(10, 4), dpi=100)
            self.ml_fig.patch.set_facecolor('white')
            self.ml_canvas = FigureCanvasQTAgg(self.ml_fig)
            self.ml_canvas.setMinimumHeight(280)
            gl.addWidget(self.ml_canvas)
        else:
            gl.addWidget(QLabel("matplotlib no disponible"))

        parent_layout.addWidget(group)

    # =========================================================================
    # SIGNALS
    # =========================================================================

    def _connect_signals(self):
        self.btn_resolve.clicked.connect(self._resolve_tickets)
        self.btn_export.clicked.connect(self._export_csv)
        self.btn_filter.clicked.connect(self._apply_filters)
        self.btn_clear_filters.clicked.connect(self._clear_filters)
        self.btn_duplicate.clicked.connect(self._duplicate_selected)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_mark_won.clicked.connect(lambda: self._mark_selected('won'))
        self.btn_mark_lost.clicked.connect(lambda: self._mark_selected('lost'))
        self.btn_mark_void.clicked.connect(lambda: self._mark_selected('void'))
        self.tabs.currentChanged.connect(self._on_tab_changed)

    # =========================================================================
    # DATA LOADING
    # =========================================================================

    def _refresh_all(self):
        """Refresca todo: dashboard, filtros, tabla."""
        self._populate_filter_combos()
        self._apply_filters()
        self._update_dashboard()

    def _populate_filter_combos(self):
        """Carga valores unicos en los combos de filtros."""
        # Ligas
        current_league = self.filter_league.currentText()
        self.filter_league.clear()
        self.filter_league.addItem('Todas')
        leagues = self.manager.get_unique_values('league_name')
        self.filter_league.addItems(leagues)
        idx = self.filter_league.findText(current_league)
        if idx >= 0:
            self.filter_league.setCurrentIndex(idx)

        # Bookmakers
        current_bm = self.filter_bookmaker.currentText()
        self.filter_bookmaker.clear()
        self.filter_bookmaker.addItem('Todos')
        bookmakers = self.manager.get_unique_values('bookmaker')
        self.filter_bookmaker.addItems(bookmakers)
        idx = self.filter_bookmaker.findText(current_bm)
        if idx >= 0:
            self.filter_bookmaker.setCurrentIndex(idx)

    def _update_dashboard(self):
        """Actualiza las tarjetas del dashboard."""
        summary = self.manager.get_summary()

        self.card_total.update_value(str(summary['total']))
        self.card_winrate.update_value(
            f"{summary['win_rate']:.1f}%",
            C.WIN if summary['win_rate'] >= 50 else C.LOSS
        )
        self.card_roi.update_value(
            f"{summary['roi']:+.1f}%",
            C.WIN if summary['roi'] >= 0 else C.LOSS
        )
        self.card_profit.update_value(
            f"S/.{summary['total_profit']:+.0f}",
            C.WIN if summary['total_profit'] >= 0 else C.LOSS
        )
        self.card_pending.update_value(str(summary['pending']), C.PENDING)

    def _apply_filters(self):
        """Aplica filtros y refresca la tabla."""
        status = self.filter_status.currentText()
        league = self.filter_league.currentText()
        bet_type = self.filter_type.currentText()
        bookmaker = self.filter_bookmaker.currentText()

        qd_from = self.filter_date_from.date()
        qd_to = self.filter_date_to.date()
        date_from = datetime(qd_from.year(), qd_from.month(), qd_from.day())
        date_to = datetime(qd_to.year(), qd_to.month(), qd_to.day(), 23, 59, 59)

        tickets = self.manager.get_filtered_tickets(
            status=status if status != 'Todos' else None,
            league_name=league if league != 'Todas' else None,
            bet_type=bet_type if bet_type != 'Todos' else None,
            bookmaker=bookmaker if bookmaker != 'Todos' else None,
            date_from=date_from,
            date_to=date_to,
        )

        self._current_tickets = tickets
        self._populate_table(tickets)

    def _clear_filters(self):
        """Limpia todos los filtros."""
        self.filter_status.setCurrentIndex(0)
        self.filter_league.setCurrentIndex(0)
        self.filter_type.setCurrentIndex(0)
        self.filter_bookmaker.setCurrentIndex(0)
        self.filter_date_from.setDate(QDate.currentDate().addMonths(-3))
        self.filter_date_to.setDate(QDate.currentDate().addDays(7))
        self._apply_filters()

    def _populate_table(self, tickets: list):
        """Llena la tabla con tickets."""
        self.tickets_table.setUpdatesEnabled(False)
        self.tickets_table.blockSignals(True)
        self.tickets_table.setSortingEnabled(False)
        self.tickets_table.setRowCount(len(tickets))

        status_colors = {
            'won': QColor(C.WIN),
            'lost': QColor(C.LOSS),
            'pending': QColor(C.PENDING),
            'void': QColor(C.VOID),
            'cashout': QColor('#6F42C1'),
        }
        status_icons = {
            'won': ' WON', 'lost': ' LOST', 'pending': ' PEND',
            'void': ' VOID', 'cashout': ' CASH',
        }

        for i, t in enumerate(tickets):
            # ID
            id_item = QTableWidgetItem(str(t.id))
            id_item.setTextAlignment(Qt.AlignCenter)
            id_item.setData(Qt.UserRole, t.id)  # Store ID for actions
            self.tickets_table.setItem(i, 0, id_item)

            # Fecha
            date_str = t.match_date.strftime('%d/%m %H:%M') if t.match_date else ''
            self.tickets_table.setItem(i, 1, QTableWidgetItem(date_str))

            # Liga (abreviada)
            league_str = (t.league_name or '')[:25]
            self.tickets_table.setItem(i, 2, QTableWidgetItem(league_str))

            # Partido
            match_str = f"{t.home_team_name} vs {t.away_team_name}"
            self.tickets_table.setItem(i, 3, QTableWidgetItem(match_str))

            # Tipo
            type_item = QTableWidgetItem(t.bet_type or '')
            type_item.setTextAlignment(Qt.AlignCenter)
            self.tickets_table.setItem(i, 4, type_item)

            # Seleccion
            self.tickets_table.setItem(i, 5, QTableWidgetItem(t.bet_selection or ''))

            # Cuota
            odds_item = QTableWidgetItem(f"{t.odds:.2f}")
            odds_item.setTextAlignment(Qt.AlignCenter)
            self.tickets_table.setItem(i, 6, odds_item)

            # Casa
            bm_item = QTableWidgetItem(t.bookmaker or '')
            bm_item.setTextAlignment(Qt.AlignCenter)
            self.tickets_table.setItem(i, 7, bm_item)

            # Monto
            stake_item = QTableWidgetItem(f"S/.{t.stake:.0f}")
            stake_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tickets_table.setItem(i, 8, stake_item)

            # P/L
            if t.profit_loss is not None and t.status in ('won', 'lost'):
                pl_str = f"{t.profit_loss:+.0f}"
                pl_item = QTableWidgetItem(pl_str)
                pl_color = QColor(C.WIN) if t.profit_loss >= 0 else QColor(C.LOSS)
                pl_item.setForeground(pl_color)
            else:
                pl_item = QTableWidgetItem('---')
                pl_item.setForeground(QColor(C.TEXT2))
            pl_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tickets_table.setItem(i, 9, pl_item)

            # Status
            st_text = status_icons.get(t.status, t.status)
            st_item = QTableWidgetItem(st_text)
            st_item.setTextAlignment(Qt.AlignCenter)
            st_color = status_colors.get(t.status, QColor(C.TEXT2))
            st_item.setForeground(st_color)
            font = QFont()
            font.setBold(True)
            st_item.setFont(font)
            self.tickets_table.setItem(i, 10, st_item)

            # ML Score
            ml_str = f"{t.ml_score:.2f}" if t.ml_score is not None else '-'
            ml_item = QTableWidgetItem(ml_str)
            ml_item.setTextAlignment(Qt.AlignCenter)
            self.tickets_table.setItem(i, 11, ml_item)

        self.tickets_table.setSortingEnabled(True)
        self.tickets_table.blockSignals(False)
        self.tickets_table.setUpdatesEnabled(True)

        self.lbl_table_info.setText(f"{len(tickets)} tickets mostrados")

    # =========================================================================
    # ACTIONS
    # =========================================================================

    def _get_selected_ticket_id(self) -> Optional[int]:
        """Obtiene el ID del ticket seleccionado."""
        row = self.tickets_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Info", "Selecciona un ticket primero.")
            return None
        item = self.tickets_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _auto_resolve_on_open(self):
        """Resolucion automatica al abrir."""
        try:
            stats = self.manager.resolve_pending_tickets()
            if stats['resolved'] > 0:
                logger.info(
                    f"Auto-resolucion: {stats['resolved']} tickets "
                    f"({stats['won']} won, {stats['lost']} lost)"
                )
        except Exception as e:
            logger.error(f"Error en auto-resolucion: {e}")

    def _resolve_tickets(self):
        """Resolucion manual de tickets pendientes."""
        try:
            stats = self.manager.resolve_pending_tickets()
            self._refresh_all()

            if stats['resolved'] == 0:
                QMessageBox.information(
                    self, "Resolucion",
                    "No hay tickets pendientes para resolver.\n"
                    "Los partidos deben haber terminado (FT/AET/PEN)."
                )
            else:
                QMessageBox.information(
                    self, "Resolucion completada",
                    f"Resueltos: {stats['resolved']} tickets\n"
                    f"  Ganados: {stats['won']}\n"
                    f"  Perdidos: {stats['lost']}\n"
                    f"  Errores: {stats['errors']}"
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error resolviendo tickets:\n{e}")

    def _duplicate_selected(self):
        """Duplica el ticket seleccionado."""
        ticket_id = self._get_selected_ticket_id()
        if ticket_id is None:
            return

        new_ticket = self.manager.duplicate_ticket(ticket_id)
        if new_ticket:
            QMessageBox.information(
                self, "Duplicado",
                f"Ticket #{ticket_id} duplicado como #{new_ticket.id}\n"
                f"Status: pending (editable)"
            )
            self._refresh_all()
        else:
            QMessageBox.warning(self, "Error", "No se pudo duplicar el ticket.")

    def _delete_selected(self):
        """Elimina el ticket seleccionado."""
        ticket_id = self._get_selected_ticket_id()
        if ticket_id is None:
            return

        reply = QMessageBox.question(
            self, "Confirmar",
            f"Eliminar ticket #{ticket_id}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.manager.delete_ticket(ticket_id):
                self._refresh_all()
            else:
                QMessageBox.warning(self, "Error", "No se pudo eliminar.")

    def _mark_selected(self, status: str):
        """Marca el ticket seleccionado con un status manual."""
        ticket_id = self._get_selected_ticket_id()
        if ticket_id is None:
            return

        if self.manager.update_ticket_status(ticket_id, status):
            self._refresh_all()
        else:
            QMessageBox.warning(self, "Error", "No se pudo actualizar el status.")

    def _export_csv(self):
        """Exporta los tickets filtrados actuales a CSV."""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Exportar CSV",
            f"tickets_{datetime.now().strftime('%Y%m%d')}.csv",
            "CSV (*.csv)"
        )
        if filepath:
            if self.manager.export_to_csv(filepath, self._current_tickets):
                QMessageBox.information(
                    self, "Exportado",
                    f"Exportados {len(self._current_tickets)} tickets a:\n{filepath}"
                )
            else:
                QMessageBox.warning(self, "Error", "Error al exportar.")

    def _on_tab_changed(self, index: int):
        """Actualiza graficos al cambiar al tab de estadisticas."""
        if index == 1:
            self._update_all_charts()

    # =========================================================================
    # CHARTS
    # =========================================================================

    def _update_all_charts(self):
        """Actualiza todos los graficos."""
        self._update_bankroll_chart()
        self._update_roi_chart()
        self._update_league_chart()
        self._update_yield_chart()
        self._update_ml_chart()

    def _update_bankroll_chart(self):
        """Grafico de evolucion del bankroll (pyqtgraph)."""
        if not HAS_PYQTGRAPH:
            return

        evolution = self.manager.get_bankroll_evolution()
        self.bankroll_plot.clear()

        # Re-agregar linea de cero
        zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('#999', width=1, style=Qt.DashLine))
        self.bankroll_plot.addItem(zero_line)

        if not evolution:
            return

        x = list(range(len(evolution)))
        y = [e['cumulative'] for e in evolution]

        # Color segun profit positivo/negativo
        pen_color = C.WIN if y[-1] >= 0 else C.LOSS
        pen = pg.mkPen(pen_color, width=2.5)

        self.bankroll_plot.plot(x, y, pen=pen, symbol='o', symbolSize=5,
                                symbolBrush=pg.mkBrush(pen_color))

        # Area rellena
        fill = pg.FillBetweenItem(
            pg.PlotDataItem(x, y),
            pg.PlotDataItem(x, [0] * len(x)),
            brush=pg.mkBrush(pen_color + '30')  # 30 = alpha hex
        )
        self.bankroll_plot.addItem(fill)

        # Tooltips via scatter
        self.bankroll_plot.setTitle(
            f"Profit acumulado: S/.{y[-1]:+.0f}",
            color=pen_color, size='12pt'
        )

    def _update_roi_chart(self):
        """ROI por tipo de apuesta (matplotlib)."""
        if not HAS_MATPLOTLIB:
            return

        data = self.manager.get_roi_by_bet_type()
        self.roi_fig.clear()

        if not data:
            ax = self.roi_fig.add_subplot(111)
            ax.text(0.5, 0.5, 'Sin datos resueltos', ha='center', va='center',
                    fontsize=14, color='#999')
            ax.set_axis_off()
            self.roi_canvas.draw()
            return

        ax1 = self.roi_fig.add_subplot(121)
        ax2 = self.roi_fig.add_subplot(122)

        labels = list(data.keys())
        rois = [data[k]['roi'] for k in labels]
        win_rates = [data[k]['win_rate'] for k in labels]
        totals = [data[k]['total'] for k in labels]

        colors_roi = [C.WIN if r >= 0 else C.LOSS for r in rois]
        colors_wr = [C.WIN if w >= 50 else C.LOSS for w in win_rates]

        # ROI bars
        bars1 = ax1.bar(labels, rois, color=colors_roi, alpha=0.85, edgecolor='white')
        ax1.set_title('ROI (%)', fontweight='bold', fontsize=11)
        ax1.axhline(y=0, color='#999', linewidth=0.8, linestyle='--')
        ax1.set_ylabel('ROI %')
        for bar, val, n in zip(bars1, rois, totals):
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:+.1f}%\n(n={n})', ha='center', va='bottom', fontsize=9)

        # Win rate bars
        bars2 = ax2.bar(labels, win_rates, color=colors_wr, alpha=0.85, edgecolor='white')
        ax2.set_title('Win Rate (%)', fontweight='bold', fontsize=11)
        ax2.axhline(y=50, color='#999', linewidth=0.8, linestyle='--')
        ax2.set_ylabel('Win %')
        ax2.set_ylim(0, 100)
        for bar, val in zip(bars2, win_rates):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:.0f}%', ha='center', va='bottom', fontsize=9)

        self.roi_fig.tight_layout()
        self.roi_canvas.draw()

    def _update_league_chart(self):
        """Win rate por liga (matplotlib)."""
        if not HAS_MATPLOTLIB:
            return

        data = self.manager.get_win_rate_by_league()
        self.league_fig.clear()

        if not data:
            ax = self.league_fig.add_subplot(111)
            ax.text(0.5, 0.5, 'Sin datos resueltos', ha='center', va='center',
                    fontsize=14, color='#999')
            ax.set_axis_off()
            self.league_canvas.draw()
            return

        # Ordenar por win rate descendente
        sorted_data = sorted(data.items(), key=lambda x: x[1]['win_rate'], reverse=True)
        labels = [k[:20] for k, v in sorted_data]  # Truncar nombres largos
        win_rates = [v['win_rate'] for k, v in sorted_data]
        rois = [v['roi'] for k, v in sorted_data]
        totals = [v['total'] for k, v in sorted_data]

        ax = self.league_fig.add_subplot(111)

        colors = [C.WIN if w >= 50 else C.LOSS for w in win_rates]
        bars = ax.barh(labels, win_rates, color=colors, alpha=0.85, edgecolor='white')
        ax.axvline(x=50, color='#999', linewidth=0.8, linestyle='--')
        ax.set_xlabel('Win Rate %')
        ax.set_title('Win Rate por Liga', fontweight='bold', fontsize=11)
        ax.set_xlim(0, 100)
        ax.invert_yaxis()

        for bar, wr, roi, n in zip(bars, win_rates, rois, totals):
            ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                    f'{wr:.0f}% | ROI:{roi:+.0f}% (n={n})',
                    va='center', fontsize=9)

        self.league_fig.tight_layout()
        self.league_canvas.draw()

    def _update_yield_chart(self):
        """Yield por rango de cuota (matplotlib)."""
        if not HAS_MATPLOTLIB:
            return

        data = self.manager.get_yield_by_odds_range()
        self.yield_fig.clear()

        if not data:
            ax = self.yield_fig.add_subplot(111)
            ax.text(0.5, 0.5, 'Sin datos resueltos', ha='center', va='center',
                    fontsize=14, color='#999')
            ax.set_axis_off()
            self.yield_canvas.draw()
            return

        ax1 = self.yield_fig.add_subplot(121)
        ax2 = self.yield_fig.add_subplot(122)

        labels = list(data.keys())
        yields = [data[k]['yield_pct'] for k in labels]
        win_rates = [data[k]['win_rate'] for k in labels]
        totals = [data[k]['total'] for k in labels]

        colors_y = [C.WIN if y >= 0 else C.LOSS for y in yields]
        colors_w = [C.WIN if w >= 50 else C.LOSS for w in win_rates]

        bars1 = ax1.bar(labels, yields, color=colors_y, alpha=0.85, edgecolor='white')
        ax1.set_title('Yield (%)', fontweight='bold', fontsize=11)
        ax1.axhline(y=0, color='#999', linewidth=0.8, linestyle='--')
        ax1.set_ylabel('Yield %')
        ax1.tick_params(axis='x', rotation=30)
        for bar, val, n in zip(bars1, yields, totals):
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:+.1f}%\n(n={n})', ha='center', va='bottom', fontsize=8)

        bars2 = ax2.bar(labels, win_rates, color=colors_w, alpha=0.85, edgecolor='white')
        ax2.set_title('Win Rate por Rango', fontweight='bold', fontsize=11)
        ax2.axhline(y=50, color='#999', linewidth=0.8, linestyle='--')
        ax2.set_ylabel('Win %')
        ax2.set_ylim(0, 100)
        ax2.tick_params(axis='x', rotation=30)
        for bar, val in zip(bars2, win_rates):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:.0f}%', ha='center', va='bottom', fontsize=9)

        self.yield_fig.tight_layout()
        self.yield_canvas.draw()

    def _update_ml_chart(self):
        """Correlacion ML Score vs resultado (matplotlib)."""
        if not HAS_MATPLOTLIB:
            return

        data = self.manager.get_ml_score_correlation()
        self.ml_fig.clear()

        if not data:
            ax = self.ml_fig.add_subplot(111)
            ax.text(0.5, 0.5, 'Sin tickets con ML Score resueltos',
                    ha='center', va='center', fontsize=14, color='#999')
            ax.set_axis_off()
            self.ml_canvas.draw()
            return

        ax1 = self.ml_fig.add_subplot(121)
        ax2 = self.ml_fig.add_subplot(122)

        scores = [d['ml_score'] for d in data]
        won = [d['won'] for d in data]

        # Scatter: ML score vs won/lost
        colors = [C.WIN if w else C.LOSS for w in won]
        ax1.scatter(scores, won, c=colors, alpha=0.6, s=40, edgecolors='white', linewidth=0.5)
        ax1.set_xlabel('ML Score')
        ax1.set_ylabel('Resultado (1=Won, 0=Lost)')
        ax1.set_title('ML Score vs Resultado', fontweight='bold', fontsize=11)
        ax1.set_yticks([0, 1])
        ax1.set_yticklabels(['Lost', 'Won'])

        # Win rate por decil de ML score
        import numpy as np
        scores_arr = np.array(scores)
        won_arr = np.array(won)

        if len(scores_arr) >= 5:
            try:
                # Crear bins equidistantes
                bins = np.linspace(scores_arr.min(), scores_arr.max(), 6)
                bin_labels = [f'{bins[i]:.2f}-{bins[i+1]:.2f}' for i in range(len(bins)-1)]
                digitized = np.digitize(scores_arr, bins[1:-1])

                bin_wr = []
                bin_counts = []
                for b in range(len(bin_labels)):
                    mask = (digitized == b)
                    if mask.sum() > 0:
                        bin_wr.append(won_arr[mask].mean() * 100)
                        bin_counts.append(mask.sum())
                    else:
                        bin_wr.append(0)
                        bin_counts.append(0)

                colors_wr = [C.WIN if w >= 50 else C.LOSS for w in bin_wr]
                bars = ax2.bar(bin_labels, bin_wr, color=colors_wr, alpha=0.85, edgecolor='white')
                ax2.axhline(y=50, color='#999', linewidth=0.8, linestyle='--')
                ax2.set_xlabel('ML Score Range')
                ax2.set_ylabel('Win Rate %')
                ax2.set_title('Win Rate por Rango ML', fontweight='bold', fontsize=11)
                ax2.set_ylim(0, 100)
                ax2.tick_params(axis='x', rotation=30)
                for bar, val, n in zip(bars, bin_wr, bin_counts):
                    ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                             f'{val:.0f}%\n(n={n})', ha='center', va='bottom', fontsize=8)
            except Exception as e:
                ax2.text(0.5, 0.5, f'Error: {e}', ha='center', va='center', fontsize=10)
                ax2.set_axis_off()
        else:
            ax2.text(0.5, 0.5, 'Pocos datos para binning', ha='center', va='center',
                     fontsize=12, color='#999')
            ax2.set_axis_off()

        self.ml_fig.tight_layout()
        self.ml_canvas.draw()