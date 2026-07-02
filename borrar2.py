"""
diagnostico_icf_v2.py
=====================
Diagnostica por qué Everton (local) tiene ICF=3.76 y Bournemouth (visita) ICF=9.28

EJECUTAR DESDE: d:\VSCode Ejercicios 02\src\
"""
import sqlite3
import os
import math
import pickle
from pathlib import Path

# ============================================================
# IDs confirmados
# ============================================================
EVERTON_ID = 45
BOURNEMOUTH_ID = 35
LEAGUE_ID = 39  # Premier League

# ============================================================
# DB paths - FUERA de src
# ============================================================
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent  # d:\VSCode Ejercicios 02\

SAD_DB = str(PROJECT_ROOT / 'sad.db')
CONST_DB = str(PROJECT_ROOT / 'constants.db')
LEVELS_DB = str(PROJECT_ROOT / 'levels.db')
MODEL_PATH = str(PROJECT_ROOT / 'anticulebra_model.pkl')

print("=" * 70)
print("DIAGNÓSTICO ICF: Everton (L) vs Bournemouth (V)")
print("=" * 70)
print(f"\n📁 Bases de datos:")
print(f"   sad.db:       {SAD_DB} {'✅' if os.path.exists(SAD_DB) else '❌'}")
print(f"   constants.db: {CONST_DB} {'✅' if os.path.exists(CONST_DB) else '❌'}")
print(f"   levels.db:    {LEVELS_DB} {'✅' if os.path.exists(LEVELS_DB) else '❌'}")
print(f"   model.pkl:    {MODEL_PATH} {'✅' if os.path.exists(MODEL_PATH) else '❌'}")

# ============================================================
# 1. CONSTANTES DE RACHA
# ============================================================
print(f"\n{'─' * 70}")
print("1. CONSTANTES DE RACHA (constants.db)")
print(f"{'─' * 70}")

conn_const = sqlite3.connect(CONST_DB)

for team_name, team_id, is_home in [("Everton", EVERTON_ID, True), ("Bournemouth", BOURNEMOUTH_ID, False)]:
    row = conn_const.execute("""
        SELECT date,
               k_positivo_local, k_positivo_visita,
               k_negativo_local, k_negativo_visita,
               k_goles_local_anotado, k_goles_local_recibido,
               k_goles_visita_anotado, k_goles_visita_recibido
        FROM constants
        WHERE team_id = ?
        ORDER BY date DESC
        LIMIT 1
    """, (team_id,)).fetchone()
    
    role = "LOCAL" if is_home else "VISITA"
    if row:
        print(f"\n   {'🏠' if is_home else '✈️'}  {team_name} (ID={team_id}) como {role}")
        print(f"      Última actualización: {row[0]}")
        print(f"      ─── Constantes LOCAL ───")
        print(f"      k_positivo_local:       {row[1]}")
        print(f"      k_negativo_local:       {row[3]}")
        print(f"      k_goles_local_anotado:  {row[5]}")
        print(f"      k_goles_local_recibido: {row[6]}")
        print(f"      ─── Constantes VISITA ───")
        print(f"      k_positivo_visita:      {row[2]}")
        print(f"      k_negativo_visita:      {row[4]}")
        print(f"      k_goles_visita_anotado: {row[7]}")
        print(f"      k_goles_visita_recibido:{row[8]}")
        
        # Guardar para cálculo posterior
        if is_home:
            k_base_eve = row[1] or 1.0
            k_neg_eve = row[3] or 0.5
            k_ga_eve = row[5] or 1.0
            k_gr_eve = row[6] or 1.0
        else:
            k_base_bou = row[2] or 1.0
            k_neg_bou = row[4] or 0.5
            k_ga_bou = row[7] or 1.0
            k_gr_bou = row[8] or 1.0
    else:
        print(f"\n   ⚠️  {team_name} (ID={team_id}) — SIN CONSTANTES")

conn_const.close()

