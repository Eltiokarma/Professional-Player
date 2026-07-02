#!/usr/bin/env python3
# src/ui/simplified_database_management_dialog.py

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QPushButton, QLabel, QProgressBar,
                               QTextEdit, QFileDialog, QMessageBox, QGroupBox)
from PySide6.QtCore import Qt, QThread, Signal
from utils.constants_calculator import ConstantsCalculator  # 🔧 USAR ARCHIVO CORREGIDO
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from data.database_manager import engine, CONST_ENGINE
from data.data_models.teams import Team
import pandas as pd
import logging
import os
from datetime import datetime


logger = logging.getLogger(__name__)

class SyncAllTeamsWorker(QThread):
    """Worker para sincronización masiva de todos los equipos"""
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(dict)
    
    def __init__(self, force_recalc=False):
        super().__init__()
        self.force_recalc = force_recalc
    
    def run(self):
        try:
            self.status.emit("Iniciando sincronización masiva...")
            
            Session = sessionmaker(bind=engine)
            session = Session()
            teams = session.query(Team).all()
            session.close()
            
            total_teams = len(teams)
            results = {
                'total': total_teams,
                'success': 0,
                'failed': 0,
                'skipped': 0,
                'details': []
            }
            
            for i, team in enumerate(teams):
                try:
                    self.status.emit(f"Procesando {team.name} ({i+1}/{total_teams})")
                    self.progress.emit(int((i / total_teams) * 100))
                    
                    with ConstantsCalculator() as calc:
                        if self.force_recalc:
                            # 🔧 USAR MÉTODO QUE SÍ EXISTE: Forzar recálculo completo
                            success = calc.calculate_and_store(team.id)
                        else:
                            # 🔧 VERIFICAR SI EXISTE MÉTODO INCREMENTAL, SINO USAR NORMAL
                            if hasattr(calc, 'incremental_calculate_and_store'):
                                success = calc.incremental_calculate_and_store(team.id)
                            else:
                                # Fallback: verificar si ya tiene datos
                                existing = calc.get_stored_constants(team.id)
                                if existing is not None and not existing.empty:
                                    results['skipped'] += 1
                                    results['details'].append(f"⏭️ {team.name}: Ya tiene datos")
                                    continue
                                else:
                                    success = calc.calculate_and_store(team.id)
                    
                    if success:
                        results['success'] += 1
                        results['details'].append(f"✅ {team.name}: Sincronizado")
                    else:
                        results['skipped'] += 1
                        results['details'].append(f"⏭️ {team.name}: Sin cambios")
                        
                except Exception as e:
                    logger.error(f"Error procesando equipo {team.id}: {e}")
                    results['failed'] += 1
                    results['details'].append(f"❌ {team.name}: Error - {str(e)}")
            
            self.progress.emit(100)
            self.finished.emit(results)
            
        except Exception as e:
            logger.error(f"Error en sincronización masiva: {e}")
            self.finished.emit({'error': str(e)})

class SimplifiedDatabaseManagementDialog(QDialog):
    """🚀 Diálogo SIMPLIFICADO para gestión de base de datos
    
    🔧 Compatible con ConstantsCalculator original y mejorado
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🚀 Gestión de Base de Datos - Optimizada")
        self.setModal(True)
        self.resize(600, 400)
        
        self.sync_worker = None
        
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        
        # Tabs principales
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # --- Tab 1: Estado y Sincronización ---
        sync_tab = QWidget()
        tabs.addTab(sync_tab, "🔄 Sincronización")
        self._build_sync_tab(sync_tab)
        
        # --- Tab 2: Exportación ---
        export_tab = QWidget()
        tabs.addTab(export_tab, "📁 Exportar")
        self._build_export_tab(export_tab)
        
        # --- Tab 3: Mantenimiento ---
        maintenance_tab = QWidget()
        tabs.addTab(maintenance_tab, "🔧 Mantenimiento")
        self._build_maintenance_tab(maintenance_tab)
        
        # Progreso global
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Listo")
        layout.addWidget(self.status_label)
        
        # Botón cerrar
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        close_layout.addWidget(btn_close)
        layout.addLayout(close_layout)

    def _build_sync_tab(self, parent):
        """Construye la pestaña de sincronización"""
        layout = QVBoxLayout(parent)
        
        # Información de estado
        status_group = QGroupBox("📊 Estado de la base de datos")
        status_layout = QVBoxLayout(status_group)
        
        self.db_status_label = QLabel("Cargando información...")
        status_layout.addWidget(self.db_status_label)
        
        btn_refresh_status = QPushButton("🔄 Actualizar estado")
        btn_refresh_status.clicked.connect(self._refresh_database_status)
        status_layout.addWidget(btn_refresh_status)
        
        layout.addWidget(status_group)
        
        # 🚀 Acciones simplificadas
        actions_group = QGroupBox("🚀 Acciones de sincronización")
        actions_layout = QVBoxLayout(actions_group)
        
        # 🔧 DETECTAR SI TENEMOS MÉTODO INCREMENTAL
        try:
            with ConstantsCalculator() as calc:
                has_incremental = hasattr(calc, 'incremental_calculate_and_store')
        except:
            has_incremental = False
        
        if has_incremental:
            info_label = QLabel("""
