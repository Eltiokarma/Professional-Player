# ui/odds_viewer/models/data_models.py
# -*- coding: utf-8 -*-
"""
Modelos de datos para el sistema de odds y simulador.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class BetType(Enum):
    """Tipos de apuesta soportados."""
    WIN = "win"                     # Victoria (1X2)
    DOUBLE_CHANCE = "double_chance" # Doble oportunidad
    OVER_UNDER = "over_under"       # Over/Under goles


class DoubleChanceType(Enum):
    """Tipos de doble oportunidad."""
    HOME_DRAW = "1X"    # Local o Empate
    AWAY_DRAW = "X2"    # Visita o Empate
    HOME_AWAY = "12"    # Local o Visita (no empate)


class MatchResult(Enum):
    """Resultado del partido."""
    HOME_WIN = "H"
    DRAW = "D"
    AWAY_WIN = "A"


@dataclass
class SimulationConfig:
    """Configuración de una simulación."""
    league_id: int
    season: int
    team_ids: Optional[List[int]] = None  # None = toda la liga
    bet_type: BetType = BetType.WIN
    double_chance_type: DoubleChanceType = DoubleChanceType.HOME_DRAW
    over_under_line: float = 2.5
    over_not_under: bool = True           # True = Over, False = Under
    home_stake: float = 10.0
    away_stake: float = 1.0
    initial_bankroll: float = 100.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'league_id': self.league_id,
            'season': self.season,
            'team_ids': self.team_ids,
            'bet_type': self.bet_type.value,
            'double_chance_type': self.double_chance_type.value,
            'over_under_line': self.over_under_line,
            'over_not_under': self.over_not_under,
            'home_stake': self.home_stake,
            'away_stake': self.away_stake,
            'initial_bankroll': self.initial_bankroll,
        }


@dataclass
class FixtureData:
    """Datos de un partido."""
    fixture_id: int
    date: datetime
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str
    goals_home: Optional[int]
    goals_away: Optional[int]
    league_id: int
    league_name: str
    season: int
    status: str
    
    @property
    def result(self) -> Optional[MatchResult]:
        """Determina el resultado del partido."""
        if self.goals_home is None or self.goals_away is None:
            return None
        if self.goals_home > self.goals_away:
            return MatchResult.HOME_WIN
        elif self.goals_home < self.goals_away:
            return MatchResult.AWAY_WIN
        return MatchResult.DRAW
    
    @property
    def total_goals(self) -> Optional[int]:
        """Total de goles en el partido."""
        if self.goals_home is None or self.goals_away is None:
            return None
        return self.goals_home + self.goals_away
    
    @property
    def score_str(self) -> str:
        """Marcador como string."""
        if self.goals_home is None or self.goals_away is None:
            return "vs"
        return f"{self.goals_home} - {self.goals_away}"


@dataclass
class OddData:
    """Datos de una cuota."""
    fixture_id: int
    bookmaker_id: int
    bookmaker_name: str
    bet_id: int
    bet_name: str
    value: str          # "Home", "Draw", "Away", "Over 2.5", etc.
    odd: float
    
    def is_match_winner(self) -> bool:
        return self.bet_name and 'winner' in self.bet_name.lower()
    
    def is_over_under(self) -> bool:
        return self.bet_name and 'over' in self.bet_name.lower()
    
    def is_btts(self) -> bool:
        return self.bet_name and ('both' in self.bet_name.lower() or 'btts' in self.bet_name.lower())


@dataclass
class BetResult:
    """Resultado de una apuesta individual."""
    fixture_id: int
    date: datetime
    home_team: str
    away_team: str
    team_bet_on: str        # Equipo por el que se apostó
    is_home: bool           # El equipo apostado jugó de local?
    goals_home: int
    goals_away: int
    match_result: MatchResult
    odd: float
    stake: float
    bet_type: BetType
    bet_won: bool
    profit_loss: float
    bankroll_after: float
    
    @property
    def result_str(self) -> str:
        return f"{self.goals_home}-{self.goals_away}"
    
    @property
    def location_emoji(self) -> str:
        return "🏠" if self.is_home else "🚌"
    
    @property
    def result_emoji(self) -> str:
        return "✓" if self.bet_won else "✗"
    
    @property
    def profit_loss_str(self) -> str:
        sign = "+" if self.profit_loss >= 0 else ""
        return f"{sign}€{self.profit_loss:.2f}"


@dataclass
class TeamSimulationResult:
    """Resultado de simulación para un equipo."""
    team_id: int
    team_name: str
    bets: List[BetResult] = field(default_factory=list)
    
    # Métricas calculadas (se llenan después)
    total_bets: int = 0
    wins: int = 0
    losses: int = 0
    total_staked: float = 0.0
    total_profit: float = 0.0
    roi: float = 0.0
    win_rate: float = 0.0
    
    # Por ubicación
    home_bets: int = 0
    home_wins: int = 0
    home_staked: float = 0.0
    home_profit: float = 0.0
    home_roi: float = 0.0
    
    away_bets: int = 0
    away_wins: int = 0
    away_staked: float = 0.0
    away_profit: float = 0.0
    away_roi: float = 0.0
    
    # Rachas
    max_win_streak: int = 0
    max_loss_streak: int = 0
    current_streak: int = 0
    current_streak_type: str = ""  # "W" o "L"
    
    # Estadísticas de odds
    avg_odd: float = 0.0
    min_odd: float = 0.0
    max_odd: float = 0.0
    
    # Bankroll
    initial_bankroll: float = 100.0
    final_bankroll: float = 100.0
    max_bankroll: float = 100.0
    min_bankroll: float = 100.0
    max_drawdown: float = 0.0
    
    def calculate_metrics(self):
        """Calcula todas las métricas a partir de las apuestas."""
        if not self.bets:
            return
        
        self.total_bets = len(self.bets)
        self.wins = sum(1 for b in self.bets if b.bet_won)
        self.losses = self.total_bets - self.wins
        self.total_staked = sum(b.stake for b in self.bets)
        self.total_profit = sum(b.profit_loss for b in self.bets)
        
        if self.total_staked > 0:
            self.roi = (self.total_profit / self.total_staked) * 100
        
        if self.total_bets > 0:
            self.win_rate = (self.wins / self.total_bets) * 100
        
        # Por ubicación
        home_bets = [b for b in self.bets if b.is_home]
        away_bets = [b for b in self.bets if not b.is_home]
        
        self.home_bets = len(home_bets)
        self.home_wins = sum(1 for b in home_bets if b.bet_won)
        self.home_staked = sum(b.stake for b in home_bets)
        self.home_profit = sum(b.profit_loss for b in home_bets)
        if self.home_staked > 0:
            self.home_roi = (self.home_profit / self.home_staked) * 100
        
        self.away_bets = len(away_bets)
        self.away_wins = sum(1 for b in away_bets if b.bet_won)
        self.away_staked = sum(b.stake for b in away_bets)
        self.away_profit = sum(b.profit_loss for b in away_bets)
        if self.away_staked > 0:
            self.away_roi = (self.away_profit / self.away_staked) * 100
        
        # Rachas
        self._calculate_streaks()
        
        # Estadísticas de odds
        odds = [b.odd for b in self.bets if b.odd > 0]
        if odds:
            self.avg_odd = sum(odds) / len(odds)
            self.min_odd = min(odds)
            self.max_odd = max(odds)
        
        # Bankroll
        self._calculate_bankroll_stats()
    
    def _calculate_streaks(self):
        """Calcula rachas de victorias y derrotas."""
        if not self.bets:
            return
        
        current_streak = 0
        current_type = None
        max_win = 0
        max_loss = 0
        
        for bet in self.bets:
            if bet.bet_won:
                if current_type == "W":
                    current_streak += 1
                else:
                    current_streak = 1
                    current_type = "W"
                max_win = max(max_win, current_streak)
            else:
                if current_type == "L":
                    current_streak += 1
                else:
                    current_streak = 1
                    current_type = "L"
                max_loss = max(max_loss, current_streak)
        
        self.max_win_streak = max_win
        self.max_loss_streak = max_loss
        self.current_streak = current_streak
        self.current_streak_type = current_type or ""
    
    def _calculate_bankroll_stats(self):
        """Calcula estadísticas de bankroll."""
        if not self.bets:
            return
        
        self.initial_bankroll = self.bets[0].bankroll_after - self.bets[0].profit_loss
        self.final_bankroll = self.bets[-1].bankroll_after
        
        bankrolls = [self.initial_bankroll]
        for bet in self.bets:
            bankrolls.append(bet.bankroll_after)
        
        self.max_bankroll = max(bankrolls)
        self.min_bankroll = min(bankrolls)
        
        # Max drawdown
        peak = bankrolls[0]
        max_dd = 0
        for br in bankrolls:
            if br > peak:
                peak = br
            dd = peak - br
            max_dd = max(max_dd, dd)
        self.max_drawdown = max_dd


@dataclass
class LeagueSimulationResult:
    """Resultado de simulación para toda la liga."""
    config: SimulationConfig
    league_name: str
    team_results: List[TeamSimulationResult] = field(default_factory=list)
    
    # Métricas globales
    total_teams: int = 0
    profitable_teams: int = 0
    avg_roi: float = 0.0
    best_roi: float = 0.0
    worst_roi: float = 0.0
    
    # Tendencias
    home_total_roi: float = 0.0
    away_total_roi: float = 0.0
    
    def calculate_league_metrics(self):
        """Calcula métricas a nivel de liga."""
        if not self.team_results:
            return
        
        self.total_teams = len(self.team_results)
        self.profitable_teams = sum(1 for t in self.team_results if t.roi > 0)
        
        rois = [t.roi for t in self.team_results]
        self.avg_roi = sum(rois) / len(rois) if rois else 0
        self.best_roi = max(rois) if rois else 0
        self.worst_roi = min(rois) if rois else 0
        
        # ROI por ubicación
        total_home_staked = sum(t.home_staked for t in self.team_results)
        total_home_profit = sum(t.home_profit for t in self.team_results)
        total_away_staked = sum(t.away_staked for t in self.team_results)
        total_away_profit = sum(t.away_profit for t in self.team_results)
        
        if total_home_staked > 0:
            self.home_total_roi = (total_home_profit / total_home_staked) * 100
        if total_away_staked > 0:
            self.away_total_roi = (total_away_profit / total_away_staked) * 100
    
    def get_ranking(self, by: str = "roi") -> List[TeamSimulationResult]:
        """Retorna equipos ordenados por métrica."""
        if by == "roi":
            return sorted(self.team_results, key=lambda t: t.roi, reverse=True)
        elif by == "profit":
            return sorted(self.team_results, key=lambda t: t.total_profit, reverse=True)
        elif by == "win_rate":
            return sorted(self.team_results, key=lambda t: t.win_rate, reverse=True)
        return self.team_results


@dataclass
class CoverageStats:
    """Estadísticas de cobertura de datos."""
    league_id: int
    league_name: str
    season: int
    total_fixtures: int
    fixtures_with_odds: int
    coverage_percent: float
    
    # Por tipo de mercado
    match_winner_count: int = 0
    over_under_count: int = 0
    double_chance_count: int = 0
    btts_count: int = 0
    
    # Bookmakers
    bookmakers: List[str] = field(default_factory=list)
    primary_bookmaker: str = ""


@dataclass 
class FixtureWithOdds:
    """Fixture con todas sus cuotas asociadas."""
    fixture: FixtureData
    odds: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Estructura: {"Match Winner": {"Home": 1.5, "Draw": 3.5, "Away": 6.0}, ...}
    
    def get_1x2_odds(self) -> Dict[str, float]:
        """Retorna cuotas 1X2."""
        for key in self.odds:
            if 'winner' in key.lower():
                return self.odds[key]
        return {}
    
    def get_over_under_odds(self, line: float = 2.5) -> Dict[str, float]:
        """Retorna cuotas Over/Under para una línea."""
        for key in self.odds:
            if 'over' in key.lower() and str(line) in key:
                return self.odds[key]
        return {}
    
    def has_complete_1x2(self) -> bool:
        """Verifica si tiene cuotas 1X2 completas."""
        odds = self.get_1x2_odds()
        return len(odds) >= 3
