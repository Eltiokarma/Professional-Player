# src/data/data_models/team_levels.py
"""
Modelo para persistir los niveles calculados de cada equipo.
"""
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey
from data.base import Base   # <–– Importa el mismo Base que usan Team y Fixture

class TeamLevel(Base):
    __tablename__ = 'team_levels'

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id', ondelete="CASCADE"), nullable=False)
    fixture_id = Column(Integer, ForeignKey('fixtures.id', ondelete="CASCADE"), nullable=False)
    date = Column(DateTime, nullable=False)
    level = Column(Float, nullable=False)
