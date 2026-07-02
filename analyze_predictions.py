# -*- coding: utf-8 -*-
"""
analyze_predictions.py
=======================
Analiza los CSVs exportados por historical_predictions_exporter.py
y genera un RESUMEN COMPACTO que puedes pegar en Claude para interpretar.

USO:
    python analyze_predictions.py

    O con rutas especificas:
    python analyze_predictions.py --main predictions_main_latest.csv --constants predictions_constants_latest.csv

SALIDA:
    - Imprime resumen en consola (~200 lineas)
    - Guarda reporte completo en analysis_report.txt
"""

import os
import sys
import argparse
from datetime import datetime

import numpy as np
import pandas as pd


# ============================================================================
# CONFIGURACION
# ============================================================================

def find_csv_files(base_dir=None):
    """Busca los CSVs mas recientes en historical_exports/."""
    if base_dir is None:
        # Buscar en el directorio del script, luego padre, luego historical_exports
        candidates = [
            os.path.join(os.getcwd(), 'historical_exports'),
            os.path.join(os.path.dirname(os.getcwd()), 'historical_exports'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'historical_exports'),
            os.getcwd(),
        ]
        for c in candidates:
            latest = os.path.join(c, 'predictions_main_latest.csv')
            if os.path.exists(latest):
                base_dir = c
                break
    
    if base_dir is None:
        return None, None
    
    main_csv = os.path.join(base_dir, 'predictions_main_latest.csv')
    const_csv = os.path.join(base_dir, 'predictions_constants_latest.csv')
    
    if not os.path.exists(main_csv):
        # Buscar el mas reciente
        files = [f for f in os.listdir(base_dir) if f.startswith('predictions_main_') and f.endswith('.csv')]
        if files:
            files.sort(reverse=True)
            main_csv = os.path.join(base_dir, files[0])
    
    if not os.path.exists(const_csv):
        files = [f for f in os.listdir(base_dir) if f.startswith('predictions_constants_') and f.endswith('.csv')]
        if files:
            files.sort(reverse=True)
            const_csv = os.path.join(base_dir, files[0])
    
    return (
        main_csv if os.path.exists(main_csv) else None,
        const_csv if os.path.exists(const_csv) else None,
    )


# ============================================================================
# FUNCIONES DE ANALISIS
# ============================================================================

def histogram_text(series, bins=10, width=40):
    """Genera un histograma en texto ASCII."""
    counts, edges = np.histogram(series.dropna(), bins=bins)
    max_count = max(counts) if max(counts) > 0 else 1
    lines = []
    for i, count in enumerate(counts):
        bar_len = int(count / max_count * width)
        bar = '#' * bar_len
        lines.append(f"  {edges[i]:6.3f}-{edges[i+1]:6.3f} | {bar:<{width}} | {count:>5} ({count/len(series)*100:5.1f}%)")
    return '\n'.join(lines)


