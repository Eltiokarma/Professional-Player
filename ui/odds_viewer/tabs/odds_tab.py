# ui/odds_viewer/tabs/odds_tab.py
# -*- coding: utf-8 -*-
"""
Tab de visualizaciÃ³n de cuotas estilo casa de apuestas.
MEJORADO: Muestra TODAS las cuotas con indicador de resultado.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QDateEdit, QPushButton, QScrollArea, QFrame, QGroupBox,
    QLineEdit, QSizePolicy, QMessageBox, QDialog,
    QDialogButtonBox, QGridLayout, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox
)
from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtGui import QColor

from ..styles.colors import Colors, Styles
from ..models.database_queries import OddsQueryModel
from ..models.data_models import FixtureWithOdds, MatchResult

logger = logging.getLogger(__name__)


class OddResultWidget(QFrame):
    """Widget que muestra una cuota con indicador de si saliÃ³ o no."""
    
    def __init__(self, bet_name: str, value: str, odd: float, won: Optional[bool] = None, parent=None):
        super().__init__(parent)
        self.bet_name = bet_name
        self.value = value
        self.odd = odd
        self.won = won
        
        self._setup_ui()
    
    def _setup_ui(self):
        if self.won is True:
            bg_color = "#D4EDDA"
            border_color = Colors.WIN
            icon = "âœ…"
        elif self.won is False:
            bg_color = "#F8D7DA"
            border_color = Colors.LOSS
            icon = "âŒ"
        else:
            bg_color = Colors.CARD
            border_color = Colors.BORDER
            icon = "âšª"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 2px solid {border_color};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        
        value_layout = QHBoxLayout()
        
        lbl_value = QLabel(self.value)
        lbl_value.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        value_layout.addWidget(lbl_value)
        
        value_layout.addStretch()
        
        lbl_icon = QLabel(icon)
        lbl_icon.setStyleSheet("font-size: 14px;")
        value_layout.addWidget(lbl_icon)
        
        layout.addLayout(value_layout)
        
        lbl_odd = QLabel(f"{self.odd:.2f}")
        lbl_odd.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {Colors.get_odd_color(self.odd)};
        """)
        lbl_odd.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_odd)
        
        self.setMinimumWidth(80)
        self.setMaximumWidth(120)


