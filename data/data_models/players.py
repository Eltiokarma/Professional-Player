# src/data/data_models/players.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from data.base import Base

class Player(Base):
    __tablename__ = 'players'
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    name = Column(String)
    firstname = Column(String)
    lastname = Column(String)
    age = Column(Integer)
    birth_date = Column(String)
    birth_place = Column(String)
    nationality = Column(String)
    height = Column(String)
    weight = Column(String)
    injured = Column(Boolean)
    photo = Column(String)

    # Clave foránea a equipo
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=True)

    # Relaciones removidas para evitar errores de dependencia circular