# -*- coding: utf-8 -*-
"""
historical_exporter_dialog.py
==============================
Dialogo UI para el Exportador de Predicciones Historicas - SAD v6

Permite configurar y lanzar la exportacion desde la interfaz grafica,
con barra de progreso, seleccion de modelos y visualizacion de resultados.
"""

import os
import sys
import json
import logging
from datetime import date, datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QSpinBox,
    QDateEdit, QProgressBar, QTextEdit, QGroupBox,
    QMessageBox, QFrame, QSizePolicy, QScrollArea, QWidget
)
from PySide6.QtCore import Qt, QThread, Signal, QDate
from PySide6.QtGui import QFont, QColor, QTextCursor

logger = logging.getLogger(__name__)


# ============================================================================
# WORKER THREAD
# ============================================================================

class ExporterWorker(QThread):
    """Hilo para ejecutar la exportacion sin congelar la UI."""
    
    progress = Signal(int, str)       # (porcentaje, mensaje)
    finished = Signal(dict)           # stats dict
    error = Signal(str)               # mensaje de error
    log_message = Signal(str)         # mensajes para el log
    
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._cancelled = False
    
    def cancel(self):
        self._cancelled = True
    
    def run(self):
        try:
            self.log_message.emit("Inicializando exportador...")
            
            # Importar el exportador
            try:
                from historical_predictions_exporter import HistoricalPredictionsExporter
            except ImportError:
                try:
                    src_dir = self.config.get('project_root', os.getcwd())
                    if os.path.join(src_dir, 'src') not in sys.path:
                        sys.path.insert(0, os.path.join(src_dir, 'src'))
                    from historical_predictions_exporter import HistoricalPredictionsExporter
                except ImportError:
                    self.error.emit(
                        "No se encontro 'historical_predictions_exporter.py'.\n\n"
                        "Asegurate de que el archivo este en src/ o en la raiz del proyecto."
                    )
                    return
            
            # Crear instancia
            exporter = HistoricalPredictionsExporter(
                project_root=self.config.get('project_root')
            )
            
            self.log_message.emit(f"Raiz del proyecto: {exporter.project_root}")
            self.log_message.emit(f"Directorio de salida: {exporter.output_dir}")
            
            # Callback de progreso
            def on_progress(pct, msg):
                if self._cancelled:
                    raise InterruptedError("Exportacion cancelada por el usuario")
                self.progress.emit(pct, msg)
                self.log_message.emit(f"[{pct:3d}%] {msg}")
            
            # Ejecutar
            stats = exporter.run(
                start_date=self.config['start_date'],
                end_date=self.config['end_date'],
                league_ids=self.config.get('league_ids'),
                enable_culebras=self.config.get('enable_culebras', True),
                enable_goals=self.config.get('enable_goals', True),
                enable_constants=self.config.get('enable_constants', True),
                progress_callback=on_progress,
                max_fixtures=self.config.get('max_fixtures'),
            )
            
            if not self._cancelled:
                self.finished.emit(stats)
            
        except InterruptedError:
            self.log_message.emit("Exportacion cancelada.")
            self.error.emit("Exportacion cancelada por el usuario.")
        except Exception as e:
            logger.error(f"Error en exportacion: {e}", exc_info=True)
            self.error.emit(f"Error durante la exportacion:\n\n{str(e)}")


# ============================================================================
# DIALOGO PRINCIPAL
# ============================================================================