def analyze_culebras(df, lines):
    """Analiza el modelo de Culebras."""
    lines.append("")
    lines.append("=" * 70)
    lines.append("1. LEY DE LAS CULEBRAS")
    lines.append("=" * 70)
    
    # Filtrar filas con datos de culebras
    cul = df[df['cul_ml_break_score'].notna()].copy()
    
    if cul.empty:
        lines.append("  [!] Sin datos de culebras")
        return
    
    lines.append(f"  Partidos con prediccion: {len(cul)} / {len(df)}")
    
    # --- Distribucion ml_break_score ---
    lines.append("")
    lines.append("  --- ml_break_score: Distribucion ---")
    score = cul['cul_ml_break_score']
    lines.append(f"  Min:    {score.min():.4f}")
    lines.append(f"  P10:    {score.quantile(0.10):.4f}")
    lines.append(f"  P25:    {score.quantile(0.25):.4f}")
    lines.append(f"  P50:    {score.quantile(0.50):.4f}")
    lines.append(f"  P75:    {score.quantile(0.75):.4f}")
    lines.append(f"  P90:    {score.quantile(0.90):.4f}")
    lines.append(f"  Max:    {score.max():.4f}")
    lines.append(f"  Media:  {score.mean():.4f}")
    lines.append(f"  Std:    {score.std():.4f}")
    
    lines.append("")
    lines.append("  Histograma ml_break_score:")
    lines.append(histogram_text(score, bins=12))
    
    # Cuantos por debajo de umbrales clave
    lines.append("")
    lines.append("  --- Conteo por umbral ---")
    for threshold in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
        n_below = (score < threshold).sum()
        lines.append(f"  ml_break < {threshold:.2f}: {n_below:>6} ({n_below/len(score)*100:5.1f}%)")
    
    # --- Accuracy del favorito por rango de ml_break_score ---
    lines.append("")
    lines.append("  --- Favorito gana vs ml_break_score ---")
    
    fav = cul[cul['cul_favorite_won'].notna()].copy()
    fav['cul_favorite_won'] = fav['cul_favorite_won'].astype(bool).astype(int)
    
    if not fav.empty:
        lines.append(f"  Total con resultado: {len(fav)}")
        lines.append(f"  Favorito gano global: {fav['cul_favorite_won'].mean():.2%}")
        lines.append("")
        
        # Por rangos
        bins = [0, 0.35, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 1.01]
        labels = ['<0.35', '0.35-0.45', '0.45-0.50', '0.50-0.55', '0.55-0.60',
                  '0.60-0.65', '0.65-0.70', '0.70-0.75', '0.75-0.80', '0.80-0.85', '>0.85']
        
        fav['score_bin'] = pd.cut(fav['cul_ml_break_score'], bins=bins, labels=labels, right=False)
        
        grouped = fav.groupby('score_bin', observed=False).agg(
            n=('cul_favorite_won', 'count'),
            wins=('cul_favorite_won', 'sum'),
        )
        grouped['win_rate'] = grouped['wins'] / grouped['n']
        grouped['loss_rate'] = 1 - grouped['win_rate']
        
        lines.append(f"  {'Rango':<14} {'N':>6} {'Fav Gana':>10} {'Fav Pierde':>11} {'% Gana':>8}")
        lines.append(f"  {'-'*14} {'-'*6} {'-'*10} {'-'*11} {'-'*8}")
        for label, row in grouped.iterrows():
            if row['n'] > 0:
                lines.append(f"  {str(label):<14} {int(row['n']):>6} {int(row['wins']):>10} "
                           f"{int(row['n'] - row['wins']):>11} {row['win_rate']:>7.1%}")
            else:
                lines.append(f"  {str(label):<14} {0:>6} {'---':>10} {'---':>11} {'---':>8}")
    
    # --- Tipo de ruptura ---
    lines.append("")
    lines.append("  --- Tipo de ruptura cuando culebra se rompe ---")
    broke = cul[cul['cul_broke_snake'] == True]
    if not broke.empty:
        bt = broke['cul_break_type'].value_counts()
        for k, v in bt.items():
            lines.append(f"  {k}: {v} ({v/len(broke)*100:.1f}%)")
    
    # --- ICF diff ---
    lines.append("")
    lines.append("  --- ICF diff: Distribucion ---")
    icf = cul['cul_icf_diff']
    lines.append(f"  Min: {icf.min():.4f}  P25: {icf.quantile(0.25):.4f}  "
                f"P50: {icf.quantile(0.50):.4f}  P75: {icf.quantile(0.75):.4f}  "
                f"Max: {icf.max():.4f}")
    
    # --- prob_break_total vs ml_break_score ---
    lines.append("")
    lines.append("  --- prob_break_total vs ml_break_score ---")
    both = cul[cul['cul_prob_break_total'].notna() & cul['cul_ml_break_score'].notna()]
    if len(both) > 10:
        corr = both['cul_prob_break_total'].corr(both['cul_ml_break_score'])
        lines.append(f"  Correlacion: {corr:.4f}")
        lines.append(f"  prob_break_total - Media: {both['cul_prob_break_total'].mean():.4f}, "
                    f"Std: {both['cul_prob_break_total'].std():.4f}")