💡 <b>Sistema inteligente detectado:</b>
• <b>Sincronización incremental:</b> Solo procesa partidos nuevos
• <b>Sin recálculos innecesarios:</b> Máxima eficiencia
• <b>Automático:</b> Detecta qué equipos necesitan actualización
            """)
            
            btn_sync_all = QPushButton("🔄 Sincronizar todos los equipos (Incremental)")
            btn_sync_all.setToolTip("Sincroniza solo partidos nuevos - MUY RÁPIDO")
        else:
            info_label = QLabel("""
💡 <b>Sistema de cálculo estándar:</b>
• <b>Sincronización inteligente:</b> Solo calcula equipos sin datos
• <b>Evita duplicados:</b> No recalcula equipos existentes
• <b>Eficiente:</b> Procesamiento optimizado
            """)
            
            btn_sync_all = QPushButton("🔄 Calcular equipos faltantes")
            btn_sync_all.setToolTip("Calcula solo equipos que no tienen constantes")
        
        info_label.setWordWrap(True)
        actions_layout.addWidget(info_label)
        
        btn_sync_all.clicked.connect(self._sync_all_teams_smart)
        actions_layout.addWidget(btn_sync_all)
        
        btn_force_recalc = QPushButton("🔄 Forzar recálculo completo (Solo si hay problemas)")
        btn_force_recalc.clicked.connect(self._force_recalculate_all)
        btn_force_recalc.setToolTip("Borra todo y recalcula - LENTO, solo para reparar problemas")
        btn_force_recalc.setStyleSheet("QPushButton { background-color: #ffebcd; }")
        actions_layout.addWidget(btn_force_recalc)
        
        layout.addWidget(actions_group)
        
        layout.addStretch()
        
        # Cargar estado inicial
        self._refresh_database_status()

    def _build_export_tab(self, parent):
        """Construye la pestaña de exportación"""
        layout = QVBoxLayout(parent)
        
        export_group = QGroupBox("📁 Exportar datos")
        export_layout = QVBoxLayout(export_group)
        
        btn_export_all = QPushButton("📊 Exportar todas las constantes (CSV)")
        btn_export_all.clicked.connect(self._export_all_constants)
        export_layout.addWidget(btn_export_all)
        
        btn_export_summary = QPushButton("📋 Exportar resumen por equipo (CSV)")
        btn_export_summary.clicked.connect(self._export_team_summary)
        export_layout.addWidget(btn_export_summary)
        
        btn_export_latest = QPushButton("🎯 Exportar últimas constantes por equipo (CSV)")
        btn_export_latest.clicked.connect(self._export_latest_constants)
        export_layout.addWidget(btn_export_latest)
        
        layout.addWidget(export_group)
        layout.addStretch()

    def _build_maintenance_tab(self, parent):
        """Construye la pestaña de mantenimiento"""
        layout = QVBoxLayout(parent)
        
        # Backup
        backup_group = QGroupBox("💾 Respaldo")
        backup_layout = QVBoxLayout(backup_group)
        
        btn_backup_constants = QPushButton("💾 Respaldar base de constantes")
        btn_backup_constants.clicked.connect(self._backup_constants_db)
        backup_layout.addWidget(btn_backup_constants)
        
        layout.addWidget(backup_group)
        
        # Estadísticas
        stats_group = QGroupBox("📊 Estadísticas avanzadas")
        stats_layout = QVBoxLayout(stats_group)
        
        btn_show_stats = QPushButton("📊 Mostrar estadísticas detalladas")
        btn_show_stats.clicked.connect(self._show_detailed_stats)
        stats_layout.addWidget(btn_show_stats)
        
        layout.addWidget(stats_group)
        
        layout.addStretch()

    def _refresh_database_status(self):
        """Actualiza el estado de la base de datos"""
        try:
            # Consulta rápida con SQL directo
            Session = sessionmaker(bind=engine)
            session = Session()
            
            total_teams = session.execute(text("SELECT COUNT(*) FROM teams")).scalar()
            session.close()
            
            teams_with_constants = pd.read_sql_query(
                "SELECT COUNT(DISTINCT team_id) as count FROM constants", 
                CONST_ENGINE
            ).iloc[0]['count']
            
            total_constants = pd.read_sql_query(
                "SELECT COUNT(*) as count FROM constants", 
                CONST_ENGINE
            ).iloc[0]['count']
            
            # Calcular estadísticas
            teams_without = total_teams - teams_with_constants
            completion_pct = (teams_with_constants / total_teams * 100) if total_teams > 0 else 0
            
            # Obtener fecha de última actualización
            try:
                last_update = pd.read_sql_query(
                    "SELECT MAX(date) as last_date FROM constants", 
                    CONST_ENGINE
                ).iloc[0]['last_date']
                last_update_str = f"📅 Última actualización: {last_update}"
            except:
                last_update_str = "📅 Última actualización: No disponible"
            
            status_text = f"""📊 <b>Estado de la base de datos:</b>

