# ui/odds_viewer/models/database_queries.py
# -*- coding: utf-8 -*-
"""
Consultas a la base de datos para fixtures, odds y estadÃ­sticas.
"""

import logging
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .data_models import (
    FixtureData, OddData, FixtureWithOdds, CoverageStats
)

logger = logging.getLogger(__name__)


class OddsQueryModel:
    """Modelo para consultas de odds y fixtures."""
    
    def __init__(self, db_path: str = None):
        """
        Inicializa el modelo de consultas.
        
        Args:
            db_path: Ruta a la base de datos SQLite.
                     Si es None, intenta encontrar sad.db automÃ¡ticamente.
        """
        self._engine = None
        self._session = None
        self._db_path = db_path
        
        if db_path:
            self.connect(db_path)
    
    def connect(self, db_path: str) -> bool:
        """Conecta a la base de datos."""
        try:
            self._db_path = db_path
            self._engine = create_engine(f'sqlite:///{db_path}', echo=False)
            Session = sessionmaker(bind=self._engine)
            self._session = Session()
            logger.info(f"Conectado a: {db_path}")
            return True
        except Exception as e:
            logger.error(f"Error conectando a BD: {e}")
            return False
    
    def close(self):
        """Cierra la conexiÃ³n."""
        if self._session:
            self._session.close()
        if self._engine:
            self._engine.dispose()
    
    # =========================================================================
    # Helpers internos
    # =========================================================================
    
    def _get_preferred_bookmaker(self, fixture_id: int) -> Optional[str]:
        """
        Obtiene el bookmaker preferido para un fixture.
        Prioridad: bet365 > el que tenga mas cuotas registradas.
        Garantiza consistencia entre card, detalle y simulador.
        """
        try:
            sql = f"""
                SELECT bookmaker_name, COUNT(*) as cnt
                FROM odds
                WHERE fixture_id = {fixture_id}
                GROUP BY bookmaker_name
                ORDER BY 
                    CASE WHEN LOWER(bookmaker_name) LIKE '%bet365%' THEN 0 ELSE 1 END,
                    cnt DESC
                LIMIT 1
            """
            with self._engine.connect() as conn:
                row = conn.execute(text(sql)).fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Error obteniendo bookmaker preferido: {e}")
            return None
    
    # =========================================================================
    # Consultas de Ligas y Equipos
    # =========================================================================
    
    def get_leagues(self) -> List[Dict[str, Any]]:
        """Obtiene todas las ligas disponibles."""
        try:
            sql = """
                SELECT DISTINCT 
                    f.league_id,
                    COALESCE(l.name, 'Liga ' || f.league_id) as league_name,
                    COUNT(DISTINCT f.id) as fixture_count
                FROM fixtures f
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE f.league_id IS NOT NULL
                GROUP BY f.league_id
                ORDER BY fixture_count DESC
            """
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                return [
                    {'id': row[0], 'name': row[1], 'fixtures': row[2]}
                    for row in result.fetchall()
                ]
        except Exception as e:
            logger.error(f"Error obteniendo ligas: {e}")
            return []
    
    def get_seasons(self, league_id: int = None) -> List[int]:
        """Obtiene temporadas disponibles."""
        try:
            sql = "SELECT DISTINCT league_season FROM fixtures WHERE league_season IS NOT NULL"
            if league_id:
                sql += f" AND league_id = {league_id}"
            sql += " ORDER BY league_season DESC"
            
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Error obteniendo temporadas: {e}")
            return []
    
    def get_teams(self, league_id: int = None, season: int = None) -> List[Dict[str, Any]]:
        """Obtiene equipos de una liga/temporada."""
        try:
            sql = """
                SELECT DISTINCT t.id, t.name, t.country
                FROM teams t
                INNER JOIN fixtures f ON (t.id = f.home_team_id OR t.id = f.away_team_id)
                WHERE 1=1
            """
            if league_id:
                sql += f" AND f.league_id = {league_id}"
            if season:
                sql += f" AND f.league_season = {season}"
            sql += " ORDER BY t.name"
            
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                return [
                    {'id': row[0], 'name': row[1], 'country': row[2]}
                    for row in result.fetchall()
                ]
        except Exception as e:
            logger.error(f"Error obteniendo equipos: {e}")
            return []
    
    # =========================================================================
    # Consultas de Fixtures
    # =========================================================================
    
    def get_fixtures(
        self,
        league_id: int = None,
        season: int = None,
        team_id: int = None,
        from_date: datetime = None,
        to_date: datetime = None,
        with_odds_only: bool = False,
        limit: int = None
    ) -> List[FixtureData]:
        """
        Obtiene fixtures segÃºn filtros.
        
        Args:
            league_id: ID de la liga
            season: Temporada
            team_id: ID del equipo (local o visita)
            from_date: Fecha desde
            to_date: Fecha hasta
            with_odds_only: Solo fixtures con odds
            limit: LÃ­mite de resultados
        """
        try:
            sql = """
                SELECT 
                    f.id,
                    f.date,
                    f.home_team_id,
                    th.name as home_team_name,
                    f.away_team_id,
                    ta.name as away_team_name,
                    f.goals_home,
                    f.goals_away,
                    f.league_id,
                    COALESCE(l.name, 'Liga ' || f.league_id) as league_name,
                    f.league_season,
                    f.status_long
                FROM fixtures f
                LEFT JOIN teams th ON f.home_team_id = th.id
                LEFT JOIN teams ta ON f.away_team_id = ta.id
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE f.status_long = 'Match Finished'
            """
            
            if league_id:
                sql += f" AND f.league_id = {league_id}"
            if season:
                sql += f" AND f.league_season = {season}"
            if team_id:
                sql += f" AND (f.home_team_id = {team_id} OR f.away_team_id = {team_id})"
            if from_date:
                sql += f" AND f.date >= '{from_date.isoformat()}'"
            if to_date:
                sql += f" AND f.date <= '{to_date.isoformat()}'"
            if with_odds_only:
                sql += " AND EXISTS (SELECT 1 FROM odds o WHERE o.fixture_id = f.id)"
            
            sql += " ORDER BY f.date ASC"
            
            if limit:
                sql += f" LIMIT {limit}"
            
            fixtures = []
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result.fetchall():
                    # Parsear fecha
                    date_val = row[1]
                    if isinstance(date_val, str):
                        try:
                            date_val = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
                        except:
                            date_val = datetime.now()
                    
                    fixtures.append(FixtureData(
                        fixture_id=row[0],
                        date=date_val,
                        home_team_id=row[2],
                        home_team_name=row[3] or f"Team {row[2]}",
                        away_team_id=row[4],
                        away_team_name=row[5] or f"Team {row[4]}",
                        goals_home=row[6],
                        goals_away=row[7],
                        league_id=row[8],
                        league_name=row[9] or "Unknown",
                        season=row[10] or 0,
                        status=row[11] or "Unknown"
                    ))
            
            return fixtures
            
        except Exception as e:
            logger.error(f"Error obteniendo fixtures: {e}")
            return []
    
    def get_fixture_by_id(self, fixture_id: int) -> Optional[FixtureData]:
        """Obtiene un fixture por ID."""
        fixtures = self.get_fixtures(limit=1)
        # Consulta especÃ­fica
        try:
            sql = f"""
                SELECT 
                    f.id, f.date, f.home_team_id, th.name,
                    f.away_team_id, ta.name, f.goals_home, f.goals_away,
                    f.league_id, COALESCE(l.name, 'Liga'), f.league_season, f.status_long
                FROM fixtures f
                LEFT JOIN teams th ON f.home_team_id = th.id
                LEFT JOIN teams ta ON f.away_team_id = ta.id
                LEFT JOIN leagues l ON f.league_id = l.id
                WHERE f.id = {fixture_id}
            """
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                row = result.fetchone()
                if row:
                    date_val = row[1]
                    if isinstance(date_val, str):
                        try:
                            date_val = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
                        except:
                            date_val = datetime.now()
                    
                    return FixtureData(
                        fixture_id=row[0],
                        date=date_val,
                        home_team_id=row[2],
                        home_team_name=row[3] or f"Team {row[2]}",
                        away_team_id=row[4],
                        away_team_name=row[5] or f"Team {row[4]}",
                        goals_home=row[6],
                        goals_away=row[7],
                        league_id=row[8],
                        league_name=row[9],
                        season=row[10] or 0,
                        status=row[11] or "Unknown"
                    )
            return None
        except Exception as e:
            logger.error(f"Error obteniendo fixture {fixture_id}: {e}")
            return None
    
    # =========================================================================
    # Consultas de Odds
    # =========================================================================
    
    def get_odds_for_fixture(self, fixture_id: int) -> List[OddData]:
        """Obtiene todas las cuotas de un fixture."""
        try:
            sql = f"""
                SELECT 
                    fixture_id, bookmaker_id, bookmaker_name,
                    bet_id, bet_name, value, odd
                FROM odds
                WHERE fixture_id = {fixture_id}
                ORDER BY bet_name, value
            """
            odds = []
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result.fetchall():
                    odds.append(OddData(
                        fixture_id=row[0],
                        bookmaker_id=row[1] or 0,
                        bookmaker_name=row[2] or "Unknown",
                        bet_id=row[3] or 0,
                        bet_name=row[4] or "Unknown",
                        value=row[5] or "",
                        odd=row[6] or 0.0
                    ))
            return odds
        except Exception as e:
            logger.error(f"Error obteniendo odds para fixture {fixture_id}: {e}")
            return []
    
    def get_1x2_odds(self, fixture_id: int) -> Dict[str, float]:
        """
        Obtiene cuotas 1X2 para un fixture.
        Usa bookmaker preferido para consistencia entre vistas.
        
        Returns:
            Dict con claves "Home", "Draw", "Away"
        """
        try:
            preferred_bm = self._get_preferred_bookmaker(fixture_id)
            
            bm_filter = ""
            if preferred_bm:
                safe_bm = preferred_bm.replace("'", "''")
                bm_filter = f"AND bookmaker_name = '{safe_bm}'"
            
            sql = f"""
                SELECT value, odd
                FROM odds
                WHERE fixture_id = {fixture_id}
                AND (
                    LOWER(bet_name) LIKE '%winner%'
                    OR LOWER(bet_name) LIKE '%1x2%'
                    OR LOWER(bet_name) LIKE '%match result%'
                )
                AND value IN ('Home', 'Draw', 'Away')
                {bm_filter}
            """
            result_dict = {}
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result.fetchall():
                    result_dict[row[0]] = row[1]
            return result_dict
        except Exception as e:
            logger.error(f"Error obteniendo odds 1X2: {e}")
            return {}
    
    def get_over_under_odds(self, fixture_id: int, line: float = 2.5) -> Dict[str, float]:
        """
        Obtiene cuotas Over/Under TOTALES para una linea.
        Filtra por bet_id=5 para excluir Home/Away/FirstHalf goals.
        
        Returns:
            Dict con claves "Over", "Under"
        """
        try:
            line_str = str(line)
            preferred_bm = self._get_preferred_bookmaker(fixture_id)
            
            bm_filter = ""
            if preferred_bm:
                safe_bm = preferred_bm.replace("'", "''")
                bm_filter = f"AND bookmaker_name = '{safe_bm}'"
            
            # Intentar con bet_id=5 (Goals Over/Under total)
            sql = f"""
                SELECT value, odd
                FROM odds
                WHERE fixture_id = {fixture_id}
                AND COALESCE(bet_id, 0) = 5
                AND (value LIKE '%{line_str}%' OR bet_name LIKE '%{line_str}%')
                {bm_filter}
            """
            result_dict = {}
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result.fetchall():
                    value = row[0]
                    if 'over' in value.lower():
                        result_dict['Over'] = row[1]
                    elif 'under' in value.lower():
                        result_dict['Under'] = row[1]
                
                # Fallback: buscar por texto excluyendo modificadores
                if not result_dict:
                    sql_fb = f"""
                        SELECT value, odd
                        FROM odds
                        WHERE fixture_id = {fixture_id}
                        AND (
                            LOWER(bet_name) LIKE '%over%under%'
                            OR LOWER(bet_name) = 'goals over/under'
                        )
                        AND LOWER(bet_name) NOT LIKE '%first%'
                        AND LOWER(bet_name) NOT LIKE '%half%'
                        AND LOWER(bet_name) NOT LIKE '%home%'
                        AND LOWER(bet_name) NOT LIKE '%away%'
                        AND LOWER(bet_name) NOT LIKE '%team%'
                        AND LOWER(bet_name) NOT LIKE '%exact%'
                        AND LOWER(bet_name) NOT LIKE '%alternative%'
                        AND (value LIKE '%{line_str}%' OR bet_name LIKE '%{line_str}%')
                        {bm_filter}
                    """
                    result = conn.execute(text(sql_fb))
                    for row in result.fetchall():
                        value = row[0]
                        if 'over' in value.lower():
                            result_dict['Over'] = row[1]
                        elif 'under' in value.lower():
                            result_dict['Under'] = row[1]
            
            return result_dict
        except Exception as e:
            logger.error(f"Error obteniendo odds Over/Under: {e}")
            return {}
    
    def get_double_chance_odds(self, fixture_id: int) -> Dict[str, float]:
        """
        Obtiene cuotas de doble oportunidad.
        
        Returns:
            Dict con claves "1X", "X2", "12"
        """
        try:
            preferred_bm = self._get_preferred_bookmaker(fixture_id)
            bm_filter = ""
            if preferred_bm:
                safe_bm = preferred_bm.replace("'", "''")
                bm_filter = f"AND bookmaker_name = '{safe_bm}'"
            
            sql = f"""
                SELECT value, odd
                FROM odds
                WHERE fixture_id = {fixture_id}
                AND LOWER(bet_name) LIKE '%double%chance%'
                {bm_filter}
            """
            result_dict = {}
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result.fetchall():
                    value = row[0]
                    if 'home' in value.lower() or '1x' in value.lower():
                        result_dict['1X'] = row[1]
                    elif 'away' in value.lower() or 'x2' in value.lower():
                        result_dict['X2'] = row[1]
                    elif 'draw' not in value.lower() and '12' in value.lower():
                        result_dict['12'] = row[1]
            return result_dict
        except Exception as e:
            logger.error(f"Error obteniendo odds Double Chance: {e}")
            return {}
    
    def get_fixtures_with_odds(
        self,
        league_id: int = None,
        season: int = None,
        team_id: int = None,
        limit: int = 100
    ) -> List[FixtureWithOdds]:
        """Obtiene fixtures con sus cuotas organizadas (bookmaker preferido)."""
        fixtures = self.get_fixtures(
            league_id=league_id,
            season=season,
            team_id=team_id,
            with_odds_only=True,
            limit=limit
        )
        
        result = []
        for fixture in fixtures:
            preferred_bm = self._get_preferred_bookmaker(fixture.fixture_id)
            odds_data = self.get_odds_for_fixture(fixture.fixture_id)
            
            # Organizar odds por mercado, filtrando por bookmaker preferido
            organized_odds = {}
            for odd in odds_data:
                if preferred_bm and odd.bookmaker_name != preferred_bm:
                    continue
                if odd.bet_name not in organized_odds:
                    organized_odds[odd.bet_name] = {}
                organized_odds[odd.bet_name][odd.value] = odd.odd
            
            result.append(FixtureWithOdds(
                fixture=fixture,
                odds=organized_odds
            ))
        
        return result
    
    # =========================================================================
    # EstadÃ­sticas de Cobertura
    # =========================================================================
    
    def get_coverage_stats(self, league_id: int = None, season: int = None) -> List[CoverageStats]:
        """Obtiene estadÃ­sticas de cobertura de datos."""
        try:
            sql = """
                SELECT 
                    f.league_id,
                    COALESCE(l.name, 'Liga ' || f.league_id) as league_name,
                    f.league_season,
                    COUNT(DISTINCT f.id) as total_fixtures,
                    COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN f.id END) as fixtures_with_odds
                FROM fixtures f
                LEFT JOIN leagues l ON f.league_id = l.id
                LEFT JOIN odds o ON f.id = o.fixture_id
                WHERE f.status_long = 'Match Finished'
            """
            
            if league_id:
                sql += f" AND f.league_id = {league_id}"
            if season:
                sql += f" AND f.league_season = {season}"
            
            sql += " GROUP BY f.league_id, f.league_season ORDER BY f.league_season DESC, total_fixtures DESC"
            
            stats = []
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result.fetchall():
                    total = row[3]
                    with_odds = row[4]
                    coverage = (with_odds / total * 100) if total > 0 else 0
                    
                    stats.append(CoverageStats(
                        league_id=row[0],
                        league_name=row[1] or "Unknown",
                        season=row[2] or 0,
                        total_fixtures=total,
                        fixtures_with_odds=with_odds,
                        coverage_percent=coverage
                    ))
            
            return stats
            
        except Exception as e:
            logger.error(f"Error obteniendo estadÃ­sticas de cobertura: {e}")
            return []
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Obtiene estadÃ­sticas globales de la BD."""
        try:
            stats = {}
            
            with self._engine.connect() as conn:
                # Total fixtures
                result = conn.execute(text("SELECT COUNT(*) FROM fixtures WHERE status_long = 'Match Finished'"))
                stats['total_fixtures'] = result.scalar() or 0
                
                # Fixtures con odds
                result = conn.execute(text("""
                    SELECT COUNT(DISTINCT fixture_id) FROM odds
                """))
                stats['fixtures_with_odds'] = result.scalar() or 0
                
                # Total odds
                result = conn.execute(text("SELECT COUNT(*) FROM odds"))
                stats['total_odds'] = result.scalar() or 0
                
                # Ligas
                result = conn.execute(text("SELECT COUNT(DISTINCT league_id) FROM fixtures"))
                stats['total_leagues'] = result.scalar() or 0
                
                # Equipos
                result = conn.execute(text("SELECT COUNT(*) FROM teams"))
                stats['total_teams'] = result.scalar() or 0
                
                # Temporadas
                result = conn.execute(text("SELECT MIN(league_season), MAX(league_season) FROM fixtures"))
                row = result.fetchone()
                stats['min_season'] = row[0] if row else None
                stats['max_season'] = row[1] if row else None
                
                # Bookmakers
                result = conn.execute(text("SELECT COUNT(DISTINCT bookmaker_name) FROM odds"))
                stats['total_bookmakers'] = result.scalar() or 0
                
                # Cobertura
                if stats['total_fixtures'] > 0:
                    stats['coverage_percent'] = (stats['fixtures_with_odds'] / stats['total_fixtures']) * 100
                else:
                    stats['coverage_percent'] = 0
            
            return stats
            
        except Exception as e:
            logger.error(f"Error obteniendo estadÃ­sticas globales: {e}")
            return {}
    
    def get_timeline_data(self, league_id: int = None, season: int = None) -> List[Dict[str, Any]]:
        """Obtiene datos para grÃ¡fico de lÃ­nea de tiempo."""
        try:
            sql = """
                SELECT 
                    strftime('%Y-%m', f.date) as month,
                    COUNT(DISTINCT f.id) as fixtures,
                    COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN f.id END) as with_odds
                FROM fixtures f
                LEFT JOIN odds o ON f.id = o.fixture_id
                WHERE f.status_long = 'Match Finished'
                AND f.date IS NOT NULL
            """
            
            if league_id:
                sql += f" AND f.league_id = {league_id}"
            if season:
                sql += f" AND f.league_season = {season}"
            
            sql += " GROUP BY month ORDER BY month"
            
            data = []
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                for row in result.fetchall():
                    data.append({
                        'month': row[0],
                        'fixtures': row[1],
                        'with_odds': row[2],
                        'coverage': (row[2] / row[1] * 100) if row[1] > 0 else 0
                    })
            
            return data
            
        except Exception as e:
            logger.error(f"Error obteniendo datos de timeline: {e}")
            return []