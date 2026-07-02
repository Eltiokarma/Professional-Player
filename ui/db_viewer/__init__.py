# ui/db_viewer/__init__.py
# -*- coding: utf-8 -*-
"""
Módulo de visualización y gestión de bases de datos SQLite.

Características:
- Visualización de tablas grandes con paginación virtual
- Edición inline con validación de tipos
- Filtros dinámicos
- Fusión de bases de datos
- Exportación a CSV

Uso:
    from db_viewer import DatabaseViewerWindow
    
    viewer = DatabaseViewerWindow()
    viewer.show()
    
    # O con una BD específica:
    viewer = DatabaseViewerWindow(db_path="mi_base.db")
    viewer.show()
"""

from .virtual_table_model import VirtualTableModel
from .database_viewer_window import DatabaseViewerWindow, FilterWidget, MergeDialog

__all__ = [
    'VirtualTableModel',
    'DatabaseViewerWindow', 
    'FilterWidget',
    'MergeDialog'
]

__version__ = '1.0.0'