def analyze_goals(df, lines):
    """Analiza el modelo de Goles."""
    lines.append("")
    lines.append("=" * 70)
    lines.append("2. LEY DEL MARCADOR (GOLES)")
    lines.append("=" * 70)
    
    gol = df[df['gol_lambda_home'].notna()].copy()
    
    if gol.empty:
        lines.append("  [!] Sin datos de goles")
        return
    
    lines.append(f"  Partidos con prediccion: {len(gol)} / {len(df)}")
    
    # --- Lambda stats ---
    lines.append("")
    lines.append("  --- Lambdas predichas ---")
    lines.append(f"  Lambda Home: Media={gol['gol_lambda_home'].mean():.3f}, "
                f"Std={gol['gol_lambda_home'].std():.3f}, "
                f"Min={gol['gol_lambda_home'].min():.3f}, Max={gol['gol_lambda_home'].max():.3f}")
    lines.append(f"  Lambda Away: Media={gol['gol_lambda_away'].mean():.3f}, "
                f"Std={gol['gol_lambda_away'].std():.3f}, "
                f"Min={gol['gol_lambda_away'].min():.3f}, Max={gol['gol_lambda_away'].max():.3f}")
    
    # --- Error de lambda ---
    lines.append("")
    lines.append("  --- Error de lambda vs goles reales ---")
    gol['err_home'] = abs(gol['gol_lambda_home'] - gol['goals_home'])
    gol['err_away'] = abs(gol['gol_lambda_away'] - gol['goals_away'])
    gol['err_total'] = abs(gol['gol_lambda_total'] - gol['total_goals'])
    
    lines.append(f"  MAE Home:  {gol['err_home'].mean():.3f}")
    lines.append(f"  MAE Away:  {gol['err_away'].mean():.3f}")
    lines.append(f"  MAE Total: {gol['err_total'].mean():.3f}")
    
    # Goles reales promedio
    lines.append(f"  Goles reales - Home: {gol['goals_home'].mean():.3f}, Away: {gol['goals_away'].mean():.3f}, "
                f"Total: {gol['total_goals'].mean():.3f}")
    
    # --- Accuracy de mercados ---
    lines.append("")
    lines.append("  --- Accuracy de mercados (umbral prob > 0.5) ---")
    
    markets = [
        ('Over 2.5', 'gol_p_total_over_25', 'gol_actual_total_over_25'),
        ('Over 3.5', 'gol_p_total_over_35', 'gol_actual_total_over_35'),
        ('BTTS', 'gol_p_btts', 'gol_actual_btts'),
        ('Home Over 0.5', 'gol_p_home_over_05', 'gol_actual_home_over_05'),
        ('Home Over 1.5', 'gol_p_home_over_15', 'gol_actual_home_over_15'),
        ('Away Over 0.5', 'gol_p_away_over_05', 'gol_actual_away_over_05'),
        ('Away Over 1.5', 'gol_p_away_over_15', 'gol_actual_away_over_15'),
    ]
    
    lines.append(f"  {'Mercado':<15} {'N':>6} {'Pred Si':>8} {'Real Si':>8} {'Acert':>7} {'Acc':>7} {'Brier':>7}")
    lines.append(f"  {'-'*15} {'-'*6} {'-'*8} {'-'*8} {'-'*7} {'-'*7} {'-'*7}")
    
    for name, pred_col, actual_col in markets:
        valid = gol[[pred_col, actual_col]].dropna()
        if valid.empty:
            continue
        
        pred_binary = (valid[pred_col] > 0.5).astype(int)
        actual = valid[actual_col].astype(int)
        
        n = len(valid)
        pred_yes = pred_binary.sum()
        real_yes = actual.sum()
        correct = (pred_binary == actual).sum()
        acc = correct / n
        brier = ((valid[pred_col] - actual) ** 2).mean()
        
        lines.append(f"  {name:<15} {n:>6} {pred_yes:>8} {real_yes:>8} {correct:>7} {acc:>6.1%} {brier:>7.4f}")
    
    # --- Top score hit rate ---
    if 'gol_actual_top_score_hit' in gol.columns:
        hits = gol['gol_actual_top_score_hit'].dropna()
        if not hits.empty:
            lines.append(f"\n  Top score exacto acertado: {hits.sum():.0f}/{len(hits)} ({hits.mean():.1%})")
    
    # --- Calibracion: prob predicha vs frecuencia real ---
    lines.append("")
    lines.append("  --- Calibracion Over 2.5 (prob predicha vs % real) ---")
    valid_o25 = gol[['gol_p_total_over_25', 'gol_actual_total_over_25']].dropna()
    if not valid_o25.empty:
        cal_bins = [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]
        cal_labels = ['0-20%', '20-30%', '30-40%', '40-50%', '50-60%', '60-70%', '70-80%', '80-100%']
        valid_o25['prob_bin'] = pd.cut(valid_o25['gol_p_total_over_25'], bins=cal_bins, labels=cal_labels, right=False)
        
        cal = valid_o25.groupby('prob_bin', observed=False).agg(
            n=('gol_actual_total_over_25', 'count'),
            real_rate=('gol_actual_total_over_25', 'mean'),
        )
        
        lines.append(f"  {'Prob Pred':<10} {'N':>6} {'% Real Over25':>14}")
        lines.append(f"  {'-'*10} {'-'*6} {'-'*14}")
        for label, row in cal.iterrows():
            if row['n'] > 0:
                lines.append(f"  {str(label):<10} {int(row['n']):>6} {row['real_rate']:>13.1%}")
    
    # --- Level bin diff ---
    lines.append("")
    lines.append("  --- Level bin diff vs resultado ---")
    valid_lvl = gol[gol['gol_level_bin_diff'].notna()].copy()
    if not valid_lvl.empty:
        lines.append(f"  Rango: {valid_lvl['gol_level_bin_diff'].min():.0f} a {valid_lvl['gol_level_bin_diff'].max():.0f}")
        lines.append(f"  Media: {valid_lvl['gol_level_bin_diff'].mean():.2f}")
        
        # Win rate del home por level_bin_diff
        valid_lvl['home_win'] = (valid_lvl['outcome'] == '1').astype(int)
        
        lvl_bins = [-10, -4, -2, -1, 0, 1, 2, 4, 10]
        lvl_labels = ['<-4', '-4 a -2', '-2 a -1', '-1 a 0', '0 a 1', '1 a 2', '2 a 4', '>4']
        valid_lvl['lvl_bin'] = pd.cut(valid_lvl['gol_level_bin_diff'], bins=lvl_bins, labels=lvl_labels, right=False)
        
        lvl_grouped = valid_lvl.groupby('lvl_bin', observed=False).agg(
            n=('home_win', 'count'),
            home_wins=('home_win', 'sum'),
        )
        lvl_grouped['home_wr'] = lvl_grouped['home_wins'] / lvl_grouped['n']
        
        lines.append(f"  {'LvlDiff':<10} {'N':>6} {'Home%':>7}")
        lines.append(f"  {'-'*10} {'-'*6} {'-'*7}")
        for label, row in lvl_grouped.iterrows():
            if row['n'] > 0:
                lines.append(f"  {str(label):<10} {int(row['n']):>6} {row['home_wr']:>6.1%}")


