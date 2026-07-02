# extraction_window_v2.py
"""
Ventana de Extraccion de Datos - API Football
Version 2.1 - UI Mejorada + Optimizaciones

Mejoras v2.1:
- Límite de fixtures reducido a 500 para mejor rendimiento
- Auto-cálculo de constantes solo para fixtures FT (máx 50 equipos)
- Verificación inicial asíncrona (no bloquea UI)
- Soporte para nuevas ligas configuradas
"""

import os
import csv
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Any, Optional
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QLineEdit,
    QSpinBox, QDateEdit, QGroupBox, QProgressBar, QTextEdit,
    QTabWidget, QMessageBox, QHeaderView, QCheckBox, QFrame,
    QComboBox, QScrollArea, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QDate, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QBrush, QIcon
from config.season_mapping import get_current_season, group_leagues_by_season

# Imports del backend

HAS_BACKEND = False
ORIG_ENGINE = None
init_all_tables = None

try:
    from data.api_fetcher import APIFetcher
    from data.database_manager import ORIG_ENGINE
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import Column, Integer, String, Float, ForeignKey, and_
    from data.base import Base
    from data.data_models.teams import Team
    from data.data_models.fixtures import Fixture
    from data.data_models.players import Player
    from data.data_models.player_statistics import PlayerStatistic
    
    HAS_BACKEND = True
except ImportError as e:
    print(f" Backend parcialmente disponible: {e}")

# Configuracion de regiones de ligas
try:
    from config.api_config import LEAGUE_REGIONS
except ImportError:
    LEAGUE_REGIONS = {
        'Sudamerica': ['Argentina', 'Brazil', 'Chile', 'Colombia', 'Peru', 'Uruguay', 'Ecuador', 'Paraguay', 'Bolivia', 'Venezuela'],
        'Norteamerica': ['USA', 'Mexico', 'Canada'],
        'Europa': ['England', 'Spain', 'Germany', 'Italy', 'France', 'Portugal', 'Netherlands'],
        'Otros': ['World', 'Japan', 'China', 'Australia']
    }


# ============================================================================
# MODELOS PARA ODDS Y LEAGUES (si no existen)
# ============================================================================

try:
    from data.data_models.odds import Odd
except ImportError:
    if HAS_BACKEND:
        class Odd(Base):
            """Modelo para cuotas de apuestas"""
            __tablename__ = 'odds'
            __table_args__ = {'extend_existing': True}
            
            id = Column(Integer, primary_key=True, autoincrement=True)
            fixture_id = Column(Integer, ForeignKey('fixtures.id'), nullable=False, index=True)
            bookmaker_id = Column(Integer)
            bookmaker_name = Column(String)
            bet_id = Column(Integer)
            bet_name = Column(String)
            value = Column(String)  # Home, Draw, Away, etc.
            odd = Column(Float)
    else:
        Odd = None

try:
    from data.data_models.leagues import League
except ImportError:
    if HAS_BACKEND:
        class League(Base):
            """Modelo para ligas"""
            __tablename__ = 'leagues'
            __table_args__ = {'extend_existing': True}
            
            id = Column(Integer, primary_key=True)
            name = Column(String)
            country = Column(String)
            logo = Column(String)
            season = Column(Integer)
    else:
        League = None


# ============================================================================
# FUNCIONES DE PROCESAMIENTO DE DATOS
# ============================================================================

def process_fixtures(raw_fixtures: List[Dict]) -> List[Tuple]:
    """
    Convierte fixtures crudos de la API a formato para guardar.
    
    Args:
        raw_fixtures: Lista de dicts de la API
        
    Returns:
        Lista de tuplas (Fixture, home_team, away_team)
    """
    if not HAS_BACKEND:
        return []
    
    results = []
    
    for raw in raw_fixtures:
        try:
            fixture_data = raw.get('fixture', {})
            league_data = raw.get('league', {})
            teams_data = raw.get('teams', {})
            goals_data = raw.get('goals', {})
            score_data = raw.get('score', {})
            
            # Crear equipos
            home_data = teams_data.get('home', {})
            away_data = teams_data.get('away', {})
            
            home_team = Team(
                id=home_data.get('id'),
                name=home_data.get('name'),
                logo=home_data.get('logo')
            ) if home_data.get('id') else None
            
            away_team = Team(
                id=away_data.get('id'),
                name=away_data.get('name'),
                logo=away_data.get('logo')
            ) if away_data.get('id') else None
            
            # Parsear fecha
            date_str = fixture_data.get('date')
            fixture_date = None
            if date_str:
                try:
                    fixture_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except:
                    fixture_date = datetime.now()
            
            # Crear fixture
            fixture = Fixture(
                id=fixture_data.get('id'),
                referee=fixture_data.get('referee'),
                timezone=fixture_data.get('timezone'),
                date=fixture_date,
                timestamp=fixture_data.get('timestamp'),
                venue_id=fixture_data.get('venue', {}).get('id'),
                venue_name=fixture_data.get('venue', {}).get('name'),
                venue_city=fixture_data.get('venue', {}).get('city'),
                status_long=fixture_data.get('status', {}).get('long'),
                status_short=fixture_data.get('status', {}).get('short'),
                elapsed=fixture_data.get('status', {}).get('elapsed'),
                league_id=league_data.get('id'),
                league_season=league_data.get('season'),
                league_round=league_data.get('round'),
                home_team_id=home_data.get('id'),
                away_team_id=away_data.get('id'),
                goals_home=goals_data.get('home'),
                goals_away=goals_data.get('away'),
                halftime_home=score_data.get('halftime', {}).get('home'),
                halftime_away=score_data.get('halftime', {}).get('away'),
                fulltime_home=score_data.get('fulltime', {}).get('home'),
                fulltime_away=score_data.get('fulltime', {}).get('away'),
            )
            
            results.append((fixture, home_team, away_team))
            
        except Exception as e:
            print(f"Error procesando fixture: {e}")
            continue
    
    return results


def process_odds(raw_odds: List[Dict], fixture_id: int, preferred_bookmakers: List[int] = None) -> List:
    """
    Convierte odds crudos de la API a objetos Odd.
    
    Filtra localmente por bookmaker preferido: recorre la lista de preferencia
    y usa el PRIMER bookmaker que tenga datos disponibles.
    Si preferred_bookmakers es None, usa PREFERRED_BOOKMAKERS de api_config.
    
    Args:
        raw_odds: Lista de dicts de la API (puede contener múltiples bookmakers)
        fixture_id: ID del fixture
        preferred_bookmakers: Lista de IDs de bookmakers en orden de preferencia
        
    Returns:
        Lista de objetos Odd (del bookmaker preferido encontrado)
    """
    if not HAS_BACKEND or Odd is None:
        return []
    
    # Importar preferencias si no se pasaron
    if preferred_bookmakers is None:
        try:
            from config.api_config import PREFERRED_BOOKMAKERS
            preferred_bookmakers = PREFERRED_BOOKMAKERS
        except ImportError:
            preferred_bookmakers = []  # Sin filtro, procesar todos
    
    # Recopilar todos los bookmakers disponibles en la respuesta
    all_bookmakers = {}  # bookmaker_id -> bookie_data
    for item in raw_odds:
        for bookie in item.get('bookmakers', []):
            bk_id = bookie.get('id')
            if bk_id and bk_id not in all_bookmakers:
                all_bookmakers[bk_id] = bookie
    
    # Seleccionar el bookmaker preferido que esté disponible
    selected_bookies = []
    if preferred_bookmakers:
        for bk_id in preferred_bookmakers:
            if bk_id in all_bookmakers:
                selected_bookies = [all_bookmakers[bk_id]]
                break
        
        # Si ningún preferido está disponible, usar el primero que haya
        if not selected_bookies and all_bookmakers:
            first_id = next(iter(all_bookmakers))
            selected_bookies = [all_bookmakers[first_id]]
    else:
        # Sin filtro: procesar todos
        selected_bookies = list(all_bookmakers.values())
    
    # Convertir a objetos Odd
    odds_list = []
    for bookie in selected_bookies:
        bookmaker_id = bookie.get('id')
        bookmaker_name = bookie.get('name')
        
        for bet in bookie.get('bets', []):
            bet_id = bet.get('id')
            bet_name = bet.get('name')
            
            for value in bet.get('values', []):
                try:
                    odd = Odd(
                        fixture_id=fixture_id,
                        bookmaker_id=bookmaker_id,
                        bookmaker_name=bookmaker_name,
                        bet_id=bet_id,
                        bet_name=bet_name,
                        value=str(value.get('value', '')),
                        odd=float(value.get('odd', 0))
                    )
                    odds_list.append(odd)
                except Exception as e:
                    print(f"Error procesando odd: {e}")
                    continue
    
    return odds_list


def process_players_stats(raw_players: List[Dict]) -> Tuple[List, List]:
    """
    Procesa estadisticas de jugadores de la API.
    
    Args:
        raw_players: Lista de dicts de la API
        
    Returns:
        Tupla (lista_players, lista_stats) para usar con save_players_and_statistics
    """
    if not HAS_BACKEND:
        return [], []
    
    players_data = []
    
    for item in raw_players:
        try:
            player_info = item.get('player', {})
            statistics = item.get('statistics', [])
            
            # Crear Player
            player = Player(
                id=player_info.get('id'),
                name=player_info.get('name'),
                firstname=player_info.get('firstname'),
                lastname=player_info.get('lastname'),
                age=player_info.get('age'),
                birth_date=player_info.get('birth', {}).get('date'),
                birth_place=player_info.get('birth', {}).get('place'),
                nationality=player_info.get('nationality'),
                height=player_info.get('height'),
                weight=player_info.get('weight'),
                injured=player_info.get('injured'),
                photo=player_info.get('photo')
            )
            
            # Crear estadisticas
            stats_list = []
            for stat in statistics:
                team_data = stat.get('team', {})
                league_data = stat.get('league', {})
                games = stat.get('games', {})
                goals = stat.get('goals', {})
                paisses = stat.get('paisses', {})
                
                team = Team(
                    id=team_data.get('id'),
                    name=team_data.get('name'),
                    logo=team_data.get('logo')
                ) if team_data.get('id') else None
                
                player_stat = PlayerStatistic(
                    player_id=player.id,
                    team_id=team_data.get('id'),
                    league_id=league_data.get('id'),
                    season=league_data.get('season'),
                    games_appearences=games.get('appearences'),
                    games_lineups=games.get('lineups'),
                    games_minutes=games.get('minutes'),
                    games_position=games.get('position'),
                    games_rating=float(games.get('rating') or 0) if games.get('rating') else None,
                    goals_total=goals.get('total'),
                    goals_assists=goals.get('assists'),
                    paisses_total=paisses.get('total'),
                    paisses_accuracy=paisses.get('accuracy'),
                )
                stats_list.append(player_stat)
            
            players_data.append((player, team, stats_list))
            
        except Exception as e:
            print(f"Error procesando jugador: {e}")
            continue
    
    return players_data


# ============================================================================
# FUNCIONES DE BASE DE DATOS (wrappers)
# ============================================================================

def save_fixtures_wrapper(fixtures_data: List[Tuple]) -> int:
    """Wrapper para guardar fixtures"""
    if not HAS_BACKEND:
        return 0
    
    try:
        from data.api_database_manager import save_fixtures
        return save_fixtures(fixtures_data)
    except ImportError:
        # Implementacion local
        Session = sessionmaker(bind=ORIG_ENGINE)
        session = Session()
        count = 0
        
        try:
            for fixture, home_team, away_team in fixtures_data:
                if home_team and home_team.id:
                    session.merge(home_team)
                if away_team and away_team.id:
                    session.merge(away_team)
                if fixture and fixture.id:
                    session.merge(fixture)
                    count += 1
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
        
        return count


