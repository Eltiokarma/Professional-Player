# src/ui/constants_repair_tool.py
# -*- coding: utf-8 -*-
"""
🔧 HERRAMIENTA DE DIAGNÓSTICO Y REPARACIÓN DE CONSTANTS.DB
===========================================================
Detecta y repara:
- Partidos no terminados insertados por error
- Partidos terminados con q=NULL (datos corruptos)
- Equipos con K congelado
"""

import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QProgressBar, QLabel, QGroupBox, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)


class DiagnosticWorker(QThread):
    """Worker para ejecutar diagnóstico en background."""
    progress = Signal(str)
    finished = Signal(dict)
    
    def __init__(self, sad_path: str, const_path: str):
        super().__init__()
        self.sad_path = sad_path
        self.const_path = const_path
    
    def run(self):
        import sqlite3
        results = {}
        
        try:
            const = sqlite3.connect(self.const_path)
            const.execute(f"ATTACH DATABASE '{self.sad_path}' AS sad")
            
            # 1. Total registros
            self.progress.emit("📊 Contando registros totales...")
            cur = const.execute("SELECT COUNT(*) FROM constants")
            results['total_registros'] = cur.fetchone()[0]
            
            # 2. Registros basura (no terminados)
            self.progress.emit("🔍 Buscando partidos no terminados...")
            cur = const.execute("""
                SELECT COUNT(*) FROM constants
                WHERE fixture_id IN (
                    SELECT id FROM sad.fixtures WHERE status_long != 'Match Finished'
                )
            """)
            results['registros_no_terminados'] = cur.fetchone()[0]
            
            # 3. Desglose por status
            self.progress.emit("📋 Analizando status de fixtures...")
            cur = const.execute("""
                SELECT f.status_long, COUNT(*) 
                FROM constants c
                JOIN sad.fixtures f ON c.fixture_id = f.id
                WHERE f.status_long != 'Match Finished'
                GROUP BY f.status_long
                ORDER BY COUNT(*) DESC
            """)
            results['desglose_status'] = list(cur)
            
            # 4. Partidos terminados con q=NULL
            self.progress.emit("🔍 Buscando partidos con datos corruptos...")
            cur = const.execute("""
                SELECT COUNT(*) FROM constants c
                JOIN sad.fixtures f ON c.fixture_id = f.id
                WHERE f.status_long = 'Match Finished'
                AND f.goals_home IS NOT NULL
                AND c.q_local IS NULL AND c.q_visita IS NULL
            """)
            results['registros_q_null'] = cur.fetchone()[0]
            
            # 5. Equipos con último registro basura (K congelado)
            self.progress.emit("🔍 Buscando equipos con K congelado...")
            cur = const.execute("""
                WITH ultimos AS (
                    SELECT team_id, fixture_id,
                           ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY date DESC) as rn
                    FROM constants
                )
                SELECT COUNT(DISTINCT u.team_id)
                FROM ultimos u
                JOIN sad.fixtures f ON u.fixture_id = f.id
                WHERE u.rn = 1 AND f.status_long != 'Match Finished'
            """)
            results['equipos_k_congelado'] = cur.fetchone()[0]
            
            # 6. Cobertura actual
            self.progress.emit("📊 Calculando cobertura...")
            cur = const.execute("""
                SELECT COUNT(*) FROM sad.fixtures 
                WHERE status_long = 'Match Finished' AND goals_home IS NOT NULL
            """)
            results['fixtures_terminados'] = cur.fetchone()[0]
            
            cur = const.execute("SELECT COUNT(DISTINCT fixture_id) FROM constants")
            results['fixtures_en_constants'] = cur.fetchone()[0]
            
            # 7. Equipos que necesitarían recálculo
            self.progress.emit("📊 Contando equipos a recalcular...")
            cur = const.execute("""
                SELECT COUNT(DISTINCT team_id) FROM (
                    SELECT DISTINCT f.home_team_id as team_id FROM sad.fixtures f
                    WHERE f.status_long = 'Match Finished'
                    AND f.id NOT IN (SELECT fixture_id FROM constants WHERE q_local IS NOT NULL OR q_visita IS NOT NULL)
                    UNION
                    SELECT DISTINCT f.away_team_id as team_id FROM sad.fixtures f
                    WHERE f.status_long = 'Match Finished'
                    AND f.id NOT IN (SELECT fixture_id FROM constants WHERE q_local IS NOT NULL OR q_visita IS NOT NULL)
                )
            """)
            results['equipos_a_recalcular'] = cur.fetchone()[0]
            
            const.close()
            results['success'] = True
            
        except Exception as e:
            results['success'] = False
            results['error'] = str(e)
            logger.error(f"Error en diagnóstico: {e}")
        
        self.finished.emit(results)


