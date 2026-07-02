# src/data/api_database_manager.py
"""
Funciones de guardado para datos de API-Football.
Extiende database_manager.py con operaciones de escritura.
"""

import logging
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import and_

from data.database_manager import ORIG_ENGINE, SessionOrig
from data.data_models.teams import Team
from data.data_models.fixtures import Fixture
from data.data_models.players import Player
from data.data_models.player_statistics import PlayerStatistic
from data.data_models.statistics import TeamStatistics
from data.data_models.odds import Odd
from data.data_models.leagues import League
from data.base import Base

logger = logging.getLogger(__name__)


# Crear todas las tablas si no existen
def init_all_tables():
    """Crea todas las tablas necesarias en sad.db."""
    # Importar todos los modelos para que se registren en Base.metadata
    from data.data_models import teams, fixtures, players, player_statistics, statistics, odds, leagues
    Base.metadata.create_all(ORIG_ENGINE)
    logger.info("Tablas creadas/verificadas en sad.db")


# =============================================================================
# SAVE FIXTURES
# =============================================================================

def save_fixtures(fixtures_data: List[Tuple[Fixture, Team, Team]]) -> int:
    """
    Guarda fixtures y equipos en la base de datos.
    Usa merge para actualizar si ya existen.
    
    Args:
        fixtures_data: Lista de tuplas (Fixture, home_team, away_team)
        
    Returns:
        NÃºmero de fixtures guardados
    """
    session = SessionOrig()
    count = 0
    
    try:
        for fixture, home_team, away_team in fixtures_data:
            # Merge teams primero
            if home_team and home_team.id:
                session.merge(home_team)
            if away_team and away_team.id:
                session.merge(away_team)
            
            # Merge fixture
            if fixture and fixture.id:
                session.merge(fixture)
                count += 1
        
        session.commit()
        logger.info(f"Guardados {count} fixtures")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error guardando fixtures: {e}")
        raise
    finally:
        session.close()
    
    return count


# =============================================================================
# SAVE PLAYERS & STATISTICS
# =============================================================================

def save_players_and_statistics(
    players_data: List[Tuple[Player, Team, List[PlayerStatistic]]]
) -> Tuple[int, int]:
    """
    Guarda jugadores y sus estadÃ­sticas.
    
    Args:
        players_data: Lista de tuplas (Player, Team, [PlayerStatistic, ...])
        
    Returns:
        Tupla (jugadores guardados, estadÃ­sticas guardadas)
    """
    session = SessionOrig()
    players_count = 0
    stats_count = 0
    
    try:
        for player, team, stats_list in players_data:
            # Merge team
            if team and team.id:
                session.merge(team)
            
            # Merge player
            if player and player.id:
                session.merge(player)
                players_count += 1
            
            # Add stats (no merge porque puede haber mÃºltiples por jugador)
            for stat in stats_list:
                # Verificar si ya existe esta estadÃ­stica
                existing = session.query(PlayerStatistic).filter(
                    and_(
                        PlayerStatistic.player_id == stat.player_id,
                        PlayerStatistic.team_id == stat.team_id,
                        PlayerStatistic.league_id == stat.league_id,
                        PlayerStatistic.season == stat.season
                    )
                ).first()
                
                if existing:
                    # Actualizar existente
                    for key, value in stat.__dict__.items():
                        if not key.startswith('_') and key != 'id':
                            setattr(existing, key, value)
                else:
                    session.add(stat)
                
                stats_count += 1
        
        session.commit()
        logger.info(f"Guardados {players_count} jugadores y {stats_count} estadÃ­sticas")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error guardando jugadores: {e}")
        raise
    finally:
        session.close()
    
    return players_count, stats_count


# =============================================================================
# SAVE TEAM STATISTICS
# =============================================================================

def save_team_statistics(stats_data: Tuple[Team, TeamStatistics]) -> bool:
    """
    Guarda estadÃ­sticas de equipo.
    
    Args:
        stats_data: Tupla (Team, TeamStatistics)
        
    Returns:
        True si se guardÃ³ correctamente
    """
    if not stats_data:
        return False
    
    team, team_stats = stats_data
    session = SessionOrig()
    
    try:
        # Merge team
        if team and team.id:
            session.merge(team)
        
        # Verificar si ya existe esta estadÃ­stica
        if team_stats:
            existing = session.query(TeamStatistics).filter(
                and_(
                    TeamStatistics.team_id == team_stats.team_id,
                    TeamStatistics.league_id == team_stats.league_id,
                    TeamStatistics.season == team_stats.season
                )
            ).first()
            
            if existing:
                # Actualizar existente
                for key, value in team_stats.__dict__.items():
                    if not key.startswith('_') and key != 'id':
                        setattr(existing, key, value)
            else:
                session.add(team_stats)
        
        session.commit()
        logger.info(f"Guardadas estadÃ­sticas para equipo {team.name if team else 'unknown'}")
        return True
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error guardando team statistics: {e}")
        return False
    finally:
        session.close()


# =============================================================================
# SAVE ODDS
# =============================================================================

