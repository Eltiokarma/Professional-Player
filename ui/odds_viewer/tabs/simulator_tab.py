# ui/odds_viewer/tabs/simulator_tab.py
# -*- coding: utf-8 -*-
"""
Tab del Simulador del Hincha - LAYOUT MEJORADO.
"""

import logging
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QDoubleSpinBox, QSpinBox,
    QPushButton, QFrame, QScrollArea, QGroupBox,
    QRadioButton, QButtonGroup, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QSplitter, QTabWidget, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QColor

from ..styles.colors import Colors, Styles
from ..models.data_models import (
    SimulationConfig, BetType, DoubleChanceType,
    TeamSimulationResult, LeagueSimulationResult
)
from ..models.database_queries import OddsQueryModel
from ..simulador.fan_simulator import FanSimulator

logger = logging.getLogger(__name__)


class SimpleKPICard(QFrame):
    """KPI Card simple y visible."""
    
    def __init__(self, title: str, icon: str = "", parent=None):
        super().__init__(parent)
        
        self.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 2px solid #E0E0E0;
                border-radius: 8px;
            }
        """)
        self.setFixedHeight(75)
        self.setMinimumWidth(120)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        
        title_text = f"{icon} {title}" if icon else title
        self.title_lbl = QLabel(title_text)
        self.title_lbl.setStyleSheet("color: #666666; font-size: 10px; font-weight: bold;")
        layout.addWidget(self.title_lbl)
        
        self.value_lbl = QLabel("--")
        self.value_lbl.setStyleSheet("color: #333333; font-size: 18px; font-weight: bold;")
        layout.addWidget(self.value_lbl)
    
    def set_value(self, value: str, color: str = "#333333"):
        self.value_lbl.setText(str(value))
        self.value_lbl.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold;")


class SimulationWorker(QThread):
    """Worker para simulaciones."""
    
    progress = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, simulator: FanSimulator, config: SimulationConfig, mode: str = "team"):
        super().__init__()
        self.simulator = simulator
        self.config = config
        self.mode = mode
        self.team_id = None
    
    def set_team_id(self, team_id: int):
        self.team_id = team_id
    
    def run(self):
        try:
            if self.mode == "team" and self.team_id:
                self.progress.emit(10, "Cargando datos...")
                result = self.simulator.simulate_team(self.team_id, self.config)
                self.progress.emit(100, "Completado")
                self.finished.emit(result)
            elif self.mode == "league":
                self.progress.emit(10, "Cargando equipos...")
                result = self.simulator.simulate_league(self.config)
                self.progress.emit(100, "Completado")
                self.finished.emit(result)
            else:
                self.error.emit("Configuración inválida")
        except Exception as e:
            logger.error(f"Error: {e}")
            self.error.emit(str(e))


class SimulatorTab(QWidget):
    """Tab del simulador - LAYOUT MEJORADO."""
    
    def __init__(self, db_model: OddsQueryModel, parent=None):
        super().__init__(parent)
        self.db = db_model
        self.simulator = FanSimulator(db_model)
        self.worker = None
        
        self.current_team_result = None
        self.current_league_result = None
        
        self._setup_ui()
        self._load_initial_data()
    
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # === PANEL DE CONFIGURACIÓN (compacto) ===
        config_frame = QFrame()
        config_frame.setStyleSheet("background-color: #FAFAFA; border: 1px solid #E0E0E0; border-radius: 10px;")
        config_frame.setMaximumHeight(250)
        config_layout = QVBoxLayout(config_frame)
        config_layout.setContentsMargins(15, 10, 15, 10)
        config_layout.setSpacing(8)
        
        # Título
        title = QLabel("🎰 SIMULADOR DEL HINCHA")
        title.setStyleSheet("color: #1a1a2e; font-size: 18px; font-weight: bold;")
        config_layout.addWidget(title)
        
        # Fila 1: Modo + Liga + Temporada + Equipo
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        
        # Modo
        row1.addWidget(QLabel("Modo:"))
        self.radio_one_team = QRadioButton("Un equipo")
        self.radio_one_team.setChecked(True)
        self.radio_all_league = QRadioButton("Toda la liga")
        
        self.mode_button_group = QButtonGroup()
        self.mode_button_group.addButton(self.radio_one_team, 0)
        self.mode_button_group.addButton(self.radio_all_league, 1)
        self.mode_button_group.buttonClicked.connect(self._on_mode_changed)
        
        row1.addWidget(self.radio_one_team)
        row1.addWidget(self.radio_all_league)
        
        row1.addSpacing(20)
        
        row1.addWidget(QLabel("Liga:"))
        self.combo_league = QComboBox()
        self.combo_league.setMinimumWidth(200)
        self.combo_league.currentIndexChanged.connect(self._on_league_changed)
        row1.addWidget(self.combo_league)
        
        row1.addWidget(QLabel("Temp:"))
        self.combo_season = QComboBox()
        self.combo_season.setMinimumWidth(80)
        self.combo_season.currentIndexChanged.connect(self._on_season_changed)
        row1.addWidget(self.combo_season)
        
        row1.addWidget(QLabel("Equipo:"))
        self.combo_team = QComboBox()
        self.combo_team.setMinimumWidth(180)
        row1.addWidget(self.combo_team)
        
        row1.addStretch()
        config_layout.addLayout(row1)
        
        # Fila 2: Montos + Tipo de Apuesta + Botón
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        
        row2.addWidget(QLabel("🏠 Local:"))
        self.spin_home_stake = QDoubleSpinBox()
        self.spin_home_stake.setRange(0.1, 1000)
        self.spin_home_stake.setValue(10.0)
        self.spin_home_stake.setPrefix("€")
        self.spin_home_stake.setFixedWidth(80)
        row2.addWidget(self.spin_home_stake)
        
        row2.addWidget(QLabel("🚌 Visita:"))
        self.spin_away_stake = QDoubleSpinBox()
        self.spin_away_stake.setRange(0.1, 1000)
        self.spin_away_stake.setValue(1.0)
        self.spin_away_stake.setPrefix("€")
        self.spin_away_stake.setFixedWidth(80)
        row2.addWidget(self.spin_away_stake)
        
        row2.addWidget(QLabel("🏦 Bankroll:"))
        self.spin_bankroll = QDoubleSpinBox()
        self.spin_bankroll.setRange(1, 100000)
        self.spin_bankroll.setValue(100.0)
        self.spin_bankroll.setPrefix("€")
        self.spin_bankroll.setFixedWidth(90)
        row2.addWidget(self.spin_bankroll)
        
        row2.addSpacing(20)
        
        # Tipo de apuesta simplificado
        row2.addWidget(QLabel("Tipo:"))
        self.combo_bet_type = QComboBox()
        self.combo_bet_type.addItems([
            "Victoria (1X2)",
            "Doble Chance",
            "Over 2.5",
            "Under 2.5"
        ])
        self.combo_bet_type.setMinimumWidth(120)
        row2.addWidget(self.combo_bet_type)
        
        row2.addStretch()
        
        self.btn_simulate = QPushButton("▶️ SIMULAR")
        self.btn_simulate.setStyleSheet("""
            QPushButton {
                background-color: #FF6B35;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 30px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E55A2B; }
            QPushButton:disabled { background-color: #CCCCCC; }
        """)
        self.btn_simulate.clicked.connect(self._run_simulation)
        row2.addWidget(self.btn_simulate)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedWidth(100)
        row2.addWidget(self.progress_bar)
        
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #28A745; font-weight: bold;")
        row2.addWidget(self.lbl_status)
        
        config_layout.addLayout(row2)
        
        main_layout.addWidget(config_frame)
        
        # === PANEL DE RESULTADOS ===
        self.results_tabs = QTabWidget()
        self.results_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #E0E0E0;
                border-radius: 5px;
                background: white;
            }
            QTabBar::tab {
                background: #F0F0F0;
                padding: 8px 20px;
                margin-right: 2px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
            QTabBar::tab:selected {
                background: #1a1a2e;
                color: white;
            }
        """)
        
        self.team_results_widget = self._create_team_results_tab()
        self.results_tabs.addTab(self.team_results_widget, "📊 Resultados del Equipo")
        
        self.league_results_widget = self._create_league_results_tab()
        self.results_tabs.addTab(self.league_results_widget, "🏆 Ranking de Liga")
        
        main_layout.addWidget(self.results_tabs, 1)  # stretch = 1 para que ocupe el espacio restante
    
    def _create_team_results_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # KPIs en grid compacto
        kpis_frame = QFrame()
        kpis_frame.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; padding: 5px;")
        kpis_layout = QGridLayout(kpis_frame)
        kpis_layout.setSpacing(8)
        
        self.kpi_profit = SimpleKPICard("PROFIT", "💰")
        kpis_layout.addWidget(self.kpi_profit, 0, 0)
        
        self.kpi_roi = SimpleKPICard("ROI", "📈")
        kpis_layout.addWidget(self.kpi_roi, 0, 1)
        
        self.kpi_winrate = SimpleKPICard("WIN RATE", "🎯")
        kpis_layout.addWidget(self.kpi_winrate, 0, 2)
        
        self.kpi_home_roi = SimpleKPICard("LOCAL", "🏠")
        kpis_layout.addWidget(self.kpi_home_roi, 0, 3)
        
        self.kpi_away_roi = SimpleKPICard("VISITA", "🚌")
        kpis_layout.addWidget(self.kpi_away_roi, 0, 4)
        
        self.kpi_streak_win = SimpleKPICard("RACHA+", "🔥")
        kpis_layout.addWidget(self.kpi_streak_win, 0, 5)
        
        self.kpi_streak_loss = SimpleKPICard("RACHA-", "❄️")
        kpis_layout.addWidget(self.kpi_streak_loss, 0, 6)
        
        self.kpi_avg_odd = SimpleKPICard("CUOTA", "📊")
        kpis_layout.addWidget(self.kpi_avg_odd, 0, 7)
        
        self.kpi_total_bets = SimpleKPICard("TOTAL", "🎰")
        kpis_layout.addWidget(self.kpi_total_bets, 0, 8)
        
        layout.addWidget(kpis_frame)
        
        # Tabla de apuestas - OCUPA TODO EL ESPACIO RESTANTE
        table_group = QGroupBox("📋 Detalle de Apuestas")
        table_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #E0E0E0;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        table_layout = QVBoxLayout(table_group)
        
        self.bets_table = QTableWidget()
        self.bets_table.setColumnCount(8)
        self.bets_table.setHorizontalHeaderLabels([
            "#", "Fecha", "Rival", "Loc", "Result", "Cuota", "Apuesta", "P/L"
        ])
        self.bets_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.bets_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.bets_table.setColumnWidth(0, 40)
        self.bets_table.setAlternatingRowColors(True)
        self.bets_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                gridline-color: #E0E0E0;
                border: none;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #1a1a2e;
                color: white;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
        """)
        self.bets_table.setMinimumHeight(200)
        
        table_layout.addWidget(self.bets_table)
        layout.addWidget(table_group, 1)  # stretch = 1
        
        return widget
    
    def _create_league_results_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # KPIs de liga
        kpis_frame = QFrame()
        kpis_frame.setStyleSheet("background-color: #F8F9FA; border-radius: 8px; padding: 5px;")
        kpis_layout = QHBoxLayout(kpis_frame)
        kpis_layout.setSpacing(8)
        
        self.kpi_league_teams = SimpleKPICard("EQUIPOS", "🏟️")
        kpis_layout.addWidget(self.kpi_league_teams)
        
        self.kpi_profitable = SimpleKPICard("RENTABLES", "✅")
        kpis_layout.addWidget(self.kpi_profitable)
        
        self.kpi_league_avg_roi = SimpleKPICard("ROI AVG", "📊")
        kpis_layout.addWidget(self.kpi_league_avg_roi)
        
        self.kpi_league_home = SimpleKPICard("ROI LOCAL", "🏠")
        kpis_layout.addWidget(self.kpi_league_home)
        
        self.kpi_league_away = SimpleKPICard("ROI VISITA", "🚌")
        kpis_layout.addWidget(self.kpi_league_away)
        
        kpis_layout.addStretch()
        layout.addWidget(kpis_frame)
        
        # Insights
        self.lbl_insights = QLabel("Ejecuta una simulación de liga para ver el ranking...")
        self.lbl_insights.setWordWrap(True)
        self.lbl_insights.setStyleSheet("""
            color: #666666;
            padding: 10px;
            background-color: #FFF9E6;
            border: 1px solid #FFE082;
            border-radius: 5px;
        """)
        layout.addWidget(self.lbl_insights)
        
        # Ranking
        ranking_group = QGroupBox("🏆 Ranking de Rentabilidad")
        ranking_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #E0E0E0;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
        """)
        ranking_layout = QVBoxLayout(ranking_group)
        
        self.ranking_scroll = QScrollArea()
        self.ranking_scroll.setWidgetResizable(True)
        self.ranking_scroll.setStyleSheet("QScrollArea { border: none; }")
        
        self.ranking_container = QWidget()
        self.ranking_container_layout = QVBoxLayout(self.ranking_container)
        self.ranking_container_layout.setSpacing(5)
        self.ranking_container_layout.setContentsMargins(5, 5, 5, 5)
        self.ranking_scroll.setWidget(self.ranking_container)
        
        ranking_layout.addWidget(self.ranking_scroll)
        layout.addWidget(ranking_group, 1)
        
        return widget
    
    def _load_initial_data(self):
        try:
            leagues = self.db.get_leagues()
            self.combo_league.clear()
            for league in leagues:
                self.combo_league.addItem(
                    f"{league['name']} ({league['fixtures']})",
                    league['id']
                )
            self._load_seasons()
        except Exception as e:
            logger.error(f"Error cargando datos: {e}")
    
    def _load_seasons(self):
        league_id = self.combo_league.currentData()
        if not league_id:
            return
        
        seasons = self.db.get_seasons(league_id)
        self.combo_season.clear()
        for season in seasons:
            self.combo_season.addItem(str(season), season)
    
    def _load_teams(self):
        league_id = self.combo_league.currentData()
        season = self.combo_season.currentData()
        
        if not league_id:
            return
        
        teams = self.db.get_teams(league_id, season)
        self.combo_team.clear()
        for team in teams:
            self.combo_team.addItem(team['name'], team['id'])
    
    def _on_league_changed(self):
        self._load_seasons()
        self._load_teams()
    
    def _on_season_changed(self):
        self._load_teams()
    
    def _on_mode_changed(self):
        mode = self.mode_button_group.checkedId()
        self.combo_team.setEnabled(mode == 0)
    
    def _get_config(self) -> SimulationConfig:
        bet_text = self.combo_bet_type.currentText()
        
        if "Victoria" in bet_text:
            bet_type = BetType.WIN
        elif "Doble" in bet_text:
            bet_type = BetType.DOUBLE_CHANCE
        else:
            bet_type = BetType.OVER_UNDER
        
        over_not_under = "Over" in bet_text
        
        return SimulationConfig(
            league_id=self.combo_league.currentData(),
            season=self.combo_season.currentData(),
            bet_type=bet_type,
            over_under_line=2.5,
            over_not_under=over_not_under,
            home_stake=self.spin_home_stake.value(),
            away_stake=self.spin_away_stake.value(),
            initial_bankroll=self.spin_bankroll.value()
        )
    
    def _run_simulation(self):
        config = self._get_config()
        
        if not config.league_id:
            QMessageBox.warning(self, "Error", "Selecciona una liga")
            return
        
        mode = self.mode_button_group.checkedId()
        
        if mode == 0:
            team_id = self.combo_team.currentData()
            if not team_id:
                QMessageBox.warning(self, "Error", "Selecciona un equipo")
                return
            
            self.worker = SimulationWorker(self.simulator, config, "team")
            self.worker.set_team_id(team_id)
        else:
            self.worker = SimulationWorker(self.simulator, config, "league")
        
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_simulation_finished)
        self.worker.error.connect(self._on_simulation_error)
        
        self.btn_simulate.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("...")
        
        self.worker.start()
    
    def _on_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
    
    def _on_simulation_finished(self, result):
        self.btn_simulate.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText("✅ OK")
        
        if isinstance(result, TeamSimulationResult):
            self.current_team_result = result
            self._display_team_results(result)
            self.results_tabs.setCurrentIndex(0)
        elif isinstance(result, LeagueSimulationResult):
            self.current_league_result = result
            self._display_league_results(result)
            self.results_tabs.setCurrentIndex(1)
    
    def _on_simulation_error(self, error: str):
        self.btn_simulate.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.lbl_status.setText("❌")
        QMessageBox.critical(self, "Error", error)
    
    def _display_team_results(self, result: TeamSimulationResult):
        GREEN = "#28A745"
        RED = "#DC3545"
        
        profit_color = GREEN if result.total_profit >= 0 else RED
        self.kpi_profit.set_value(f"€{result.total_profit:+.2f}", profit_color)
        
        roi_color = GREEN if result.roi >= 0 else RED
        self.kpi_roi.set_value(f"{result.roi:+.1f}%", roi_color)
        
        self.kpi_winrate.set_value(f"{result.win_rate:.1f}%")
        
        home_color = GREEN if result.home_roi >= 0 else RED
        self.kpi_home_roi.set_value(f"{result.home_roi:+.1f}%", home_color)
        
        away_color = GREEN if result.away_roi >= 0 else RED
        self.kpi_away_roi.set_value(f"{result.away_roi:+.1f}%", away_color)
        
        self.kpi_streak_win.set_value(str(result.max_win_streak), GREEN)
        self.kpi_streak_loss.set_value(str(result.max_loss_streak), RED)
        self.kpi_avg_odd.set_value(f"{result.avg_odd:.2f}")
        self.kpi_total_bets.set_value(str(result.total_bets))
        
        # Tabla
        self.bets_table.setRowCount(len(result.bets))
        
        for i, bet in enumerate(result.bets):
            rival = bet.away_team if bet.is_home else bet.home_team
            result_color = QColor(GREEN if bet.bet_won else RED)
            
            self.bets_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.bets_table.setItem(i, 1, QTableWidgetItem(bet.date.strftime("%d/%m/%y")))
            self.bets_table.setItem(i, 2, QTableWidgetItem(rival))
            self.bets_table.setItem(i, 3, QTableWidgetItem(bet.location_emoji))
            
            result_item = QTableWidgetItem(f"{bet.result_str} {bet.result_emoji}")
            result_item.setForeground(result_color)
            self.bets_table.setItem(i, 4, result_item)
            
            self.bets_table.setItem(i, 5, QTableWidgetItem(f"{bet.odd:.2f}"))
            self.bets_table.setItem(i, 6, QTableWidgetItem(f"€{bet.stake:.2f}"))
            
            pl_item = QTableWidgetItem(bet.profit_loss_str)
            pl_item.setForeground(result_color)
            self.bets_table.setItem(i, 7, pl_item)
    
    def _display_league_results(self, result: LeagueSimulationResult):
        GREEN = "#28A745"
        RED = "#DC3545"
        
        self.kpi_league_teams.set_value(str(result.total_teams))
        self.kpi_profitable.set_value(str(result.profitable_teams), GREEN)
        
        avg_color = GREEN if result.avg_roi >= 0 else RED
        self.kpi_league_avg_roi.set_value(f"{result.avg_roi:+.1f}%", avg_color)
        
        home_color = GREEN if result.home_total_roi >= 0 else RED
        self.kpi_league_home.set_value(f"{result.home_total_roi:+.1f}%", home_color)
        
        away_color = GREEN if result.away_total_roi >= 0 else RED
        self.kpi_league_away.set_value(f"{result.away_total_roi:+.1f}%", away_color)
        
        # Insights
        insights = self.simulator.get_insights(result)
        self.lbl_insights.setText(" | ".join(insights[:3]))
        
        # Ranking
        while self.ranking_container_layout.count():
            item = self.ranking_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        ranking = result.get_ranking(by="roi")
        
        for i, team in enumerate(ranking):
            row = QFrame()
            row.setStyleSheet("""
                QFrame {
                    background-color: white;
                    border: 1px solid #E0E0E0;
                    border-radius: 5px;
                }
            """)
            row.setFixedHeight(40)
            
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 5, 10, 5)
            
            rank_icons = {1: "🥇", 2: "🥈", 3: "🥉"}
            rank_text = rank_icons.get(i + 1, f"{i+1}.")
            lbl_rank = QLabel(rank_text)
            lbl_rank.setFixedWidth(30)
            lbl_rank.setStyleSheet("font-size: 14px; font-weight: bold;")
            row_layout.addWidget(lbl_rank)
            
            lbl_team = QLabel(team.team_name)
            lbl_team.setStyleSheet("font-size: 12px; font-weight: bold; color: #333333;")
            row_layout.addWidget(lbl_team, 2)
            
            roi_color = GREEN if team.roi >= 0 else RED
            lbl_roi = QLabel(f"{team.roi:+.1f}%")
            lbl_roi.setStyleSheet(f"color: {roi_color}; font-weight: bold;")
            lbl_roi.setFixedWidth(70)
            row_layout.addWidget(lbl_roi)
            
            profit_color = GREEN if team.total_profit >= 0 else RED
            lbl_profit = QLabel(f"€{team.total_profit:+.2f}")
            lbl_profit.setStyleSheet(f"color: {profit_color};")
            lbl_profit.setFixedWidth(80)
            row_layout.addWidget(lbl_profit)
            
            self.ranking_container_layout.addWidget(row)
        
        self.ranking_container_layout.addStretch()
