# ui/db_viewer/match_viewer_dialog.py
# -*- coding: utf-8 -*-
"""
⚽ Visor de Partidos estilo BeSoccer
====================================
Muestra partidos agrupados por liga con navegación por fechas,
marcadores, estados y odds.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any
from collections import defaultdict

# Timezone de Perú (UTC-5)
PERU_TZ = timezone(timedelta(hours=-5))

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QPushButton, QFrame, QComboBox, QApplication,
    QSizePolicy, QSpacerItem, QGridLayout
)
from PySide6.QtCore import Qt, Signal, QDate, QTimer
from PySide6.QtGui import QFont, QColor, QPalette

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


# =============================================================================
# Ubicación de la base de datos
# =============================================================================

def get_db_path() -> str:
    """Obtiene la ruta de sad.db subiendo niveles desde este archivo."""
    # Intentar múltiples rutas posibles
    possible_paths = [
        # Desde src/ui/db_viewer/
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sad.db'),
        # Desde src/ui/
        os.path.join(os.path.dirname(__file__), '..', '..', 'sad.db'),
        # Desde src/
        os.path.join(os.path.dirname(__file__), '..', 'sad.db'),
        # Desde la raíz
        os.path.join(os.path.dirname(__file__), 'sad.db'),
    ]
    
    for path in possible_paths:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            return abs_path
    
    # Si no encuentra, devolver la ruta estándar
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sad.db'))


# =============================================================================
# Colores por país/liga
# =============================================================================

LEAGUE_COLORS = {
    # Sudamérica
    'Argentina': '#75AADB',
    'Brazil': '#009739',
    'Peru': '#D91023',
    'Colombia': '#FCD116',
    'Chile': '#0033A0',
    'Uruguay': '#0038A8',
    'Bolivia': '#007934',
    'Paraguay': '#DA121A',
    'Ecuador': '#FFD100',
    'Venezuela': '#CF142B',
    
    # Europa Top 5
    'England': '#C8102E',
    'Spain': '#AA151B',
    'Italy': '#009246',
    'Germany': '#000000',
    'France': '#002654',
    
    # Otros europeos
    'Portugal': '#006600',
    'Netherlands': '#FF6600',
    'Belgium': '#ED2939',
    'Turkey': '#E30A17',
    'Russia': '#0039A6',
    'Ukraine': '#005BBB',
    'Greece': '#0D5EAF',
    'Scotland': '#0065BF',
    
    # Competiciones internacionales
    'World': '#1E3A5F',
    'Copa Libertadores': '#1B365D',
    'Copa Sudamericana': '#C41E3A',
    'Champions League': '#1A237E',
    'Europa League': '#FF6600',
    
    # Default
    'default': '#4A5568',
}


def get_league_color(country: str, league_name: str = '') -> str:
    """Obtiene el color para una liga/país."""
    # Primero intentar por nombre de liga
    for key, color in LEAGUE_COLORS.items():
        if key.lower() in league_name.lower():
            return color
    
    # Luego por país
    return LEAGUE_COLORS.get(country, LEAGUE_COLORS['default'])


# =============================================================================
# Widget de fecha individual
# =============================================================================

class DateButton(QPushButton):
    """Botón para seleccionar una fecha."""
    
    date_selected = Signal(QDate)
    
    def __init__(self, date: QDate, is_today: bool = False, parent=None):
        super().__init__(parent)
        self.date = date
        self.is_today = is_today
        self._selected = False
        
        self.setFixedSize(70, 70)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(lambda: self.date_selected.emit(self.date))
        
        self._update_display()
    
    def _update_display(self):
        """Actualiza el contenido del botón."""
        day_names = ['LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB', 'DOM']
        month_names = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 
                       'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC']
        
        day_name = day_names[self.date.dayOfWeek() - 1]
        day_num = self.date.day()
        month = month_names[self.date.month() - 1]
        
        if self.is_today:
            self.setText(f"{day_name}\nHOY\n{day_num:02d} {month}")
        else:
            self.setText(f"{day_name}\n{day_num:02d}\n{month}")
        
        self._apply_style()
    
    def set_selected(self, selected: bool):
        """Marca el botón como seleccionado."""
        self._selected = selected
        self._apply_style()
    
    def _apply_style(self):
        """Aplica estilo según estado."""
        if self._selected:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1a1a2e;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 11px;
                    font-weight: bold;
                    border-bottom: 3px solid #28A745;
                }
            """)
        elif self.is_today:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #E8F5E9;
                    color: #1a1a2e;
                    border: 1px solid #28A745;
                    border-radius: 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #C8E6C9;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #F5F5F5;
                    color: #333;
                    border: 1px solid #DDD;
                    border-radius: 8px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #E0E0E0;
                    border-color: #999;
                }
            """)


# =============================================================================
# Widget de partido individual
# =============================================================================

class MatchWidget(QFrame):
    """Widget que muestra un partido individual."""
    
    match_clicked = Signal(int)  # Emite fixture_id
    analysis_requested = Signal(int)  # Emite fixture_id para análisis pre-partido
    
    def __init__(self, match_data: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.match_data = match_data
        self.setFrameStyle(QFrame.StyledPanel)
        
        self._build_ui()
        self._apply_style()
    
    def _build_ui(self):
        """Construye la interfaz del widget."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(10)
        
        # === Hora/Estado ===
        time_widget = QWidget()
        time_layout = QVBoxLayout(time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(2)
        
        status = self.match_data.get('status_short', 'NS')
        
        if status in ['FT', 'AET', 'PEN']:
            # Partido terminado
            status_label = QLabel("FIN")
            status_label.setStyleSheet("color: #666; font-size: 11px; font-weight: bold;")
        elif status in ['1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE']:
            # En vivo
            elapsed = self.match_data.get('elapsed', '')
            status_label = QLabel(f"⚽ {elapsed}'")
            status_label.setStyleSheet("color: #E53935; font-size: 12px; font-weight: bold;")
        else:
            # Por jugar - mostrar hora en Lima (UTC-5)
            match_date = self.match_data.get('date')
            if match_date:
                if isinstance(match_date, str):
                    try:
                        # Parsear fecha (puede venir con o sin timezone)
                        if 'Z' in match_date or '+' in match_date:
                            dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
                            # Convertir UTC a Lima (restar 5 horas)
                            dt = dt.replace(tzinfo=None) - timedelta(hours=5)
                        else:
                            # Sin timezone, asumir UTC
                            dt = datetime.fromisoformat(match_date)
                            dt = dt - timedelta(hours=5)
                    except:
                        dt = datetime.now()
                else:
                    # Es datetime object, asumir UTC
                    dt = match_date - timedelta(hours=5)
                time_str = dt.strftime("%H:%M")
            else:
                time_str = "--:--"
            status_label = QLabel(time_str)
            status_label.setStyleSheet("color: #333; font-size: 13px; font-weight: bold;")
        
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setFixedWidth(50)
        time_layout.addWidget(status_label)
        
        layout.addWidget(time_widget)
        
        # === Equipo Local ===
        home_name = self.match_data.get('home_name', 'Local')
        home_label = QLabel(home_name)
        home_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        home_label.setStyleSheet("font-size: 13px; color: #1a1a2e;")
        home_label.setMinimumWidth(150)
        layout.addWidget(home_label, 1)
        
        # === Marcador ===
        score_widget = QWidget()
        score_layout = QHBoxLayout(score_widget)
        score_layout.setContentsMargins(10, 0, 10, 0)
        score_layout.setSpacing(5)
        
        goals_home = self.match_data.get('goals_home')
        goals_away = self.match_data.get('goals_away')
        
        if goals_home is not None and goals_away is not None:
            score_text = f"{goals_home} - {goals_away}"
            score_style = "font-size: 16px; font-weight: bold; color: #1a1a2e;"
        else:
            score_text = "vs"
            score_style = "font-size: 14px; color: #888;"
        
        score_label = QLabel(score_text)
        score_label.setAlignment(Qt.AlignCenter)
        score_label.setStyleSheet(score_style)
        score_label.setFixedWidth(60)
        score_layout.addWidget(score_label)
        
        layout.addWidget(score_widget)
        
        # === Equipo Visitante ===
        away_name = self.match_data.get('away_name', 'Visitante')
        away_label = QLabel(away_name)
        away_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        away_label.setStyleSheet("font-size: 13px; color: #1a1a2e;")
        away_label.setMinimumWidth(150)
        layout.addWidget(away_label, 1)
        
        # === Odds (si hay) ===
        odds = self.match_data.get('odds', {})
        if odds:
            odds_widget = QWidget()
            odds_layout = QHBoxLayout(odds_widget)
            odds_layout.setContentsMargins(10, 0, 0, 0)
            odds_layout.setSpacing(5)
            
            for key, label in [('home', '1'), ('draw', 'X'), ('away', '2')]:
                odd_value = odds.get(key)
                if odd_value:
                    odd_btn = QLabel(f"{odd_value:.2f}")
                    odd_btn.setAlignment(Qt.AlignCenter)
                    odd_btn.setFixedSize(45, 25)
                    odd_btn.setStyleSheet("""
                        QLabel {
                            background-color: #E3F2FD;
                            color: #1565C0;
                            border: 1px solid #90CAF9;
                            border-radius: 4px;
                            font-size: 11px;
                            font-weight: bold;
                        }
                    """)
                    odds_layout.addWidget(odd_btn)
            
            layout.addWidget(odds_widget)
        
        # === Botón de Análisis Pre-Partido ===
        btn_analysis = QPushButton("🔮")
        btn_analysis.setToolTip("Análisis Pre-Partido")
        btn_analysis.setFixedSize(35, 30)
        btn_analysis.setCursor(Qt.PointingHandCursor)
        btn_analysis.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
            QPushButton:pressed {
                background-color: #6A1B9A;
            }
        """)
        btn_analysis.clicked.connect(self._on_analysis_clicked)
        layout.addWidget(btn_analysis)
    
    def _on_analysis_clicked(self):
        """Emite señal para abrir análisis pre-partido."""
        fixture_id = self.match_data.get('fixture_id')
        if fixture_id:
            self.analysis_requested.emit(fixture_id)
    
    def _apply_style(self):
        """Aplica estilo al widget."""
        self.setStyleSheet("""
            MatchWidget {
                background-color: white;
                border: none;
                border-bottom: 1px solid #E0E0E0;
            }
            MatchWidget:hover {
                background-color: #F5F5F5;
            }
        """)
    
    def mousePressEvent(self, event):
        """Maneja clic en el partido."""
        if event.button() == Qt.LeftButton:
            fixture_id = self.match_data.get('fixture_id')
            if fixture_id:
                self.match_clicked.emit(fixture_id)
        super().mousePressEvent(event)


# =============================================================================
# Widget de grupo de liga
# =============================================================================

class LeagueGroupWidget(QFrame):
    """Widget que agrupa partidos de una liga."""
    
    match_clicked = Signal(int)
    analysis_requested = Signal(int)  # Nueva señal para análisis
    
    def __init__(self, league_id: int, league_name: str, country: str, matches: List[Dict], parent=None):
        super().__init__(parent)
        self.league_id = league_id
        self.league_name = league_name
        self.country = country
        self.matches = matches
        
        self._build_ui()
    
    def _build_ui(self):
        """Construye la interfaz."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header de la liga
        header = QFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        color = get_league_color(self.country, self.league_name)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {color};
                border-radius: 8px 8px 0 0;
            }}
        """)
        
        # Bandera/indicador de país
        flag_label = QLabel("⚽")
        flag_label.setStyleSheet("font-size: 16px;")
        header_layout.addWidget(flag_label)
        
        # Nombre de liga con ID
        league_display = f"{self.league_name.upper()} ({self.league_id})" if self.league_id else self.league_name.upper()
        league_label = QLabel(league_display)
        league_label.setStyleSheet("""
            font-size: 13px;
            font-weight: bold;
            color: white;
            letter-spacing: 1px;
        """)
        header_layout.addWidget(league_label)
        
        # País
        country_label = QLabel(f"({self.country})")
        country_label.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.8);")
        header_layout.addWidget(country_label)
        
        header_layout.addStretch()
        
        # Contador de partidos
        count_label = QLabel(f"{len(self.matches)} partidos")
        count_label.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.8);")
        header_layout.addWidget(count_label)
        
        layout.addWidget(header)
        
        # Contenedor de partidos
        matches_container = QFrame()
        matches_container.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-top: none;
                border-radius: 0 0 8px 8px;
            }
        """)
        matches_layout = QVBoxLayout(matches_container)
        matches_layout.setContentsMargins(0, 0, 0, 0)
        matches_layout.setSpacing(0)
        
        for match in self.matches:
            match_widget = MatchWidget(match)
            match_widget.match_clicked.connect(self.match_clicked.emit)
            match_widget.analysis_requested.connect(self.analysis_requested.emit)
            matches_layout.addWidget(match_widget)
        
        layout.addWidget(matches_container)


