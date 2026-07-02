#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚖️ LEY DE LA FE PERDIDA — VENTANA UI v4
==========================================
Interfaz para analizar partidos con el péndulo del hincha.

Ubicación: src/ui/ley_fe_perdida_window.py
Engine:    src/ley_fe_perdida_engine.py

Autor: Gerson (desarrollado con Claude)
Fecha: Febrero 2026
"""

import os
import sys
import logging
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QFrame, QScrollArea, QSplitter,
    QProgressBar, QMessageBox, QSizePolicy, QApplication,
    QSpinBox, QAbstractItemView, QTextEdit
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QBrush, QPainter, QPen

logger = logging.getLogger(__name__)


# =============================================================================
# RESOLUCIÓN DE IMPORTS
# =============================================================================

def _find_src_dir() -> str:
    this_dir = os.path.dirname(os.path.abspath(__file__))
    if this_dir.replace('\\', '/').endswith('/ui') or this_dir.endswith('\\ui'):
        return os.path.dirname(this_dir)
    return this_dir

_src = _find_src_dir()
if _src not in sys.path:
    sys.path.insert(0, _src)

from ley_fe_perdida_engine import (
    FePerdidaEngine, MatchAnalysis, TeamPendulum,
    FlagType, GoalFlag, PendulumZone, TeamStature,
    FLAG_EMOJIS, FLAG_DESCRIPTIONS, ZONE_EMOJIS, STATURE_EMOJIS,
    BASELINE, PENDULUM_THRESHOLDS
)


# =============================================================================
# COLORES
# =============================================================================

class C:
    BG       = "#F4F5F7"
    CARD     = "#FFFFFF"
    CARD_ALT = "#F9FAFB"
    HDR_BG   = "#F0F1F3"
    INPUT_BG = "#FFFFFF"

    T1 = "#1A1D23"
    T2 = "#5A6170"
    T3 = "#9CA3AF"

    B1 = "#E5E7EB"
    B2 = "#D1D5DB"

    ACC     = "#2563EB"
    ACC_HOV = "#1D4ED8"
    ACC_LT  = "#EFF6FF"
    ACC_SF  = "#DBEAFE"

    HOME_STRONG = "#16A34A"
    HOME        = "#2563EB"
    NONE_FLAG   = "#9CA3AF"
    AWAY        = "#DC2626"
    AWAY_STRONG = "#9333EA"

    EUFORIA      = "#16A34A"
    CONFIANZA    = "#65A30D"
    NEUTRAL      = "#9CA3AF"
    TENSION      = "#D97706"
    FRUSTRACION  = "#DC2626"
    FE_DESTRUIDA = "#BE123C"

    GRANDE = "#D97706"
    MEDIO  = "#2563EB"
    CHICO  = "#78716C"

    WIN  = "#16A34A"
    DRAW = "#D97706"
    LOSS = "#DC2626"

    TOP = "#1E293B"


FLAG_COLORS = {
    FlagType.HOME_STRONG: C.HOME_STRONG,
    FlagType.HOME: C.HOME,
    FlagType.NONE: C.NONE_FLAG,
    FlagType.AWAY: C.AWAY,
    FlagType.AWAY_STRONG: C.AWAY_STRONG,
}

ZONE_COLORS = {
    PendulumZone.EUFORIA: C.EUFORIA,
    PendulumZone.CONFIANZA: C.CONFIANZA,
    PendulumZone.NEUTRAL: C.NEUTRAL,
    PendulumZone.TENSION: C.TENSION,
    PendulumZone.FRUSTRACION: C.FRUSTRACION,
    PendulumZone.FE_DESTRUIDA: C.FE_DESTRUIDA,
}

STYLESHEET = f"""
QMainWindow {{ background-color: {C.BG}; }}

QGroupBox {{
    font-weight: 600; font-size: 12px; color: {C.T2};
    border: 1px solid {C.B1}; border-radius: 8px;
    margin-top: 10px; padding: 14px 10px 10px 10px;
    background-color: {C.CARD};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
}}