def analyze_constants(const_df, lines):
    """Analiza el modelo de Constantes."""
    lines.append("")
    lines.append("=" * 70)
    lines.append("3. LEY DE LAS CONSTANTES")
    lines.append("=" * 70)
    
    if const_df is None or const_df.empty:
        lines.append("  [!] Sin datos de constantes")
        return
    
    valid = const_df[const_df['pred_correct'].notna()].copy()
    lines.append(f"  Predicciones totales: {len(const_df)}")
    lines.append(f"  Con resultado verificable: {len(valid)}")
    
    if valid.empty:
        return
    
    # --- Accuracy global ---
    lines.append(f"\n  Accuracy global: {valid['pred_correct'].mean():.2%}")
    
    # --- Accuracy por tipo de constante ---
    lines.append("")
    lines.append("  --- Accuracy por constante ---")
    lines.append(f"  {'Constante':<30} {'N':>6} {'Correct':>8} {'Acc':>7} {'Tipo':<9}")
    lines.append(f"  {'-'*30} {'-'*6} {'-'*8} {'-'*7} {'-'*9}")
    
    for ct in sorted(valid['constant_type'].unique()):
        ct_df = valid[valid['constant_type'] == ct]
        n = len(ct_df)
        correct = ct_df['pred_correct'].sum()
        acc = correct / n
        is_bin = 'binario' if ct_df['is_binary'].iloc[0] == 1 else 'ternario'
        lines.append(f"  {ct:<30} {n:>6} {int(correct):>8} {acc:>6.1%} {is_bin:<9}")
    
    # --- Accuracy binarias vs ternarias ---
    lines.append("")
    bin_df = valid[valid['is_binary'] == 1]
    ter_df = valid[valid['is_binary'] == 0]
    if not bin_df.empty:
        lines.append(f"  Binarias (goles):     {bin_df['pred_correct'].mean():.2%} ({len(bin_df)} predicciones)")
    if not ter_df.empty:
        lines.append(f"  Ternarias (rendim.):  {ter_df['pred_correct'].mean():.2%} ({len(ter_df)} predicciones)")
    
    # --- Distribucion de predicciones ---
    lines.append("")
    lines.append("  --- Distribucion de pred_winner ---")
    pw = valid['pred_winner'].value_counts()
    for k, v in pw.items():
        lines.append(f"  {k}: {v} ({v/len(valid)*100:.1f}%)")
    
    # --- Distribucion de actual_change ---
    lines.append("")
    lines.append("  --- Distribucion de actual_change ---")
    ac = valid['actual_change'].value_counts()
    for k, v in ac.items():
        lines.append(f"  {k}: {v} ({v/len(valid)*100:.1f}%)")
    
    # --- Accuracy cuando el modelo esta muy seguro ---
    lines.append("")
    lines.append("  --- Accuracy por confianza (max prob predicha) ---")
    valid['max_prob'] = valid[['pred_incremento', 'pred_reset', 'pred_decremento']].max(axis=1)
    
    conf_bins = [0, 40, 50, 60, 70, 80, 101]
    conf_labels = ['<40%', '40-50%', '50-60%', '60-70%', '70-80%', '>80%']
    valid['conf_bin'] = pd.cut(valid['max_prob'], bins=conf_bins, labels=conf_labels, right=False)
    
    conf_grouped = valid.groupby('conf_bin', observed=False).agg(
        n=('pred_correct', 'count'),
        correct=('pred_correct', 'sum'),
    )
    conf_grouped['acc'] = conf_grouped['correct'] / conf_grouped['n']
    
    lines.append(f"  {'Confianza':<10} {'N':>6} {'Acc':>7}")
    lines.append(f"  {'-'*10} {'-'*6} {'-'*7}")
    for label, row in conf_grouped.iterrows():
        if row['n'] > 0:
            lines.append(f"  {str(label):<10} {int(row['n']):>6} {row['acc']:>6.1%}")