# ============================================================
# 2. NIVELES
# ============================================================
print(f"\n{'─' * 70}")
print("2. NIVELES (levels.db)")
print(f"{'─' * 70}")

nivel_eve = 1.0
nivel_bou = 1.0

if os.path.exists(LEVELS_DB):
    conn_lv = sqlite3.connect(LEVELS_DB)
    for team_name, team_id in [("Everton", EVERTON_ID), ("Bournemouth", BOURNEMOUTH_ID)]:
        rows = conn_lv.execute("""
            SELECT date, level FROM team_levels
            WHERE team_id = ? ORDER BY date DESC LIMIT 5
        """, (team_id,)).fetchall()
        
        if rows:
            print(f"\n   📊 {team_name}:")
            for r in rows:
                print(f"      {r[0][:16]}  nivel = {r[1]:.3f}")
            if team_id == EVERTON_ID:
                nivel_eve = rows[0][1]
            else:
                nivel_bou = rows[0][1]
        else:
            print(f"\n   ⚠️  {team_name}: SIN NIVELES")
    conn_lv.close()

# ============================================================
# 3. PESOS CALIBRADOS
# ============================================================
print(f"\n{'─' * 70}")
print("3. PESOS DEL MODELO")
print(f"{'─' * 70}")

DEFAULT_W = {
    'k_local': 1.0, 'k_visita': 1.0,
    'k_goles_anotado': 0.8, 'k_goles_recibido': 0.6,
    'k_negativo': 0.3, 'nivel': 1.2,
}

w = DEFAULT_W.copy()
scale_k = 0.15

if os.path.exists(MODEL_PATH):
    try:
        with open(MODEL_PATH, 'rb') as f:
            data = pickle.load(f)
            w = data.get('weights', DEFAULT_W)
            scale_k = data.get('scale_k', 0.15)
        print(f"   ✅ Modelo calibrado cargado")
    except Exception as e:
        print(f"   ❌ Error: {e}")
else:
    print(f"   ⚠️  Sin modelo calibrado, usando defaults")

print(f"\n   Pesos:")
for k, v in sorted(w.items()):
    bug = " ← 🐛 NUNCA SE USA en calculate_icf!" if k == 'k_visita' else ""
    print(f"      {k:<20} = {v:.4f}{bug}")
print(f"   scale_k = {scale_k}")

# ============================================================
# 4. CÁLCULO ICF PASO A PASO
# ============================================================
print(f"\n{'─' * 70}")
print("4. CÁLCULO ICF DETALLADO")
print(f"{'─' * 70}")

# --- EVERTON (LOCAL) ---
print(f"\n   🏠 EVERTON (LOCAL)  nivel={nivel_eve:.3f}")
comp1 = w.get('k_local', 1.0) * k_base_eve
comp2 = w.get('k_goles_anotado', 0.8) * k_ga_eve
comp3 = w.get('k_goles_recibido', 0.6) * k_gr_eve
comp4 = w.get('k_negativo', 0.3) * k_neg_eve
comp5 = w.get('nivel', 1.2) * nivel_eve

print(f"      + k_local({w.get('k_local',1):.4f}) × k_positivo_local({k_base_eve:.3f})     = {comp1:+.4f}")
print(f"      + k_goles_a({w.get('k_goles_anotado',0.8):.4f}) × k_goles_L_anot({k_ga_eve:.3f})  = {comp2:+.4f}")
print(f"      - k_goles_r({w.get('k_goles_recibido',0.6):.4f}) × k_goles_L_rec({k_gr_eve:.3f})   = {-comp3:+.4f}")
print(f"      - k_negativo({w.get('k_negativo',0.3):.4f}) × k_negativo_local({k_neg_eve:.3f})  = {-comp4:+.4f}")
print(f"      + nivel({w.get('nivel',1.2):.4f}) × nivel({nivel_eve:.3f})              = {comp5:+.4f}")
icf_eve = comp1 + comp2 - comp3 - comp4 + comp5
print(f"      ────────────────────────────────────────────")
print(f"      ICF EVERTON = {icf_eve:.4f}")

