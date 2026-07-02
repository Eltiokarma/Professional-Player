#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🗃️ Visor de Base de Datos - Lanzador Principal

Este script lanza el visor de bases de datos con detección automática
de las BDs del proyecto de análisis deportivo.

Uso:
    python run_db_viewer.py
    python run_db_viewer.py ruta/a/mi_base.db
"""

import sys
import os
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def find_project_databases():
    """
    Busca las bases de datos del proyecto en ubicaciones comunes.
    
    Returns:
        Dict con nombres descriptivos y rutas a las BDs encontradas
    """
    databases = {}
    
    # Posibles ubicaciones relativas al script
    search_paths = [
        '.',           # Directorio actual
        '..',          # Directorio padre
        '../..',       # Dos niveles arriba
        'data',        # Subdirectorio data
        '../data',     # data en directorio padre
    ]
    
    # BDs conocidas del proyecto
    known_dbs = [
        ('sad.db', '📊 Datos Originales (sad.db)'),
        ('constants.db', '📈 Constantes Calculadas (constants.db)'),
        ('levels.db', '📉 Niveles de Equipos (levels.db)'),
        ('discreto.db', '🤖 Datos ML (discreto.db)'),
    ]
    
    for base_path in search_paths:
        for db_file, description in known_dbs:
            full_path = os.path.abspath(os.path.join(base_path, db_file))
            if os.path.exists(full_path) and full_path not in databases.values():
                databases[description] = full_path
                logger.info(f"BD encontrada: {full_path}")
    
    return databases


def main():
    """Función principal."""
    from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
    from database_viewer_window import DatabaseViewerWindow
    
    logger.info("🗃️ Iniciando Visor de Base de Datos...")
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Estilo global mejorado
    app.setStyleSheet("""
        QMainWindow {
            background-color: #F8F9FA;
        }
        QDialog {
            background-color: #FFFFFF;
        }
        QGroupBox {
            font-weight: bold;
            border: 2px solid #DEE2E6;
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 12px;
            background-color: #FFFFFF;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px;
            color: #495057;
        }
        QTreeWidget {
            border: 1px solid #DEE2E6;
            border-radius: 4px;
            background-color: #FFFFFF;
            alternate-background-color: #F8F9FA;
        }
        QTreeWidget::item:selected {
            background-color: #007BFF;
            color: white;
        }
        QTableView {
            border: 1px solid #DEE2E6;
            border-radius: 4px;
            background-color: #FFFFFF;
            alternate-background-color: #F8F9FA;
            gridline-color: #E9ECEF;
        }
        QTableView::item:selected {
            background-color: #007BFF;
            color: white;
        }
        QHeaderView::section {
            background-color: #E9ECEF;
            padding: 6px;
            border: none;
            border-right: 1px solid #DEE2E6;
            border-bottom: 1px solid #DEE2E6;
            font-weight: bold;
        }
        QPushButton {
            padding: 8px 16px;
            border-radius: 4px;
            border: 1px solid #DEE2E6;
            background-color: #FFFFFF;
            color: #212529;
        }
        QPushButton:hover {
            background-color: #E9ECEF;
            border-color: #ADB5BD;
        }
        QPushButton:pressed {
            background-color: #DEE2E6;
        }
        QLineEdit, QComboBox, QSpinBox {
            padding: 6px 10px;
            border: 1px solid #CED4DA;
            border-radius: 4px;
            background-color: #FFFFFF;
        }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
            border-color: #80BDFF;
            outline: none;
        }
        QStatusBar {
            background-color: #E9ECEF;
            border-top: 1px solid #DEE2E6;
        }
        QToolBar {
            background-color: #FFFFFF;
            border-bottom: 1px solid #DEE2E6;
            spacing: 5px;
            padding: 5px;
        }
        QMenuBar {
            background-color: #FFFFFF;
            border-bottom: 1px solid #DEE2E6;
        }
        QMenuBar::item:selected {
            background-color: #E9ECEF;
        }
        QMenu {
            background-color: #FFFFFF;
            border: 1px solid #DEE2E6;
        }
        QMenu::item:selected {
            background-color: #007BFF;
            color: white;
        }
        QProgressBar {
            border: 1px solid #DEE2E6;
            border-radius: 4px;
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: #28A745;
            border-radius: 3px;
        }
        QFrame#FilterWidget {
            background-color: #F8F9FA;
            border: 1px solid #DEE2E6;
            border-radius: 4px;
        }
    """)
    
    # Determinar qué BD abrir
    db_path = None
    
    # Si se pasó una BD como argumento
    if len(sys.argv) > 1:
        arg_path = sys.argv[1]
        if os.path.exists(arg_path):
            db_path = os.path.abspath(arg_path)
            logger.info(f"Abriendo BD desde argumento: {db_path}")
    
    # Si no, buscar BDs del proyecto
    if not db_path:
        databases = find_project_databases()
        
        if databases:
            # Mostrar diálogo de selección
            items = list(databases.keys())
            items.append("📂 Abrir otra base de datos...")
            
            item, ok = QInputDialog.getItem(
                None,
                "🗃️ Seleccionar Base de Datos",
                "Se encontraron las siguientes bases de datos del proyecto:\n"
                "Selecciona cuál deseas abrir:",
                items,
                0,
                False
            )
            
            if ok and item:
                if item in databases:
                    db_path = databases[item]
                # Si eligió "Abrir otra...", se abrirá el diálogo de archivo en la ventana
    
    # Crear ventana principal
    window = DatabaseViewerWindow(db_path=db_path)
    window.show()
    
    # Mensaje de bienvenida
    if not db_path:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            window,
            "🗃️ Bienvenido al Visor de Base de Datos",
            "Para comenzar:\n\n"
            "1. Usa 📂 Archivo → Abrir para cargar una base de datos\n"
            "2. Selecciona una tabla del árbol izquierdo\n"
            "3. Usa los filtros para buscar datos específicos\n"
            "4. Haz doble clic en una celda para editarla\n"
            "5. No olvides 💾 Guardar tus cambios\n\n"
            "💡 Tip: Las tablas grandes cargan instantáneamente\n"
            "   gracias a la paginación virtual."
        )
    
    logger.info("✅ Visor iniciado correctamente")
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
