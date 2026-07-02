# src/updated_main.py
# -*- coding: utf-8 -*-
"""
🏆 SOFTWARE DE ANÁLISIS DEPORTIVO - VERSION OPTIMIZADA
======================================================
Incluye: Anticulebras, Extraccion, Gestion BD, Analisis, Odds Viewer, Ley del Marcador, Tickets, Regresion al Nivel, Fe Perdida
"""
import sys
import os
import logging

# ============================================================
# 🔧 CONFIGURACIÓN DE LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)

logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.info("🚀 Iniciando aplicacion...")

# Agregar el directorio src al path de Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel, QHBoxLayout,
    QFrame, QGridLayout, QMessageBox, QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor


class MainMenuButton(QPushButton):
    """Boton estilizado para el menu principal con efectos."""
    
    def __init__(self, icon: str, title: str, description: str, 
                 color: str, parent=None):
        super().__init__(parent)
        self.base_color = color
        self.setMinimumSize(280, 130)
        self.setCursor(Qt.PointingHandCursor)
        
        self._apply_style(color)
        self._add_shadow()
        
        # Layout interno
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 15, 20, 15)
        
        # Icono y titulo
        header = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 36px; background: transparent;")
        header.addWidget(icon_label)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            background: transparent;
        """)
        header.addWidget(title_label)
        header.addStretch()
        
        layout.addLayout(header)
        
        # Descripcion
        desc_label = QLabel(description)
        desc_label.setStyleSheet("""
            font-size: 12px; 
            color: rgba(255,255,255,0.85);
            background: transparent;
        """)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        layout.addStretch()
    
    def _apply_style(self, color: str):
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {color}, 
                    stop:1 {self._darken(color, 0.15)}
                );
                border: none;
                border-radius: 15px;
                text-align: left;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self._lighten(color, 0.1)}, 
                    stop:1 {color}
                );
            }}
            QPushButton:pressed {{
                background: {self._darken(color, 0.2)};
            }}
        """)
    
    def _add_shadow(self):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)
    
    def _darken(self, hex_color: str, factor: float = 0.1) -> str:
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        darkened = tuple(max(0, int(c * (1 - factor))) for c in rgb)
        return '#' + ''.join(f'{c:02x}' for c in darkened)
    
    def _lighten(self, hex_color: str, factor: float = 0.1) -> str:
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        lightened = tuple(min(255, int(c + (255 - c) * factor)) for c in rgb)
        return '#' + ''.join(f'{c:02x}' for c in lightened)


