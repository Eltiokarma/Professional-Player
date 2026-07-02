#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sad_dashboard_window.py

SAD DASHBOARD — Visualización de Extracción Fase 1
===================================================

Ventana QWebEngineView que renderiza el dashboard de constantes K,
goles y tablero de decisiones para un partido específico.

Usa HTML/JS vanilla embebido — cero dependencias externas.
Único requisito: pip install PySide6-WebEngineWidgets

Autor: Gerson (desarrollado con Claude)
Fecha: Marzo 2026
"""

import json
import logging
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget, QStatusBar, QLabel
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView

logger = logging.getLogger(__name__)


# =====================================================================
# HTML TEMPLATE — Todo el frontend va aquí como string
# =====================================================================

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>SAD Dashboard</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');

:root {
  --bg: #0a0e17;
  --card: #111827;
  --card-hover: #1a2235;
  --border: #1e293b;
  --text: #e2e8f0;
  --muted: #64748b;
  --accent: #3b82f6;
  --green: #22c55e;
  --yellow: #eab308;
  --red: #ef4444;
  --orange: #f97316;
  --purple: #a855f7;
  --cyan: #06b6d4;
  --burst: #ff3366;
  --burst-bg: rgba(255,51,102,0.1);
  --deep: #0f172a;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', -apple-system, sans-serif; padding: 12px; }
::-webkit-scrollbar { height: 4px; width: 4px; }
::-webkit-scrollbar-track { background: var(--card); }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }

.container { max-width: 920px; margin: 0 auto; }

.header { text-align: center; margin-bottom: 16px; padding: 14px 0; border-bottom: 1px solid var(--border); }
.header .phase { font-size: 9px; text-transform: uppercase; letter-spacing: 3px; color: var(--muted); }
.header h1 { font-size: 20px; font-weight: 800; margin: 6px 0 2px; letter-spacing: -0.5px; }
.header h1 .home { color: var(--cyan); }
.header h1 .vs { color: var(--muted); margin: 0 8px; font-size: 14px; }
.header h1 .away { color: var(--orange); }
.header .meta { font-size: 10px; color: var(--muted); }

.tabs { display: flex; gap: 4px; margin-bottom: 12px; }
.tab-btn { flex: 1; padding: 8px 12px; background: var(--card); border: 1px solid var(--border);
  border-radius: 6px; color: var(--muted); font-weight: 700; font-size: 12px; cursor: pointer; transition: all 0.2s; }
.tab-btn.active-home { background: rgba(6,182,212,0.09); border-color: var(--cyan); color: var(--cyan); }
.tab-btn.active-away { background: rgba(249,115,22,0.09); border-color: var(--orange); color: var(--orange); }

.section-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px;
  margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }

.k-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 14px; margin-bottom: 8px; transition: border-color 0.3s; }
.k-card.burst-zone { border-color: var(--burst); box-shadow: 0 0 12px var(--burst-bg); }
.k-card-header { display: flex; justify-content: space-between; align-items: center; cursor: pointer; user-select: none; }
.k-card-left { display: flex; align-items: center; gap: 10px; }
.k-name { font-size: 13px; font-weight: 700; color: var(--text); font-family: 'JetBrains Mono', monospace; }
.badge { font-size: 9px; padding: 2px 6px; border-radius: 4px; font-weight: 700; display: inline-block; }
.badge-burst { background: var(--burst); color: #fff; }
.badge-signal { background: var(--orange); color: #000; }
.badge-seq { background: var(--yellow); color: #000; }
.k-card-right { display: flex; align-items: center; gap: 12px; }
.k-value { font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 800; }
.k-value.burst { color: var(--burst); }
.k-value.zero { color: var(--muted); }
.k-value.pos { color: var(--green); }
.pct-techo { font-size: 10px; color: var(--muted); }
.ml-badge { font-size: 10px; padding: 2px 6px; border-radius: 3px; font-weight: 600; }
.ml-incr { background: rgba(34,197,94,0.15); color: var(--green); }
.ml-decr { background: rgba(239,68,68,0.15); color: var(--red); }
.ml-flat { background: rgba(234,179,8,0.15); color: var(--yellow); }
.chevron { color: var(--muted); font-size: 16px; transition: transform 0.2s; }
.chevron.open { transform: rotate(180deg); }

.k-body { margin-top: 12px; display: none; }
.k-body.open { display: block; }
.ecg-label { font-size: 10px; color: var(--muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 1px; }

.stat-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 8px; }
.stat-box { background: var(--deep); border-radius: 6px; padding: 8px; }
.stat-box .lbl { font-size: 9px; color: var(--muted); text-transform: uppercase; }
.stat-box .val { font-size: 13px; color: var(--text); font-weight: 600; margin-top: 2px; }
.stat-box .sub { font-size: 10px; color: var(--muted); }

.peaks-box { margin-top: 8px; background: var(--deep); border-radius: 6px; padding: 8px; }
.peaks-box .title { font-size: 9px; color: var(--muted); text-transform: uppercase; margin-bottom: 6px; letter-spacing: 1px; }
table.peaks { width: 100%; border-collapse: collapse; }
table.peaks th { font-size: 8px; color: var(--muted); text-transform: uppercase; padding: 2px 4px; border-bottom: 1px solid var(--border); }
table.peaks td { font-size: 10px; padding: 3px 4px; border-bottom: 1px solid rgba(30,41,59,0.13); }
td.peak-val { font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700; text-align: center; }
td.peak-date { color: var(--muted); font-family: monospace; text-align: center; }
td.peak-rival { color: var(--text); }
.peak-top { color: var(--burst); }
.techo-bar-wrap { margin-top: 6px; display: flex; align-items: center; gap: 6px; }
.techo-bar-label { font-size: 9px; color: var(--muted); }
.techo-bar-track { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
.techo-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
.techo-bar-pct { font-size: 9px; font-weight: 700; }

.amp-box { margin-top: 8px; background: var(--deep); border-radius: 6px; padding: 8px; }
.amp-row { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
.amp-label { font-size: 9px; color: var(--muted); width: 70px; text-align: right; }
.amp-bar-wrap { flex: 1; }
.amp-bar { height: 14px; border-radius: 2px; transition: width 0.5s; min-width: 2px; }
.amp-count { font-size: 9px; color: var(--muted); width: 16px; }

.info-banner { margin-top: 6px; padding: 6px 10px; border-radius: 4px; font-size: 10px; }
.info-yellow { background: rgba(234,179,8,0.1); border: 1px solid rgba(234,179,8,0.3); color: var(--yellow); }
.info-orange { background: rgba(249,115,22,0.1); border: 1px solid rgba(249,115,22,0.3); color: var(--orange); font-weight: 600; }
.info-red { background: rgba(239,68,68,0.08); color: var(--red); }
.info-seq { background: rgba(234,179,8,0.08); color: var(--yellow); }

.goals-panel { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-top: 16px; }
.goals-title { font-size: 13px; color: var(--accent); margin: 0 0 10px; text-transform: uppercase; letter-spacing: 1px; }
table.goals { width: 100%; border-collapse: collapse; font-size: 11px; }
table.goals th { padding: 4px 6px; color: var(--muted); font-weight: 600; font-size: 9px; text-transform: uppercase; border-bottom: 1px solid var(--border); }
table.goals td { padding: 4px 6px; }
.goals-win { background: rgba(34,197,94,0.08); }
.goals-draw { background: rgba(234,179,8,0.05); }
.goals-loss { background: rgba(239,68,68,0.08); }

.dist-section { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.dist-title { font-size: 9px; color: var(--muted); text-transform: uppercase; margin-bottom: 4px; }
.dist-row { display: flex; align-items: center; gap: 4px; margin-bottom: 2px; }
.dist-g { font-size: 10px; color: var(--muted); width: 10px; text-align: right; }
.dist-bar-wrap { flex: 1; }
.dist-bar { height: 14px; border-radius: 2px; min-width: 2px; }
.dist-info { font-size: 9px; color: var(--muted); width: 30px; }
.dist-mean { font-size: 9px; color: var(--muted); margin-top: 4px; }
.diff-section { margin-top: 12px; }
.diff-d { font-size: 10px; width: 20px; text-align: right; font-family: monospace; font-weight: 700; }
.diff-info { font-size: 9px; color: var(--muted); width: 36px; }
.cycle-info { font-size: 9px; color: var(--muted); margin-top: 4px; }

.ctx-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 16px 0; }
.ctx-card { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 10px; text-align: center; }
.ctx-label { font-size: 8px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
.ctx-val { font-size: 14px; font-weight: 800; margin: 4px 0; }
.ctx-sub { font-size: 9px; color: var(--muted); }

.decision-board { background: #0a1628; border: 2px solid var(--accent); border-radius: 10px; padding: 16px; margin-top: 8px; }
.decision-header { text-align: center; margin-bottom: 12px; }
.decision-header .title { font-size: 10px; text-transform: uppercase; letter-spacing: 2px; color: var(--accent); }
.decision-header .sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
.d-card { background: var(--deep); border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; }
.d-card.d-high { border: 1px solid var(--burst); border-left: 3px solid var(--burst); }
.d-card.d-medium { border: 1px solid var(--orange); border-left: 3px solid var(--orange); }
.d-card-top { display: flex; justify-content: space-between; align-items: start; }
.d-title { font-size: 12px; font-weight: 700; color: var(--text); }
.d-detail { font-size: 10px; color: var(--muted); margin-top: 2px; }
.d-sev { font-size: 8px; padding: 2px 6px; border-radius: 3px; color: #fff; font-weight: 700; text-transform: uppercase; white-space: nowrap; }
.d-sev-high { background: var(--burst); }
.d-sev-medium { background: var(--orange); }
.d-question { margin-top: 6px; padding: 6px 8px; background: rgba(59,130,246,0.08);
  border-radius: 4px; border: 1px solid rgba(59,130,246,0.2); }
.d-question span { font-size: 10px; color: var(--accent); font-weight: 600; }

.footer { text-align: center; padding: 12px 0; font-size: 9px; color: var(--muted);
  border-top: 1px solid var(--border); margin-top: 16px; }

.res-win { color: var(--green); font-weight: 600; }
.res-draw { color: var(--yellow); font-weight: 600; }
.res-loss { color: var(--red); font-weight: 600; }

/* === PATCH: K Summary Bars === */
.k-summary { margin-bottom: 16px; padding: 14px; background: var(--card); border: 1px solid var(--border); border-radius: 8px; }
.k-summary-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; }
.k-summary-teams { display: flex; justify-content: space-between; margin-bottom: 4px; padding: 0 74px 0 0; font-size: 11px; }
.k-summary-teams .home-lbl { color: var(--cyan); font-weight: 700; }
.k-summary-teams .away-lbl { color: var(--orange); font-weight: 700; }
.k-summary-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.k-summary-row-name { font-size: 11px; color: var(--muted); min-width: 66px; text-align: right; font-weight: 600; }
.k-summary-bar { flex: 1; display: flex; height: 30px; border-radius: 5px; overflow: hidden; }
.k-summary-seg { display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: #fff; min-width: 28px; transition: width 0.4s; }
.k-summary-seg.seg-local { background: #22c55e; }
.k-summary-seg.seg-empate { background: #475569; color: var(--text); }
.k-summary-seg.seg-visita { background: #ef4444; }
.k-summary-seg.seg-goles { background: #3b82f6; }
.k-summary-seg.seg-corta { background: #475569; color: var(--text); }
.k-summary-legend { display: flex; gap: 10px; justify-content: center; margin-top: 6px; font-size: 9px; color: var(--muted); }
.k-summary-legend span { display: flex; align-items: center; gap: 3px; }
.k-summary-legend .dot { width: 7px; height: 7px; border-radius: 2px; display: inline-block; }

/* === PATCH: ECG Tooltip === */
#ecg-tooltip {
  position: fixed; display: none; z-index: 9999;
  background: #1e293b; border: 1px solid #334155; border-radius: 6px;
  padding: 8px 10px; pointer-events: none; min-width: 140px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
#ecg-tooltip .tt-rival { font-size: 12px; font-weight: 700; color: #e2e8f0; margin-bottom: 3px; }
#ecg-tooltip .tt-row { font-size: 10px; color: #94a3b8; display: flex; justify-content: space-between; gap: 12px; }
#ecg-tooltip .tt-val { font-family: 'JetBrains Mono', monospace; font-weight: 700; }
#ecg-tooltip .tt-pos { color: #22c55e; }
#ecg-tooltip .tt-neg { color: #ef4444; }
#ecg-tooltip .tt-zero { color: #64748b; }
#ecg-tooltip .tt-lvl { color: #a78bfa; }
</style>
</head>
<body>
<div class="container" id="app"></div>
<div id="ecg-tooltip"></div>

<script>
const DATA = __INJECTED_DATA__;

function resClass(res) {
  const p = res.split('-').map(Number);
  return p[0] > p[1] ? 'res-win' : p[0] < p[1] ? 'res-loss' : 'res-draw';
}
function mlClass(ml) {
  const m = ml.toUpperCase();
  return m === 'INCR' ? 'ml-incr' : m === 'DECR' ? 'ml-decr' : 'ml-flat';
}
function barWidth(pct, max) { return Math.max((pct / (max || 50)) * 100, 2) + '%'; }

function percentile(arr, p) {
  if (!arr.length) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function calcBurstThreshold(data) {
  const positives = data.map(d => d.val).filter(v => v > 0);
  if (positives.length < 3) return null;
  return percentile(positives, 75);
}

// === PATCH: ECG Tooltip via data-* attributes ===
function showEcgTip(evt, el) {
  var tip = document.getElementById('ecg-tooltip');
  if (!tip) return;
  var r = el.dataset;
  var val = parseFloat(r.val || 0);
  var vc = val > 0 ? 'tt-pos' : val < 0 ? 'tt-neg' : 'tt-zero';
  var h = '';
  if (r.rival) h += '<div class="tt-rival">' + r.rival + '</div>';
  h += '<div class="tt-row"><span>' + (r.date||'') + '</span>';
  if (r.res) h += '<span>' + r.res + '</span>';
  h += '</div>';
  h += '<div class="tt-row"><span>Valor K</span><span class="tt-val ' + vc + '">' + val.toFixed(2) + '</span></div>';
  if (r.lvl && r.lvl !== '') {
    h += '<div class="tt-row"><span>Nivel rival</span><span class="tt-val tt-lvl">' + parseFloat(r.lvl).toFixed(2) + '</span></div>';
  }
  tip.innerHTML = h;
  tip.style.display = 'block';
  tip.style.left = Math.min(evt.clientX + 12, window.innerWidth - 180) + 'px';
  tip.style.top = Math.max(evt.clientY - 10, 4) + 'px';
}
function hideEcgTip() {
  var tip = document.getElementById('ecg-tooltip');
  if (tip) tip.style.display = 'none';
}

function renderECG(data) {
  if (!data || !data.length) return '<div style="color:var(--muted);font-size:10px">Sin datos</div>';
  const burstMin = calcBurstThreshold(data);
  const h = 80;
  const minBarW = 8, maxBarW = 28, gap = 2;
  const barW = Math.max(minBarW, Math.min(maxBarW, Math.floor(400 / data.length) - gap));
  const w = Math.max(400, data.length * (barW + gap) + 24);
  const absMax = Math.max(...data.map(d => Math.abs(d.val)), 1);
  const mid = h / 2;

  let svg = `<svg width="${w}" height="${h + 28}" style="display:block">`;
  svg += `<line x1="10" y1="${mid}" x2="${w-10}" y2="${mid}" stroke="#334155" stroke-width="1" stroke-dasharray="3,3"/>`;

  if (burstMin && burstMin > 0) {
    const by = mid - (burstMin / absMax) * (mid - 4);
    if (by > 2) {
      svg += `<line x1="10" y1="${by}" x2="${w-10}" y2="${by}" stroke="var(--burst)" stroke-width="1" stroke-dasharray="4,4" stroke-opacity="0.5"/>`;
      svg += `<text x="${w-8}" y="${by-3}" fill="var(--burst)" font-size="8" text-anchor="end" opacity="0.7">P75: ${burstMin.toFixed(1)}</text>`;
    }
  }

  data.forEach((d, i) => {
    const x = 12 + i * (barW + gap);
    const barH = (Math.abs(d.val) / absMax) * (mid - 4);
    const y = d.val >= 0 ? mid - barH : mid;
    const isLast = i === data.length - 1;
    const inBurst = burstMin && d.val >= burstMin;
    const fill = isLast ? 'var(--cyan)' : inBurst ? 'var(--burst)' : d.val > 0 ? 'var(--green)' : d.val < 0 ? 'var(--red)' : '#334155';
    const op = isLast ? 1 : 0.75;
    var _rv = (d.rival||'').replace(/"/g,'');
    svg += `<rect x="${x}" y="${y}" width="${barW}" height="${Math.max(barH,1)}" fill="${fill}" rx="1" opacity="${op}" style="cursor:pointer" data-rival="${_rv}" data-res="${d.res||''}" data-val="${d.val}" data-date="${d.date}" data-lvl="${d.lvl!=null?d.lvl:''}" onmouseover="showEcgTip(event,this)" onmouseout="hideEcgTip()"/>`;
    if (isLast) svg += `<text x="${x+barW/2}" y="${d.val>=0 ? y-3 : y+barH+10}" fill="var(--cyan)" font-size="9" font-weight="700" text-anchor="middle">${d.val}</text>`;
    const showLabel = data.length <= 30 || i % Math.ceil(data.length / 30) === 0 || isLast;
    if (showLabel) svg += `<text x="${x+barW/2}" y="${h+14}" fill="var(--muted)" font-size="6.5" text-anchor="middle" transform="rotate(-35,${x+barW/2},${h+14})">${d.date}</text>`;
  });

  svg += '</svg>';
  return `<div style="overflow-x:auto">${svg}</div>`;
}

const ecgRanges = {};
function setEcgRange(idx, range) {
  ecgRanges[idx] = range;
  const container = document.getElementById('ecg-container-' + idx);
  if (!container) return;
  const c = ecgDataStore[idx];
  if (!c) return;
  const allEcg = c.ecg || [];
  const sliced = range === 0 ? allEcg : allEcg.slice(-range);
  container.innerHTML = renderECG(sliced);
  document.querySelectorAll('#ecg-btns-' + idx + ' button').forEach(btn => {
    const r = parseInt(btn.dataset.range);
    btn.style.background = r === range ? 'var(--accent)' : 'var(--deep)';
    btn.style.color = r === range ? '#fff' : 'var(--muted)';
  });
}
const ecgDataStore = {};

function renderConstantCard(c, idx) {
  const isBurst = !!c.burstZone;
  const valueClass = isBurst ? 'burst' : c.value === 0 ? 'zero' : 'pos';
  const ml = (c.ml || '').toUpperCase();

  let badges = '';
  if (isBurst) badges += '<span class="badge badge-burst">ZONA BURST</span>';
  if (c.flag) badges += '<span class="badge badge-signal">SEÑAL</span>';
  if (c.sequoia > 2) badges += `<span class="badge badge-seq">${c.sequoia}× en 0</span>`;

  let body = '';
  const defaultRange = 6;
  ecgDataStore[idx] = c;
  ecgRanges[idx] = defaultRange;
  const allEcg = c.ecg || [];
  const slicedEcg = allEcg.slice(-defaultRange);
  const ranges = [6, 12, 24, 48, 0];
  const rangeLabels = {6:'6', 12:'12', 24:'24', 48:'48', 0:'Todo'};

  body += `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
    <div class="ecg-label" style="margin:0">Electrocardiograma</div>
    <div id="ecg-btns-${idx}" style="display:flex;gap:3px">`;
  ranges.forEach(r => {
    const active = r === defaultRange;
    body += `<button data-range="${r}" onclick="setEcgRange(${idx},${r})" style="
      padding:2px 8px;border-radius:3px;border:1px solid var(--border);font-size:9px;cursor:pointer;
      font-weight:600;background:${active?'var(--accent)':'var(--deep)'};color:${active?'#fff':'var(--muted)'};
    ">${rangeLabels[r]}</button>`;
  });
  body += `</div></div>`;
  body += `<div id="ecg-container-${idx}">${renderECG(slicedEcg)}</div>`;

  body += `<div class="stat-grid">
    <div class="stat-box"><div class="lbl">Inercia</div><div class="val">${c.inertia||'—'}</div><div class="sub">Accel: ${c.accel||'—'}</div></div>
    <div class="stat-box"><div class="lbl">Bursts</div><div class="val">${c.totalBursts||'—'} total</div><div class="sub">c/${c.burstFreqMedian||'—'} partidos</div></div>
    <div class="stat-box"><div class="lbl">Desde últ burst</div><div class="val" style="color:${c.sinceLastBurst >= (c.burstFreqMedian||99) ? 'var(--orange)' : 'var(--text)'}">${c.sinceLastBurst||'—'} partidos</div><div class="sub">mediana: ${c.burstFreqMedian||'—'}</div></div>
  </div>`;

  const pk = c.peaks || {};
  const hasAnyPeak = (pk.pos && pk.pos.length) || (pk.neg && pk.neg.length) || (pk.zero && pk.zero.length);
  const hasTop4 = !hasAnyPeak && c.top4 && c.top4.length;

  if (hasAnyPeak || hasTop4) {
    body += `<div class="peaks-box">`;
    function peakTable(title, icon, list, valColor) {
      if (!list || !list.length) return '';
      let h = `<div style="margin-bottom:8px"><div class="title">${icon} ${title}</div>
      <table class="peaks"><thead><tr><th style="text-align:center">#</th><th style="text-align:center">Valor</th><th style="text-align:center">Fecha</th><th>Rival</th><th style="text-align:center">Res</th></tr></thead><tbody>`;
      list.forEach((p, j) => {
        h += `<tr><td style="text-align:center;color:var(--muted)">${j+1}</td>
          <td class="peak-val" style="color:${valColor}">${p.val.toFixed(2)}</td>
          <td class="peak-date">${p.date}</td>
          <td class="peak-rival">${p.rival||''}</td>
          <td style="text-align:center" class="${p.res ? resClass(p.res) : ''}">${p.res||''}</td></tr>`;
      });
      return h + '</tbody></table></div>';
    }
    if (hasAnyPeak) {
      body += peakTable('Picos Positivos', '🔺', pk.pos, 'var(--green)');
      body += peakTable('Picos Negativos', '🔻', pk.neg, 'var(--red)');
      body += peakTable('Resets (k=0)', '⏸', pk.zero, 'var(--yellow)');
    } else {
      body += peakTable('Top 4 Picos Históricos', '🏔', c.top4, 'var(--burst)');
    }
    const barColor = isBurst ? 'var(--burst)' : 'var(--accent)';
    body += `<div class="techo-bar-wrap"><span class="techo-bar-label">Valor actual vs techo:</span>
      <div class="techo-bar-track"><div class="techo-bar-fill" style="width:${Math.min(c.pctTecho,100)}%;background:${barColor}"></div></div>
      <span class="techo-bar-pct" style="color:${barColor}">${c.pctTecho}%</span></div></div>`;
  }

  if (c.burstAmplitude) {
    const bb = c.burstBands || [];
    const colors = ['var(--yellow)', 'var(--orange)', 'var(--red)', 'var(--burst)'];
    const keys = ['baja', 'media', 'alta', 'extrema'];
    const bands = keys.map((k, i) => ({label: bb[i] ? bb[i].label : k, n: c.burstAmplitude[k] || 0, color: colors[i]}));
    const maxAmp = Math.max(...bands.map(b => b.n), 1);
    body += `<div class="amp-box"><div class="ecg-label">Amplitud de bursts (P75=${c.burstMin||'?'})</div>`;
    bands.forEach(b => {
      body += `<div class="amp-row"><span class="amp-label">${b.label}</span>
        <div class="amp-bar-wrap"><div class="amp-bar" style="width:${barWidth(b.n, maxAmp)};background:${b.color}"></div></div>
        <span class="amp-count">${b.n}</span></div>`;
    });
    body += '</div>';
  }

  if (c.postBurst) {
    const txt = c.postBurst.dato || c.postBurst.anota || c.postBurst.recibe || '';
    body += `<div class="info-banner info-yellow">⚡ Post-burst: ${txt}</div>`;
  }
  if (c.sequoia > 0) {
    body += `<div class="info-banner info-seq">Sequía: ${c.sequoia} en 0 | Historial: ${c.seqHist||'—'}`;
    if (c.reboteVisita) body += `<br>Rebote de visita: ${c.reboteVisita}`;
    body += '</div>';
  }
  if (c.postBurstNoAnota) body += `<div class="info-banner info-red">⛔ ${c.postBurstNoAnota}</div>`;
  if (c.flag) body += `<div class="info-banner info-orange">${c.flag}</div>`;

  return `<div class="k-card ${isBurst?'burst-zone':''}" id="kcard-${idx}">
    <div class="k-card-header" onclick="toggleCard(${idx})">
      <div class="k-card-left"><span class="k-name">${c.name}</span>${badges}</div>
      <div class="k-card-right">
        <span class="k-value ${valueClass}">${c.value.toFixed(2)}</span>
        <span class="pct-techo">${c.pctTecho}% techo</span>
        <span class="ml-badge ${mlClass(ml)}">${ml}</span>
        <span class="chevron" id="chev-${idx}">▼</span>
      </div>
    </div>
    <div class="k-body" id="kbody-${idx}">${body}</div>
  </div>`;
}

// Goals panel
const goalsDataStore = {};
function calcGoalStats(matches) {
  if (!matches.length) return {gfMean:0,gfMedian:0,gcMean:0,gcMedian:0,diffMean:0,ciclo:'—',gfDist:[],gcDist:[],diffDist:[]};
  const gf=matches.map(m=>m.gf),gc=matches.map(m=>m.gc),diff=matches.map(m=>m.gf-m.gc);
  const mean=a=>a.reduce((s,v)=>s+v,0)/a.length;
  const med=a=>{const s=[...a].sort((x,y)=>x-y);const m=Math.floor(s.length/2);return s.length%2?s[m]:(s[m-1]+s[m])/2;};
  function dist(arr,key){const c={};arr.forEach(v=>c[v]=(c[v]||0)+1);return Object.entries(c).map(([g,n])=>({[key]:+g,n,pct:Math.round(n/arr.length*100)})).sort((a,b)=>a[key]-b[key]);}
  const last5=gf.slice(-5);
  return {gfMean:mean(gf).toFixed(2),gfMedian:med(gf),gcMean:mean(gc).toFixed(2),gcMedian:med(gc),
    diffMean:mean(diff).toFixed(2),ciclo:mean(last5)>=1?'PRODUCTIVO':'IMPRODUCTIVO',
    gfDist:dist(gf,'g'),gcDist:dist(gc,'g'),diffDist:dist(diff,'d')};
}

function renderGoalsContent(panelId, matches, teamName) {
  const tbody = document.getElementById('tbody-' + panelId);
  const statsEl = document.getElementById('stats-' + panelId);
  if (!tbody || !statsEl) return;
  let html = '';
  matches.forEach(m => {
    const d=m.gf-m.gc; const cls=d>0?'goals-win':d<0?'goals-loss':'goals-draw';
    const dStr=d>0?'+'+d:''+d; const dColor=d>0?'var(--green)':d<0?'var(--red)':'var(--yellow)';
    const cond=m.is_home?'L':'V'; const condColor=m.is_home?'var(--cyan)':'var(--orange)';
    html+=`<tr class="${cls}"><td style="color:var(--muted);font-family:monospace;font-size:10px;text-align:center">${m.date}</td>
      <td style="text-align:center;font-weight:700;font-size:10px;color:${condColor}">${cond}</td><td>${m.rival}</td>
      <td style="font-family:monospace;font-weight:700;text-align:center;color:${dColor}">${m.res}</td>
      <td style="text-align:center;font-weight:700;color:${m.gf>0?'var(--green)':'var(--muted)'}">${m.gf}</td>
      <td style="text-align:center;font-weight:700;color:${m.gc>0?'var(--red)':'var(--muted)'}">${m.gc}</td>
      <td style="text-align:center;font-family:monospace;font-weight:700;color:${dColor}">${dStr}</td></tr>`;
  });
  tbody.innerHTML = html;
  const s = calcGoalStats(matches); const n = matches.length;
  function distHTML(arr,color,label){let h=`<div><div class="dist-title">${label} (${n})</div>`;
    (arr||[]).forEach(d=>{h+=`<div class="dist-row"><span class="dist-g">${d.g!==undefined?d.g:d.d}</span>
      <div class="dist-bar-wrap"><div class="dist-bar" style="width:${barWidth(d.pct,50)};background:${color}"></div></div>
      <span class="dist-info">${d.n} (${d.pct}%)</span></div>`;});return h+'</div>';}
  function diffHTML(arr){let h='';(arr||[]).forEach(d=>{const c=d.d>0?'var(--green)':d.d<0?'var(--red)':'var(--yellow)';
    h+=`<div class="dist-row"><span class="diff-d" style="color:${c}">${d.d>0?'+'+d.d:d.d}</span>
      <div class="dist-bar-wrap"><div class="dist-bar" style="width:${barWidth(d.pct,50)};background:${c}"></div></div>
      <span class="diff-info">${d.n} (${d.pct}%)</span></div>`;});return h;}
  const cc=s.ciclo==='PRODUCTIVO'?'var(--green)':'var(--red)';
  statsEl.innerHTML=`<div class="dist-section">${distHTML(s.gfDist,'var(--green)','Distribución GF')}${distHTML(s.gcDist,'var(--red)','Distribución GC')}</div>
    <div style="font-size:9px;color:var(--muted);margin-top:4px">μ GF ${s.gfMean} · med ${s.gfMedian} | μ GC ${s.gcMean} · med ${s.gcMedian}</div>
    <div class="diff-section"><div class="dist-title">Diferencia de goles (${n})</div>${diffHTML(s.diffDist)}
    <div class="cycle-info">μ dif: ${s.diffMean>0?'+':''}${s.diffMean} · Ciclo: <span style="color:${cc};font-weight:600">${s.ciclo}</span></div></div>`;
}

function setGoalsFilter(panelId, filter) {
  const store=goalsDataStore[panelId]; if(!store) return;
  let filtered; if(filter==='L') filtered=store.matches.filter(m=>m.is_home);
  else if(filter==='V') filtered=store.matches.filter(m=>!m.is_home);
  else filtered=store.matches;
  renderGoalsContent(panelId, filtered.slice(-10), store.teamName);
  document.querySelectorAll('#goals-filter-'+panelId+' button').forEach(btn=>{
    const f=btn.dataset.filter; const a=f===filter;
    btn.style.background=a?'var(--accent)':'var(--deep)'; btn.style.color=a?'#fff':'var(--muted)';
  });
}

function renderGoalsPanel(data, teamName, ctx) {
  if (!data) return '';
  const allMatches = data.matches || [];
  const id = 'goals-' + ctx.replace(/\s/g, '');
  goalsDataStore[id] = { matches: allMatches, teamName };
  const dm = allMatches.slice(-10);
  let mh = '';
  dm.forEach(m => {
    const d=m.gf-m.gc; const cls=d>0?'goals-win':d<0?'goals-loss':'goals-draw';
    const dStr=d>0?'+'+d:''+d; const dColor=d>0?'var(--green)':d<0?'var(--red)':'var(--yellow)';
    const cond=m.is_home?'L':'V'; const condColor=m.is_home?'var(--cyan)':'var(--orange)';
    mh+=`<tr class="${cls}"><td style="color:var(--muted);font-family:monospace;font-size:10px;text-align:center">${m.date}</td>
      <td style="text-align:center;font-weight:700;font-size:10px;color:${condColor}">${cond}</td><td>${m.rival}</td>
      <td style="font-family:monospace;font-weight:700;text-align:center;color:${dColor}">${m.res}</td>
      <td style="text-align:center;font-weight:700;color:${m.gf>0?'var(--green)':'var(--muted)'}">${m.gf}</td>
      <td style="text-align:center;font-weight:700;color:${m.gc>0?'var(--red)':'var(--muted)'}">${m.gc}</td>
      <td style="text-align:center;font-family:monospace;font-weight:700;color:${dColor}">${dStr}</td></tr>`;
  });
  const is=calcGoalStats(dm); const cc=is.ciclo==='PRODUCTIVO'?'var(--green)':'var(--red)';
  function distHTML(arr,color,label,n){let h=`<div><div class="dist-title">${label} (${n})</div>`;
    (arr||[]).forEach(d=>{h+=`<div class="dist-row"><span class="dist-g">${d.g!==undefined?d.g:d.d}</span>
      <div class="dist-bar-wrap"><div class="dist-bar" style="width:${barWidth(d.pct,50)};background:${color}"></div></div>
      <span class="dist-info">${d.n} (${d.pct}%)</span></div>`;});return h+'</div>';}
  function diffHTML(arr){let h='';(arr||[]).forEach(d=>{const c=d.d>0?'var(--green)':d.d<0?'var(--red)':'var(--yellow)';
    h+=`<div class="dist-row"><span class="diff-d" style="color:${c}">${d.d>0?'+'+d.d:d.d}</span>
      <div class="dist-bar-wrap"><div class="dist-bar" style="width:${barWidth(d.pct,50)};background:${c}"></div></div>
      <span class="diff-info">${d.n} (${d.pct}%)</span></div>`;});return h;}
  const dn=dm.length;
  return `<div class="goals-panel" id="${id}">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
      <div class="goals-title" style="margin:0">${teamName} — Últimos partidos</div>
      <div id="goals-filter-${id}" style="display:flex;gap:3px">
        <button data-filter="all" onclick="setGoalsFilter('${id}','all')" style="padding:3px 10px;border-radius:3px;border:1px solid var(--border);font-size:10px;cursor:pointer;font-weight:600;background:var(--accent);color:#fff">Todos</button>
        <button data-filter="L" onclick="setGoalsFilter('${id}','L')" style="padding:3px 10px;border-radius:3px;border:1px solid var(--border);font-size:10px;cursor:pointer;font-weight:600;background:var(--deep);color:var(--muted)">Local</button>
        <button data-filter="V" onclick="setGoalsFilter('${id}','V')" style="padding:3px 10px;border-radius:3px;border:1px solid var(--border);font-size:10px;cursor:pointer;font-weight:600;background:var(--deep);color:var(--muted)">Visita</button>
      </div>
    </div>
    <div style="overflow-x:auto"><table class="goals"><thead><tr>
      <th style="text-align:center">Fecha</th><th style="text-align:center">Cond</th><th>Rival</th><th style="text-align:center">Res</th>
      <th style="text-align:center">GF</th><th style="text-align:center">GC</th><th style="text-align:center">Dif</th>
    </tr></thead><tbody id="tbody-${id}">${mh}</tbody></table></div>
    <div id="stats-${id}">
      <div class="dist-section">${distHTML(is.gfDist,'var(--green)','Distribución GF',dn)}${distHTML(is.gcDist,'var(--red)','Distribución GC',dn)}</div>
      <div style="font-size:9px;color:var(--muted);margin-top:4px">μ GF ${is.gfMean} · med ${is.gfMedian} | μ GC ${is.gcMean} · med ${is.gcMedian}</div>
      <div class="diff-section"><div class="dist-title">Diferencia de goles (${dn})</div>${diffHTML(is.diffDist)}
      <div class="cycle-info">μ dif: ${is.diffMean>0?'+':''}${is.diffMean} · Ciclo: <span style="color:${cc};font-weight:600">${is.ciclo}</span></div></div>
    </div></div>`;
}

function renderContextBar(ctx) {
  if (!ctx || !ctx.length) return '';
  return `<div class="ctx-grid">${ctx.map(c=>
    `<div class="ctx-card"><div class="ctx-label">${c.label}</div>
     <div class="ctx-val" style="color:${c.color||'var(--text)'}">${c.val}</div>
     <div class="ctx-sub">${c.sub||''}</div></div>`
  ).join('')}</div>`;
}

function renderDecisions(decisions) {
  if (!decisions || !decisions.length) return '';
  let cards='';
  decisions.forEach(d=>{const sev=d.severity||'medium';
    cards+=`<div class="d-card d-${sev}"><div class="d-card-top"><div>
      <div class="d-title">${d.id}. ${d.title}</div><div class="d-detail">${d.detail}</div>
    </div><span class="d-sev d-sev-${sev}">${sev==='high'?'alta':'media'}</span></div>
    <div class="d-question"><span>→ ${d.question}</span></div></div>`;});
  return `<div class="decision-board"><div class="decision-header">
    <div class="title">Tablero de decisiones</div>
    <div class="sub">Puntos donde se requiere juicio humano</div></div>${cards}</div>`;
}

// === PATCH: K Summary render ===
function renderKSummary(d) {
  var ks = d.k_summary;
  if (!ks) return '';
  var pL=Math.round(ks.p_local||0), pE=Math.round(ks.p_empate||0), pV=Math.round(ks.p_visita||0);
  var pG=Math.round(ks.p_hay_goles||0), pC=Math.round(ks.p_se_corta||0);
  return '<div class="k-summary">'+
    '<div class="k-summary-label">Resumen K \u2014 Predicci\u00f3n ML</div>'+
    '<div class="k-summary-teams"><span class="home-lbl">'+d.home_team+' (L)</span>'+
    '<span class="away-lbl">'+d.away_team+' (V)</span></div>'+
    '<div class="k-summary-row"><span class="k-summary-row-name">K resultado</span>'+
    '<div class="k-summary-bar">'+
    '<div class="k-summary-seg seg-local" style="width:'+pL+'%">'+pL+'%</div>'+
    '<div class="k-summary-seg seg-empate" style="width:'+pE+'%">'+pE+'%</div>'+
    '<div class="k-summary-seg seg-visita" style="width:'+pV+'%">'+pV+'%</div>'+
    '</div></div>'+
    '<div class="k-summary-row"><span class="k-summary-row-name">K goles</span>'+
    '<div class="k-summary-bar">'+
    '<div class="k-summary-seg seg-goles" style="width:'+pG+'%">'+pG+'%</div>'+
    '<div class="k-summary-seg seg-corta" style="width:'+pC+'%">'+pC+'%</div>'+
    '</div></div>'+
    '<div class="k-summary-legend">'+
    '<span><span class="dot" style="background:#22c55e"></span> Local</span>'+
    '<span><span class="dot" style="background:#475569"></span> Empate / Se corta</span>'+
    '<span><span class="dot" style="background:#ef4444"></span> Visita</span>'+
    '<span><span class="dot" style="background:#3b82f6"></span> Hay goles</span>'+
    '</div></div>';
}

let activeTeam = 'home';
function render() {
  const d = DATA;
  const isHome = activeTeam === 'home';
  const constants = isHome ? (d.home_constants || []) : (d.away_constants || []);
  const goals = isHome ? d.home_goals : d.away_goals;
  const teamName = isHome ? d.home_team : d.away_team;
  const ctx = isHome ? 'Local' : 'Visita';
  const dotColor = isHome ? 'var(--cyan)' : 'var(--orange)';
  let html = '';
  html += `<div class="header"><div class="phase">${d.phase || 'SAD · Fase 1 · Extracción sin veredicto'}</div>
    <h1><span class="home">${d.home_team || '—'}</span><span class="vs">vs</span><span class="away">${d.away_team || '—'}</span></h1>
    <div class="meta">${d.match_info || ''}</div></div>`;
  html += `<div class="tabs">
    <button class="tab-btn ${isHome?'active-home':''}" onclick="switchTeam('home')">${d.home_team || 'Local'} (L)</button>
    <button class="tab-btn ${!isHome?'active-away':''}" onclick="switchTeam('away')">${d.away_team || 'Visita'} (V)</button></div>`;

  // K Summary
  html += renderKSummary(d);

  // Constants section
  html += `<div style="margin-bottom:16px">
    <div class="section-label"><span class="dot" style="background:${dotColor}"></span>Constantes K — click para expandir</div>`;
  constants.forEach((c, i) => { html += renderConstantCard(c, i); });
  html += '</div>';
  html += renderGoalsPanel(goals, teamName, ctx);
  html += renderContextBar(d.context_bar);
  html += renderDecisions(d.decisions);
  html += `<div class="footer">SAD Fase 1 · Extracción mecánica sin veredicto · ${new Date().toLocaleDateString()}</div>`;
  document.getElementById('app').innerHTML = html;
}

function switchTeam(team) {
  activeTeam = team;
  Object.keys(ecgRanges).forEach(k => delete ecgRanges[k]);
  Object.keys(ecgDataStore).forEach(k => delete ecgDataStore[k]);
  Object.keys(goalsDataStore).forEach(k => delete goalsDataStore[k]);
  render();
}
function toggleCard(idx) {
  const body = document.getElementById('kbody-' + idx);
  const chev = document.getElementById('chev-' + idx);
  if (body.classList.contains('open')) { body.classList.remove('open'); chev.classList.remove('open'); }
  else { body.classList.add('open'); chev.classList.add('open'); }
}

render();
</script>
</body>
</html>"""


