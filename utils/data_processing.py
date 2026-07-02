# src/utils/data_processing.py
"""
Procesadores de datos de API-Football.
Convierte respuestas JSON de la API a objetos ORM para almacenamiento.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dateutil import parser as date_parser

from data.data_models.teams import Team
from data.data_models.fixtures import Fixture
from data.data_models.players import Player
from data.data_models.player_statistics import PlayerStatistic
from data.data_models.statistics import TeamStatistics
from data.data_models.odds import Odd
from data.data_models.leagues import League

logger = logging.getLogger(__name__)


# =============================================================================
# FIXTURES
# =============================================================================

def process_fixtures(fixtures_data: List[Dict]) -> List[Tuple[Fixture, Team, Team]]:
    """
    Procesa fixtures desde la respuesta de la API.
    
    Args:
        fixtures_data: Lista de fixtures de la API
        
    Returns:
        Lista de tuplas (Fixture, home_team, away_team)
    """
    results = []
    
    for fixture_data in fixtures_data:
        try:
            # Extraer información del fixture
            fixture_info = fixture_data.get('fixture', {})
            league_info = fixture_data.get('league', {})
            teams_info = fixture_data.get('teams', {})
            goals_info = fixture_data.get('goals', {})
            score_info = fixture_data.get('score', {})
            
            # Parsear fecha
            date_str = fixture_info.get('date')
            fixture_date = None
            if date_str:
                try:
                    fixture_date = date_parser.isoparse(date_str)
                except Exception:
                    fixture_date = None
            
            # Crear equipos
            home_team_data = teams_info.get('home', {})
            away_team_data = teams_info.get('away', {})
            
            home_team = Team(
                id=home_team_data.get('id'),
                name=home_team_data.get('name'),
                logo=home_team_data.get('logo')
            )
            
            away_team = Team(
                id=away_team_data.get('id'),
                name=away_team_data.get('name'),
                logo=away_team_data.get('logo')
            )
            
            # Venue
            venue_info = fixture_info.get('venue', {})
            
            # Status
            status_info = fixture_info.get('status', {})
            
            # Scores por período
            halftime = score_info.get('halftime', {})
            fulltime = score_info.get('fulltime', {})
            extratime = score_info.get('extratime', {})
            penalty = score_info.get('penalty', {})
            
            # Crear fixture
            fixture = Fixture(
                id=fixture_info.get('id'),
                referee=fixture_info.get('referee'),
                timezone=fixture_info.get('timezone'),
                date=fixture_date,
                timestamp=fixture_info.get('timestamp'),
                first_half_start=fixture_info.get('periods', {}).get('first'),
                second_half_start=fixture_info.get('periods', {}).get('second'),
                
                # Venue
                venue_id=venue_info.get('id'),
                venue_name=venue_info.get('name'),
                venue_city=venue_info.get('city'),
                
                # Status
                status_long=status_info.get('long'),
                status_short=status_info.get('short'),
                elapsed=status_info.get('elapsed'),
                
                # League
                league_id=league_info.get('id'),
                league_season=league_info.get('season'),
                league_round=league_info.get('round'),
                
                # Teams
                home_team_id=home_team_data.get('id'),
                away_team_id=away_team_data.get('id'),
                
                # Goals
                goals_home=goals_info.get('home'),
                goals_away=goals_info.get('away'),
                
                # Scores por período
                halftime_home=halftime.get('home'),
                halftime_away=halftime.get('away'),
                fulltime_home=fulltime.get('home'),
                fulltime_away=fulltime.get('away'),
                extratime_home=extratime.get('home'),
                extratime_away=extratime.get('away'),
                penalty_home=penalty.get('home'),
                penalty_away=penalty.get('away'),
            )
            
            results.append((fixture, home_team, away_team))
            
        except Exception as e:
            logger.error(f"Error procesando fixture: {e}")
            continue
    
    logger.info(f"Procesados {len(results)} fixtures")
    return results


# =============================================================================
# PLAYERS & STATISTICS
# =============================================================================

def process_players_stats(
    players_data: List[Dict]
) -> List[Tuple[Player, Team, List[PlayerStatistic]]]:
    """
    Procesa jugadores y sus estadísticas desde la respuesta de la API.
    
    Args:
        players_data: Lista de jugadores de la API
        
    Returns:
        Lista de tuplas (Player, Team, [PlayerStatistic, ...])
    """
    results = []
    
    for player_data in players_data:
        try:
            # Información del jugador
            player_info = player_data.get('player', {})
            statistics = player_data.get('statistics', [])
            
            # Parsear fecha de nacimiento
            birth_info = player_info.get('birth', {})
            
            # Crear jugador
            player = Player(
                id=player_info.get('id'),
                name=player_info.get('name'),
                firstname=player_info.get('firstname'),
                lastname=player_info.get('lastname'),
                age=player_info.get('age'),
                birth_date=birth_info.get('date'),
                birth_place=birth_info.get('place'),
                nationality=player_info.get('nationality'),
                height=player_info.get('height'),
                weight=player_info.get('weight'),
                injured=player_info.get('injured'),
                photo=player_info.get('photo'),
            )
            
            # Procesar estadísticas por temporada/liga
            player_stats_list = []
            team = None
            
            for stat in statistics:
                team_info = stat.get('team', {})
                league_info = stat.get('league', {})
                games = stat.get('games', {})
                substitutes = stat.get('substitutes', {})
                shots = stat.get('shots', {})
                goals = stat.get('goals', {})
                passes = stat.get('passes', {})
                tackles = stat.get('tackles', {})
                duels = stat.get('duels', {})
                dribbles = stat.get('dribbles', {})
                fouls = stat.get('fouls', {})
                cards = stat.get('cards', {})
                penalty = stat.get('penalty', {})
                
                # Crear equipo
                if team_info.get('id'):
                    team = Team(
                        id=team_info.get('id'),
                        name=team_info.get('name'),
                        logo=team_info.get('logo')
                    )
                    player.team_id = team.id
                
                # Crear estadística
                player_stat = PlayerStatistic(
                    player_id=player.id,
                    team_id=team_info.get('id'),
                    league_id=league_info.get('id'),
                    season=league_info.get('season'),
                    
                    # Games
                    games_appearences=games.get('appearences'),
                    games_lineups=games.get('lineups'),
                    games_minutes=games.get('minutes'),
                    games_number=games.get('number'),
                    games_position=games.get('position'),
                    games_rating=_safe_float(games.get('rating')),
                    games_captain=games.get('captain'),
                    
                    # Substitutes
                    substitutes_in=substitutes.get('in'),
                    substitutes_out=substitutes.get('out'),
                    substitutes_bench=substitutes.get('bench'),
                    
                    # Shots
                    shots_total=shots.get('total'),
                    shots_on=shots.get('on'),
                    
                    # Goals
                    goals_total=goals.get('total'),
                    goals_conceded=goals.get('conceded'),
                    goals_assists=goals.get('assists'),
                    goals_saves=goals.get('saves'),
                    
                    # Passes
                    passes_total=passes.get('total'),
                    passes_key=passes.get('key'),
                    passes_accuracy=passes.get('accuracy'),
                    
                    # Tackles
                    tackles_total=tackles.get('total'),
                    tackles_blocks=tackles.get('blocks'),
                    tackles_interceptions=tackles.get('interceptions'),
                    
                    # Duels
                    duels_total=duels.get('total'),
                    duels_won=duels.get('won'),
                    
                    # Dribbles
                    dribbles_attempts=dribbles.get('attempts'),
                    dribbles_success=dribbles.get('success'),
                    dribbles_past=dribbles.get('past'),
                    
                    # Fouls
                    fouls_drawn=fouls.get('drawn'),
                    fouls_committed=fouls.get('committed'),
                    
                    # Cards
                    cards_yellow=cards.get('yellow'),
                    cards_yellowred=cards.get('yellowred'),
                    cards_red=cards.get('red'),
                    
                    # Penalty
                    penalty_won=penalty.get('won'),
                    penalty_committed=penalty.get('commited'),  # API usa 'commited' (typo)
                    penalty_scored=penalty.get('scored'),
                    penalty_missed=penalty.get('missed'),
                    penalty_saved=penalty.get('saved'),
                )
                
                player_stats_list.append(player_stat)
            
            if team:
                results.append((player, team, player_stats_list))
                
        except Exception as e:
            logger.error(f"Error procesando jugador: {e}")
            continue
    
    logger.info(f"Procesados {len(results)} jugadores")
    return results


# =============================================================================
# TEAM STATISTICS
# =============================================================================

def process_team_statistics(stats_data: Dict) -> Optional[Tuple[Team, TeamStatistics]]:
    """
    Procesa estadísticas agregadas de un equipo.
    
    Args:
        stats_data: Respuesta de la API para team statistics
        
    Returns:
        Tupla (Team, TeamStatistics) o None
    """
    try:
        if not stats_data:
            return None
        
        team_info = stats_data.get('team', {})
        league_info = stats_data.get('league', {})
        fixtures_info = stats_data.get('fixtures', {})
        goals_info = stats_data.get('goals', {})
        clean_sheet = stats_data.get('clean_sheet', {})
        failed_to_score = stats_data.get('failed_to_score', {})
        
        # Crear equipo
        team = Team(
            id=team_info.get('id'),
            name=team_info.get('name'),
            logo=team_info.get('logo')
        )
        
        # Extraer fixtures
        played = fixtures_info.get('played', {})
        wins = fixtures_info.get('wins', {})
        draws = fixtures_info.get('draws', {})
        loses = fixtures_info.get('loses', {})
        
        # Extraer goles
        goals_for = goals_info.get('for', {}).get('total', {})
        goals_against = goals_info.get('against', {}).get('total', {})
        
        # Crear estadísticas
        team_stats = TeamStatistics(
            team_id=team.id,
            league_id=league_info.get('id'),
            season=league_info.get('season'),
            
            form=stats_data.get('form'),
            
            # Partidos
            played_home=played.get('home'),
            played_away=played.get('away'),
            played_total=played.get('total'),
            
            # Victorias
            wins_home=wins.get('home'),
            wins_away=wins.get('away'),
            wins_total=wins.get('total'),
            
            # Empates
            draws_home=draws.get('home'),
            draws_away=draws.get('away'),
            draws_total=draws.get('total'),
            
            # Derrotas
            loses_home=loses.get('home'),
            loses_away=loses.get('away'),
            loses_total=loses.get('total'),
            
            # Goles a favor
            goals_for_home=goals_for.get('home'),
            goals_for_away=goals_for.get('away'),
            goals_for_total=goals_for.get('total'),
            
            # Goles en contra
            goals_against_home=goals_against.get('home'),
            goals_against_away=goals_against.get('away'),
            goals_against_total=goals_against.get('total'),
            
            # Clean sheets
            clean_sheet_home=clean_sheet.get('home'),
            clean_sheet_away=clean_sheet.get('away'),
            clean_sheet_total=clean_sheet.get('total'),
            
            # Failed to score
            failed_to_score_home=failed_to_score.get('home'),
            failed_to_score_away=failed_to_score.get('away'),
            failed_to_score_total=failed_to_score.get('total'),
        )
        
        logger.info(f"Procesadas estadísticas para equipo {team.name}")
        return (team, team_stats)
        
    except Exception as e:
        logger.error(f"Error procesando team statistics: {e}")
        return None


# =============================================================================
# ODDS
# =============================================================================

def process_odds(odds_data: List[Dict], fixture_id: int) -> List[Odd]:
    """
    Procesa odds desde la respuesta de la API.
    
    Args:
        odds_data: Lista de odds de la API
        fixture_id: ID del fixture
        
    Returns:
        Lista de objetos Odd
    """
    results = []
    
    for odds_response in odds_data:
        try:
            league_info = odds_response.get('league', {})
            bookmakers = odds_response.get('bookmakers', [])
            
            for bookmaker in bookmakers:
                bookmaker_id = bookmaker.get('id')
                bookmaker_name = bookmaker.get('name')
                
                bets = bookmaker.get('bets', [])
                
                for bet in bets:
                    bet_id = bet.get('id')
                    bet_name = bet.get('name')
                    
                    values = bet.get('values', [])
                    
                    for value in values:
                        odd_value = value.get('odd')
                        
                        # Convertir odd a float
                        try:
                            odd_float = float(odd_value) if odd_value else None
                        except (ValueError, TypeError):
                            odd_float = None
                        
                        odd = Odd(
                            fixture_id=fixture_id,
                            league_id=league_info.get('id'),
                            bookmaker_id=bookmaker_id,
                            bookmaker_name=bookmaker_name,
                            bet_id=bet_id,
                            bet_name=bet_name,
                            value=value.get('value'),
                            odd=odd_float
                        )
                        
                        results.append(odd)
                        
        except Exception as e:
            logger.error(f"Error procesando odds: {e}")
            continue
    
    logger.info(f"Procesados {len(results)} odds para fixture {fixture_id}")
    return results


# =============================================================================
# LEAGUES
# =============================================================================

def process_leagues(leagues_data: List[Dict]) -> List[League]:
    """
    Procesa ligas desde la respuesta de la API.
    
    Args:
        leagues_data: Lista de ligas de la API
        
    Returns:
        Lista de objetos League
    """
    results = []
    
    for league_data in leagues_data:
        try:
            league_info = league_data.get('league', {})
            country_info = league_data.get('country', {})
            seasons = league_data.get('seasons', [])
            
            # Tomar la temporada más reciente
            current_season = None
            if seasons:
                current_season = max(seasons, key=lambda s: s.get('year', 0)).get('year')
            
            league = League(
                id=league_info.get('id'),
                name=league_info.get('name'),
                country=country_info.get('name'),
                logo=league_info.get('logo'),
                flag=country_info.get('flag'),
                season=current_season
            )
            
            results.append(league)
            
        except Exception as e:
            logger.error(f"Error procesando liga: {e}")
            continue
    
    logger.info(f"Procesadas {len(results)} ligas")
    return results


# =============================================================================
# HELPERS
# =============================================================================

def _safe_float(value: Any) -> Optional[float]:
    """Convierte un valor a float de forma segura."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Convierte un valor a int de forma segura."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None