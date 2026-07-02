# src/data/data_models/statistics.py
"""Modelo ORM para estadísticas de equipos."""

from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from data.base import Base


class TeamStatistics(Base):
    """Modelo para almacenar estadísticas agregadas de equipos por temporada."""
    __tablename__ = 'team_statistics'
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False, index=True)
    league_id = Column(Integer, nullable=True)
    season = Column(Integer, nullable=True)
    
    # Forma reciente
    form = Column(String, nullable=True)  # Ej: "WWDLW"
    
    # Partidos jugados
    played_home = Column(Integer, nullable=True)
    played_away = Column(Integer, nullable=True)
    played_total = Column(Integer, nullable=True)
    
    # Victorias
    wins_home = Column(Integer, nullable=True)
    wins_away = Column(Integer, nullable=True)
    wins_total = Column(Integer, nullable=True)
    
    # Empates
    draws_home = Column(Integer, nullable=True)
    draws_away = Column(Integer, nullable=True)
    draws_total = Column(Integer, nullable=True)
    
    # Derrotas
    loses_home = Column(Integer, nullable=True)
    loses_away = Column(Integer, nullable=True)
    loses_total = Column(Integer, nullable=True)
    
    # Goles a favor
    goals_for_home = Column(Integer, nullable=True)
    goals_for_away = Column(Integer, nullable=True)
    goals_for_total = Column(Integer, nullable=True)
    
    # Goles en contra
    goals_against_home = Column(Integer, nullable=True)
    goals_against_away = Column(Integer, nullable=True)
    goals_against_total = Column(Integer, nullable=True)
    
    # Porterías a cero
    clean_sheet_home = Column(Integer, nullable=True)
    clean_sheet_away = Column(Integer, nullable=True)
    clean_sheet_total = Column(Integer, nullable=True)
    
    # Partidos sin marcar
    failed_to_score_home = Column(Integer, nullable=True)
    failed_to_score_away = Column(Integer, nullable=True)
    failed_to_score_total = Column(Integer, nullable=True)

    # Relación con Team
    team = relationship("Team", backref="team_statistics_list")

    def __repr__(self):
        return f"<TeamStatistics(team_id={self.team_id}, season={self.season}, played={self.played_total})>"