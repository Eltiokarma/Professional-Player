#!/usr/bin/env python3
"""
EXTRACTOR AUTOMÁTICO DE DATOS v5.0
===================================
Versión para ejecución automática diaria.
Extrae todo lo posible sin saturar el rate limit.

Estrategia:
- Usa casi todo el límite diario (~95 requests)
- Delays largos entre requests (sin prisa)
- Prioridad: fixtures primero, odds después
"""

import os
import sys
import logging
import argparse
import sqlite3
import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass

# ==============================================================================
# CONFIGURACIÓN PRINCIPAL
# ==============================================================================

API_KEY = os.getenv('API_KEY', 'b60d0208ddmsh43bd45eb5ed3c91p17411cjsn23301d31c9f6')
SEASON = 2026
DATABASE_PATH = os.getenv('DATABASE_PATH', 'sad.db')

# Límite conservador (plan free = 100/día, dejamos margen)
DEFAULT_REQUEST_LIMIT = 95

# Delay entre requests (segundos) - sin prisa
DELAY_ENTRE_REQUESTS = 1.5

# ==============================================================================
# BOOKMAKERS
# ==============================================================================
BOOKMAKERS_PRIORITY = [
    26,   # Betsson
    8,    # Bet365
    6,    # Bwin
    11,   # 1xBet
    4,    # Pinnacle
    24,   # Betway
    32,   # Betano
]

# ==============================================================================
# LIGAS - TODAS LAS QUE QUIERES
# ==============================================================================
LIGAS_CONFIG = {
    'SUDAMERICA': {
        128: 'Argentina - Liga Profesional',
        129: 'Argentina - Primera Nacional',
        71: 'Brasil - Serie A',
        72: 'Brasil - Serie B',
        239: 'Colombia - Primera A',
        265: 'Chile - Primera División',
        281: 'Perú - Primera División',
        268: 'Uruguay - Primera División',
        242: 'Ecuador - Liga Pro',
    },
    'MEXICO': {
        262: 'México - Liga MX',
        263: 'México - Liga de Expansión',
    },
    'COPAS_CONMEBOL': {
        13: 'CONMEBOL Libertadores',
        11: 'CONMEBOL Sudamericana',
    },
    'COPAS_UEFA': {
        2: 'UEFA Champions League',
        3: 'UEFA Europa League',
        848: 'UEFA Conference League',
    },
    'EUROPA_TOP': {
        39: 'Inglaterra - Premier League',
        40: 'Inglaterra - Championship',
        140: 'España - La Liga',
        141: 'España - Segunda División',
        135: 'Italia - Serie A',
        136: 'Italia - Serie B',
        78: 'Alemania - Bundesliga',
        79: 'Alemania - 2. Bundesliga',
        61: 'Francia - Ligue 1',
        62: 'Francia - Ligue 2',
    },
    'EUROPA_OTROS': {
        94: 'Portugal - Primeira Liga',
        144: 'Bélgica - Pro League',
    },
}

# Rango de fechas
DIAS_ATRAS = 3
DIAS_ADELANTE = 10

# ==============================================================================
# LOGGING
# ==============================================================================

def setup_logging():
    log_format = '%(asctime)s | %(levelname)-8s | %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('extractor.log', encoding='utf-8')
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==============================================================================
# CONTADOR DE REQUESTS
# ==============================================================================

@dataclass
class RequestCounter:
    count: int = 0
    limit: int = DEFAULT_REQUEST_LIMIT
    
    def increment(self) -> bool:
        self.count += 1
        if self.count > self.limit:
            logger.warning(f"⚠️  LÍMITE ALCANZADO: {self.limit} requests")
            return False
        return True
    
    def remaining(self) -> int:
        return max(0, self.limit - self.count)
    
    def status(self) -> str:
        return f"[{self.count}/{self.limit}]"
    
    def hay_espacio(self, necesarios: int = 1) -> bool:
        return self.remaining() >= necesarios

request_counter = RequestCounter()

# ==============================================================================
# CLIENTE API
# ==============================================================================

