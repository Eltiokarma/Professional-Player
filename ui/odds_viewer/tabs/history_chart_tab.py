# ui/odds_viewer/tabs/history_chart_tab.py
# -*- coding: utf-8 -*-
"""
Tab de Cobertura de Odds.
Muestra visualmente en qué fechas HAY y NO HAY odds para cada equipo/liga.
Útil para saber qué datos están disponibles para Machine Learning.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFrame, QGroupBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QGridLayout,
    QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont

from ..styles.colors import Colors
from ..models.database_queries import OddsQueryModel

logger = logging.getLogger(__name__)


class CoverageHeatmap(QFrame):
    """
    Heatmap de cobertura de odds.
    Verde = Tiene odds, Rojo = No tiene odds.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []  # Lista de {"date": str, "has_odds": bool, "fixture_id": int}
        self.team_name = ""
        self.setMinimumHeight(200)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 10px;
            }
        """)
    
    def set_data(self, data: List[Dict], team_name: str = ""):
        self.data = data
        self.team_name = team_name
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        if not self.data:
            # Mensaje cuando no hay datos
            painter = QPainter(self)
            painter.setPen(QColor("#999999"))
            painter.setFont(QFont("Arial", 14))
            painter.drawText(self.rect(), Qt.AlignCenter, "Selecciona filtros y haz clic en ANALIZAR")
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        margin_left = 20
        margin_right = 20
        margin_top = 50
        margin_bottom = 60
        
        width = self.width() - margin_left - margin_right
        height = self.height() - margin_top - margin_bottom
        
        if width <= 0 or height <= 0:
            return
        
        # Título
        painter.setPen(QColor("#333333"))
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        title = f"📊 Cobertura de Odds: {self.team_name}" if self.team_name else "📊 Cobertura de Odds"
        painter.drawText(margin_left, 30, title)
        
        # Estadísticas rápidas
        total = len(self.data)
        with_odds = sum(1 for d in self.data if d['has_odds'])
        coverage_pct = (with_odds / total * 100) if total > 0 else 0
        
        painter.setFont(QFont("Arial", 11))
        stats = f"Total partidos: {total} | Con Odds: {with_odds} | Cobertura: {coverage_pct:.1f}%"
        painter.drawText(margin_left + 400, 30, stats)
        
        # Dibujar bloques
        n = len(self.data)
        if n == 0:
            return
        
        # Calcular tamaño de bloques
        cols = min(n, 30)  # Máximo 30 columnas
        rows = (n + cols - 1) // cols
        
        block_width = min(25, (width - 10) / cols)
        block_height = min(20, (height - 10) / max(rows, 1))
        
        for i, item in enumerate(self.data):
            col = i % cols
            row = i // cols
            
            x = margin_left + col * (block_width + 2)
            y = margin_top + row * (block_height + 2)
            
            # Color según si tiene odds o no
            if item['has_odds']:
                color = QColor("#28A745")  # Verde
            else:
                color = QColor("#DC3545")  # Rojo
            
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(int(x), int(y), int(block_width), int(block_height), 3, 3)
        
        # Leyenda
        legend_y = self.height() - 35
        painter.setFont(QFont("Arial", 10))
        
        # Verde
        painter.setBrush(QBrush(QColor("#28A745")))
        painter.drawRect(margin_left, legend_y, 15, 15)
        painter.setPen(QColor("#333333"))
        painter.drawText(margin_left + 20, legend_y + 12, "Con Odds")
        
        # Rojo
        painter.setBrush(QBrush(QColor("#DC3545")))
        painter.setPen(Qt.NoPen)
        painter.drawRect(margin_left + 100, legend_y, 15, 15)
        painter.setPen(QColor("#333333"))
        painter.drawText(margin_left + 120, legend_y + 12, "Sin Odds")


class CoverageByDateChart(QFrame):
    """
    Gráfico de barras mostrando cobertura por mes/semana.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []  # Lista de {"period": str, "total": int, "with_odds": int}
        self.setMinimumHeight(180)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #E0E0E0;
                border-radius: 10px;
            }
        """)
    
    def set_data(self, data: List[Dict]):
        self.data = data
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        
        if not self.data:
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        margin_left = 50
        margin_right = 20
        margin_top = 40
        margin_bottom = 50
        
        width = self.width() - margin_left - margin_right
        height = self.height() - margin_top - margin_bottom
        
        if width <= 0 or height <= 0:
            return
        
        # Título
        painter.setPen(QColor("#333333"))
        painter.setFont(QFont("Arial", 12, QFont.Bold))
        painter.drawText(margin_left, 25, "📅 Cobertura por Período")
        
        # Máximo
        max_val = max(d['total'] for d in self.data) if self.data else 1
        if max_val == 0:
            max_val = 1
        
        # Ejes
        painter.setPen(QPen(QColor("#E0E0E0"), 1))
        painter.drawLine(margin_left, margin_top, margin_left, margin_top + height)
        painter.drawLine(margin_left, margin_top + height, margin_left + width, margin_top + height)
        
        # Barras
        n = len(self.data)
        bar_width = min(40, (width / n) * 0.6)
        spacing = width / n
        
        for i, item in enumerate(self.data):
            x = margin_left + i * spacing + (spacing - bar_width) / 2
            
            total = item['total']
            with_odds = item['with_odds']
            
            # Barra total (gris)
            total_height = (total / max_val) * height
            painter.setBrush(QBrush(QColor("#E0E0E0")))
            painter.setPen(Qt.NoPen)
            y_total = margin_top + height - total_height
            painter.drawRoundedRect(int(x), int(y_total), int(bar_width), int(total_height), 3, 3)
            
            # Barra con odds (verde)
            if with_odds > 0:
                odds_height = (with_odds / max_val) * height
                painter.setBrush(QBrush(QColor("#28A745")))
                y_odds = margin_top + height - odds_height
                painter.drawRoundedRect(int(x), int(y_odds), int(bar_width), int(odds_height), 3, 3)
            
            # Label
            painter.setPen(QColor("#666666"))
            painter.setFont(QFont("Arial", 8))
            label = item['period']
            if len(label) > 7:
                label = label[-5:]  # Solo mes-año
            painter.drawText(int(x - 5), margin_top + height + 15, label)
            
            # Porcentaje encima
            pct = (with_odds / total * 100) if total > 0 else 0
            painter.setFont(QFont("Arial", 8, QFont.Bold))
            pct_color = "#28A745" if pct >= 80 else ("#FFC107" if pct >= 50 else "#DC3545")
            painter.setPen(QColor(pct_color))
            painter.drawText(int(x), int(y_total - 5), f"{pct:.0f}%")


class HistoryChartTab(QWidget):
    """
    Tab de Cobertura de Odds.
    
    Muestra visualmente:
    - En qué fechas HAY odds para un equipo
    - En qué fechas NO HAY odds
    - Porcentaje de cobertura por período
    - Tabla detallada de partidos sin odds
    
    Útil para saber qué datos usar en Machine Learning.
    """
    
    def __init__(self, db_model: OddsQueryModel, parent=None):
        super().__init__(parent)
        self.db = db_model
        
        self._setup_ui()
        self._load_initial_data()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # === Header (compacto) ===
        header = QFrame()
        header.setStyleSheet("background-color: white; border-radius: 8px; border: 1px solid #E0E0E0;")
        header.setMaximumHeight(110)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        header_layout.setSpacing(8)
        
        # Título y subtítulo en una línea
        title_row = QHBoxLayout()
        title = QLabel("📊 COBERTURA DE ODDS")
        title.setStyleSheet("color: #1a1a2e; font-size: 18px; font-weight: bold;")
        title_row.addWidget(title)
        
        subtitle = QLabel("Visualiza en qué fechas HAY y NO HAY odds disponibles. Útil para saber qué datos usar en Machine Learning.")
        subtitle.setStyleSheet("color: #666666; font-size: 11px;")
        title_row.addWidget(subtitle, 1)
        header_layout.addLayout(title_row)
        
        # Filtros
        filters = QHBoxLayout()
        filters.setSpacing(10)
        
        filters.addWidget(QLabel("Liga:"))
        self.combo_league = QComboBox()
        self.combo_league.setMinimumWidth(180)
        self.combo_league.currentIndexChanged.connect(self._on_league_changed)
        filters.addWidget(self.combo_league)
        
        filters.addWidget(QLabel("Temporada:"))
        self.combo_season = QComboBox()
        self.combo_season.currentIndexChanged.connect(self._on_season_changed)
        filters.addWidget(self.combo_season)
        
        filters.addWidget(QLabel("Equipo:"))
        self.combo_team = QComboBox()
        self.combo_team.setMinimumWidth(150)
        filters.addWidget(self.combo_team)
        
        filters.addStretch()
        
        self.btn_analyze = QPushButton("🔍 ANALIZAR COBERTURA")
        self.btn_analyze.setStyleSheet("""
            QPushButton {
                background-color: #FF6B35;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #E55A2B; }
        """)
        self.btn_analyze.clicked.connect(self._analyze_coverage)
        filters.addWidget(self.btn_analyze)
        
        header_layout.addLayout(filters)
        layout.addWidget(header)
        
        # === Splitter principal ===
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E0E0E0;
                border-radius: 4px;
            }
            QSplitter::handle:hover {
                background-color: #FF6B35;
            }
        """)
        
        # Panel superior: Gráficos (más compacto)
        charts_widget = QWidget()
        charts_layout = QVBoxLayout(charts_widget)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        charts_layout.setSpacing(5)
        
        # Heatmap de cobertura (compacto)
        self.heatmap = CoverageHeatmap()
        self.heatmap.setMinimumHeight(120)
        self.heatmap.setMaximumHeight(180)
        charts_layout.addWidget(self.heatmap)
        
        # Gráfico por período (compacto)
        self.period_chart = CoverageByDateChart()
        self.period_chart.setMinimumHeight(130)
        self.period_chart.setMaximumHeight(180)
        charts_layout.addWidget(self.period_chart)
        
        splitter.addWidget(charts_widget)
        
        # Panel inferior: Tabla de partidos SIN odds (más grande)
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(5)
        
        # Título de la tabla
        table_header = QHBoxLayout()
        table_title = QLabel("❌ Partidos SIN Odds (para revisar)")
        table_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #DC3545;")
        table_header.addWidget(table_title)
        
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color: #666666; font-size: 12px;")
        table_header.addWidget(self.lbl_count)
        table_header.addStretch()
        
        table_layout.addLayout(table_header)
        
        # Tabla grande
        self.missing_table = QTableWidget()
        self.missing_table.setColumnCount(6)
        self.missing_table.setHorizontalHeaderLabels([
            "#", "Fecha", "Local", "Visitante", "Resultado", "ID Fixture"
        ])
        self.missing_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.missing_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.missing_table.setColumnWidth(0, 40)
        self.missing_table.setAlternatingRowColors(True)
        self.missing_table.setMinimumHeight(150)
        self.missing_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                gridline-color: #E0E0E0;
                border: 1px solid #E0E0E0;
                border-radius: 5px;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #DC3545;
                color: white;
                padding: 10px;
                border: none;
                font-weight: bold;
            }
        """)
        
        table_layout.addWidget(self.missing_table, 1)  # stretch=1 para que ocupe espacio
        
        splitter.addWidget(table_widget)
        
        # Proporciones del splitter: 40% gráficos, 60% tabla
        splitter.setSizes([300, 400])
        
        layout.addWidget(splitter, 1)  # stretch=1
        
        # === Resumen estadístico (footer compacto) ===
        self.lbl_stats = QLabel("Selecciona filtros y haz clic en ANALIZAR COBERTURA")
        self.lbl_stats.setStyleSheet("""
            color: #666666;
            font-size: 12px;
            padding: 8px 12px;
            background-color: white;
            border-radius: 5px;
            border: 1px solid #E0E0E0;
        """)
        self.lbl_stats.setMaximumHeight(40)
        layout.addWidget(self.lbl_stats)
    
    def _load_initial_data(self):
        try:
            leagues = self.db.get_leagues()
            self.combo_league.clear()
            self.combo_league.addItem("-- Seleccionar Liga --", None)
            for league in leagues:
                self.combo_league.addItem(
                    f"{league['name']} ({league['fixtures']} partidos)",
                    league['id']
                )
        except Exception as e:
            logger.error(f"Error cargando datos: {e}")
    
    def _on_league_changed(self):
        league_id = self.combo_league.currentData()
        
        self.combo_season.clear()
        self.combo_season.addItem("Todas", None)
        if league_id:
            seasons = self.db.get_seasons(league_id)
            for s in seasons:
                self.combo_season.addItem(str(s), s)
        
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
    
    def _analyze_coverage(self):
        """Analiza la cobertura de odds para los filtros seleccionados."""
        league_id = self.combo_league.currentData()
        season = self.combo_season.currentData()
        team_id = self.combo_team.currentData()
        team_name = self.combo_team.currentText()
        
        if not league_id:
            return
        
        try:
            # Obtener fixtures con y sin odds
            fixtures = self.db.get_fixtures_with_odds(
                league_id=league_id,
                season=season,
                team_id=team_id,
                limit=500
            )
            
            # También obtener fixtures sin odds
            all_fixtures = self._get_all_fixtures(league_id, season, team_id)
            
            # Crear diccionario de fixtures con odds
            fixtures_with_odds = {fw.fixture.fixture_id for fw in fixtures if fw.odds}
            
            # Datos para heatmap
            heatmap_data = []
            missing_fixtures = []
            
            for fixture in all_fixtures:
                has_odds = fixture['id'] in fixtures_with_odds
                heatmap_data.append({
                    'date': fixture['date'],
                    'has_odds': has_odds,
                    'fixture_id': fixture['id'],
                    'home': fixture['home'],
                    'away': fixture['away'],
                    'score': fixture['score']
                })
                
                if not has_odds:
                    missing_fixtures.append(fixture)
            
            # Ordenar por fecha
            heatmap_data.sort(key=lambda x: x['date'] if x['date'] else "")
            
            # Actualizar heatmap
            self.heatmap.set_data(heatmap_data, team_name if team_id else "Liga completa")
            
            # Calcular cobertura por período
            period_data = self._calculate_period_coverage(heatmap_data)
            self.period_chart.set_data(period_data)
            
            # Llenar tabla de partidos sin odds
            self._fill_missing_table(missing_fixtures)
            
            # Estadísticas
            total = len(heatmap_data)
            with_odds = sum(1 for d in heatmap_data if d['has_odds'])
            without_odds = total - with_odds
            coverage = (with_odds / total * 100) if total > 0 else 0
            
            self.lbl_stats.setText(
                f"📊 Resumen: {total} partidos total | "
                f"✅ {with_odds} con odds ({coverage:.1f}%) | "
                f"❌ {without_odds} sin odds | "
                f"{'⚠️ Cobertura baja!' if coverage < 50 else '✅ Buena cobertura' if coverage >= 80 else '⚡ Cobertura media'}"
            )
            
        except Exception as e:
            logger.error(f"Error analizando cobertura: {e}")
            self.lbl_stats.setText(f"❌ Error: {str(e)}")
    
    def _get_all_fixtures(self, league_id: int, season: Optional[int], team_id: Optional[int]) -> List[Dict]:
        """Obtiene TODOS los fixtures (con o sin odds)."""
        query = """
            SELECT 
                f.id,
                f.date,
                th.name as home,
                ta.name as away,
                f.goals_home,
                f.goals_away
            FROM fixtures f
            JOIN teams th ON f.home_team_id = th.id
            JOIN teams ta ON f.away_team_id = ta.id
            WHERE f.league_id = :league_id
        """
        params = {'league_id': league_id}
        
        if season:
            query += " AND f.league_season = :season"
            params['season'] = season
        
        if team_id:
            query += " AND (f.home_team_id = :team_id OR f.away_team_id = :team_id2)"
            params['team_id'] = team_id
            params['team_id2'] = team_id
        
        query += " ORDER BY f.date DESC LIMIT 500"
        
        try:
            from sqlalchemy import text
            with self.db._engine.connect() as conn:
                result = conn.execute(text(query), params)
                rows = result.fetchall()
            
            fixtures = []
            for row in rows:
                score = f"{row[4]}-{row[5]}" if row[4] is not None else "vs"
                fixtures.append({
                    'id': row[0],
                    'date': row[1] or "",
                    'home': row[2],
                    'away': row[3],
                    'score': score
                })
            
            return fixtures
        except Exception as e:
            logger.error(f"Error obteniendo fixtures: {e}")
            return []
    
    def _calculate_period_coverage(self, data: List[Dict]) -> List[Dict]:
        """Calcula cobertura agrupada por mes."""
        by_month = defaultdict(lambda: {'total': 0, 'with_odds': 0})
        
        for item in data:
            if item['date']:
                try:
                    # Extraer año-mes
                    if isinstance(item['date'], str):
                        month = item['date'][:7]  # "2024-01"
                    else:
                        month = item['date'].strftime("%Y-%m")
                    
                    by_month[month]['total'] += 1
                    if item['has_odds']:
                        by_month[month]['with_odds'] += 1
                except:
                    pass
        
        # Convertir a lista ordenada
        result = []
        for period in sorted(by_month.keys()):
            result.append({
                'period': period,
                'total': by_month[period]['total'],
                'with_odds': by_month[period]['with_odds']
            })
        
        return result
    
    def _fill_missing_table(self, fixtures: List[Dict]):
        """Llena la tabla con partidos sin odds."""
        total = len(fixtures)
        show_count = min(total, 200)  # Mostrar hasta 200
        
        self.missing_table.setRowCount(show_count)
        self.lbl_count.setText(f"({total} partidos sin odds)")
        
        for i, f in enumerate(fixtures[:show_count]):
            date = f['date'][:10] if f['date'] else "--"
            
            # Número de fila
            num_item = QTableWidgetItem(str(i + 1))
            num_item.setTextAlignment(Qt.AlignCenter)
            self.missing_table.setItem(i, 0, num_item)
            
            self.missing_table.setItem(i, 1, QTableWidgetItem(date))
            self.missing_table.setItem(i, 2, QTableWidgetItem(f['home']))
            self.missing_table.setItem(i, 3, QTableWidgetItem(f['away']))
            self.missing_table.setItem(i, 4, QTableWidgetItem(f['score']))
            self.missing_table.setItem(i, 5, QTableWidgetItem(str(f['id'])))
