# src/data/data_models/teams.py
from sqlalchemy import Column, Integer, String
from data.base import Base

class Team(Base):
    __tablename__ = 'teams'
    __table_args__ = {'extend_existing': True}
    
    id      = Column(Integer, primary_key=True)
    name    = Column(String)
    country = Column(String, nullable=True)
    founded = Column(Integer, nullable=True)
    logo    = Column(String, nullable=True)

    # Relaciones removidas para evitar errores de dependencia circular
    # Usar queries explícitas cuando necesites datos relacionados