# ui/odds_viewer/widgets/match_widgets.py
# -*- coding: utf-8 -*-
"""
Widgets para visualización de partidos y cuotas.
VERSION CORREGIDA - KPIs visibles con texto negro.
"""

from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from ..styles.colors import Colors
from ..models.data_models import FixtureWithOdds, FixtureData


class OddButton(QPushButton):
    """Botón de cuota estilo casa de apuestas."""
    
    clicked_with_data = Signal(str, float)
    
    def __init__(self, label: str, odd: float, parent=None):
        super().__init__(parent)
        self.label = label
        self.odd = odd
        
        self._setup_ui()
        self.clicked.connect(self._on_clicked)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        
        lbl_text = QLabel(self.label)
        lbl_text.setAlignment(Qt.AlignCenter)
        lbl_text.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        layout.addWidget(lbl_text)
        
        odd_text = f"{self.odd:.2f}" if self.odd else "-"
        lbl_odd = QLabel(odd_text)
        lbl_odd.setAlignment(Qt.AlignCenter)
        lbl_odd.setStyleSheet(f"""
            color: {Colors.get_odd_color(self.odd)};
            font-size: 16px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(lbl_odd)
        
        self.setMinimumWidth(70)
        self.setMinimumHeight(55)
        
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ODD_BUTTON_BG};
                border: 1px solid {Colors.BORDER};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {Colors.ODD_BUTTON_HOVER};
                border-color: {Colors.ACCENT};
            }}
        """)
    
    def _on_clicked(self):
        self.clicked_with_data.emit(self.label, self.odd)


class MarketPanel(QFrame):
    """Panel de un mercado de apuestas."""
    
    def __init__(self, title: str, odds: dict, parent=None):
        super().__init__(parent)
        self.title = title
        self.odds = odds
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        
        title_label = QLabel(self.title)
        title_label.setStyleSheet(f"""
            color: {Colors.TEXT_SECONDARY};
            font-size: 11px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(title_label)
        
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(6)
        
        for label, odd in self.odds.items():
            btn = OddButton(label, odd or 0)
            buttons_layout.addWidget(btn)
        
        layout.addLayout(buttons_layout)


class KPICard(QFrame):
    """
    Tarjeta de indicador KPI - VERSION CORREGIDA.
    Usa colores oscuros para texto visible.
    """
    
    def __init__(
        self,
        title: str,
        value: str = "0",
        subtitle: str = "",
        color: str = None,
        icon: str = "",
        parent=None
    ):
        super().__init__(parent)
        
        self._color = color or "#333333"
        
        # Crear el frame con estilo
        self.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 12px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(4)
        
        # Título con icono
        title_text = f"{icon} {title}" if icon else title
        self.title_label = QLabel(title_text)
        self.title_label.setStyleSheet("""
            color: #666666;
            font-size: 11px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(self.title_label)
        
        # Valor principal - TEXTO GRANDE Y VISIBLE
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"""
            color: {self._color};
            font-size: 24px;
            font-weight: bold;
            background: transparent;
        """)
        layout.addWidget(self.value_label)
        
        # Subtítulo
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setStyleSheet("""
                color: #999999;
                font-size: 10px;
                background: transparent;
            """)
            layout.addWidget(self.subtitle_label)
        
        self.setMinimumWidth(130)
        self.setMinimumHeight(85)
    
    def update_value(self, value: str, color: str = None):
        """Actualiza el valor del KPI."""
        self.value_label.setText(str(value))
        if color:
            self._color = color
            self.value_label.setStyleSheet(f"""
                color: {color};
                font-size: 24px;
                font-weight: bold;
                background: transparent;
            """)


