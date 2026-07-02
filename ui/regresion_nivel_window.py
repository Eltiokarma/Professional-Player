# src/ui/regresion_nivel_window.py
# -*- coding: utf-8 -*-
"""
Ventana UI para la Ley de la Regresion al Nivel.
=================================================

Tabs:
  1. Prediccion - Seleccionar partido, ver P(Win) con indicadores visuales
  2. Validacion - Metricas del modelo, calibracion, feature importance
  3. Entrenamiento - Reentrenar modelo con progreso en vivo

Autor: Sistema de Analisis Deportivo
"""

import os
import logging
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QFrame, QTextEdit, QMessageBox, QSpinBox, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  ESTILOS
# ══════════════════════════════════════════════════════════

TEAL = "#009688"
TEAL_DARK = "#00796B"
TEAL_BG = "#E0F2F1"

STYLESHEET = """
QMainWindow { background-color: #F8F9FA; }
QTabWidget::pane {
    border: 1px solid #E0E0E0;
    background-color: white;
    border-radius: 8px;
}
QTabBar::tab {
    padding: 10px 20px; margin-right: 2px;
    background-color: #E9ECEF;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background-color: #009688; color: white; font-weight: bold;
}
QTabBar::tab:hover:!selected { background-color: #DEE2E6; }
QGroupBox {
    font-weight: bold;
    border: 2px solid #E0E0E0; border-radius: 10px;
    margin-top: 1.5ex; padding-top: 15px; background: white;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 15px;
    padding: 0 8px; color: #009688;
}
"""


# ══════════════════════════════════════════════════════════
#  WORKERS
# ══════════════════════════════════════════════════════════

class _PredictionWorker(QThread):
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, engine, home_id, away_id, league_id, season):
        super().__init__()
        self.engine = engine
        self.home_id = home_id
        self.away_id = away_id
        self.league_id = league_id
        self.season = season
    
    def run(self):
        try:
            result = self.engine.predict_match(
                self.home_id, self.away_id,
                self.league_id, self.season)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _TrainingWorker(QThread):
    progress = Signal(str, int)
    finished = Signal(object)
    
    def __init__(self, engine, max_season):
        super().__init__()
        self.engine = engine
        self.max_season = max_season
    
    def run(self):
        result = self.engine.train_model(
            max_train_season=self.max_season,
            progress_callback=lambda msg, pct: self.progress.emit(msg, pct))
        self.finished.emit(result)


class _MatchesWorker(QThread):
    """Carga partidos en background."""
    finished = Signal(list)
    error = Signal(str)
    
    def __init__(self, engine, days):
        super().__init__()
        self.engine = engine
        self.days = days
    
    def run(self):
        try:
            matches = self.engine.get_upcoming_matches(self.days)
            self.finished.emit(matches)
        except Exception as e:
            self.error.emit(str(e))


# ══════════════════════════════════════════════════════════
#  VENTANA PRINCIPAL
# ══════════════════════════════════════════════════════════

