# ui/db_viewer/virtual_table_model.py
# -*- coding: utf-8 -*-
"""
Modelo de tabla virtual con paginación para PySide6.
Optimizado para manejar tablas muy grandes (100K+ filas) sin consumir memoria.
"""

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal
from PySide6.QtGui import QColor, QBrush
from sqlalchemy import create_engine, inspect, text, MetaData, Table
from sqlalchemy.orm import sessionmaker
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class VirtualTableModel(QAbstractTableModel):
    """
    Modelo de tabla que carga datos bajo demanda (lazy loading).
    
    Características:
    - Paginación virtual: solo carga los datos visibles
    - Cache inteligente: guarda páginas recientes en memoria
    - Tracking de cambios: marca celdas modificadas
    - Soporte para filtros SQL dinámicos
    """
    
    # Señales
    data_changed = Signal()
    loading_started = Signal()
    loading_finished = Signal(int)  # total de filas
    error_occurred = Signal(str)
    
    # Configuración de paginación
    PAGE_SIZE = 100  # Filas por página
    CACHE_SIZE = 5   # Páginas en cache
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Conexión a BD
        self._engine = None
        self._session = None
        self._table_name = None
        self._metadata = None
        self._table = None
        
        # Datos
        self._columns: List[str] = []
        self._column_types: Dict[str, str] = {}
        self._primary_keys: List[str] = []
        self._total_rows = 0
        
        # Cache de páginas: {page_number: [rows]}
        self._cache: Dict[int, List[tuple]] = {}
        self._cache_order: List[int] = []  # Para LRU
        
        # Cambios pendientes: {(row, col): new_value}
        self._pending_changes: Dict[Tuple[int, int], Any] = {}
        
        # Filtros activos
        self._where_clause = ""
        self._order_by = ""
        
    def connect_to_database(self, db_path: str) -> bool:
        """Conecta a una base de datos SQLite."""
        try:
            self._engine = create_engine(f'sqlite:///{db_path}', echo=False)
            Session = sessionmaker(bind=self._engine)
            self._session = Session()
            self._metadata = MetaData()
            self._metadata.reflect(bind=self._engine)
            logger.info(f"Conectado a: {db_path}")
            return True
        except Exception as e:
            logger.error(f"Error conectando a BD: {e}")
            self.error_occurred.emit(str(e))
            return False
    
    def get_tables(self) -> List[str]:
        """Retorna lista de tablas en la BD."""
        if not self._engine:
            return []
        inspector = inspect(self._engine)
        return inspector.get_table_names()
    
    def get_table_info(self, table_name: str) -> Dict[str, Any]:
        """Obtiene información detallada de una tabla."""
        if not self._engine:
            return {}
        
        inspector = inspect(self._engine)
        columns = inspector.get_columns(table_name)
        pk = inspector.get_pk_constraint(table_name)
        fks = inspector.get_foreign_keys(table_name)
        
        # Contar filas
        with self._engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            row_count = result.scalar()
        
        return {
            'name': table_name,
            'columns': columns,
            'primary_keys': pk.get('constrained_columns', []),
            'foreign_keys': fks,
            'row_count': row_count
        }
    
    def load_table(self, table_name: str, where: str = "", order_by: str = "") -> bool:
        """
        Carga una tabla en el modelo.
        
        Args:
            table_name: Nombre de la tabla
            where: Cláusula WHERE (sin 'WHERE')
            order_by: Cláusula ORDER BY (sin 'ORDER BY')
        """
        if not self._engine:
            return False
        
        self.beginResetModel()
        self.loading_started.emit()
        
        try:
            # Limpiar cache y cambios
            self._cache.clear()
            self._cache_order.clear()
            self._pending_changes.clear()
            
            # Guardar configuración
            self._table_name = table_name
            self._where_clause = where
            self._order_by = order_by
            
            # Obtener metadatos de columnas
            inspector = inspect(self._engine)
            columns_info = inspector.get_columns(table_name)
            pk_info = inspector.get_pk_constraint(table_name)
            
            self._columns = [col['name'] for col in columns_info]
            self._column_types = {col['name']: str(col['type']) for col in columns_info}
            self._primary_keys = pk_info.get('constrained_columns', [])
            
            # Contar total de filas (con filtros)
            count_sql = f"SELECT COUNT(*) FROM {table_name}"
            if where:
                count_sql += f" WHERE {where}"
            
            with self._engine.connect() as conn:
                result = conn.execute(text(count_sql))
                self._total_rows = result.scalar()
            
            logger.info(f"Tabla {table_name} cargada: {self._total_rows} filas, {len(self._columns)} columnas")
            
            self.endResetModel()
            self.loading_finished.emit(self._total_rows)
            return True
            
        except Exception as e:
            logger.error(f"Error cargando tabla: {e}")
            self.error_occurred.emit(str(e))
            self.endResetModel()
            return False
    
    def _fetch_page(self, page: int) -> List[tuple]:
        """Obtiene una página de datos de la BD."""
        if page in self._cache:
            # Actualizar orden LRU
            if page in self._cache_order:
                self._cache_order.remove(page)
            self._cache_order.append(page)
            return self._cache[page]
        
        offset = page * self.PAGE_SIZE
        
        sql = f"SELECT * FROM {self._table_name}"
        if self._where_clause:
            sql += f" WHERE {self._where_clause}"
        if self._order_by:
            sql += f" ORDER BY {self._order_by}"
        sql += f" LIMIT {self.PAGE_SIZE} OFFSET {offset}"
        
        try:
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchall()
            
            # Guardar en cache
            self._cache[page] = rows
            self._cache_order.append(page)
            
            # Limitar tamaño del cache (LRU)
            while len(self._cache) > self.CACHE_SIZE:
                oldest = self._cache_order.pop(0)
                del self._cache[oldest]
            
            return rows
            
        except Exception as e:
            logger.error(f"Error obteniendo página {page}: {e}")
            return []
    
    def _get_row_data(self, row: int) -> Optional[tuple]:
        """Obtiene los datos de una fila específica."""
        page = row // self.PAGE_SIZE
        page_offset = row % self.PAGE_SIZE
        
        page_data = self._fetch_page(page)
        if page_offset < len(page_data):
            return page_data[page_offset]
        return None
    
    # =========================================================================
    # Implementación de QAbstractTableModel
    # =========================================================================
    
    def rowCount(self, parent=QModelIndex()) -> int:
        return self._total_rows
    
    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)
    
    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        
        row, col = index.row(), index.column()
        
        # Verificar si hay un cambio pendiente
        if (row, col) in self._pending_changes:
            value = self._pending_changes[(row, col)]
        else:
            row_data = self._get_row_data(row)
            if row_data is None:
                return None
            value = row_data[col]
        
        if role == Qt.DisplayRole or role == Qt.EditRole:
            if value is None:
                return "" if role == Qt.DisplayRole else None
            return str(value) if role == Qt.DisplayRole else value
        
        elif role == Qt.BackgroundRole:
            # Resaltar celdas modificadas
            if (row, col) in self._pending_changes:
                return QBrush(QColor(255, 255, 200))  # Amarillo claro
            # Resaltar PKs
            if self._columns[col] in self._primary_keys:
                return QBrush(QColor(230, 240, 255))  # Azul muy claro
        
        elif role == Qt.ForegroundRole:
            if value is None:
                return QBrush(QColor(150, 150, 150))  # Gris para NULLs
        
        elif role == Qt.ToolTipRole:
            col_name = self._columns[col]
            col_type = self._column_types.get(col_name, "UNKNOWN")
            is_pk = "🔑 PK" if col_name in self._primary_keys else ""
            return f"{col_name} ({col_type}) {is_pk}\nValor: {value}"
        
        return None
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self._columns):
                col_name = self._columns[section]
                if col_name in self._primary_keys:
                    return f"🔑 {col_name}"
                return col_name
        else:
            return section + 1  # Número de fila (1-indexed)
        
        return None
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        
        # Permitir edición excepto en PKs
        col_name = self._columns[index.column()]
        if col_name not in self._primary_keys:
            flags |= Qt.ItemIsEditable
        
        return flags
    
    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or role != Qt.EditRole:
            return False
        
        row, col = index.row(), index.column()
        col_name = self._columns[col]
        
        # No permitir editar PKs
        if col_name in self._primary_keys:
            return False
        
        # Obtener valor actual
        current_data = self._get_row_data(row)
        if current_data is None:
            return False
        
        current_value = current_data[col]
        
        # Si el valor es igual, no hacer nada
        if str(value) == str(current_value):
            if (row, col) in self._pending_changes:
                del self._pending_changes[(row, col)]
            return False
        
        # Guardar cambio pendiente
        self._pending_changes[(row, col)] = value
        
        # Emitir señal de cambio
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.BackgroundRole])
        self.data_changed.emit()
        
        return True
    
    # =========================================================================
    # Operaciones de edición
    # =========================================================================
    
    def has_pending_changes(self) -> bool:
        """Verifica si hay cambios sin guardar."""
        return len(self._pending_changes) > 0
    
    def get_pending_changes_count(self) -> int:
        """Retorna cantidad de cambios pendientes."""
        return len(self._pending_changes)
    
    def save_changes(self) -> Tuple[int, List[str]]:
        """
        Guarda todos los cambios pendientes en la BD.
        
        Returns:
            (cantidad_guardados, lista_errores)
        """
        if not self._pending_changes:
            return 0, []
        
        saved = 0
        errors = []
        
        # Agrupar cambios por fila
        changes_by_row: Dict[int, Dict[int, Any]] = {}
        for (row, col), value in self._pending_changes.items():
            if row not in changes_by_row:
                changes_by_row[row] = {}
            changes_by_row[row][col] = value
        
        for row, cols_values in changes_by_row.items():
            try:
                # Obtener datos originales de la fila para PKs
                row_data = self._get_row_data(row)
                if row_data is None:
                    errors.append(f"Fila {row}: No encontrada")
                    continue
                
                # Construir cláusula WHERE con PKs
                where_parts = []
                for pk in self._primary_keys:
                    pk_idx = self._columns.index(pk)
                    pk_value = row_data[pk_idx]
                    where_parts.append(f"{pk} = :pk_{pk}")
                
                if not where_parts:
                    # Si no hay PK, usar rowid
                    where_parts.append(f"rowid = :rowid")
                
                # Construir SET clause
                set_parts = []
                params = {}
                
                for col_idx, new_value in cols_values.items():
                    col_name = self._columns[col_idx]
                    set_parts.append(f"{col_name} = :val_{col_name}")
                    params[f"val_{col_name}"] = new_value
                
                # Agregar parámetros de WHERE
                for pk in self._primary_keys:
                    pk_idx = self._columns.index(pk)
                    params[f"pk_{pk}"] = row_data[pk_idx]
                
                if not self._primary_keys:
                    # Calcular rowid
                    params["rowid"] = row + 1  # rowid es 1-indexed en SQLite
                
                # Ejecutar UPDATE
                sql = f"UPDATE {self._table_name} SET {', '.join(set_parts)} WHERE {' AND '.join(where_parts)}"
                
                with self._engine.connect() as conn:
                    conn.execute(text(sql), params)
                    conn.commit()
                
                saved += len(cols_values)
                
                # Limpiar cambios guardados
                for col in cols_values.keys():
                    del self._pending_changes[(row, col)]
                
            except Exception as e:
                errors.append(f"Fila {row}: {str(e)}")
                logger.error(f"Error guardando fila {row}: {e}")
        
        # Invalidar cache para que se recarguen los datos
        self._cache.clear()
        self._cache_order.clear()
        
        # Notificar cambios
        self.layoutChanged.emit()
        
        return saved, errors
    
    def discard_changes(self):
        """Descarta todos los cambios pendientes."""
        if not self._pending_changes:
            return
        
        # Obtener celdas afectadas
        cells = list(self._pending_changes.keys())
        self._pending_changes.clear()
        
        # Notificar cambios
        for row, col in cells:
            index = self.index(row, col)
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.BackgroundRole])
    
    def refresh(self):
        """Recarga los datos de la tabla."""
        self._cache.clear()
        self._cache_order.clear()
        
        # Recontar filas
        if self._table_name:
            count_sql = f"SELECT COUNT(*) FROM {self._table_name}"
            if self._where_clause:
                count_sql += f" WHERE {self._where_clause}"
            
            with self._engine.connect() as conn:
                result = conn.execute(text(count_sql))
                self._total_rows = result.scalar()
        
        self.layoutChanged.emit()
    
    def apply_filter(self, where_clause: str):
        """Aplica un filtro a la tabla."""
        self.load_table(self._table_name, where_clause, self._order_by)
    
    def apply_sort(self, column: int, ascending: bool = True):
        """Ordena por una columna."""
        if 0 <= column < len(self._columns):
            col_name = self._columns[column]
            order = "ASC" if ascending else "DESC"
            self._order_by = f"{col_name} {order}"
            self.load_table(self._table_name, self._where_clause, self._order_by)
    
    # =========================================================================
    # Inserción y eliminación
    # =========================================================================
    
    def insert_row(self, values: Dict[str, Any] = None) -> bool:
        """Inserta una nueva fila."""
        try:
            if values is None:
                values = {}
            
            # Construir INSERT
            cols = list(values.keys()) if values else []
            vals = list(values.values()) if values else []
            
            if cols:
                sql = f"INSERT INTO {self._table_name} ({', '.join(cols)}) VALUES ({', '.join([':' + c for c in cols])})"
                params = {c: v for c, v in zip(cols, vals)}
            else:
                sql = f"INSERT INTO {self._table_name} DEFAULT VALUES"
                params = {}
            
            with self._engine.connect() as conn:
                conn.execute(text(sql), params)
                conn.commit()
            
            # Recargar
            self.refresh()
            return True
            
        except Exception as e:
            logger.error(f"Error insertando fila: {e}")
            self.error_occurred.emit(str(e))
            return False
    
    def delete_rows(self, rows: List[int]) -> Tuple[int, List[str]]:
        """
        Elimina múltiples filas.
        
        Returns:
            (cantidad_eliminadas, lista_errores)
        """
        deleted = 0
        errors = []
        
        for row in sorted(rows, reverse=True):  # Eliminar de abajo hacia arriba
            try:
                row_data = self._get_row_data(row)
                if row_data is None:
                    errors.append(f"Fila {row}: No encontrada")
                    continue
                
                # Construir WHERE con PKs
                where_parts = []
                params = {}
                
                for pk in self._primary_keys:
                    pk_idx = self._columns.index(pk)
                    pk_value = row_data[pk_idx]
                    where_parts.append(f"{pk} = :pk_{pk}")
                    params[f"pk_{pk}"] = pk_value
                
                if not where_parts:
                    where_parts.append("rowid = :rowid")
                    params["rowid"] = row + 1
                
                sql = f"DELETE FROM {self._table_name} WHERE {' AND '.join(where_parts)}"
                
                with self._engine.connect() as conn:
                    conn.execute(text(sql), params)
                    conn.commit()
                
                deleted += 1
                
            except Exception as e:
                errors.append(f"Fila {row}: {str(e)}")
                logger.error(f"Error eliminando fila {row}: {e}")
        
        if deleted > 0:
            self.refresh()
        
        return deleted, errors
    
    # =========================================================================
    # Utilidades
    # =========================================================================
    
    def get_column_info(self) -> List[Dict[str, Any]]:
        """Retorna información de todas las columnas."""
        info = []
        for col in self._columns:
            info.append({
                'name': col,
                'type': self._column_types.get(col, 'UNKNOWN'),
                'is_pk': col in self._primary_keys
            })
        return info
    
    def export_to_csv(self, filepath: str, include_headers: bool = True) -> bool:
        """Exporta la tabla actual a CSV."""
        try:
            import csv
            
            sql = f"SELECT * FROM {self._table_name}"
            if self._where_clause:
                sql += f" WHERE {self._where_clause}"
            if self._order_by:
                sql += f" ORDER BY {self._order_by}"
            
            with self._engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchall()
            
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if include_headers:
                    writer.writerow(self._columns)
                for row in rows:
                    writer.writerow(row)
            
            logger.info(f"Exportado a {filepath}: {len(rows)} filas")
            return True
            
        except Exception as e:
            logger.error(f"Error exportando a CSV: {e}")
            self.error_occurred.emit(str(e))
            return False
    
    def close(self):
        """Cierra la conexión a la BD."""
        if self._session:
            self._session.close()
        if self._engine:
            self._engine.dispose()