# --- BOURNEMOUTH (VISITA) ---
print(f"\n   ✈️  BOURNEMOUTH (VISITA)  nivel={nivel_bou:.3f}")
# BUG: usa k_local en vez de k_visita
comp1_bug = w.get('k_local', 1.0) * k_base_bou
comp1_fix = w.get('k_visita', 1.0) * k_base_bou
comp2 = w.get('k_goles_anotado', 0.8) * k_ga_bou
comp3 = w.get('k_goles_recibido', 0.6) * k_gr_bou
comp4 = w.get('k_negativo', 0.3) * k_neg_bou
comp5 = w.get('nivel', 1.2) * nivel_bou

print(f"      + k_local({w.get('k_local',1):.4f}) × k_positivo_visita({k_base_bou:.3f})   = {comp1_bug:+.4f}  ← 🐛 usa k_local!")
print(f"        k_visita({w.get('k_visita',1):.4f}) × k_positivo_visita({k_base_bou:.3f})  = {comp1_fix:+.4f}  ← debería ser esto")
print(f"      + k_goles_a({w.get('k_goles_anotado',0.8):.4f}) × k_goles_V_anot({k_ga_bou:.3f})  = {comp2:+.4f}")
print(f"      - k_goles_r({w.get('k_goles_recibido',0.6):.4f}) × k_goles_V_rec({k_gr_bou:.3f})   = {-comp3:+.4f}")
print(f"      - k_negativo({w.get('k_negativo',0.3):.4f}) × k_negativo_visita({k_neg_bou:.3f}) = {-comp4:+.4f}")
print(f"      + nivel({w.get('nivel',1.2):.4f}) × nivel({nivel_bou:.3f})              = {comp5:+.4f}")

icf_bou_bug = comp1_bug + comp2 - comp3 - comp4 + comp5
icf_bou_fix = comp1_fix + comp2 - comp3 - comp4 + comp5

print(f"      ────────────────────────────────────────────")
print(f"      ICF BOURNEMOUTH (actual/bug):   {icf_bou_bug:.4f}")
print(f"      ICF BOURNEMOUTH (corregido):    {icf_bou_fix:.4f}")
print(f"      Diferencia por bug:             {icf_bou_bug - icf_bou_fix:+.4f}")

# ============================================================
# 5. PROBABILIDADES RESULTANTES
# ============================================================
print(f"\n{'─' * 70}")
print("5. PROBABILIDADES RESULTANTES")
print(f"{'─' * 70}")

def icf_to_prob(icf_h, icf_a, sk):
    delta = icf_h - icf_a
    home_str = 1 / (1 + math.exp(-sk * delta))
    draw_factor = math.exp(-0.3 * abs(delta))
    prob_draw = min(max(0.26 * (0.5 + draw_factor), 0.15), 0.40)
    remaining = 1 - prob_draw
    prob_h = home_str * remaining
    prob_a = (1 - home_str) * remaining
    total = prob_h + prob_draw + prob_a
    return prob_h/total, prob_draw/total, prob_a/total

ph_bug, pd_bug, pa_bug = icf_to_prob(icf_eve, icf_bou_bug, scale_k)
ph_fix, pd_fix, pa_fix = icf_to_prob(icf_eve, icf_bou_fix, scale_k)

print(f"\n   CON BUG (actual):     delta = {icf_eve - icf_bou_bug:+.3f}")
print(f"      Prob 1 (Everton):    {ph_bug*100:.1f}%")
print(f"      Prob X (Empate):     {pd_bug*100:.1f}%")
print(f"      Prob 2 (Bournemouth):{pa_bug*100:.1f}%")