class RepairWorker(QThread):
    """Worker para ejecutar reparación en background."""
    progress = Signal(str)
    step_progress = Signal(int, int)  # current, total
    finished = Signal(dict)
    
    def __init__(self, sad_path: str, const_path: str, do_recalc: bool = True):
        super().__init__()
        self.sad_path = sad_path
        self.const_path = const_path
        self.do_recalc = do_recalc
        self._stop = False
    
    def stop(self):
        self._stop = True
    
    def run(self):
        import sqlite3
        results = {
            'eliminados_no_terminados': 0,
            'eliminados_q_null': 0,
            'equipos_recalculados': 0,
            'errores_recalculo': 0
        }
        
        try:
            # ══════════════════════════════════════════════════════
            # PASO 1: Eliminar registros de partidos no terminados
            # ══════════════════════════════════════════════════════
            self.progress.emit("🗑️ PASO 1: Eliminando partidos no terminados...")
            
            const = sqlite3.connect(self.const_path)
            const.execute(f"ATTACH DATABASE '{self.sad_path}' AS sad")
            
            cur = const.execute("SELECT COUNT(*) FROM constants")
            antes = cur.fetchone()[0]
            
            const.execute("""
                DELETE FROM constants
                WHERE fixture_id IN (
                    SELECT id FROM sad.fixtures 
                    WHERE status_long != 'Match Finished'
                )
            """)
            const.commit()
            
            cur = const.execute("SELECT COUNT(*) FROM constants")
            despues = cur.fetchone()[0]
            results['eliminados_no_terminados'] = antes - despues
            
            self.progress.emit(f"   ✓ Eliminados {results['eliminados_no_terminados']:,} registros")
            
            if self._stop:
                const.close()
                results['cancelled'] = True
                self.finished.emit(results)
                return
            
            # ══════════════════════════════════════════════════════
            # PASO 2: Eliminar registros con q=NULL pero terminados
            # ══════════════════════════════════════════════════════
            self.progress.emit("🗑️ PASO 2: Eliminando registros corruptos (q=NULL)...")
            
            antes = despues
            
            const.execute("""
                DELETE FROM constants
                WHERE q_local IS NULL AND q_visita IS NULL
                AND fixture_id IN (
                    SELECT id FROM sad.fixtures 
                    WHERE status_long = 'Match Finished'
                    AND goals_home IS NOT NULL
                )
            """)
            const.commit()
            
            cur = const.execute("SELECT COUNT(*) FROM constants")
            despues = cur.fetchone()[0]
            results['eliminados_q_null'] = antes - despues
            
            self.progress.emit(f"   ✓ Eliminados {results['eliminados_q_null']:,} registros")
            
            if self._stop:
                const.close()
                results['cancelled'] = True
                self.finished.emit(results)
                return
            
            # ══════════════════════════════════════════════════════
            # PASO 3: Identificar equipos a recalcular
            # ══════════════════════════════════════════════════════
            self.progress.emit("📋 PASO 3: Identificando equipos a recalcular...")
            
            cur = const.execute("""
                SELECT DISTINCT team_id FROM (
                    SELECT DISTINCT f.home_team_id as team_id FROM sad.fixtures f
                    WHERE f.status_long = 'Match Finished'
                    AND f.goals_home IS NOT NULL
                    AND f.id NOT IN (SELECT fixture_id FROM constants)
                    UNION
                    SELECT DISTINCT f.away_team_id as team_id FROM sad.fixtures f
                    WHERE f.status_long = 'Match Finished'
                    AND f.goals_home IS NOT NULL
                    AND f.id NOT IN (SELECT fixture_id FROM constants)
                )
            """)
            equipos = [row[0] for row in cur]
            
            self.progress.emit(f"   ✓ {len(equipos)} equipos necesitan recálculo")
            
            const.close()
            
            if self._stop:
                results['cancelled'] = True
                self.finished.emit(results)
                return
            
            # ══════════════════════════════════════════════════════
            # PASO 4: Recalcular equipos (opcional)
            # ══════════════════════════════════════════════════════
            if self.do_recalc and equipos:
                self.progress.emit(f"🔄 PASO 4: Recalculando {len(equipos)} equipos...")
                
                try:
                    from utils.constants_calculator import ConstantsCalculator
                    
                    with ConstantsCalculator() as calc:
                        for i, team_id in enumerate(equipos, 1):
                            if self._stop:
                                results['cancelled'] = True
                                break
                            
                            try:
                                result = calc.full_recalculate_team(team_id)
                                if result:
                                    results['equipos_recalculados'] += 1
                                else:
                                    results['equipos_recalculados'] += 1  # Sin datos no es error
                            except Exception as e:
                                results['errores_recalculo'] += 1
                                logger.warning(f"Error recalculando equipo {team_id}: {e}")
                            
                            self.step_progress.emit(i, len(equipos))
                            
                            if i % 20 == 0:
                                self.progress.emit(f"   Procesados {i}/{len(equipos)}...")
                    
                    self.progress.emit(f"   ✓ Recalculados {results['equipos_recalculados']} equipos")
                    if results['errores_recalculo'] > 0:
                        self.progress.emit(f"   ⚠️ {results['errores_recalculo']} errores")
                        
                except ImportError as e:
                    self.progress.emit(f"   ❌ No se pudo importar ConstantsCalculator: {e}")
                    results['error_recalc'] = str(e)
            
            results['success'] = True
            
        except Exception as e:
            results['success'] = False
            results['error'] = str(e)
            logger.error(f"Error en reparación: {e}")
        
        self.finished.emit(results)