class APIFootballClient:
    BASE_URL = 'https://api-football-v1.p.rapidapi.com/v3'
    
    def __init__(self, api_key: str, dry_run: bool = False):
        self.api_key = api_key
        self.dry_run = dry_run
        self.session = requests.Session()
        self.session.headers.update({
            'x-rapidapi-key': api_key,
            'x-rapidapi-host': 'api-football-v1.p.rapidapi.com'
        })
    
    def _request(self, endpoint: str, params: dict = None) -> Optional[Dict]:
        global request_counter
        
        if not request_counter.increment():
            return None
        
        if self.dry_run:
            logger.info(f"  [DRY-RUN] {endpoint} {params}")
            return {'response': []}
        
        url = f"{self.BASE_URL}/{endpoint}"
        
        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code == 429:
                    logger.warning("⏳ Rate limit - esperando 60s...")
                    time.sleep(60)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                if data.get('errors') and len(data['errors']) > 0:
                    logger.error(f"Error API: {data['errors']}")
                    return None
                
                # Delay después de cada request exitoso
                time.sleep(DELAY_ENTRE_REQUESTS)
                return data
                
            except requests.exceptions.Timeout:
                logger.warning(f"  Timeout (intento {attempt+1}/3)")
                time.sleep(5)
            except Exception as e:
                logger.error(f"  Error: {e}")
                if attempt < 2:
                    time.sleep(3)
        
        return None
    
    def get_fixtures(self, league_id: int, season: int,
                     from_date: str = None, to_date: str = None) -> List[Dict]:
        params = {'league': league_id, 'season': season}
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        
        data = self._request('fixtures', params)
        return data.get('response', []) if data else []
    
    def get_odds(self, fixture_id: int) -> List[Dict]:
        """Obtiene odds de TODOS los bookmakers (1 request)"""
        params = {'fixture': fixture_id}
        data = self._request('odds', params)
        return data.get('response', []) if data else []