def save_odds_wrapper(odds_list: List) -> int:
    """Wrapper para guardar odds"""
    if not HAS_BACKEND or not odds_list:
        return 0
    
    try:
        from data.api_database_manager import save_odds
        return save_odds(odds_list)
    except ImportError:
        # Implementacion local
        Session = sessionmaker(bind=ORIG_ENGINE)
        session = Session()
        
        try:
            for odd in odds_list:
                session.merge(odd)
            session.commit()
            return len(odds_list)
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()


def save_players_wrapper(players_data: List) -> Tuple[int, int]:
    """Wrapper para guardar jugadores y estadisticas"""
    if not HAS_BACKEND or not players_data:
        return 0, 0
    
    try:
        from data.api_database_manager import save_players_and_statistics
        return save_players_and_statistics(players_data)
    except ImportError:
        # Implementacion local
        Session = sessionmaker(bind=ORIG_ENGINE)
        session = Session()
        players_count = 0
        stats_count = 0
        
        try:
            for player, team, stats_list in players_data:
                if team and team.id:
                    session.merge(team)
                if player and player.id:
                    session.merge(player)
                    players_count += 1
                for stat in stats_list:
                    session.merge(stat)
                    stats_count += 1
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
        
        return players_count, stats_count


def get_teams_by_league_wrapper(league_id: int) -> List:
    """Wrapper para obtener equipos por liga"""
    if not HAS_BACKEND:
        return []
    
    try:
        from data.api_database_manager import get_teams_by_league
        return get_teams_by_league(league_id)
    except ImportError:
        # Implementacion local
        from sqlalchemy import distinct
        Session = sessionmaker(bind=ORIG_ENGINE)
        session = Session()
        
        try:
            # Obtener equipos que han jugado en esta liga
            home_ids = session.query(distinct(Fixture.home_team_id)).filter(
                Fixture.league_id == league_id
            ).all()
            away_ids = session.query(distinct(Fixture.away_team_id)).filter(
                Fixture.league_id == league_id
            ).all()
            
            team_ids = set([t[0] for t in home_ids if t[0]]) | set([t[0] for t in away_ids if t[0]])
            
            teams = session.query(Team).filter(Team.id.in_(team_ids)).all()
            return teams
        except Exception as e:
            print(f"Error obteniendo equipos: {e}")
            return []
        finally:
            session.close()


def save_team_statistics_wrapper(stats_data: Dict) -> bool:
    """Wrapper para guardar estadisticas de equipo"""
    if not HAS_BACKEND:
        return False
    
    try:
        from data.api_database_manager import save_team_statistics
        return save_team_statistics(stats_data)
    except ImportError:
        # Por ahora solo retornar True (implementar si es necesario)
        print(f"save_team_statistics no implementado localmente")
        return True


def has_odds_extracted_wrapper(fixture_id: int) -> bool:
    """Verifica si un fixture tiene odds extraidos"""
    if not HAS_BACKEND:
        return False
    
    try:
        from data.api_database_manager import has_odds_extracted
        return has_odds_extracted(fixture_id)
    except ImportError:
        Session = sessionmaker(bind=ORIG_ENGINE)
        session = Session()
        
        try:
            count = session.query(Odd).filter(Odd.fixture_id == fixture_id).count()
            return count > 0
        except:
            return False
        finally:
            session.close()


def init_tables():
    """Inicializa tablas en la BD"""
    if not HAS_BACKEND:
        return
    
    try:
        from data.api_database_manager import init_all_tables
        init_all_tables()
    except ImportError:
        Base.metadata.create_all(ORIG_ENGINE)


# ============================================================================
# ESTILOS CSS
# ============================================================================

STYLES = """
QMainWindow {
    background-color: #f5f6fa;
}

QGroupBox {
    font-weight: bold;
    border: 2px solid #dcdde1;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 10px;
    background-color: white;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 8px;
    color: #2f3640;
}

QPushButton {
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 500;
    border: none;
}

QPushButton:hover {
    opacity: 0.9;
}

QPushButton:disabled {
    background-color: #dcdde1;
    color: #7f8c8d;
}

QTableWidget {
    border: 1px solid #dcdde1;
    border-radius: 8px;
    background-color: white;
    gridline-color: #ecf0f1;
}

QTableWidget::item {
    padding: 5px;
}

QTableWidget::item:selected {
    background-color: #74b9ff;
    color: white;
}

QHeaderView::section {
    background-color: #f8f9fa;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #dcdde1;
    font-weight: bold;
    color: #2f3640;
}

QLineEdit, QSpinBox, QDateEdit, QComboBox {
    padding: 8px;
    border: 2px solid #dcdde1;
    border-radius: 6px;
    background-color: white;
}

QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus {
    border-color: #74b9ff;
}

QProgressBar {
    border: none;
    border-radius: 10px;
    background-color: #ecf0f1;
    height: 20px;
    text-align: center;
}

QProgressBar::chunk {
    border-radius: 10px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00b894, stop:1 #00cec9);
}

QTabWidget::pane {
    border: 2px solid #dcdde1;
    border-radius: 8px;
    background-color: white;
}

QTabBar::tab {
    background-color: #f8f9fa;
    padding: 10px 20px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: white;
    border-bottom: 3px solid #0984e3;
}

QTabBar::tab:hover:!selected {
    background-color: #dfe6e9;
}
"""


# ============================================================================
# BACKGROUND DB QUERY THREAD (para consultas sin bloquear UI)
# ============================================================================

class _DBQueryThread(QThread):
    """Hilo ligero para ejecutar consultas de BD sin bloquear la UI"""
    result_ready = Signal(object)
    error_occurred = Signal(str)
    
    def __init__(self, query_func, parent=None):
        super().__init__(parent)
        self._query_func = query_func
    
    def run(self):
        try:
            result = self._query_func()
            self.result_ready.emit(result)
        except Exception as e:
            import traceback
            self.error_occurred.emit(f"{str(e)}\n{traceback.format_exc()}")


# ============================================================================
# WORKER THREAD
# ============================================================================