class ConstantsRepairDialog(QDialog):
    """Diálogo de diagnóstico y reparación de constants.db"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔧 Diagnóstico y Reparación de Constants")
        self.setMinimumSize(700, 600)
        self.resize(750, 650)
        
        self.worker = None
        self._get_db_paths()
        self._build_ui()
    
    def _get_db_paths(self):
        """Obtiene las rutas de las bases de datos."""
        import os
        
        # Intentar obtener desde database_manager
        try:
            from data.database_manager import ORIG_ENGINE, CONST_ENGINE
            self.sad_path = ORIG_ENGINE.url.database
            self.const_path = CONST_ENGINE.url.database
        except:
            # Fallback a rutas por defecto
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.sad_path = os.path.join(base_dir, 'sad.db')
            self.const_path = os.path.join(base_dir, 'constants.db')
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # ═══════════════════════════════════════════════════════
        # HEADER
        # ═══════════════════════════════════════════════════════
        header = QLabel("🔧 Diagnóstico y Reparación de Constants.db")
        header.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #1a1a2e;
            padding: 10px 0;
        """)
        layout.addWidget(header)
        
        # Info de rutas
        paths_label = QLabel(f"📁 sad.db: {self.sad_path}\n📁 constants.db: {self.const_path}")
        paths_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(paths_label)
        
        # ═══════════════════════════════════════════════════════
        # ÁREA DE RESULTADOS
        # ═══════════════════════════════════════════════════════
        results_group = QGroupBox("📊 Resultados del Diagnóstico")
        results_layout = QVBoxLayout(results_group)
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setFont(QFont("Consolas", 10))
        self.results_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        self.results_text.setPlainText("Presiona 'Ejecutar Diagnóstico' para analizar constants.db")
        results_layout.addWidget(self.results_text)
        
        layout.addWidget(results_group)
        
        # ═══════════════════════════════════════════════════════
        # BARRA DE PROGRESO
        # ═══════════════════════════════════════════════════════
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 5px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #28A745;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # ═══════════════════════════════════════════════════════
        # OPCIONES
        # ═══════════════════════════════════════════════════════
        options_layout = QHBoxLayout()
        
        self.chk_recalc = QCheckBox("🔄 Recalcular equipos afectados después de limpiar")
        self.chk_recalc.setChecked(True)
        self.chk_recalc.setStyleSheet("font-size: 12px;")
        options_layout.addWidget(self.chk_recalc)
        
        options_layout.addStretch()
        layout.addLayout(options_layout)
        
        # ═══════════════════════════════════════════════════════
        # BOTONES
        # ═══════════════════════════════════════════════════════
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        self.btn_diagnose = QPushButton("🔍 Ejecutar Diagnóstico")
        self.btn_diagnose.setStyleSheet("""
            QPushButton {
                background-color: #007BFF;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #0056b3; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.btn_diagnose.clicked.connect(self.run_diagnostic)
        buttons_layout.addWidget(self.btn_diagnose)
        
        self.btn_repair = QPushButton("🔧 Ejecutar Reparación")
        self.btn_repair.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1e7e34; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.btn_repair.clicked.connect(self.run_repair)
        self.btn_repair.setEnabled(False)
        buttons_layout.addWidget(self.btn_repair)
        
        self.btn_cancel = QPushButton("⏹️ Cancelar")
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
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.btn_cancel.clicked.connect(self.cancel_operation)
        self.btn_cancel.setEnabled(False)
        buttons_layout.addWidget(self.btn_cancel)
        
        buttons_layout.addStretch()
        
        btn_close = QPushButton("❌ Cerrar")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #6C757D;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #5a6268; }
        """)
        btn_close.clicked.connect(self.close)
        buttons_layout.addWidget(btn_close)
        
        layout.addLayout(buttons_layout)
        
        # Estado
        self.diagnostic_results = None
    
    def log(self, message: str):
        """Añade mensaje al log."""
        self.results_text.append(message)
        # Auto-scroll
        scrollbar = self.results_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def run_diagnostic(self):
        """Ejecuta el diagnóstico."""
        self.results_text.clear()
        self.log("=" * 60)
        self.log("🔍 INICIANDO DIAGNÓSTICO DE CONSTANTS.DB")
        self.log(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log("=" * 60)
        self.log("")
        
        self.btn_diagnose.setEnabled(False)
        self.btn_repair.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        
        self.worker = DiagnosticWorker(self.sad_path, self.const_path)
        self.worker.progress.connect(self.log)
        self.worker.finished.connect(self.on_diagnostic_finished)
        self.worker.start()
    
    def on_diagnostic_finished(self, results: dict):
        """Callback cuando termina el diagnóstico."""
        self.progress_bar.setVisible(False)
        self.btn_diagnose.setEnabled(True)
        
        if not results.get('success'):
            self.log(f"\n❌ ERROR: {results.get('error', 'Error desconocido')}")
            return
        
        self.diagnostic_results = results
        
        # Mostrar resultados
        self.log("")
        self.log("=" * 60)
        self.log("📊 RESULTADOS DEL DIAGNÓSTICO")
        self.log("=" * 60)
        self.log("")
        self.log(f"📁 Total registros en constants.db: {results['total_registros']:,}")
        self.log("")
        
        # Problemas encontrados
        total_problemas = results['registros_no_terminados'] + results['registros_q_null']
        
        if total_problemas == 0:
            self.log("✅ ¡NO SE ENCONTRARON PROBLEMAS!")
            self.log("")
            self.log(f"📊 Cobertura: {results['fixtures_en_constants']:,} / {results['fixtures_terminados']:,} fixtures")
            cobertura = results['fixtures_en_constants'] * 100 / max(results['fixtures_terminados'], 1)
            self.log(f"   ({cobertura:.1f}%)")
        else:
            self.log("🔴 PROBLEMAS ENCONTRADOS:")
            self.log("")
            self.log(f"   • Partidos no terminados: {results['registros_no_terminados']:,}")
            
            if results['desglose_status']:
                for status, count in results['desglose_status'][:5]:
                    self.log(f"      - {status}: {count:,}")
            
            self.log(f"   • Partidos con q=NULL (corruptos): {results['registros_q_null']:,}")
            self.log(f"   • Equipos con K congelado: {results['equipos_k_congelado']:,}")
            self.log("")
            self.log(f"📊 Total a limpiar: {total_problemas:,} registros")
            self.log(f"📊 Equipos a recalcular: {results['equipos_a_recalcular']:,}")
            self.log("")
            self.log("💡 Presiona 'Ejecutar Reparación' para corregir estos problemas")
            
            self.btn_repair.setEnabled(True)
        
        self.log("")
        self.log("=" * 60)
    
    def run_repair(self):
        """Ejecuta la reparación."""
        if not self.diagnostic_results:
            QMessageBox.warning(self, "Aviso", "Ejecuta primero el diagnóstico")
            return
        
        total = (self.diagnostic_results['registros_no_terminados'] + 
                 self.diagnostic_results['registros_q_null'])
        
        reply = QMessageBox.question(
            self,
            "Confirmar Reparación",
            f"Se eliminarán {total:,} registros basura y se recalcularán "
            f"{self.diagnostic_results['equipos_a_recalcular']:,} equipos.\n\n"
            "¿Deseas continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self.log("")
        self.log("=" * 60)
        self.log("🔧 INICIANDO REPARACIÓN")
        self.log("=" * 60)
        self.log("")
        
        self.btn_diagnose.setEnabled(False)
        self.btn_repair.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        do_recalc = self.chk_recalc.isChecked()
        
        self.worker = RepairWorker(self.sad_path, self.const_path, do_recalc)
        self.worker.progress.connect(self.log)
        self.worker.step_progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_repair_finished)
        self.worker.start()
    
    def update_progress(self, current: int, total: int):
        """Actualiza la barra de progreso."""
        if total > 0:
            self.progress_bar.setValue(int(current * 100 / total))
    
    def on_repair_finished(self, results: dict):
        """Callback cuando termina la reparación."""
        self.progress_bar.setVisible(False)
        self.btn_diagnose.setEnabled(True)
        self.btn_repair.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        
        self.log("")
        self.log("=" * 60)
        self.log("📊 RESUMEN DE REPARACIÓN")
        self.log("=" * 60)
        self.log("")
        
        if results.get('cancelled'):
            self.log("⚠️ Operación cancelada por el usuario")
        elif not results.get('success'):
            self.log(f"❌ ERROR: {results.get('error', 'Error desconocido')}")
        else:
            total_eliminados = results['eliminados_no_terminados'] + results['eliminados_q_null']
            self.log(f"🗑️ Registros eliminados: {total_eliminados:,}")
            self.log(f"   • No terminados: {results['eliminados_no_terminados']:,}")
            self.log(f"   • Corruptos (q=NULL): {results['eliminados_q_null']:,}")
            self.log("")
            self.log(f"🔄 Equipos recalculados: {results['equipos_recalculados']:,}")
            if results['errores_recalculo'] > 0:
                self.log(f"⚠️ Errores en recálculo: {results['errores_recalculo']:,}")
            self.log("")
            self.log("✅ REPARACIÓN COMPLETADA")
        
        self.log("")
        self.log("=" * 60)
        
        # Limpiar resultados de diagnóstico
        self.diagnostic_results = None
    
    def cancel_operation(self):
        """Cancela la operación en curso."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log("\n⏹️ Cancelando operación...")
    
    def closeEvent(self, event):
        """Maneja el cierre del diálogo."""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Operación en curso",
                "Hay una operación en curso. ¿Deseas cancelarla y cerrar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.worker.stop()
                self.worker.wait(3000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIÓN PARA AGREGAR BOTÓN AL MENÚ PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def open_repair_tool(parent=None):
    """Función helper para abrir la herramienta desde cualquier lugar."""
    dialog = ConstantsRepairDialog(parent)
    dialog.exec()


if __name__ == "__main__":
    # Para pruebas independientes
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    dialog = ConstantsRepairDialog()
    dialog.show()
    sys.exit(app.exec())