QTableWidget {{
    gridline-color: {C.B1}; border: 1px solid {C.B1};
    border-radius: 6px; background-color: {C.CARD};
    alternate-background-color: {C.CARD_ALT};
    color: {C.T1}; selection-background-color: {C.ACC_SF};
    selection-color: {C.T1}; outline: none; font-size: 12px;
}}
QTableWidget::item {{ padding: 3px 6px; border-bottom: 1px solid {C.B1}; }}
QTableWidget::item:selected {{ background-color: {C.ACC_LT}; }}
QHeaderView::section {{
    background-color: {C.HDR_BG}; color: {C.T2};
    padding: 6px; border: none; border-bottom: 2px solid {C.B2};
    font-weight: 600; font-size: 11px;
}}

QComboBox {{
    padding: 4px 10px; border: 1px solid {C.B2}; border-radius: 5px;
    background-color: {C.INPUT_BG}; color: {C.T1};
    min-height: 26px; font-size: 12px;
}}
QComboBox:hover, QComboBox:focus {{ border-color: {C.ACC}; }}
QComboBox::drop-down {{ border: none; padding-right: 6px; }}
QComboBox QAbstractItemView {{
    background-color: {C.CARD}; color: {C.T1};
    border: 1px solid {C.B2}; selection-background-color: {C.ACC_LT};
    outline: none;
}}

QSpinBox {{
    padding: 4px 8px; border: 1px solid {C.B2}; border-radius: 5px;
    background-color: {C.INPUT_BG}; color: {C.T1};
    min-height: 26px; font-size: 12px;
}}
QSpinBox:hover {{ border-color: {C.ACC}; }}

QPushButton#btn_analyze {{
    background-color: {C.ACC}; color: white;
    padding: 5px 18px; border-radius: 5px;
    font-weight: 600; font-size: 12px;
    min-height: 28px; border: none;
}}
QPushButton#btn_analyze:hover {{ background-color: {C.ACC_HOV}; }}
QPushButton#btn_analyze:pressed {{ background-color: #1E40AF; }}
QPushButton#btn_analyze:disabled {{ background-color: {C.B2}; color: {C.T3}; }}