🏟️ <b>Equipos:</b>
   • Total: {total_teams:,}
   • Con constantes: {teams_with_constants:,}
   • Sin constantes: {teams_without:,}

📈 <b>Constantes:</b>
   • Total de registros: {total_constants:,}
   • Progreso: {completion_pct:.1f}%

{last_update_str}

💡 <b>Estado:</b> {"✅ Completo" if teams_without == 0 else f"⚠️ {teams_without} equipos pendientes"}"""
            
            self.db_status_label.setText(status_text)
            
        except Exception as e:
            logger.error(f"Error obteniendo estado: {e}")
            self.db_status_label.setText(f"❌ Error obteniendo estado: {str(e)}")

    def _sync_all_teams_smart(self):
        """🚀 Sincronización inteligente de todos los equipos"""
        if self.sync_worker and self.sync_worker.isRunning():
            QMessageBox.information(self, "En proceso", "Ya hay una sincronización en proceso")
            return
        
        # Verificar capacidades del calculador
        try:
            with ConstantsCalculator() as calc:
                has_incremental = hasattr(calc, 'incremental_calculate_and_store')
        except:
            has_incremental = False
        
        if has_incremental:
            message = """🚀 ¿Iniciar sincronización incremental de todos los equipos?

• Solo procesará partidos nuevos
• Muy eficiente y rápido
• Recomendado para uso regular"""
        else:
            message = """🔄 ¿Calcular constantes para equipos faltantes?