class RegresionNivelWindow(QMainWindow):
    """Ventana de la Ley de la Regresion al Nivel."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = None
        self.upcoming_matches = []
        self._workers = []           # Mantener refs a threads
        
        self._setup_window()
        self._setup_ui()
        self._init_engine()
    
    def _setup_window(self):
        self.setWindowTitle("\U0001f4c9 Ley de la Regresion al Nivel")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        self.setStyleSheet(STYLESHEET)
    
    def _init_engine(self):
        """Inicializa el engine."""
        try:
            from regresion_nivel_engine import RegresionNivelEngine
            self.engine = RegresionNivelEngine()
            
            info = self.engine.get_model_info()
            if info.get('exists'):
                self.engine.load_model()
                self._update_model_status(info)
                self._load_upcoming_matches()
            else:
                self._update_model_status({'exists': False})
        except Exception as e:
            logger.error(f"Error inicializando engine: {e}", exc_info=True)
            self.lbl_model_status.setText(f"\u274c Error: {e}")
            self.lbl_model_status.setStyleSheet("font-size: 11px; color: #DC3545;")
    
    # ──────────────────────────────────────────────────────
    #  UI PRINCIPAL
    # ──────────────────────────────────────────────────────
    
    def _setup_ui(self):
        central = QWidget()
        main = QVBoxLayout(central)
        main.setContentsMargins(15, 15, 15, 15)
        main.setSpacing(10)
        
        # --- Header ---
        main.addLayout(self._build_header())
        
        # --- Tabs ---
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_prediction_tab(), "\U0001f3af Prediccion")
        self.tabs.addTab(self._build_validation_tab(), "\U0001f4ca Validacion")
        self.tabs.addTab(self._build_training_tab(), "\u2699\ufe0f Entrenamiento")
        main.addWidget(self.tabs)
        
        self.setCentralWidget(central)
    
    def _build_header(self):
        lay = QVBoxLayout()
        
        title = QLabel("\U0001f4c9 Ley de la Regresion al Nivel")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #1a1a2e;")
        lay.addWidget(title)
        
        sub = QLabel(
            "Si un equipo rinde por debajo de su nivel, tiende a mejorar "
            "(y viceversa). AUC=0.874 | Accuracy=80% | 23/23 ligas"
        )
        sub.setStyleSheet("font-size: 12px; color: #666;")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        
        self.lbl_model_status = QLabel("Cargando...")
        self.lbl_model_status.setStyleSheet("font-size: 11px; color: #888;")
        lay.addWidget(self.lbl_model_status)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {TEAL}; max-height: 2px;")
        line.setFixedHeight(2)
        lay.addWidget(line)
        
        return lay
    
    # ──────────────────────────────────────────────────────
    #  TAB 1: PREDICCION
    # ──────────────────────────────────────────────────────
    
    def _build_prediction_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(15)
        
        # --- Selector ---
        grp = QGroupBox("Seleccionar Partido")
        grp_lay = QHBoxLayout(grp)
        
        grp_lay.addWidget(QLabel("Partido:"))
        
        self.combo_matches = QComboBox()
        self.combo_matches.setMinimumWidth(450)
        self.combo_matches.addItem("-- Cargando partidos --")
        grp_lay.addWidget(self.combo_matches, 1)
        
        self.btn_predict = QPushButton("\U0001f52e Predecir")
        self.btn_predict.setStyleSheet(f"""
            QPushButton {{ background: {TEAL}; color: white; border: none;
                           border-radius: 8px; padding: 10px 24px;
                           font-weight: bold; font-size: 13px; }}
            QPushButton:hover {{ background: {TEAL_DARK}; }}
        """)
        self.btn_predict.clicked.connect(self._on_predict)
        grp_lay.addWidget(self.btn_predict)
        
        btn_refresh = QPushButton("\U0001f504")
        btn_refresh.setToolTip("Refrescar lista de partidos")
        btn_refresh.setFixedSize(40, 40)
        btn_refresh.setStyleSheet("""
            QPushButton { background: #6C757D; color: white; border: none;
                          border-radius: 8px; font-size: 16px; }
            QPushButton:hover { background: #5A6268; }
        """)
        btn_refresh.clicked.connect(self._load_upcoming_matches)
        grp_lay.addWidget(btn_refresh)
        
        lay.addWidget(grp)
        
        # --- Cards de equipos ---
        cards_lay = QHBoxLayout()
        
        self.card_home = self._build_team_card("LOCAL")
        cards_lay.addWidget(self.card_home)
        
        vs = QLabel("VS")
        vs.setAlignment(Qt.AlignCenter)
        vs.setStyleSheet("font-size: 28px; font-weight: bold; color: #CCC;")
        vs.setFixedWidth(60)
        cards_lay.addWidget(vs)
        
        self.card_away = self._build_team_card("VISITANTE")
        cards_lay.addWidget(self.card_away)
        
        lay.addLayout(cards_lay)
        
        # --- Recomendacion ---
        self.lbl_rec = QLabel("")
        self.lbl_rec.setWordWrap(True)
        self.lbl_rec.setStyleSheet(f"""
            padding: 12px; background: {TEAL_BG}; border-radius: 8px;
            font-size: 13px; color: #004D40; border-left: 4px solid {TEAL};
        """)
        self.lbl_rec.setVisible(False)
        lay.addWidget(self.lbl_rec)
        
        lay.addStretch()
        return w
    
    def _build_team_card(self, side_label: str) -> QFrame:
        card = QFrame()
        card.setObjectName("team_card")
        card.setStyleSheet("""
            QFrame#team_card { background: white; border: 2px solid #E0E0E0;
                               border-radius: 12px; padding: 15px; }
        """)
        vbox = QVBoxLayout(card)
        vbox.setSpacing(6)
        
        side = QLabel(side_label)
        side.setAlignment(Qt.AlignCenter)
        side.setStyleSheet("font-size: 10px; color: #999; font-weight: bold; letter-spacing: 2px;")
        vbox.addWidget(side)
        
        name_lbl = QLabel("---")
        name_lbl.setObjectName("team_name")
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #1a1a2e;")
        vbox.addWidget(name_lbl)
        
        pwin_lbl = QLabel("--")
        pwin_lbl.setObjectName("p_win")
        pwin_lbl.setAlignment(Qt.AlignCenter)
        pwin_lbl.setStyleSheet(f"font-size: 44px; font-weight: bold; color: {TEAL};")
        vbox.addWidget(pwin_lbl)
        
        pwin_desc = QLabel("P(Win)")
        pwin_desc.setAlignment(Qt.AlignCenter)
        pwin_desc.setStyleSheet("font-size: 10px; color: #999;")
        vbox.addWidget(pwin_desc)
        
        # Linea separadora
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background: #E9ECEF; max-height: 1px;")
        vbox.addWidget(sep)
        
        # Grid de detalles
        grid = QGridLayout()
        grid.setSpacing(4)
        labels = ["Nivel:", "Forma (ult.5):", "Gap:", "Mu:", "PPG temp.:"]
        for i, txt in enumerate(labels):
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size: 11px; color: #888;")
            grid.addWidget(lbl, i, 0, Qt.AlignRight)
            
            val = QLabel("--")
            val.setObjectName(f"detail_{i}")
            val.setStyleSheet("font-size: 12px; font-weight: bold; color: #333;")
            grid.addWidget(val, i, 1, Qt.AlignLeft)
        
        vbox.addLayout(grid)
        return card
    
    def _fill_card(self, card: QFrame, name: str, p_win: float,
                   level: float, pts_recent: float, gap: float,
                   mu: float, ppg: Optional[float], is_favored: bool):
        """Rellena una card de equipo."""
        card.findChild(QLabel, "team_name").setText(name)
        
        lbl_pw = card.findChild(QLabel, "p_win")
        lbl_pw.setText(f"{p_win:.0%}")
        
        if p_win > 0.55:
            color = "#27AE60"
        elif p_win > 0.40:
            color = "#F39C12"
        else:
            color = "#E74C3C"
        lbl_pw.setStyleSheet(f"font-size: 44px; font-weight: bold; color: {color};")
        
        # Borde verde si es favorito
        border = f"3px solid {TEAL}" if is_favored else "2px solid #E0E0E0"
        card.setStyleSheet(f"""
            QFrame#team_card {{ background: white; border: {border};
                                border-radius: 12px; padding: 15px; }}
        """)
        
        vals = [
            f"{level:.2f}",
            f"{pts_recent:.2f} pts/p",
            f"{gap:+.2f}",
            f"{mu:.2f}",
            f"{ppg:.2f}" if ppg else "N/A",
        ]
        for i, v in enumerate(vals):
            det = card.findChild(QLabel, f"detail_{i}")
            if not det:
                continue
            det.setText(v)
            # Colorear gap
            if i == 2:
                gv = gap
                if gv > 0.3:
                    det.setStyleSheet("font-size: 12px; font-weight: bold; color: #27AE60;")
                elif gv < -0.3:
                    det.setStyleSheet("font-size: 12px; font-weight: bold; color: #E74C3C;")
                else:
                    det.setStyleSheet("font-size: 12px; font-weight: bold; color: #333;")
    
    # ──────────────────────────────────────────────────────
    #  TAB 2: VALIDACION
    # ──────────────────────────────────────────────────────
    
    def _build_validation_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        
        self.txt_validation = QTextEdit()
        self.txt_validation.setReadOnly(True)
        self.txt_validation.setStyleSheet("""
            QTextEdit { font-family: 'Consolas', 'Courier New', monospace;
                        font-size: 12px; background: #1a1a2e; color: #E0E0E0;
                        border-radius: 8px; padding: 15px; }
        """)
        self.txt_validation.setPlainText("Cargando informacion del modelo...")
        lay.addWidget(self.txt_validation)
        
        return w
    
    # ──────────────────────────────────────────────────────
    #  TAB 3: ENTRENAMIENTO
    # ──────────────────────────────────────────────────────
    
    def _build_training_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(15)
        
        # Config
        grp = QGroupBox("Configuracion")
        g = QGridLayout(grp)
        
        g.addWidget(QLabel("Max temporada entrenamiento:"), 0, 0)
        self.spin_max_season = QSpinBox()
        self.spin_max_season.setRange(2018, 2026)
        self.spin_max_season.setValue(2024)
        g.addWidget(self.spin_max_season, 0, 1)
        g.addWidget(QLabel(
            "Datos hasta esta temporada para train. Datos posteriores = test."
        ), 0, 2)
        
        lay.addWidget(grp)
        
        # Botones
        btn_lay = QHBoxLayout()
        self.btn_train = QPushButton("\U0001f680 Entrenar Modelo")
        self.btn_train.setStyleSheet(f"""
            QPushButton {{ background: {TEAL}; color: white; border: none;
                           border-radius: 8px; padding: 12px 28px;
                           font-weight: bold; font-size: 14px; }}
            QPushButton:hover {{ background: {TEAL_DARK}; }}
        """)
        self.btn_train.clicked.connect(self._on_train)
        btn_lay.addWidget(self.btn_train)
        btn_lay.addStretch()
        lay.addLayout(btn_lay)
        
        # Progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{ border: 2px solid #E0E0E0; border-radius: 8px;
                           text-align: center; height: 25px; }}
            QProgressBar::chunk {{ background-color: {TEAL}; border-radius: 6px; }}
        """)
        lay.addWidget(self.progress_bar)
        
        self.lbl_train_status = QLabel("")
        self.lbl_train_status.setStyleSheet("color: #666;")
        lay.addWidget(self.lbl_train_status)
        
        # Log
        self.txt_training = QTextEdit()
        self.txt_training.setReadOnly(True)
        self.txt_training.setStyleSheet("""
            QTextEdit { font-family: 'Consolas', 'Courier New', monospace;
                        font-size: 12px; background: #1a1a2e; color: #E0E0E0;
                        border-radius: 8px; padding: 15px; }
        """)
        self.txt_training.setPlainText(
            "Listo para entrenar.\n\n"
            "El modelo usa HistGradientBoosting + calibracion isotonica.\n"
            "Tiempo estimado: 30-90 segundos.\n\n"
            "Presiona 'Entrenar Modelo' para iniciar."
        )
        lay.addWidget(self.txt_training)
        
        return w
    
    # ──────────────────────────────────────────────────────
    #  ACCIONES
    # ──────────────────────────────────────────────────────
    
    def _load_upcoming_matches(self):
        """Carga proximos partidos en background."""
        if not self.engine:
            return
        
        self.combo_matches.clear()
        self.combo_matches.addItem("\u23f3 Cargando partidos...")
        self.combo_matches.setEnabled(False)
        
        worker = _MatchesWorker(self.engine, 14)
        worker.finished.connect(self._on_matches_loaded)
        worker.error.connect(lambda e: self._on_matches_error(e))
        worker.start()
        self._workers.append(worker)
    
    def _on_matches_loaded(self, matches):
        self.upcoming_matches = matches
        self.combo_matches.clear()
        self.combo_matches.setEnabled(True)
        
        if not matches:
            self.combo_matches.addItem("No hay partidos proximos en las ligas SAD")
            return
        
        for m in matches:
            dt = str(m['date'])[:16].replace('T', ' ')
            self.combo_matches.addItem(
                f"{m['home_name']} vs {m['away_name']}  "
                f"({m['league_name']})  {dt}"
            )
    
    def _on_matches_error(self, err):
        self.combo_matches.clear()
        self.combo_matches.setEnabled(True)
        self.combo_matches.addItem(f"Error: {err}")
    
    def _on_predict(self):
        if not self.engine or not self.upcoming_matches:
            QMessageBox.warning(self, "Aviso",
                                "No hay partidos o modelo no cargado.")
            return
        
        idx = self.combo_matches.currentIndex()
        if idx < 0 or idx >= len(self.upcoming_matches):
            return
        
        m = self.upcoming_matches[idx]
        self.btn_predict.setEnabled(False)
        self.btn_predict.setText("\u23f3 Calculando...")
        
        worker = _PredictionWorker(
            self.engine, m['home_id'], m['away_id'],
            m['league_id'], m['season'])
        worker.finished.connect(self._on_prediction_result)
        worker.error.connect(self._on_prediction_error)
        worker.start()
        self._workers.append(worker)
    
    def _on_prediction_result(self, pred):
        self.btn_predict.setEnabled(True)
        self.btn_predict.setText("\U0001f52e Predecir")
        
        if pred is None:
            QMessageBox.warning(self, "Sin datos",
                                "No se pudo predecir. Faltan niveles o historial "
                                "de los equipos (se necesitan al menos 5 partidos).")
            return
        
        favored_home = pred.p_home_win >= pred.p_away_win
        
        self._fill_card(
            self.card_home, pred.home_team, pred.p_home_win,
            pred.level_home, pred.pts_recent_home, pred.gap_home,
            pred.mu_home, pred.season_ppg_home, favored_home)
        
        self._fill_card(
            self.card_away, pred.away_team, pred.p_away_win,
            pred.level_away, pred.pts_recent_away, pred.gap_away,
            pred.mu_away, pred.season_ppg_away, not favored_home)
        
        # Recomendacion
        self.lbl_rec.setText(
            f"\U0001f4a1 {pred.recommendation}\n\n"
            f"Confianza: {pred.confidence}  |  "
            f"Gap diff: {pred.gap_diff:+.2f}  |  "
            f"P(Draw)\u2248{pred.p_draw_approx:.0%}  |  "
            f"Copa: {'Si' if pred.is_international else 'No'}  |  "
            f"Temporada: {pred.season_progress:.0%}"
        )
        self.lbl_rec.setVisible(True)
    
    def _on_prediction_error(self, msg):
        self.btn_predict.setEnabled(True)
        self.btn_predict.setText("\U0001f52e Predecir")
        QMessageBox.critical(self, "Error", f"Error en prediccion:\n{msg}")
    
    # --- Entrenamiento ---
    
    def _on_train(self):
        if not self.engine:
            QMessageBox.warning(self, "Aviso", "Engine no inicializado.")
            return
        
        ms = self.spin_max_season.value()
        reply = QMessageBox.question(
            self, "Entrenar Modelo",
            f"Entrenar modelo con datos hasta temporada {ms}.\n"
            f"Tiempo estimado: 30-90 segundos.\n\n\u00bfContinuar?",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        
        self.btn_train.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.txt_training.clear()
        
        worker = _TrainingWorker(self.engine, ms)
        worker.progress.connect(self._on_train_progress)
        worker.finished.connect(self._on_train_finished)
        worker.start()
        self._workers.append(worker)
    
    def _on_train_progress(self, msg, pct):
        self.progress_bar.setValue(pct)
        self.lbl_train_status.setText(msg)
        self.txt_training.append(f"[{pct:>3}%] {msg}")
    
    def _on_train_finished(self, result):
        self.btn_train.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if result.success:
            self.txt_training.append(f"\n{'='*55}")
            self.txt_training.append(f"  ENTRENAMIENTO EXITOSO")
            self.txt_training.append(f"  Records:  {result.n_records:,}")
            self.txt_training.append(f"  Train:    {result.n_train:,}")
            self.txt_training.append(f"  Test:     {result.n_test:,}")
            self.txt_training.append(f"  Accuracy: {result.accuracy:.1%}")
            self.txt_training.append(f"  AUC-ROC:  {result.auc_roc:.3f}")
            self.txt_training.append(f"  Log-loss: {result.log_loss:.4f}")
            self.txt_training.append(f"  Mejora:   {result.mejora_pct:+.1f}% vs sin-gap")
            self.txt_training.append(f"  Tiempo:   {result.elapsed_seconds:.1f}s")
            self.txt_training.append(f"  Modelo:   {result.model_path}")
            self.txt_training.append(f"{'='*55}")
            
            info = self.engine.get_model_info()
            self._update_model_status(info)
            
            QMessageBox.information(
                self, "Exito",
                f"Modelo entrenado exitosamente.\n\n"
                f"AUC-ROC: {result.auc_roc:.3f}\n"
                f"Accuracy: {result.accuracy:.1%}\n"
                f"Mejora vs sin-gap: {result.mejora_pct:+.1f}%\n"
                f"Tiempo: {result.elapsed_seconds:.1f}s")
        else:
            self.txt_training.append(f"\n\u274c ERROR: {result.message}")
            QMessageBox.critical(self, "Error",
                                 f"Error en entrenamiento:\n{result.message}")
    
    # ──────────────────────────────────────────────────────
    #  HELPERS
    # ──────────────────────────────────────────────────────
    
    def _update_model_status(self, info: dict):
        if info.get('exists'):
            results = info.get('results', {})
            bm = results.get('best_metrics', {})
            auc = bm.get('auc_roc', 0)
            acc = bm.get('accuracy', 0)
            
            # Si no hay results JSON, usar lo del joblib
            model_name = info.get('best_model', '?')
            trained = str(info.get('trained_at', '?'))[:16]
            seasons = info.get('train_seasons', '?')
            
            if auc > 0:
                self.lbl_model_status.setText(
                    f"\u2705 Modelo {model_name} | AUC={auc:.3f} | "
                    f"Acc={acc:.1%} | Train: {seasons} | {trained}")
            else:
                self.lbl_model_status.setText(
                    f"\u2705 Modelo {model_name} cargado | Train: {seasons} | {trained}")
            self.lbl_model_status.setStyleSheet("font-size: 11px; color: #27AE60;")
            
            self._show_validation_report(results)
        else:
            self.lbl_model_status.setText(
                "\u26a0\ufe0f Modelo no encontrado. "
                "Ve a 'Entrenamiento' para crear uno.")
            self.lbl_model_status.setStyleSheet("font-size: 11px; color: #E74C3C;")
    
    def _show_validation_report(self, results: dict):
        """Muestra informe de validacion."""
        if not results:
            self.txt_validation.setPlainText(
                "Sin archivo ml_results_v2.json.\n"
                "Ejecuta el script diagnosegap.py para generar resultados completos,\n"
                "o entrena un nuevo modelo desde la pestana Entrenamiento.")
            return
        
        lines = []
        lines.append("=" * 62)
        lines.append("  LEY DE LA REGRESION AL NIVEL")
        lines.append("  Modelo: {}".format(results.get('best_model', '?')))
        lines.append("=" * 62)
        
        lines.append(f"\n  Tipo:       {results.get('type', '?')}")
        lines.append(f"  Ventana:    {results.get('window', '?')} partidos")
        lines.append(f"  Features:   {results.get('n_features', '?')}")
        lines.append(f"  Train:      {results.get('n_train', '?'):,} records")
        lines.append(f"  Test:       {results.get('n_test', '?'):,} records")
        
        bm = results.get('best_metrics', {})
        if bm:
            lines.append(f"\n  METRICAS OUT-OF-SAMPLE")
            lines.append(f"  {'─'*42}")
            for k in ['accuracy', 'auc_roc', 'log_loss', 'brier', 'precision', 'recall', 'f1']:
                v = bm.get(k)
                if v is not None:
                    fmt = f"{v:.1%}" if k in ('accuracy', 'precision', 'recall', 'f1') else f"{v:.4f}"
                    lines.append(f"  {k:<14} {fmt}")
        
        bl = results.get('baseline_metrics', {})
        if bl:
            lines.append(f"\n  VS BASELINE (sin gap)")
            lines.append(f"  {'─'*42}")
            lines.append(f"  Baseline Acc:   {bl.get('accuracy', 0):.1%}")
            lines.append(f"  Baseline LL:    {bl.get('log_loss', 0):.4f}")
            lines.append(f"  Mejora LL:      {results.get('mejora_vs_sin_gap_pct', 0):+.2f}%")
        
        fi = results.get('feature_importances', {})
        if fi:
            lines.append(f"\n  FEATURE IMPORTANCE (permutation)")
            lines.append(f"  {'─'*42}")
            sorted_fi = sorted(fi.items(), key=lambda x: -x[1])
            max_imp = sorted_fi[0][1] if sorted_fi else 1
            for name, imp in sorted_fi:
                bar_len = int(imp / max_imp * 30) if max_imp > 0 else 0
                bar = '#' * bar_len
                lines.append(f"  {name:<25} {imp:.4f} {bar}")
        
        all_m = results.get('all_models', [])
        if all_m:
            lines.append(f"\n  COMPARACION DE MODELOS")
            lines.append(f"  {'─'*55}")
            lines.append(f"  {'Modelo':<25} {'Acc':>6} {'AUC':>6} {'LL':>8} {'t(s)':>6}")
            lines.append(f"  {'─'*55}")
            for m in all_m:
                lines.append(
                    f"  {m.get('name', '?'):<25} "
                    f"{m.get('accuracy', 0):>6.1%} "
                    f"{m.get('auc_roc', 0):>6.3f} "
                    f"{m.get('log_loss', 0):>8.4f} "
                    f"{m.get('time', 0):>6.1f}")
        
        by_level = results.get('by_level', [])
        if by_level:
            lines.append(f"\n  PERFORMANCE POR BANDA DE NIVEL")
            lines.append(f"  {'─'*55}")
            for b in by_level:
                lines.append(
                    f"  {b.get('band', '?'):<20} n={b.get('n', 0):>5}  "
                    f"AUC={b.get('auc', 0):.3f}  Acc={b.get('accuracy', 0):.1%}")
        
        by_phase = results.get('by_phase', [])
        if by_phase:
            lines.append(f"\n  PERFORMANCE POR FASE DE TEMPORADA")
            lines.append(f"  {'─'*55}")
            for p in by_phase:
                lines.append(
                    f"  {p.get('phase', '?'):<22} n={p.get('n', 0):>5}  "
                    f"AUC={p.get('auc', 0):.3f}  Acc={p.get('accuracy', 0):.1%}")
        
        self.txt_validation.setPlainText("\n".join(lines))