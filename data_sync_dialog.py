# data_sync_dialog.py
"""
Diálogo de Sincronización de Datos
Verifica y permite actualizar:
- Partidos desactualizados (terminados sin resultados)
- Odds faltantes (próximos 3 días)
- Ligas sin datos históricos (desde 2020)
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QTextEdit, QCheckBox, QMessageBox, QFrame,
    QScrollArea, QWidget, QSizePolicy, QSplitter, QTabWidget
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont
from config.season_mapping import get_current_season, group_leagues_by_season

# ============================================================================
# CONFIGURACIÓN DE LIGAS PARA AUTO-EXTRACCIÓN (ACTUALIZADO)
# ============================================================================

LIGAS_CONFIG = {
    'SUDAMERICA': {
        128: 'Argentina - Liga Profesional',
        129: 'Argentina - Primera Nacional',
        71:  'Brasil - Serie A',
        72:  'Brasil - Serie B',
        239: 'Colombia - Primera A',
        240: 'Colombia - Primera B',
        265: 'Chile - Primera División',
        266: 'Chile - Primera B',
        281: 'Perú - Primera División',
        282: 'Perú - Segunda División',
        268: 'Uruguay - Primera División (Apertura)',
        270: 'Uruguay - Primera División (Clausura)',
        269: 'Uruguay - Segunda División',
        242: 'Ecuador - Liga Pro',
        243: 'Ecuador - Liga Pro Serie B',
        250: 'Paraguay - División Profesional (Apertura)',
        252: 'Paraguay - División Profesional (Clausura)',
        251: 'Paraguay - División Intermedia',
        299: 'Venezuela - Primera División',
        300: 'Venezuela - Segunda División',
    },
    'COPAS_SUDAMERICA': {
        # Argentina
        130:  'Copa Argentina',
        517:  'Argentina - Trofeo de Campeones',
        # Brasil
        73:   'Brasil - Copa Do Brasil',
        632:  'Brasil - Supercopa do Brasil',
        # Colombia
        241:  'Copa Colombia',
        713:  'Colombia - Superliga',
        # Chile
        267:  'Chile - Copa Chile',
        527:  'Chile - Super Cup',
        # Perú
        502:  'Perú - Copa Bicentenario',
        # Uruguay
        930:  'Uruguay - Copa Uruguay',
        842:  'Uruguay - Super Copa',
        # Ecuador
        917:  'Ecuador - Copa Ecuador',
        853:  'Ecuador - Supercopa',
        # Paraguay
        501:  'Paraguay - Copa Paraguay',
        961:  'Paraguay - Supercopa',
        # Venezuela
        1113: 'Venezuela - Copa Venezuela',
    },
    'MEXICO': {
        262: 'México - Liga MX',
        263: 'México - Liga de Expansión',
        264: 'México - Copa MX',
    },
    'COPAS_CONMEBOL': {
        13: 'CONMEBOL Libertadores',
        11: 'CONMEBOL Sudamericana',
    },
    'COPAS_UEFA': {
        2:   'UEFA Champions League',
        3:   'UEFA Europa League',
        848: 'UEFA Conference League',
    },
    'EUROPA_TOP': {
        39:  'Inglaterra - Premier League',
        40:  'Inglaterra - Championship',
        140: 'España - La Liga',
        141: 'España - Segunda División',
        135: 'Italia - Serie A',
        136: 'Italia - Serie B',
        78:  'Alemania - Bundesliga',
        79:  'Alemania - 2. Bundesliga',
        61:  'Francia - Ligue 1',
        62:  'Francia - Ligue 2',
    },
    'COPAS_NACIONALES_EUROPA': {
        # Inglaterra
        45:  'Inglaterra - FA Cup',
        48:  'Inglaterra - EFL Cup',
        528: 'Inglaterra - Community Shield',
        # España
        143: 'España - Copa del Rey',
        556: 'España - SuperCopa',
        # Italia
        137: 'Italia - Coppa Italia',
        547: 'Italia - Super Cup',
        # Alemania
        81:  'Alemania - DFB Pokal',
        529: 'Alemania - Super Cup',
        # Francia
        66:  'Francia - Coupe de France',
        526: 'Francia - Trophée des Champions',
        # Portugal
        96:  'Portugal - Taça de Portugal',
        97:  'Portugal - Taça da Liga',
        550: 'Portugal - Super Cup',
        # Países Bajos
        90:  'Países Bajos - KNVB Beker',
        543: 'Países Bajos - Super Cup',
        # Bélgica
        147: 'Bélgica - Cup',
        # Grecia
        199: 'Grecia - Cup',
    },
    'EUROPA_OTROS': {
        # Portugal
        94:  'Portugal - Primeira Liga',
        95:  'Portugal - Segunda Liga',
        # Bélgica
        144: 'Bélgica - Pro League',
        145: 'Bélgica - Challenger Pro League',
        # Grecia
        197: 'Grecia - Super League',
        198: 'Grecia - Football League',
        # Países Bajos
        88:  'Países Bajos - Eredivisie',
        89:  'Países Bajos - Eerste Divisie',
    },
}

# Año mínimo para verificar datos históricos
MIN_YEAR_DATA = 2020


def get_all_configured_league_ids() -> List[int]:
    """Obtiene todos los IDs de ligas configuradas"""
    ids = []
    for region_leagues in LIGAS_CONFIG.values():
        ids.extend(region_leagues.keys())
    return ids


def get_league_name_by_id(league_id: int) -> str:
    """Obtiene el nombre de la liga por su ID"""
    for region_leagues in LIGAS_CONFIG.values():
        if league_id in region_leagues:
            return region_leagues[league_id]
    return f"Liga {league_id}"


def get_league_region_by_id(league_id: int) -> str:
    """Obtiene la región de la liga por su ID"""
    for region, leagues in LIGAS_CONFIG.items():
        if league_id in leagues:
            return region
    return "OTROS"


# ============================================================================
# WORKER PARA VERIFICACIÓN DE DATOS
# ============================================================================

class DataCheckWorker(QThread):
    """Worker para verificar datos pendientes sin bloquear la UI"""
    progress = Signal(str)
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, check_type: str = 'all'):
        super().__init__()
        self.check_type = check_type
    
    def run(self):
        try:
            results = {}
            
            if self.check_type in ('all', 'outdated'):
                self.progress.emit("Verificando partidos desactualizados...")
                results['outdated'] = self._check_outdated_fixtures()
            
            if self.check_type in ('all', 'odds'):
                self.progress.emit("Verificando odds faltantes...")
                results['missing_odds'] = self._check_missing_odds()
            
            if self.check_type in ('all', 'coverage'):
                self.progress.emit("Verificando cobertura de ligas...")
                results['league_coverage'] = self._check_league_coverage()
            
            self.finished.emit(results)
            
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
    
    def _check_outdated_fixtures(self) -> List[Dict]:
        """
        Busca partidos que ya deberían haber terminado pero no tienen resultados.
        """
        try:
            from data.database_manager import ORIG_ENGINE
            from sqlalchemy import text
            
            lima_tz = timezone(timedelta(hours=-5))
            now_lima = datetime.now(lima_tz)
            week_ago = now_lima - timedelta(days=7)
            
            league_ids = get_all_configured_league_ids()
            league_placeholders = ','.join([str(lid) for lid in league_ids])
            
            # Normalizar fechas a formato con espacio (SQLite compara strings,
            # 'T' > ' ' en ASCII causa que fixtures del mismo día fallen)
            now_utc_str = now_lima.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            week_ago_str = week_ago.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            
            query = text(f"""
                SELECT 
                    f.id,
                    f.date,
                    f.league_id,
                    f.status_short,
                    f.goals_home,
                    f.goals_away,
                    ht.name as home_name,
                    at.name as away_name
                FROM fixtures f
                LEFT JOIN teams ht ON f.home_team_id = ht.id
                LEFT JOIN teams at ON f.away_team_id = at.id
                WHERE f.league_id IN ({league_placeholders})
                  AND REPLACE(f.date, 'T', ' ') < :now_utc
                  AND REPLACE(f.date, 'T', ' ') > :week_ago
                  AND (
                      f.status_short IS NULL
                      OR f.status_short NOT IN ('FT', 'AET', 'PEN')
                      OR f.goals_home IS NULL 
                      OR f.goals_away IS NULL
                  )
                ORDER BY f.date DESC
            """)
            
            with ORIG_ENGINE.connect() as conn:
                result = conn.execute(query, {
                    'now_utc': now_utc_str,
                    'week_ago': week_ago_str
                })
                rows = result.fetchall()
            
            outdated = []
            for row in rows:
                outdated.append({
                    'id': row[0],
                    'date': row[1],
                    'league_id': row[2],
                    'status': row[3],
                    'goals_home': row[4],
                    'goals_away': row[5],
                    'home_name': row[6] or 'N/A',
                    'away_name': row[7] or 'N/A',
                    'league_name': get_league_name_by_id(row[2]),
                    'region': get_league_region_by_id(row[2])
                })
            
            return outdated
            
        except Exception as e:
            print(f"Error verificando partidos desactualizados: {e}")
            return []
    
    def _check_missing_odds(self) -> List[Dict]:
        """
        Busca partidos en las próximas 72 horas que no tienen odds.
        """
        try:
            from data.database_manager import ORIG_ENGINE
            from sqlalchemy import text
            
            lima_tz = timezone(timedelta(hours=-5))
            now_lima = datetime.now(lima_tz)
            three_days_later = now_lima + timedelta(days=3)
            
            league_ids = get_all_configured_league_ids()
            if not league_ids:
                return []
                
            league_placeholders = ','.join([str(lid) for lid in league_ids])
            
            now_utc_str = now_lima.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            future_utc_str = three_days_later.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            
            query = text(f"""
                SELECT 
                    f.id,
                    f.date,
                    f.league_id,
                    f.status_short,
                    ht.name as home_name,
                    at.name as away_name
                FROM fixtures f
                LEFT JOIN teams ht ON f.home_team_id = ht.id
                LEFT JOIN teams at ON f.away_team_id = at.id
                WHERE f.league_id IN ({league_placeholders})
                  AND REPLACE(f.date, 'T', ' ') > :now_utc
                  AND REPLACE(f.date, 'T', ' ') < :future_utc
                  AND f.status_short = 'NS'
                  AND NOT EXISTS (SELECT 1 FROM odds o WHERE o.fixture_id = f.id)
                ORDER BY f.date ASC
            """)
            
            with ORIG_ENGINE.connect() as conn:
                result = conn.execute(query, {
                    'now_utc': now_utc_str,
                    'future_utc': future_utc_str
                })
                rows = result.fetchall()
            
            missing = []
            for row in rows:
                fixture_date = row[1]
                hours_remaining = 0
                
                try:
                    if fixture_date:
                        if isinstance(fixture_date, str):
                            try:
                                fixture_date = datetime.fromisoformat(fixture_date.replace('Z', '+00:00'))
                            except:
                                fixture_date = datetime.strptime(fixture_date[:19], '%Y-%m-%d %H:%M:%S')
                                fixture_date = fixture_date.replace(tzinfo=timezone.utc)
                        
                        if fixture_date.tzinfo is None:
                            fixture_date = fixture_date.replace(tzinfo=timezone.utc)
                        
                        now_utc = now_lima.astimezone(timezone.utc)
                        time_to_match = fixture_date - now_utc
                        hours_remaining = time_to_match.total_seconds() / 3600
                except Exception as e:
                    hours_remaining = 0
                
                missing.append({
                    'id': row[0],
                    'date': row[1],
                    'league_id': row[2],
                    'status': row[3],
                    'home_name': row[4] or 'N/A',
                    'away_name': row[5] or 'N/A',
                    'league_name': get_league_name_by_id(row[2]),
                    'region': get_league_region_by_id(row[2]),
                    'hours_remaining': round(hours_remaining, 1)
                })
            
            return missing
            
        except Exception as e:
            import traceback
            print(f"Error verificando odds faltantes: {e}")
            traceback.print_exc()
            return []
    
    def _check_league_coverage(self) -> List[Dict]:
        """
        Verifica qué ligas configuradas tienen datos y cuáles no.
        Detecta ligas sin datos históricos desde MIN_YEAR_DATA.
        """
        try:
            from data.database_manager import ORIG_ENGINE
            from sqlalchemy import text
            
            league_ids = get_all_configured_league_ids()
            coverage = []
            
            # ✅ Un solo query para todas las ligas en vez de N queries
            league_placeholders = ','.join([str(lid) for lid in league_ids])
            
            query = text(f"""
                SELECT 
                    league_id,
                    COUNT(*) as total,
                    MIN(REPLACE(date, 'T', ' ')) as first_date,
                    MAX(REPLACE(date, 'T', ' ')) as last_date,
                    SUM(CASE WHEN status_short IN ('FT', 'AET', 'PEN') THEN 1 ELSE 0 END) as finished,
                    COUNT(DISTINCT league_season) as seasons
                FROM fixtures 
                WHERE league_id IN ({league_placeholders})
                GROUP BY league_id
            """)
            
            # Ejecutar un solo query
            db_data = {}
            with ORIG_ENGINE.connect() as conn:
                result = conn.execute(query)
                for row in result.fetchall():
                    db_data[row[0]] = {
                        'total': row[1],
                        'first_date': row[2],
                        'last_date': row[3],
                        'finished': row[4],
                        'seasons': row[5],
                    }
            
            for lid in league_ids:
                data = db_data.get(lid, {})
                total = data.get('total', 0)
                first_date = data.get('first_date')
                last_date = data.get('last_date')
                finished = data.get('finished', 0)
                seasons = data.get('seasons', 0)
                
                # Determinar si tiene datos suficientes
                has_data = total > 0
                has_historical = False
                first_year = None
                
                if first_date:
                    try:
                        if isinstance(first_date, str):
                            first_year = int(first_date[:4])
                        else:
                            first_year = first_date.year
                        has_historical = first_year <= MIN_YEAR_DATA
                    except:
                        pass
                
                # Calcular estado
                if not has_data:
                    status = 'NO_DATA'
                    status_text = '❌ Sin datos'
                elif not has_historical:
                    status = 'INCOMPLETE'
                    status_text = f'⚠️ Solo desde {first_year}'
                else:
                    status = 'OK'
                    status_text = f'✅ Desde {first_year}'
                
                coverage.append({
                    'league_id': lid,
                    'league_name': get_league_name_by_id(lid),
                    'region': get_league_region_by_id(lid),
                    'total_fixtures': total,
                    'finished_fixtures': finished,
                    'seasons': seasons,
                    'first_date': first_date,
                    'last_date': last_date,
                    'first_year': first_year,
                    'status': status,
                    'status_text': status_text,
                    'has_data': has_data,
                    'has_historical': has_historical,
                })
            
            # Ordenar: primero sin datos, luego incompletos, luego OK
            status_order = {'NO_DATA': 0, 'INCOMPLETE': 1, 'OK': 2}
            coverage.sort(key=lambda x: (status_order.get(x['status'], 3), x['league_name']))
            
            return coverage
            
        except Exception as e:
            import traceback
            print(f"Error verificando cobertura de ligas: {e}")
            traceback.print_exc()
            return []


# ============================================================================
# WORKER PARA ACTUALIZACIÓN DE DATOS
# ============================================================================

class DataSyncWorker(QThread):
    """Worker para sincronizar datos desde la API"""
    progress = Signal(int, str)
    log = Signal(str, str)
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, sync_type: str, fixture_ids: List[int] = None, league_ids: List[int] = None, seasons: List[int] = None):
        super().__init__()
        self.sync_type = sync_type
        self.fixture_ids = fixture_ids or []
        self.league_ids = league_ids or []
        self.seasons = seasons or []
        self._stop = False
    
    def stop(self):
        self._stop = True
    
    def run(self):
        try:
            if self.sync_type == 'results':
                self._sync_results()
            elif self.sync_type == 'odds':
                self._sync_odds()
            elif self.sync_type == 'historical':
                self._sync_historical()
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
    
    # =========================================================================
    # FIX: _sync_results ahora hace merge de TODOS los fixtures de la API
    # =========================================================================
    
    def _sync_results(self):
        """
        Actualiza resultados de partidos desactualizados - AGRUPADO POR LIGA.
        Además hace merge de TODOS los fixtures devueltos por la API (no solo los
        outdated), para que fixtures nuevos o programados también se guarden/actualicen
        sin consumir llamadas extra.
        """
        try:
            from data.api_fetcher import APIFetcher
            from data.api_database_manager import save_fixtures
            from data.database_manager import ORIG_ENGINE
            from ui.extraction_window import process_fixtures
            from sqlalchemy import text
            from datetime import datetime, timedelta
            from collections import defaultdict
            
            self.log.emit("Obteniendo información de fixtures de la BD...", "info")
            
            fixture_ids_str = ','.join([str(fid) for fid in self.fixture_ids])
            
            query = text(f"""
                SELECT id, league_id, league_season, date 
                FROM fixtures 
                WHERE id IN ({fixture_ids_str})
            """)
            
            fixtures_info = {}
            leagues_fixtures = defaultdict(list)
            
            with ORIG_ENGINE.connect() as conn:
                result = conn.execute(query)
                for row in result.fetchall():
                    fid, league_id, season, date = row
                    fixtures_info[fid] = {
                        'league_id': league_id,
                        'season': season or 2024,
                        'date': date
                    }
                    leagues_fixtures[(league_id, season or 2024)].append(fid)
            
            fetcher = APIFetcher()
            total_leagues = len(leagues_fixtures)
            updated = 0
            merged_total = 0
            errors = 0
            
            self.log.emit(f"Procesando {len(self.fixture_ids)} fixtures en {total_leagues} ligas", "info")
            
            for i, ((league_id, season), fixture_ids_in_league) in enumerate(leagues_fixtures.items()):
                if self._stop:
                    break
                
                pct = int((i / total_leagues) * 90)
                league_name = get_league_name_by_id(league_id)
                self.progress.emit(pct, f"Liga {league_name} ({i+1}/{total_leagues})")
                self.log.emit(f"Obteniendo fixtures de {league_name} (temporada {season})...", "info")
                
                try:
                    # -------------------------------------------------------
                    # Llamar API SIN filtro de fechas → trae TODA la temporada
                    # Misma cantidad de llamadas API (1 por liga), pero cubre
                    # fixtures programados que aún no estaban en la BD
                    # -------------------------------------------------------
                    raw_fixtures = fetcher.get_fixtures(
                        league_ids=[league_id],
                        season=season
                    )
                    
                    if raw_fixtures:
                        api_fixtures = {f['fixture']['id']: f for f in raw_fixtures}
                        
                        # --- 1) Reportar actualizaciones de los outdated ---
                        for fid in fixture_ids_in_league:
                            if fid in api_fixtures:
                                fixture_data = api_fixtures[fid]
                                goals = fixture_data.get('goals', {})
                                status = fixture_data.get('fixture', {}).get('status', {})
                                updated += 1
                                self.log.emit(
                                    f"  {fid}: {goals.get('home', '-')}-{goals.get('away', '-')} ({status.get('short', '?')})", 
                                    "success"
                                )
                            else:
                                self.log.emit(f"  {fid}: No encontrado en respuesta API", "warning")
                        
                        # --- 2) Merge TODOS los fixtures de la API (INSERT OR UPDATE) ---
                        fixtures_data = process_fixtures(raw_fixtures)
                        saved = save_fixtures(fixtures_data)
                        merged_total += saved
                        
                        self.log.emit(
                            f"  ✓ {league_name}: {saved} fixtures sincronizados (temporada completa)", 
                            "success"
                        )
                    else:
                        self.log.emit(f"  ✗ {league_name}: Sin datos de API", "warning")
                        
                except Exception as e:
                    self.log.emit(f"  ✗ {league_name}: Error - {str(e)}", "error")
                    errors += len(fixture_ids_in_league)
            
            not_updated = len(self.fixture_ids) - updated
            self.progress.emit(100, "Completado")
            self.log.emit(
                f"Resumen: {updated} resultados actualizados, {merged_total} fixtures totales sincronizados, "
                f"{not_updated} sin cambios, {errors} errores", 
                "success" if errors == 0 else "warning"
            )
            
            self.finished.emit({
                'type': 'results',
                'updated': updated,
                'merged': merged_total,
                'errors': errors,
                'total': len(self.fixture_ids),
                'api_calls': total_leagues
            })
            
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
    
    def _sync_odds(self):
        """Descarga odds para fixtures seleccionados"""
        try:
            from data.api_fetcher import APIFetcher
            from data.api_database_manager import save_odds
            
            fetcher = APIFetcher()
            total = len(self.fixture_ids)
            saved = 0
            errors = 0
            
            for i, fid in enumerate(self.fixture_ids):
                if self._stop:
                    break
                
                pct = int((i / total) * 100)
                self.progress.emit(pct, f"Descargando odds {fid} ({i+1}/{total})")
                
                try:
                    raw_odds = fetcher.get_odds_with_fallback(fid)
                    
                    if raw_odds:
                        odds_list = self._process_odds(raw_odds, fid)
                        if odds_list:
                            save_odds(odds_list)
                            self.log.emit(f"Fixture {fid}: {len(odds_list)} cuotas guardadas", "success")
                            saved += 1
                        else:
                            self.log.emit(f"Fixture {fid}: Sin cuotas procesables", "warning")
                    else:
                        self.log.emit(f"Fixture {fid}: Sin odds disponibles en API", "warning")
                        
                except Exception as e:
                    self.log.emit(f"Fixture {fid}: Error - {str(e)}", "error")
                    errors += 1
            
            self.progress.emit(100, "Completado")
            self.finished.emit({
                'type': 'odds',
                'saved': saved,
                'errors': errors,
                'total': total
            })
            
        except Exception as e:
            self.error.emit(str(e))
    
    def _sync_historical(self):
        """Descarga datos históricos para ligas faltantes"""
        try:
            from data.api_fetcher import APIFetcher
            from data.api_database_manager import save_fixtures
            from ui.extraction_window import process_fixtures
            
            fetcher = APIFetcher()
            total_ops = len(self.league_ids) * len(self.seasons)
            current = 0
            total_fixtures = 0
            errors = 0
            
            self.log.emit(f"Descargando datos históricos: {len(self.league_ids)} ligas × {len(self.seasons)} temporadas", "info")
            
            for league_id in self.league_ids:
                if self._stop:
                    break
                    
                league_name = get_league_name_by_id(league_id)
                
                for season in self.seasons:
                    if self._stop:
                        break
                    
                    current += 1
                    pct = int((current / total_ops) * 100)
                    self.progress.emit(pct, f"{league_name} - {season} ({current}/{total_ops})")
                    
                    try:
                        raw_fixtures = fetcher.get_fixtures(
                            league_ids=[league_id],
                            season=season
                        )
                        
                        if raw_fixtures:
                            fixtures_data = process_fixtures(raw_fixtures)
                            save_fixtures(fixtures_data)
                            total_fixtures += len(fixtures_data)
                            self.log.emit(f"✓ {league_name} {season}: {len(fixtures_data)} fixtures", "success")
                        else:
                            self.log.emit(f"⚠ {league_name} {season}: Sin datos", "warning")
                            
                    except Exception as e:
                        self.log.emit(f"✗ {league_name} {season}: Error - {str(e)}", "error")
                        errors += 1
            
            self.progress.emit(100, "Completado")
            self.finished.emit({
                'type': 'historical',
                'fixtures': total_fixtures,
                'errors': errors,
                'api_calls': current
            })
            
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
    
    def _process_odds(self, raw_odds: List[Dict], fixture_id: int) -> List:
        """Procesa odds crudos de la API"""
        try:
            from data.data_models.odds import Odd
        except ImportError:
            return []
        
        odds_list = []
        
        for item in raw_odds:
            bookmakers = item.get('bookmakers', [])
            
            for bookie in bookmakers:
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
                        except:
                            continue
        
        return odds_list


# ============================================================================
# DIÁLOGO PRINCIPAL
# ============================================================================

class DataSyncDialog(QDialog):
    """Diálogo para verificar y sincronizar datos pendientes"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Verificación de Datos Pendientes")
        self.resize(1200, 850)
        self.setModal(True)
        
        self.outdated_fixtures = []
        self.missing_odds = []
        self.league_coverage = []
        self.check_worker = None
        self.sync_worker = None
        
        self._build_ui()
        
        # Iniciar verificación automáticamente
        QTimer.singleShot(100, self._start_check)
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Header
        header = QLabel("🔄 Verificando datos pendientes de actualización...")
        header.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #2d3436;
            padding: 10px;
            background: #dfe6e9;
            border-radius: 8px;
        """)
        header.setAlignment(Qt.AlignCenter)
        self.header_label = header
        layout.addWidget(header)
        
        # Info de zona horaria y configuración
        info_row = QHBoxLayout()
        tz_info = QLabel("⏰ Zona horaria: Lima (UTC-5)")
        tz_info.setStyleSheet("color: #636e72; font-size: 11px;")
        info_row.addWidget(tz_info)
        
        leagues_info = QLabel(f"📋 Ligas configuradas: {len(get_all_configured_league_ids())}")
        leagues_info.setStyleSheet("color: #636e72; font-size: 11px;")
        info_row.addWidget(leagues_info)
        
        info_row.addStretch()
        layout.addLayout(info_row)
        
        # === TABS para organizar mejor ===
        self.main_tabs = QTabWidget()
        
        # Tab 1: Partidos Pendientes
        tab_fixtures = QWidget()
        tab_fixtures_layout = QVBoxLayout(tab_fixtures)
        
        # Splitter para las dos tablas
        self.tables_splitter = QSplitter(Qt.Vertical)
        self.tables_splitter.setHandleWidth(6)
        
        # Sección: Partidos Desactualizados
        self.outdated_group = self._build_outdated_section()
        self.tables_splitter.addWidget(self.outdated_group)
        
        # Sección: Odds Faltantes
        self.odds_group = self._build_odds_section()
        self.tables_splitter.addWidget(self.odds_group)
        
        self.tables_splitter.setSizes([350, 350])
        tab_fixtures_layout.addWidget(self.tables_splitter)
        
        self.main_tabs.addTab(tab_fixtures, "⚠️ Datos Pendientes")
        
        # Tab 2: Cobertura de Ligas
        tab_coverage = QWidget()
        tab_coverage_layout = QVBoxLayout(tab_coverage)
        self.coverage_group = self._build_coverage_section()
        tab_coverage_layout.addWidget(self.coverage_group)
        self.main_tabs.addTab(tab_coverage, "📊 Cobertura de Ligas")
        
        layout.addWidget(self.main_tabs, 1)
        
        # === Progress Bar ===
        progress_frame = QFrame()
        progress_frame.setStyleSheet("background: white; border-radius: 8px; padding: 8px;")
        progress_layout = QVBoxLayout(progress_frame)
        progress_layout.setContentsMargins(10, 5, 10, 5)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("Iniciando verificación...")
        self.progress_label.setStyleSheet("color: #636e72;")
        progress_layout.addWidget(self.progress_label)
        
        layout.addWidget(progress_frame)
        
        # === Log ===
        log_group = QGroupBox("📝 Log de Operaciones")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        self.log_text.setStyleSheet("""
            background-color: #2d3436;
            color: #dfe6e9;
            font-family: 'Consolas', monospace;
            font-size: 11px;
            border-radius: 6px;
        """)
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_group)
        
        # === Botones ===
        btn_layout = QHBoxLayout()
        
        self.chk_only_issues = QCheckBox("Solo ligas con issues")
        self.chk_only_issues.setToolTip(
            "Si esta marcado: actualiza solo las ligas sin datos o incompletas.\n"
            "Si esta desmarcado: actualiza las 80 ligas configuradas."
        )
        self.chk_only_issues.setStyleSheet("color: #2d3436; padding: 5px;")
        btn_layout.addWidget(self.chk_only_issues)
        
        self.btn_refresh_season = QPushButton("🔄 Actualizar temporada en curso")
        self.btn_refresh_season.clicked.connect(self._refresh_current_season)
        self.btn_refresh_season.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5b4cdb; }
        """)
        btn_layout.addWidget(self.btn_refresh_season)
        self.btn_refresh = QPushButton("🔄 Verificar de Nuevo")
        self.btn_refresh.clicked.connect(self._start_check)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #74b9ff;
                color: white;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0984e3; }
        """)
        btn_layout.addWidget(self.btn_refresh)
        
        btn_layout.addStretch()
        
        self.btn_sync_all = QPushButton("⚡ Sincronizar Todo")
        self.btn_sync_all.clicked.connect(self._sync_all)
        self.btn_sync_all.setStyleSheet("""
            QPushButton {
                background-color: #00b894;
                color: white;
                padding: 10px 25px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #00a381; }
        """)
        self.btn_sync_all.setEnabled(False)
        btn_layout.addWidget(self.btn_sync_all)
        
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #636e72;
                color: white;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #4a5459; }
        """)
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)
    
    def _build_outdated_section(self) -> QGroupBox:
        """Construye la sección de partidos desactualizados"""
        group = QGroupBox("⚠️ Partidos Desactualizados (sin resultados)")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                border: 2px solid #fdcb6e;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title { color: #fdcb6e; }
        """)
        layout = QVBoxLayout(group)
        
        self.outdated_info = QLabel("Verificando...")
        self.outdated_info.setStyleSheet("color: #636e72; padding: 5px;")
        layout.addWidget(self.outdated_info)
        
        self.outdated_table = QTableWidget()
        self.outdated_table.setColumnCount(7)
        self.outdated_table.setHorizontalHeaderLabels([
            '✓', 'ID', 'Fecha', 'Región', 'Liga', 'Partido', 'Estado'
        ])
        self.outdated_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.outdated_table.setColumnWidth(0, 30)
        self.outdated_table.setColumnWidth(1, 80)
        self.outdated_table.setColumnWidth(2, 130)
        self.outdated_table.setColumnWidth(3, 100)
        self.outdated_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.outdated_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.outdated_table.setColumnWidth(6, 60)
        self.outdated_table.setAlternatingRowColors(True)
        self.outdated_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.outdated_table, 1)
        
        btn_row = QHBoxLayout()
        
        btn_select_all = QPushButton("Seleccionar Todo")
        btn_select_all.clicked.connect(lambda: self._select_all_table(self.outdated_table, True))
        btn_row.addWidget(btn_select_all)
        
        btn_deselect = QPushButton("Deseleccionar")
        btn_deselect.clicked.connect(lambda: self._select_all_table(self.outdated_table, False))
        btn_row.addWidget(btn_deselect)
        
        btn_row.addStretch()
        
        self.btn_sync_results = QPushButton("📥 Actualizar Resultados Seleccionados")
        self.btn_sync_results.clicked.connect(self._sync_results)
        self.btn_sync_results.setStyleSheet("""
            QPushButton {
                background-color: #fdcb6e;
                color: #2d3436;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #f9b42a; }
        """)
        self.btn_sync_results.setEnabled(False)
        btn_row.addWidget(self.btn_sync_results)
        
        layout.addLayout(btn_row)
        
        return group
    
    def _build_odds_section(self) -> QGroupBox:
        """Construye la sección de odds faltantes"""
        group = QGroupBox("🎯 Partidos Próximos Sin Odds (hasta 72h)")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                border: 2px solid #74b9ff;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title { color: #0984e3; }
        """)
        layout = QVBoxLayout(group)
        
        self.odds_info = QLabel("Verificando...")
        self.odds_info.setStyleSheet("color: #636e72; padding: 5px;")
        layout.addWidget(self.odds_info)
        
        self.odds_table = QTableWidget()
        self.odds_table.setColumnCount(7)
        self.odds_table.setHorizontalHeaderLabels([
            '✓', 'ID', 'Fecha', 'Región', 'Liga', 'Partido', 'Faltan (h)'
        ])
        self.odds_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.odds_table.setColumnWidth(0, 30)
        self.odds_table.setColumnWidth(1, 80)
        self.odds_table.setColumnWidth(2, 130)
        self.odds_table.setColumnWidth(3, 100)
        self.odds_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.odds_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.odds_table.setColumnWidth(6, 70)
        self.odds_table.setAlternatingRowColors(True)
        self.odds_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.odds_table, 1)
        
        btn_row = QHBoxLayout()
        
        btn_select_all = QPushButton("Seleccionar Todo")
        btn_select_all.clicked.connect(lambda: self._select_all_table(self.odds_table, True))
        btn_row.addWidget(btn_select_all)
        
        btn_deselect = QPushButton("Deseleccionar")
        btn_deselect.clicked.connect(lambda: self._select_all_table(self.odds_table, False))
        btn_row.addWidget(btn_deselect)
        
        btn_row.addStretch()
        
        self.btn_sync_odds = QPushButton("📥 Descargar Odds Seleccionados")
        self.btn_sync_odds.clicked.connect(self._sync_odds)
        self.btn_sync_odds.setStyleSheet("""
            QPushButton {
                background-color: #74b9ff;
                color: white;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0984e3; }
        """)
        self.btn_sync_odds.setEnabled(False)
        btn_row.addWidget(self.btn_sync_odds)
        
        layout.addLayout(btn_row)
        
        return group
    
    def _build_coverage_section(self) -> QGroupBox:
        """Construye la sección de cobertura de ligas"""
        group = QGroupBox(f"📊 Cobertura de Datos por Liga (desde {MIN_YEAR_DATA})")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 13px;
                font-weight: bold;
                border: 2px solid #6c5ce7;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title { color: #6c5ce7; }
        """)
        layout = QVBoxLayout(group)
        
        self.coverage_info = QLabel("Verificando cobertura de ligas configuradas...")
        self.coverage_info.setStyleSheet("color: #636e72; padding: 5px;")
        layout.addWidget(self.coverage_info)
        
        self.coverage_table = QTableWidget()
        self.coverage_table.setColumnCount(8)
        self.coverage_table.setHorizontalHeaderLabels([
            '✓', 'ID', 'Región', 'Liga', 'Fixtures', 'Temporadas', 'Desde', 'Estado'
        ])
        self.coverage_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.coverage_table.setColumnWidth(0, 30)
        self.coverage_table.setColumnWidth(1, 50)
        self.coverage_table.setColumnWidth(2, 120)
        self.coverage_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.coverage_table.setColumnWidth(4, 70)
        self.coverage_table.setColumnWidth(5, 80)
        self.coverage_table.setColumnWidth(6, 70)
        self.coverage_table.setColumnWidth(7, 120)
        self.coverage_table.setAlternatingRowColors(True)
        self.coverage_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.coverage_table, 1)
        
        btn_row = QHBoxLayout()
        
        btn_select_missing = QPushButton("Seleccionar Sin Datos")
        btn_select_missing.clicked.connect(self._select_missing_coverage)
        btn_select_missing.setStyleSheet("background-color: #e17055; color: white;")
        btn_row.addWidget(btn_select_missing)
        
        btn_select_incomplete = QPushButton("Seleccionar Incompletos")
        btn_select_incomplete.clicked.connect(self._select_incomplete_coverage)
        btn_select_incomplete.setStyleSheet("background-color: #fdcb6e; color: #2d3436;")
        btn_row.addWidget(btn_select_incomplete)
        
        btn_row.addStretch()
        
        self.btn_download_historical = QPushButton("📥 Descargar Datos Históricos")
        self.btn_download_historical.clicked.connect(self._download_historical)
        self.btn_download_historical.setStyleSheet("""
            QPushButton {
                background-color: #6c5ce7;
                color: white;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5b4cdb; }
        """)
        self.btn_download_historical.setEnabled(False)
        btn_row.addWidget(self.btn_download_historical)
        
        layout.addLayout(btn_row)
        
        return group
    
    def _start_check(self):
        """Inicia la verificación de datos"""
        if self.check_worker and self.check_worker.isRunning():
            return
        
        self.progress_bar.setValue(0)
        self.progress_label.setText("Verificando datos pendientes...")
        self.header_label.setText("🔄 Verificando datos pendientes de actualización...")
        self.header_label.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #2d3436;
            padding: 10px;
            background: #dfe6e9;
            border-radius: 8px;
        """)
        
        self.btn_sync_all.setEnabled(False)
        self.btn_sync_results.setEnabled(False)
        self.btn_sync_odds.setEnabled(False)
        self.btn_download_historical.setEnabled(False)
        
        self.check_worker = DataCheckWorker('all')
        self.check_worker.progress.connect(self._on_check_progress)
        self.check_worker.finished.connect(self._on_check_finished)
        self.check_worker.error.connect(self._on_check_error)
        self.check_worker.start()
    
    def _on_check_progress(self, msg):
        self.progress_label.setText(msg)
    
    def _on_check_finished(self, results):
        self.outdated_fixtures = results.get('outdated', [])
        self.missing_odds = results.get('missing_odds', [])
        self.league_coverage = results.get('league_coverage', [])
        
        self._log(f"Encontrados: {len(self.outdated_fixtures)} desactualizados, {len(self.missing_odds)} sin odds", "info")
        
        # Actualizar tablas
        self._populate_outdated_table()
        self._populate_odds_table()
        self._populate_coverage_table()
        
        # Contar problemas de cobertura
        no_data = len([c for c in self.league_coverage if c['status'] == 'NO_DATA'])
        incomplete = len([c for c in self.league_coverage if c['status'] == 'INCOMPLETE'])
        
        # Actualizar header
        total_pending = len(self.outdated_fixtures) + len(self.missing_odds)
        
        if total_pending > 0 or no_data > 0:
            msg_parts = []
            if total_pending > 0:
                msg_parts.append(f"{total_pending} datos pendientes")
            if no_data > 0:
                msg_parts.append(f"{no_data} ligas sin datos")
            if incomplete > 0:
                msg_parts.append(f"{incomplete} ligas incompletas")
            
            self.header_label.setText(f"⚠️ {' | '.join(msg_parts)}")
            self.header_label.setStyleSheet("""
                font-size: 16px;
                font-weight: bold;
                color: white;
                padding: 10px;
                background: #e17055;
                border-radius: 8px;
            """)
            self.btn_sync_all.setEnabled(True)
        else:
            self.header_label.setText("✅ Todos los datos están actualizados")
            self.header_label.setStyleSheet("""
                font-size: 16px;
                font-weight: bold;
                color: white;
                padding: 10px;
                background: #00b894;
                border-radius: 8px;
            """)
        
        # Actualizar badges de tabs
        tab_text = f"⚠️ Datos Pendientes ({total_pending})" if total_pending > 0 else "✅ Datos Pendientes"
        self.main_tabs.setTabText(0, tab_text)
        
        coverage_issues = no_data + incomplete
        tab_text = f"📊 Cobertura ({coverage_issues} issues)" if coverage_issues > 0 else "📊 Cobertura"
        self.main_tabs.setTabText(1, tab_text)
        
        self.progress_bar.setValue(100)
        self.progress_label.setText("Verificación completada")
        self._log("Verificación completada", "success")
    
    def _on_check_error(self, error):
        self.progress_label.setText("Error en verificación")
        self._log(f"Error: {error}", "error")
        QMessageBox.critical(self, "Error", f"Error verificando datos:\n{error}")
    
    def _populate_outdated_table(self):
        """Rellena la tabla de partidos desactualizados"""
        self.outdated_table.setRowCount(len(self.outdated_fixtures))
        
        for i, fixture in enumerate(self.outdated_fixtures):
            chk = QCheckBox()
            chk.setChecked(True)
            self.outdated_table.setCellWidget(i, 0, chk)
            
            item_id = QTableWidgetItem(str(fixture['id']))
            item_id.setData(Qt.UserRole, fixture['id'])
            item_id.setTextAlignment(Qt.AlignCenter)
            self.outdated_table.setItem(i, 1, item_id)
            
            fecha = str(fixture['date'])[:16] if fixture['date'] else ''
            self.outdated_table.setItem(i, 2, QTableWidgetItem(fecha))
            
            # Región
            region = fixture.get('region', '')
            item_region = QTableWidgetItem(region)
            if 'SUDAMERICA' in region or 'MEXICO' in region:
                item_region.setBackground(QColor('#ffeaa7'))
            elif 'EUROPA' in region:
                item_region.setBackground(QColor('#dfe6e9'))
            elif 'COPA' in region:
                item_region.setBackground(QColor('#81ecec'))
            self.outdated_table.setItem(i, 3, item_region)
            
            self.outdated_table.setItem(i, 4, QTableWidgetItem(fixture['league_name']))
            
            match = f"{fixture['home_name']} vs {fixture['away_name']}"
            self.outdated_table.setItem(i, 5, QTableWidgetItem(match))
            
            status = fixture['status'] or 'N/A'
            item_status = QTableWidgetItem(status)
            item_status.setTextAlignment(Qt.AlignCenter)
            if status not in ['FT', 'AET', 'PEN']:
                item_status.setBackground(QColor('#fff3cd'))
            self.outdated_table.setItem(i, 6, item_status)
        
        count = len(self.outdated_fixtures)
        self.outdated_info.setText(
            f"📊 {count} partidos encontrados que ya deberían haber terminado pero no tienen resultados"
            if count > 0 else "✅ No hay partidos desactualizados"
        )
        self.btn_sync_results.setEnabled(count > 0)
    
    def _populate_odds_table(self):
        """Rellena la tabla de odds faltantes"""
        self.odds_table.setRowCount(len(self.missing_odds))
        
        for i, fixture in enumerate(self.missing_odds):
            chk = QCheckBox()
            chk.setChecked(True)
            self.odds_table.setCellWidget(i, 0, chk)
            
            item_id = QTableWidgetItem(str(fixture['id']))
            item_id.setData(Qt.UserRole, fixture['id'])
            item_id.setTextAlignment(Qt.AlignCenter)
            self.odds_table.setItem(i, 1, item_id)
            
            fecha = str(fixture['date'])[:16] if fixture['date'] else ''
            self.odds_table.setItem(i, 2, QTableWidgetItem(fecha))
            
            # Región
            region = fixture.get('region', '')
            item_region = QTableWidgetItem(region)
            if 'SUDAMERICA' in region or 'MEXICO' in region:
                item_region.setBackground(QColor('#ffeaa7'))
            elif 'EUROPA' in region:
                item_region.setBackground(QColor('#dfe6e9'))
            elif 'COPA' in region:
                item_region.setBackground(QColor('#81ecec'))
            self.odds_table.setItem(i, 3, item_region)
            
            self.odds_table.setItem(i, 4, QTableWidgetItem(fixture['league_name']))
            
            match = f"{fixture['home_name']} vs {fixture['away_name']}"
            self.odds_table.setItem(i, 5, QTableWidgetItem(match))
            
            hours = fixture.get('hours_remaining', 0)
            item_hours = QTableWidgetItem(f"{hours}h")
            item_hours.setTextAlignment(Qt.AlignCenter)
            if hours < 24:
                item_hours.setBackground(QColor('#ff7675'))
                item_hours.setForeground(QColor('white'))
            elif hours < 48:
                item_hours.setBackground(QColor('#fdcb6e'))
            self.odds_table.setItem(i, 6, item_hours)
        
        count = len(self.missing_odds)
        self.odds_info.setText(
            f"📊 {count} partidos en las próximas 72 horas sin odds descargadas"
            if count > 0 else "✅ Todos los partidos próximos tienen odds"
        )
        self.btn_sync_odds.setEnabled(count > 0)
    
    def _populate_coverage_table(self):
        """Rellena la tabla de cobertura de ligas"""
        self.coverage_table.setRowCount(len(self.league_coverage))
        
        for i, league in enumerate(self.league_coverage):
            chk = QCheckBox()
            chk.setChecked(league['status'] in ('NO_DATA', 'INCOMPLETE'))
            self.coverage_table.setCellWidget(i, 0, chk)
            
            item_id = QTableWidgetItem(str(league['league_id']))
            item_id.setData(Qt.UserRole, league['league_id'])
            item_id.setTextAlignment(Qt.AlignCenter)
            self.coverage_table.setItem(i, 1, item_id)
            
            # Región
            region = league.get('region', '')
            item_region = QTableWidgetItem(region)
            if 'SUDAMERICA' in region or 'MEXICO' in region:
                item_region.setBackground(QColor('#ffeaa7'))
            elif 'EUROPA' in region:
                item_region.setBackground(QColor('#dfe6e9'))
            elif 'COPA' in region:
                item_region.setBackground(QColor('#81ecec'))
            self.coverage_table.setItem(i, 2, item_region)
            
            self.coverage_table.setItem(i, 3, QTableWidgetItem(league['league_name']))
            
            item_fixtures = QTableWidgetItem(str(league['total_fixtures']))
            item_fixtures.setTextAlignment(Qt.AlignCenter)
            self.coverage_table.setItem(i, 4, item_fixtures)
            
            item_seasons = QTableWidgetItem(str(league['seasons']))
            item_seasons.setTextAlignment(Qt.AlignCenter)
            self.coverage_table.setItem(i, 5, item_seasons)
            
            first_year = league.get('first_year', '-')
            item_year = QTableWidgetItem(str(first_year) if first_year else '-')
            item_year.setTextAlignment(Qt.AlignCenter)
            self.coverage_table.setItem(i, 6, item_year)
            
            # Estado con colores
            status = league['status']
            item_status = QTableWidgetItem(league['status_text'])
            item_status.setTextAlignment(Qt.AlignCenter)
            if status == 'NO_DATA':
                item_status.setBackground(QColor('#ff7675'))
                item_status.setForeground(QColor('white'))
            elif status == 'INCOMPLETE':
                item_status.setBackground(QColor('#fdcb6e'))
            else:
                item_status.setBackground(QColor('#00b894'))
                item_status.setForeground(QColor('white'))
            self.coverage_table.setItem(i, 7, item_status)
        
        no_data = len([c for c in self.league_coverage if c['status'] == 'NO_DATA'])
        incomplete = len([c for c in self.league_coverage if c['status'] == 'INCOMPLETE'])
        ok = len([c for c in self.league_coverage if c['status'] == 'OK'])
        
        self.coverage_info.setText(
            f"📊 Cobertura: {ok} OK | {incomplete} incompletas | {no_data} sin datos"
        )
        self.btn_download_historical.setEnabled(no_data > 0 or incomplete > 0)
    
    def _select_all_table(self, table: QTableWidget, select: bool):
        """Selecciona/deselecciona todos los items de una tabla"""
        for i in range(table.rowCount()):
            chk = table.cellWidget(i, 0)
            if chk:
                chk.setChecked(select)
    
    def _select_missing_coverage(self):
        """Selecciona ligas sin datos"""
        for i in range(self.coverage_table.rowCount()):
            chk = self.coverage_table.cellWidget(i, 0)
            status_item = self.coverage_table.item(i, 7)
            if chk and status_item:
                chk.setChecked('Sin datos' in status_item.text())
    
    def _select_incomplete_coverage(self):
        """Selecciona ligas incompletas"""
        for i in range(self.coverage_table.rowCount()):
            chk = self.coverage_table.cellWidget(i, 0)
            status_item = self.coverage_table.item(i, 7)
            if chk and status_item:
                chk.setChecked('Solo desde' in status_item.text())
    
    def _get_selected_ids(self, table: QTableWidget) -> List[int]:
        """Obtiene IDs seleccionados de una tabla"""
        ids = []
        for i in range(table.rowCount()):
            chk = table.cellWidget(i, 0)
            if chk and chk.isChecked():
                item = table.item(i, 1)
                if item:
                    ids.append(int(item.data(Qt.UserRole)))
        return ids
    
    def _sync_results(self):
        """Sincroniza resultados seleccionados"""
        ids = self._get_selected_ids(self.outdated_table)
        if not ids:
            QMessageBox.warning(self, "Sin selección", "Selecciona al menos un partido")
            return
        
        leagues = set()
        for fixture in self.outdated_fixtures:
            if fixture['id'] in ids:
                leagues.add(fixture['league_name'])
        
        reply = QMessageBox.question(
            self, "Confirmar",
            f"¿Actualizar resultados de {len(ids)} partidos?\n\n"
            f"Se consultarán {len(leagues)} ligas (1 llamada API por liga)\n"
            f"Se sincronizará el fixture completo de cada liga.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._start_sync('results', ids)
    
    def _sync_odds(self):
        """Descarga odds seleccionados"""
        ids = self._get_selected_ids(self.odds_table)
        if not ids:
            QMessageBox.warning(self, "Sin selección", "Selecciona al menos un partido")
            return
        
        reply = QMessageBox.question(
            self, "Confirmar",
            f"¿Descargar odds de {len(ids)} partidos?\n\n"
            f"Esto consumirá {len(ids)} llamadas a la API.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._start_sync('odds', ids)
    
    def _download_historical(self):
        """Descarga datos históricos para ligas seleccionadas"""
        league_ids = self._get_selected_ids(self.coverage_table)
        if not league_ids:
            QMessageBox.warning(self, "Sin selección", "Selecciona al menos una liga")
            return
        
        # Determinar temporadas a descargar
        current_year = datetime.now().year
        seasons = list(range(MIN_YEAR_DATA, current_year + 1))
        
        total_calls = len(league_ids) * len(seasons)
        
        reply = QMessageBox.question(
            self, "Confirmar Descarga Histórica",
            f"¿Descargar datos históricos para {len(league_ids)} ligas?\n\n"
            f"Temporadas: {MIN_YEAR_DATA} - {current_year}\n"
            f"Total estimado: ~{total_calls} llamadas API\n\n"
            "⚠️ Esto puede tomar varios minutos y consumir muchas llamadas.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._start_sync('historical', league_ids=league_ids, seasons=seasons)

    def _refresh_current_season(self):
        """Actualiza la temporada en curso para las ligas configuradas."""
        all_league_ids = get_all_configured_league_ids()
        
        if self.chk_only_issues.isChecked():
            issue_ids = set()
            for c in self.league_coverage:
                if c['status'] in ('NO_DATA', 'INCOMPLETE'):
                    issue_ids.add(c['league_id'])
            for f in self.outdated_fixtures:
                issue_ids.add(f['league_id'])
            for f in self.missing_odds:
                issue_ids.add(f['league_id'])
            
            league_ids = [lid for lid in all_league_ids if lid in issue_ids]
            
            if not league_ids:
                QMessageBox.information(
                    self, "Sin issues",
                    "No hay ligas con problemas detectados.\n"
                    "Desmarca 'Solo ligas con issues' para actualizar todas."
                )
                return
        else:
            league_ids = all_league_ids
        
        country_by_id = {}
        for region_leagues in LIGAS_CONFIG.values():
            for lid, name in region_leagues.items():
                if ' - ' in name:
                    country_by_id[lid] = name.split(' - ')[0]
        
        groups = group_leagues_by_season(league_ids, country_by_id)
        
        summary = "\n".join(
            f"  • Temporada {s}: {len(ids)} ligas"
            for s, ids in groups.items()
        )
        
        scope = "ligas con issues" if self.chk_only_issues.isChecked() else "todas las ligas"
        
        reply = QMessageBox.question(
            self,
            "Confirmar actualizacion",
            f"Se actualizaran {len(league_ids)} {scope} "
            f"agrupadas por temporada:\n\n{summary}\n\n"
            f"Total: ~{len(league_ids)} llamadas API.\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self._season_queue = [(s, ids) for s, ids in groups.items()]
        self._log(
            f"🔄 Iniciando actualizacion de {len(league_ids)} ligas "
            f"en {len(self._season_queue)} grupo(s) de temporada...",
            "info"
        )
        self._process_next_season_group()
    
    def _process_next_season_group(self):
        """Procesa el siguiente grupo de temporada de la cola."""
        if not hasattr(self, '_season_queue') or not self._season_queue:
            self._log("✅ Actualizacion de temporada en curso completada", "success")
            self._start_check()
            return
        
        season, lids = self._season_queue.pop(0)
        self._log(f"📡 Procesando {len(lids)} ligas para temporada {season}...", "info")
        self._start_sync('historical', league_ids=lids, seasons=[season])


    def _sync_all(self):
        """Sincroniza todo"""
        result_ids = self._get_selected_ids(self.outdated_table)
        odds_ids = self._get_selected_ids(self.odds_table)
        
        total = len(result_ids) + len(odds_ids)
        if total == 0:
            QMessageBox.warning(self, "Sin selección", "No hay elementos seleccionados")
            return
        
        result_leagues = set()
        for fixture in self.outdated_fixtures:
            if fixture['id'] in result_ids:
                result_leagues.add(fixture['league_name'])
        
        api_calls_results = len(result_leagues)
        api_calls_odds = len(odds_ids)
        
        reply = QMessageBox.question(
            self, "Confirmar Sincronización Total",
            f"Se actualizarán:\n"
            f"• {len(result_ids)} resultados ({api_calls_results} llamadas API)\n"
            f"• {len(odds_ids)} cuotas ({api_calls_odds} llamadas API)\n\n"
            f"Total: ~{api_calls_results + api_calls_odds} llamadas a la API\n\n"
            "¿Continuar?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if result_ids:
                self._start_sync('results', result_ids, then_odds=odds_ids)
            elif odds_ids:
                self._start_sync('odds', odds_ids)
    
    def _start_sync(self, sync_type: str, ids: List[int] = None, then_odds: List[int] = None, 
                    league_ids: List[int] = None, seasons: List[int] = None):
        """Inicia sincronización"""
        if self.sync_worker and self.sync_worker.isRunning():
            QMessageBox.warning(self, "Ocupado", "Ya hay una sincronización en curso")
            return
        
        self.progress_bar.setValue(0)
        self._pending_odds = then_odds
        
        self.btn_sync_all.setEnabled(False)
        self.btn_sync_results.setEnabled(False)
        self.btn_sync_odds.setEnabled(False)
        self.btn_download_historical.setEnabled(False)
        
        self.sync_worker = DataSyncWorker(
            sync_type, 
            fixture_ids=ids,
            league_ids=league_ids,
            seasons=seasons
        )
        self.sync_worker.progress.connect(self._on_sync_progress)
        self.sync_worker.log.connect(self._log)
        self.sync_worker.finished.connect(self._on_sync_finished)
        self.sync_worker.error.connect(self._on_sync_error)
        self.sync_worker.start()
    
    def _on_sync_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.progress_label.setText(msg)
    
    def _on_sync_finished(self, result):
        sync_type = result.get('type')
        
        if sync_type == 'results':
            updated = result.get('updated', 0)
            merged = result.get('merged', 0)
            errors = result.get('errors', 0)
            self._log(f"Resultados actualizados: {updated} OK, {merged} fixtures sincronizados, {errors} errores", 
                     "success" if errors == 0 else "warning")
            
            if hasattr(self, '_pending_odds') and self._pending_odds:
                self._log("Continuando con descarga de odds...", "info")
                odds_ids = self._pending_odds
                self._pending_odds = None
                self._start_sync('odds', odds_ids)
                return
                
        elif sync_type == 'odds':
            saved = result.get('saved', 0)
            errors = result.get('errors', 0)
            self._log(f"Odds descargados: {saved} OK, {errors} errores",
                     "success" if errors == 0 else "warning")
        
        elif sync_type == 'historical':
            fixtures = result.get('fixtures', 0)
            errors = result.get('errors', 0)
            self._log(f"Datos históricos: {fixtures} fixtures guardados, {errors} errores",
                     "success" if errors == 0 else "warning")
            
            if hasattr(self, '_season_queue') and self._season_queue:
                self._process_next_season_group()
                return

        
        self.progress_label.setText("Sincronización completada")
        QMessageBox.information(self, "Completado", "Sincronización finalizada")
        
        self._start_check()
    
    def _on_sync_error(self, error):
        self.progress_label.setText("Error en sincronización")
        self._log(f"Error: {error}", "error")
        QMessageBox.critical(self, "Error", f"Error en sincronización:\n{error}")
        
        self.btn_sync_all.setEnabled(True)
        self.btn_sync_results.setEnabled(len(self.outdated_fixtures) > 0)
        self.btn_sync_odds.setEnabled(len(self.missing_odds) > 0)
        self.btn_download_historical.setEnabled(True)
    
    def _log(self, message: str, msg_type: str = "info"):
        """Añade mensaje al log"""
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


# ============================================================================
# FUNCIÓN PARA INTEGRAR CON EXTRACTION_WINDOW
# ============================================================================

def show_data_sync_dialog(parent=None) -> bool:
    """
    Muestra el diálogo de sincronización de datos.
    Retorna True si se realizaron cambios.
    """
    dialog = DataSyncDialog(parent)
    result = dialog.exec()
    return result == QDialog.Accepted


# ============================================================================
# MAIN (para pruebas)
# ============================================================================

if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    dialog = DataSyncDialog()
    dialog.show()
    sys.exit(app.exec())