print(f"\n   CORREGIDO:            delta = {icf_eve - icf_bou_fix:+.3f}")
print(f"      Prob 1 (Everton):    {ph_fix*100:.1f}%")
print(f"      Prob X (Empate):     {pd_fix*100:.1f}%")
print(f"      Prob 2 (Bournemouth):{pa_fix*100:.1f}%")

print(f"\n   CAMBIO:")
print(f"      Everton:     {ph_bug*100:.1f}% → {ph_fix*100:.1f}%  ({(ph_fix-ph_bug)*100:+.1f}%)")
print(f"      Empate:      {pd_bug*100:.1f}% → {pd_fix*100:.1f}%  ({(pd_fix-pd_bug)*100:+.1f}%)")
print(f"      Bournemouth: {pa_bug*100:.1f}% → {pa_fix*100:.1f}%  ({(pa_fix-pa_bug)*100:+.1f}%)")

# ============================================================
# 6. ÚLTIMOS RESULTADOS EN LIGA
# ============================================================
print(f"\n{'─' * 70}")
print("6. ÚLTIMOS RESULTADOS EN PREMIER LEAGUE")
print(f"{'─' * 70}")

conn_sad = sqlite3.connect(SAD_DB)

for team_name, team_id in [("Everton", EVERTON_ID), ("Bournemouth", BOURNEMOUTH_ID)]:
    rows = conn_sad.execute("""
        SELECT f.date,
               CASE WHEN f.home_team_id = ? THEN 'L' ELSE 'V' END,
               CASE WHEN f.home_team_id = ? THEN at.name ELSE ht.name END,
               f.goals_home, f.goals_away,
               CASE 
                   WHEN (f.home_team_id = ? AND f.goals_home > f.goals_away) OR
                        (f.away_team_id = ? AND f.goals_away > f.goals_home) THEN 'W'
                   WHEN f.goals_home = f.goals_away THEN 'D'
                   ELSE 'L'
               END
        FROM fixtures f
        JOIN teams ht ON f.home_team_id = ht.id
        JOIN teams at ON f.away_team_id = at.id
        WHERE (f.home_team_id = ? OR f.away_team_id = ?)
          AND f.league_id = ?
          AND f.status_short = 'FT'
        ORDER BY f.date DESC
        LIMIT 10
    """, (team_id, team_id, team_id, team_id, team_id, team_id, LEAGUE_ID)).fetchall()
    
    if rows:
        wins = sum(1 for r in rows if r[5] == 'W')
        draws = sum(1 for r in rows if r[5] == 'D')
        losses = sum(1 for r in rows if r[5] == 'L')
        pts = wins * 3 + draws
        
        print(f"\n   📋 {team_name} — Últimos {len(rows)} partidos:")
        for r in rows:
            emoji = "✅" if r[5] == 'W' else ("🤝" if r[5] == 'D' else "❌")
            print(f"      {r[0][:10]}  ({r[1]}) vs {r[2]:<20}  {r[3]}-{r[4]}  {emoji}")
        print(f"      → {wins}W {draws}D {losses}L = {pts}pts ({pts/len(rows):.2f} ppg)")

conn_sad.close()

# ============================================================
# 7. DIAGNÓSTICO FINAL
# ============================================================
print(f"\n{'=' * 70}")
print("DIAGNÓSTICO FINAL")
print(f"{'=' * 70}")
print(f"""
   ICF Everton (L):      {icf_eve:.3f}
   ICF Bournemouth (V):  {icf_bou_bug:.3f}  (con bug)  /  {icf_bou_fix:.3f}  (corregido)
   Delta:                {icf_eve - icf_bou_bug:+.3f}  (con bug)  /  {icf_eve - icf_bou_fix:+.3f}  (corregido)
   
   La diferencia de ICF viene de:
   1. Constantes de racha (k_positivo, k_goles, k_negativo)
   2. Nivel del equipo
   3. Bug: peso k_visita no se aplica al visitante
   
   Revisa arriba qué componente contribuye más a la diferencia.
""")