class SADDashboardWindow(QMainWindow):
    """
    Ventana del SAD Dashboard.
    Recibe un dict con la data del partido y renderiza el dashboard
    completo en un QWebEngineView embebido.
    """

    def __init__(self, match_data: Dict[str, Any] = None, parent=None):
        super().__init__(parent)
        self._match_data = match_data or {}
        self.setWindowTitle(
            f"📊 SAD Dashboard — "
            f"{self._match_data.get('home_team', '?')} vs "
            f"{self._match_data.get('away_team', '?')}"
        )
        self.setMinimumSize(980, 700)
        self.resize(1000, 850)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view)
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage(
            f"📊 {self._match_data.get('home_team', '')} vs "
            f"{self._match_data.get('away_team', '')} · Fase 1 Extracción"
        )
        self._render()

    def _render(self):
        try:
            data_json = json.dumps(self._match_data, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"Error serializando match_data: {e}")
            data_json = '{}'
        html = _HTML_TEMPLATE.replace('__INJECTED_DATA__', data_json)
        self.web_view.setHtml(html, QUrl("about:blank"))

    def update_data(self, match_data: Dict[str, Any]):
        self._match_data = match_data
        self.setWindowTitle(
            f"📊 SAD Dashboard — "
            f"{match_data.get('home_team', '?')} vs "
            f"{match_data.get('away_team', '?')}"
        )
        self._render()

    def inject_k_summary(self, team_predictions: Dict, rival_predictions: Dict):
        """
        Inyecta el resumen K a partir de predicciones ya calculadas.
        Llamar después de construir el dashboard, antes o después de show().
        Re-renderiza automáticamente.
        """
        try:
            from sad_dashboard_loader import calculate_k_summary
            ks = calculate_k_summary(team_predictions, rival_predictions)
            self._match_data['k_summary'] = ks
            self._render()
            logger.info(f"K Summary inyectado: L={ks['p_local']:.0f}% E={ks['p_empate']:.0f}% V={ks['p_visita']:.0f}%")
        except Exception as e:
            logger.warning(f"Error inyectando K summary: {e}")

    @classmethod
    def from_db(cls, home_team_id, away_team_id, match_info='',
                context_bar=None, decisions=None,
                team_predictions=None, rival_predictions=None,
                parent=None):
        try:
            from sad_dashboard_loader import build_dashboard_data
        except ImportError:
            from ui.sad_dashboard_loader import build_dashboard_data
        data = build_dashboard_data(
            home_team_id=home_team_id, away_team_id=away_team_id,
            match_info=match_info, context_bar=context_bar, decisions=decisions,
            team_predictions=team_predictions, rival_predictions=rival_predictions,
        )
        return cls(match_data=data, parent=parent)