# =============================================================================
# Diálogo principal del visor de partidos
# =============================================================================

class MatchViewerDialog(QDialog):
    """
    Diálogo principal del visor de partidos estilo BeSoccer.
    """
    
    def __init__(self, db_path: str = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚽ Visor de Partidos")
        self.resize(1000, 700)
        self.setModal(False)
        
        # Configurar BD
        self.db_path = db_path or get_db_path()
        self.engine = None
        self.Session = None
        
        # Estado
        self.selected_date = QDate.currentDate()
        self.selected_league_id = None  # None = todas
        self.date_buttons: List[DateButton] = []
        
        self._connect_db()
        self._build_ui()
        self._load_leagues()
        self._load_matches()
    
    def _connect_db(self):
        """Conecta a la base de datos."""
        try:
            if os.path.exists(self.db_path):
                self.engine = create_engine(f'sqlite:///{self.db_path}', echo=False)
                self.Session = sessionmaker(bind=self.engine)
                logger.info(f"Conectado a: {self.db_path}")
            else:
                logger.error(f"BD no encontrada: {self.db_path}")
        except Exception as e:
            logger.error(f"Error conectando a BD: {e}")
    
    def _build_ui(self):
        """Construye la interfaz principal."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # === Header con filtros ===
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: white;
                border-bottom: 1px solid #E0E0E0;
            }
        """)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        header_layout.setSpacing(10)
        
        # Fila 1: Título y filtro de liga
        title_row = QHBoxLayout()
        
        title = QLabel("⚽ Visor de Partidos")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a1a2e;")
        title_row.addWidget(title)
        
        # Hora de Perú (Lima UTC-5)
        self.peru_time_label = QLabel()
        self.peru_time_label.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: #D91023;
            background-color: #FFF3F3;
            padding: 5px 12px;
            border-radius: 6px;
            border: 1px solid #FFCCCC;
        """)
        self._update_peru_time()
        title_row.addWidget(self.peru_time_label)
        
        # Timer para actualizar la hora cada segundo
        self.time_timer = QTimer(self)
        self.time_timer.timeout.connect(self._update_peru_time)
        self.time_timer.start(1000)
        
        title_row.addStretch()
        
        # Filtro de liga
        league_label = QLabel("Liga:")
        league_label.setStyleSheet("font-size: 12px; color: #666;")
        title_row.addWidget(league_label)
        
        self.league_combo = QComboBox()
        self.league_combo.setMinimumWidth(250)
        self.league_combo.setStyleSheet("""
            QComboBox {
                padding: 8px 12px;
                border: 1px solid #DDD;
                border-radius: 6px;
                background: white;
            }
        """)
        self.league_combo.currentIndexChanged.connect(self._on_league_changed)
        title_row.addWidget(self.league_combo)
        
        header_layout.addLayout(title_row)
        
        # Fila 2: Calendario de fechas
        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        
        # Botón anterior
        btn_prev = QPushButton("◀")
        btn_prev.setFixedSize(30, 70)
        btn_prev.setStyleSheet("""
            QPushButton {
                background: #F5F5F5;
                border: 1px solid #DDD;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover { background: #E0E0E0; }
        """)
        btn_prev.clicked.connect(self._prev_week)
        date_row.addWidget(btn_prev)
        
        # Contenedor de fechas
        self.dates_container = QHBoxLayout()
        self.dates_container.setSpacing(5)
        date_row.addLayout(self.dates_container)
        
        # Botón siguiente
        btn_next = QPushButton("▶")
        btn_next.setFixedSize(30, 70)
        btn_next.setStyleSheet("""
            QPushButton {
                background: #F5F5F5;
                border: 1px solid #DDD;
                border-radius: 6px;
                font-size: 14px;
            }
            QPushButton:hover { background: #E0E0E0; }
        """)
        btn_next.clicked.connect(self._next_week)
        date_row.addWidget(btn_next)
        
        date_row.addStretch()
        
        header_layout.addLayout(date_row)
        
        layout.addWidget(header)
        
        # Generar botones de fecha
        self._generate_date_buttons()
        
        # === Área de contenido (scroll) ===
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #F5F5F5;
            }
        """)
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(15, 15, 15, 15)
        self.content_layout.setSpacing(15)
        
        scroll.setWidget(self.content_widget)
        layout.addWidget(scroll)
        
        # === Footer con info ===
        footer = QFrame()
        footer.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                padding: 8px;
            }
        """)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(15, 8, 15, 8)
        
        self.info_label = QLabel("Cargando partidos...")
        self.info_label.setStyleSheet("color: white; font-size: 12px;")
        footer_layout.addWidget(self.info_label)
        
        footer_layout.addStretch()
        
        db_label = QLabel(f"📁 {os.path.basename(self.db_path)}")
        db_label.setStyleSheet("color: rgba(255,255,255,0.7); font-size: 11px;")
        footer_layout.addWidget(db_label)
        
        layout.addWidget(footer)
    
    def _generate_date_buttons(self):
        """Genera los botones de fecha para la semana actual."""
        # Limpiar botones existentes
        for btn in self.date_buttons:
            btn.deleteLater()
        self.date_buttons.clear()
        
        # Generar 7 días centrados en la fecha seleccionada
        today = QDate.currentDate()
        start_date = self.selected_date.addDays(-3)
        
        for i in range(7):
            date = start_date.addDays(i)
            is_today = (date == today)
            
            btn = DateButton(date, is_today)
            btn.date_selected.connect(self._on_date_selected)
            btn.set_selected(date == self.selected_date)
            
            self.dates_container.addWidget(btn)
            self.date_buttons.append(btn)
    
    def _update_peru_time(self):
        """Actualiza el label con la hora actual de Perú (Lima UTC-5)."""
        now_utc = datetime.now(timezone.utc)
        now_peru = now_utc.astimezone(PERU_TZ)
        
        day_names = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        day_name = day_names[now_peru.weekday()]
        
        time_str = now_peru.strftime("%H:%M:%S")
        date_str = now_peru.strftime("%d/%m")
        
        self.peru_time_label.setText(f"🇵🇪 Lima: {day_name} {date_str} - {time_str}")
    
    def _on_date_selected(self, date: QDate):
        """Maneja selección de fecha."""
        self.selected_date = date
        
        # Actualizar botones
        for btn in self.date_buttons:
            btn.set_selected(btn.date == date)
        
        self._load_matches()
    
    def _prev_week(self):
        """Navega a la semana anterior."""
        self.selected_date = self.selected_date.addDays(-7)
        self._generate_date_buttons()
        self._load_matches()
    
    def _next_week(self):
        """Navega a la semana siguiente."""
        self.selected_date = self.selected_date.addDays(7)
        self._generate_date_buttons()
        self._load_matches()
    
    def _load_leagues(self):
        """Carga las ligas disponibles."""
        self.league_combo.clear()
        self.league_combo.addItem("🌍 Todas las ligas", None)
        
        if not self.Session:
            return
        
        try:
            session = self.Session()
            
            # Obtener ligas que tienen fixtures
            query = text("""
                SELECT DISTINCT l.id, l.name, l.country
                FROM leagues l
                INNER JOIN fixtures f ON f.league_id = l.id
                ORDER BY l.country, l.name
            """)
            
            results = session.execute(query).fetchall()
            
            for row in results:
                league_id, name, country = row
                display_name = f"{country} - {name}" if country else name
                self.league_combo.addItem(display_name, league_id)
            
            session.close()
            
        except Exception as e:
            logger.error(f"Error cargando ligas: {e}")
    
    def _on_league_changed(self, index: int):
        """Maneja cambio de liga seleccionada."""
        self.selected_league_id = self.league_combo.currentData()
        self._load_matches()
    
    def _get_league_name_fallback(self, league_id: int) -> str:
        """Obtiene el nombre de una liga por su ID usando un diccionario de fallback."""
        # Diccionario de ligas conocidas (IDs de API-Football)
        KNOWN_LEAGUES = {
            # Sudamérica
            128: "Liga Profesional Argentina",
            129: "Copa Argentina",
            130: "Superliga Argentina",
            131: "Primera B Nacional",
            71: "Serie A Brasil",
            72: "Serie B Brasil",
            73: "Copa do Brasil",
            268: "Liga 1 Peru",
            269: "Liga 2 Peru",
            239: "Primera Division Colombia",
            240: "Copa Colombia",
            265: "Primera Division Chile",
            266: "Copa Chile",
            242: "Primera Division Uruguay",
            243: "Copa Uruguay",
            245: "Primera Division Ecuador",
            246: "Copa Ecuador",
            # Copas internacionales
            13: "Copa Libertadores",
            11: "Copa Sudamericana",
            # Europa Top 5
            39: "Premier League",
            40: "Championship",
            41: "League One",
            140: "La Liga",
            141: "Segunda Division",
            135: "Serie A Italia",
            136: "Serie B Italia",
            78: "Bundesliga",
            79: "2. Bundesliga",
            61: "Ligue 1",
            62: "Ligue 2",
            # Otras
            94: "Primeira Liga Portugal",
            144: "Eredivisie",
            88: "Eredivisie",
            2: "Champions League",
            3: "Europa League",
            848: "Conference League",
            # México
            262: "Liga MX",
            263: "Liga MX Expansion",
        }
        
        return KNOWN_LEAGUES.get(league_id, f"Liga ID: {league_id}")
    
    def _load_matches(self):
        """Carga los partidos de la fecha seleccionada (en hora de Lima)."""
        # Limpiar contenido actual
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not self.Session:
            self._show_error("No hay conexión a la base de datos")
            return
        
        try:
            session = self.Session()
            
            # ═══════════════════════════════════════════════════════════════
            # CONVERTIR FECHA DE LIMA A RANGO UTC
            # Lima es UTC-5, entonces:
            # - 00:00 Lima = 05:00 UTC del mismo día
            # - 23:59 Lima = 04:59 UTC del día siguiente
            # ═══════════════════════════════════════════════════════════════
            
            # Fecha seleccionada (en Lima)
            year = self.selected_date.year()
            month = self.selected_date.month()
            day = self.selected_date.day()
            
            # Inicio del día en Lima = 05:00 UTC del mismo día
            # Fin del día en Lima = 05:00 UTC del día siguiente
            from datetime import datetime as dt_module
            
            lima_start = dt_module(year, month, day, 0, 0, 0)  # 00:00 Lima
            utc_start = lima_start + timedelta(hours=5)  # Convertir a UTC (+5 horas)
            utc_end = utc_start + timedelta(days=1)  # 24 horas después
            
            utc_start_str = utc_start.strftime("%Y-%m-%d %H:%M:%S")
            utc_end_str = utc_end.strftime("%Y-%m-%d %H:%M:%S")
            
            logger.info(f"Buscando partidos para Lima {year}-{month:02d}-{day:02d}: UTC {utc_start_str} a {utc_end_str}")
            
            # Query principal con rango UTC
            query = text("""
                SELECT 
                    f.id as fixture_id,
                    f.date,
                    f.status_short,
                    f.status_long,
                    f.elapsed,
                    f.goals_home,
                    f.goals_away,
                    f.league_id,
                    l.name as league_name,
                    l.country as league_country,
                    th.name as home_name,
                    ta.name as away_name
                FROM fixtures f
                LEFT JOIN leagues l ON f.league_id = l.id
                LEFT JOIN teams th ON f.home_team_id = th.id
                LEFT JOIN teams ta ON f.away_team_id = ta.id
                WHERE f.date >= :utc_start AND f.date < :utc_end
                {league_filter}
                ORDER BY l.country, l.name, f.date
            """.format(
                league_filter="AND f.league_id = :league_id" if self.selected_league_id else ""
            ))
            
            params = {'utc_start': utc_start_str, 'utc_end': utc_end_str}
            if self.selected_league_id:
                params['league_id'] = self.selected_league_id
            
            results = session.execute(query, params).fetchall()
            
            # Obtener odds para estos fixtures
            fixture_ids = [r.fixture_id for r in results]
            odds_map = self._load_odds(session, fixture_ids)
            
            session.close()
            
            if not results:
                self._show_no_matches()
                return
            
            # Agrupar por liga
            leagues_dict = defaultdict(list)
            for row in results:
                # Determinar nombre de liga
                if row.league_name:
                    league_name = row.league_name
                elif row.league_id:
                    # Buscar en diccionario de ligas conocidas o mostrar ID
                    league_name = self._get_league_name_fallback(row.league_id)
                else:
                    league_name = 'Sin Liga'
                
                league_country = row.league_country or ''
                league_key = (row.league_id, league_name, league_country)
                
                match_data = {
                    'fixture_id': row.fixture_id,
                    'date': row.date,
                    'status_short': row.status_short,
                    'status_long': row.status_long,
                    'elapsed': row.elapsed,
                    'goals_home': row.goals_home,
                    'goals_away': row.goals_away,
                    'home_name': row.home_name or 'Local',
                    'away_name': row.away_name or 'Visitante',
                    'odds': odds_map.get(row.fixture_id, {}),
                    'league_id': row.league_id,  # Para mostrar en header
                }
                leagues_dict[league_key].append(match_data)
            
            # Crear widgets por liga
            total_matches = 0
            for (league_id, league_name, country), matches in leagues_dict.items():
                league_widget = LeagueGroupWidget(league_id, league_name, country, matches)
                league_widget.match_clicked.connect(self._on_match_clicked)
                league_widget.analysis_requested.connect(self._on_analysis_requested)
                self.content_layout.addWidget(league_widget)
                total_matches += len(matches)
            
            self.content_layout.addStretch()
            
            # Actualizar info
            self.info_label.setText(
                f"📅 {self.selected_date.toString('dd/MM/yyyy')} | "
                f"⚽ {total_matches} partidos | "
                f"🏆 {len(leagues_dict)} ligas"
            )
            
        except Exception as e:
            logger.error(f"Error cargando partidos: {e}")
            self._show_error(f"Error: {str(e)}")
    
    def _load_odds(self, session, fixture_ids: List[int]) -> Dict[int, Dict]:
        """Carga odds 1X2 para los fixtures."""
        odds_map = {}
        
        if not fixture_ids:
            return odds_map
        
        try:
            # Buscar odds de tipo "Match Winner" o similar
            query = text("""
                SELECT fixture_id, value, odd
                FROM odds
                WHERE fixture_id IN :ids
                AND (bet_name LIKE '%Winner%' OR bet_name LIKE '%1X2%' OR bet_id = 1)
            """)
            
            results = session.execute(query, {'ids': tuple(fixture_ids)}).fetchall()
            
            for row in results:
                fixture_id = row.fixture_id
                value = row.value.lower() if row.value else ''
                odd = row.odd
                
                if fixture_id not in odds_map:
                    odds_map[fixture_id] = {}
                
                if 'home' in value or value == '1':
                    odds_map[fixture_id]['home'] = odd
                elif 'draw' in value or value == 'x':
                    odds_map[fixture_id]['draw'] = odd
                elif 'away' in value or value == '2':
                    odds_map[fixture_id]['away'] = odd
                    
        except Exception as e:
            logger.warning(f"Error cargando odds: {e}")
        
        return odds_map
    
    def _show_no_matches(self):
        """Muestra mensaje cuando no hay partidos."""
        label = QLabel("📭 No hay partidos para esta fecha")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("""
            font-size: 16px;
            color: #888;
            padding: 50px;
        """)
        self.content_layout.addWidget(label)
        self.content_layout.addStretch()
        
        self.info_label.setText(f"📅 {self.selected_date.toString('dd/MM/yyyy')} | Sin partidos")
    
    def _show_error(self, message: str):
        """Muestra mensaje de error."""
        label = QLabel(f"❌ {message}")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("""
            font-size: 14px;
            color: #E53935;
            padding: 50px;
        """)
        self.content_layout.addWidget(label)
        self.content_layout.addStretch()
        
        self.info_label.setText("Error al cargar datos")
    
    def _on_match_clicked(self, fixture_id: int):
        """Maneja clic en un partido - muestra info básica."""
        logger.info(f"Partido seleccionado: {fixture_id}")
        # Click simple solo loguea, el botón de análisis abre la ventana
    
    def _on_analysis_requested(self, fixture_id: int):
        """Abre el análisis pre-partido para el fixture seleccionado."""
        logger.info(f"Abriendo análisis pre-partido para fixture: {fixture_id}")
        
        try:
            # Importar PreMatchAnalysisWindow
            import sys
            import os
            
            # Agregar path si es necesario
            src_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            
            from ui.pre_match_analysis_window import PreMatchAnalysisWindow
            
            # Crear y mostrar la ventana de análisis con el fixture_id
            # El constructor ahora acepta fixture_id y lo carga automáticamente
            self.pre_match_window = PreMatchAnalysisWindow(fixture_id=fixture_id)
            self.pre_match_window.show()
            self.pre_match_window.raise_()
            self.pre_match_window.activateWindow()
            
        except ImportError as e:
            logger.error(f"Error importando PreMatchAnalysisWindow: {e}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Módulo no disponible",
                f"El módulo de Análisis Pre-Partido no está disponible:\n{str(e)}\n\n"
                f"Fixture ID: {fixture_id}"
            )
        except Exception as e:
            logger.error(f"Error abriendo análisis pre-partido: {e}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                "Error",
                f"Error al abrir análisis pre-partido:\n{str(e)}"
            )


# =============================================================================
# Punto de entrada para pruebas
# =============================================================================

if __name__ == "__main__":
    import sys
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    dialog = MatchViewerDialog()
    dialog.show()
    
    sys.exit(app.exec())