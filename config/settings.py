# src/config/settings.py
"""Configuración centralizada de la aplicación"""
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class UISettings:
    """Configuración de interfaz de usuario"""
    teams_per_page: int = 50
    search_debounce_ms: int = 500
    max_cache_size: int = 100
    default_window_width: int = 1400
    default_window_height: int = 800
    progress_update_interval: int = 10  # Actualizar progreso cada N elementos

@dataclass
class DatabaseSettings:
    """Configuración de base de datos"""
    batch_size: int = 1000
    connection_timeout: int = 30
    max_retries: int = 3
    enable_query_logging: bool = False

@dataclass
class CalculationSettings:
    """Configuración de cálculos"""
    default_level: float = 1.0
    visitor_multiplier: float = 1.4
    cache_expiry_hours: int = 24
    parallel_workers: int = 4

@dataclass
class AppSettings:
    """Configuración principal de la aplicación"""
    ui: UISettings = UISettings()
    database: DatabaseSettings = DatabaseSettings()
    calculation: CalculationSettings = CalculationSettings()
    
    @classmethod
    def load_from_env(cls) -> 'AppSettings':
        """Carga configuración desde variables de entorno"""
        settings = cls()
        
        # UI Settings
        settings.ui.teams_per_page = int(os.getenv('TEAMS_PER_PAGE', settings.ui.teams_per_page))
        settings.ui.search_debounce_ms = int(os.getenv('SEARCH_DEBOUNCE_MS', settings.ui.search_debounce_ms))
        settings.ui.max_cache_size = int(os.getenv('MAX_CACHE_SIZE', settings.ui.max_cache_size))
        
        # Database Settings
        settings.database.batch_size = int(os.getenv('DB_BATCH_SIZE', settings.database.batch_size))
        settings.database.connection_timeout = int(os.getenv('DB_TIMEOUT', settings.database.connection_timeout))
        settings.database.enable_query_logging = os.getenv('DB_LOGGING', 'false').lower() == 'true'
        
        # Calculation Settings
        settings.calculation.default_level = float(os.getenv('DEFAULT_LEVEL', settings.calculation.default_level))
        settings.calculation.visitor_multiplier = float(os.getenv('VISITOR_MULTIPLIER', settings.calculation.visitor_multiplier))
        settings.calculation.parallel_workers = int(os.getenv('PARALLEL_WORKERS', settings.calculation.parallel_workers))
        
        return settings

# Instancia global de configuración
app_settings = AppSettings.load_from_env()
