# src/data/data_models/fixtures.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from data.base import Base

class Fixture(Base):
    __tablename__ = 'fixtures'
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    referee = Column(String)
    timezone = Column(String)
    date = Column(DateTime)
    timestamp = Column(Integer)
    first_half_start = Column(Integer)
    second_half_start = Column(Integer)
    venue_id = Column(Integer)
    venue_name = Column(String)
    venue_city = Column(String)
    status_long = Column(String)
    status_short = Column(String)
    elapsed = Column(Integer)
    league_id = Column(Integer)
    league_season = Column(Integer)
    league_round = Column(String)

    # Claves foráneas a equipos
    home_team_id = Column(Integer, ForeignKey('teams.id'))
    away_team_id = Column(Integer, ForeignKey('teams.id'))

    # Goles
    goals_home = Column(Integer)
    goals_away = Column(Integer)
    halftime_home = Column(Integer)
    halftime_away = Column(Integer)
    fulltime_home = Column(Integer)
    fulltime_away = Column(Integer)
    extratime_home = Column(Integer)
    extratime_away = Column(Integer)
    penalty_home = Column(Integer)
    penalty_away = Column(Integer)

    # Relaciones removidas para evitar errores de dependencia circular
    # Para obtener datos del equipo, usar queries explícitas:
    # session.query(Team).filter(Team.id == fixture.home_team_id).first()