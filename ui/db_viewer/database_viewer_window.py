# ui/db_viewer/database_viewer_window.py
# -*- coding: utf-8 -*-
"""
Ventana principal del visor de bases de datos.
Permite visualizar, editar y fusionar bases de datos SQLite.
"""

import os
import logging
from datetime import datetime
from typing import Optional, List

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTableView, QHeaderView,
    QToolBar, QStatusBar, QLabel, QComboBox, QPushButton,
    QLineEdit, QGroupBox, QFormLayout, QSpinBox, QMessageBox,
    QFileDialog, QProgressBar, QMenu, QDialog, QDialogButtonBox,
    QTextEdit, QApplication, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QAction, QIcon, QKeySequence, QFont

from .virtual_table_model import VirtualTableModel

logger = logging.getLogger(__name__)


class FilterWidget(QFrame):
    """Widget para construir filtros dinámicos."""
    
    filter_changed = Signal(str)  # Emite la cláusula WHERE
    
    OPERATORS = {
        '=': 'Igual a',
        '!=': 'Diferente de',
        '>': 'Mayor que',
        '<': 'Menor que',
        '>=': 'Mayor o igual',
        '<=': 'Menor o igual',
        'LIKE': 'Contiene',
        'IS NULL': 'Es vacío',
        'IS NOT NULL': 'No es vacío',
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self._columns = []
        self._filters: List[dict] = []
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Título
        title = QLabel("🔍 Filtros")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # Contenedor de filtros activos
        self._filters_container = QVBoxLayout()
        layout.addLayout(self._filters_container)
        
        # Botones de control
        btn_layout = QHBoxLayout()
        
        self._btn_add = QPushButton("+ Agregar filtro")
        self._btn_add.clicked.connect(self._add_filter_row)
        btn_layout.addWidget(self._btn_add)
        
        self._btn_clear = QPushButton("🗑 Limpiar")
        self._btn_clear.clicked.connect(self._clear_filters)
        btn_layout.addWidget(self._btn_clear)
        
        self._btn_apply = QPushButton("▶ Aplicar")
        self._btn_apply.setStyleSheet("background-color: #28A745; color: white; font-weight: bold;")
        self._btn_apply.clicked.connect(self._apply_filters)
        btn_layout.addWidget(self._btn_apply)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Agregar un filtro por defecto
        self._add_filter_row()
    
    def set_columns(self, columns: List[str]):
        """Establece las columnas disponibles para filtrar."""
        self._columns = columns
        # Actualizar combos existentes
        for i in range(self._filters_container.count()):
            widget = self._filters_container.itemAt(i).widget()
            if widget:
                combo = widget.findChild(QComboBox, "col_combo")
                if combo:
                    current = combo.currentText()
                    combo.clear()
                    combo.addItems(columns)
                    if current in columns:
                        combo.setCurrentText(current)
    
    def _add_filter_row(self):
        """Agrega una nueva fila de filtro."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)
        
        # Combo de columna
        col_combo = QComboBox()
        col_combo.setObjectName("col_combo")
        col_combo.addItems(self._columns)
        col_combo.setMinimumWidth(120)
        row_layout.addWidget(col_combo)
        
        # Combo de operador
        op_combo = QComboBox()
        op_combo.setObjectName("op_combo")
        for op, label in self.OPERATORS.items():
            op_combo.addItem(label, op)
        op_combo.setMinimumWidth(100)
        op_combo.currentIndexChanged.connect(lambda: self._on_operator_changed(row_widget))
        row_layout.addWidget(op_combo)
        
        # Input de valor
        value_input = QLineEdit()
        value_input.setObjectName("value_input")
        value_input.setPlaceholderText("Valor...")
        value_input.setMinimumWidth(150)
        value_input.returnPressed.connect(self._apply_filters)
        row_layout.addWidget(value_input)
        
        # Botón eliminar
        btn_remove = QPushButton("✕")
        btn_remove.setMaximumWidth(30)
        btn_remove.clicked.connect(lambda: self._remove_filter_row(row_widget))
        row_layout.addWidget(btn_remove)
        
        self._filters_container.addWidget(row_widget)
    
    def _remove_filter_row(self, widget):
        """Elimina una fila de filtro."""
        self._filters_container.removeWidget(widget)
        widget.deleteLater()
    
    def _on_operator_changed(self, row_widget):
        """Maneja cambio de operador para habilitar/deshabilitar input."""
        op_combo = row_widget.findChild(QComboBox, "op_combo")
        value_input = row_widget.findChild(QLineEdit, "value_input")
        
        if op_combo and value_input:
            op = op_combo.currentData()
            value_input.setEnabled(op not in ['IS NULL', 'IS NOT NULL'])
    
    def _clear_filters(self):
        """Limpia todos los filtros."""
        while self._filters_container.count():
            widget = self._filters_container.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self._add_filter_row()
        self.filter_changed.emit("")
    
    def _apply_filters(self):
        """Construye y emite la cláusula WHERE."""
        conditions = []
        
        for i in range(self._filters_container.count()):
            widget = self._filters_container.itemAt(i).widget()
            if not widget:
                continue
            
            col_combo = widget.findChild(QComboBox, "col_combo")
            op_combo = widget.findChild(QComboBox, "op_combo")
            value_input = widget.findChild(QLineEdit, "value_input")
            
            if not all([col_combo, op_combo, value_input]):
                continue
            
            column = col_combo.currentText()
            operator = op_combo.currentData()
            value = value_input.text().strip()
            
            if not column:
                continue
            
            if operator == 'IS NULL':
                conditions.append(f"{column} IS NULL")
            elif operator == 'IS NOT NULL':
                conditions.append(f"{column} IS NOT NULL")
            elif value:
                if operator == 'LIKE':
                    conditions.append(f"{column} LIKE '%{value}%'")
                else:
                    # Detectar si es número
                    try:
                        float(value)
                        conditions.append(f"{column} {operator} {value}")
                    except ValueError:
                        conditions.append(f"{column} {operator} '{value}'")
        
        where_clause = " AND ".join(conditions)
        logger.info(f"Filtro aplicado: {where_clause}")
        self.filter_changed.emit(where_clause)


class MergeDialog(QDialog):
    """Diálogo para fusionar bases de datos."""
    
    def __init__(self, current_db_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔀 Fusionar Bases de Datos")
        self.setModal(True)
        self.resize(600, 500)
        
        self.current_db = current_db_path
        self.source_db = None
        self.source_engine = None
        
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # Paso 1: Seleccionar BD fuente
        group1 = QGroupBox("📂 Paso 1: Seleccionar base de datos a fusionar")
        g1_layout = QHBoxLayout(group1)
        
        self._source_path = QLineEdit()
        self._source_path.setReadOnly(True)
        self._source_path.setPlaceholderText("Selecciona una base de datos...")
        g1_layout.addWidget(self._source_path)
        
        btn_browse = QPushButton("Examinar...")
        btn_browse.clicked.connect(self._browse_source)
        g1_layout.addWidget(btn_browse)
        
        layout.addWidget(group1)
        
        # Paso 2: Vista previa de tablas
        group2 = QGroupBox("📋 Paso 2: Tablas a fusionar")
        g2_layout = QVBoxLayout(group2)
        
        self._tables_tree = QTreeWidget()
        self._tables_tree.setHeaderLabels(["Tabla", "Filas origen", "Filas destino", "Acción"])
        self._tables_tree.setAlternatingRowColors(True)
        g2_layout.addWidget(self._tables_tree)
        
        layout.addWidget(group2)
        
        # Paso 3: Opciones de conflicto
        group3 = QGroupBox("⚙ Paso 3: Estrategia de conflictos")
        g3_layout = QVBoxLayout(group3)
        
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItem("Omitir duplicados (conservar existentes)", "skip")
        self._strategy_combo.addItem("Sobrescribir (reemplazar con nuevos)", "overwrite")
        self._strategy_combo.addItem("Crear como nuevos (generar nuevos IDs)", "duplicate")
        g3_layout.addWidget(self._strategy_combo)
        
        layout.addWidget(group3)
        
        # Log de progreso
        group4 = QGroupBox("📜 Progreso")
        g4_layout = QVBoxLayout(group4)
        
        self._progress = QProgressBar()
        g4_layout.addWidget(self._progress)
        
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(100)
        g4_layout.addWidget(self._log)
        
        layout.addWidget(group4)
        
        # Botones
        buttons = QDialogButtonBox()
        self._btn_merge = QPushButton("🔀 Fusionar")
        self._btn_merge.setEnabled(False)
        self._btn_merge.clicked.connect(self._execute_merge)
        buttons.addButton(self._btn_merge, QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        
        layout.addWidget(buttons)
    
    def _browse_source(self):
        """Abre diálogo para seleccionar BD fuente."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar base de datos",
            "",
            "SQLite (*.db *.sqlite *.sqlite3);;Todos (*.*)"
        )
        
        if path:
            self._source_path.setText(path)
            self.source_db = path
            self._analyze_source()
    
    def _analyze_source(self):
        """Analiza la BD fuente y muestra comparación."""
        from sqlalchemy import create_engine, inspect, text
        
        self._tables_tree.clear()
        self._log.clear()
        
        try:
            # Conectar a ambas BDs
            self.source_engine = create_engine(f'sqlite:///{self.source_db}')
            dest_engine = create_engine(f'sqlite:///{self.current_db}')
            
            source_inspector = inspect(self.source_engine)
            dest_inspector = inspect(dest_engine)
            
            source_tables = set(source_inspector.get_table_names())
            dest_tables = set(dest_inspector.get_table_names())
            
            all_tables = source_tables | dest_tables
            
            for table in sorted(all_tables):
                item = QTreeWidgetItem()
                item.setText(0, table)
                
                # Contar filas en origen
                if table in source_tables:
                    with self.source_engine.connect() as conn:
                        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                    item.setText(1, f"{count:,}")
                else:
                    item.setText(1, "-")
                
                # Contar filas en destino
                if table in dest_tables:
                    with dest_engine.connect() as conn:
                        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                    item.setText(2, f"{count:,}")
                else:
                    item.setText(2, "-")
                
                # Determinar acción
                if table in source_tables and table in dest_tables:
                    item.setText(3, "ðŸ“¥ Fusionar")
                    item.setCheckState(0, Qt.Checked)
                elif table in source_tables:
                    item.setText(3, "âž• Crear tabla")
                    item.setCheckState(0, Qt.Checked)
                else:
                    item.setText(3, "â­ Solo en destino")
                    item.setCheckState(0, Qt.Unchecked)
                    item.setDisabled(True)
                
                self._tables_tree.addTopLevelItem(item)
            
            self._tables_tree.resizeColumnToContents(0)
            self._btn_merge.setEnabled(True)
            self._log.append("âœ… Análisis completado")
            
            dest_engine.dispose()
            
        except Exception as e:
            self._log.append(f"✕ Error: {e}")
            logger.error(f"Error analizando BD fuente: {e}")
    
    def _execute_merge(self):
        """Ejecuta la fusión de bases de datos."""
        from sqlalchemy import create_engine, inspect, text, MetaData
        
        strategy = self._strategy_combo.currentData()
        self._log.append(f"\n🔄 Iniciando fusión (estrategia: {strategy})...")
        self._progress.setValue(0)
        
        try:
            dest_engine = create_engine(f'sqlite:///{self.current_db}')
            
            # Obtener tablas seleccionadas
            tables_to_merge = []
            for i in range(self._tables_tree.topLevelItemCount()):
                item = self._tables_tree.topLevelItem(i)
                if item.checkState(0) == Qt.Checked:
                    tables_to_merge.append(item.text(0))
            
            total = len(tables_to_merge)
            
            for idx, table in enumerate(tables_to_merge):
                self._log.append(f"  ðŸ“‹ Procesando {table}...")
                QApplication.processEvents()
                
                # Leer datos de origen
                with self.source_engine.connect() as src_conn:
                    rows = src_conn.execute(text(f"SELECT * FROM {table}")).fetchall()
                    columns_result = src_conn.execute(text(f"PRAGMA table_info({table})"))
                    columns = [row[1] for row in columns_result]
                
                if not rows:
                    self._log.append(f"    â­ Sin datos")
                    continue
                
                # Verificar si tabla existe en destino
                dest_inspector = inspect(dest_engine)
                if table not in dest_inspector.get_table_names():
                    # Copiar estructura de tabla
                    with self.source_engine.connect() as src_conn:
                        create_sql = src_conn.execute(
                            text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
                        ).scalar()
                    
                    with dest_engine.connect() as dest_conn:
                        dest_conn.execute(text(create_sql))
                        dest_conn.commit()
                    
                    self._log.append(f"    âž• Tabla creada")
                
                # Insertar datos
                inserted = 0
                skipped = 0
                
                with dest_engine.connect() as dest_conn:
                    for row in rows:
                        try:
                            placeholders = ", ".join([f":{c}" for c in columns])
                            params = {c: v for c, v in zip(columns, row)}
                            
                            if strategy == "skip":
                                # Verificar si existe (por PK)
                                # Simplificado: intentar insertar y capturar error
                                try:
                                    dest_conn.execute(
                                        text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"),
                                        params
                                    )
                                    inserted += 1
                                except:
                                    skipped += 1
                            
                            elif strategy == "overwrite":
                                dest_conn.execute(
                                    text(f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"),
                                    params
                                )
                                inserted += 1
                            
                            elif strategy == "duplicate":
                                # Quitar ID si existe
                                cols_no_id = [c for c in columns if c.lower() != 'id']
                                if len(cols_no_id) < len(columns):
                                    vals_no_id = [v for c, v in zip(columns, row) if c.lower() != 'id']
                                    placeholders = ", ".join([f":{c}" for c in cols_no_id])
                                    params = {c: v for c, v in zip(cols_no_id, vals_no_id)}
                                    dest_conn.execute(
                                        text(f"INSERT INTO {table} ({', '.join(cols_no_id)}) VALUES ({placeholders})"),
                                        params
                                    )
                                else:
                                    dest_conn.execute(
                                        text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"),
                                        params
                                    )
                                inserted += 1
                        
                        except Exception as e:
                            skipped += 1
                    
                    dest_conn.commit()
                
                self._log.append(f"    âœ… {inserted:,} insertados, {skipped:,} omitidos")
                self._progress.setValue(int((idx + 1) / total * 100))
                QApplication.processEvents()
            
            dest_engine.dispose()
            self._log.append("\nâœ… Fusión completada exitosamente")
            QMessageBox.information(self, "Éxito", "La fusión se completó exitosamente")
            
        except Exception as e:
            self._log.append(f"\n✕ Error: {e}")
            logger.error(f"Error en fusión: {e}")
            QMessageBox.critical(self, "Error", f"Error durante la fusión:\n{e}")


class DatabaseViewerWindow(QMainWindow):
    """
    Ventana principal del visor de bases de datos.
    
    Características:
    - Visualización de tablas con paginación virtual
    - Edición inline con validación
    - Filtros dinámicos
    - Fusión de bases de datos
    - Exportación a CSV
    """
    
    def __init__(self, parent=None, db_path: str = None):
        super().__init__(parent)
        self.setWindowTitle("📊 Visor de Base de Datos")
        self.resize(1200, 800)
        
        self._current_db_path = db_path
        self._model = VirtualTableModel()
        
        self._build_ui()
        self._setup_connections()
        self._create_menus()
        self._create_toolbar()
        
        # Cargar BD si se proporcionó
        if db_path and os.path.exists(db_path):
            self._load_database(db_path)
    
    def _build_ui(self):
        """Construye la interfaz de usuario."""
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Splitter principal
        splitter = QSplitter(Qt.Horizontal)
        
        # === Panel izquierdo: Árbol de tablas ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        
        # Selector de BD
        db_group = QGroupBox("ðŸ“ Base de Datos")
        db_layout = QVBoxLayout(db_group)
        
        self._db_combo = QComboBox()
        self._db_combo.setEditable(False)
        self._db_combo.currentTextChanged.connect(self._on_db_selected)
        db_layout.addWidget(self._db_combo)
        
        btn_layout = QHBoxLayout()
        btn_open = QPushButton("📂 Abrir")
        btn_open.clicked.connect(self._open_database)
        btn_layout.addWidget(btn_open)
        
        btn_refresh = QPushButton("🔄")
        btn_refresh.setToolTip("Refrescar")
        btn_refresh.setMaximumWidth(30)
        btn_refresh.clicked.connect(self._refresh_tree)
        btn_layout.addWidget(btn_refresh)
        
        db_layout.addLayout(btn_layout)
        left_layout.addWidget(db_group)
        
        # Árbol de tablas
        tables_group = QGroupBox("📋 Tablas")
        tables_layout = QVBoxLayout(tables_group)
        
        self._tables_tree = QTreeWidget()
        self._tables_tree.setHeaderLabels(["Nombre", "Filas"])
        self._tables_tree.setAlternatingRowColors(True)
        self._tables_tree.itemClicked.connect(self._on_table_selected)
        self._tables_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tables_tree.customContextMenuRequested.connect(self._show_table_context_menu)
        tables_layout.addWidget(self._tables_tree)
        
        left_layout.addWidget(tables_group)
        
        left_panel.setMaximumWidth(280)
        splitter.addWidget(left_panel)
        
        # === Panel derecho: Tabla y filtros ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        
        # Widget de filtros
        self._filter_widget = FilterWidget()
        self._filter_widget.filter_changed.connect(self._on_filter_changed)
        self._filter_widget.setMaximumHeight(150)
        right_layout.addWidget(self._filter_widget)
        
        # Tabla de datos
        self._table_view = QTableView()
        self._table_view.setModel(self._model)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setSortingEnabled(True)
        self._table_view.setSelectionBehavior(QTableView.SelectRows)
        self._table_view.setSelectionMode(QTableView.ExtendedSelection)
        
        # Configurar header
        header = self._table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.sectionClicked.connect(self._on_header_clicked)
        
        right_layout.addWidget(self._table_view)
        
        # Barra de información
        info_layout = QHBoxLayout()
        
        self._lbl_table_info = QLabel("Selecciona una tabla")
        info_layout.addWidget(self._lbl_table_info)
        
        info_layout.addStretch()
        
        self._lbl_changes = QLabel("")
        self._lbl_changes.setStyleSheet("color: #FF6B35; font-weight: bold;")
        info_layout.addWidget(self._lbl_changes)
        
        # Navegación de páginas
        self._btn_first = QPushButton("â®")
        self._btn_first.setMaximumWidth(30)
        self._btn_first.clicked.connect(lambda: self._go_to_page(0))
        info_layout.addWidget(self._btn_first)
        
        self._btn_prev = QPushButton("â—€")
        self._btn_prev.setMaximumWidth(30)
        self._btn_prev.clicked.connect(self._prev_page)
        info_layout.addWidget(self._btn_prev)
        
        self._page_spin = QSpinBox()
        self._page_spin.setMinimum(1)
        self._page_spin.setMaximumWidth(80)
        self._page_spin.valueChanged.connect(lambda v: self._go_to_page(v - 1))
        info_layout.addWidget(self._page_spin)
        
        self._lbl_total_pages = QLabel("/ 0")
        info_layout.addWidget(self._lbl_total_pages)
        
        self._btn_next = QPushButton("â–¶")
        self._btn_next.setMaximumWidth(30)
        self._btn_next.clicked.connect(self._next_page)
        info_layout.addWidget(self._btn_next)
        
        self._btn_last = QPushButton("â­")
        self._btn_last.setMaximumWidth(30)
        self._btn_last.clicked.connect(self._go_to_last_page)
        info_layout.addWidget(self._btn_last)
        
        right_layout.addLayout(info_layout)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([250, 950])
        
        main_layout.addWidget(splitter)
        
        self.setCentralWidget(central)
        
        # Barra de estado
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Listo")
    
    def _setup_connections(self):
        """Configura las conexiones de señales."""
        self._model.loading_started.connect(lambda: self._status_bar.showMessage("Cargando..."))
        self._model.loading_finished.connect(self._on_loading_finished)
        self._model.error_occurred.connect(self._on_error)
        self._model.data_changed.connect(self._on_data_changed)
    
    def _create_menus(self):
        """Crea los menús de la aplicación."""
        menubar = self.menuBar()
        
        # Menú Archivo
        file_menu = menubar.addMenu("ðŸ“‚ &Archivo")
        
        action_open = QAction("Abrir base de datos...", self)
        action_open.setShortcut(QKeySequence.Open)
        action_open.triggered.connect(self._open_database)
        file_menu.addAction(action_open)
        
        file_menu.addSeparator()
        
        action_export = QAction("Exportar tabla a CSV...", self)
        action_export.setShortcut(QKeySequence("Ctrl+E"))
        action_export.triggered.connect(self._export_to_csv)
        file_menu.addAction(action_export)
        
        file_menu.addSeparator()
        
        action_close = QAction("Cerrar", self)
        action_close.setShortcut(QKeySequence.Close)
        action_close.triggered.connect(self.close)
        file_menu.addAction(action_close)
        
        # Menú Editar
        edit_menu = menubar.addMenu("ðŸ“ &Editar")
        
        action_save = QAction("Guardar cambios", self)
        action_save.setShortcut(QKeySequence.Save)
        action_save.triggered.connect(self._save_changes)
        edit_menu.addAction(action_save)
        
        action_discard = QAction("Descartar cambios", self)
        action_discard.setShortcut(QKeySequence("Ctrl+Z"))
        action_discard.triggered.connect(self._discard_changes)
        edit_menu.addAction(action_discard)
        
        edit_menu.addSeparator()
        
        action_insert = QAction("Insertar fila", self)
        action_insert.setShortcut(QKeySequence("Ctrl+N"))
        action_insert.triggered.connect(self._insert_row)
        edit_menu.addAction(action_insert)
        
        action_delete = QAction("Eliminar filas seleccionadas", self)
        action_delete.setShortcut(QKeySequence.Delete)
        action_delete.triggered.connect(self._delete_selected_rows)
        edit_menu.addAction(action_delete)
        
        # Menú Herramientas
        tools_menu = menubar.addMenu("ðŸ”§ &Herramientas")
        
        action_merge = QAction("Fusionar con otra BD...", self)
        action_merge.triggered.connect(self._open_merge_dialog)
        tools_menu.addAction(action_merge)
        
        tools_menu.addSeparator()
        
        action_vacuum = QAction("Optimizar BD (VACUUM)", self)
        action_vacuum.triggered.connect(self._vacuum_database)
        tools_menu.addAction(action_vacuum)
    
    def _create_toolbar(self):
        """Crea la barra de herramientas."""
        toolbar = QToolBar("Principal")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Botones principales
        btn_save = QPushButton("💾 Guardar")
        btn_save.clicked.connect(self._save_changes)
        toolbar.addWidget(btn_save)
        
        btn_refresh = QPushButton("🔄 Refrescar")
        btn_refresh.clicked.connect(self._refresh_table)
        toolbar.addWidget(btn_refresh)
        
        toolbar.addSeparator()
        
        btn_insert = QPushButton("âž• Nueva fila")
        btn_insert.clicked.connect(self._insert_row)
        toolbar.addWidget(btn_insert)
        
        btn_delete = QPushButton("ðŸ—‘ Eliminar")
        btn_delete.clicked.connect(self._delete_selected_rows)
        toolbar.addWidget(btn_delete)
        
        toolbar.addSeparator()
        
        btn_export = QPushButton("📤 Exportar CSV")
        btn_export.clicked.connect(self._export_to_csv)
        toolbar.addWidget(btn_export)
        
        btn_merge = QPushButton("🔀 Fusionar BD")
        btn_merge.clicked.connect(self._open_merge_dialog)
        toolbar.addWidget(btn_merge)
        toolbar.addSeparator()
        
        btn_matches = QPushButton("⚽ Visor de Partidos")
        btn_matches.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        btn_matches.clicked.connect(self._open_match_viewer)
        toolbar.addWidget(btn_matches)

    
    # =========================================================================
    # Manejo de base de datos
    # =========================================================================
    
    def _open_database(self):
        """Abre un diálogo para seleccionar una BD."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir base de datos",
            "",
            "SQLite (*.db *.sqlite *.sqlite3);;Todos (*.*)"
        )
        
        if path:
            self._load_database(path)
    
    def _load_database(self, path: str):
        """Carga una base de datos."""
        if self._model.has_pending_changes():
            reply = QMessageBox.question(
                self,
                "Cambios sin guardar",
                "Hay cambios sin guardar. ¿Descartar?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        if self._model.connect_to_database(path):
            self._current_db_path = path
            
            # Actualizar combo de BDs
            if path not in [self._db_combo.itemText(i) for i in range(self._db_combo.count())]:
                self._db_combo.addItem(path)
            self._db_combo.setCurrentText(path)
            
            self._refresh_tree()
            self.setWindowTitle(f"📊 Visor de Base de Datos - {os.path.basename(path)}")
            self._status_bar.showMessage(f"BD cargada: {path}")
    
    def _refresh_tree(self):
        """Refresca el árbol de tablas."""
        self._tables_tree.clear()
        
        tables = self._model.get_tables()
        for table in tables:
            info = self._model.get_table_info(table)
            
            item = QTreeWidgetItem()
            item.setText(0, table)
            item.setText(1, f"{info['row_count']:,}")
            item.setData(0, Qt.UserRole, table)
            
            # Agregar columnas como hijos
            for col in info['columns']:
                col_item = QTreeWidgetItem()
                col_name = col['name']
                col_type = str(col['type'])
                is_pk = "ðŸ”‘" if col_name in info['primary_keys'] else ""
                col_item.setText(0, f"{is_pk} {col_name}")
                col_item.setText(1, col_type)
                item.addChild(col_item)
            
            self._tables_tree.addTopLevelItem(item)
        
        self._tables_tree.resizeColumnToContents(0)
    
    def _on_db_selected(self, path: str):
        """Maneja selección de BD en el combo."""
        if path and path != self._current_db_path:
            self._load_database(path)
    
    def _on_table_selected(self, item: QTreeWidgetItem, column: int):
        """Maneja selección de tabla en el árbol."""
        table_name = item.data(0, Qt.UserRole)
        if table_name:
            self._load_table(table_name)
    
    def _load_table(self, table_name: str):
        """Carga una tabla en la vista."""
        if self._model.has_pending_changes():
            reply = QMessageBox.question(
                self,
                "Cambios sin guardar",
                "Hay cambios sin guardar. ¿Descartar?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self._model.load_table(table_name)
        
        # Actualizar filtros
        columns = [col['name'] for col in self._model.get_column_info()]
        self._filter_widget.set_columns(columns)
        
        # Ajustar columnas
        self._table_view.resizeColumnsToContents()
    
    def _show_table_context_menu(self, pos):
        """Muestra menú contextual para tablas."""
        item = self._tables_tree.itemAt(pos)
        if not item:
            return
        
        table_name = item.data(0, Qt.UserRole)
        if not table_name:
            return
        
        menu = QMenu()
        
        action_open = menu.addAction("ðŸ“‹ Abrir tabla")
        action_open.triggered.connect(lambda: self._load_table(table_name))
        
        action_export = menu.addAction("ðŸ“¤ Exportar a CSV")
        action_export.triggered.connect(lambda: self._export_table_to_csv(table_name))
        
        menu.addSeparator()
        
        action_info = menu.addAction("â„¹ Información")
        action_info.triggered.connect(lambda: self._show_table_info(table_name))
        
        menu.exec_(self._tables_tree.mapToGlobal(pos))
    
    # =========================================================================
    # Filtros y ordenamiento
    # =========================================================================
    
    def _on_filter_changed(self, where_clause: str):
        """Aplica filtro a la tabla."""
        self._model.apply_filter(where_clause)
    
    def _on_header_clicked(self, column: int):
        """Ordena por columna clickeada."""
        # Toggle orden
        current_order = self._table_view.horizontalHeader().sortIndicatorOrder()
        ascending = current_order != Qt.AscendingOrder
        self._model.apply_sort(column, ascending)
    
    # =========================================================================
    # Edición
    # =========================================================================
    
    def _save_changes(self):
        """Guarda cambios pendientes."""
        if not self._model.has_pending_changes():
            self._status_bar.showMessage("No hay cambios para guardar")
            return
        
        saved, errors = self._model.save_changes()
        
        if errors:
            QMessageBox.warning(
                self,
                "Errores al guardar",
                f"Se guardaron {saved} cambios.\n\nErrores:\n" + "\n".join(errors[:10])
            )
        else:
            self._status_bar.showMessage(f"âœ… {saved} cambios guardados")
        
        self._update_changes_label()
    
    def _discard_changes(self):
        """Descarta cambios pendientes."""
        if not self._model.has_pending_changes():
            return
        
        reply = QMessageBox.question(
            self,
            "Descartar cambios",
            f"¿Descartar {self._model.get_pending_changes_count()} cambios?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._model.discard_changes()
            self._update_changes_label()
            self._status_bar.showMessage("Cambios descartados")
    
    def _insert_row(self):
        """Inserta una nueva fila."""
        if self._model.insert_row():
            self._status_bar.showMessage("âœ… Fila insertada")
            # Ir a la última página
            self._go_to_last_page()
        else:
            self._status_bar.showMessage("✕ Error al insertar fila")
    
    def _delete_selected_rows(self):
        """Elimina las filas seleccionadas."""
        selection = self._table_view.selectionModel()
        rows = sorted(set(index.row() for index in selection.selectedIndexes()), reverse=True)
        
        if not rows:
            self._status_bar.showMessage("No hay filas seleccionadas")
            return
        
        reply = QMessageBox.question(
            self,
            "Eliminar filas",
            f"¿Eliminar {len(rows)} filas seleccionadas?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            deleted, errors = self._model.delete_rows(rows)
            
            if errors:
                QMessageBox.warning(
                    self,
                    "Errores al eliminar",
                    f"Se eliminaron {deleted} filas.\n\nErrores:\n" + "\n".join(errors[:10])
                )
            else:
                self._status_bar.showMessage(f"âœ… {deleted} filas eliminadas")
    
    def _on_data_changed(self):
        """Actualiza indicador de cambios."""
        self._update_changes_label()
    
    def _update_changes_label(self):
        """Actualiza el label de cambios pendientes."""
        count = self._model.get_pending_changes_count()
        if count > 0:
            self._lbl_changes.setText(f"⚠ {count} cambios sin guardar")
        else:
            self._lbl_changes.setText("")
    
    # =========================================================================
    # Navegación
    # =========================================================================
    
    def _on_loading_finished(self, total_rows: int):
        """Actualiza UI después de cargar datos."""
        page_size = VirtualTableModel.PAGE_SIZE
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        
        self._page_spin.setMaximum(total_pages)
        self._lbl_total_pages.setText(f"/ {total_pages}")
        self._lbl_table_info.setText(f"ðŸ“Š {total_rows:,} filas")
        
        self._status_bar.showMessage(f"Tabla cargada: {total_rows:,} filas")
    
    def _go_to_page(self, page: int):
        """Navega a una página específica."""
        page_size = VirtualTableModel.PAGE_SIZE
        row = page * page_size
        index = self._model.index(row, 0)
        self._table_view.scrollTo(index)
        self._page_spin.setValue(page + 1)
    
    def _prev_page(self):
        """Va a la página anterior."""
        current = self._page_spin.value()
        if current > 1:
            self._go_to_page(current - 2)
    
    def _next_page(self):
        """Va a la página siguiente."""
        current = self._page_spin.value()
        if current < self._page_spin.maximum():
            self._go_to_page(current)
    
    def _go_to_last_page(self):
        """Va a la última página."""
        self._go_to_page(self._page_spin.maximum() - 1)
    
    # =========================================================================
    # Exportación y herramientas
    # =========================================================================
    
    def _export_to_csv(self):
        """Exporta la tabla actual a CSV."""
        if not self._model._table_name:
            self._status_bar.showMessage("No hay tabla seleccionada")
            return
        
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar a CSV",
            f"{self._model._table_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV (*.csv)"
        )
        
        if path:
            if self._model.export_to_csv(path):
                self._status_bar.showMessage(f"âœ… Exportado a {path}")
                QMessageBox.information(self, "Éxito", f"Tabla exportada a:\n{path}")
    
    def _export_table_to_csv(self, table_name: str):
        """Exporta una tabla específica a CSV."""
        # Cargar tabla temporalmente
        self._model.load_table(table_name)
        self._export_to_csv()
    
    def _show_table_info(self, table_name: str):
        """Muestra información detallada de una tabla."""
        info = self._model.get_table_info(table_name)
        
        msg = f"""ðŸ“‹ Tabla: {table_name}
        
ðŸ“Š Filas: {info['row_count']:,}

ðŸ”‘ Claves primarias: {', '.join(info['primary_keys']) or 'Ninguna'}

ðŸ“ Columnas:
"""
        for col in info['columns']:
            pk = "ðŸ”‘" if col['name'] in info['primary_keys'] else "  "
            msg += f"\n  {pk} {col['name']}: {col['type']}"
        
        if info['foreign_keys']:
            msg += "\n\n🔗 Claves foráneas:"
            for fk in info['foreign_keys']:
                msg += f"\n  • {fk['constrained_columns']} → {fk['referred_table']}"
        
        QMessageBox.information(self, f"Información: {table_name}", msg)
    
    def _open_merge_dialog(self):
        """Abre el diálogo de fusión."""
        if not self._current_db_path:
            QMessageBox.warning(self, "Error", "Primero abre una base de datos")
            return
        
        dialog = MergeDialog(self._current_db_path, self)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_tree()
            self._refresh_table()
    
    
    def _open_match_viewer(self):
        """Abre el visor de partidos estilo BeSoccer."""
        try:
            from .match_viewer_dialog import MatchViewerDialog
            
            db_path = self._current_db_path
            if not db_path or 'sad.db' not in str(db_path):
                import os
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                sad_path = os.path.join(base_dir, 'sad.db')
                if os.path.exists(sad_path):
                    db_path = sad_path
            
            dialog = MatchViewerDialog(db_path, self)
            dialog.show()
            
        except ImportError as e:
            logger.error(f"Error importando MatchViewerDialog: {e}")
            QMessageBox.critical(
                self,
                "Error de importacion",
                f"No se pudo cargar el modulo del visor de partidos:\n{str(e)}"
            )
        except Exception as e:
            logger.error(f"Error abriendo visor de partidos: {e}")
            QMessageBox.critical(self, "Error", f"Error al abrir el visor de partidos:\n{str(e)}")

    def _vacuum_database(self):
        """Optimiza la base de datos con VACUUM."""
        if not self._current_db_path:
            return
        
        reply = QMessageBox.question(
            self,
            "Optimizar BD",
            "¿Ejecutar VACUUM para optimizar la base de datos?\n\n"
            "Esto puede tardar unos segundos para BDs grandes.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                from sqlalchemy import text
                with self._model._engine.connect() as conn:
                    conn.execute(text("VACUUM"))
                self._status_bar.showMessage("âœ… Base de datos optimizada")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error al optimizar:\n{e}")
    
    def _refresh_table(self):
        """Refresca la tabla actual."""
        self._model.refresh()
        self._status_bar.showMessage("🔄 Tabla refrescada")
    
    def _on_error(self, message: str):
        """Maneja errores del modelo."""
        self._status_bar.showMessage(f"✕ Error: {message}")
        logger.error(f"Error en modelo: {message}")
    
    # =========================================================================
    # Eventos
    # =========================================================================
    
    def closeEvent(self, event):
        """Maneja el cierre de la ventana."""
        if self._model.has_pending_changes():
            reply = QMessageBox.question(
                self,
                "Cambios sin guardar",
                "Hay cambios sin guardar. ¿Qué deseas hacer?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Save:
                self._save_changes()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
                return
        
        self._model.close()
        event.accept()


# =============================================================================
# Punto de entrada para pruebas
# =============================================================================

def main():
    """Función principal para ejecutar el visor."""
    import sys
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Estilo global
    app.setStyleSheet("""
        QMainWindow {
            background-color: #F5F5F5;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #CCC;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QTreeWidget, QTableView {
            border: 1px solid #DDD;
            border-radius: 3px;
        }
        QPushButton {
            padding: 5px 10px;
            border-radius: 3px;
            border: 1px solid #CCC;
            background-color: #FFF;
        }
        QPushButton:hover {
            background-color: #E8E8E8;
        }
        QPushButton:pressed {
            background-color: #D0D0D0;
        }
    """)
    
    window = DatabaseViewerWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()