def analyze_cross_models(df, const_df, lines):
    """Analiza cruces entre modelos."""
    lines.append("")
    lines.append("=" * 70)
    lines.append("4. CRUCES ENTRE MODELOS")
    lines.append("=" * 70)
    
    # Necesitamos datos de culebras + resultado
    cul = df[df['cul_ml_break_score'].notna() & df['cul_favorite_won'].notna()].copy()
    
    if cul.empty:
        lines.append("  [!] Sin datos suficientes para cruce")
        return
    
    cul['fav_won'] = cul['cul_favorite_won'].astype(bool).astype(int)
    
    # --- Culebra + Goles ---
    if 'gol_level_bin_diff' in cul.columns:
        lines.append("")
        lines.append("  --- Culebra baja + Level diff alto = Favorito seguro? ---")
        
        cg = cul[cul['gol_level_bin_diff'].notna()].copy()
        if not cg.empty:
            conditions = [
                ('ml_break<0.55 AND lvl_diff>=3', 
                 (cg['cul_ml_break_score'] < 0.55) & (cg['gol_level_bin_diff'] >= 3)),
                ('ml_break<0.55 AND lvl_diff<3', 
                 (cg['cul_ml_break_score'] < 0.55) & (cg['gol_level_bin_diff'] < 3)),
                ('ml_break 0.55-0.70 AND lvl_diff>=3', 
                 (cg['cul_ml_break_score'] >= 0.55) & (cg['cul_ml_break_score'] < 0.70) & (cg['gol_level_bin_diff'] >= 3)),
                ('ml_break 0.55-0.70 AND lvl_diff<3', 
                 (cg['cul_ml_break_score'] >= 0.55) & (cg['cul_ml_break_score'] < 0.70) & (cg['gol_level_bin_diff'] < 3)),
                ('ml_break>=0.70 AND lvl_diff>=3', 
                 (cg['cul_ml_break_score'] >= 0.70) & (cg['gol_level_bin_diff'] >= 3)),
                ('ml_break>=0.70 AND lvl_diff<3', 
                 (cg['cul_ml_break_score'] >= 0.70) & (cg['gol_level_bin_diff'] < 3)),
            ]
            
            lines.append(f"  {'Condicion':<40} {'N':>6} {'Fav%':>7}")
            lines.append(f"  {'-'*40} {'-'*6} {'-'*7}")
            for name, mask in conditions:
                subset = cg[mask]
                if len(subset) > 0:
                    lines.append(f"  {name:<40} {len(subset):>6} {subset['fav_won'].mean():>6.1%}")
    
    # --- Culebra + Burbuja (via constantes) ---
    if const_df is not None and not const_df.empty:
        lines.append("")
        lines.append("  --- Burbuja score promedio vs resultado ---")
        
        # Calcular burbuja score por equipo/partido
        # Solo constantes de rendimiento local/visita
        relevant = const_df[
            const_df['constant_type'].isin(['k_local', 'k_visita']) & 
            const_df['pred_incremento'].notna()
        ].copy()
        
        if not relevant.empty:
            relevant['burbuja'] = (relevant['pred_incremento'] - relevant['pred_decremento']) / 100
            
            # Agregar por fixture_id
            burbuja_by_fx = relevant.groupby(['fixture_id', 'is_home'])['burbuja'].mean().unstack(fill_value=0)
            burbuja_by_fx.columns = ['burbuja_away', 'burbuja_home']
            burbuja_by_fx['burbuja_diff'] = burbuja_by_fx['burbuja_home'] - burbuja_by_fx['burbuja_away']
            
            # Merge con main
            merged = cul.merge(burbuja_by_fx, left_on='fixture_id', right_index=True, how='inner')
            
            if not merged.empty:
                lines.append(f"  Partidos con burbuja: {len(merged)}")
                
                # Burbuja diff positiva = home favorable
                bub_conditions = [
                    ('Burbuja home > away AND ml_break<0.55',
                     (merged['burbuja_diff'] > 0.1) & (merged['cul_ml_break_score'] < 0.55)),
                    ('Burbuja home > away AND ml_break>=0.65',
                     (merged['burbuja_diff'] > 0.1) & (merged['cul_ml_break_score'] >= 0.65)),
                    ('Burbuja away > home AND ml_break<0.55',
                     (merged['burbuja_diff'] < -0.1) & (merged['cul_ml_break_score'] < 0.55)),
                    ('Burbuja away > home AND ml_break>=0.65',
                     (merged['burbuja_diff'] < -0.1) & (merged['cul_ml_break_score'] >= 0.65)),
                ]
                
                # Para este cruce necesitamos favorito = home
                merged_fav_home = merged[merged['cul_favorite'] == 'home']
                
                lines.append(f"  (Solo favorito=home: {len(merged_fav_home)} partidos)")
                lines.append(f"  {'Condicion':<45} {'N':>6} {'Fav%':>7}")
                lines.append(f"  {'-'*45} {'-'*6} {'-'*7}")
                for name, mask in bub_conditions:
                    subset = merged_fav_home[mask]
                    if len(subset) > 5:
                        lines.append(f"  {name:<45} {len(subset):>6} {subset['fav_won'].mean():>6.1%}")
    
    # --- Correlaciones ---
    lines.append("")
    lines.append("  --- Correlaciones con resultado (fav_won) ---")
    
    corr_cols = [
        'cul_ml_break_score', 'cul_icf_diff', 'cul_favorite_prob', 'cul_prob_underdog',
        'cul_rest_days_diff', 'cul_match_importance',
    ]
    
    if 'gol_level_bin_diff' in cul.columns:
        corr_cols.extend(['gol_level_bin_diff', 'gol_lambda_home', 'gol_lambda_away'])
    
    for col in corr_cols:
        if col in cul.columns:
            valid = cul[[col, 'fav_won']].dropna()
            if len(valid) > 10:
                corr = valid[col].corr(valid['fav_won'])
                lines.append(f"  {col:<30} r = {corr:>7.4f}")


