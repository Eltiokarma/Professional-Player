# ui/odds_viewer/simulador/fan_simulator.py
# -*- coding: utf-8 -*-
"""
Motor de simulación del hincha.
Simula apuestas sistemáticas siguiendo a un equipo.
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from ..models.data_models import (
    SimulationConfig, BetType, DoubleChanceType, MatchResult,
    FixtureData, BetResult, TeamSimulationResult, LeagueSimulationResult
)
from ..models.database_queries import OddsQueryModel

logger = logging.getLogger(__name__)


class FanSimulator:
    """
    Simulador del hincha: calcula rentabilidad de apostar siempre por un equipo.
    
    Soporta:
    - Victoria (1X2): Apuesta a que el equipo gana
    - Doble Oportunidad: Apuesta a que el equipo gana o empata
    - Over/Under: Apuesta a cantidad de goles
    """
    
    def __init__(self, db_model: OddsQueryModel):
        """
        Inicializa el simulador.
        
        Args:
            db_model: Modelo de consultas a la BD
        """
        self.db = db_model
    
    def simulate_team(
        self,
        team_id: int,
        config: SimulationConfig
    ) -> TeamSimulationResult:
        """
        Simula apuestas para un equipo específico.
        
        Args:
            team_id: ID del equipo a simular
            config: Configuración de la simulación
            
        Returns:
            TeamSimulationResult con todas las apuestas y métricas
        """
        # Obtener info del equipo
        teams = self.db.get_teams(league_id=config.league_id, season=config.season)
        team_info = next((t for t in teams if t['id'] == team_id), None)
        team_name = team_info['name'] if team_info else f"Team {team_id}"
        
        # Obtener fixtures del equipo
        fixtures = self.db.get_fixtures(
            league_id=config.league_id,
            season=config.season,
            team_id=team_id,
            with_odds_only=True
        )
        
        if not fixtures:
            logger.warning(f"No se encontraron fixtures con odds para equipo {team_id}")
            return TeamSimulationResult(team_id=team_id, team_name=team_name)
        
        # Simular cada partido
        bets = []
        bankroll = config.initial_bankroll
        
        for fixture in fixtures:
            # Determinar si jugamos de local o visita
            is_home = fixture.home_team_id == team_id
            
            # Obtener stake según ubicación
            stake = config.home_stake if is_home else config.away_stake
            
            # Obtener cuota y determinar si ganó
            bet_result = self._process_bet(
                fixture=fixture,
                team_id=team_id,
                is_home=is_home,
                stake=stake,
                bankroll=bankroll,
                config=config
            )
            
            if bet_result:
                bankroll = bet_result.bankroll_after
                bets.append(bet_result)
        
        # Crear resultado
        result = TeamSimulationResult(
            team_id=team_id,
            team_name=team_name,
            bets=bets,
            initial_bankroll=config.initial_bankroll
        )
        
        # Calcular métricas
        result.calculate_metrics()
        
        return result
    
    def _process_bet(
        self,
        fixture: FixtureData,
        team_id: int,
        is_home: bool,
        stake: float,
        bankroll: float,
        config: SimulationConfig
    ) -> Optional[BetResult]:
        """
        Procesa una apuesta individual.
        
        Args:
            fixture: Datos del partido
            team_id: ID del equipo apostado
            is_home: Si el equipo juega de local
            stake: Monto apostado
            bankroll: Bankroll actual
            config: Configuración
            
        Returns:
            BetResult o None si no hay datos
        """
        # Obtener cuota según tipo de apuesta
        if config.bet_type == BetType.WIN:
            odd, bet_won = self._evaluate_win_bet(fixture, is_home)
        elif config.bet_type == BetType.DOUBLE_CHANCE:
            odd, bet_won = self._evaluate_double_chance_bet(fixture, is_home, config.double_chance_type)
        elif config.bet_type == BetType.OVER_UNDER:
            odd, bet_won = self._evaluate_over_under_bet(fixture, config.over_under_line, config.over_not_under)
        else:
            return None
        
        # Si no hay cuota, saltar
        if odd is None or odd <= 1.0:
            return None
        
        # Calcular profit/loss
        if bet_won:
            profit_loss = stake * (odd - 1)
        else:
            profit_loss = -stake
        
        new_bankroll = bankroll + profit_loss
        
        # Determinar nombres de equipos
        team_bet_on = fixture.home_team_name if is_home else fixture.away_team_name
        
        return BetResult(
            fixture_id=fixture.fixture_id,
            date=fixture.date,
            home_team=fixture.home_team_name,
            away_team=fixture.away_team_name,
            team_bet_on=team_bet_on,
            is_home=is_home,
            goals_home=fixture.goals_home or 0,
            goals_away=fixture.goals_away or 0,
            match_result=fixture.result,
            odd=odd,
            stake=stake,
            bet_type=config.bet_type,
            bet_won=bet_won,
            profit_loss=profit_loss,
            bankroll_after=new_bankroll
        )
    
    def _evaluate_win_bet(
        self,
        fixture: FixtureData,
        is_home: bool
    ) -> Tuple[Optional[float], bool]:
        """
        Evalúa apuesta de victoria (1X2).
        
        Returns:
            (cuota, ganó)
        """
        odds = self.db.get_1x2_odds(fixture.fixture_id)
        
        if not odds:
            return None, False
        
        # Obtener cuota según ubicación
        if is_home:
            odd = odds.get('Home')
            bet_won = fixture.result == MatchResult.HOME_WIN
        else:
            odd = odds.get('Away')
            bet_won = fixture.result == MatchResult.AWAY_WIN
        
        return odd, bet_won
    
    def _evaluate_double_chance_bet(
        self,
        fixture: FixtureData,
        is_home: bool,
        dc_type: DoubleChanceType
    ) -> Tuple[Optional[float], bool]:
        """
        Evalúa apuesta de doble oportunidad.
        
        Si el hincha va de local, apuesta a 1X (gana o empata).
        Si va de visita, apuesta a X2 (empata o gana).
        
        Returns:
            (cuota, ganó)
        """
        # Intentar obtener odds de doble oportunidad
        dc_odds = self.db.get_double_chance_odds(fixture.fixture_id)
        
        # Si no hay odds de DC, calcular desde 1X2
        if not dc_odds:
            x1x2_odds = self.db.get_1x2_odds(fixture.fixture_id)
            if not x1x2_odds:
                return None, False
            
            # Aproximar cuota de DC desde 1X2 (simplificado)
            # DC 1X ≈ 1 / (1/odd_home + 1/odd_draw)
            home_odd = x1x2_odds.get('Home', 0)
            draw_odd = x1x2_odds.get('Draw', 0)
            away_odd = x1x2_odds.get('Away', 0)
            
            if home_odd > 0 and draw_odd > 0:
                dc_odds['1X'] = 1 / (1/home_odd + 1/draw_odd)
            if away_odd > 0 and draw_odd > 0:
                dc_odds['X2'] = 1 / (1/away_odd + 1/draw_odd)
            if home_odd > 0 and away_odd > 0:
                dc_odds['12'] = 1 / (1/home_odd + 1/away_odd)
        
        # Determinar qué tipo de DC usar
        if is_home:
            # Hincha local: 1X (gana o empata)
            odd = dc_odds.get('1X')
            bet_won = fixture.result in [MatchResult.HOME_WIN, MatchResult.DRAW]
        else:
            # Hincha visitante: X2 (empata o gana)
            odd = dc_odds.get('X2')
            bet_won = fixture.result in [MatchResult.AWAY_WIN, MatchResult.DRAW]
        
        return odd, bet_won
    
    def _evaluate_over_under_bet(
        self,
        fixture: FixtureData,
        line: float,
        is_over: bool
    ) -> Tuple[Optional[float], bool]:
        """
        Evalúa apuesta Over/Under.
        
        Returns:
            (cuota, ganó)
        """
        odds = self.db.get_over_under_odds(fixture.fixture_id, line)
        
        if not odds:
            return None, False
        
        total_goals = fixture.total_goals
        if total_goals is None:
            return None, False
        
        if is_over:
            odd = odds.get('Over')
            bet_won = total_goals > line
        else:
            odd = odds.get('Under')
            bet_won = total_goals < line
        
        return odd, bet_won
    
    def simulate_league(
        self,
        config: SimulationConfig
    ) -> LeagueSimulationResult:
        """
        Simula apuestas para todos los equipos de una liga.
        
        Args:
            config: Configuración de la simulación
            
        Returns:
            LeagueSimulationResult con resultados de todos los equipos
        """
        # Obtener nombre de la liga
        leagues = self.db.get_leagues()
        league_info = next((l for l in leagues if l['id'] == config.league_id), None)
        league_name = league_info['name'] if league_info else f"Liga {config.league_id}"
        
        # Obtener todos los equipos
        if config.team_ids:
            team_ids = config.team_ids
        else:
            teams = self.db.get_teams(
                league_id=config.league_id,
                season=config.season
            )
            team_ids = [t['id'] for t in teams]
        
        logger.info(f"Simulando {len(team_ids)} equipos de {league_name}")
        
        # Simular cada equipo
        team_results = []
        for i, team_id in enumerate(team_ids):
            logger.debug(f"Simulando equipo {i+1}/{len(team_ids)}: {team_id}")
            result = self.simulate_team(team_id, config)
            if result.total_bets > 0:  # Solo incluir si tiene apuestas
                team_results.append(result)
        
        # Crear resultado de liga
        league_result = LeagueSimulationResult(
            config=config,
            league_name=league_name,
            team_results=team_results
        )
        
        # Calcular métricas de liga
        league_result.calculate_league_metrics()
        
        return league_result
    
    def get_insights(self, league_result: LeagueSimulationResult) -> List[str]:
        """
        Genera insights automáticos de la simulación.
        
        Args:
            league_result: Resultado de la simulación de liga
            
        Returns:
            Lista de insights en formato texto
        """
        insights = []
        
        if not league_result.team_results:
            return ["No hay datos suficientes para generar insights."]
        
        # Equipos rentables
        profitable = league_result.profitable_teams
        total = league_result.total_teams
        profitable_pct = (profitable / total * 100) if total > 0 else 0
        
        if profitable_pct >= 50:
            insights.append(
                f"✅ {profitable}/{total} equipos ({profitable_pct:.0f}%) son rentables para el hincha"
            )
        else:
            insights.append(
                f"⚠️ Solo {profitable}/{total} equipos ({profitable_pct:.0f}%) son rentables"
            )
        
        # Mejor equipo
        ranking = league_result.get_ranking(by="roi")
        if ranking:
            best = ranking[0]
            worst = ranking[-1]
            insights.append(
                f"🥇 Mejor equipo: {best.team_name} (ROI: {best.roi:+.1f}%)"
            )
            insights.append(
                f"📉 Peor equipo: {worst.team_name} (ROI: {worst.roi:+.1f}%)"
            )
        
        # Local vs Visita
        if league_result.home_total_roi > league_result.away_total_roi + 5:
            insights.append(
                f"🏠 Apostar a LOCAL es más rentable ({league_result.home_total_roi:+.1f}% vs {league_result.away_total_roi:+.1f}%)"
            )
        elif league_result.away_total_roi > league_result.home_total_roi + 5:
            insights.append(
                f"🚌 Apostar a VISITA es más rentable ({league_result.away_total_roi:+.1f}% vs {league_result.home_total_roi:+.1f}%)"
            )
        else:
            insights.append(
                f"⚖️ Local y Visita tienen rentabilidad similar (Local: {league_result.home_total_roi:+.1f}%, Visita: {league_result.away_total_roi:+.1f}%)"
            )
        
        # ROI promedio
        if league_result.avg_roi > 0:
            insights.append(
                f"📈 ROI promedio de la liga: {league_result.avg_roi:+.1f}% (positivo)"
            )
        else:
            insights.append(
                f"📉 ROI promedio de la liga: {league_result.avg_roi:+.1f}% (negativo)"
            )
        
        # Equipos con alto win rate pero ROI negativo (cuotas bajas)
        trap_teams = [
            t for t in ranking 
            if t.win_rate > 60 and t.roi < 0
        ]
        if trap_teams:
            names = ", ".join([t.team_name for t in trap_teams[:3]])
            insights.append(
                f"⚠️ Cuidado: {names} tienen alto % de aciertos pero cuotas bajas (ROI negativo)"
            )
        
        # Equipos con valor (ROI alto y cuotas altas)
        value_teams = [
            t for t in ranking
            if t.roi > 10 and t.avg_odd > 2.0
        ]
        if value_teams:
            names = ", ".join([t.team_name for t in value_teams[:3]])
            insights.append(
                f"💎 Value bets: {names} tienen ROI alto con cuotas promedio > 2.0"
            )
        
        return insights
    
    def analyze_monthly_performance(
        self,
        team_result: TeamSimulationResult
    ) -> Dict[str, Dict[str, float]]:
        """
        Analiza rendimiento mensual de un equipo.
        
        Returns:
            Dict con métricas por mes
        """
        monthly = {}
        
        for bet in team_result.bets:
            month_key = bet.date.strftime("%Y-%m")
            
            if month_key not in monthly:
                monthly[month_key] = {
                    'bets': 0,
                    'wins': 0,
                    'staked': 0,
                    'profit': 0
                }
            
            monthly[month_key]['bets'] += 1
            if bet.bet_won:
                monthly[month_key]['wins'] += 1
            monthly[month_key]['staked'] += bet.stake
            monthly[month_key]['profit'] += bet.profit_loss
        
        # Calcular ROI por mes
        for month in monthly:
            staked = monthly[month]['staked']
            if staked > 0:
                monthly[month]['roi'] = (monthly[month]['profit'] / staked) * 100
            else:
                monthly[month]['roi'] = 0
        
        return monthly