class HistoricalExporterDialog(QDialog):
    """Dialogo para configurar y ejecutar la exportacion de predicciones historicas."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Exportador de Predicciones Historicas")
        self.setMinimumSize(750, 700)
        self.resize(800, 780)
        self.worker = None
        self._build_ui()
    
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # ─── HEADER ───
        header = QLabel("Exportador de Predicciones Historicas")
        header.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #1a1a2e;
            padding-bottom: 5px;
        """)
        header.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header)
        
        subtitle = QLabel(
            "Genera predicciones retroactivas de los 3 modelos ML sobre partidos ya jugados.\n"
            "Util para calibracion de umbrales, evaluacion de accuracy y entrenamiento de meta-modelo."
        )
        subtitle.setStyleSheet("color: #666; font-size: 11px;")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        main_layout.addWidget(subtitle)
        
        # Linea decorativa
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #9C27B0; max-height: 2px;")
        line.setFixedHeight(2)
        main_layout.addWidget(line)
        
        # ─── CONFIGURACION ───
        config_layout = QHBoxLayout()
        config_layout.setSpacing(15)
        
        # --- Columna izquierda: Fechas ---
        dates_group = QGroupBox("Rango de Fechas")
        dates_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                margin-top: 1.5ex;
                padding-top: 15px;
            }
            QGroupBox::title {
                color: #9C27B0;
            }
        """)
        dates_layout = QGridLayout(dates_group)
        dates_layout.setSpacing(10)
        
        dates_layout.addWidget(QLabel("Desde:"), 0, 0)
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDate(QDate(2024, 1, 1))
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setStyleSheet("padding: 6px; border-radius: 4px;")
        dates_layout.addWidget(self.date_start, 0, 1)
        
        dates_layout.addWidget(QLabel("Hasta:"), 1, 0)
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDate(QDate(2024, 12, 31))
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setStyleSheet("padding: 6px; border-radius: 4px;")
        dates_layout.addWidget(self.date_end, 1, 1)
        
        # Max fixtures
        dates_layout.addWidget(QLabel("Max partidos:"), 2, 0)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(0, 999999)
        self.spin_max.setValue(0)
        self.spin_max.setSpecialValueText("Sin limite")
        self.spin_max.setToolTip("0 = procesar todos los partidos del rango")
        self.spin_max.setStyleSheet("padding: 6px; border-radius: 4px;")
        dates_layout.addWidget(self.spin_max, 2, 1)
        
        config_layout.addWidget(dates_group)
        
        # --- Columna derecha: Modelos ---
        models_group = QGroupBox("Modelos ML a Ejecutar")
        models_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                margin-top: 1.5ex;
                padding-top: 15px;
            }
            QGroupBox::title {
                color: #9C27B0;
            }
        """)
        models_layout = QVBoxLayout(models_group)
        models_layout.setSpacing(12)
        
        self.chk_culebras = QCheckBox("Ley de las Culebras")
        self.chk_culebras.setChecked(True)
        self.chk_culebras.setToolTip("ICF, probabilidades 1X2, ml_break_score, favorito")
        self.chk_culebras.setStyleSheet("font-size: 13px;")
        models_layout.addWidget(self.chk_culebras)
        
        lbl_cul = QLabel("  ICF, 1X2, ml_break_score, favorito")
        lbl_cul.setStyleSheet("color: #888; font-size: 10px; margin-left: 20px;")
        models_layout.addWidget(lbl_cul)
        
        self.chk_goals = QCheckBox("Ley del Marcador (Goles Poisson)")
        self.chk_goals.setChecked(True)
        self.chk_goals.setToolTip("Lambdas, Over/Under, BTTS, top score")
        self.chk_goals.setStyleSheet("font-size: 13px;")
        models_layout.addWidget(self.chk_goals)
        
        lbl_gol = QLabel("  Lambdas, Over/Under, BTTS, top score")
        lbl_gol.setStyleSheet("color: #888; font-size: 10px; margin-left: 20px;")
        models_layout.addWidget(lbl_gol)
        
        self.chk_constants = QCheckBox("Ley de las Constantes")
        self.chk_constants.setChecked(True)
        self.chk_constants.setToolTip("Prediccion de cambio K por equipo/constante")
        self.chk_constants.setStyleSheet("font-size: 13px;")
        models_layout.addWidget(self.chk_constants)
        
        lbl_const = QLabel("  Cambio de K (rendimiento + goles)")
        lbl_const.setStyleSheet("color: #888; font-size: 10px; margin-left: 20px;")
        models_layout.addWidget(lbl_const)
        
        models_layout.addStretch()
        
        config_layout.addWidget(models_group)
        
        main_layout.addLayout(config_layout)
        
        # ─── BOTONES DE ACCION ───
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.btn_run = QPushButton("Iniciar Exportacion")
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 30px;
                font-size: 14px;
                font-weight: bold;
                min-width: 200px;
            }
            QPushButton:hover { background-color: #7B1FA2; }
            QPushButton:pressed { background-color: #6A1B9A; }
            QPushButton:disabled { background-color: #CE93D8; }
        """)
        self.btn_run.clicked.connect(self.start_export)
        btn_layout.addWidget(self.btn_run)
        
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #c82333; }
            QPushButton:disabled { background-color: #E57373; }
        """)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_export)
        btn_layout.addWidget(self.btn_cancel)
        
        self.btn_open_folder = QPushButton("Abrir Carpeta")
        self.btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #218838; }
            QPushButton:disabled { background-color: #A5D6A7; }
        """)
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        btn_layout.addWidget(self.btn_open_folder)
        
        btn_layout.addStretch()
        
        self.btn_close = QPushButton("Cerrar")
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_close)
        
        main_layout.addLayout(btn_layout)
        
        # ─── PROGRESO ───
        progress_group = QGroupBox("Progreso")
        progress_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                margin-top: 1.5ex;
                padding-top: 15px;
            }
            QGroupBox::title { color: #9C27B0; }
        """)
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                text-align: center;
                height: 25px;
                background: #F5F5F5;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #9C27B0, stop:1 #E040FB
                );
                border-radius: 5px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        self.lbl_status = QLabel("Listo para iniciar")
        self.lbl_status.setStyleSheet("color: #666; font-size: 12px;")
        progress_layout.addWidget(self.lbl_status)
        
        main_layout.addWidget(progress_group)
        
        # ─── LOG / RESULTADOS ───
        results_group = QGroupBox("Log y Resultados")
        results_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #E0E0E0;
                border-radius: 8px;
                margin-top: 1.5ex;
                padding-top: 15px;
            }
            QGroupBox::title { color: #9C27B0; }
        """)
        results_layout = QVBoxLayout(results_group)
        
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(180)
        self.txt_log.setStyleSheet("""
            QTextEdit {
                background: #1a1a2e;
                color: #00FF88;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        self.txt_log.setPlaceholderText("Los mensajes de progreso y resultados apareceran aqui...")
        results_layout.addWidget(self.txt_log)
        
        main_layout.addWidget(results_group)
        
        # Estado interno
        self._output_dir = None
    
    # ════════════════════════════════════════════════
    # ACCIONES
    # ════════════════════════════════════════════════
    
    def _find_project_root(self) -> str:
        """Busca la raiz del proyecto donde estan sad.db, constants.db.
        
        IMPORTANTE: Las DBs estan al MISMO NIVEL que src/, no dentro.
        Estructura:
            D:/VSCode Ejercicios 02/
                sad.db          <-- AQUI
                constants.db
                src/
                    historical_exporter_dialog.py  (este archivo)
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(script_dir)
        
        # Si estamos dentro de src/, las DBs estan en el padre
        if os.path.basename(script_dir).lower() == 'src':
            if os.path.exists(os.path.join(parent_dir, 'sad.db')):
                return parent_dir
        
        # Prioridad 1: Padre del directorio del script
        if os.path.exists(os.path.join(parent_dir, 'sad.db')):
            return parent_dir
        
        # Prioridad 2: Directorio del script mismo
        if os.path.exists(os.path.join(script_dir, 'sad.db')):
            return script_dir
        
        # Prioridad 3: CWD y busqueda hacia arriba
        cwd = os.getcwd()
        check = cwd
        for _ in range(6):
            if os.path.exists(os.path.join(check, 'sad.db')):
                return check
            check = os.path.dirname(check)
        
        return parent_dir
    
    def start_export(self):
        """Inicia la exportacion en un hilo secundario."""
        # Validar
        qd_start = self.date_start.date()
        qd_end = self.date_end.date()
        
        start = date(qd_start.year(), qd_start.month(), qd_start.day())
        end = date(qd_end.year(), qd_end.month(), qd_end.day())
        
        if start > end:
            QMessageBox.warning(self, "Fechas invalidas",
                                "La fecha de inicio debe ser anterior a la fecha fin.")
            return
        
        if not (self.chk_culebras.isChecked() or 
                self.chk_goals.isChecked() or 
                self.chk_constants.isChecked()):
            QMessageBox.warning(self, "Sin modelos",
                                "Debes seleccionar al menos un modelo ML.")
            return
        
        # Preparar config
        max_fx = self.spin_max.value()
        project_root = self._find_project_root()
        
        config = {
            'start_date': start,
            'end_date': end,
            'enable_culebras': self.chk_culebras.isChecked(),
            'enable_goals': self.chk_goals.isChecked(),
            'enable_constants': self.chk_constants.isChecked(),
            'max_fixtures': max_fx if max_fx > 0 else None,
            'project_root': project_root,
        }
        
        # UI
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_open_folder.setEnabled(False)
        self.progress_bar.setValue(0)
        self.txt_log.clear()
        
        self._log(f"Proyecto: {project_root}")
        self._log(f"Periodo: {start} a {end}")
        modelos = []
        if config['enable_culebras']: modelos.append("Culebras")
        if config['enable_goals']: modelos.append("Goles")
        if config['enable_constants']: modelos.append("Constantes")
        self._log(f"Modelos: {', '.join(modelos)}")
        if max_fx > 0:
            self._log(f"Limite: {max_fx} partidos (modo prueba)")
        self._log("=" * 50)
        
        # Lanzar worker
        self.worker = ExporterWorker(config)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.log_message.connect(self._log)
        self.worker.start()
    
    def cancel_export(self):
        """Cancela la exportacion en curso."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lbl_status.setText("Cancelando...")
            self._log("Solicitando cancelacion...")
    
    def open_output_folder(self):
        """Abre la carpeta de resultados en el explorador de archivos."""
        if self._output_dir and os.path.isdir(self._output_dir):
            import subprocess
            if sys.platform == 'win32':
                os.startfile(self._output_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self._output_dir])
            else:
                subprocess.Popen(['xdg-open', self._output_dir])
        else:
            QMessageBox.information(self, "Info", 
                                    "No hay carpeta de resultados disponible aun.")
    
    # ════════════════════════════════════════════════
    # SLOTS
    # ════════════════════════════════════════════════
    
    def _on_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(msg)
    
    def _on_finished(self, stats: dict):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Exportacion completada!")
        
        # Guardar output dir
        if 'csv_main' in stats:
            self._output_dir = os.path.dirname(stats['csv_main'])
            self.btn_open_folder.setEnabled(True)
        
        # Mostrar resumen
        self._log("")
        self._log("=" * 50)
        self._log("EXPORTACION COMPLETADA")
        self._log("=" * 50)
        self._log(f"Partidos procesados: {stats.get('total_fixtures', 0)}")
        self._log(f"Registros constantes: {stats.get('total_constants_rows', 0)}")
        self._log(f"Periodo: {stats.get('period', 'N/A')}")
        
        successes = stats.get('successes', {})
        errors = stats.get('errors', {})
        self._log("")
        self._log("--- Resultados por Modelo ---")
        
        if successes.get('culebras', 0) > 0 or errors.get('culebras', 0) > 0:
            self._log(f"  Culebras: {successes.get('culebras', 0)} OK, "
                      f"{errors.get('culebras', 0)} errores")
            if 'culebras_favorite_accuracy' in stats:
                acc = stats['culebras_favorite_accuracy']
                self._log(f"    Accuracy favorito: {acc:.2%}")
            if 'culebras_ml_score_mean' in stats:
                self._log(f"    ml_break_score: media={stats['culebras_ml_score_mean']:.4f}, "
                          f"std={stats.get('culebras_ml_score_std', 0):.4f}")
                self._log(f"    Percentiles: P25={stats.get('culebras_ml_score_p25', 0):.4f}, "
                          f"P50={stats.get('culebras_ml_score_p50', 0):.4f}, "
                          f"P75={stats.get('culebras_ml_score_p75', 0):.4f}")
        
        if successes.get('goals', 0) > 0 or errors.get('goals', 0) > 0:
            self._log(f"  Goles: {successes.get('goals', 0)} OK, "
                      f"{errors.get('goals', 0)} errores")
            if 'goals_over25_accuracy' in stats:
                self._log(f"    Over 2.5 accuracy: {stats['goals_over25_accuracy']:.2%}")
            if 'goals_btts_accuracy' in stats:
                self._log(f"    BTTS accuracy: {stats['goals_btts_accuracy']:.2%}")
            if 'goals_top_score_hit_rate' in stats:
                self._log(f"    Top score hit rate: {stats['goals_top_score_hit_rate']:.2%}")
        
        if successes.get('constants', 0) > 0 or errors.get('constants', 0) > 0:
            self._log(f"  Constantes: {successes.get('constants', 0)} OK, "
                      f"{errors.get('constants', 0)} errores")
            if 'constants_accuracy' in stats:
                self._log(f"    Accuracy global: {stats['constants_accuracy']:.2%}")
        
        self._log("")
        self._log("--- Archivos Generados ---")
        if stats.get('csv_main'):
            self._log(f"  CSV principal: {os.path.basename(stats['csv_main'])}")
        if stats.get('csv_constants'):
            self._log(f"  CSV constantes: {os.path.basename(stats['csv_constants'])}")
        if stats.get('sqlite_db'):
            self._log(f"  SQLite: {os.path.basename(stats['sqlite_db'])}")
        if self._output_dir:
            self._log(f"  Carpeta: {self._output_dir}")
    
    def _on_error(self, error_msg: str):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText("Error en la exportacion")
        self._log(f"\nERROR: {error_msg}")
        
        QMessageBox.critical(self, "Error de Exportacion", error_msg)
    
    def _log(self, message: str):
        """Agrega un mensaje al log."""
        self.txt_log.append(message)
        # Auto-scroll al final
        cursor = self.txt_log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.txt_log.setTextCursor(cursor)
    
    def closeEvent(self, event):
        """Manejo de cierre: cancelar worker si esta corriendo."""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "Exportacion en curso",
                "Hay una exportacion en curso. Deseas cancelarla y cerrar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.worker.cancel()
                self.worker.wait(5000)
                event.accept()
            else:
                event.ignore()
                return
        event.accept()