# src/data/data_models/leagues.py
"""Modelo ORM para ligas de fútbol."""

from sqlalchemy import Column, Integer, String
from data.base import Base


class League(Base):
    """Modelo para almacenar información de ligas."""
    __tablename__ = 'leagues'
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)
    country = Column(String, nullable=True)
    logo = Column(String, nullable=True)
    flag = Column(String, nullable=True)
    season = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<League(id={self.id}, name='{self.name}', country='{self.country}')>"