class ExtractionWorker(QThread):
    """Worker thread para extracciones en background"""
    progress = Signal(int, str)
    finished = Signal(dict)
    error = Signal(str)
    log = Signal(str, str)  # mensaje, tipo (info/success/warning/error)
    
    def __init__(self, task_type, **kwargs):
        super().__init__()
        self.task_type = task_type
        self.kwargs = kwargs
        self._stop = False
    
    def stop(self):
        self._stop = True
    
    def run(self):
        if not HAS_BACKEND:
            self.error.emit("Backend no disponible. Verifica las importaciones.")
            return
            
        try:
            if self.task_type == 'fixtures':
                self._extract_fixtures()
            elif self.task_type == 'players':
                self._extract_players()
            elif self.task_type == 'team_stats':
                self._extract_team_stats()
            elif self.task_type == 'odds':
                self._extract_odds()
            elif self.task_type == 'odds_single':
                self._extract_odds_single()
            elif self.task_type == 'sync_constants':
                self._sync_constants_task()
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
    
    def _extract_fixtures(self):
        league_ids = self.kwargs.get('league_ids', [])
        season = self.kwargs.get('season', 2024)
        date_from = self.kwargs.get('date_from')
        date_to = self.kwargs.get('date_to')
        
        total = len(league_ids)
        all_fixtures = []
        
        fetcher = APIFetcher()
        
        for i, lid in enumerate(league_ids):
            if self._stop:
                self.log.emit("Operacion cancelada por el usuario", "warning")
                break
            
            pct = int((i / total) * 100)
            self.progress.emit(pct, f"Liga {lid} ({i+1}/{total})")
            self.log.emit(f"Extrayendo fixtures de liga {lid}...", "info")
            
            try:
                # Llamar API con parametros correctos
                raw_fixtures = fetcher.get_fixtures(
                    league_ids=[lid],
                    season=season,
                    from_date=date_from,
                    to_date=date_to
                )
                
                if raw_fixtures:
                    fixtures = process_fixtures(raw_fixtures)
                    save_fixtures_wrapper(fixtures)
                    all_fixtures.extend(fixtures)
                    self.log.emit(f"Liga {lid}: {len(fixtures)} fixtures guardados", "success")
                else:
                    self.log.emit(f"Liga {lid}: Sin fixtures disponibles", "warning")
                    
            except Exception as e:
                self.log.emit(f"Liga {lid}: Error - {str(e)}", "error")
        
        # AUTO-CALCULO DE CONSTANTES (solo si hay fixtures FT nuevos)
        auto_calc = self.kwargs.get('auto_calculate_constants', True)
        if auto_calc and all_fixtures:
            self._auto_calculate_constants(all_fixtures)
        
        self.progress.emit(100, "Completado")
        self.finished.emit({'type': 'fixtures', 'count': len(all_fixtures)})
    
    def _extract_odds(self):
        fixture_ids = self.kwargs.get('fixture_ids', [])
        
        total = len(fixture_ids)
        fetcher = APIFetcher()
        saved = 0
        
        for i, fid in enumerate(fixture_ids):
            if self._stop:
                break
            
            pct = int((i / total) * 100)
            self.progress.emit(pct, f"Fixture {fid} ({i+1}/{total})")
            self.log.emit(f"Extrayendo odds de fixture {fid}...", "info")
            
            try:
                raw_odds = fetcher.get_odds_with_fallback(fid)
                
                if raw_odds:
                    odds_list = process_odds(raw_odds, fid)
                    save_odds_wrapper(odds_list)
                    saved += 1
                    self.log.emit(f"Fixture {fid}: {len(odds_list)} cuotas guardadas", "success")
                else:
                    self.log.emit(f"Fixture {fid}: Sin odds disponibles", "warning")
                    
            except Exception as e:
                self.log.emit(f"Fixture {fid}: Error - {str(e)}", "error")
        
        self.progress.emit(100, "Completado")
        self.finished.emit({'type': 'odds', 'count': saved})
    
    def _extract_odds_single(self):
        fixture_id = self.kwargs.get('fixture_id')
        
        self.progress.emit(25, f"Consultando API...")
        self.log.emit(f"Extrayendo odds para fixture {fixture_id}...", "info")
        
        fetcher = APIFetcher()
        
        try:
            raw_odds = fetcher.get_odds_with_fallback(fixture_id)
            
            if raw_odds:
                self.progress.emit(50, "Procesando...")
                odds_list = process_odds(raw_odds, fixture_id)
                
                self.progress.emit(75, "Guardando...")
                save_odds_wrapper(odds_list)
                
                self.log.emit(f"Guardadas {len(odds_list)} cuotas", "success")
                self.progress.emit(100, "Completado")
                self.finished.emit({'type': 'odds_single', 'count': len(odds_list)})
            else:
                self.log.emit(f"Sin odds disponibles para este fixture", "warning")
                self.progress.emit(100, "Sin datos")
                self.finished.emit({'type': 'odds_single', 'count': 0})
                
        except Exception as e:
            self.error.emit(str(e))
    
    def _extract_players(self):
        league_id = self.kwargs.get('league_id')
        season = self.kwargs.get('season', 2024)
        
        self.progress.emit(10, "Consultando API...")
        self.log.emit(f"Extrayendo jugadores de liga {league_id}...", "info")
        
        fetcher = APIFetcher()
        
        try:
            raw = fetcher.get_all_players_stats(league_id, season)
            
            if raw:
                self.progress.emit(50, "Procesando datos...")
                players_data = process_players_stats(raw)
                
                self.progress.emit(75, "Guardando en BD...")
                players_count, stats_count = save_players_wrapper(players_data)
                
                self.log.emit(f"Guardados {players_count} jugadores y {stats_count} estadisticas", "success")
                self.progress.emit(100, "Completado")
                self.finished.emit({'type': 'players', 'players': players_count, 'stats': stats_count})
            else:
                self.log.emit("Sin datos de jugadores", "warning")
                self.finished.emit({'type': 'players', 'players': 0, 'stats': 0})
                
        except Exception as e:
            self.error.emit(str(e))
    
    def _extract_team_stats(self):
        league_id = self.kwargs.get('league_id')
        season = self.kwargs.get('season', 2024)
        
        self.log.emit(f"Obteniendo equipos de liga {league_id}...", "info")
        
        try:
            teams = get_teams_by_league_wrapper(league_id)
            
            if not teams:
                self.log.emit("No se encontraron equipos", "warning")
                self.finished.emit({'type': 'team_stats', 'count': 0})
                return
            
            fetcher = APIFetcher()
            total = len(teams)
            saved = 0
            
            for i, team in enumerate(teams):
                if self._stop:
                    break
                
                team_id = team.id if hasattr(team, 'id') else team['id']
                team_name = team.name if hasattr(team, 'name') else team['name']
                
                pct = int((i / total) * 100)
                self.progress.emit(pct, f"{team_name} ({i+1}/{total})")
                self.log.emit(f"Extrayendo stats de {team_name}...", "info")
                
                try:
                    raw = fetcher.get_team_statistics(team_id, league_id, season)
                    if raw and 'response' in raw:
                        save_team_statistics_wrapper(raw['response'])
                        saved += 1
                        self.log.emit(f"{team_name}: OK", "success")
                except Exception as e:
                    self.log.emit(f"{team_name}: Error - {str(e)}", "error")
            
            self.progress.emit(100, "Completado")
            self.finished.emit({'type': 'team_stats', 'count': saved})
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _auto_calculate_constants(self, fixtures_data: list):
        """
        Calcula constantes automaticamente para los equipos de los fixtures extraidos.
        SOLO calcula si hay fixtures nuevos con resultados (FT).
        Limita a maximo 50 equipos para evitar demoras excesivas.
        
        Args:
            fixtures_data: Lista de tuplas (Fixture, home_team, away_team)
        """
        try:
            # Importar calculador de constantes
            try:
                from utils.constants_calculator import ConstantsCalculator
            except ImportError:
                self.log.emit("⚠ ConstantsCalculator no disponible - Constantes no calculadas", "warning")
                return
            
            # Filtrar solo fixtures terminados (FT) para calcular constantes
            finished_fixtures = []
            for fixture_tuple in fixtures_data:
                fixture = fixture_tuple[0] if isinstance(fixture_tuple, tuple) else fixture_tuple
                if hasattr(fixture, 'status_short') and fixture.status_short in ('FT', 'AET', 'PEN'):
                    finished_fixtures.append(fixture_tuple)
            
            if not finished_fixtures:
                self.log.emit("ℹ No hay fixtures terminados nuevos - Constantes no calculadas", "info")
                return
            
            # Extraer IDs unicos de equipos de fixtures terminados
            team_ids = set()
            for fixture_tuple in finished_fixtures:
                fixture = fixture_tuple[0] if isinstance(fixture_tuple, tuple) else fixture_tuple
                
                if hasattr(fixture, 'home_team_id') and fixture.home_team_id:
                    team_ids.add(fixture.home_team_id)
                if hasattr(fixture, 'away_team_id') and fixture.away_team_id:
                    team_ids.add(fixture.away_team_id)
            
            if not team_ids:
                self.log.emit("No hay equipos para calcular constantes", "warning")
                return
            
            # Limitar a maximo 50 equipos para evitar demoras
            if len(team_ids) > 50:
                self.log.emit(f"⚠ Limitando calculo a 50 equipos (de {len(team_ids)})", "warning")
                team_ids = set(list(team_ids)[:50])
            
            self.log.emit(f"📊 Calculando constantes para {len(team_ids)} equipos ({len(finished_fixtures)} fixtures FT)...", "info")
            
            # Calcular constantes para cada equipo
            with ConstantsCalculator() as calculator:
                success = 0
                errors = 0
                
                for i, team_id in enumerate(team_ids, 1):
                    if self._stop:
                        self.log.emit("Calculo de constantes cancelado", "warning")
                        break
                    
                    try:
                        # Usar calculo incremental (mas eficiente)
                        result = calculator.incremental_calculate_and_store(team_id)
                        if result:
                            success += 1
                        
                        # Emitir progreso parcial cada 10 equipos
                        if i % 10 == 0:
                            self.log.emit(f"   Constantes: {i}/{len(team_ids)} equipos procesados", "info")
                            
                    except Exception as e:
                        errors += 1
                        if errors <= 3:  # Solo mostrar primeros 3 errores
                            self.log.emit(f"   Error calculando constantes equipo {team_id}: {e}", "error")
            
            # Resumen
            if errors == 0:
                self.log.emit(f"✅ Constantes calculadas: {success} equipos actualizados", "success")
            else:
                self.log.emit(f"⚠ Constantes: {success} OK, {errors} errores", "warning")
                
        except Exception as e:
            self.log.emit(f"❌ Error en auto-calculo de constantes: {e}", "error")
    
    def _sync_constants_task(self):
        """
        Tarea para sincronizar constantes desde la pestana de Constantes.
        """
        league_id = self.kwargs.get('league_id')
        incremental = self.kwargs.get('incremental', True)
        
        self.log.emit("📊 Iniciando sincronizacion de constantes...", "info")
        
        try:
            from utils.constants_calculator import ConstantsCalculator
            from data.database_manager import SessionOrig
            from data.data_models.teams import Team
            from data.data_models.fixtures import Fixture
            from sqlalchemy import or_, distinct
            
            session = SessionOrig()
            
            # Obtener equipos a procesar
            query = session.query(distinct(Fixture.home_team_id)).filter(
                Fixture.status_short == 'FT'
            )
            
            if league_id:
                query = query.filter(Fixture.league_id == league_id)
                self.log.emit(f"Filtrando por liga {league_id}", "info")
            
            home_teams = {t[0] for t in query.all() if t[0]}
            
            query = session.query(distinct(Fixture.away_team_id)).filter(
                Fixture.status_short == 'FT'
            )
            if league_id:
                query = query.filter(Fixture.league_id == league_id)
            
            away_teams = {t[0] for t in query.all() if t[0]}
            
            team_ids = home_teams | away_teams
            session.close()
            
            total = len(team_ids)
            self.log.emit(f"Procesando {total} equipos...", "info")
            
            if total == 0:
                self.log.emit("No hay equipos para procesar", "warning")
                self.finished.emit({'type': 'sync_constants', 'success': 0, 'errors': 0})
                return
            
            success = 0
            errors = 0
            
            with ConstantsCalculator() as calculator:
                for i, team_id in enumerate(team_ids, 1):
                    if self._stop:
                        self.log.emit("Operacion cancelada", "warning")
                        break
                    
                    pct = int((i / total) * 100)
                    self.progress.emit(pct, f"Equipo {i}/{total}")
                    
                    try:
                        if incremental:
                            result = calculator.incremental_calculate_and_store(team_id)
                        else:
                            result = calculator.calculate_and_store(team_id)
                        
                        if result:
                            success += 1
                        
                        # Log cada 10 equipos
                        if i % 10 == 0:
                            self.log.emit(f"   Progreso: {i}/{total} equipos", "info")
                            
                    except Exception as e:
                        errors += 1
                        self.log.emit(f"   Error equipo {team_id}: {e}", "error")
            
            self.progress.emit(100, "Completado")
            
            if errors == 0:
                self.log.emit(f"✅ Sincronizacion completada: {success} equipos procesados", "success")
            else:
                self.log.emit(f"⚠ Completado con errores: {success} OK, {errors} errores", "warning")
            
            self.finished.emit({'type': 'sync_constants', 'success': success, 'errors': errors})
            
        except Exception as e:
            self.error.emit(str(e))


# ============================================================================
# VENTANA PRINCIPAL
# ============================================================================

