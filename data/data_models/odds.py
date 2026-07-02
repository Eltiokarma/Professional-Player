# src/data/data_models/odds.py
"""Modelo ORM para cuotas de apuestas."""

from sqlalchemy import Column, Integer, String, Float, ForeignKey
from data.base import Base


class Odd(Base):
    """Modelo para almacenar cuotas de apuestas por fixture."""
    __tablename__ = 'odds'
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    fixture_id = Column(Integer, ForeignKey('fixtures.id'), nullable=False, index=True)
    league_id = Column(Integer, nullable=True)
    bookmaker_id = Column(Integer, nullable=True)
    bookmaker_name = Column(String, nullable=True)
    bet_id = Column(Integer, nullable=True)
    bet_name = Column(String, nullable=True)
    value = Column(String, nullable=True)  # Ej: "Home", "Draw", "Away", "Over 2.5", etc.
    odd = Column(Float, nullable=True)

    def __repr__(self):
        return f"<Odd(fixture_id={self.fixture_id}, bet='{self.bet_name}', value='{self.value}', odd={self.odd})>"