class MatchCard(QFrame):
    """Tarjeta de partido estilo casa de apuestas."""
    
    clicked = Signal(int)
    view_details = Signal(int)
    
    def __init__(self, fixture_with_odds: FixtureWithOdds = None, parent=None):
        super().__init__(parent)
        self.fixture_with_odds = fixture_with_odds
        self.fixture = fixture_with_odds.fixture if fixture_with_odds else None
        
        self._setup_ui()
        
        if fixture_with_odds:
            self.set_data(fixture_with_odds)
    
    def _setup_ui(self):
        self.setCursor(Qt.PointingHandCursor)
        
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
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 12, 15, 12)
        main_layout.setSpacing(10)
        
        # Header
        header_layout = QHBoxLayout()
        
        self.lbl_date = QLabel("📅 --/--/----")
        self.lbl_date.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        header_layout.addWidget(self.lbl_date)
        
        header_layout.addStretch()
        
        self.lbl_id = QLabel("ID: ------")
        self.lbl_id.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px; background: transparent;")
        header_layout.addWidget(self.lbl_id)
        
        main_layout.addLayout(header_layout)
        
        # Equipos
        teams_layout = QHBoxLayout()
        teams_layout.setSpacing(15)
        
        home_layout = QVBoxLayout()
        self.lbl_home_icon = QLabel("🏠")
        self.lbl_home_icon.setStyleSheet("background: transparent;")
        home_layout.addWidget(self.lbl_home_icon, alignment=Qt.AlignCenter)
        
        self.lbl_home = QLabel("Equipo Local")
        self.lbl_home.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold; background: transparent;")
        self.lbl_home.setAlignment(Qt.AlignCenter)
        self.lbl_home.setWordWrap(True)
        home_layout.addWidget(self.lbl_home)
        
        teams_layout.addLayout(home_layout, 2)
        
        score_layout = QVBoxLayout()
        self.lbl_score = QLabel("vs")
        self.lbl_score.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 24px; font-weight: bold; background: transparent;")
        self.lbl_score.setAlignment(Qt.AlignCenter)
        score_layout.addWidget(self.lbl_score)
        
        teams_layout.addLayout(score_layout, 1)
        
        away_layout = QVBoxLayout()
        self.lbl_away_icon = QLabel("🚌")
        self.lbl_away_icon.setStyleSheet("background: transparent;")
        away_layout.addWidget(self.lbl_away_icon, alignment=Qt.AlignCenter)
        
        self.lbl_away = QLabel("Equipo Visitante")
        self.lbl_away.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold; background: transparent;")
        self.lbl_away.setAlignment(Qt.AlignCenter)
        self.lbl_away.setWordWrap(True)
        away_layout.addWidget(self.lbl_away)
        
        teams_layout.addLayout(away_layout, 2)
        
        main_layout.addLayout(teams_layout)
        
        # Mercados
        self.markets_layout = QHBoxLayout()
        self.markets_layout.setSpacing(10)
        main_layout.addLayout(self.markets_layout)
        
        # Footer
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        
        self.btn_details = QPushButton("📊 Ver más")
        self.btn_details.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {Colors.ACCENT};
                border: none;
                font-size: 12px;
            }}
            QPushButton:hover {{ text-decoration: underline; }}
        """)
        self.btn_details.clicked.connect(self._on_details_clicked)
        footer_layout.addWidget(self.btn_details)
        
        main_layout.addLayout(footer_layout)
    
    def set_data(self, fixture_with_odds: FixtureWithOdds):
        self.fixture_with_odds = fixture_with_odds
        self.fixture = fixture_with_odds.fixture
        
        date_str = self.fixture.date.strftime("%d/%m/%Y • %H:%M") if self.fixture.date else "--"
        self.lbl_date.setText(f"📅 {date_str}")
        self.lbl_id.setText(f"ID: {self.fixture.fixture_id}")
        
        self.lbl_home.setText(self.fixture.home_team_name)
        self.lbl_away.setText(self.fixture.away_team_name)
        self.lbl_score.setText(self.fixture.score_str)
        
        while self.markets_layout.count():
            item = self.markets_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        odds_1x2 = fixture_with_odds.get_1x2_odds()
        if odds_1x2:
            panel_1x2 = MarketPanel("Ganador", {
                "1": odds_1x2.get("Home", 0),
                "X": odds_1x2.get("Draw", 0),
                "2": odds_1x2.get("Away", 0)
            })
            self.markets_layout.addWidget(panel_1x2)
        
        odds_ou = fixture_with_odds.get_over_under_odds(2.5)
        if odds_ou:
            panel_ou = MarketPanel("Total Goles", {
                "+2.5": odds_ou.get("Over", 0),
                "-2.5": odds_ou.get("Under", 0)
            })
            self.markets_layout.addWidget(panel_ou)
        
        self.markets_layout.addStretch()
    
    def _on_details_clicked(self):
        if self.fixture:
            self.view_details.emit(self.fixture.fixture_id)
    
    def mousePressEvent(self, event):
        if self.fixture:
            self.clicked.emit(self.fixture.fixture_id)
        super().mousePressEvent(event)


class BetResultRow(QFrame):
    """Fila de resultado de apuesta."""
    
    def __init__(self, bet_result, row_number: int, parent=None):
        super().__init__(parent)
        self.bet_result = bet_result
        self.row_number = row_number
        self._setup_ui()
    
    def _setup_ui(self):
        bg_color = "#FFFFFF" if self.row_number % 2 == 0 else "#F8F9FA"
        result_color = "#28A745" if self.bet_result.bet_won else "#DC3545"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-bottom: 1px solid #E0E0E0;
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        
        lbl_num = QLabel(str(self.row_number))
        lbl_num.setFixedWidth(30)
        lbl_num.setStyleSheet("color: #999999; background: transparent;")
        layout.addWidget(lbl_num)
        
        date_str = self.bet_result.date.strftime("%d/%m/%y")
        lbl_date = QLabel(date_str)
        lbl_date.setFixedWidth(70)
        lbl_date.setStyleSheet("color: #333333; background: transparent;")
        layout.addWidget(lbl_date)
        
        rival = self.bet_result.away_team if self.bet_result.is_home else self.bet_result.home_team
        lbl_rival = QLabel(rival)
        lbl_rival.setMinimumWidth(120)
        lbl_rival.setStyleSheet("color: #333333; background: transparent;")
        layout.addWidget(lbl_rival, 2)
        
        lbl_loc = QLabel(self.bet_result.location_emoji)
        lbl_loc.setFixedWidth(30)
        lbl_loc.setAlignment(Qt.AlignCenter)
        lbl_loc.setStyleSheet("background: transparent;")
        layout.addWidget(lbl_loc)
        
        result_str = f"{self.bet_result.result_str} {self.bet_result.result_emoji}"
        lbl_result = QLabel(result_str)
        lbl_result.setFixedWidth(60)
        lbl_result.setStyleSheet(f"color: {result_color}; font-weight: bold; background: transparent;")
        layout.addWidget(lbl_result)
        
        lbl_odd = QLabel(f"{self.bet_result.odd:.2f}")
        lbl_odd.setFixedWidth(50)
        lbl_odd.setAlignment(Qt.AlignRight)
        lbl_odd.setStyleSheet("color: #333333; background: transparent;")
        layout.addWidget(lbl_odd)
        
        lbl_stake = QLabel(f"€{self.bet_result.stake:.2f}")
        lbl_stake.setFixedWidth(60)
        lbl_stake.setAlignment(Qt.AlignRight)
        lbl_stake.setStyleSheet("color: #333333; background: transparent;")
        layout.addWidget(lbl_stake)
        
        lbl_pl = QLabel(self.bet_result.profit_loss_str)
        lbl_pl.setFixedWidth(70)
        lbl_pl.setAlignment(Qt.AlignRight)
        lbl_pl.setStyleSheet(f"color: {result_color}; font-weight: bold; background: transparent;")
        layout.addWidget(lbl_pl)
        
        indicator = QLabel("🟢" if self.bet_result.bet_won else "🔴")
        indicator.setFixedWidth(25)
        indicator.setStyleSheet("background: transparent;")
        layout.addWidget(indicator)


class TeamRankingBar(QFrame):
    """Barra de ranking de equipo."""
    
    def __init__(
        self,
        rank: int,
        team_name: str,
        roi: float,
        profit: float,
        max_roi: float,
        parent=None
    ):
        super().__init__(parent)
        self.rank = rank
        self.team_name = team_name
        self.roi = roi
        self.profit = profit
        self.max_roi = max_roi
        
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 6px;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        
        rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}
        rank_text = rank_icons.get(self.rank, str(self.rank))
        lbl_rank = QLabel(rank_text)
        lbl_rank.setFixedWidth(35)
        lbl_rank.setStyleSheet("font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(lbl_rank)
        
        lbl_team = QLabel(self.team_name)
        lbl_team.setStyleSheet("font-size: 14px; font-weight: bold; color: #333333; background: transparent;")
        layout.addWidget(lbl_team, 2)
        
        bar_width = 150
        bar_container = QFrame()
        bar_container.setFixedWidth(bar_width + 10)
        bar_container.setFixedHeight(20)
        bar_container.setStyleSheet("background-color: #E0E0E0; border-radius: 4px;")
        
        if self.max_roi > 0:
            fill_ratio = abs(self.roi) / self.max_roi
            fill_width = int(bar_width * min(fill_ratio, 1.0))
        else:
            fill_width = 0
        
        bar_color = "#28A745" if self.roi >= 0 else "#DC3545"
        
        bar_fill = QFrame(bar_container)
        bar_fill.setGeometry(5, 2, fill_width, 16)
        bar_fill.setStyleSheet(f"background-color: {bar_color}; border-radius: 3px;")
        
        layout.addWidget(bar_container)
        
        roi_color = "#28A745" if self.roi >= 0 else "#DC3545"
        lbl_roi = QLabel(f"{self.roi:+.1f}%")
        lbl_roi.setFixedWidth(70)
        lbl_roi.setAlignment(Qt.AlignRight)
        lbl_roi.setStyleSheet(f"color: {roi_color}; font-weight: bold; background: transparent;")
        layout.addWidget(lbl_roi)
        
        profit_color = "#28A745" if self.profit >= 0 else "#DC3545"
        lbl_profit = QLabel(f"€{self.profit:+.2f}")
        lbl_profit.setFixedWidth(80)
        lbl_profit.setAlignment(Qt.AlignRight)
        lbl_profit.setStyleSheet(f"color: {profit_color}; background: transparent;")
        layout.addWidget(lbl_profit)