def save_odds(odds_list: List[Odd]) -> int:
    """
    Guarda odds en la base de datos con upsert inteligente.
    
    Optimización: un solo SELECT por fixture_id para cargar existentes,
    luego batch insert/update con un solo commit.
    
    Args:
        odds_list: Lista de objetos Odd
        
    Returns:
        Número de odds guardados/actualizados
    """
    if not odds_list:
        return 0
    
    session = SessionOrig()
    count = 0
    
    try:
        # Agrupar odds nuevas por fixture_id
        from collections import defaultdict
        by_fixture = defaultdict(list)
        for odd in odds_list:
            by_fixture[odd.fixture_id].append(odd)
        
        for fixture_id, new_odds in by_fixture.items():
            # UN solo SELECT: traer todas las odds existentes de este fixture
            existing_odds = session.query(Odd).filter(
                Odd.fixture_id == fixture_id
            ).all()
            
            # Construir lookup dict: (bookmaker_id, bet_id, value) -> Odd existente
            existing_map = {}
            for ex in existing_odds:
                key = (ex.bookmaker_id, ex.bet_id, ex.value)
                existing_map[key] = ex
            
            # Procesar nuevas odds contra el mapa
            for odd in new_odds:
                key = (odd.bookmaker_id, odd.bet_id, odd.value)
                existing = existing_map.get(key)
                
                if existing:
                    # Update solo si cambió el valor
                    if existing.odd != odd.odd:
                        existing.odd = odd.odd
                else:
                    session.add(odd)
                
                count += 1
        
        session.commit()
        logger.info(f"Guardados {count} odds ({len(by_fixture)} fixtures)")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error guardando odds: {e}")
        raise
    finally:
        session.close()
    
    return count



# =============================================================================
# SAVE LEAGUES
# =============================================================================

def save_leagues(leagues_list: List[League]) -> int:
    """
    Guarda ligas en la base de datos.
    
    Args:
        leagues_list: Lista de objetos League
        
    Returns:
        NÃºmero de ligas guardadas
    """
    if not leagues_list:
        return 0
    
    session = SessionOrig()
    count = 0
    
    try:
        for league in leagues_list:
            if league and league.id:
                session.merge(league)
                count += 1
        
        session.commit()
        logger.info(f"Guardadas {count} ligas")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error guardando ligas: {e}")
        raise
    finally:
        session.close()
    
    return count


# =============================================================================
# QUERY HELPERS
# =============================================================================

def get_all_fixtures(
    league_id: int = None,
    status: str = None,
    limit: int = None
) -> List[Fixture]:
    """
    Obtiene fixtures de la base de datos.
    
    Args:
        league_id: Filtrar por liga
        status: Filtrar por estado (FT, NS, etc.)
        limit: LÃ­mite de resultados
        
    Returns:
        Lista de fixtures
    """
    session = SessionOrig()
    
    try:
        query = session.query(Fixture)
        
        if league_id:
            query = query.filter(Fixture.league_id == league_id)
        if status:
            query = query.filter(Fixture.status_short == status)
        
        query = query.order_by(Fixture.date.desc())
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
        
    finally:
        session.close()


def get_fixtures_by_ids(fixture_ids: List[int]) -> List[Fixture]:
    """
    Obtiene fixtures por lista de IDs.
    
    Args:
        fixture_ids: Lista de IDs
        
    Returns:
        Lista de fixtures
    """
    session = SessionOrig()
    
    try:
        return session.query(Fixture).filter(
            Fixture.id.in_(fixture_ids)
        ).all()
    finally:
        session.close()


def get_fixtures_by_time_range_and_leagues(
    from_date: str,
    to_date: str,
    league_ids: List[int] = None
) -> List[Fixture]:
    """
    Obtiene fixtures en un rango de fechas y ligas.
    
    Args:
        from_date: Fecha inicio (YYYY-MM-DD)
        to_date: Fecha fin (YYYY-MM-DD)
        league_ids: Lista de IDs de ligas
        
    Returns:
        Lista de fixtures
    """
    from datetime import datetime
    
    session = SessionOrig()
    
    try:
        query = session.query(Fixture)
        
        # Filtrar por fechas
        from_dt = datetime.strptime(from_date, '%Y-%m-%d')
        to_dt = datetime.strptime(to_date, '%Y-%m-%d')
        
        query = query.filter(
            and_(
                Fixture.date >= from_dt,
                Fixture.date <= to_dt
            )
        )
        
        # Filtrar por ligas
        if league_ids:
            query = query.filter(Fixture.league_id.in_(league_ids))
        
        return query.order_by(Fixture.date).all()
        
    finally:
        session.close()


def has_odds_extracted(fixture_id: int) -> bool:
    """
    Verifica si un fixture ya tiene odds extraÃ­dos.
    
    Args:
        fixture_id: ID del fixture
        
    Returns:
        True si tiene odds
    """
    session = SessionOrig()
    
    try:
        count = session.query(Odd).filter(
            Odd.fixture_id == fixture_id
        ).count()
        return count > 0
    finally:
        session.close()


def get_teams_by_league(league_id: int, season: int = None) -> List[Team]:
    """
    Obtiene equipos de una liga.
    
    Args:
        league_id: ID de la liga
        season: Temporada
        
    Returns:
        Lista de equipos
    """
    session = SessionOrig()
    
    try:
        # Obtener equipos que han jugado en esta liga
        query = session.query(Team).join(
            Fixture,
            (Team.id == Fixture.home_team_id) | (Team.id == Fixture.away_team_id)
        ).filter(
            Fixture.league_id == league_id
        )
        
        if season:
            query = query.filter(Fixture.league_season == season)
        
        return query.distinct().all()
        
    finally:
        session.close()