class MatchDetailDialog(QDialog):
    """DiÃ¡logo que muestra TODAS las cuotas de un partido."""
    
    def __init__(self, fixture_with_odds: FixtureWithOdds, db_model: OddsQueryModel, parent=None):
        super().__init__(parent)
        self.fixture = fixture_with_odds.fixture
        self.odds = fixture_with_odds.odds
        self.db = db_model
        
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWindowTitle(f"ðŸ“‹ {self.fixture.home_team_name} vs {self.fixture.away_team_name}")
        self.setMinimumSize(800, 600)
        self.resize(900, 700)
        
        # Fondo claro explicito para no heredar tema oscuro del sistema
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {Colors.BACKGROUND};
                color: {Colors.TEXT_PRIMARY};
            }}
            QDialogButtonBox QPushButton {{
                background-color: {Colors.CARD};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
                padding: 8px 20px;
            }}
            QDialogButtonBox QPushButton:hover {{
                background-color: {Colors.CARD_HOVER};
                border-color: {Colors.ACCENT};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Header
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.PRIMARY};
                border-radius: 10px;
            }}
        """)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 15)
        
        teams_layout = QHBoxLayout()
        
        lbl_home = QLabel(f"ðŸ  {self.fixture.home_team_name}")
        lbl_home.setStyleSheet(f"color: white; font-size: 18px; font-weight: bold;")
        teams_layout.addWidget(lbl_home)
        
        teams_layout.addStretch()
        
        lbl_score = QLabel(self.fixture.score_str)
        lbl_score.setStyleSheet(f"color: {Colors.ACCENT}; font-size: 28px; font-weight: bold;")
        teams_layout.addWidget(lbl_score)
        
        teams_layout.addStretch()
        
        lbl_away = QLabel(f"{self.fixture.away_team_name} ðŸšŒ")
        lbl_away.setStyleSheet(f"color: white; font-size: 18px; font-weight: bold;")
        teams_layout.addWidget(lbl_away)
        
        header_layout.addLayout(teams_layout)
        
        date_str = self.fixture.date.strftime("%d/%m/%Y %H:%M") if self.fixture.date else "--"
        lbl_info = QLabel(f"ðŸ“… {date_str}  |  ðŸ† {self.fixture.league_name}  |  ID: {self.fixture.fixture_id}")
        lbl_info.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 12px;")
        header_layout.addWidget(lbl_info)
        
        layout.addWidget(header)
        
        # Leyenda
        legend = QLabel("âœ… = Apuesta GANADORA  |  âŒ = Apuesta PERDEDORA  |  âšª = No determinado")
        legend.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px; padding: 5px;")
        legend.setAlignment(Qt.AlignCenter)
        layout.addWidget(legend)
        
        # Scroll de mercados
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {Colors.BACKGROUND}; }}")
        
        markets_widget = QWidget()
        markets_layout = QVBoxLayout(markets_widget)
        markets_layout.setSpacing(15)
        
        all_odds = self.db.get_odds_for_fixture(self.fixture.fixture_id)
        
        # Filtrar por bookmaker preferido para consistencia con la card
        preferred_bm = self.db._get_preferred_bookmaker(self.fixture.fixture_id)
        if preferred_bm:
            all_odds = [o for o in all_odds if o.bookmaker_name == preferred_bm]
        
        markets = {}
        for odd in all_odds:
            if odd.bet_name not in markets:
                markets[odd.bet_name] = []
            markets[odd.bet_name].append(odd)
        
        for market_name, market_odds in sorted(markets.items()):
            market_frame = self._create_market_panel(market_name, market_odds)
            markets_layout.addWidget(market_frame)
        
        if not markets:
            no_odds = QLabel("ðŸ“­ No hay cuotas disponibles")
            no_odds.setAlignment(Qt.AlignCenter)
            no_odds.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 16px; padding: 50px;")
            markets_layout.addWidget(no_odds)
        
        markets_layout.addStretch()
        scroll.setWidget(markets_widget)
        layout.addWidget(scroll)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _create_market_panel(self, market_name: str, odds_list) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
            }}
        """)
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 12, 15, 12)
        
        title = QLabel(f"ðŸ“Š {market_name}")
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)
        
        odds_layout = QHBoxLayout()
        odds_layout.setSpacing(10)
        
        for odd in odds_list:
            won = self._evaluate_bet(market_name, odd.value)
            widget = OddResultWidget(market_name, odd.value, odd.odd, won)
            odds_layout.addWidget(widget)
        
        odds_layout.addStretch()
        layout.addLayout(odds_layout)
        
        return frame
    
    def _evaluate_bet(self, market_name: str, value: str) -> Optional[bool]:
        if self.fixture.goals_home is None or self.fixture.goals_away is None:
            return None
        
        goals_home = self.fixture.goals_home
        goals_away = self.fixture.goals_away
        total_goals = goals_home + goals_away
        result = self.fixture.result
        
        market_lower = market_name.lower()
        value_lower = value.lower()
        
        # Match Winner / 1X2
        if 'winner' in market_lower or '1x2' in market_lower or 'result' in market_lower:
            if 'home' in value_lower or value == '1':
                return result == MatchResult.HOME_WIN
            elif 'away' in value_lower or value == '2':
                return result == MatchResult.AWAY_WIN
            elif 'draw' in value_lower or value.lower() == 'x':
                return result == MatchResult.DRAW
        
        # Over/Under
        if 'over' in market_lower or 'under' in market_lower or 'goals' in market_lower:
            try:
                import re
                numbers = re.findall(r'[\d.]+', value)
                if numbers:
                    line = float(numbers[0])
                    if 'over' in value_lower:
                        return total_goals > line
                    elif 'under' in value_lower:
                        return total_goals < line
            except:
                pass
        
        # Double Chance
        if 'double' in market_lower:
            if '1x' in value_lower or ('home' in value_lower and 'draw' in value_lower):
                return result in [MatchResult.HOME_WIN, MatchResult.DRAW]
            elif 'x2' in value_lower or ('away' in value_lower and 'draw' in value_lower):
                return result in [MatchResult.AWAY_WIN, MatchResult.DRAW]
            elif '12' in value_lower:
                return result in [MatchResult.HOME_WIN, MatchResult.AWAY_WIN]
        
        # Both Teams to Score
        if 'both' in market_lower or 'btts' in market_lower:
            both_scored = goals_home > 0 and goals_away > 0
            if 'yes' in value_lower or 'si' in value_lower:
                return both_scored
            elif 'no' in value_lower:
                return not both_scored
        
        # Correct Score
        if 'correct' in market_lower or 'score' in market_lower:
            try:
                parts = value.replace('-', ':').split(':')
                if len(parts) == 2:
                    ph = int(parts[0].strip())
                    pa = int(parts[1].strip())
                    return goals_home == ph and goals_away == pa
            except:
                pass
        
        return None