class ExtractionWindow(QMainWindow):
    """Ventana principal de extraccion de datos API - Version 2.1"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📡 Extraccion de Datos - API Football")
        self.setStyleSheet(STYLES)
        
        # === Adaptar al tamano real de la pantalla ===
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            w = min(1500, int(available.width() * 0.92))
            h = min(950, int(available.height() * 0.90))
            self.resize(w, h)
            x = available.x() + (available.width() - w) // 2
            y = available.y() + (available.height() - h) // 2
            self.move(x, y)
        else:
            self.resize(1500, 950)
        
        # Inicializar
        if init_all_tables:
            try:
                init_all_tables()
            except Exception as e:
                print(f"Error inicializando tablas: {e}")
        
        self.leagues_data = []
        self.fixtures_data = []
        self.worker = None
        self._db_thread = None
        self._check_thread = None
        self._count_update_timer = None
        self._season_queue = []

        self._build_ui()
        self._load_leagues()
        
        # === VERIFICACION AUTOMATICA AL INICIAR (async) ===
        QTimer.singleShot(500, self._check_pending_data_on_start)
    
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # === PANEL IZQUIERDO: LIGAS ===
        left_panel = self._build_leagues_panel()
        main_layout.addWidget(left_panel)
        
        # === PANEL DERECHO: CONTENIDO PRINCIPAL ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(10)
        right_panel.setMinimumWidth(600)
        
        # Tabs principales
        self.tabs = QTabWidget()
        self._build_fixtures_tab()
        self._build_odds_tab()
        self._build_players_tab()
        self._build_constants_tab()
        right_layout.addWidget(self.tabs, 1)
        
        # Panel de log y progreso
        log_panel = self._build_log_panel()
        right_layout.addWidget(log_panel)
        
        main_layout.addWidget(right_panel, 1)
    
    def _build_leagues_panel(self):
        """Construye el panel de ligas"""
        panel = QWidget()
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(420)
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        
        # Titulo
        title = QLabel("⚽ LIGAS DISPONIBLES")
        title.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #2d3436;
            padding: 10px;
            background: white;
            border-radius: 8px;
        """)
        layout.addWidget(title)
        
        # Busqueda
        search_frame = QFrame()
        search_frame.setStyleSheet("background: white; border-radius: 8px; padding: 5px;")
        search_layout = QHBoxLayout(search_frame)
        search_layout.addWidget(QLabel("🔍"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar liga o pais...")
        self.search_input.textChanged.connect(self._filter_leagues)
        self.search_input.setStyleSheet("border: none;")
        search_layout.addWidget(self.search_input)
        layout.addWidget(search_frame)
        
        # Filtros por region
        region_frame = QFrame()
        region_frame.setStyleSheet("background: white; border-radius: 8px; padding: 8px;")
        region_layout = QHBoxLayout(region_frame)
        region_layout.setSpacing(5)
        
        for region, icon in [('Sudamerica', '🌎'), ('Norteamerica', '🌎'), ('Europa', '🌍'), ('Otros', '🌏')]:
            btn = QPushButton(f"{icon} {region}")
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #f8f9fa;
                    color: #2d3436;
                    padding: 6px 10px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #74b9ff;
                    color: white;
                }
            """)
            btn.clicked.connect(lambda c, r=region: self._filter_by_region(r))
            region_layout.addWidget(btn)
        
        layout.addWidget(region_frame)
        
        # Tabla de ligas
        self.leagues_table = QTableWidget()
        self.leagues_table.setColumnCount(4)
        self.leagues_table.setHorizontalHeaderLabels(['✓', 'ID', 'Liga', 'Pais'])
        self.leagues_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.leagues_table.setColumnWidth(0, 35)
        self.leagues_table.setColumnWidth(1, 50)
        self.leagues_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.leagues_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.leagues_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.leagues_table.setAlternatingRowColors(True)
        layout.addWidget(self.leagues_table, 1)
        # CAMBIO 1: Conectar señal UNA SOLA VEZ al crear el widget
        self.leagues_table.itemChanged.connect(self._on_league_checkbox_changed)
        
        # Botones de seleccion
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setSpacing(10)
        
        btn_all = QPushButton("✅ Seleccionar Todo")
        btn_all.setStyleSheet("background-color: #00b894; color: white;")
        btn_all.clicked.connect(lambda: self._select_all_leagues(True))
        btn_layout.addWidget(btn_all)
        
        btn_none = QPushButton("❌ Limpiar")
        btn_none.setStyleSheet("background-color: #636e72; color: white;")
        btn_none.clicked.connect(lambda: self._select_all_leagues(False))
        btn_layout.addWidget(btn_none)
        
        layout.addWidget(btn_frame)
        
        # Contador
        self.selection_count = QLabel("Liga:")
        self.selection_count.setStyleSheet("""
            color: #636e72;
            padding: 8px;
            background: white;
            border-radius: 6px;
            font-weight: 500;
        """)
        layout.addWidget(self.selection_count)
        
        return panel
    
    def _build_fixtures_tab(self):
        """Construye la pestana de fixtures"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        
        # === SECCION 1: EXTRACCION API ===
        api_group = QGroupBox("📡 EXTRACCION DESDE API")
        api_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                border: 2px solid #0984e3;
            }
            QGroupBox::title {
                color: #0984e3;
            }
        """)
        api_layout = QVBoxLayout(api_group)
        
        row1 = QHBoxLayout()
        
        row1.addWidget(QLabel("Temporada:"))
        self.api_season = QSpinBox()
        self.api_season.setRange(2015, 2030)
        self.api_season.setValue(2024)
        self.api_season.setMinimumWidth(80)
        row1.addWidget(self.api_season)
        
        row1.addSpacing(30)
        
        self.chk_auto_constants = QCheckBox("📊 Calcular constantes automaticamente")
        self.chk_auto_constants.setChecked(True)
        self.chk_auto_constants.setToolTip(
            "Si esta activado, se calcularan las constantes (K values) para los equipos\n"
            "de los fixtures terminados (FT). Limitado a 50 equipos por extraccion."
        )
        row1.addWidget(self.chk_auto_constants)
        
        row1.addStretch()
        
        btn_extract = QPushButton("🚀 EXTRAER FIXTURES DE LIGAS SELECCIONADAS")
        btn_extract.setStyleSheet("""
            QPushButton {
                background-color: #00b894;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #00a381; }
        """)
        btn_extract.clicked.connect(self._extract_fixtures)
        row1.addWidget(btn_extract)
        
        btn_verify = QPushButton("⚠️ Verificar Datos Pendientes")
        btn_verify.setStyleSheet("""
            QPushButton {
                background-color: #e17055;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 10px 15px;
            }
            QPushButton:hover { background-color: #d63031; }
        """)
        btn_verify.setToolTip("Verifica partidos sin resultados, odds faltantes y cobertura de ligas")
        btn_verify.clicked.connect(self._show_sync_dialog)
        row1.addWidget(btn_verify)
        
        btn_refresh_season = QPushButton("🔄 Actualizar temporada en curso")
        btn_refresh_season.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                font-size: 12px;
                font-weight: bold;
                padding: 10px 15px;
            }
            QPushButton:hover { background-color: #5b4cdb; }
        """)
        btn_refresh_season.setToolTip(
            "Extrae fixtures de la temporada actualmente en curso\n"
            "para todas las ligas configuradas (Europa=2025/26, Sudamerica=2026, etc.)"
        )
        btn_refresh_season.clicked.connect(self._refresh_current_season)
        row1.addWidget(btn_refresh_season)
       
        api_layout.addLayout(row1)
        
        info_label = QLabel("ℹ️ La API extrae TODOS los fixtures de la temporada seleccionada para las ligas marcadas")
        info_label.setStyleSheet("color: #636e72; font-size: 11px; padding: 5px;")
        api_layout.addWidget(info_label)
        
        layout.addWidget(api_group)
        
        # === SECCION 2: VISTA DE BASE DE DATOS ===
        db_group = QGroupBox("🗄️ FIXTURES EN BASE DE DATOS")
        db_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                border: 2px solid #6c5ce7;
            }
            QGroupBox::title {
                color: #6c5ce7;
            }
        """)
        db_layout = QVBoxLayout(db_group)
        
        # Filtros de fecha
        date_row = QHBoxLayout()
        
        date_row.addWidget(QLabel("Desde:"))
        self.db_date_from = QDateEdit()
        self.db_date_from.setCalendarPopup(True)
        self.db_date_from.setDate(QDate.currentDate().addMonths(-1))
        self.db_date_from.setMinimumWidth(120)
        date_row.addWidget(self.db_date_from)
        
        date_row.addWidget(QLabel("Hasta:"))
        self.db_date_to = QDateEdit()
        self.db_date_to.setCalendarPopup(True)
        self.db_date_to.setDate(QDate.currentDate().addDays(7))
        self.db_date_to.setMinimumWidth(120)
        date_row.addWidget(self.db_date_to)
        
        date_row.addSpacing(15)
        
        date_row.addWidget(QLabel("Rangos:"))
        for text, days_back, days_forward in [
            ("Ultima semana", 7, 0),
            ("Ultimo mes", 30, 0),
            ("Proxima semana", 0, 7),
            ("Todo el mes", 15, 15)
        ]:
            btn = QPushButton(text)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #f8f9fa;
                    color: #2d3436;
                    padding: 4px 8px;
                    font-size: 10px;
                }
                QPushButton:hover { background-color: #74b9ff; color: white; }
            """)
            btn.clicked.connect(lambda c, b=days_back, f=days_forward: self._set_db_date_range(b, f))
            date_row.addWidget(btn)
        
        date_row.addStretch()
        db_layout.addLayout(date_row)
        
        # Otros filtros
        filter_row = QHBoxLayout()
        
        filter_row.addWidget(QLabel("Liga:"))
        self.db_league_filter = QComboBox()
        self.db_league_filter.addItem("Todas las ligas", None)
        self.db_league_filter.setMinimumWidth(150)
        filter_row.addWidget(self.db_league_filter)
        
        filter_row.addWidget(QLabel("Estado:"))
        self.db_status_filter = QComboBox()
        self.db_status_filter.addItems(["Todos", "Terminados (FT)", "Programados (NS)", "En vivo"])
        self.db_status_filter.setMinimumWidth(130)
        filter_row.addWidget(self.db_status_filter)
        
        filter_row.addWidget(QLabel("ODDS:"))
        self.db_odds_filter = QComboBox()
        self.db_odds_filter.addItems(["Todos", "Con ODDS", "Sin ODDS"])
        self.db_odds_filter.setMinimumWidth(100)
        filter_row.addWidget(self.db_odds_filter)
        
        filter_row.addStretch()
        
        btn_load = QPushButton("🔄 Cargar")
        btn_load.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                padding: 8px 15px;
            }
            QPushButton:hover { background-color: #5b4cdb; }
        """)
        btn_load.clicked.connect(self._load_fixtures)
        filter_row.addWidget(btn_load)
        
        db_layout.addLayout(filter_row)
        
        # Tabla de fixtures
        self.fixtures_table = QTableWidget()
        self.fixtures_table.setColumnCount(9)
        self.fixtures_table.setHorizontalHeaderLabels([
            '✓', 'ID', 'Fecha', 'Liga', 'Local', 'Marcador', 'Visitante', 'Estado', 'ODDS'
        ])
        self.fixtures_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.fixtures_table.setColumnWidth(0, 35)
        self.fixtures_table.setColumnWidth(1, 75)
        self.fixtures_table.setColumnWidth(2, 140)
        self.fixtures_table.setColumnWidth(3, 60)
        self.fixtures_table.setColumnWidth(5, 70)
        self.fixtures_table.setColumnWidth(7, 70)
        self.fixtures_table.setColumnWidth(8, 60)
        self.fixtures_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.fixtures_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.fixtures_table.setAlternatingRowColors(True)
        self.fixtures_table.setSelectionBehavior(QTableWidget.SelectRows)
        db_layout.addWidget(self.fixtures_table, 1)
        # CAMBIO 2: Conectar señal UNA SOLA VEZ al crear el widget
        self.fixtures_table.itemChanged.connect(self._on_fixture_checkbox_changed)
        
        # Info y acciones
        info_row = QHBoxLayout()
        
        self.fixtures_info = QLabel("📊 Fixtures: 0 | Seleccionados: 0 | Con ODDS: 0")
        self.fixtures_info.setStyleSheet("color: #636e72; font-weight: 500;")
        info_row.addWidget(self.fixtures_info)
        
        info_row.addStretch()
        
        btn_select_no_odds = QPushButton("Seleccionar sin ODDS")
        btn_select_no_odds.setStyleSheet("background-color: #fdcb6e; color: #2d3436;")
        btn_select_no_odds.clicked.connect(self._select_fixtures_without_odds)
        info_row.addWidget(btn_select_no_odds)
        
        db_layout.addLayout(info_row)
        
        layout.addWidget(db_group, 1)
        
        self.tabs.addTab(tab, "📋 Fixtures")

    def _build_odds_tab(self):
        """Construye la pestana de odds"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Metodo 1: Por ID individual
        group1 = QGroupBox("🎯 Extraccion por ID de Fixture")
        group1.setStyleSheet("QGroupBox { border: 2px solid #e17055; } QGroupBox::title { color: #e17055; }")
        g1_layout = QHBoxLayout(group1)
        
        g1_layout.addWidget(QLabel("Fixture ID:"))
        self.odds_fixture_id = QSpinBox()
        self.odds_fixture_id.setRange(1, 99999999)
        self.odds_fixture_id.setValue(1)
        self.odds_fixture_id.setMinimumWidth(120)
        g1_layout.addWidget(self.odds_fixture_id)
        
        btn_single = QPushButton("📥 Extraer ODDS")
        btn_single.setStyleSheet("background-color: #e17055; color: white; padding: 10px 20px;")
        btn_single.clicked.connect(self._extract_odds_single)
        g1_layout.addWidget(btn_single)
        
        g1_layout.addStretch()
        layout.addWidget(group1)
        
        # Metodo 2: Desde seleccion
        group2 = QGroupBox("📋 Extraccion de Fixtures Seleccionados")
        group2.setStyleSheet("QGroupBox { border: 2px solid #00cec9; } QGroupBox::title { color: #00cec9; }")
        g2_layout = QVBoxLayout(group2)
        
        info = QLabel("""
            <p style='color: #636e72; line-height: 1.6;'>
            <b>Pasos:</b><br>
            1️⃣ Ve a la pestana <b>Fixtures</b><br>
            2️⃣ Carga los fixtures desde la BD<br>
            3️⃣ Marca los fixtures deseados (checkbox) o usa "Seleccionar sin ODDS"<br>
            4️⃣ Regresa aqui y pulsa el boton
            </p>
        """)
        g2_layout.addWidget(info)
        
        btn_selected = QPushButton("📥 EXTRAER ODDS DE FIXTURES SELECCIONADOS")
        btn_selected.setStyleSheet("""
            QPushButton {
                background-color: #00cec9;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 15px;
            }
            QPushButton:hover { background-color: #00b5b0; }
        """)
        btn_selected.clicked.connect(self._extract_odds_selected)
        g2_layout.addWidget(btn_selected)
        
        layout.addWidget(group2)
        
        # Metodo 3: Automatico
        group3 = QGroupBox("🤖 Extraccion Automatica")
        group3.setStyleSheet("QGroupBox { border: 2px solid #636e72; } QGroupBox::title { color: #636e72; }")
        g3_layout = QVBoxLayout(group3)
        
        auto_info = QLabel("Detecta automaticamente los fixtures cargados que NO tienen odds en la BD")
        auto_info.setStyleSheet("color: #636e72;")
        g3_layout.addWidget(auto_info)
        
        btn_auto = QPushButton("⚡ Extraer ODDS Faltantes")
        btn_auto.setStyleSheet("background-color: #636e72; color: white; padding: 10px;")
        btn_auto.clicked.connect(self._extract_odds_auto)
        g3_layout.addWidget(btn_auto)
        
        layout.addWidget(group3)
        
        layout.addStretch()
        
        self.tabs.addTab(tab, "💰 Odds / Cuotas")
    
    def _build_players_tab(self):
        """Construye la pestana de jugadores"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(20)
        
        # Jugadores
        group1 = QGroupBox("👤 Extraer Jugadores por Liga")
        group1.setStyleSheet("QGroupBox { border: 2px solid #0984e3; } QGroupBox::title { color: #0984e3; }")
        g1_layout = QHBoxLayout(group1)
        
        g1_layout.addWidget(QLabel("Liga:"))
        self.players_league_id = QSpinBox()
        self.players_league_id.setRange(1, 9999)
        self.players_league_id.setValue(39)
        g1_layout.addWidget(self.players_league_id)
        
        g1_layout.addWidget(QLabel("Temporada:"))
        self.players_season = QSpinBox()
        self.players_season.setRange(2015, 2030)
        self.players_season.setValue(2024)
        g1_layout.addWidget(self.players_season)
        
        btn = QPushButton("📥 Extraer Jugadores")
        btn.setStyleSheet("background-color: #0984e3; color: white; padding: 10px 20px;")
        btn.clicked.connect(self._extract_players)
        g1_layout.addWidget(btn)
        
        g1_layout.addStretch()
        layout.addWidget(group1)
        
        # Stats de equipos
        group2 = QGroupBox("📊 Estadisticas de Equipos")
        group2.setStyleSheet("QGroupBox { border: 2px solid #6c5ce7; } QGroupBox::title { color: #6c5ce7; }")
        g2_layout = QHBoxLayout(group2)
        
        g2_layout.addWidget(QLabel("Liga:"))
        self.stats_league_id = QSpinBox()
        self.stats_league_id.setRange(1, 9999)
        self.stats_league_id.setValue(39)
        g2_layout.addWidget(self.stats_league_id)
        
        g2_layout.addWidget(QLabel("Temporada:"))
        self.stats_season = QSpinBox()
        self.stats_season.setRange(2015, 2030)
        self.stats_season.setValue(2024)
        g2_layout.addWidget(self.stats_season)
        
        btn2 = QPushButton("📥 Extraer Stats")
        btn2.setStyleSheet("background-color: #6c5ce7; color: white; padding: 10px 20px;")
        btn2.clicked.connect(self._extract_team_stats)
        g2_layout.addWidget(btn2)
        
        g2_layout.addStretch()
        layout.addWidget(group2)
        
        # Advertencia
        warn_frame = QFrame()
        warn_frame.setStyleSheet("""
            background-color: #ffeaa7;
            border-radius: 8px;
            padding: 15px;
        """)
        warn_layout = QHBoxLayout(warn_frame)
        warn_layout.addWidget(QLabel("⚠️"))
        warn_layout.addWidget(QLabel("La extraccion de jugadores consume muchas llamadas API. Usala con moderacion."))
        warn_layout.addStretch()
        layout.addWidget(warn_frame)
        
        layout.addStretch()
        
        self.tabs.addTab(tab, "👥 Jugadores")
    
    def _build_constants_tab(self):
        """Construye la pestana de sincronizacion de constantes"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Header
        header = QLabel("📊 SINCRONIZACION DE CONSTANTES (K Values)")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #2d3436;")
        layout.addWidget(header)
        
        info = QLabel(
            "Las constantes (K values) son metricas de rendimiento calculadas a partir de los resultados "
            "de los partidos. Son necesarias para las predicciones del modelo ML.\n\n"
            "✅ Las constantes se calculan automaticamente al extraer fixtures (si la opcion esta activada)\n"
            "📊 Usa esta pestana para sincronizar constantes de partidos que ya estan en la BD"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #636e72; font-size: 12px; padding: 10px; background-color: #f8f9fa; border-radius: 8px;")
        layout.addWidget(info)
        
        # === DIAGNOSTICO ===
        diag_group = QGroupBox("🔍 Diagnostico")
        diag_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #00b894;
            }
            QGroupBox::title { color: #00b894; }
        """)
        diag_layout = QVBoxLayout(diag_group)
        
        btn_diagnose = QPushButton("📊 Ver estado de constantes")
        btn_diagnose.setStyleSheet("""
            QPushButton {
                background-color: #00b894;
                color: white;
                font-size: 13px;
                padding: 10px;
            }
            QPushButton:hover { background-color: #00a381; }
        """)
        btn_diagnose.clicked.connect(self._diagnose_constants)
        diag_layout.addWidget(btn_diagnose)
        
        self.constants_status = QTextEdit()
        self.constants_status.setReadOnly(True)
        self.constants_status.setMaximumHeight(150)
        self.constants_status.setStyleSheet("""
            QTextEdit {
                background-color: #2d3436;
                color: #dfe6e9;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border-radius: 6px;
            }
        """)
        diag_layout.addWidget(self.constants_status)
        
        layout.addWidget(diag_group)
        
        # === SINCRONIZACION ===
        sync_group = QGroupBox("🔄 Sincronizacion")
        sync_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #0984e3;
            }
            QGroupBox::title { color: #0984e3; }
        """)
        sync_layout = QVBoxLayout(sync_group)
        
        # Selector de liga
        liga_row = QHBoxLayout()
        liga_row.addWidget(QLabel("Liga:"))
        self.const_league_filter = QComboBox()
        self.const_league_filter.addItem("🌐 Todas las ligas", None)
        self.const_league_filter.setMinimumWidth(250)
        liga_row.addWidget(self.const_league_filter)
        liga_row.addStretch()
        sync_layout.addLayout(liga_row)
        
        # Botones de accion
        btn_row = QHBoxLayout()
        
        btn_sync = QPushButton("📊 Calcular constantes faltantes")
        btn_sync.setStyleSheet("""
            QPushButton {
                background-color: #0984e3;
                color: white;
                font-size: 13px;
                padding: 10px;
            }
            QPushButton:hover { background-color: #0873c4; }
        """)
        btn_sync.setToolTip("Calcula constantes solo para partidos nuevos (incremental)")
        btn_sync.clicked.connect(self._sync_constants)
        btn_row.addWidget(btn_sync)
        
        btn_recalc = QPushButton("🔄 Recalcular TODO")
        btn_recalc.setStyleSheet("""
            QPushButton {
                background-color: #d63031;
                color: white;
                font-size: 13px;
                padding: 10px;
            }
            QPushButton:hover { background-color: #b52828; }
        """)
        btn_recalc.setToolTip("Borra y recalcula todas las constantes desde cero (lento)")
        btn_recalc.clicked.connect(self._full_recalc_constants)
        btn_row.addWidget(btn_recalc)
        
        sync_layout.addLayout(btn_row)
        layout.addWidget(sync_group)
        
        # Advertencia
        warn_frame = QFrame()
        warn_frame.setStyleSheet("background-color: #ffeaa7; border-radius: 6px; padding: 8px;")
        warn_layout = QHBoxLayout(warn_frame)
        warn_layout.addWidget(QLabel("⚠️"))
        warn_layout.addWidget(QLabel("El calculo de constantes puede tomar varios minutos si hay muchos equipos/partidos."))
        warn_layout.addStretch()
        layout.addWidget(warn_frame)
        
        layout.addStretch()
        
        self.tabs.addTab(tab, "📈 Constantes")
        
        # Cargar ligas en el combo
        QTimer.singleShot(500, self._populate_constants_leagues)
    
    def _populate_constants_leagues(self):
        """Carga las ligas disponibles en el combo de constantes"""
        try:
            for league in self.leagues_data:
                lid = league.get('id', league.get('league_id', league.get('League ID')))
                name = league.get('name', league.get('league_name', league.get('League Name', f'Liga {lid}')))
                country = league.get('country', league.get('Country Name', ''))
                
                display = f"{name} ({country})" if country else name
                self.const_league_filter.addItem(display, lid)
        except Exception as e:
            print(f"Error cargando ligas para constantes: {e}")
    
    def _diagnose_constants(self):
        """Ejecuta diagnostico de constantes - VERSION ASYNC"""
        self.constants_status.clear()
        self.constants_status.append("🔍 Analizando estado de constantes...\n")
        
        def _query():
            from utils.constants_calculator import ConstantsCalculator, ConstantResult
            from data.database_manager import SessionOrig, SessionConst
            from data.data_models.fixtures import Fixture
            from sqlalchemy import func
            
            session_orig = SessionOrig()
            session_const = SessionConst()
            
            try:
                teams_with_fixtures = session_orig.query(
                    func.count(func.distinct(Fixture.home_team_id))
                ).filter(Fixture.status_short == 'FT').scalar() or 0
                
                teams_with_constants = session_const.query(
                    func.count(func.distinct(ConstantResult.team_id))
                ).scalar() or 0
                
                total_fixtures = session_orig.query(func.count(Fixture.id)).filter(
                    Fixture.status_short == 'FT'
                ).scalar() or 0
                
                total_constants = session_const.query(func.count(ConstantResult.id)).scalar() or 0
                
                return {
                    'teams_with_fixtures': teams_with_fixtures,
                    'teams_with_constants': teams_with_constants,
                    'total_fixtures': total_fixtures,
                    'total_constants': total_constants,
                }
            finally:
                session_orig.close()
                session_const.close()
        
        def _on_result(data):
            teams_with_fixtures = data['teams_with_fixtures']
            teams_with_constants = data['teams_with_constants']
            total_fixtures = data['total_fixtures']
            total_constants = data['total_constants']
            
            coverage = (teams_with_constants / teams_with_fixtures * 100) if teams_with_fixtures > 0 else 0
            
            self.constants_status.append(f"📊 ESTADO DE CONSTANTES")
            self.constants_status.append(f"{'='*40}")
            self.constants_status.append(f"")
            self.constants_status.append(f"Equipos con partidos:     {teams_with_fixtures:,}")
            self.constants_status.append(f"Equipos con constantes:   {teams_with_constants:,}")
            self.constants_status.append(f"Cobertura:                {coverage:.1f}%")
            self.constants_status.append(f"")
            self.constants_status.append(f"Fixtures terminados:      {total_fixtures:,}")
            self.constants_status.append(f"Registros de constantes:  {total_constants:,}")
            self.constants_status.append(f"")
            
            if coverage < 100:
                missing = teams_with_fixtures - teams_with_constants
                self.constants_status.append(f"⚠️ Faltan constantes para ~{missing} equipos")
                self.constants_status.append(f"   Usa 'Calcular constantes faltantes' para sincronizar")
            else:
                self.constants_status.append(f"✅ Todas las constantes estan calculadas")
        
        def _on_error(error_msg):
            self.constants_status.append(f"❌ Error: {error_msg}")
        
        self._diag_thread = _DBQueryThread(_query, self)
        self._diag_thread.result_ready.connect(_on_result)
        self._diag_thread.error_occurred.connect(_on_error)
        self._diag_thread.start()
    
    def _sync_constants(self):
        """Sincroniza constantes faltantes"""
        league_id = self.const_league_filter.currentData()
        
        msg = "Calcular constantes faltantes"
        if league_id:
            msg += f" para liga {league_id}"
        msg += "?\n\nEsto puede tomar varios minutos."
        
        reply = QMessageBox.question(self, "Confirmar", msg, 
            QMessageBox.Yes | QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        self._log("📊 Iniciando calculo de constantes faltantes...", "info")
        self._start_worker('sync_constants', league_id=league_id, incremental=True)
    
    def _full_recalc_constants(self):
        """Recalcula todas las constantes"""
        league_id = self.const_league_filter.currentData()
        
        msg = "⚠️ ADVERTENCIA: Esto borrara y recalculara TODAS las constantes"
        if league_id:
            msg += f" de la liga {league_id}"
        msg += ".\n\nEstas seguro? Este proceso puede tomar MUCHO tiempo."
        
        reply = QMessageBox.warning(self, "Confirmar recalculo completo", msg,
            QMessageBox.Yes | QMessageBox.No)
        
        if reply != QMessageBox.Yes:
            return
        
        self._log("🔄 Iniciando recalculo completo de constantes...", "warning")
        self._start_worker('sync_constants', league_id=league_id, incremental=False)
    
    def _build_log_panel(self):
        """Construye el panel de log y progreso"""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 10px;
                border: 1px solid #dcdde1;
            }
        """)
        panel.setMaximumHeight(200)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # Barra de progreso
        progress_row = QHBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        self.progress_bar.setTextVisible(True)
        progress_row.addWidget(self.progress_bar, 1)
        
        self.progress_label = QLabel("✅ Listo")
        self.progress_label.setMinimumWidth(180)
        self.progress_label.setStyleSheet("font-weight: 500; color: #2d3436;")
        progress_row.addWidget(self.progress_label)
        
        self.btn_cancel = QPushButton("❌ Cancelar")
        self.btn_cancel.setStyleSheet("background-color: #d63031; color: white;")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_operation)
        progress_row.addWidget(self.btn_cancel)
        
        layout.addLayout(progress_row)
        
        # Log con formato
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(130)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #2d3436;
                color: #dfe6e9;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                border-radius: 8px;
                padding: 10px;
                border: none;
            }
        """)
        layout.addWidget(self.log_text)
        
        return panel
    
    # =========================================================================
    # METODOS DE CARGA
    # =========================================================================
    
    def _load_leagues(self):
        """Carga ligas desde CSV"""
        csv_paths = [
            'leagues2024.csv',
            'data/leagues2024.csv',
            '../leagues2024.csv',
            '/mnt/user-data/uploads/leagues2024.csv',
        ]
        
        for path in csv_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        self.leagues_data = list(reader)
                    self._log(f"Cargadas {len(self.leagues_data)} ligas", "success")
                    self._populate_leagues_table()
                    self._populate_league_filter()
                    return
                except Exception as e:
                    self._log(f"Error leyendo {path}: {e}", "error")
        
        self._log("No se encontro archivo de ligas", "warning")
    
    def _populate_leagues_table(self, data=None):
        """Rellena tabla de ligas - OPTIMIZADO"""
        if data is None:
            data = self.leagues_data
        
        self.leagues_table.setUpdatesEnabled(False)
        self.leagues_table.blockSignals(True)
        
        try:
            self.leagues_table.setRowCount(len(data))
            
            for i, league in enumerate(data):
                # Checkbox
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)
                self.leagues_table.setItem(i, 0, chk_item)
                
                # ID
                lid = league.get('League ID', '')
                item_id = QTableWidgetItem(str(lid))
                item_id.setData(Qt.UserRole, lid)
                item_id.setTextAlignment(Qt.AlignCenter)
                self.leagues_table.setItem(i, 1, item_id)
                
                # Nombre
                name = league.get('League Name', '')
                self.leagues_table.setItem(i, 2, QTableWidgetItem(name))
                
                # Pais
                country = league.get('Country Name', '')
                item_country = QTableWidgetItem(country)
                if country in LEAGUE_REGIONS.get('Europa', []):
                    item_country.setBackground(QColor('#dfe6e9'))
                elif country in LEAGUE_REGIONS.get('Sudamerica', []):
                    item_country.setBackground(QColor('#ffeaa7'))
                self.leagues_table.setItem(i, 3, item_country)
        finally:
            self.leagues_table.blockSignals(False)
            self.leagues_table.setUpdatesEnabled(True)
        # CAMBIO 3: Eliminado bloque disconnect/reconnect - señal ya conectada en _build_leagues_panel
    
    def _populate_league_filter(self):
        """Rellena el combo de filtro de ligas"""
        self.db_league_filter.clear()
        self.db_league_filter.addItem("Todas las ligas", None)
        
        seen = set()
        for league in self.leagues_data:
            lid = league.get('League ID', '')
            name = league.get('League Name', '')
            if lid and lid not in seen:
                self.db_league_filter.addItem(f"{lid} - {name}", lid)
                seen.add(lid)
    
    def _load_fixtures(self):
        """Carga fixtures desde BD - VERSION ASYNC"""
        if not HAS_BACKEND or ORIG_ENGINE is None:
            self._log("Backend no disponible", "error")
            return
        
        self.progress_label.setText("🔄 Cargando fixtures...")
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(0)
        
        try:
            filters = {
                'date_from': self.db_date_from.date().toString("yyyy-MM-dd"),
                'date_to': self.db_date_to.date().toString("yyyy-MM-dd"),
                'league_id': self.db_league_filter.currentData(),
                'status_text': self.db_status_filter.currentText(),
                'odds_text': self.db_odds_filter.currentText(),
            }
        except Exception as e:
            self._log(f"Error leyendo filtros: {e}", "error")
            return
        
        def _query():
            return self._execute_fixtures_query(filters)
        
        if self._db_thread and self._db_thread.isRunning():
            self._db_thread.wait(1000)
        
        self._db_thread = _DBQueryThread(_query, self)
        self._db_thread.result_ready.connect(self._on_fixtures_loaded)
        self._db_thread.error_occurred.connect(self._on_fixtures_load_error)
        self._db_thread.start()
    
    def _execute_fixtures_query(self, filters):
        """Ejecuta la consulta SQL de fixtures"""
        from sqlalchemy import text
        
        date_from = filters['date_from']
        date_to = filters['date_to']
        league_id = filters['league_id']
        status_text = filters['status_text']
        odds_text = filters['odds_text']
        
        status_filter = None
        if status_text == "Terminados (FT)":
            status_filter = ('FT', 'AET', 'PEN')
        elif status_text == "Programados (NS)":
            status_filter = ('NS', 'TBD')
        elif status_text == "En vivo":
            status_filter = ('1H', '2H', 'HT', 'LIVE', 'ET', 'BT', 'P')
        
        odds_filter = None
        if odds_text == "Con ODDS":
            odds_filter = True
        elif odds_text == "Sin ODDS":
            odds_filter = False
        
        query_parts = ["""
            SELECT 
                f.id, 
                f.date, 
                f.league_id, 
                f.status_short,
                f.goals_home, 
                f.goals_away,
                ht.name as home_name, 
                at.name as away_name,
                CASE WHEN EXISTS (
                    SELECT 1 FROM odds o WHERE o.fixture_id = f.id
                ) THEN 1 ELSE 0 END as has_odds
            FROM fixtures f
            LEFT JOIN teams ht ON f.home_team_id = ht.id
            LEFT JOIN teams at ON f.away_team_id = at.id
            WHERE DATE(f.date) >= :date_from 
              AND DATE(f.date) <= :date_to
        """]
        
        params = {"date_from": date_from, "date_to": date_to}
        
        if league_id is not None:
            query_parts.append("AND f.league_id = :league_id")
            params["league_id"] = league_id
        
        if status_filter:
            placeholders = ", ".join([f":status_{i}" for i in range(len(status_filter))])
            query_parts.append(f"AND f.status_short IN ({placeholders})")
            for i, status in enumerate(status_filter):
                params[f"status_{i}"] = status
        
        # OPTIMIZACION: Reducido de 2000 a 500
        query_parts.append("ORDER BY f.date DESC LIMIT 500")
        query_str = " ".join(query_parts)
        
        with ORIG_ENGINE.connect() as conn:
            result = conn.execute(text(query_str), params)
            rows = result.fetchall()
        
        if odds_filter is not None:
            if odds_filter:
                rows = [r for r in rows if r[8] == 1]
            else:
                rows = [r for r in rows if r[8] == 0]
        
        return {
            'rows': rows,
            'filters': filters,
            'status_text': status_text,
            'odds_text': odds_text,
        }
    
    def _on_fixtures_loaded(self, result):
        """Callback cuando los fixtures se cargan"""
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)
        self.progress_label.setText("✅ Carga completada")
        
        rows = result['rows']
        filters = result['filters']
        
        self.fixtures_data = rows
        self._populate_fixtures_table(rows)
        
        filter_info = []
        if filters.get('league_id'):
            filter_info.append(f"Liga:{filters['league_id']}")
        if result.get('status_text') and result['status_text'] != 'Todos':
            filter_info.append(f"Estado:{result['status_text']}")
        if result.get('odds_text') and result['odds_text'] != 'Todos':
            filter_info.append(f"ODDS:{result['odds_text']}")
        
        filter_str = f" | Filtros: {', '.join(filter_info)}" if filter_info else ""
        self._log(
            f"Cargados {len(rows)} fixtures "
            f"({filters['date_from']} a {filters['date_to']}){filter_str}", 
            "success"
        )
    
    def _on_fixtures_load_error(self, error_msg):
        """Callback para errores de carga"""
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_label.setText("❌ Error en carga")
        self._log(f"Error cargando fixtures: {error_msg}", "error")
        self._load_fixtures_simple()

    def _load_fixtures_simple(self):
        """Carga fixtures sin verificacion de ODDS (fallback)"""
        try:
            from sqlalchemy import text
            
            # OPTIMIZACION: Reducido de 1000 a 500
            query = text("""
                SELECT 
                    f.id, f.date, f.league_id, f.status_short,
                    f.goals_home, f.goals_away,
                    ht.name as home_name, at.name as away_name
                FROM fixtures f
                LEFT JOIN teams ht ON f.home_team_id = ht.id
                LEFT JOIN teams at ON f.away_team_id = at.id
                ORDER BY f.date DESC
                LIMIT 500
            """)
            
            with ORIG_ENGINE.connect() as conn:
                result = conn.execute(query)
                rows = result.fetchall()
            
            self.fixtures_data = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], None) for r in rows]
            self._populate_fixtures_table(self.fixtures_data)
            self._log(f"Cargados {len(rows)} fixtures (sin verificacion ODDS)", "warning")
            
        except Exception as e:
            self._log(f"Error en carga simple: {e}", "error")
    
    def _populate_fixtures_table(self, data):
        """Rellena tabla de fixtures - OPTIMIZADO"""
        self.fixtures_table.setUpdatesEnabled(False)
        self.fixtures_table.blockSignals(True)
        
        try:
            self.fixtures_table.setRowCount(len(data))
            
            bold_font = QFont("Arial", 10, QFont.Bold)
            
            bg_ft = QColor('#d4edda')
            fg_ft = QColor('#155724')
            bg_ns = QColor('#cce5ff')
            fg_ns = QColor('#004085')
            bg_live = QColor('#fff3cd')
            fg_live = QColor('#856404')
            bg_odds_yes = QColor('#d4edda')
            bg_odds_no = QColor('#f8d7da')
            bg_odds_unk = QColor('#e2e3e5')
            
            odds_count = 0
            
            for i, row in enumerate(data):
                # Checkbox
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk_item.setCheckState(Qt.Unchecked)
                self.fixtures_table.setItem(i, 0, chk_item)
                
                # ID
                fid = row[0]
                item_id = QTableWidgetItem(str(fid))
                item_id.setData(Qt.UserRole, fid)
                item_id.setTextAlignment(Qt.AlignCenter)
                self.fixtures_table.setItem(i, 1, item_id)
                
                # Fecha
                fecha = str(row[1])[:16] if row[1] else ''
                item_fecha = QTableWidgetItem(fecha)
                item_fecha.setTextAlignment(Qt.AlignCenter)
                self.fixtures_table.setItem(i, 2, item_fecha)
                
                # Liga
                item_liga = QTableWidgetItem(str(row[2] or ''))
                item_liga.setTextAlignment(Qt.AlignCenter)
                self.fixtures_table.setItem(i, 3, item_liga)
                
                # Local
                self.fixtures_table.setItem(i, 4, QTableWidgetItem(str(row[6] or '')))
                
                # Marcador
                gh = row[4] if row[4] is not None else '-'
                ga = row[5] if row[5] is not None else '-'
                item_score = QTableWidgetItem(f"{gh} - {ga}")
                item_score.setTextAlignment(Qt.AlignCenter)
                item_score.setFont(bold_font)
                self.fixtures_table.setItem(i, 5, item_score)
                
                # Visitante
                self.fixtures_table.setItem(i, 6, QTableWidgetItem(str(row[7] or '')))
                
                # Estado
                status = str(row[3] or '')
                item_status = QTableWidgetItem(status)
                item_status.setTextAlignment(Qt.AlignCenter)
                if status in ('FT', 'AET', 'PEN'):
                    item_status.setBackground(bg_ft)
                    item_status.setForeground(fg_ft)
                elif status == 'NS':
                    item_status.setBackground(bg_ns)
                    item_status.setForeground(fg_ns)
                elif status in ('1H', '2H', 'HT', 'LIVE'):
                    item_status.setBackground(bg_live)
                    item_status.setForeground(fg_live)
                self.fixtures_table.setItem(i, 7, item_status)
                
                # ODDS
                has_odds = row[8] if len(row) > 8 else None
                if has_odds == 1:
                    item_odds = QTableWidgetItem("✅")
                    item_odds.setBackground(bg_odds_yes)
                    odds_count += 1
                elif has_odds == 0:
                    item_odds = QTableWidgetItem("❌")
                    item_odds.setBackground(bg_odds_no)
                else:
                    item_odds = QTableWidgetItem("?")
                    item_odds.setBackground(bg_odds_unk)
                item_odds.setTextAlignment(Qt.AlignCenter)
                item_odds.setData(Qt.UserRole, has_odds)
                self.fixtures_table.setItem(i, 8, item_odds)
        finally:
            self.fixtures_table.blockSignals(False)
            self.fixtures_table.setUpdatesEnabled(True)
        # CAMBIO 4: Eliminado bloque disconnect/reconnect - señal ya conectada en _build_fixtures_tab
        
        self._update_fixtures_info()
    
    # =========================================================================
    # FILTROS Y SELECCION
    # =========================================================================
    
    def _filter_leagues(self, text):
        """Filtra ligas por texto"""
        text = text.lower()
        
        if not text:
            self._populate_leagues_table()
            return
        
        filtered = [
            l for l in self.leagues_data
            if text in l.get('League Name', '').lower() or 
               text in l.get('Country Name', '').lower() or
               text in str(l.get('League ID', ''))
        ]
        self._populate_leagues_table(filtered)
    
    def _filter_by_region(self, region):
        """Filtra por region geografica"""
        if region not in LEAGUE_REGIONS:
            return
        
        countries = LEAGUE_REGIONS[region]
        filtered = [
            l for l in self.leagues_data
            if l.get('Country Name', '') in countries
        ]
        self._populate_leagues_table(filtered)
        self._log(f"Filtrado por {region}: {len(filtered)} ligas", "info")
    
    def _select_all_leagues(self, select):
        """Selecciona/deselecciona todas las ligas visibles"""
        self.leagues_table.blockSignals(True)
        try:
            state = Qt.Checked if select else Qt.Unchecked
            for i in range(self.leagues_table.rowCount()):
                chk_item = self.leagues_table.item(i, 0)
                if chk_item:
                    chk_item.setCheckState(state)
        finally:
            self.leagues_table.blockSignals(False)
        self._update_selection_count()
    
    def _select_fixtures_without_odds(self):
        """Selecciona fixtures sin ODDS"""
        self.fixtures_table.blockSignals(True)
        count = 0
        try:
            for i in range(self.fixtures_table.rowCount()):
                odds_item = self.fixtures_table.item(i, 8)
                chk_item = self.fixtures_table.item(i, 0)
                if odds_item and chk_item:
                    has_odds = odds_item.data(Qt.UserRole)
                    if has_odds == 0:
                        chk_item.setCheckState(Qt.Checked)
                        count += 1
                    else:
                        chk_item.setCheckState(Qt.Unchecked)
        finally:
            self.fixtures_table.blockSignals(False)
        
        self._log(f"Seleccionados {count} fixtures sin ODDS", "info")
        self._update_fixtures_info()
    
    def _set_db_date_range(self, days_back, days_forward):
        """Establece rango de fechas"""
        today = QDate.currentDate()
        self.db_date_from.setDate(today.addDays(-days_back))
        self.db_date_to.setDate(today.addDays(days_forward))

    def _get_selected_league_ids(self):
        """Obtiene IDs de ligas seleccionadas"""
        ids = []
        for i in range(self.leagues_table.rowCount()):
            chk_item = self.leagues_table.item(i, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                item = self.leagues_table.item(i, 1)
                if item:
                    try:
                        ids.append(int(item.data(Qt.UserRole)))
                    except:
                        pass
        return ids
    
    def _get_selected_fixture_ids(self):
        """Obtiene IDs de fixtures seleccionados"""
        ids = []
        for i in range(self.fixtures_table.rowCount()):
            chk_item = self.fixtures_table.item(i, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                item = self.fixtures_table.item(i, 1)
                if item:
                    try:
                        ids.append(int(item.data(Qt.UserRole)))
                    except:
                        pass
        return ids
    
    def _on_league_checkbox_changed(self, item):
        """Handler para cambio en checkbox de liga"""
        if item.column() == 0:
            self._update_selection_count()
    
    def _on_fixture_checkbox_changed(self, item):
        """Handler para cambio en checkbox de fixture"""
        if item.column() == 0:
            if not self._count_update_timer:
                self._count_update_timer = QTimer(self)
                self._count_update_timer.setSingleShot(True)
                self._count_update_timer.timeout.connect(self._update_fixtures_info)
            self._count_update_timer.start(100)
    
    def _update_selection_count(self):
        """Actualiza contador de ligas seleccionadas"""
        count = len(self._get_selected_league_ids())
        self.selection_count.setText(f"📋 Ligas seleccionadas: {count}")
    
    def _update_fixtures_info(self):
        """Actualiza info de fixtures"""
        total = self.fixtures_table.rowCount()
        
        selected = 0
        odds_count = 0
        for i in range(total):
            chk_item = self.fixtures_table.item(i, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                selected += 1
            
            odds_item = self.fixtures_table.item(i, 8)
            if odds_item and odds_item.data(Qt.UserRole) == 1:
                odds_count += 1
        
        self.fixtures_info.setText(f"📊 Fixtures: {total} | Seleccionados: {selected} | Con ODDS: {odds_count}")
    
    # =========================================================================
    # EXTRACCIONES
    # =========================================================================
    
    def _extract_fixtures(self):
        """Extrae fixtures de ligas seleccionadas"""
        league_ids = self._get_selected_league_ids()
        
        if not league_ids:
            QMessageBox.warning(self, "Sin seleccion", "Selecciona al menos una liga del panel izquierdo")
            return
        
        auto_calc = self.chk_auto_constants.isChecked()
        
        self._log(f"Iniciando extraccion de {len(league_ids)} ligas para temporada {self.api_season.value()}...", "info")
        if auto_calc:
            self._log("📊 Auto-calculo de constantes habilitado (solo para fixtures FT)", "info")
        
        self._start_worker('fixtures',
            league_ids=league_ids,
            season=self.api_season.value(),
            date_from=None,
            date_to=None,
            auto_calculate_constants=auto_calc
        )

    def _extract_odds_single(self):
        """Extrae odds de un fixture"""
        self._start_worker('odds_single',
            fixture_id=self.odds_fixture_id.value()
        )
    
    def _extract_odds_selected(self):
        """Extrae odds de fixtures seleccionados"""
        fixture_ids = self._get_selected_fixture_ids()
        
        if not fixture_ids:
            QMessageBox.warning(self, "Sin seleccion", 
                "No hay fixtures seleccionados.\n\n"
                "1. Ve a la pestana Fixtures\n"
                "2. Carga fixtures desde BD\n"
                "3. Marca los fixtures deseados\n"
                "4. Vuelve aqui"
            )
            return
        
        self._log(f"Extrayendo ODDS para {len(fixture_ids)} fixtures...", "info")
        self._start_worker('odds', fixture_ids=fixture_ids)
    
    def _extract_odds_auto(self):
        """Extrae odds faltantes automaticamente"""
        fixture_ids = []
        
        for i in range(self.fixtures_table.rowCount()):
            odds_item = self.fixtures_table.item(i, 8)
            id_item = self.fixtures_table.item(i, 1)
            if odds_item and id_item:
                has_odds = odds_item.data(Qt.UserRole)
                if has_odds == 0:
                    try:
                        fixture_ids.append(int(id_item.data(Qt.UserRole)))
                    except:
                        pass
        
        if not fixture_ids:
            QMessageBox.information(self, "Info", 
                "No hay fixtures sin ODDS en la tabla.\n"
                "Carga fixtures primero desde la pestana Fixtures."
            )
            return
        
        reply = QMessageBox.question(self, "Confirmar",
            f"Se extraeran ODDS para {len(fixture_ids)} fixtures.\nContinuar?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._start_worker('odds', fixture_ids=fixture_ids)
    
    def _extract_players(self):
        """Extrae jugadores"""
        self._start_worker('players',
            league_id=self.players_league_id.value(),
            season=self.players_season.value()
        )
    
    def _extract_team_stats(self):
        """Extrae estadisticas de equipos"""
        self._start_worker('team_stats',
            league_id=self.stats_league_id.value(),
            season=self.stats_season.value()
        )
    
    # =========================================================================
    # WORKER MANAGEMENT
    # =========================================================================
    
    def _start_worker(self, task_type, **kwargs):
        """Inicia worker de extraccion"""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Ocupado", "Ya hay una extraccion en proceso")
            return
        
        self.progress_bar.setValue(0)
        self.btn_cancel.setEnabled(True)
        
        self.worker = ExtractionWorker(task_type, **kwargs)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.log.connect(self._log)
        self.worker.start()
    
    def _cancel_operation(self):
        """Cancela operacion en curso"""
        if self.worker:
            self.worker.stop()
            self._log("Cancelando operacion...", "warning")
    
    def _on_progress(self, value, text):
        """Actualiza progreso"""
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"🔄 {text}")
    
    def _on_finished(self, result):
        """Maneja finalizacion"""
        self.btn_cancel.setEnabled(False)
        self.progress_label.setText("✅ Completado")
        
        task_type = result.get('type', '')
        
        if task_type == 'fixtures':
            count = result.get('count', 0)
            if self._season_queue:
                self._log(f"✅ Grupo completado ({count} fixtures). Procesando siguiente...", "success")
                self._process_next_season_group()
                return
            QMessageBox.information(self, "✅ Completado", f"Extraidos {count} fixtures")
            self._load_fixtures()

        elif task_type == 'odds':
            count = result.get('count', 0)
            QMessageBox.information(self, "✅ Completado", f"ODDS extraidas para {count} fixtures")
            self._load_fixtures()
        elif task_type == 'odds_single':
            count = result.get('count', 0)
            if count > 0:
                QMessageBox.information(self, "✅ Completado", f"Extraidas {count} cuotas")
            else:
                QMessageBox.information(self, "Sin datos", "No hay odds disponibles para este fixture")
        elif task_type == 'players':
            players = result.get('players', 0)
            stats = result.get('stats', 0)
            QMessageBox.information(self, "✅ Completado", 
                f"Extraidos {players} jugadores\n{stats} estadisticas")
        elif task_type == 'team_stats':
            count = result.get('count', 0)
            QMessageBox.information(self, "✅ Completado", 
                f"Stats de {count} equipos extraidas")
        elif task_type == 'sync_constants':
            success = result.get('success', 0)
            errors = result.get('errors', 0)
            if errors == 0:
                QMessageBox.information(self, "✅ Completado",
                    f"Constantes calculadas para {success} equipos")
            else:
                QMessageBox.warning(self, "⚠️ Completado con errores",
                    f"Constantes: {success} OK, {errors} errores")
    
    def _on_error(self, error):
        """Maneja errores"""
        self.btn_cancel.setEnabled(False)
        self.progress_label.setText("❌ Error")
        self._log(f"ERROR: {error}", "error")
        QMessageBox.critical(self, "Error", f"Error en extraccion:\n{error}")
    
    def _log(self, message, msg_type="info"):
        """Anade mensaje al log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        colors = {
            "info": "#74b9ff",
            "success": "#00b894",
            "warning": "#fdcb6e",
            "error": "#ff7675"
        }
        
        icons = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌"
        }
        
        color = colors.get(msg_type, "#dfe6e9")
        icon = icons.get(msg_type, "")
        
        html = f'<span style="color: #636e72;">[{timestamp}]</span> ' \
               f'<span style="color: {color};">{icon} {message}</span>'
        
        self.log_text.append(html)
        
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # =========================================================================
    # SINCRONIZACION AUTOMATICA DE DATOS
    # =========================================================================
    
    def _show_sync_dialog(self):
        """Muestra el dialogo de sincronizacion de datos pendientes"""
        try:
            from data_sync_dialog import DataSyncDialog
            
            dialog = DataSyncDialog(self)
            result = dialog.exec()
            
            if result:
                self._load_fixtures()
                self._log("Datos verificados desde dialogo de sincronizacion", "success")
                
        except ImportError as e:
            QMessageBox.warning(
                self, 
                "Modulo no encontrado",
                f"No se pudo cargar el modulo data_sync_dialog:\n{e}\n\n"
                "Asegurate de que el archivo data_sync_dialog.py este en el directorio correcto."
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error al abrir dialogo:\n{e}")
            
    def _refresh_current_season(self):
        """Extrae fixtures de la temporada en curso para todas las ligas configuradas."""
        try:
            from data_sync_dialog import get_all_configured_league_ids
        except ImportError as e:
            QMessageBox.critical(self, "Error", f"No se pudo cargar data_sync_dialog:\n{e}")
            return
        
        country_by_id = {}
        for l in self.leagues_data:
            try:
                lid = int(l.get('League ID', 0))
                if lid:
                    country_by_id[lid] = l.get('Country Name', '')
            except (ValueError, TypeError):
                continue
        
        league_ids = get_all_configured_league_ids()
        if not league_ids:
            QMessageBox.warning(self, "Sin ligas", "No hay ligas configuradas en data_sync_dialog.")
            return
        
        groups = group_leagues_by_season(league_ids, country_by_id)
        
        summary = "\n".join(
            f"  • Temporada {s}: {len(ids)} ligas"
            for s, ids in groups.items()
        )
        
        reply = QMessageBox.question(
            self,
            "Confirmar actualizacion",
            f"Se actualizaran {len(league_ids)} ligas agrupadas por temporada:\n\n"
            f"{summary}\n\n"
            f"Cada grupo hace 1 llamada API por liga.\n"
            f"¿Continuar?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self._season_queue = list(groups.items())
        self._log(f"🔄 Iniciando actualizacion de {len(league_ids)} ligas en {len(self._season_queue)} grupo(s)...", "info")
        self._process_next_season_group()
    
    def _process_next_season_group(self):
        """Procesa el siguiente grupo de ligas en la cola de temporada."""
        if not self._season_queue:
            self._log("✅ Actualizacion de temporada en curso completada", "success")
            QMessageBox.information(
                self,
                "✅ Completado",
                "Actualizacion de temporada en curso finalizada para todas las ligas."
            )
            self._load_fixtures()
            return
        
        season, league_ids = self._season_queue.pop(0)
        self._log(f"📡 Procesando {len(league_ids)} ligas para temporada {season}...", "info")
        
        self._start_worker(
            'fixtures',
            league_ids=league_ids,
            season=season,
            date_from=None,
            date_to=None,
            auto_calculate_constants=self.chk_auto_constants.isChecked()
        )

    def _check_pending_data_on_start(self):
        """
        Verifica si hay datos pendientes al iniciar - VERSION ASINCRONA
        Se llama automaticamente 500ms despues de abrir la ventana.
        
        Detecta:
        1. Partidos sin resultados actualizados (ultima semana)
        2. Partidos proximos (72h) sin odds
        3. Ligas configuradas que NO tienen fixtures en la BD
        
        NOTA: Las queries estan sincronizadas con DataCheckWorker en data_sync_dialog.py
        - Usa REPLACE(f.date, 'T', ' ') para comparacion correcta en SQLite
        - Incluye f.status_short IS NULL para detectar fixtures sin estado
        """
        try:
            from data_sync_dialog import get_all_configured_league_ids, get_league_name_by_id, LIGAS_CONFIG
        except ImportError:
            self._log("data_sync_dialog no encontrado - verificacion omitida", "warning")
            return
        
        if not HAS_BACKEND or ORIG_ENGINE is None:
            return
        
        self._log("🔍 Verificando datos pendientes...", "info")
        
        def _query():
            """Ejecuta las verificaciones en background"""
            from sqlalchemy import text
            
            lima_tz = timezone(timedelta(hours=-5))
            now_lima = datetime.now(lima_tz)
            week_ago = now_lima - timedelta(days=7)
            three_days_later = now_lima + timedelta(days=3)
            
            league_ids = get_all_configured_league_ids()
            if not league_ids:
                return {'outdated': 0, 'odds': 0, 'leagues_configured': 0, 
                        'missing_leagues': [], 'missing_league_names': []}
            
            league_placeholders = ','.join([str(lid) for lid in league_ids])
            
            # Normalizar fechas a formato con espacio (consistente con DataCheckWorker)
            now_utc_str = now_lima.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            week_ago_str = week_ago.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            future_utc_str = three_days_later.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            
            # 1. Partidos desactualizados
            # SINCRONIZADO con DataCheckWorker._check_outdated_fixtures:
            # - REPLACE(f.date, 'T', ' ') para comparacion correcta en SQLite
            # - f.status_short IS NULL para detectar fixtures sin estado
            query_outdated = text(f"""
                SELECT COUNT(*) FROM fixtures f
                WHERE f.league_id IN ({league_placeholders})
                  AND REPLACE(f.date, 'T', ' ') < :now_utc
                  AND REPLACE(f.date, 'T', ' ') > :week_ago
                  AND (
                      f.status_short IS NULL
                      OR f.status_short NOT IN ('FT', 'AET', 'PEN')
                      OR f.goals_home IS NULL 
                      OR f.goals_away IS NULL
                  )
            """)
            
            # 2. Odds faltantes
            # SINCRONIZADO con DataCheckWorker._check_missing_odds:
            # - REPLACE(f.date, 'T', ' ') para comparacion correcta en SQLite
            query_odds = text(f"""
                SELECT COUNT(*) FROM fixtures f
                WHERE f.league_id IN ({league_placeholders})
                  AND REPLACE(f.date, 'T', ' ') > :now_utc
                  AND REPLACE(f.date, 'T', ' ') < :future_utc
                  AND f.status_short = 'NS'
                  AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.fixture_id = f.id)
            """)
            
            # 3. Ligas sin datos
            query_leagues_with_data = text(f"""
                SELECT DISTINCT league_id 
                FROM fixtures 
                WHERE league_id IN ({league_placeholders})
            """)
            
            outdated_count = 0
            odds_count = 0
            missing_leagues = []
            missing_league_names = []
            
            with ORIG_ENGINE.connect() as conn:
                result = conn.execute(query_outdated, {
                    'now_utc': now_utc_str,
                    'week_ago': week_ago_str
                })
                outdated_count = result.scalar() or 0
                
                result = conn.execute(query_odds, {
                    'now_utc': now_utc_str,
                    'future_utc': future_utc_str
                })
                odds_count = result.scalar() or 0
                
                # Detectar ligas sin datos
                result = conn.execute(query_leagues_with_data)
                leagues_with_data = {row[0] for row in result.fetchall()}
                
                for lid in league_ids:
                    if lid not in leagues_with_data:
                        missing_leagues.append(lid)
                        missing_league_names.append(get_league_name_by_id(lid))
            
            return {
                'outdated': outdated_count,
                'odds': odds_count,
                'leagues_configured': len(league_ids),
                'missing_leagues': missing_leagues,
                'missing_league_names': missing_league_names,
            }
        
        def _on_result(data):
            """Callback cuando termina la verificacion"""
            outdated_count = data['outdated']
            odds_count = data['odds']
            leagues = data['leagues_configured']
            missing_leagues = data['missing_leagues']
            missing_league_names = data['missing_league_names']
            
            self._log(f"📋 Ligas configuradas: {leagues}", "info")
            
            if missing_leagues:
                self._log(f"⚠️ {len(missing_leagues)} ligas sin datos en BD: {', '.join(missing_league_names)}", "warning")
            
            has_issues = outdated_count > 0 or odds_count > 0 or len(missing_leagues) > 0
            
            if has_issues:
                msg = "Se detectaron datos pendientes de actualizacion:\n\n"
                
                if missing_leagues:
                    msg += f"🆕 {len(missing_leagues)} ligas configuradas SIN DATOS en la BD:\n"
                    for name in missing_league_names:
                        msg += f"   • {name}\n"
                    msg += "\n"
                
                if outdated_count > 0:
                    msg += f"⚠️ {outdated_count} partidos sin resultados actualizados\n"
                if odds_count > 0:
                    msg += f"💰 {odds_count} partidos proximos (72h) sin odds\n"
                
                msg += "\n¿Desea abrir el panel de sincronizacion?"
                
                self._log(f"⚠️ Pendientes: {outdated_count} resultados, {odds_count} odds, {len(missing_leagues)} ligas sin datos", "warning")
                
                reply = QMessageBox.question(
                    self,
                    "⚠️ Datos Pendientes Detectados",
                    msg,
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    self._show_sync_dialog()
            else:
                self._log("✅ Todos los datos estan actualizados", "success")
        
        def _on_error(error_msg):
            """Callback para errores"""
            self._log(f"Error en verificacion inicial: {error_msg}", "error")
        
        # Ejecutar en hilo de fondo
        self._check_thread = _DBQueryThread(_query, self)
        self._check_thread.result_ready.connect(_on_result)
        self._check_thread.error_occurred.connect(_on_error)
        self._check_thread.start()

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    window = ExtractionWindow()
    window.show()
    sys.exit(app.exec())