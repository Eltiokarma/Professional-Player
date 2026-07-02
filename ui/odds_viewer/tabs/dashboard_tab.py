# ui/odds_viewer/tabs/dashboard_tab.py
# -*- coding: utf-8 -*-
"""
Tab de Dashboard Analítico.
Muestra estadísticas de cobertura de datos y gráficos.
"""

import logging
from typing import List, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QPushButton, QFrame, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QProgressBar, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QBrush, QPen

from ..styles.colors import Colors, Styles
from ..models.database_queries import OddsQueryModel
from ..widgets.match_widgets import KPICard

logger = logging.getLogger(__name__)


class CoverageBar(QFrame):
    """Barra de cobertura visual."""
    
    def __init__(self, label: str, value: float, max_value: float = 100, parent=None):
        super().__init__(parent)
        self.label = label
        self.value = value
        self.max_value = max_value
        self.setMinimumHeight(35)
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(10)
        
        # Label
        lbl = QLabel(self.label)
        lbl.setMinimumWidth(80)
        lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: bold;")
        layout.addWidget(lbl)
        
        # Barra de progreso
        progress = QProgressBar()
        progress.setRange(0, int(self.max_value))
        progress.setValue(int(self.value))
        progress.setTextVisible(True)
        progress.setFormat(f"{self.value:.1f}%")
        
        # Color según valor
        if self.value >= 80:
            color = Colors.WIN
        elif self.value >= 50:
            color = Colors.CHART_TERTIARY
        else:
            color = Colors.LOSS
        
        progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {Colors.BORDER};
                border-radius: 5px;
                background-color: {Colors.BACKGROUND};
                text-align: center;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(progress, 1)


