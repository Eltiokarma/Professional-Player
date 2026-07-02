# src/ui/anticulebra/__init__.py
# -*- coding: utf-8 -*-
"""
🐍 MÓDULO ANTICULEBRAS v4 - Machine Learning
Sistema de predicción con ML real para ruptura de culebras.

Uso:
    from ui.anticulebra import AnticulebraWindow
    window = AnticulebraWindow()
    window.show()
"""

from .anticulebra_engine import (
    AnticulebraEngine,
    MatchPrediction,
    DayAnalysis,
    JornadaAnalysis,
    CalibrationResult,
    MLTrainingResult,
    ValidationMetrics,
    Outcome,
    BreakType,
    FavoriteType,
    format_probability,
    format_odds,
    get_tension_color,
    get_break_type_emoji,
    get_outcome_emoji,
)

from .anticulebra_window import AnticulebraWindow

__all__ = [
    'AnticulebraEngine',
    'MatchPrediction',
    'DayAnalysis',
    'JornadaAnalysis',
    'CalibrationResult',
    'MLTrainingResult',
    'ValidationMetrics',
    'Outcome',
    'BreakType',
    'FavoriteType',
    'format_probability',
    'format_odds',
    'get_tension_color',
    'get_break_type_emoji',
    'get_outcome_emoji',
    'AnticulebraWindow',
]

__version__ = '4.0.0'