# ==============================================================================
# BASE DE DATOS
# ==============================================================================

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_tables()
    
    def _ensure_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY,
                name TEXT,
                country TEXT,
                founded INTEGER,
                logo TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fixtures (
                id INTEGER PRIMARY KEY,
                timezone TEXT,
                date DATETIME,
                timestamp INTEGER,
                first_half_start INTEGER,
                second_half_start INTEGER,
                venue_id INTEGER,
                venue_name TEXT,
                venue_city TEXT,
                status_long TEXT,
                status_short TEXT,
                elapsed INTEGER,
                league_id INTEGER,
                league_season INTEGER,
                league_round TEXT,
                home_team_id INTEGER REFERENCES teams(id),
                away_team_id INTEGER REFERENCES teams(id),
                goals_home INTEGER,
                goals_away INTEGER,
                halftime_home INTEGER,
                halftime_away INTEGER,
                fulltime_home INTEGER,
                fulltime_away INTEGER,
                extratime_home INTEGER,
                extratime_away INTEGER,
                penalty_home INTEGER,
                penalty_away INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS odds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fixture_id INTEGER REFERENCES fixtures(id),
                league_id INTEGER,
                bookmaker_id INTEGER,
                bookmaker_name TEXT,
                bet_id INTEGER,
                bet_name TEXT,
                value TEXT,
                odd REAL
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_fixtures_league ON fixtures(league_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_odds_fixture ON odds(fixture_id)')
        
        conn.commit()
        conn.close()
    
    def save_team(self, team_data: dict):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO teams (id, name, country, founded, logo)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                team_data.get('id'),
                team_data.get('name'),
                team_data.get('country'),
                team_data.get('founded'),
                team_data.get('logo')
            ))
            conn.commit()
        finally:
            conn.close()
    
    def save_fixture(self, fixture_data: dict) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            f = fixture_data.get('fixture', {})
            league = fixture_data.get('league', {})
            teams = fixture_data.get('teams', {})
            goals = fixture_data.get('goals', {})
            score = fixture_data.get('score', {})
            
            home = teams.get('home', {})
            away = teams.get('away', {})
            
            if home.get('id'):
                self.save_team(home)
            if away.get('id'):
                self.save_team(away)
            
            halftime = score.get('halftime', {})
            fulltime = score.get('fulltime', {})
            extratime = score.get('extratime', {})
            penalty = score.get('penalty', {})
            
            cursor.execute('''
                INSERT OR REPLACE INTO fixtures (
                    id, timezone, date, timestamp,
                    first_half_start, second_half_start,
                    venue_id, venue_name, venue_city,
                    status_long, status_short, elapsed,
                    league_id, league_season, league_round,
                    home_team_id, away_team_id,
                    goals_home, goals_away,
                    halftime_home, halftime_away,
                    fulltime_home, fulltime_away,
                    extratime_home, extratime_away,
                    penalty_home, penalty_away
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                f.get('id'),
                f.get('timezone'),
                f.get('date'),
                f.get('timestamp'),
                f.get('periods', {}).get('first'),
                f.get('periods', {}).get('second'),
                f.get('venue', {}).get('id'),
                f.get('venue', {}).get('name'),
                f.get('venue', {}).get('city'),
                f.get('status', {}).get('long'),
                f.get('status', {}).get('short'),
                f.get('status', {}).get('elapsed'),
                league.get('id'),
                league.get('season'),
                league.get('round'),
                home.get('id'),
                away.get('id'),
                goals.get('home'),
                goals.get('away'),
                halftime.get('home'),
                halftime.get('away'),
                fulltime.get('home'),
                fulltime.get('away'),
                extratime.get('home'),
                extratime.get('away'),
                penalty.get('home'),
                penalty.get('away')
            ))
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error guardando fixture: {e}")
            return False
        finally:
            conn.close()
    
    def save_odds(self, fixture_id: int, odds_data: list) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        count = 0
        
        try:
            for response in odds_data:
                league_id = response.get('league', {}).get('id')
                
                for bookmaker in response.get('bookmakers', []):
                    bk_id = bookmaker.get('id')
                    bk_name = bookmaker.get('name')
                    
                    for bet in bookmaker.get('bets', []):
                        bet_id = bet.get('id')
                        bet_name = bet.get('name')
                        
                        for value in bet.get('values', []):
                            odd_value = value.get('odd')
                            try:
                                odd_float = float(odd_value) if odd_value else None
                            except:
                                odd_float = None
                            
                            cursor.execute('''
                                SELECT id FROM odds 
                                WHERE fixture_id = ? AND bookmaker_id = ? 
                                AND bet_id = ? AND value = ?
                            ''', (fixture_id, bk_id, bet_id, value.get('value')))
                            
                            existing = cursor.fetchone()
                            
                            if existing:
                                cursor.execute('UPDATE odds SET odd = ? WHERE id = ?', 
                                             (odd_float, existing[0]))
                            else:
                                cursor.execute('''
                                    INSERT INTO odds (fixture_id, league_id, bookmaker_id,
                                        bookmaker_name, bet_id, bet_name, value, odd)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (fixture_id, league_id, bk_id, bk_name, 
                                      bet_id, bet_name, value.get('value'), odd_float))
                            count += 1
            
            conn.commit()
        except Exception as e:
            logger.error(f"Error guardando odds: {e}")
        finally:
            conn.close()
        
        return count
    
    def get_fixtures_sin_odds(self, days_ahead: int = 7) -> List[int]:
        """Fixtures próximos que no tienen odds"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        future = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT DISTINCT f.id FROM fixtures f
            LEFT JOIN odds o ON f.id = o.fixture_id
            WHERE f.status_short = 'NS'
            AND date(f.date) BETWEEN ? AND ?
            AND o.id IS NULL
            ORDER BY f.date
        ''', (today, future))
        
        ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return ids
    
    def get_stats(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM fixtures')
        fixtures = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM teams')
        teams = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM odds')
        odds = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(DISTINCT fixture_id) FROM odds')
        fixtures_con_odds = cursor.fetchone()[0]
        
        conn.close()
        return {
            'fixtures': fixtures, 
            'teams': teams, 
            'odds': odds,
            'fixtures_con_odds': fixtures_con_odds
        }

# ==============================================================================
# EXTRACTOR
# ==============================================================================

class Extractor:
    def __init__(self, api: APIFootballClient, db: Database):
        self.api = api
        self.db = db
        self.stats = {
            'fixtures_nuevos': 0,
            'fixtures_actualizados': 0,
            'odds_guardados': 0,
            'ligas_procesadas': 0
        }
    
    def extraer_fixtures(self, ligas: Dict[int, str]):
        """Extrae fixtures de todas las ligas"""
        logger.info("=" * 60)
        logger.info("⚽ FASE 1: EXTRAYENDO FIXTURES")
        logger.info("=" * 60)
        
        from_date = (datetime.now() - timedelta(days=DIAS_ATRAS)).strftime('%Y-%m-%d')
        to_date = (datetime.now() + timedelta(days=DIAS_ADELANTE)).strftime('%Y-%m-%d')
        
        logger.info(f"📅 Rango: {from_date} → {to_date}")
        logger.info(f"📋 Ligas a procesar: {len(ligas)}")
        logger.info(f"📊 Requests disponibles: {request_counter.remaining()}")
        
        for i, (liga_id, liga_nombre) in enumerate(ligas.items(), 1):
            if not request_counter.hay_espacio():
                logger.warning("⚠️  Sin requests disponibles para más ligas")
                break
            
            logger.info(f"\n[{i}/{len(ligas)}] {liga_nombre}")
            
            fixtures = self.api.get_fixtures(liga_id, SEASON, from_date, to_date)
            
            guardados = 0
            for fixture in fixtures:
                if self.db.save_fixture(fixture):
                    guardados += 1
            
            self.stats['fixtures_nuevos'] += guardados
            self.stats['ligas_procesadas'] += 1
            logger.info(f"  ✓ {guardados} fixtures {request_counter.status()}")
    
    def extraer_odds(self):
        """Extrae odds para fixtures que no tienen"""
        logger.info("\n" + "=" * 60)
        logger.info("💰 FASE 2: EXTRAYENDO ODDS")
        logger.info("=" * 60)
        
        fixtures_pendientes = self.db.get_fixtures_sin_odds(days_ahead=DIAS_ADELANTE)
        
        if not fixtures_pendientes:
            logger.info("✓ Todos los fixtures ya tienen odds")
            return
        
        requests_disponibles = request_counter.remaining()
        fixtures_a_procesar = fixtures_pendientes[:requests_disponibles]
        
        logger.info(f"📋 Fixtures sin odds: {len(fixtures_pendientes)}")
        logger.info(f"📊 Requests disponibles: {requests_disponibles}")
        logger.info(f"🎯 Procesaremos: {len(fixtures_a_procesar)} fixtures")
        
        for i, fixture_id in enumerate(fixtures_a_procesar, 1):
            if not request_counter.hay_espacio():
                logger.info("📊 Límite alcanzado - continuamos mañana")
                break
            
            odds = self.api.get_odds(fixture_id)
            
            if odds:
                count = self.db.save_odds(fixture_id, odds)
                self.stats['odds_guardados'] += count
                bk_count = sum(len(r.get('bookmakers', [])) for r in odds)
                logger.info(f"[{i}/{len(fixtures_a_procesar)}] Fixture {fixture_id}: {count} odds ({bk_count} bk) {request_counter.status()}")
            else:
                logger.info(f"[{i}/{len(fixtures_a_procesar)}] Fixture {fixture_id}: sin odds {request_counter.status()}")
    
    def mostrar_resumen(self):
        db_stats = self.db.get_stats()
        
        logger.info("\n" + "=" * 60)
        logger.info("📊 RESUMEN DE EJECUCIÓN")
        logger.info("=" * 60)
        logger.info(f"  Requests usados:     {request_counter.count}/{request_counter.limit}")
        logger.info(f"  Ligas procesadas:    {self.stats['ligas_procesadas']}")
        logger.info(f"  Fixtures extraídos:  {self.stats['fixtures_nuevos']}")
        logger.info(f"  Odds guardados:      {self.stats['odds_guardados']}")
        logger.info("")
        logger.info("📁 ESTADO DE LA BASE DE DATOS:")
        logger.info(f"  Total fixtures:      {db_stats['fixtures']}")
        logger.info(f"  Total equipos:       {db_stats['teams']}")
        logger.info(f"  Total odds:          {db_stats['odds']}")
        logger.info(f"  Fixtures con odds:   {db_stats['fixtures_con_odds']}")
        logger.info("=" * 60)

# ==============================================================================
# MAIN
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description='Extractor automático API-Football v5')
    parser.add_argument('--fixtures', action='store_true', help='Solo fixtures')
    parser.add_argument('--odds', action='store_true', help='Solo odds')
    parser.add_argument('--limit', type=int, default=DEFAULT_REQUEST_LIMIT, help='Límite requests')
    parser.add_argument('--db', default=DATABASE_PATH, help='Ruta base de datos')
    parser.add_argument('--dry-run', action='store_true', help='Simular sin hacer requests')
    
    args = parser.parse_args()
    
    # Verificar API key
    if API_KEY == 'TU_API_KEY_AQUI':
        logger.error("❌ Configura tu API_KEY en el script")
        sys.exit(1)
    
    # Configurar límite
    global request_counter
    request_counter = RequestCounter(limit=args.limit)
    
    # Header
    logger.info("")
    logger.info("🚀 " + "=" * 56)
    logger.info("🚀 EXTRACTOR AUTOMÁTICO API-FOOTBALL v5.0")
    logger.info("🚀 " + "=" * 56)
    logger.info(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📊 Límite de requests: {args.limit}")
    logger.info(f"⏱️  Delay entre requests: {DELAY_ENTRE_REQUESTS}s")
    if args.dry_run:
        logger.info("⚠️  MODO DRY-RUN (sin requests reales)")
    
    # Crear cliente y DB
    api = APIFootballClient(API_KEY, dry_run=args.dry_run)
    db = Database(args.db)
    extractor = Extractor(api, db)
    
    # Construir lista de todas las ligas
    todas_ligas = {}
    for region, ligas in LIGAS_CONFIG.items():
        todas_ligas.update(ligas)
    
    logger.info(f"⚽ Ligas configuradas: {len(todas_ligas)}")
    
    # Ejecutar
    solo_fixtures = args.fixtures and not args.odds
    solo_odds = args.odds and not args.fixtures
    ambos = not args.fixtures and not args.odds
    
    if solo_fixtures or ambos:
        extractor.extraer_fixtures(todas_ligas)
    
    if solo_odds or ambos:
        extractor.extraer_odds()
    
    # Resumen
    extractor.mostrar_resumen()
    
    logger.info("")
    logger.info("✅ EJECUCIÓN COMPLETADA")
    logger.info("")

if __name__ == '__main__':
    main()