class SimpleBarChart(QFrame):
    """Gráfico de barras simple usando Qt."""
    
    def __init__(self, data: List[Dict], title: str = "", parent=None):
        """
        Args:
            data: Lista de dicts con 'label' y 'value'
            title: Título del gráfico
        """
        super().__init__(parent)
        self.data = data
        self.title = title
        self.setMinimumHeight(200)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.CARD};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
            }}
        """)
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        if not self.data:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Dimensiones
        margin = 40
        title_height = 30 if self.title else 0
        width = self.width() - 2 * margin
        height = self.height() - 2 * margin - title_height
        
        # Título
        if self.title:
            painter.setPen(QColor(Colors.TEXT_PRIMARY))
            painter.drawText(margin, 25, self.title)
        
        # Encontrar valor máximo
        max_val = max(d['value'] for d in self.data) if self.data else 1
        if max_val == 0:
            max_val = 1
        
        # Dibujar barras
        bar_width = width / len(self.data) * 0.7
        spacing = width / len(self.data)
        
        for i, item in enumerate(self.data):
            x = margin + i * spacing + (spacing - bar_width) / 2
            bar_height = (item['value'] / max_val) * height
            y = margin + title_height + height - bar_height
            
            # Color de la barra
            color = QColor(item.get('color', Colors.CHART_PRIMARY))
            
            # Dibujar barra
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(int(x), int(y), int(bar_width), int(bar_height), 4, 4)
            
            # Label debajo
            painter.setPen(QColor(Colors.TEXT_SECONDARY))
            label = item['label']
            if len(label) > 8:
                label = label[:6] + ".."
            painter.drawText(
                int(x), 
                int(margin + title_height + height + 15),
                int(bar_width),
                20,
                Qt.AlignCenter,
                label
            )
            
            # Valor encima
            painter.drawText(
                int(x),
                int(y - 5),
                int(bar_width),
                20,
                Qt.AlignCenter,
                f"{item['value']:.0f}"
            )


class DashboardTab(QWidget):
    """
    Tab de Dashboard Analítico.
    
    Muestra:
    - KPIs globales de la base de datos
    - Cobertura de datos por liga/temporada
    - Gráficos de distribución
    - Timeline de datos
    """
    
    def __init__(self, db_model: OddsQueryModel, parent=None):
        super().__init__(parent)
        self.db = db_model
        
        self._setup_ui()
        self._load_data()
    
    def _setup_ui(self):
        """Construye la interfaz."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # === Header ===
        header_layout = QHBoxLayout()
        
        title = QLabel("📊 DASHBOARD DE COBERTURA DE DATOS")
        title.setStyleSheet(f"""
            color: {Colors.PRIMARY};
            font-size: 20px;
            font-weight: bold;
        """)
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        self.btn_refresh = QPushButton("🔄 Actualizar")
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ACCENT};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT_HOVER};
            }}
        """)
        self.btn_refresh.clicked.connect(self._load_data)
        header_layout.addWidget(self.btn_refresh)
        
        main_layout.addLayout(header_layout)
        
        # === KPIs Globales ===
        kpis_layout = QHBoxLayout()
        kpis_layout.setSpacing(15)
        
        self.kpi_fixtures = KPICard("TOTAL PARTIDOS", "0", "Partidos finalizados", Colors.CHART_PRIMARY, "⚽")
        kpis_layout.addWidget(self.kpi_fixtures)
        
        self.kpi_with_odds = KPICard("CON CUOTAS", "0", "Partidos con odds", Colors.WIN, "📊")
        kpis_layout.addWidget(self.kpi_with_odds)
        
        self.kpi_coverage = KPICard("COBERTURA", "0%", "Porcentaje con datos", Colors.CHART_TERTIARY, "📈")
        kpis_layout.addWidget(self.kpi_coverage)
        
        self.kpi_leagues = KPICard("LIGAS", "0", "Competiciones", Colors.CHART_SECONDARY, "🏆")
        kpis_layout.addWidget(self.kpi_leagues)
        
        self.kpi_teams = KPICard("EQUIPOS", "0", "En la base de datos", Colors.AWAY, "🏟️")
        kpis_layout.addWidget(self.kpi_teams)
        
        self.kpi_bookmakers = KPICard("BOOKMAKERS", "0", "Casas de apuestas", Colors.ACCENT, "🎰")
        kpis_layout.addWidget(self.kpi_bookmakers)
        
        main_layout.addLayout(kpis_layout)
        
        # === Splitter para gráficos y tablas ===
        splitter = QSplitter(Qt.Horizontal)
        
        # Panel izquierdo: Cobertura por temporada
        left_panel = QFrame()
        left_panel.setStyleSheet(f"background-color: {Colors.CARD}; border-radius: 8px;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(15, 15, 15, 15)
        
        left_title = QLabel("📈 COBERTURA POR TEMPORADA")
        left_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        left_layout.addWidget(left_title)
        
        self.coverage_container = QVBoxLayout()
        left_layout.addLayout(self.coverage_container)
        left_layout.addStretch()
        
        splitter.addWidget(left_panel)
        
        # Panel derecho: Tabla de ligas
        right_panel = QFrame()
        right_panel.setStyleSheet(f"background-color: {Colors.CARD}; border-radius: 8px;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(15, 15, 15, 15)
        
        right_title = QLabel("📋 DETALLE POR LIGA")
        right_title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        right_layout.addWidget(right_title)
        
        self.leagues_table = QTableWidget()
        self.leagues_table.setColumnCount(5)
        self.leagues_table.setHorizontalHeaderLabels([
            "Liga", "Partidos", "Con Odds", "Cobertura", "Temporadas"
        ])
        self.leagues_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.leagues_table.setAlternatingRowColors(True)
        self.leagues_table.setStyleSheet(Styles.TABLE_VIEW)
        right_layout.addWidget(self.leagues_table)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 600])
        
        main_layout.addWidget(splitter)
        
        # === Panel inferior: Datos faltantes ===
        bottom_panel = QFrame()
        bottom_panel.setStyleSheet(f"background-color: {Colors.CARD}; border-radius: 8px;")
        bottom_layout = QHBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(20, 15, 20, 15)
        
        # Indicadores de estado
        self.lbl_complete = QLabel("🟢 Completos: 0")
        self.lbl_complete.setStyleSheet(f"color: {Colors.WIN}; font-size: 14px; font-weight: bold;")
        bottom_layout.addWidget(self.lbl_complete)
        
        bottom_layout.addSpacing(30)
        
        self.lbl_partial = QLabel("🟡 Parciales: 0")
        self.lbl_partial.setStyleSheet(f"color: {Colors.CHART_TERTIARY}; font-size: 14px; font-weight: bold;")
        bottom_layout.addWidget(self.lbl_partial)
        
        bottom_layout.addSpacing(30)
        
        self.lbl_missing = QLabel("🔴 Sin odds: 0")
        self.lbl_missing.setStyleSheet(f"color: {Colors.LOSS}; font-size: 14px; font-weight: bold;")
        bottom_layout.addWidget(self.lbl_missing)
        
        bottom_layout.addStretch()
        
        # Info adicional
        self.lbl_seasons = QLabel("📅 Temporadas: --")
        self.lbl_seasons.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 13px;")
        bottom_layout.addWidget(self.lbl_seasons)
        
        main_layout.addWidget(bottom_panel)
    
    def _load_data(self):
        """Carga datos del dashboard."""
        try:
            # Obtener estadísticas globales
            stats = self.db.get_global_stats()
            
            # Actualizar KPIs
            self.kpi_fixtures.update_value(f"{stats.get('total_fixtures', 0):,}")
            self.kpi_with_odds.update_value(f"{stats.get('fixtures_with_odds', 0):,}")
            
            coverage = stats.get('coverage_percent', 0)
            coverage_color = Colors.WIN if coverage >= 80 else (Colors.CHART_TERTIARY if coverage >= 50 else Colors.LOSS)
            self.kpi_coverage.update_value(f"{coverage:.1f}%", coverage_color)
            
            self.kpi_leagues.update_value(f"{stats.get('total_leagues', 0):,}")
            self.kpi_teams.update_value(f"{stats.get('total_teams', 0):,}")
            self.kpi_bookmakers.update_value(f"{stats.get('total_bookmakers', 0):,}")
            
            # Temporadas
            min_season = stats.get('min_season')
            max_season = stats.get('max_season')
            if min_season and max_season:
                self.lbl_seasons.setText(f"📅 Temporadas: {min_season} - {max_season}")
            
            # Indicadores de estado
            total = stats.get('total_fixtures', 0)
            with_odds = stats.get('fixtures_with_odds', 0)
            without_odds = total - with_odds
            
            self.lbl_complete.setText(f"🟢 Con odds: {with_odds:,}")
            self.lbl_missing.setText(f"🔴 Sin odds: {without_odds:,}")
            
            # Obtener cobertura por temporada
            self._load_coverage_by_season()
            
            # Obtener detalle por liga
            self._load_leagues_table()
            
        except Exception as e:
            logger.error(f"Error cargando datos del dashboard: {e}")
    
    def _load_coverage_by_season(self):
        """Carga barras de cobertura por temporada."""
        # Limpiar contenedor
        while self.coverage_container.count():
            item = self.coverage_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        try:
            # Obtener stats de cobertura agrupados por temporada
            coverage_stats = self.db.get_coverage_stats()
            
            # Agrupar por temporada
            by_season = {}
            for stat in coverage_stats:
                season = stat.season
                if season not in by_season:
                    by_season[season] = {'total': 0, 'with_odds': 0}
                by_season[season]['total'] += stat.total_fixtures
                by_season[season]['with_odds'] += stat.fixtures_with_odds
            
            # Crear barras (últimas 5 temporadas)
            for season in sorted(by_season.keys(), reverse=True)[:6]:
                data = by_season[season]
                if data['total'] > 0:
                    coverage = (data['with_odds'] / data['total']) * 100
                else:
                    coverage = 0
                
                bar = CoverageBar(str(season), coverage)
                self.coverage_container.addWidget(bar)
            
        except Exception as e:
            logger.error(f"Error cargando cobertura por temporada: {e}")
    
    def _load_leagues_table(self):
        """Carga tabla de ligas."""
        try:
            coverage_stats = self.db.get_coverage_stats()
            
            # Agrupar por liga
            by_league = {}
            for stat in coverage_stats:
                league_id = stat.league_id
                if league_id not in by_league:
                    by_league[league_id] = {
                        'name': stat.league_name,
                        'total': 0,
                        'with_odds': 0,
                        'seasons': set()
                    }
                by_league[league_id]['total'] += stat.total_fixtures
                by_league[league_id]['with_odds'] += stat.fixtures_with_odds
                by_league[league_id]['seasons'].add(stat.season)
            
            # Ordenar por total de partidos
            sorted_leagues = sorted(
                by_league.values(),
                key=lambda x: x['total'],
                reverse=True
            )
            
            # Llenar tabla
            self.leagues_table.setRowCount(len(sorted_leagues))
            
            for i, league in enumerate(sorted_leagues):
                # Nombre
                self.leagues_table.setItem(i, 0, QTableWidgetItem(league['name']))
                
                # Total partidos
                self.leagues_table.setItem(i, 1, QTableWidgetItem(f"{league['total']:,}"))
                
                # Con odds
                self.leagues_table.setItem(i, 2, QTableWidgetItem(f"{league['with_odds']:,}"))
                
                # Cobertura
                if league['total'] > 0:
                    coverage = (league['with_odds'] / league['total']) * 100
                else:
                    coverage = 0
                
                coverage_item = QTableWidgetItem(f"{coverage:.1f}%")
                if coverage >= 80:
                    coverage_item.setForeground(QColor(Colors.WIN))
                elif coverage >= 50:
                    coverage_item.setForeground(QColor(Colors.CHART_TERTIARY))
                else:
                    coverage_item.setForeground(QColor(Colors.LOSS))
                self.leagues_table.setItem(i, 3, coverage_item)
                
                # Temporadas
                seasons = sorted(league['seasons'])
                if len(seasons) > 1:
                    seasons_str = f"{min(seasons)}-{max(seasons)}"
                else:
                    seasons_str = str(seasons[0]) if seasons else "-"
                self.leagues_table.setItem(i, 4, QTableWidgetItem(seasons_str))
            
        except Exception as e:
            logger.error(f"Error cargando tabla de ligas: {e}")