class MatchCardEnhanced(QFrame):
    """Tarjeta de partido mejorada."""
    
    clicked = Signal(int)
    view_details = Signal(object)
    
    def __init__(self, fixture_with_odds: FixtureWithOdds, db_model: OddsQueryModel = None, parent=None):
        super().__init__(parent)
        self.fixture_with_odds = fixture_with_odds
        self.fixture = fixture_with_odds.fixture
        self.db_model = db_model
        
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
            }}
            QFrame:hover {{
                border-color: {Colors.ACCENT};
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        date_str = self.fixture.date.strftime("%d/%m/%Y %H:%M") if self.fixture.date else "--"
        lbl_date = QLabel(f"ðŸ“… {date_str}")
        lbl_date.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        header_layout.addWidget(lbl_date)
        
        header_layout.addStretch()
        
        lbl_id = QLabel(f"ID: {self.fixture.fixture_id}")
        lbl_id.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        header_layout.addWidget(lbl_id)
        
        layout.addLayout(header_layout)
        
        # Equipos y Marcador
        match_layout = QHBoxLayout()
        
        lbl_home = QLabel(f"ðŸ  {self.fixture.home_team_name}")
        lbl_home.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        match_layout.addWidget(lbl_home, 2)
        
        lbl_score = QLabel(self.fixture.score_str)
        lbl_score.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {Colors.ACCENT};")
        lbl_score.setAlignment(Qt.AlignCenter)
        match_layout.addWidget(lbl_score, 1)
        
        lbl_away = QLabel(f"{self.fixture.away_team_name} ðŸšŒ")
        lbl_away.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        lbl_away.setAlignment(Qt.AlignRight)
        match_layout.addWidget(lbl_away, 2)
        
        layout.addLayout(match_layout)
        
        # Cuotas principales con resultado
        odds_layout = QHBoxLayout()
        odds_layout.setSpacing(8)
        
        # Usar db_model para odds consistentes (mismo bookmaker en card y detalle)
        if self.db_model:
            odds_1x2 = self.db_model.get_1x2_odds(self.fixture.fixture_id)
        else:
            odds_1x2 = self.fixture_with_odds.get_1x2_odds()
        if odds_1x2:
            result = self.fixture.result
            
            home_won = result == MatchResult.HOME_WIN if result else None
            odds_layout.addWidget(self._mini_odd("1", odds_1x2.get("Home", 0), home_won))
            
            draw_won = result == MatchResult.DRAW if result else None
            odds_layout.addWidget(self._mini_odd("X", odds_1x2.get("Draw", 0), draw_won))
            
            away_won = result == MatchResult.AWAY_WIN if result else None
            odds_layout.addWidget(self._mini_odd("2", odds_1x2.get("Away", 0), away_won))
        
        odds_layout.addStretch()
        
        if self.db_model:
            odds_ou = self.db_model.get_over_under_odds(self.fixture.fixture_id, 2.5)
        else:
            odds_ou = self.fixture_with_odds.get_over_under_odds(2.5)
        if odds_ou and self.fixture.goals_home is not None:
            total = self.fixture.goals_home + self.fixture.goals_away
            odds_layout.addWidget(self._mini_odd("+2.5", odds_ou.get("Over", 0), total > 2.5))
            odds_layout.addWidget(self._mini_odd("-2.5", odds_ou.get("Under", 0), total < 2.5))
        
        layout.addLayout(odds_layout)
        
        # Footer
        footer_layout = QHBoxLayout()
        
        total_odds = sum(len(v) for v in self.fixture_with_odds.odds.values())
        lbl_markets = QLabel(f"ðŸ“Š {len(self.fixture_with_odds.odds)} mercados â€¢ {total_odds} cuotas")
        lbl_markets.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        footer_layout.addWidget(lbl_markets)
        
        footer_layout.addStretch()
        
        btn_details = QPushButton("Ver TODAS las cuotas â†’")
        btn_details.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ACCENT};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {Colors.ACCENT_HOVER}; }}
        """)
        btn_details.clicked.connect(lambda: self.view_details.emit(self.fixture_with_odds))
        footer_layout.addWidget(btn_details)
        
        layout.addLayout(footer_layout)
    
    def _mini_odd(self, label: str, odd: float, won: Optional[bool]) -> QFrame:
        frame = QFrame()
        
        if won is True:
            bg, border = "#D4EDDA", Colors.WIN
        elif won is False:
            bg, border = "#F8D7DA", Colors.LOSS
        else:
            bg, border = Colors.ODD_BUTTON_BG, Colors.BORDER
        
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 5px;
            }}
        """)
        
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(1)
        
        lbl_label = QLabel(label)
        lbl_label.setStyleSheet(f"font-size: 10px; color: {Colors.TEXT_SECONDARY};")
        lbl_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_label)
        
        lbl_odd = QLabel(f"{odd:.2f}" if odd else "-")
        lbl_odd.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        lbl_odd.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_odd)
        
        frame.setFixedWidth(55)
        return frame