QProgressBar {{ border: none; border-radius: 2px; background-color: {C.B1}; }}
QProgressBar::chunk {{ background-color: {C.ACC}; border-radius: 2px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 6px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {C.B2}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {C.T3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QSplitter::handle {{ background-color: {C.B1}; width: 1px; margin: 0 3px; }}

QLabel {{ color: {C.T1}; }}
"""


# =============================================================================
# WORKER (sin cambios)
# =============================================================================

class AnalysisWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, engine: FePerdidaEngine, league_id: int, days: int):
        super().__init__()
        self.engine = engine
        self.league_id = league_id
        self.days = days

    def run(self):
        try:
            self.progress.emit(10, "Buscando partidos...")
            matches = self.engine.get_upcoming_matches(self.league_id, self.days)
            if not matches:
                self.finished.emit([])
                return
            analyses = []
            total = len(matches)
            for i, m in enumerate(matches):
                pct = 10 + int(85 * (i + 1) / total)
                self.progress.emit(pct, f"Analizando {i+1}/{total}...")
                odds = self.engine._get_match_odds(m['fixture_id'])
                analysis = self.engine.analyze_match(
                    home_team_id=m['home_team_id'],
                    away_team_id=m['away_team_id'],
                    league_id=self.league_id,
                    fixture_id=m['fixture_id'],
                    match_date=m['date'],
                    odds_home=odds.get('home'),
                    odds_draw=odds.get('draw'),
                    odds_away=odds.get('away'),
                )
                analyses.append(analysis)
            self.progress.emit(100, "Listo")
            self.finished.emit(analyses)
        except Exception as e:
            self.error.emit(str(e))


# =============================================================================
# WIDGETS
# =============================================================================

class PendulumBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self._score = 0.0
        self._zone = PendulumZone.NEUTRAL

    def set_value(self, score: float, zone: PendulumZone):
        self._score = score
        self._zone = zone
        self.update()

    def paintEvent(self, event):
        from PySide6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setBrush(QColor("#F0F1F3"))
        p.setPen(QPen(QColor(C.B1), 1))
        p.drawRoundedRect(QRectF(0, 0, w, h), 5, 5)
        cx = w / 2.0
        p.setPen(QPen(QColor(C.B2), 1))
        p.drawLine(int(cx), 2, int(cx), h - 2)
        zone_color = QColor(ZONE_COLORS.get(self._zone, C.NEUTRAL))
        norm = max(-100, min(100, self._score))
        bar_w = abs(norm) / 100.0 * (cx - 4)
        if bar_w > 1:
            c = QColor(zone_color); c.setAlpha(180)
            p.setBrush(c); p.setPen(Qt.NoPen)
            if norm >= 0:
                p.drawRoundedRect(QRectF(cx + 1, 3, bar_w, h - 6), 3, 3)
            else:
                p.drawRoundedRect(QRectF(cx - bar_w - 1, 3, bar_w, h - 6), 3, 3)
        p.setPen(QColor(C.T1))
        f = QFont("Segoe UI", 9); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, f"{self._score:+.1f}")
        p.end()


class FlagBadge(QLabel):
    def __init__(self, flag=FlagType.NONE, parent=None):
        super().__init__(parent)
        self.set_flag(flag)

    def set_flag(self, flag):
        color = FLAG_COLORS.get(flag, C.NONE_FLAG)
        emoji = FLAG_EMOJIS.get(flag, "⚪")
        text = flag.value.replace("_", " ").title()
        self.setText(f" {emoji} {text} ")
        self.setStyleSheet(f"""
            background-color: {color}; color: white;
            font-weight: 600; font-size: 11px;
            padding: 3px 10px; border-radius: 4px;
        """)
        self.setAlignment(Qt.AlignCenter)


class StatureBadge(QLabel):
    def __init__(self, stature=TeamStature.MEDIO, parent=None):
        super().__init__(parent)
        self.set_stature(stature)

    def set_stature(self, stature):
        colors = {
            TeamStature.GRANDE: C.GRANDE, TeamStature.MEDIO: C.MEDIO,
            TeamStature.CHICO: C.CHICO, TeamStature.UNKNOWN: C.NEUTRAL,
        }
        accent = colors.get(stature, C.NEUTRAL)
        emoji = STATURE_EMOJIS.get(stature, "❓")
        self.setText(f" {emoji} {stature.value.upper()} ")
        self.setStyleSheet(f"""
            background-color: transparent; color: {accent};
            font-weight: 600; font-size: 10px;
            padding: 2px 6px; border: 1px solid {accent}; border-radius: 3px;
        """)


# =============================================================================
# PANEL DETALLE
# =============================================================================

class MatchDetailPanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._container = QWidget()
        self._container.setStyleSheet(f"background: {C.BG};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self.setWidget(self._container)
        self._show_placeholder()

    def _show_placeholder(self):
        ph = QLabel("← Selecciona un partido")
        ph.setStyleSheet(f"color: {C.T3}; font-size: 13px; padding: 40px;")
        ph.setAlignment(Qt.AlignCenter)
        ph.setWordWrap(True)
        self._layout.addWidget(ph)
        self._layout.addStretch()

    def show_analysis(self, a: MatchAnalysis):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        # HEADER
        self._layout.addWidget(self._mk(
            f"⚖️ {a.home.team_name}  vs  {a.away.team_name}",
            C.T1, True, 16, wrap=True
        ))
        self._layout.addWidget(self._mk(
            f"{a.league_name} · {self._fmt(a.match_date)}",
            C.T3, False, 11
        ))

        # FLAG
        fb = QGroupBox("🚩 Flag")
        fl = QVBoxLayout(fb); fl.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(FlagBadge(a.flag))
        etxt = f"+{a.edge_pp:.0f} pp" if a.edge_pp > 0 else "Sin ventaja"
        row.addWidget(self._mk(etxt, FLAG_COLORS.get(a.flag, C.T3), True, 15))
        row.addStretch()
        fl.addLayout(row)
        d = QLabel(a.flag_description)
        d.setStyleSheet(f"color: {C.T2}; font-style: italic; font-size: 11px;")
        d.setWordWrap(True)
        fl.addWidget(d)
        self._layout.addWidget(fb)

        # PÉNDULOS
        pb = QGroupBox("📊 Péndulos")
        pl = QVBoxLayout(pb); pl.setSpacing(6)

        for role, pend in [("LOCAL", a.home), ("VISITANTE", a.away)]:
            card = QFrame()
            card.setStyleSheet(f"QFrame {{ border: 1px solid {C.B1}; border-radius: 6px; background: {C.CARD_ALT}; }}")
            vl = QVBoxLayout(card); vl.setSpacing(3); vl.setContentsMargins(8, 6, 8, 6)

            nr = QHBoxLayout()
            nr.addWidget(self._mk(role, C.T3, True, 9))
            nr.addWidget(self._mk(pend.team_name, C.T1, True, 13))
            nr.addStretch()
            nr.addWidget(StatureBadge(pend.stature))
            vl.addLayout(nr)

            bar = PendulumBar(); bar.set_value(pend.pendulum_score, pend.zone)
            vl.addWidget(bar)

            ir = QHBoxLayout()
            ze = ZONE_EMOJIS.get(pend.zone, "")
            zc = ZONE_COLORS.get(pend.zone, C.NEUTRAL)
            ir.addWidget(self._mk(f"{ze} {pend.zone.value.replace('_',' ').title()}", zc, True, 11))
            ir.addWidget(self._mk(f"[{pend.mode}]", C.T3, False, 10))
            ir.addStretch()
            rl = QLabel(self._racha("".join(pend.last_results[:7])))
            rl.setTextFormat(Qt.RichText)
            rl.setStyleSheet("font-size: 12px; font-family: 'Consolas', monospace;")
            ir.addWidget(rl)
            vl.addLayout(ir)

            if pend.goal_flag == GoalFlag.SCORES:
                vl.addWidget(self._mk(f"⚽ Anota: {pend.team_scores_pct*100:.0f}% — eufórico", C.EUFORIA, True, 10))
            elif pend.goal_flag == GoalFlag.SECO:
                vl.addWidget(self._mk(f"💀 Solo: {pend.team_scores_pct*100:.0f}% — en crisis", C.FRUSTRACION, True, 10))

            pl.addWidget(card)

        # GAP
        gf = QFrame()
        gf.setStyleSheet(f"background: {C.ACC_LT}; border: 1px solid {C.ACC_SF}; border-radius: 6px;")
        gl = QHBoxLayout(gf); gl.setContentsMargins(12, 4, 12, 4)
        gl.addWidget(self._mk("GAP", C.T3, True, 10))
        gl.addStretch()
        gc = C.HOME_STRONG if a.gap > 15 else (C.AWAY if a.gap < -15 else C.T1)
        gl.addWidget(self._mk(f"{a.gap:+.1f}", gc, True, 18))
        pl.addWidget(gf)
        self._layout.addWidget(pb)

        # PROBABILIDADES
        prb = QGroupBox("📈 Probabilidades")
        prl = QGridLayout(prb); prl.setSpacing(4)
        for j, h in enumerate(["", "Home", "Draw", "Away"]):
            l = self._mk(h, C.T3, True, 10); l.setAlignment(Qt.AlignCenter)
            prl.addWidget(l, 0, j)
        prl.addWidget(self._mk("Modelo", C.T2, False, 11), 1, 0)
        for j, (val, base) in enumerate([
            (a.prob_home, BASELINE['home_win']),
            (a.prob_draw, BASELINE['draw']),
            (a.prob_away, BASELINE['away_win']),
        ]):
            diff = (val - base) * 100
            cc = C.HOME_STRONG if diff > 3 else (C.AWAY if diff < -3 else C.T1)
            l = self._mk(f"{val*100:.0f}%", cc, True, 14); l.setAlignment(Qt.AlignCenter)
            prl.addWidget(l, 1, j + 1)
        prl.addWidget(self._mk("Base", C.T3, False, 10), 2, 0)
        for j, val in enumerate([BASELINE['home_win'], BASELINE['draw'], BASELINE['away_win']]):
            l = self._mk(f"{val*100:.0f}%", C.T3, False, 10); l.setAlignment(Qt.AlignCenter)
            prl.addWidget(l, 2, j + 1)
        if a.odds_home:
            prl.addWidget(self._mk("Odds", C.T3, False, 10), 3, 0)
            for j, val in enumerate([a.odds_home, a.odds_draw, a.odds_away]):
                l = self._mk(f"{val:.2f}" if val else "—", C.T2, False, 10)
                l.setAlignment(Qt.AlignCenter)
                prl.addWidget(l, 3, j + 1)
        self._layout.addWidget(prb)

        # MARGEN
        sf = QFrame()
        sf.setStyleSheet(f"background: {C.CARD}; border: 1px solid {C.B1}; border-radius: 6px;")
        sr = QHBoxLayout(sf); sr.setContentsMargins(10, 5, 10, 5)
        sr.addWidget(self._mk(f"📏 Margen: {a.expected_margin:+.2f} goles", C.T1, True, 11))
        sr.addStretch()
        sr.addWidget(self._mk(f"💥 Goleada 3+: {a.goleada_pct*100:.1f}%", C.T2, False, 11))
        self._layout.addWidget(sf)

        # MERCADO
        if a.market_suggestions:
            mb = QGroupBox("💰 ¿Qué se lleva el hincha?")
            mkl = QVBoxLayout(mb); mkl.setSpacing(3)
            for ms in a.market_suggestions:
                r = QHBoxLayout()
                icon = "⚽" if "Anota" in ms.market or "Win" in ms.market else "🚫"
                r.addWidget(self._mk(f"{icon} {ms.market}", C.T1, True, 11))
                r.addStretch()
                r.addWidget(self._mk(f"{ms.probability*100:.0f}%", C.ACC, True, 13))
                ec = C.HOME_STRONG if ms.edge_pp > 0 else C.AWAY
                r.addWidget(self._mk(f"({ms.edge_pp:+.0f}pp)", ec, False, 10))
                mkl.addLayout(r)
            self._layout.addWidget(mb)

        # HÁNDICAP
        if a.handicap_suggestions:
            hb = QGroupBox("🎯 Hándicap Europeo")
            hl = QVBoxLayout(hb); hl.setSpacing(3)
            for hs in a.handicap_suggestions:
                r = QHBoxLayout()
                star = " ⭐" if hs.suggested else ""
                r.addWidget(self._mk(f"{hs.team_name} +{hs.handicap}{star}", C.T1, hs.suggested, 11))
                r.addStretch()
                r.addWidget(self._mk(f"Gana {hs.win_pct*100:.0f}%", C.ACC, True, 12))
                hl.addLayout(r)
            self._layout.addWidget(hb)

        # FAITH DETAILS
        fdb = QGroupBox("📋 Detalle de fe")
        fdl = QVBoxLayout(fdb); fdl.setSpacing(1)
        for pend in [a.home, a.away]:
            if not pend.faith_details: continue
            fdl.addWidget(self._mk(f"▸ {pend.team_name}", C.T1, True, 11))
            for fd in pend.faith_details[:7]:
                ri = "🏠" if fd['role'] == 'home' else "✈️"
                rc = {"W": C.WIN, "D": C.DRAW, "L": C.LOSS}.get(fd['result'], C.T3)
                line = QLabel(
                    f"  {ri} vs {fd['opp']}  {fd['score']}  "
                    f"<span style='color:{rc};font-weight:bold;'>{fd['result']}</span>  "
                    f"<span style='color:{C.T3};'>fe={fd['faith']:+.2f} × w={fd['weight']:.2f}</span>"
                )
                line.setTextFormat(Qt.RichText)
                line.setStyleSheet(f"font-size: 10px; font-family: 'Consolas', monospace; color: {C.T2};")
                fdl.addWidget(line)
        self._layout.addWidget(fdb)
        self._layout.addStretch()

    # helpers
    def _mk(self, t, c, b=False, s=12, wrap=False):
        l = QLabel(t)
        w = "bold" if b else "normal"
        l.setStyleSheet(f"font-size: {s}px; font-weight: {w}; color: {c};")
        if wrap: l.setWordWrap(True)
        return l

    def _fmt(self, d):
        try: return datetime.fromisoformat(str(d).replace('Z','')).strftime("%a %d %b %Y %H:%M")
        except: return str(d)[:16]

    def _racha(self, r):
        m = {"W": C.WIN, "D": C.DRAW, "L": C.LOSS}
        return "".join(f"<span style='color:{m.get(c,C.T3)};font-weight:bold;'>{c}</span>" for c in r)


# =============================================================================
# VENTANA PRINCIPAL
# =============================================================================

class FePerdidaWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._analyses: List[MatchAnalysis] = []
        self._worker: Optional[AnalysisWorker] = None

        try:
            self.engine = FePerdidaEngine()
        except Exception as e:
            logger.error(f"Error inicializando engine: {e}")
            QMessageBox.critical(None, "Error", f"No se pudo inicializar el engine:\n{e}")
            return

        self._build_ui()
        self._load_leagues()

    def _build_ui(self):
        self.setWindowTitle("⚖️ Ley de la Fe Perdida — Péndulo del Hincha")
        self.resize(1400, 900)
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── TOP BAR  (48px fija, oscura) ──
        top = QFrame()
        top.setFixedHeight(48)
        top.setStyleSheet(f"QFrame {{ background: {C.TOP}; border-bottom: 1px solid #334155; }}")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 0, 16, 0)
        t = QLabel("⚖️ LEY DE LA FE PERDIDA")
        t.setStyleSheet("font-size: 15px; font-weight: bold; color: white; letter-spacing: 0.5px;")
        tl.addWidget(t)
        tl.addStretch()
        b = QLabel("📊 Lookup Table Empírica")
        b.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 600; background: #334155; padding: 3px 10px; border-radius: 4px;")
        b.setToolTip("Frecuencias observadas en 42,452 partidos de 37 ligas")
        tl.addWidget(b)
        root.addWidget(top)

        # ── CONTROLS  (42px fija, blanca) ──
        ctrl = QFrame()
        ctrl.setFixedHeight(42)
        ctrl.setStyleSheet(f"QFrame {{ background: {C.CARD}; border-bottom: 1px solid {C.B1}; }}")
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(16, 0, 16, 0)
        cl.setSpacing(8)

        cl.addWidget(self._clbl("Liga"))
        self.combo_league = QComboBox()
        self.combo_league.setMinimumWidth(280)
        self.combo_league.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        cl.addWidget(self.combo_league)
        cl.addSpacing(8)
        cl.addWidget(self._clbl("Días"))
        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 60)
        self.spin_days.setValue(14)
        self.spin_days.setFixedWidth(60)
        cl.addWidget(self.spin_days)
        cl.addSpacing(4)
        self.btn_analyze = QPushButton("🔍 Analizar")
        self.btn_analyze.setObjectName("btn_analyze")
        self.btn_analyze.setCursor(Qt.PointingHandCursor)
        self.btn_analyze.clicked.connect(self._on_analyze)
        cl.addWidget(self.btn_analyze)
        cl.addStretch()
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {C.T3}; font-size: 11px;")
        cl.addWidget(self.lbl_status)
        root.addWidget(ctrl)

        # ── PROGRESS (3px) ──
        self.progress = QProgressBar()
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # ── FLAGS SUMMARY (altura fija 24px) ──
        self.lbl_summary = QLabel("")
        self.lbl_summary.setFixedHeight(24)
        self.lbl_summary.setStyleSheet(f"font-size: 11px; color: {C.T2}; padding: 2px 16px; background: {C.BG};")
        root.addWidget(self.lbl_summary)

        # ── SPLITTER  (ocupa TODO el espacio restante) ──
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet(f"QSplitter {{ background: {C.BG}; }}")

        # Tabla izquierda
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Fecha", "Local", "Visitante", "Flag", "Gap", "Home%", "Away%", "Edge"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_match_selected)
        for i, w in enumerate([85, 130, 130, 95, 50, 50, 50, 50]):
            self.table.setColumnWidth(i, w)

        self.splitter.addWidget(self.table)

        # Detalle derecho
        self.detail_panel = MatchDetailPanel()
        self.splitter.addWidget(self.detail_panel)

        self.splitter.setSizes([660, 500])

        # ★ CLAVE: stretch=1 para que el splitter se coma todo el espacio
        root.addWidget(self.splitter, stretch=1)

    def _clbl(self, t):
        l = QLabel(t)
        l.setStyleSheet(f"color: {C.T2}; font-size: 11px; font-weight: 600;")
        return l

    # ── Datos ──

    def _load_leagues(self):
        try:
            leagues = self.engine.get_available_leagues()
            self.combo_league.clear()
            for lg in leagues:
                self.combo_league.addItem(
                    f"{lg['name']} — {lg['upcoming']} próximos",
                    userData=lg['league_id']
                )
            self.lbl_status.setText(f"{len(leagues)} ligas disponibles")
        except Exception as e:
            logger.error(f"Error cargando ligas: {e}")
            self.lbl_status.setText(f"Error: {e}")

    def _on_analyze(self):
        lid = self.combo_league.currentData()
        if lid is None: return
        self.btn_analyze.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.lbl_status.setText("Analizando...")
        self._worker = AnalysisWorker(self.engine, lid, self.spin_days.value())
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_err)
        self._worker.start()

    def _on_progress(self, p, m):
        self.progress.setValue(p)
        self.lbl_status.setText(m)

    def _on_done(self, analyses):
        self._analyses = analyses
        self.progress.setVisible(False)
        self.btn_analyze.setEnabled(True)
        flags = sum(1 for a in analyses if a.flag != FlagType.NONE)
        self.lbl_status.setText(f"{len(analyses)} partidos · {flags} flags")
        if flags:
            parts = []
            for a in analyses:
                if a.flag != FlagType.NONE:
                    short = (a.home.team_name.split()[-1]
                             if a.flag in (FlagType.HOME, FlagType.HOME_STRONG)
                             else a.away.team_name.split()[-1])
                    parts.append(f"{FLAG_EMOJIS[a.flag]} {short}")
            self.lbl_summary.setText(f"🚩 Flags: {' · '.join(parts)}")
        else:
            self.lbl_summary.setText("ℹ️ Sin flags activos")
        self._populate_table()
        for i, a in enumerate(analyses):
            if a.flag != FlagType.NONE:
                self.table.selectRow(i); return
        if analyses: self.table.selectRow(0)

    def _on_err(self, msg):
        self.progress.setVisible(False)
        self.btn_analyze.setEnabled(True)
        self.lbl_status.setText(f"Error: {msg}")
        QMessageBox.warning(self, "Error", f"Error en análisis:\n{msg}")

    # ── Tabla ──

    def _populate_table(self):
        self.table.setRowCount(0)
        self._analyses = sorted(
            self._analyses,
            key=lambda a: (0 if a.flag != FlagType.NONE else 1, a.match_date)
        )
        self.table.setRowCount(len(self._analyses))
        for row, a in enumerate(self._analyses):
            try: ds = datetime.fromisoformat(str(a.match_date).replace('Z','')).strftime("%d/%m %H:%M")
            except: ds = str(a.match_date)[:10]

            self._cell(row, 0, ds)
            self._cell(row, 1, a.home.team_name)
            self._cell(row, 2, a.away.team_name)

            fi = QTableWidgetItem(f"{FLAG_EMOJIS[a.flag]} {a.flag.value}")
            fc = FLAG_COLORS.get(a.flag, C.NONE_FLAG)
            fi.setForeground(QBrush(QColor(fc)))
            fi.setFont(QFont("Segoe UI", -1, QFont.Bold))
            fi.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, fi)

            gi = QTableWidgetItem(f"{a.gap:+.0f}")
            gi.setTextAlignment(Qt.AlignCenter)
            if abs(a.gap) >= 25:
                gi.setFont(QFont("Segoe UI", -1, QFont.Bold))
                gi.setForeground(QBrush(QColor(C.ACC)))
            self.table.setItem(row, 4, gi)

            self._cell(row, 5, f"{a.prob_home*100:.0f}%", Qt.AlignCenter)
            self._cell(row, 6, f"{a.prob_away*100:.0f}%", Qt.AlignCenter)

            et = f"+{a.edge_pp:.0f}" if a.edge_pp > 0 else "—"
            ei = QTableWidgetItem(et)
            ei.setTextAlignment(Qt.AlignCenter)
            if a.edge_pp > 0:
                ei.setForeground(QBrush(QColor(C.HOME_STRONG)))
                ei.setFont(QFont("Segoe UI", -1, QFont.Bold))
            self.table.setItem(row, 7, ei)

            if a.flag != FlagType.NONE:
                bg = QColor(fc); bg.setAlpha(18)
                for col in range(8):
                    it = self.table.item(row, col)
                    if it: it.setBackground(QBrush(bg))

    def _cell(self, r, c, t, a=Qt.AlignLeft):
        it = QTableWidgetItem(t)
        it.setTextAlignment(a | Qt.AlignVCenter)
        self.table.setItem(r, c, it)

    def _on_match_selected(self):
        rows = self.table.selectedIndexes()
        if not rows: return
        r = rows[0].row()
        if 0 <= r < len(self._analyses):
            self.detail_panel.show_analysis(self._analyses[r])


# =============================================================================
# STANDALONE
# =============================================================================

def main():
    app = QApplication(sys.argv)
    f = QFont("Segoe UI", 10)
    f.setHintingPreference(QFont.PreferFullHinting)
    app.setFont(f)
    w = FePerdidaWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()