def _build_demo_data() -> Dict[str, Any]:
    """Datos de demostración (Sporting Cristal vs Carabobo FC)."""
    return {
        "home_team": "Sporting Cristal",
        "away_team": "Carabobo FC",
        "match_info": "Libertadores Fase 3 · Vuelta · 11/03/2026 · SC ganó ida 1-0",
        "phase": "SAD · Fase 1 · Extracción sin veredicto",

        "k_summary": {
            "p_local": 43, "p_empate": 37, "p_visita": 20,
            "p_hay_goles": 60, "p_se_corta": 40,
        },

        "home_constants": [
            {
                "name": "k general", "value": 5.3, "techo": 32.71, "pctTecho": 16,
                "burstZone": True, "burstMin": 5.05, "burstMedian": 10.7,
                "inertia": "↗ SUBIENDO", "accel": "+1.99",
                "totalBursts": 51, "burstFreqMedian": 5, "sinceLastBurst": 6,
                "burstAmplitude": {"baja": 13, "media": 19, "alta": 12, "extrema": 7},
                "ml": "INCR",
                "peaks": {"pos": [{"val": 32.71, "date": "2020-11-14", "rival": "Dep. Binacional", "res": "2-1"}],
                          "neg": [{"val": -6.97, "date": "2025-12-14", "rival": "Alianza Lima", "res": "0-2"}],
                          "zero": [{"val": 0.0, "date": "2026-02-25", "rival": "2 de Mayo", "res": "0-0"}]},
                "ecg": [
                    {"date": "25-12-11", "val": 3.43, "rival": "Cusco", "res": "1-0", "lvl": 0.87},
                    {"date": "25-12-14", "val": -6.97, "rival": "Alianza Lima", "res": "0-2", "lvl": 2.14},
                    {"date": "26-01-25", "val": 3.29, "rival": "U. Católica", "res": "3-1", "lvl": 1.55},
                    {"date": "26-02-01", "val": 0, "rival": "Sport Huancayo", "res": "1-1", "lvl": 0.95},
                    {"date": "26-02-08", "val": -2.8, "rival": "FBC Melgar", "res": "1-2", "lvl": 1.78},
                    {"date": "26-02-14", "val": 5.61, "rival": "Cienciano", "res": "2-0", "lvl": 1.12},
                    {"date": "26-02-18", "val": 0, "rival": "Ayacucho FC", "res": "0-0", "lvl": 0.72},
                    {"date": "26-02-21", "val": 0, "rival": "Universitario", "res": "2-2", "lvl": 2.31},
                    {"date": "26-02-25", "val": 0, "rival": "2 de Mayo", "res": "0-0", "lvl": 0.55},
                    {"date": "26-02-28", "val": -1.91, "rival": "Alianza Atlético", "res": "0-1", "lvl": 0.91},
                    {"date": "26-03-04", "val": 0.7, "rival": "UTC Cajamarca", "res": "1-0", "lvl": 0.83},
                    {"date": "26-03-07", "val": 5.3, "rival": "Alianza Atlético", "res": "3-1", "lvl": 1.23},
                ],
            },
            {
                "name": "k local", "value": 4.6, "techo": 41.65, "pctTecho": 11,
                "burstZone": False, "burstMin": 5.0, "burstMedian": 10.9,
                "inertia": "↔ LATERAL", "accel": "+4.60",
                "totalBursts": 27, "burstFreqMedian": 5, "sinceLastBurst": 4,
                "burstAmplitude": {"baja": 6, "media": 9, "alta": 8, "extrema": 4},
                "ml": "INCR",
                "peaks": {"pos": [{"val": 41.65, "date": "2024-03-02", "rival": "Atlético Grau", "res": "1-0"}], "neg": [], "zero": []},
                "ecg": [
                    {"date": "25-09-29", "val": 4.64, "rival": "Ayacucho FC", "res": "3-0", "lvl": 0.72},
                    {"date": "25-10-24", "val": -4.02, "rival": "Universitario", "res": "0-1", "lvl": 2.31},
                    {"date": "25-11-07", "val": 2.42, "rival": "Cienciano", "res": "2-1", "lvl": 1.12},
                    {"date": "25-12-03", "val": 0, "rival": "Alianza Lima", "res": "1-1", "lvl": 2.14},
                    {"date": "25-12-11", "val": 3.43, "rival": "Cusco", "res": "1-0", "lvl": 0.87},
                    {"date": "26-03-07", "val": 4.6, "rival": "Alianza Atlético", "res": "3-1", "lvl": 1.23},
                ],
            },
        ],

        "away_constants": [
            {
                "name": "k general", "value": 0, "techo": 14.12, "pctTecho": 0,
                "burstZone": False, "burstMin": 5.04, "burstMedian": 7.22, "ml": "decr",
                "inertia": "↔ LATERAL", "accel": "+5.43",
                "totalBursts": 9, "burstFreqMedian": 7, "sinceLastBurst": 3,
                "burstAmplitude": {"baja": 4, "media": 4, "alta": 1, "extrema": 0},
                "sequoia": 1, "seqHist": "máx 3",
                "peaks": {"pos": [{"val": 14.12, "date": "2025-11-23", "rival": "Puerto Cabello", "res": "1-0"}], "neg": [], "zero": []},
                "ecg": [
                    {"date": "25-11-23", "val": 14.12, "rival": "Puerto Cabello", "res": "1-0", "lvl": 0.65},
                    {"date": "25-11-30", "val": 0, "rival": "UCV", "res": "1-1", "lvl": 1.05},
                    {"date": "26-02-13", "val": 1.88, "rival": "Trujillanos FC", "res": "2-0", "lvl": 0.58},
                    {"date": "26-02-24", "val": 8.24, "rival": "Huachipato", "res": "2-1", "lvl": 1.42},
                    {"date": "26-02-28", "val": 0, "rival": "Zamora FC", "res": "0-1", "lvl": 1.88},
                    {"date": "26-03-07", "val": 0, "rival": "Zamora FC", "res": "0-0", "lvl": 1.88},
                ],
            },
        ],

        "home_goals": {
            "matches": [
                {"date": "25-09-17", "rival": "Alianza Atlético", "res": "0-0", "gf": 0, "gc": 0, "is_home": True},
                {"date": "25-09-29", "rival": "Ayacucho FC", "res": "3-0", "gf": 3, "gc": 0, "is_home": True},
                {"date": "25-10-24", "rival": "Universitario", "res": "0-1", "gf": 0, "gc": 1, "is_home": True},
                {"date": "26-01-25", "rival": "U. Católica", "res": "3-1", "gf": 3, "gc": 1, "is_home": True},
                {"date": "26-02-08", "rival": "FBC Melgar", "res": "1-2", "gf": 1, "gc": 2, "is_home": True},
                {"date": "26-02-25", "rival": "2 de Mayo", "res": "0-0", "gf": 0, "gc": 0, "is_home": True},
                {"date": "26-03-07", "rival": "Alianza Atlético", "res": "3-1", "gf": 3, "gc": 1, "is_home": True},
            ],
            "gfDist": [{"g":0,"n":2,"pct":29},{"g":1,"n":1,"pct":14},{"g":3,"n":4,"pct":57}],
            "gcDist": [{"g":0,"n":3,"pct":43},{"g":1,"n":3,"pct":43},{"g":2,"n":1,"pct":14}],
            "gfMean": 1.43, "gfMedian": 1.0, "gcMean": 0.71, "gcMedian": 1.0, "diffMean": 0.71, "ciclo": "PRODUCTIVO",
        },

        "away_goals": {
            "matches": [
                {"date": "25-09-20", "rival": "Acad. Anzoátegui", "res": "0-0", "gf": 0, "gc": 0, "is_home": False},
                {"date": "25-11-05", "rival": "Metropolitanos", "res": "4-0", "gf": 4, "gc": 0, "is_home": False},
                {"date": "26-02-08", "rival": "Trujillanos FC", "res": "1-1", "gf": 1, "gc": 1, "is_home": True},
                {"date": "26-02-24", "rival": "Huachipato", "res": "2-1", "gf": 2, "gc": 1, "is_home": True},
                {"date": "26-03-07", "rival": "Zamora FC", "res": "0-0", "gf": 0, "gc": 0, "is_home": False},
            ],
            "gfDist": [{"g":0,"n":2,"pct":40},{"g":1,"n":1,"pct":20},{"g":2,"n":1,"pct":20},{"g":4,"n":1,"pct":20}],
            "gcDist": [{"g":0,"n":3,"pct":60},{"g":1,"n":2,"pct":40}],
            "gfMean": 1.4, "gfMedian": 1.0, "gcMean": 0.4, "gcMedian": 0.0, "diffMean": 1.0, "ciclo": "IMPRODUCTIVO",
        },

        "context_bar": [
            {"label": "Regresión", "val": "SC 88% vs CB 4%", "sub": "Conf. ALTA", "color": "#22c55e"},
            {"label": "Fe Perdida", "val": "NONE", "sub": "Sin señal", "color": "#64748b"},
            {"label": "Anticulebra", "val": "Score 0.24", "sub": "Tipo: empate", "color": "#eab308"},
            {"label": "DC Trampa", "val": "1X = 1.10", "sub": "> 1.05 ⚠️", "color": "#f97316"},
        ],

        "decisions": [
            {"id": 1, "title": "k_general SC en zona burst baja", "detail": "Percentil 6% + accel (+1.99) + DC trampa 1.10", "question": "¿Activar como convergencia de riesgo?", "severity": "high"},
            {"id": 2, "title": "kga Carabobo: rebote vs contexto", "detail": "kga 3 en 0 + ML INCR DIVERGE con kgva post-burst (0/5 no anotó)", "question": "¿Carabobo puede anotar hoy?", "severity": "high"},
        ],
    }


if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    demo_data = _build_demo_data()
    window = SADDashboardWindow(demo_data)
    window.show()
    sys.exit(app.exec())