• Solo procesará equipos sin constantes
• Evita duplicar trabajo
• Proceso eficiente"""
        
        reply = QMessageBox.question(
            self,
            "Confirmar sincronización",
            message,
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._start_sync_worker(force_recalc=False)

    def _force_recalculate_all(self):
        """⚠️ Forzar recálculo completo de todos los equipos"""
        if self.sync_worker and self.sync_worker.isRunning():
            QMessageBox.information(self, "En proceso", "Ya hay una sincronización en proceso")
            return
        
        reply = QMessageBox.warning(
            self,
            "⚠️ Confirmar recálculo completo",
            "⚠️ ¿Forzar recálculo completo de TODOS los equipos?\n\n"
            "• Borrará TODOS los datos existentes\n"
            "• Recalculará desde cero\n"
            "• Proceso MUY LENTO\n"
            "• Solo usar si hay problemas graves\n\n"
            "💡 Recomendado: Usar sincronización inteligente en su lugar",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Confirmar otra vez
            reply2 = QMessageBox.critical(
                self,
                "🚨 Última confirmación",
                "🚨 ¿Está SEGURO de borrar todos los datos y recalcular?\n\n"
                "Esta acción NO se puede deshacer.",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply2 == QMessageBox.Yes:
                self._start_sync_worker(force_recalc=True)

    def _start_sync_worker(self, force_recalc=False):
        """Inicia el worker de sincronización"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        
        action = "recálculo completo" if force_recalc else "sincronización inteligente"
        self.status_label.setText(f"🔄 Iniciando {action}...")
        
        self.sync_worker = SyncAllTeamsWorker(force_recalc)
        self.sync_worker.progress.connect(self.progress_bar.setValue)
        self.sync_worker.status.connect(self.status_label.setText)
        self.sync_worker.finished.connect(self._on_sync_finished)
        self.sync_worker.start()

    def _on_sync_finished(self, results):
        """Maneja finalización de sincronización"""
        self.progress_bar.setVisible(False)
        
        if 'error' in results:
            self.status_label.setText(f"❌ Error: {results['error']}")
            QMessageBox.critical(self, "Error", f"Error en sincronización:\n{results['error']}")
        else:
            # Mostrar resultados
            total = results['total']
            success = results['success']
            failed = results['failed']
            skipped = results['skipped']
            
            self.status_label.setText(f"✅ Completado: {success} éxito, {failed} fallos, {skipped} omitidos")
            
            QMessageBox.information(
                self,
                "✅ Sincronización completada",
                f"📊 Resultados de la sincronización:\n\n"
                f"• Total procesados: {total}\n"
                f"• Exitosos: {success}\n"
                f"• Fallidos: {failed}\n"
                f"• Omitidos (sin cambios): {skipped}\n\n"
                f"🎯 Efectividad: {(success/(total-skipped)*100):.1f}%" if (total-skipped) > 0 else ""
            )
        
        # Actualizar estado
        self._refresh_database_status()

    def _export_all_constants(self):
        """📊 Exporta todas las constantes"""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, 
                "Exportar todas las constantes", 
                f"constantes_todas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV (*.csv)"
            )
            
            if path:
                self.status_label.setText("📊 Exportando todas las constantes...")
                
                # SQL directo para máxima velocidad
                query = """
                SELECT 
                    c.*,
                    t.name as team_name
                FROM constants c
                LEFT JOIN teams t ON c.team_id = t.id
                ORDER BY c.team_id, c.date
                """
                
                df = pd.read_sql_query(query, CONST_ENGINE)
                df.to_csv(path, index=False)
                
                self.status_label.setText(f"✅ Exportadas {len(df):,} constantes a {path}")
                QMessageBox.information(self, "✅ Exportado", f"Exportadas {len(df):,} constantes exitosamente")
                
        except Exception as e:
            logger.error(f"Error exportando constantes: {e}")
            QMessageBox.critical(self, "❌ Error", f"Error al exportar: {str(e)}")

    def _export_team_summary(self):
        """📋 Exporta resumen por equipo"""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, 
                "Exportar resumen por equipo", 
                f"resumen_equipos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV (*.csv)"
            )
            
            if path:
                self.status_label.setText("📋 Generando resumen por equipo...")
                
                query = """
                SELECT 
                    t.name as equipo,
                    COUNT(c.id) as total_partidos,
                    MIN(c.date) as primer_partido,
                    MAX(c.date) as ultimo_partido,
                    AVG(c.k_positivo) as promedio_k_positivo,
                    AVG(c.k_negativo) as promedio_k_negativo
                FROM teams t
                LEFT JOIN constants c ON t.id = c.team_id
                GROUP BY t.id, t.name
                ORDER BY total_partidos DESC
                """
                
                df = pd.read_sql_query(query, CONST_ENGINE)
                df.to_csv(path, index=False)
                
                self.status_label.setText(f"✅ Resumen exportado a {path}")
                QMessageBox.information(self, "✅ Exportado", f"Resumen de {len(df):,} equipos exportado exitosamente")
                
        except Exception as e:
            logger.error(f"Error exportando resumen: {e}")
            QMessageBox.critical(self, "❌ Error", f"Error al exportar resumen: {str(e)}")

    def _export_latest_constants(self):
        """🎯 Exporta últimas constantes por equipo"""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, 
                "Exportar últimas constantes", 
                f"ultimas_constantes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV (*.csv)"
            )
            
            if path:
                self.status_label.setText("🎯 Exportando últimas constantes...")
                
                query = """
                SELECT 
                    t.name as equipo,
                    c.*
                FROM teams t
                INNER JOIN (
                    SELECT team_id, MAX(date) as max_date
                    FROM constants
                    GROUP BY team_id
                ) latest ON t.id = latest.team_id
                INNER JOIN constants c ON c.team_id = latest.team_id AND c.date = latest.max_date
                ORDER BY t.name
                """
                
                df = pd.read_sql_query(query, CONST_ENGINE)
                df.to_csv(path, index=False)
                
                self.status_label.setText(f"✅ Últimas constantes exportadas a {path}")
                QMessageBox.information(self, "✅ Exportado", f"Últimas constantes de {len(df):,} equipos exportadas")
                
        except Exception as e:
            logger.error(f"Error exportando últimas constantes: {e}")
            QMessageBox.critical(self, "❌ Error", f"Error al exportar: {str(e)}")

    def _backup_constants_db(self):
        """💾 Respalda la base de datos de constantes"""
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, 
                "Respaldar base de constantes", 
                f"constants_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                "Database (*.db)"
            )
            
            if path:
                self.status_label.setText("💾 Creando respaldo...")
                
                # Copiar archivo de base de datos
                import shutil
                constants_db_path = CONST_ENGINE.url.database
                shutil.copy2(constants_db_path, path)
                
                self.status_label.setText(f"✅ Respaldo creado en {path}")
                QMessageBox.information(self, "✅ Respaldo creado", f"Base de datos respaldada exitosamente en:\n{path}")
                
        except Exception as e:
            logger.error(f"Error creando respaldo: {e}")
            QMessageBox.critical(self, "❌ Error", f"Error al crear respaldo: {str(e)}")

    def _show_detailed_stats(self):
        """📊 Muestra estadísticas detalladas"""
        try:
            self.status_label.setText("📊 Generando estadísticas...")
            
            # Estadísticas avanzadas
            stats_query = """
            SELECT 
                COUNT(DISTINCT team_id) as equipos_con_datos,
                COUNT(*) as total_registros,
                AVG(k_positivo) as promedio_k_positivo,
                MIN(date) as fecha_minima,
                MAX(date) as fecha_maxima,
                COUNT(DISTINCT date) as fechas_unicas
            FROM constants
            """
            
            stats = pd.read_sql_query(stats_query, CONST_ENGINE).iloc[0]
            
            stats_text = f"""📊 <b>Estadísticas Detalladas:</b>

🏟️ <b>Equipos con datos:</b> {stats['equipos_con_datos']:,}
📈 <b>Total de registros:</b> {stats['total_registros']:,}
📅 <b>Fechas únicas:</b> {stats['fechas_unicas']:,}

📊 <b>Promedio K positivo:</b> {stats['promedio_k_positivo']:.2f}

📅 <b>Rango de fechas:</b>
   • Desde: {stats['fecha_minima']}
   • Hasta: {stats['fecha_maxima']}

💾 <b>Tamaño promedio por equipo:</b> {(stats['total_registros'] / stats['equipos_con_datos']):.1f} registros
"""
            
            QMessageBox.information(self, "📊 Estadísticas Detalladas", stats_text)
            self.status_label.setText("✅ Estadísticas generadas")
            
        except Exception as e:
            logger.error(f"Error generando estadísticas: {e}")
            QMessageBox.critical(self, "❌ Error", f"Error al generar estadísticas: {str(e)}")

    def closeEvent(self, event):
        """Limpieza al cerrar"""
        if self.sync_worker and self.sync_worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Sincronización en proceso",
                "Hay una sincronización en proceso. ¿Desea cancelarla?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.sync_worker.terminate()
                self.sync_worker.wait(3000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# Alias para compatibilidad
DatabaseManagementDialog = SimplifiedDatabaseManagementDialog