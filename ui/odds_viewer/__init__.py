# ui/odds_viewer/__init__.py
# -*- coding: utf-8 -*-
"""
Módulo de Visualización de Odds y Simulador del Hincha.

Sistema completo para:
- Visualización de cuotas estilo casa de apuestas
- Dashboard de análisis de cobertura de datos
- Simulación de apuestas sistemáticas del hincha

Uso básico:
    from ui.odds_viewer import OddsViewerWindow
    
    window = OddsViewerWindow()
    window.show()
    
    # O con una BD específica:
    window = OddsViewerWindow(db_path="sad.db")
    window.show()

Componentes principales:
    - OddsViewerWindow: Ventana principal con todos los tabs
    - OddsTab: Visualización de partidos y cuotas
    - DashboardTab: Análisis de cobertura
    - SimulatorTab: Simulador del hincha
    - FanSimulator: Motor de simulación
"""

from .main_window import OddsViewerWindow
from .tabs.odds_tab import OddsTab
from .tabs.dashboard_tab import DashboardTab
from .tabs.simulator_tab import SimulatorTab
from .simulador.fan_simulator import FanSimulator
from .models.database_queries import OddsQueryModel
from .models.data_models import (
    SimulationConfig,
    BetType,
    DoubleChanceType,
    TeamSimulationResult,
    LeagueSimulationResult
)

__all__ = [
    # Ventana principal
    'OddsViewerWindow',
    
    # Tabs
    'OddsTab',
    'DashboardTab', 
    'SimulatorTab',
    
    # Motor de simulación
    'FanSimulator',
    
    # Modelos
    'OddsQueryModel',
    'SimulationConfig',
    'BetType',
    'DoubleChanceType',
    'TeamSimulationResult',
    'LeagueSimulationResult',
]

__version__ = '1.0.0'
__author__ = 'Claude'
