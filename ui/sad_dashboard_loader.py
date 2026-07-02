#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sad_dashboard_loader.py

Carga datos de sad.db y constants.db para alimentar el SADDashboardWindow.
Usa sqlite3 directo (sin ORM) para ser independiente del import chain de src/.

Autor: Gerson (desarrollado con Claude)
Fecha: Marzo 2026
"""

import os
import sqlite3
import logging
import numpy as np
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def find_project_root() -> str:
    this_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    current = this_dir
    for _ in range(6):
        candidates.append(current)
        parent = os.path.dirname(current)
        if parent == current: break
        current = parent
    candidates.reverse()
    for path in candidates:
        sad_path = os.path.join(path, 'sad.db')
        const_path = os.path.join(path, 'constants.db')
        if not (os.path.exists(sad_path) and os.path.exists(const_path)): continue
        try:
            conn = sqlite3.connect(const_path)
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='constants'").fetchone()
            conn.close()
            if row:
                print(f"  [root encontrado] {path}")
                return path
        except: pass
    fallback = os.path.dirname(this_dir)
    print(f"  [FALLBACK] usando {fallback}")
    return fallback


def _get_db_paths() -> Tuple[str, str, str]:
    root = find_project_root()
    return os.path.join(root, 'sad.db'), os.path.join(root, 'constants.db'), os.path.join(root, 'levels.db')


def _connect(db_path):
    if not os.path.exists(db_path): raise FileNotFoundError(f"DB no encontrada: {db_path}")
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row; return conn


def _connect_optional(db_path):
    if not os.path.exists(db_path): return None
    try:
        conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row; return conn
    except: return None


def _get_team_name(conn_sad, team_id):
    row = conn_sad.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    return row['name'] if row else f"Team {team_id}"


def _get_fused_constants(conn_const, conn_sad, team_id):
    rows = conn_const.execute("""
        SELECT date, fixture_id, k_positivo, k_negativo, k_positivo_local, k_negativo_local,
               k_positivo_visita, k_negativo_visita, k_goles_anotado, k_goles_recibido,
               k_goles_local_anotado, k_goles_local_recibido, k_goles_visita_anotado, k_goles_visita_recibido
        FROM constants WHERE team_id = ? ORDER BY date
    """, (team_id,)).fetchall()
    fixture_ids = list(set(r['fixture_id'] for r in rows))
    is_home_map = {}
    for i in range(0, len(fixture_ids), 500):
        batch = fixture_ids[i:i+500]
        ph = ','.join('?' * len(batch))
        for fr in conn_sad.execute(f"SELECT id, home_team_id FROM fixtures WHERE id IN ({ph})", batch).fetchall():
            is_home_map[fr['id']] = (fr['home_team_id'] == team_id)
    results = []
    for r in rows:
        def v(col):
            val = r[col]; return val if val is not None else 0.0
        kp, kn = v('k_positivo'), v('k_negativo')
        kpl, knl = v('k_positivo_local'), v('k_negativo_local')
        kpv, knv = v('k_positivo_visita'), v('k_negativo_visita')
        results.append({
            'date': r['date'], 'fixture_id': r['fixture_id'],
            'is_home': is_home_map.get(r['fixture_id'], True),
            'k': kp+kn, 'k_local': kpl+knl, 'k_visita': kpv+knv,
            'k_goles_anotado': v('k_goles_anotado'), 'k_goles_recibido': v('k_goles_recibido'),
            'k_goles_local_anotado': v('k_goles_local_anotado'), 'k_goles_local_recibido': v('k_goles_local_recibido'),
            'k_goles_visita_anotado': v('k_goles_visita_anotado'), 'k_goles_visita_recibido': v('k_goles_visita_recibido'),
        })
    return results


def _get_fixtures_for_team(conn_sad, team_id, condition=None, limit=30):
    if condition == 'home': where = "f.home_team_id = ? AND f.status_long = 'Match Finished'"
    elif condition == 'away': where = "f.away_team_id = ? AND f.status_long = 'Match Finished'"
    else: where = "(f.home_team_id = ? OR f.away_team_id = ?) AND f.status_long = 'Match Finished'"
    params = [team_id]
    if condition is None: params.append(team_id)
    sql = f"""SELECT f.id, f.date, f.goals_home, f.goals_away, f.home_team_id, f.away_team_id,
               th.name as home_name, ta.name as away_name
        FROM fixtures f LEFT JOIN teams th ON f.home_team_id = th.id
        LEFT JOIN teams ta ON f.away_team_id = ta.id WHERE {where} ORDER BY f.date DESC LIMIT ?"""
    params.append(limit)
    results = []
    for r in conn_sad.execute(sql, params).fetchall():
        is_home = r['home_team_id'] == team_id
        gf = r['goals_home'] if is_home else r['goals_away']
        gc = r['goals_away'] if is_home else r['goals_home']
        rival = r['away_name'] if is_home else r['home_name']
        if gf is None or gc is None: continue
        dt = r['date']
        if isinstance(dt, str):
            try: dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except:
                try: dt = datetime.strptime(dt[:10], '%Y-%m-%d')
                except: dt = None
        results.append({'fixture_id': r['id'], 'date': dt.strftime('%y-%m-%d') if dt else '??-??-??',
                        'rival': rival or '?', 'res': f"{gf}-{gc}", 'gf': gf, 'gc': gc, 'is_home': is_home})
    results.reverse()
    return results


_BURST_THRESHOLD_FLOOR = 3.0

def _calc_burst_threshold(values):
    positives = [v for v in values if v > 0]
    if len(positives) < 3: return _BURST_THRESHOLD_FLOOR
    return max(float(np.percentile(positives, 75)), _BURST_THRESHOLD_FLOOR)


def _analyze_k_series(all_constants, k_field, name, condition_filter=None):
    if condition_filter == 'home': filtered = [c for c in all_constants if c.get('is_home', True)]
    elif condition_filter == 'away': filtered = [c for c in all_constants if not c.get('is_home', True)]
    else: filtered = all_constants
    if not filtered: return _empty_constant(name)

    values = [c[k_field] for c in filtered]
    dates = [c['date'] for c in filtered]
    current_val = values[-1] if values else 0
    abs_values = [abs(v) for v in values]
    techo = max(abs_values) if abs_values else 0
    pct_techo = round((abs(current_val) / techo * 100) if techo > 0 else 0)

    burst_min = _calc_burst_threshold(values)
    burst_vals = [v for v in values if v >= burst_min]
    total_bursts = len(burst_vals)
    burst_median = float(np.median(burst_vals)) if burst_vals else 0
    band2, band3, band4 = burst_min * 1.5, burst_min * 3.0, burst_min * 5.0
    baja = len([v for v in burst_vals if v < band2])
    media = len([v for v in burst_vals if band2 <= v < band3])
    alta = len([v for v in burst_vals if band3 <= v < band4])
    extrema = len([v for v in burst_vals if v >= band4])
    burst_indices = [i for i, v in enumerate(values) if v >= burst_min]
    burst_gaps = [burst_indices[i]-burst_indices[i-1] for i in range(1, len(burst_indices))]
    burst_freq_median = int(np.median(burst_gaps)) if burst_gaps else 0
    since_last_burst = (len(values)-1-burst_indices[-1]) if burst_indices else len(values)
    in_burst_zone = current_val >= burst_min

    def _find_bubbles(vals):
        bubbles = []; in_b = False; bx = bm = 0; bxi = bmi = 0
        for i, v in enumerate(vals):
            if v != 0:
                if not in_b: in_b = True; bx = v; bxi = i; bm = v; bmi = i
                else:
                    if v > bx: bx = v; bxi = i
                    if v < bm: bm = v; bmi = i
            else:
                if in_b: bubbles.append((bx, bxi, bm, bmi)); in_b = False
        if in_b: bubbles.append((bx, bxi, bm, bmi))
        return bubbles

    all_bubbles = _find_bubbles(values)
    def _mp(val, idx): return {'val': round(val, 2), 'date': _format_date(dates[idx]), 'rival': '', 'res': ''}
    pp = sorted([(b[0], b[1]) for b in all_bubbles if b[0] > 0], key=lambda x: -x[0])
    top3_pos = [_mp(v, i) for v, i in pp[:3]]
    np_ = sorted([(b[2], b[3]) for b in all_bubbles if b[2] < 0], key=lambda x: x[0])
    top3_neg = [_mp(v, i) for v, i in np_[:3]]
    zi = [i for i, v in enumerate(values) if v == 0]
    top3_zero = [_mp(0.0, i) for i in zi[-3:]]

    ecg = [{'date': _format_date_short(d), 'val': round(v, 2), 'fid': filtered[i]['fixture_id']}
           for i, (v, d) in enumerate(zip(values, dates))]

    recent = values[-5:] if len(values) >= 5 else values
    if len(recent) >= 2:
        deltas = [recent[i]-recent[i-1] for i in range(1, len(recent))]
        avg_d = np.mean(deltas)
        inertia = "↗ SUBIENDO" if avg_d > 1 else "↘ BAJANDO" if avg_d < -1 else "↔ LATERAL"
        accel_str = f"{avg_d:+.2f}"
    else: inertia = "↔ LATERAL"; accel_str = "+0.00"

    sequoia = 0
    for v in reversed(values):
        if v == 0: sequoia += 1
        else: break

    if len(values) >= 3:
        l3 = values[-3:]
        ml = "INCR" if l3[-1]>l3[-2]>l3[-3] else "decr" if l3[-1]<l3[-2]<l3[-3] else "flat"
    else: ml = "flat"

    result = {
        'name': name, 'value': round(current_val, 2), 'techo': round(techo, 2),
        'pctTecho': pct_techo, 'burstZone': in_burst_zone,
        'burstMin': round(burst_min, 2), 'burstMedian': round(burst_median, 2),
        'inertia': inertia, 'accel': accel_str,
        'totalBursts': total_bursts, 'burstFreqMedian': burst_freq_median, 'sinceLastBurst': since_last_burst,
        'burstAmplitude': {'baja': baja, 'media': media, 'alta': alta, 'extrema': extrema},
        'burstBands': [{'label': f'{burst_min:.0f}-{band2:.0f}', 'key': 'baja'},
                       {'label': f'{band2:.0f}-{band3:.0f}', 'key': 'media'},
                       {'label': f'{band3:.0f}-{band4:.0f}', 'key': 'alta'},
                       {'label': f'{band4:.0f}+', 'key': 'extrema'}],
        'ml': ml, 'peaks': {'pos': top3_pos, 'neg': top3_neg, 'zero': top3_zero}, 'ecg': ecg,
    }
    if sequoia > 0:
        seqs = _find_all_droughts(values)
        result['sequoia'] = sequoia
        result['seqHist'] = f"máx {max(seqs)}" if seqs else "—"
    return result


def _find_all_droughts(values):
    droughts = []; c = 0
    for v in values:
        if v == 0: c += 1
        else:
            if c > 0: droughts.append(c)
            c = 0
    if c > 0: droughts.append(c)
    return droughts

def _empty_constant(name):
    return {'name': name, 'value': 0, 'techo': 0, 'pctTecho': 0, 'burstZone': False,
            'burstMin': 5.0, 'burstMedian': 0, 'inertia': '—', 'accel': '+0.00',
            'totalBursts': 0, 'burstFreqMedian': 0, 'sinceLastBurst': 0,
            'burstAmplitude': {'baja': 0, 'media': 0, 'alta': 0, 'extrema': 0},
            'ml': 'flat', 'peaks': {'pos': [], 'neg': [], 'zero': []}, 'ecg': []}

def _format_date(dt_raw):
    if isinstance(dt_raw, str): return dt_raw[:10]
    if isinstance(dt_raw, datetime): return dt_raw.strftime('%Y-%m-%d')
    return str(dt_raw)[:10]

def _format_date_short(dt_raw):
    if isinstance(dt_raw, str):
        d = dt_raw[:10]; return d[2:] if len(d) >= 10 and d[:2] == '20' else d
    if isinstance(dt_raw, datetime): return dt_raw.strftime('%y-%m-%d')
    return str(dt_raw)[:8]


def _build_goals_data(matches):
    if not matches:
        return {'matches': [], 'gfDist': [], 'gcDist': [], 'diffDist': [],
                'gfMean': 0, 'gfMedian': 0, 'gcMean': 0, 'gcMedian': 0, 'diffMean': 0, 'ciclo': '—'}
    gf_list = [m['gf'] for m in matches]; gc_list = [m['gc'] for m in matches]
    diff_list = [m['gf']-m['gc'] for m in matches]
    def dist(vals, key='g'):
        from collections import Counter
        c = Counter(vals); total = len(vals)
        return [{key: g, 'n': n, 'pct': round(n/total*100) if total else 0} for g, n in sorted(c.items())]
    last5 = gf_list[-5:] if len(gf_list) >= 5 else gf_list
    return {'matches': matches, 'gfDist': dist(gf_list, 'g'), 'gcDist': dist(gc_list, 'g'),
            'diffDist': dist(diff_list, 'd'),
            'gfMean': round(np.mean(gf_list), 2), 'gfMedian': round(float(np.median(gf_list)), 1),
            'gcMean': round(np.mean(gc_list), 2), 'gcMedian': round(float(np.median(gc_list)), 1),
            'diffMean': round(np.mean(diff_list), 2),
            'ciclo': "PRODUCTIVO" if np.mean(last5) >= 1.0 else "IMPRODUCTIVO"}


def _enrich_peaks_with_fixtures(k_field, analyzed, all_constants, conn_sad, team_id, condition_filter=None):
    peaks = analyzed.get('peaks', {})
    if not peaks: return
    if condition_filter == 'home': filtered = [c for c in all_constants if c.get('is_home', True)]
    elif condition_filter == 'away': filtered = [c for c in all_constants if not c.get('is_home', True)]
    else: filtered = all_constants
    values = [c[k_field] for c in filtered]; dates_raw = [c['date'] for c in filtered]
    def _fetch(fid):
        row = conn_sad.execute("""SELECT f.goals_home, f.goals_away, th.name as home_name, ta.name as away_name, f.home_team_id
            FROM fixtures f LEFT JOIN teams th ON f.home_team_id = th.id LEFT JOIN teams ta ON f.away_team_id = ta.id WHERE f.id = ?""", (fid,)).fetchone()
        if row:
            ih = row['home_team_id'] == team_id
            return (row['away_name'] if ih else row['home_name']) or '?', \
                   f"{row['goals_home'] if ih else row['goals_away']}-{row['goals_away'] if ih else row['goals_home']}" if row['goals_home'] is not None else '?-?'
        return '?', '?-?'
    for cat in ['pos', 'neg', 'zero']:
        for entry in peaks.get(cat, []):
            for idx in range(len(values)):
                if _format_date(dates_raw[idx]) == entry['date'] and round(values[idx], 2) == entry['val']:
                    entry['rival'], entry['res'] = _fetch(filtered[idx]['fixture_id']); break


def _enrich_ecg_data(constants_list, conn_sad, conn_levels, team_id):
    """Enriquece ECG con rival, resultado y nivel del rival. Modifica in-place."""
    all_fids = set()
    for c in constants_list:
        for pt in c.get('ecg', []):
            if pt.get('fid'): all_fids.add(pt['fid'])
    if not all_fids: return

    fixture_info = {}
    fid_list = list(all_fids)
    for i in range(0, len(fid_list), 500):
        batch = fid_list[i:i+500]; ph = ','.join('?' * len(batch))
        for r in conn_sad.execute(f"""SELECT f.id, f.home_team_id, f.away_team_id, f.goals_home, f.goals_away,
               th.name as home_name, ta.name as away_name FROM fixtures f
               LEFT JOIN teams th ON f.home_team_id = th.id LEFT JOIN teams ta ON f.away_team_id = ta.id
               WHERE f.id IN ({ph})""", batch).fetchall():
            ih = r['home_team_id'] == team_id
            fixture_info[r['id']] = {
                'rival': (r['away_name'] if ih else r['home_name']) or '?',
                'res': f"{r['goals_home'] if ih else r['goals_away']}-{r['goals_away'] if ih else r['goals_home']}"
                       if r['goals_home'] is not None else '?-?',
                'rival_id': r['away_team_id'] if ih else r['home_team_id'],
            }

    rival_levels = {}
    if conn_levels:
        for i in range(0, len(fid_list), 500):
            batch = fid_list[i:i+500]; ph = ','.join('?' * len(batch))
            try:
                for r in conn_levels.execute(f"SELECT team_id, fixture_id, level FROM team_levels WHERE fixture_id IN ({ph})", batch).fetchall():
                    rival_levels[(r['team_id'], r['fixture_id'])] = round(r['level'], 2)
            except: pass

    for c in constants_list:
        for pt in c.get('ecg', []):
            fid = pt.get('fid')
            if fid and fid in fixture_info:
                info = fixture_info[fid]
                pt['rival'] = info['rival']; pt['res'] = info['res']
                pt['lvl'] = rival_levels.get((info['rival_id'], fid))
            if 'fid' in pt: del pt['fid']


def calculate_k_summary(team_predictions, rival_predictions):
    """Resumen K: promedia K_local y K_visita invertida → P(local/empate/visita) + P(goles)."""
    team_kl = team_predictions.get('k_local', {}); rival_kv = rival_predictions.get('k_visita', {})
    if team_kl and rival_kv:
        pL = (team_kl.get('incremento', 0) + rival_kv.get('decremento', 0)) / 2
        pE = (team_kl.get('reset', 0) + rival_kv.get('reset', 0)) / 2
        pV = (team_kl.get('decremento', 0) + rival_kv.get('incremento', 0)) / 2
    elif team_kl: pL, pE, pV = team_kl.get('incremento', 33.3), team_kl.get('reset', 33.3), team_kl.get('decremento', 33.4)
    elif rival_kv: pL, pE, pV = rival_kv.get('decremento', 33.3), rival_kv.get('reset', 33.3), rival_kv.get('incremento', 33.4)
    else: pL = pE = pV = 33.3
    t = pL + pE + pV
    if t > 0: pL, pE, pV = pL/t*100, pE/t*100, pV/t*100
    incr = []
    for k in ['k_goles_local_anotado', 'k_goles_local_recibido']:
        p = team_predictions.get(k, {})
        if p and 'incremento' in p: incr.append(p['incremento'])
    for k in ['k_goles_visita_anotado', 'k_goles_visita_recibido']:
        p = rival_predictions.get(k, {})
        if p and 'incremento' in p: incr.append(p['incremento'])
    pG = sum(incr)/len(incr) if incr else 50.0
    return {'p_local': round(pL,1), 'p_empate': round(pE,1), 'p_visita': round(pV,1),
            'p_hay_goles': round(pG,1), 'p_se_corta': round(100-pG,1)}


def build_dashboard_data(home_team_id, away_team_id, match_info='',
                         phase='SAD · Fase 1 · Extracción sin veredicto',
                         context_bar=None, decisions=None, n_fixtures=30,
                         k_summary=None,
                         team_predictions=None, rival_predictions=None):
    """
    Construye el dict completo para SADDashboardWindow.
    
    Si se pasan team_predictions y rival_predictions (de ConstantsWorker),
    calcula k_summary automáticamente.
    """
    # Auto-calcular k_summary si tenemos predicciones
    if not k_summary and team_predictions and rival_predictions:
        k_summary = calculate_k_summary(team_predictions, rival_predictions)
    
    sad_path, const_path, levels_path = _get_db_paths()
    logger.info(f"Cargando datos: Home={home_team_id}, Away={away_team_id}")
    conn_sad = _connect(sad_path); conn_const = _connect(const_path)
    conn_levels = _connect_optional(levels_path)
    try:
        home_name = _get_team_name(conn_sad, home_team_id)
        away_name = _get_team_name(conn_sad, away_team_id)
        home_all_k = _get_fused_constants(conn_const, conn_sad, home_team_id)
        away_all_k = _get_fused_constants(conn_const, conn_sad, away_team_id)
        hkf = [('k','k general',None),('k_local','k local','home'),('k_goles_anotado','kg anotado',None),
               ('k_goles_recibido','kg recibido',None),('k_goles_local_anotado','kg local anotado','home'),
               ('k_goles_local_recibido','kg local recibido','home')]
        akf = [('k','k general',None),('k_visita','k visita','away'),('k_goles_anotado','kg anotado',None),
               ('k_goles_recibido','kg recibido',None),('k_goles_visita_anotado','kg visita anotado','away'),
               ('k_goles_visita_recibido','kg visita recibido','away')]
        home_constants = []
        for field, name, cond in hkf:
            a = _analyze_k_series(home_all_k, field, name, condition_filter=cond)
            _enrich_peaks_with_fixtures(field, a, home_all_k, conn_sad, home_team_id, cond)
            home_constants.append(a)
        away_constants = []
        for field, name, cond in akf:
            a = _analyze_k_series(away_all_k, field, name, condition_filter=cond)
            _enrich_peaks_with_fixtures(field, a, away_all_k, conn_sad, away_team_id, cond)
            away_constants.append(a)
        _enrich_ecg_data(home_constants, conn_sad, conn_levels, home_team_id)
        _enrich_ecg_data(away_constants, conn_sad, conn_levels, away_team_id)
        home_goals = _build_goals_data(_get_fixtures_for_team(conn_sad, home_team_id, limit=n_fixtures))
        away_goals = _build_goals_data(_get_fixtures_for_team(conn_sad, away_team_id, limit=n_fixtures))
        data = {'home_team': home_name, 'away_team': away_name, 'match_info': match_info, 'phase': phase,
                'home_constants': home_constants, 'away_constants': away_constants,
                'home_goals': home_goals, 'away_goals': away_goals,
                'context_bar': context_bar or [], 'decisions': decisions or []}
        if k_summary: data['k_summary'] = k_summary
        logger.info(f"Dashboard OK: {home_name} ({len(home_all_k)} K) vs {away_name} ({len(away_all_k)} K)")
        return data
    finally:
        conn_sad.close(); conn_const.close()
        if conn_levels: conn_levels.close()


if __name__ == '__main__':
    import json, sys
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    hid, aid = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) >= 3 else (2283, 18255)
    try:
        data = build_dashboard_data(hid, aid, match_info="Test CLI")
        print(f"\n✅ {data['home_team']} vs {data['away_team']}")
        for c in data['home_constants']:
            s = c['ecg'][-1] if c['ecg'] else {}
            print(f"  [H] {c['name']}: val={c['value']} | ecg[-1]: {s}")
        with open('dashboard_debug.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print("📄 → dashboard_debug.json")
    except Exception as e:
        print(f"❌ {e}"); import traceback; traceback.print_exc()