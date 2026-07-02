# src/ui/progress_worker.py
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QApplication
import logging
import traceback
from typing import Callable, Any, Optional
import time

logger = logging.getLogger(__name__)

class WorkerSignals(QObject):
    """Señales para comunicación entre worker y UI"""
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)  # 0-100
    status = Signal(str)    # mensaje de estado
    
class ProgressWorker(QRunnable):
    """Worker genérico con soporte para progreso y manejo de errores"""
    
    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        
    @Slot()
    def run(self):
        """Ejecuta la función en el hilo de fondo"""
        try:
            # Pasar las señales a la función para que pueda reportar progreso
            if 'progress_callback' not in self.kwargs:
                self.kwargs['progress_callback'] = self.signals.progress.emit
            if 'status_callback' not in self.kwargs:
                self.kwargs['status_callback'] = self.signals.status.emit
                
            result = self.fn(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as e:
            logger.error(f"Error en worker: {str(e)}")
            traceback.print_exc()
            self.signals.error.emit((type(e), e, traceback.format_exc()))
        finally:
            self.signals.finished.emit()

class ProgressManager:
    """Gestor de progreso que simplifica el uso de workers con barras de progreso"""
    
    def __init__(self, parent=None):
        self.parent = parent
        self.thread_pool = QThreadPool.globalInstance()
        self.progress_dialog = None
        
    def run_with_progress(self, 
                         task_fn: Callable, 
                         title: str = "Procesando...",
                         description: str = "Por favor espere...",
                         on_success: Optional[Callable] = None,
                         on_error: Optional[Callable] = None,
                         *args, **kwargs):
        """
        Ejecuta una tarea con barra de progreso
        
        Args:
            task_fn: Función a ejecutar
            title: Título de la ventana de progreso
            description: Descripción inicial
            on_success: Callback para éxito (recibe el resultado)
            on_error: Callback para error (recibe la excepción)
        """
        
        # Crear diálogo de progreso
        self.progress_dialog = QProgressDialog(description, "Cancelar", 0, 100, self.parent)
        self.progress_dialog.setWindowTitle(title)
        self.progress_dialog.setModal(True)
        self.progress_dialog.show()
        
        # Crear worker
        worker = ProgressWorker(task_fn, *args, **kwargs)
        
        # Conectar señales
        worker.signals.progress.connect(self.progress_dialog.setValue)
        worker.signals.status.connect(self.progress_dialog.setLabelText)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.result.connect(lambda result: self._on_success(result, on_success))
        worker.signals.error.connect(lambda error: self._on_error(error, on_error))
        
        # Conectar cancelación
        self.progress_dialog.canceled.connect(self._on_canceled)
        
        # Ejecutar
        self.thread_pool.start(worker)
        
    def _on_finished(self):
        """Limpia el diálogo cuando termina"""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
            
    def _on_success(self, result, callback):
        """Maneja el éxito"""
        if callback:
            callback(result)
            
    def _on_error(self, error, callback):
        """Maneja errores"""
        exc_type, exc_value, exc_traceback = error
        logger.error(f"Error en tarea: {exc_value}")
        
        if callback:
            callback(exc_value)
        else:
            # Mostrar error por defecto
            QMessageBox.critical(
                self.parent, 
                "Error", 
                f"Ocurrió un error durante el procesamiento:\n\n{str(exc_value)}"
            )
            
    def _on_canceled(self):
        """Maneja cancelación (nota: no detiene el hilo, solo oculta el diálogo)"""
        logger.info("Operación cancelada por el usuario")