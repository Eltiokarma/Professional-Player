# data/data_models/player_statistics.py

from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey
from data.base import Base

class PlayerStatistic(Base):
    __tablename__ = 'player_statistics'
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey('players.id'))
    team_id = Column(Integer, ForeignKey('teams.id'))
    league_id = Column(Integer)
    season = Column(Integer)

    # Campos de estadísticas
    games_appearences = Column(Integer, nullable=True)
    games_lineups = Column(Integer, nullable=True)
    games_minutes = Column(Integer, nullable=True)
    games_number = Column(Integer, nullable=True)
    games_position = Column(String, nullable=True)
    games_rating = Column(Float, nullable=True)
    games_captain = Column(Boolean, nullable=True)
    substitutes_in = Column(Integer, nullable=True)
    substitutes_out = Column(Integer, nullable=True)
    substitutes_bench = Column(Integer, nullable=True)
    shots_total = Column(Integer, nullable=True)
    shots_on = Column(Integer, nullable=True)
    goals_total = Column(Integer, nullable=True)
    goals_conceded = Column(Integer, nullable=True)
    goals_assists = Column(Integer, nullable=True)
    goals_saves = Column(Integer, nullable=True)
    passes_total = Column(Integer, nullable=True)
    passes_key = Column(Integer, nullable=True)
    passes_accuracy = Column(String, nullable=True)
    tackles_total = Column(Integer, nullable=True)
    tackles_blocks = Column(Integer, nullable=True)
    tackles_interceptions = Column(Integer, nullable=True)
    duels_total = Column(Integer, nullable=True)
    duels_won = Column(Integer, nullable=True)
    dribbles_attempts = Column(Integer, nullable=True)
    dribbles_success = Column(Integer, nullable=True)
    dribbles_past = Column(Integer, nullable=True)
    fouls_drawn = Column(Integer, nullable=True)
    fouls_committed = Column(Integer, nullable=True)
    cards_yellow = Column(Integer, nullable=True)
    cards_yellowred = Column(Integer, nullable=True)
    cards_red = Column(Integer, nullable=True)
    penalty_won = Column(Integer, nullable=True)
    penalty_committed = Column(Integer, nullable=True)
    penalty_scored = Column(Integer, nullable=True)
    penalty_missed = Column(Integer, nullable=True)
    penalty_saved = Column(Integer, nullable=True)

    # Relaciones removidas para evitar errores de dependencia circular