class UpdatedMainWindow(QMainWindow):
    """Ventana principal con todas las funcionalidades."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("\u26bd SOFTWARE DE ANALISIS DEPORTIVO")
        self.resize(950, 850)
        self.setMinimumSize(800, 700)
        
        # Referencias a ventanas
        self.extraction_window = None
        self.anticulebra_window = None
        self.odds_window = None
        self.db_viewer_window = None
        self.marcador_window = None
        self.pre_match_window = None
        self.exporter_dialog = None
        self.tickets_viewer_window = None
        self.regresion_nivel_window = None
        self.fe_perdida_window = None
        
        self._build_ui()
        self._center_window()
    
    def _center_window(self):
        """Centra la ventana en la pantalla."""
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
    
    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(50, 40, 50, 30)
        layout.setSpacing(25)
        
        # ═══════════════════════════════════════════════════════════
        # HEADER
        # ═══════════════════════════════════════════════════════════
        header = QVBoxLayout()
        header.setSpacing(8)
        
        title = QLabel("\u26bd SOFTWARE DE ANALISIS DEPORTIVO")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 34px;
            font-weight: bold;
            color: #1a1a2e;
            letter-spacing: 1px;
        """)
        header.addWidget(title)
        
        subtitle = QLabel("Sistema integral de prediccion y analisis de apuestas deportivas")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 14px; color: #666; margin-bottom: 10px;")
        header.addWidget(subtitle)
        
        # Linea decorativa
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #FF6B35; max-height: 3px; border-radius: 1px;")
        line.setFixedHeight(3)
        header.addWidget(line)
        
        layout.addLayout(header)
        
        # ═══════════════════════════════════════════════════════════
        # GRID DE BOTONES
        # ═══════════════════════════════════════════════════════════
        grid = QGridLayout()
        grid.setSpacing(20)
        grid.setContentsMargins(0, 10, 0, 10)
        
        # Fila 1
        btn_anticulebra = MainMenuButton(
            "\U0001f40d", "Ley Anticulebras",
            "Prediccion de ruptura de combinadas. Detecta cual partido rompera la culebra.",
            "#6B5B95"
        )
        btn_anticulebra.clicked.connect(self.open_anticulebra)
        grid.addWidget(btn_anticulebra, 0, 0)
        
        btn_extraction = MainMenuButton(
            "\U0001f4ca", "Extraccion de Datos",
            "Obtener fixtures, equipos, odds y estadisticas desde API-Football.",
            "#FF6B35"
        )
        btn_extraction.clicked.connect(self.open_extraction)
        grid.addWidget(btn_extraction, 0, 1)
        
        # Fila 2
        btn_database = MainMenuButton(
            "\U0001f5c4\ufe0f", "Gestion de Base de Datos",
            "Administrar constantes K, niveles de equipos y sincronizacion.",
            "#28A745"
        )
        btn_database.clicked.connect(self.open_database_management)
        grid.addWidget(btn_database, 1, 0)
        
        btn_analysis = MainMenuButton(
            "\U0001f3af", "Analisis y Prediccion",
            "Simulador de constantes y predicciones ML por equipo.",
            "#007BFF"
        )
        btn_analysis.clicked.connect(self.open_team_analysis)
        grid.addWidget(btn_analysis, 1, 1)
        
        # Fila 3
        btn_odds = MainMenuButton(
            "\U0001f3b0", "Odds y Simulador del Hincha",
            "Explorar cuotas historicas, cobertura de datos y simular estrategias.",
            "#17A2B8"
        )
        btn_odds.clicked.connect(self.open_odds_viewer)
        grid.addWidget(btn_odds, 2, 0)
        
        btn_db_viewer = MainMenuButton(
            "\U0001f50d", "Explorador de BD",
            "Visualizar tablas y datos directamente desde la base de datos.",
            "#20C997"
        )
        btn_db_viewer.clicked.connect(self.open_db_viewer)
        grid.addWidget(btn_db_viewer, 2, 1)
        
        # Fila 4 - Ley del Marcador + Analisis Pre-Partido
        btn_marcador = MainMenuButton(
            "\u26bd", "Ley del Marcador",
            "Prediccion de goles con modelo Poisson V6. Historial por equipo y proximos partidos.",
            "#E91E63"
        )
        btn_marcador.clicked.connect(self.open_marcador)
        grid.addWidget(btn_marcador, 3, 0)
        
        btn_pre_match = MainMenuButton(
            "\U0001f52e", "Analisis Pre-Partido",
            "Dashboard consolidado: Constantes, Anticulebra, Marcador, H2H y Odds.",
            "#9C27B0"
        )
        btn_pre_match.clicked.connect(self.open_pre_match_analysis)
        grid.addWidget(btn_pre_match, 3, 1)
        
        # Fila 5 - Ley de la Regresion al Nivel + Ley de la Fe Perdida
        btn_regresion = MainMenuButton(
            "\U0001f4c9", "Ley Regresion al Nivel",
            "Prediccion basada en regresion a la media. Si rinde bajo su nivel, mejorara.",
            "#009688"
        )
        btn_regresion.clicked.connect(self.open_regresion_nivel)
        grid.addWidget(btn_regresion, 4, 0)
        
        btn_fe_perdida = MainMenuButton(
            "\u2696\ufe0f", "Ley de la Fe Perdida",
            "Pendulo del hincha: flags de oportunidad basados en rachas emocionales de 42k partidos.",
            "#E8A838"
        )
        btn_fe_perdida.clicked.connect(self.open_fe_perdida)
        grid.addWidget(btn_fe_perdida, 4, 1)
        
        layout.addLayout(grid)
        
        layout.addStretch()
        
        # ═══════════════════════════════════════════════════════════
        # FOOTER
        # ═══════════════════════════════════════════════════════════
        footer = QHBoxLayout()
        footer.setSpacing(15)
        
        # Boton de reparacion (pequeno)
        btn_repair = QPushButton("\U0001f527")
        btn_repair.setToolTip("Diagnostico y reparacion de constants.db")
        btn_repair.setFixedSize(40, 40)
        btn_repair.setStyleSheet("""
            QPushButton {
                background-color: #FFC107;
                color: #1a1a2e;
                border: none;
                border-radius: 8px;
                font-size: 18px;
            }
            QPushButton:hover { background-color: #e0a800; }
        """)
        btn_repair.clicked.connect(self.open_repair_tool)
        footer.addWidget(btn_repair)
        
        # Boton Visor de Tickets
        btn_tickets = QPushButton("\U0001f3ab Tickets")
        btn_tickets.setToolTip(
            "Visor de Tickets de Apuestas\n"
            "Registro, resolucion automatica, ROI y estadisticas"
        )
        btn_tickets.setStyleSheet("""
            QPushButton {
                background-color: #6F42C1;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5A32A3; }
            QPushButton:pressed { background-color: #4A2893; }
        """)
        btn_tickets.clicked.connect(self.open_tickets_viewer)
        footer.addWidget(btn_tickets)
        
        # Boton Exportador de Predicciones Historicas
        btn_exporter = QPushButton("\U0001f4c8 Exportar Historico")
        btn_exporter.setToolTip(
            "Genera predicciones retroactivas de los 3 modelos ML\n"
            "sobre partidos ya jugados. Para calibracion de umbrales\n"
            "y entrenamiento de meta-modelo."
        )
        btn_exporter.setStyleSheet("""
            QPushButton {
                background-color: #8E24AA;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #7B1FA2; }
            QPushButton:pressed { background-color: #6A1B9A; }
        """)
        btn_exporter.clicked.connect(self.open_historical_exporter)
        footer.addWidget(btn_exporter)
        
        # Boton Regresion al Nivel
        btn_reg_nivel = QPushButton("\U0001f4c9 Regresion Nivel")
        btn_reg_nivel.setToolTip(
            "Ley de la Regresion al Nivel\n"
            "Prediccion, validacion y entrenamiento del modelo.\n"
            "AUC=0.874 | Accuracy=80%"
        )
        btn_reg_nivel.setStyleSheet("""
            QPushButton {
                background-color: #009688;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #00796B; }
            QPushButton:pressed { background-color: #004D40; }
        """)
        btn_reg_nivel.clicked.connect(self.open_regresion_nivel)
        footer.addWidget(btn_reg_nivel)
        
        # Boton configuracion
        btn_settings = QPushButton("\u2699\ufe0f Configuracion")
        btn_settings.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        btn_settings.clicked.connect(self.open_settings)
        footer.addWidget(btn_settings)
        
        # Boton salir
        btn_exit = QPushButton("\u274c Salir")
        btn_exit.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #c82333; }
        """)
        btn_exit.clicked.connect(self.close)
        footer.addWidget(btn_exit)
        
        footer.addStretch()
        
        # Info
        info = QLabel("\U0001f3c6 v2.5 | Anticulebras \u2022 Constantes K \u2022 ML \u2022 Odds \u2022 Marcador \u2022 Pre-Partido \u2022 Regresion Nivel \u2022 Fe Perdida \u2022 Tickets \u2022 Exportador")
        info.setStyleSheet("color: #888; font-size: 11px;")
        footer.addWidget(info)
        
        layout.addLayout(footer)
        
        self.setCentralWidget(central)
        
        # Estilo global de la ventana
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #F8F9FA, 
                    stop:1 #E9ECEF
                );
            }
        """)
    
    # ═══════════════════════════════════════════════════════════════════
    # METODOS PARA ABRIR VENTANAS
    # ═══════════════════════════════════════════════════════════════════
    
    def open_anticulebra(self):
        """Abre la ventana de Anticulebras."""
        try:
            from ui.anticulebra import AnticulebraWindow
            
            if self.anticulebra_window is None or not self.anticulebra_window.isVisible():
                self.anticulebra_window = AnticulebraWindow()
            
            self.anticulebra_window.show()
            self.anticulebra_window.raise_()
            self.anticulebra_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Anticulebras: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el modulo Anticulebras:\n{str(e)}\n\n"
                "Verifica que la carpeta 'anticulebra' este en ui/"
            )
        except Exception as e:
            logger.error(f"Error abriendo Anticulebras: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Anticulebras:\n{str(e)}")
    
    def open_extraction(self):
        """Abre la ventana de extraccion de datos API-Football."""
        try:
            from ui.extraction_window import ExtractionWindow
            
            if self.extraction_window is None or not self.extraction_window.isVisible():
                self.extraction_window = ExtractionWindow()
            
            self.extraction_window.show()
            self.extraction_window.raise_()
            self.extraction_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Extraccion: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el modulo de extraccion:\n{str(e)}"
            )
        except Exception as e:
            logger.error(f"Error abriendo Extraccion: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir ventana de extraccion:\n{str(e)}")
    
    def open_database_management(self):
        """Abre el dialogo de gestion de base de datos."""
        try:
            from ui.simplified_database_management_dialog import SimplifiedDatabaseManagementDialog
            dialog = SimplifiedDatabaseManagementDialog(self)
            dialog.exec()
        except ImportError as e:
            logger.error(f"Error importando Gestion BD: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo cargar el modulo de gestion de BD:\n{str(e)}"
            )
    
    def open_team_analysis(self):
        """Abre el selector de equipos para analisis."""
        try:
            from ui.team_selection_dialog import TeamSelectionDialog
            dialog = TeamSelectionDialog(self)
            dialog.exec()
        except ImportError as e:
            logger.error(f"Error importando Analisis: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo cargar el modulo de analisis:\n{str(e)}"
            )
    
    def open_odds_viewer(self):
        """Abre el visor de cuotas y simulador del hincha."""
        try:
            from ui.odds_viewer import OddsViewerWindow
            
            if self.odds_window is None or not self.odds_window.isVisible():
                self.odds_window = OddsViewerWindow()
            
            self.odds_window.show()
            self.odds_window.raise_()
            self.odds_window.activateWindow()
            
        except ImportError as e:
            logger.warning(f"Odds Viewer no disponible: {e}")
            QMessageBox.warning(
                self,
                "Modulo no disponible",
                f"El modulo Odds Viewer no esta instalado:\n{str(e)}\n\n"
                "Instalalo copiando la carpeta 'odds_viewer' en src/ui/"
            )
        except Exception as e:
            logger.error(f"Error abriendo Odds Viewer: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Odds Viewer:\n{str(e)}")
    
    def open_db_viewer(self):
        """Abre el explorador de base de datos."""
        try:
            from ui.db_viewer import DatabaseViewerWindow
            
            if self.db_viewer_window is None or not self.db_viewer_window.isVisible():
                self.db_viewer_window = DatabaseViewerWindow()
            
            self.db_viewer_window.show()
            self.db_viewer_window.raise_()
            self.db_viewer_window.activateWindow()
            
        except ImportError as e:
            logger.warning(f"DB Viewer no disponible: {e}")
            QMessageBox.warning(
                self,
                "Modulo no disponible",
                f"El modulo Database Viewer no esta instalado:\n{str(e)}\n\n"
                "Instalalo copiando la carpeta 'db_viewer' en src/ui/"
            )
        except Exception as e:
            logger.error(f"Error abriendo DB Viewer: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Database Viewer:\n{str(e)}")
    
    def open_marcador(self):
        """Abre la ventana de Ley del Marcador."""
        try:
            from ui.marcador_window import MarcadorWindow
            
            if self.marcador_window is None or not self.marcador_window.isVisible():
                self.marcador_window = MarcadorWindow()
            
            self.marcador_window.show()
            self.marcador_window.raise_()
            self.marcador_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Ley del Marcador: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el modulo Ley del Marcador:\n{str(e)}\n\n"
                "Verifica que:\n"
                "1. 'marcador_window.py' este en src/ui/\n"
                "2. 'ml_goals_predictor_v6.py' este en src/\n"
                "3. El modelo este entrenado (ml_goals_predictor_v6_model.pkl)"
            )
        except Exception as e:
            logger.error(f"Error abriendo Ley del Marcador: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Ley del Marcador:\n{str(e)}")
    
    def open_pre_match_analysis(self):
        """Abre la ventana de Analisis Pre-Partido."""
        try:
            from ui.pre_match_analysis_window import PreMatchAnalysisWindow
            
            if self.pre_match_window is None or not self.pre_match_window.isVisible():
                self.pre_match_window = PreMatchAnalysisWindow()
            
            self.pre_match_window.show()
            self.pre_match_window.raise_()
            self.pre_match_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Analisis Pre-Partido: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el modulo Analisis Pre-Partido:\n{str(e)}\n\n"
                "Verifica que:\n"
                "1. 'pre_match_analysis_window.py' este en src/ui/\n"
                "2. Los modulos de dependencia esten disponibles"
            )
        except Exception as e:
            logger.error(f"Error abriendo Analisis Pre-Partido: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Analisis Pre-Partido:\n{str(e)}")
    
    def open_regresion_nivel(self):
        """Abre la ventana de Ley de la Regresion al Nivel."""
        try:
            from ui.regresion_nivel_window import RegresionNivelWindow
            
            if self.regresion_nivel_window is None or not self.regresion_nivel_window.isVisible():
                self.regresion_nivel_window = RegresionNivelWindow()
            
            self.regresion_nivel_window.show()
            self.regresion_nivel_window.raise_()
            self.regresion_nivel_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Regresion al Nivel: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el modulo Regresion al Nivel:\n{str(e)}\n\n"
                "Verifica que:\n"
                "1. 'regresion_nivel_window.py' este en src/ui/\n"
                "2. 'regresion_nivel_engine.py' este en src/\n"
                "3. levels.db este disponible"
            )
        except Exception as e:
            logger.error(f"Error abriendo Regresion al Nivel: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Regresion al Nivel:\n{str(e)}")
    
    def open_fe_perdida(self):
        """Abre la ventana de Ley de la Fe Perdida."""
        try:
            from ui.ley_fe_perdida_window import FePerdidaWindow
            
            if self.fe_perdida_window is None or not self.fe_perdida_window.isVisible():
                self.fe_perdida_window = FePerdidaWindow()
            
            self.fe_perdida_window.show()
            self.fe_perdida_window.raise_()
            self.fe_perdida_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Fe Perdida: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar Ley de la Fe Perdida:\n{str(e)}\n\n"
                "Verifica que:\n"
                "1. 'ley_fe_perdida_window.py' este en src/ui/\n"
                "2. 'ley_fe_perdida_engine.py' este en src/"
            )
        except Exception as e:
            logger.error(f"Error abriendo Fe Perdida: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Fe Perdida:\n{str(e)}")
    
    def open_tickets_viewer(self):
        """Abre el visor de tickets de apuestas."""
        try:
            from ui.tickets_viewer_window import TicketsViewerWindow
            
            # Rutas: sad.db y tickets.db estan fuera de src/
            src_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(src_dir)
            
            tickets_db = os.path.join(project_root, 'tickets.db')
            sad_db = os.path.join(project_root, 'sad.db')
            
            if self.tickets_viewer_window is None or not self.tickets_viewer_window.isVisible():
                self.tickets_viewer_window = TicketsViewerWindow(
                    tickets_db_path=tickets_db,
                    sad_db_path=sad_db,
                )
            
            self.tickets_viewer_window.show()
            self.tickets_viewer_window.raise_()
            self.tickets_viewer_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Visor de Tickets: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el Visor de Tickets:\n{str(e)}\n\n"
                "Verifica que:\n"
                "1. 'tickets_viewer_window.py' este en src/ui/\n"
                "2. 'tickets_manager.py' este en src/utils/"
            )
        except Exception as e:
            logger.error(f"Error abriendo Visor de Tickets: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Visor de Tickets:\n{str(e)}")
    
    def open_historical_exporter(self):
        """Abre el dialogo de exportacion de predicciones historicas."""
        try:
            from utils.historical_exporter_dialog import HistoricalExporterDialog
            
            if self.exporter_dialog is None or not self.exporter_dialog.isVisible():
                self.exporter_dialog = HistoricalExporterDialog(self)
            
            self.exporter_dialog.show()
            self.exporter_dialog.raise_()
            self.exporter_dialog.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando Exportador: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el modulo Exportador:\n{str(e)}\n\n"
                "Verifica que:\n"
                "1. 'historical_exporter_dialog.py' este en src/\n"
                "2. 'historical_predictions_exporter.py' este en src/\n"
                "3. Las bases de datos (sad.db, constants.db) esten accesibles"
            )
        except Exception as e:
            logger.error(f"Error abriendo Exportador: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir Exportador:\n{str(e)}")
    
    def open_repair_tool(self):
        """Abre la herramienta de diagnostico y reparacion de constants.db"""
        try:
            from ui.constants_repair_tool import ConstantsRepairDialog
            dialog = ConstantsRepairDialog(self)
            dialog.exec()
        except ImportError as e:
            logger.error(f"Error importando repair tool: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"No se pudo cargar la herramienta de reparacion:\n{str(e)}\n\n"
                "Verifica que 'constants_repair_tool.py' este en src/ui/"
            )
        except Exception as e:
            logger.error(f"Error abriendo repair tool: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir herramienta:\n{str(e)}")
    
    def open_settings(self):
        """Abre configuracion."""
        QMessageBox.information(
            self,
            "\u2699\ufe0f Configuracion",
            "El panel de configuracion estara disponible proximamente.\n\n"
            "Por ahora puedes modificar:\n"
            "\u2022 config/api_config.py - API keys\n"
            "\u2022 config/settings.py - Configuracion general\n\n"
            "Archivos de base de datos:\n"
            "\u2022 sad.db - Fixtures y odds\n"
            "\u2022 constants.db - Constantes K\n"
            "\u2022 levels.db - Niveles de equipos\n"
            "\u2022 tickets.db - Tickets de apuestas\n"
            "\u2022 pendulum.db - Cache pendulo Fe Perdida\n"
            "\u2022 regresion_nivel_output/ - Modelo Regresion al Nivel"
        )