def analyze_general(df, lines):
    """Estadisticas generales del dataset."""
    lines.append("=" * 70)
    lines.append("0. RESUMEN GENERAL DEL DATASET")
    lines.append("=" * 70)
    
    lines.append(f"  Total partidos: {len(df)}")
    lines.append(f"  Columnas: {len(df.columns)}")
    lines.append(f"  Periodo: {df['date'].min()} a {df['date'].max()}")
    lines.append(f"  Ligas: {df['league_id'].nunique()}")
    
    # Resultados
    lines.append(f"\n  --- Resultados ---")
    outcome_counts = df['outcome'].value_counts()
    for k, v in outcome_counts.items():
        lines.append(f"  {k}: {v} ({v/len(df)*100:.1f}%)")
    
    lines.append(f"  Goles promedio: {df['total_goals'].mean():.2f}")
    lines.append(f"  Partidos con 0 goles: {(df['total_goals'] == 0).sum()}")
    
    # Top ligas
    lines.append(f"\n  --- Top 15 ligas por partidos ---")
    top_leagues = df.groupby(['league_id', 'league_name']).size().sort_values(ascending=False).head(15)
    for (lid, lname), count in top_leagues.items():
        lines.append(f"  [{lid}] {lname[:35]:<35} {count:>5}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Analizar predicciones historicas SAD')
    parser.add_argument('--main', type=str, default=None, help='Path al CSV principal')
    parser.add_argument('--constants', type=str, default=None, help='Path al CSV de constantes')
    parser.add_argument('--output', type=str, default='analysis_report.txt', help='Archivo de salida')
    
    args = parser.parse_args()
    
    # Buscar archivos
    if args.main is None:
        main_csv, const_csv = find_csv_files()
    else:
        main_csv = args.main
        const_csv = args.constants
    
    if main_csv is None:
        print("ERROR: No se encontro el CSV principal.")
        print("Uso: python analyze_predictions.py --main path/predictions_main.csv")
        sys.exit(1)
    
    print(f"Leyendo CSV principal: {main_csv}")
    df = pd.read_csv(main_csv)
    print(f"  {len(df)} filas x {len(df.columns)} columnas")
    
    const_df = None
    if const_csv and os.path.exists(const_csv):
        print(f"Leyendo CSV constantes: {const_csv}")
        const_df = pd.read_csv(const_csv)
        print(f"  {len(const_df)} filas x {len(const_df.columns)} columnas")
    
    # Analizar
    lines = []
    lines.append("=" * 70)
    lines.append("ANALISIS DE PREDICCIONES HISTORICAS - SAD v6")
    lines.append(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"CSV: {os.path.basename(main_csv)}")
    lines.append("=" * 70)
    
    analyze_general(df, lines)
    analyze_culebras(df, lines)
    analyze_goals(df, lines)
    analyze_constants(const_df, lines)
    analyze_cross_models(df, const_df, lines)
    
    # Footer
    lines.append("")
    lines.append("=" * 70)
    lines.append("FIN DEL REPORTE")
    lines.append("=" * 70)
    
    report = '\n'.join(lines)
    
    # Guardar
    output_path = args.output
    if not os.path.isabs(output_path):
        # Guardar junto al CSV
        output_path = os.path.join(os.path.dirname(main_csv), output_path)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\nReporte guardado en: {output_path}")
    print(f"Lineas: {len(lines)}")
    print("\n--- PEGA ESTO EN CLAUDE ---\n")
    print(report)


if __name__ == '__main__':
    main()