class OddsTab(QWidget):
    """Tab de visualizaciÃ³n de cuotas MEJORADO."""
    
    fixture_selected = Signal(int)
    
    def __init__(self, db_model: OddsQueryModel, parent=None):
        super().__init__(parent)
        self.db = db_model
        self.current_fixtures: List[FixtureWithOdds] = []
        
        self._setup_ui()
        self._load_initial_data()
    
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        header = self._create_header()
        main_layout.addWidget(header)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {Colors.BACKGROUND}; }}")
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(15, 15, 15, 15)
        self.content_layout.setSpacing(15)
        
        scroll.setWidget(self.content_widget)
        main_layout.addWidget(scroll)
    
    def _create_header(self) -> QWidget:
        header = QFrame()
        header.setStyleSheet(f"QFrame {{ background-color: {Colors.PRIMARY}; }}")
        
        layout = QVBoxLayout(header)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)
        
        title_layout = QHBoxLayout()
        
        title = QLabel("ðŸ† VISOR DE CUOTAS")
        title.setStyleSheet(f"color: white; font-size: 22px; font-weight: bold;")
        title_layout.addWidget(title)
        
        title_layout.addStretch()
        
        legend = QLabel("âœ… GanÃ³  |  âŒ PerdiÃ³")
        legend.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 12px;")
        title_layout.addWidget(legend)
        
        layout.addLayout(title_layout)
        
        # Filtros fila 1
        f1 = QHBoxLayout()
        f1.setSpacing(15)
        
        f1.addWidget(self._label("Liga:"))
        self.combo_league = QComboBox()
        self.combo_league.setStyleSheet(self._combo_style())
        self.combo_league.setMinimumWidth(200)
        self.combo_league.currentIndexChanged.connect(self._on_league_changed)
        f1.addWidget(self.combo_league)
        
        f1.addWidget(self._label("Temporada:"))
        self.combo_season = QComboBox()
        self.combo_season.setStyleSheet(self._combo_style())
        self.combo_season.currentIndexChanged.connect(self._on_season_changed)
        f1.addWidget(self.combo_season)
        
        f1.addWidget(self._label("Equipo:"))
        self.combo_team = QComboBox()
        self.combo_team.setStyleSheet(self._combo_style())
        self.combo_team.setMinimumWidth(180)
        f1.addWidget(self.combo_team)
        
        f1.addStretch()
        layout.addLayout(f1)
        
        # Filtros fila 2
        f2 = QHBoxLayout()
        f2.setSpacing(15)
        
        f2.addWidget(self._label("Desde:"))
        self.date_from = QDateEdit()
        self.date_from.setStyleSheet(self._combo_style())
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addMonths(-3))
        f2.addWidget(self.date_from)
        
        f2.addWidget(self._label("Hasta:"))
        self.date_to = QDateEdit()
        self.date_to.setStyleSheet(self._combo_style())
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        f2.addWidget(self.date_to)
        
        f2.addStretch()
        
        self.btn_filter = QPushButton("ðŸ”„ FILTRAR")
        self.btn_filter.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ACCENT};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px 25px;
                font-weight: bold;
                font-size: 14px;
            }}
            QPushButton:hover {{ background-color: {Colors.ACCENT_HOVER}; }}
        """)
        self.btn_filter.clicked.connect(self._load_fixtures)
        f2.addWidget(self.btn_filter)
        
        layout.addLayout(f2)
        
        self.lbl_info = QLabel("Selecciona filtros y haz clic en FILTRAR")
        self.lbl_info.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(self.lbl_info)
        
        return header
    
    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: white; font-size: 13px;")
        return lbl
    
    def _combo_style(self) -> str:
        return f"""
            QComboBox, QDateEdit {{
                background-color: {Colors.SECONDARY};
                color: white;
                border: 1px solid {Colors.TEXT_MUTED};
                border-radius: 6px;
                padding: 8px 12px;
                min-width: 100px;
            }}
            QComboBox:hover, QDateEdit:hover {{ border-color: {Colors.ACCENT}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {Colors.SECONDARY};
                color: white;
                selection-background-color: {Colors.ACCENT};
            }}
            QCalendarWidget {{
                background-color: white;
            }}
            QCalendarWidget QAbstractItemView {{
                background-color: white;
                color: {Colors.TEXT_PRIMARY};
                selection-background-color: {Colors.ACCENT};
                selection-color: white;
            }}
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background-color: {Colors.PRIMARY};
                color: white;
            }}
            QCalendarWidget QToolButton {{
                background-color: {Colors.PRIMARY};
                color: white;
                border: none;
                padding: 4px 8px;
                font-weight: bold;
            }}
            QCalendarWidget QToolButton:hover {{
                background-color: {Colors.ACCENT};
            }}
            QCalendarWidget QSpinBox {{
                background-color: {Colors.PRIMARY};
                color: white;
                border: 1px solid {Colors.TEXT_MUTED};
            }}
            QCalendarWidget QMenu {{
                background-color: white;
                color: {Colors.TEXT_PRIMARY};
            }}
            QCalendarWidget QMenu::item:selected {{
                background-color: {Colors.ACCENT};
                color: white;
            }}
        """
    
    def _load_initial_data(self):
        try:
            leagues = self.db.get_leagues()
            self.combo_league.clear()
            self.combo_league.addItem("-- Seleccionar Liga --", None)
            for league in leagues:
                self.combo_league.addItem(f"{league['name']} ({league['fixtures']})", league['id'])
        except Exception as e:
            logger.error(f"Error: {e}")
    
    def _on_league_changed(self):
        league_id = self.combo_league.currentData()
        
        self.combo_season.clear()
        self.combo_season.addItem("Todas", None)
        if league_id:
            seasons = self.db.get_seasons(league_id)
            for season in seasons:
                self.combo_season.addItem(str(season), season)
        
        self._load_teams()
    
    def _on_season_changed(self):
        self._load_teams()
    
    def _load_teams(self):
        league_id = self.combo_league.currentData()
        season = self.combo_season.currentData()
        
        self.combo_team.clear()
        self.combo_team.addItem("Todos los equipos", None)
        
        if league_id:
            teams = self.db.get_teams(league_id, season)
            for team in teams:
                self.combo_team.addItem(team['name'], team['id'])
    
    def _load_fixtures(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        league_id = self.combo_league.currentData()
        season = self.combo_season.currentData()
        team_id = self.combo_team.currentData()
        from_date = datetime.combine(self.date_from.date().toPython(), datetime.min.time())
        to_date = datetime.combine(self.date_to.date().toPython(), datetime.max.time())
        
        try:
            self.current_fixtures = self.db.get_fixtures_with_odds(
                league_id=league_id,
                season=season,
                team_id=team_id,
                limit=300
            )
            
            self.current_fixtures = [
                f for f in self.current_fixtures
                if f.fixture.date and from_date <= f.fixture.date <= to_date
            ]
            
            if not self.current_fixtures:
                self.lbl_info.setText("ðŸ“­ No se encontraron partidos")
                no_data = QLabel("No hay partidos con cuotas para estos filtros")
                no_data.setAlignment(Qt.AlignCenter)
                no_data.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 16px; padding: 50px;")
                self.content_layout.addWidget(no_data)
                return
            
            by_league = {}
            for f in self.current_fixtures:
                ln = f.fixture.league_name
                if ln not in by_league:
                    by_league[ln] = []
                by_league[ln].append(f)
            
            total = 0
            for league_name, fixtures in sorted(by_league.items()):
                header = self._create_league_header(league_name, len(fixtures))
                self.content_layout.addWidget(header)
                
                for fixture in sorted(fixtures, key=lambda x: x.fixture.date, reverse=True):
                    card = MatchCardEnhanced(fixture, db_model=self.db)
                    card.view_details.connect(self._show_match_details)
                    self.content_layout.addWidget(card)
                    total += 1
            
            self.content_layout.addStretch()
            self.lbl_info.setText(f"âœ… {total} partidos encontrados")
            
        except Exception as e:
            logger.error(f"Error: {e}")
            self.lbl_info.setText(f"âŒ Error: {str(e)}")
    
    def _create_league_header(self, name: str, count: int) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background-color: {Colors.SECONDARY}; border-radius: 8px; }}")
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(15, 10, 15, 10)
        
        lbl = QLabel(f"ðŸ† {name}")
        lbl.setStyleSheet(f"color: white; font-size: 16px; font-weight: bold;")
        layout.addWidget(lbl)
        
        layout.addStretch()
        
        lbl_count = QLabel(f"{count} partidos")
        lbl_count.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 13px;")
        layout.addWidget(lbl_count)
        
        return frame
    
    def _show_match_details(self, fixture_with_odds: FixtureWithOdds):
        dialog = MatchDetailDialog(fixture_with_odds, self.db, self)
        dialog.exec()