def main():
    """Funcion principal que inicia la aplicacion."""
    logger.info("\U0001f4f1 Creando aplicacion Qt...")
    app = QApplication(sys.argv)
    
    # Fuente global
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Estilo global
    app.setStyleSheet("""
        QMainWindow {
            background-color: #F8F9FA;
        }
        QDialog {
            background-color: #FFFFFF;
        }
        QGroupBox {
            font-weight: bold;
            border: 2px solid #DEE2E6;
            border-radius: 8px;
            margin-top: 1.5ex;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 15px;
            padding: 0 8px;
            color: #495057;
        }
        QToolTip {
            background-color: #1a1a2e;
            color: white;
            border: none;
            border-radius: 5px;
            padding: 8px 12px;
            font-size: 12px;
        }
        QScrollBar:vertical {
            background: #F1F3F4;
            width: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background: #C1C1C1;
            border-radius: 6px;
            min-height: 30px;
        }
        QScrollBar::handle:vertical:hover {
            background: #A8A8A8;
        }
        QScrollBar:horizontal {
            background: #F1F3F4;
            height: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal {
            background: #C1C1C1;
            border-radius: 6px;
            min-width: 30px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #A8A8A8;
        }
        QTableWidget {
            gridline-color: #E9ECEF;
            selection-background-color: #17A2B8;
            selection-color: white;
        }
        QHeaderView::section {
            background-color: #1a1a2e;
            color: white;
            padding: 8px;
            border: none;
            font-weight: bold;
        }
        QComboBox {
            padding: 8px 12px;
            border: 1px solid #CED4DA;
            border-radius: 6px;
            background: white;
        }
        QComboBox:hover {
            border-color: #17A2B8;
        }
        QComboBox::drop-down {
            border: none;
            padding-right: 10px;
        }
        QSpinBox, QDoubleSpinBox {
            padding: 8px;
            border: 1px solid #CED4DA;
            border-radius: 6px;
        }
        QLineEdit {
            padding: 8px 12px;
            border: 1px solid #CED4DA;
            border-radius: 6px;
        }
        QLineEdit:focus {
            border-color: #17A2B8;
        }
    """)
    
    logger.info("\U0001fa9f Creando ventana principal...")
    window = UpdatedMainWindow()
    window.show()
    logger.info("\u2705 Aplicacion lista")
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())