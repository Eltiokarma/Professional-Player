# ui/odds_viewer/main_window.py
# -*- coding: utf-8 -*-
"""
Ventana principal del sistema de visualización de Odds y Simulador del Hincha.
"""

import os
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QStatusBar, QLabel, QMessageBox,
    QFileDialog, QMenuBar, QMenu
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QIcon

from .styles.colors import Colors, Styles
from .models.database_queries import OddsQueryModel
from .tabs.odds_tab import OddsTab
from .tabs.dashboard_tab import DashboardTab
from .tabs.simulator_tab import SimulatorTab
from .tabs.history_chart_tab import HistoryChartTab

logger = logging.getLogger(__name__)


class OddsViewerWindow(QMainWindow):
    """
    Ventana principal del sistema de Odds y Simulador del Hincha.
    
    Integra tres módulos:
    - Visor de Cuotas: Visualización estilo casa de apuestas
    - Dashboard: Análisis de cobertura de datos
    - Simulador: Simulación de apuestas del hincha
    """
    
    def __init__(self, db_path: str = None, parent=None):
        super().__init__(parent)
        
        self.db_model: Optional[OddsQueryModel] = None
        self.db_path = db_path
        
        self._setup_window()
        self._setup_menubar()
        self._setup_ui()
        self._setup_statusbar()
        
        # Conectar a BD si se proporcionó path
        if db_path and os.path.exists(db_path):
            self._connect_database(db_path)
        else:
            self._try_auto_connect()
    
    def _setup_window(self):
        """Configura la ventana principal."""
        self.setWindowTitle("🎰 Odds Viewer & Simulador del Hincha")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # Estilo global
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {Colors.BACKGROUND};
            }}
            QTabWidget::pane {{
                border: none;
                background-color: {Colors.BACKGROUND};
            }}
            QTabBar::tab {{
                background-color: {Colors.CARD};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                padding: 12px 25px;
                margin-right: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }}
            QTabBar::tab:selected {{
                background-color: {Colors.PRIMARY};
                color: {Colors.TEXT_LIGHT};
                border-color: {Colors.PRIMARY};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {Colors.CARD_HOVER};
            }}
        """)
    
    def _setup_menubar(self):
        """Configura la barra de menú."""
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{
                background-color: {Colors.PRIMARY};
                color: {Colors.TEXT_LIGHT};
                padding: 5px;
            }}
            QMenuBar::item {{
                padding: 8px 15px;
                border-radius: 4px;
            }}
            QMenuBar::item:selected {{
                background-color: {Colors.SECONDARY};
            }}
            QMenu {{
                background-color: {Colors.CARD};
                border: 1px solid {Colors.BORDER};
            }}
            QMenu::item {{
                padding: 8px 25px;
            }}
            QMenu::item:selected {{
                background-color: {Colors.ACCENT};
                color: {Colors.TEXT_LIGHT};
            }}
        """)
        
        # Menú Archivo
        file_menu = menubar.addMenu("📁 Archivo")
        
        action_open = QAction("📂 Abrir Base de Datos...", self)
        action_open.setShortcut("Ctrl+O")
        action_open.triggered.connect(self._open_database)
        file_menu.addAction(action_open)
        
        action_refresh = QAction("🔄 Recargar Datos", self)
        action_refresh.setShortcut("F5")
        action_refresh.triggered.connect(self._refresh_data)
        file_menu.addAction(action_refresh)
        
        file_menu.addSeparator()
        
        action_close = QAction("❌ Cerrar", self)
        action_close.setShortcut("Ctrl+W")
        action_close.triggered.connect(self.close)
        file_menu.addAction(action_close)
        
        # Menú Ver
        view_menu = menubar.addMenu("👁️ Ver")
        
        action_odds = QAction("🏆 Visor de Cuotas", self)
        action_odds.setShortcut("Ctrl+1")
        action_odds.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        view_menu.addAction(action_odds)
        
        action_dashboard = QAction("📊 Dashboard", self)
        action_dashboard.setShortcut("Ctrl+2")
        action_dashboard.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        view_menu.addAction(action_dashboard)
        
        action_simulator = QAction("🎰 Simulador", self)
        action_simulator.setShortcut("Ctrl+3")
        action_simulator.triggered.connect(lambda: self.tabs.setCurrentIndex(2))
        view_menu.addAction(action_simulator)
        
        action_history = QAction("📈 Gráficos Históricos", self)
        action_history.setShortcut("Ctrl+4")
        action_history.triggered.connect(lambda: self.tabs.setCurrentIndex(3))
        view_menu.addAction(action_history)
        
        # Menú Ayuda
        help_menu = menubar.addMenu("❓ Ayuda")
        
        action_about = QAction("ℹ️ Acerca de...", self)
        action_about.triggered.connect(self._show_about)
        help_menu.addAction(action_about)
        
        action_shortcuts = QAction("⌨️ Atajos de Teclado", self)
        action_shortcuts.triggered.connect(self._show_shortcuts)
        help_menu.addAction(action_shortcuts)
    
    def _setup_ui(self):
        """Construye la interfaz principal."""
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Tabs principales
        self.tabs = QTabWidget()
        
        # Placeholder para tabs (se cargan cuando hay conexión a BD)
        self.odds_tab = None
        self.dashboard_tab = None
        self.simulator_tab = None
        self.history_tab = None
        
        # Tab de bienvenida (cuando no hay BD conectada)
        self.welcome_tab = self._create_welcome_tab()
        self.tabs.addTab(self.welcome_tab, "🏠 Inicio")
        
        layout.addWidget(self.tabs)
    
    def _create_welcome_tab(self) -> QWidget:
        """Crea el tab de bienvenida."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        
        # Logo/Título
        title = QLabel("🎰 ODDS VIEWER")
        title.setStyleSheet(f"""
            color: {Colors.PRIMARY};
            font-size: 48px;
            font-weight: bold;
        """)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel("Sistema de Visualización de Cuotas y Simulador del Hincha")
        subtitle.setStyleSheet(f"""
            color: {Colors.TEXT_SECONDARY};
            font-size: 18px;
        """)
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(40)
        
        # Estado de conexión
        self.lbl_connection = QLabel("⚠️ No hay base de datos conectada")
        self.lbl_connection.setStyleSheet(f"""
            color: {Colors.CHART_TERTIARY};
            font-size: 16px;
            padding: 20px;
            background-color: {Colors.CARD};
            border-radius: 10px;
        """)
        self.lbl_connection.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_connection)
        
        layout.addSpacing(20)
        
        # Instrucciones
        instructions = QLabel("""
            <h3>Para comenzar:</h3>
            <ol>
                <li>Ve a <b>Archivo → Abrir Base de Datos</b> (Ctrl+O)</li>
                <li>Selecciona tu archivo <code>sad.db</code></li>
                <li>¡Explora tus datos y simula apuestas!</li>
            </ol>
            <br>
            <h3>Características:</h3>
            <ul>
                <li><b>🏆 Visor de Cuotas</b>: Visualiza partidos estilo casa de apuestas</li>
                <li><b>📊 Dashboard</b>: Analiza la cobertura de tus datos</li>
                <li><b>🎰 Simulador</b>: Simula apuestas siguiendo a tu equipo</li>
            </ul>
        """)
        instructions.setStyleSheet(f"""
            color: {Colors.TEXT_PRIMARY};
            font-size: 14px;
            padding: 30px;
            background-color: {Colors.CARD};
            border-radius: 10px;
        """)
        instructions.setAlignment(Qt.AlignLeft)
        layout.addWidget(instructions)
        
        layout.addStretch()
        
        return widget
    
    def _setup_statusbar(self):
        """Configura la barra de estado."""
        self.statusbar = QStatusBar()
        self.statusbar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {Colors.PRIMARY};
                color: {Colors.TEXT_LIGHT};
                padding: 5px;
            }}
        """)
        self.setStatusBar(self.statusbar)
        
        # Labels de estado
        self.lbl_db_status = QLabel("💾 Sin conexión")
        self.statusbar.addWidget(self.lbl_db_status)
        
        self.statusbar.addPermanentWidget(QLabel(""))  # Spacer
        
        self.lbl_info = QLabel("")
        self.statusbar.addPermanentWidget(self.lbl_info)
    
    def _try_auto_connect(self):
        """Intenta conectar automáticamente a una BD."""
        # Buscar sad.db en ubicaciones comunes
        possible_paths = [
            "../../sad.db",
            "../sad.db",
            "sad.db",
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "sad.db"),
        ]
        
        for path in possible_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                logger.info(f"Base de datos encontrada: {abs_path}")
                self._connect_database(abs_path)
                return
        
        logger.info("No se encontró base de datos automáticamente")
    
    def _open_database(self):
        """Abre diálogo para seleccionar base de datos."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Base de Datos",
            "",
            "SQLite Database (*.db *.sqlite *.sqlite3);;All Files (*)"
        )
        
        if path:
            self._connect_database(path)
    
    def _connect_database(self, path: str):
        """Conecta a una base de datos."""
        try:
            # Cerrar conexión anterior si existe
            if self.db_model:
                self.db_model.close()
            
            # Crear nuevo modelo
            self.db_model = OddsQueryModel(path)
            self.db_path = path
            
            # Actualizar UI
            self._update_connection_status(True, path)
            self._load_tabs()
            
            logger.info(f"Conectado a: {path}")
            
        except Exception as e:
            logger.error(f"Error conectando a BD: {e}")
            QMessageBox.critical(
                self,
                "Error de Conexión",
                f"No se pudo conectar a la base de datos:\n{str(e)}"
            )
            self._update_connection_status(False)
    
    def _update_connection_status(self, connected: bool, path: str = ""):
        """Actualiza indicadores de conexión."""
        if connected:
            db_name = os.path.basename(path)
            self.lbl_db_status.setText(f"💾 Conectado: {db_name}")
            self.lbl_connection.setText(f"✅ Conectado a: {path}")
            self.lbl_connection.setStyleSheet(f"""
                color: {Colors.WIN};
                font-size: 16px;
                padding: 20px;
                background-color: {Colors.CARD};
                border-radius: 10px;
            """)
        else:
            self.lbl_db_status.setText("💾 Sin conexión")
            self.lbl_connection.setText("⚠️ No hay base de datos conectada")
            self.lbl_connection.setStyleSheet(f"""
                color: {Colors.CHART_TERTIARY};
                font-size: 16px;
                padding: 20px;
                background-color: {Colors.CARD};
                border-radius: 10px;
            """)
    
    def _load_tabs(self):
        """Carga los tabs con datos de la BD."""
        if not self.db_model:
            return
        
        try:
            # Remover TODOS los tabs existentes
            while self.tabs.count() > 0:
                self.tabs.removeTab(0)
            
            # Crear y agregar TODOS los tabs
            logger.info("Creando tabs...")
            
            self.odds_tab = OddsTab(self.db_model)
            self.tabs.addTab(self.odds_tab, "🏆 Visor de Cuotas")
            logger.info("Tab 1: Visor de Cuotas - OK")
            
            self.dashboard_tab = DashboardTab(self.db_model)
            self.tabs.addTab(self.dashboard_tab, "📊 Dashboard")
            logger.info("Tab 2: Dashboard - OK")
            
            self.simulator_tab = SimulatorTab(self.db_model)
            self.tabs.addTab(self.simulator_tab, "🎰 Simulador")
            logger.info("Tab 3: Simulador - OK")
            
            self.history_tab = HistoryChartTab(self.db_model)
            self.tabs.addTab(self.history_tab, "📊 Cobertura")
            logger.info("Tab 4: Cobertura - OK")
            
            # Seleccionar primer tab
            self.tabs.setCurrentIndex(0)
            
            # Actualizar info
            stats = self.db_model.get_global_stats()
            self.lbl_info.setText(
                f"📊 {stats.get('total_fixtures', 0):,} partidos | "
                f"🎰 {stats.get('fixtures_with_odds', 0):,} con odds"
            )
            
            logger.info(f"Total tabs cargados: {self.tabs.count()}")
            
        except Exception as e:
            logger.error(f"Error cargando tabs: {e}")
            import traceback
            traceback.print_exc()
    
    def _refresh_data(self):
        """Recarga datos de la BD."""
        if self.db_path:
            self._connect_database(self.db_path)
    
    def _show_about(self):
        """Muestra diálogo Acerca de."""
        QMessageBox.about(
            self,
            "Acerca de Odds Viewer",
            """
            <h2>🎰 Odds Viewer & Simulador del Hincha</h2>
            <p>Version 1.0.0</p>
            <br>
            <p>Sistema de visualización de cuotas de apuestas deportivas
            y simulador de rentabilidad para el hincha.</p>
            <br>
            <h3>Características:</h3>
            <ul>
                <li>Visualización de cuotas estilo casa de apuestas</li>
                <li>Dashboard de análisis de cobertura de datos</li>
                <li>Simulador de apuestas sistemáticas</li>
                <li>Ranking de rentabilidad por equipo</li>
                <li>Análisis de tendencias e insights</li>
            </ul>
            <br>
            <p>Desarrollado con ❤️ usando PySide6</p>
            """
        )
    
    def _show_shortcuts(self):
        """Muestra atajos de teclado."""
        QMessageBox.information(
            self,
            "Atajos de Teclado",
            """
            <h3>⌨️ Atajos de Teclado</h3>
            <br>
            <table>
                <tr><td><b>Ctrl+O</b></td><td>Abrir base de datos</td></tr>
                <tr><td><b>F5</b></td><td>Recargar datos</td></tr>
                <tr><td><b>Ctrl+1</b></td><td>Ir a Visor de Cuotas</td></tr>
                <tr><td><b>Ctrl+2</b></td><td>Ir a Dashboard</td></tr>
                <tr><td><b>Ctrl+3</b></td><td>Ir a Simulador</td></tr>
                <tr><td><b>Ctrl+W</b></td><td>Cerrar ventana</td></tr>
            </table>
            """
        )
    
    def closeEvent(self, event):
        """Cierra conexiones al cerrar la ventana."""
        if self.db_model:
            self.db_model.close()
        event.accept()
