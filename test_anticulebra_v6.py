# -*- coding: utf-8 -*-
"""
TEST ANTICULEBRA v6 - Consola
==============================
Entrena el modelo v6 desde cero y evalua en consola.
Coloca este script junto a sad.db y la carpeta src/.

Salidas:
  - Metricas de entrenamiento (AUC, accuracy, calibracion)
  - Feature importance comparativa
  - Sweet spots por rango de score
  - Simulacion de apuestas
  - Guarda evaluation_dataset_v6.csv para analisis posterior
"""

import os
import sys
import time
import pickle
import warnings
import types
import numpy as np
import pandas as pd
from datetime import datetime, date

warnings.filterwarnings('ignore')

from sqlalchemy import create_engine, text
from sklearn.metrics import (
    accuracy_score, roc_auc_score, brier_score_loss,
    precision_score, recall_score, f1_score,
    classification_report, confusion_matrix
)
from sklearn.calibration import calibration_curve

# =============================================================================
# AUTO-DETECT PROJECT ROOT
# =============================================================================

def find_project_root():
    """Auto-detecta la raiz del proyecto buscando sad.db."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        script_dir,
        os.path.dirname(script_dir),
        os.path.join(script_dir, '..'),
        os.path.join(script_dir, '..', '..'),
    ]
    best = None
    best_size = 0
    for c in candidates:
        c = os.path.abspath(c)
        db_path = os.path.join(c, 'sad.db')
        if os.path.exists(db_path):
            size = os.path.getsize(db_path)
            if size > best_size:
                best = c
                best_size = size
    if best:
        return best
    raise FileNotFoundError(
        "No se encontro sad.db. Coloca este script en la carpeta raiz del proyecto."
    )


PROJECT_ROOT = find_project_root()
SAD_DB = os.path.join(PROJECT_ROOT, 'sad.db')
CONST_DB = os.path.join(PROJECT_ROOT, 'constants.db')

print()
print("=" * 70)
print(" TEST ANTICULEBRA v6 - Consola")
print("=" * 70)
print(f" Raiz:         {PROJECT_ROOT}")
print(f" sad.db:       {os.path.getsize(SAD_DB)/1024/1024:.1f} MB")
if os.path.exists(CONST_DB):
    print(f" constants.db: {os.path.getsize(CONST_DB)/1024/1024:.1f} MB")
else:
    print(" constants.db: NO ENCONTRADA")
print("=" * 70)


# =============================================================================
# IMPORT ENGINE WITH MONKEY-PATCH
# =============================================================================

def setup_engine():
    """Importa AnticulebraEngine con monkey-patch de database_manager."""
    src_dir = os.path.join(PROJECT_ROOT, 'src')
    if not os.path.exists(src_dir):
        if os.path.exists(os.path.join(PROJECT_ROOT, 'anticulebra_engine.py')):
            src_dir = PROJECT_ROOT
        else:
            print("[ERROR] No se encontro src/ ni anticulebra_engine.py")
            sys.exit(1)

    sys.path.insert(0, src_dir)

    mock_data = types.ModuleType('data')
    mock_data.__path__ = [os.path.join(src_dir, 'data')]
    mock_db = types.ModuleType('data.database_manager')
    mock_db.BASE_DIR = PROJECT_ROOT
    mock_db.ORIG_ENGINE = create_engine(f'sqlite:///{SAD_DB}')
    mock_db.CONST_ENGINE = create_engine(f'sqlite:///{CONST_DB}')
    mock_data.database_manager = mock_db

    sys.modules['data'] = mock_data
    sys.modules['data.database_manager'] = mock_db

    from ui.anticulebra.anticulebra_engine import AnticulebraEngine
    return AnticulebraEngine


# =============================================================================
# UTILITIES
# =============================================================================

def hbar(char="-", width=70):
    print(char * width)

def section(title):
    print()
    hbar("=")
    print(f" {title}")
    hbar("=")

def subsection(title):
    print(f"\n--- {title} ---")


# =============================================================================
# 1. GENERAR DATASET v6
# =============================================================================

def step_generate_dataset(EngineClass):
    section("1. GENERANDO DATASET v6")
    t0 = time.time()
    
    engine = EngineClass()
    
    leagues = engine.get_available_leagues(require_odds=False)
    league_ids = [l['league_id'] for l in leagues[:25]]
    print(f" Ligas: {len(league_ids)}")
    
    df = engine.generate_ml_dataset(
        league_ids=league_ids,
        min_matches_per_day=2,
        progress_callback=lambda p, m: print(f"\r  [{p:3d}%] {m:<60s}", end="", flush=True)
    )
    print()
    
    elapsed = time.time() - t0
    print(f"\n Dataset generado en {elapsed:.1f}s")
    print(f" Total muestras:  {len(df):,}")
    print(f" Rupturas:        {int(df['broke_snake'].sum()):,} ({df['broke_snake'].mean()*100:.1f}%)")
    print(f" Ligas:           {df['league_id'].nunique()}")
    print(f" Periodo:         {df['date'].min()} a {df['date'].max()}")
    
    # Verificar que las 6 nuevas features existen
    v6_features = ['n_matches_day', 'joint_prob_all_favs', 'min_favorite_prob_day',
                   'mean_favorite_prob_day', 'weakest_link_rank', 'n_tight_matches_day']
    missing = [f for f in v6_features if f not in df.columns]
    if missing:
        print(f"\n [ERROR] Features v6 faltantes: {missing}")
        print(" Asegurate de estar usando anticulebra_engine.py v6")
        sys.exit(1)
    else:
        print(f" Features v6:     6/6 presentes OK")
    
    return df, engine


# =============================================================================
# 2. ENTRENAR MODELO v6
# =============================================================================

def step_train_model(engine, df):
    section("2. ENTRENANDO MODELO v6")
    t0 = time.time()
    
    result = engine.train_ml_model(
        df=df,
        use_smote=False,
        progress_callback=lambda p, m: print(f"\r  [{p:3d}%] {m:<60s}", end="", flush=True)
    )
    print()
    
    elapsed = time.time() - t0
    print(f"\n Entrenamiento completado en {elapsed:.1f}s")
    print(f" Modelo:          {result.model_type}")
    print(f" AUC-ROC (test):  {result.auc_roc:.4f}")
    print(f" Accuracy (test): {result.accuracy:.4f}")
    print(f" Precision:       {result.precision_break:.4f}")
    print(f" Recall:          {result.recall_break:.4f}")
    print(f" CV Scores:       {[round(s,4) for s in result.cross_val_scores]}")
    print(f" CV Mean:         {np.mean(result.cross_val_scores):.4f} +/- {np.std(result.cross_val_scores):.4f}")
    
    return result


# =============================================================================
# 3. EVALUACION COMPLETA EN TEST SET
# =============================================================================

def step_evaluate(engine, df):
    section("3. EVALUACION COMPLETA")
    
    feature_cols = engine.ML_FEATURES
    X = df[feature_cols].fillna(0)
    y = df['broke_snake'].values
    
    # Reproducir el split 3-way del entrenamiento
    split_train = int(len(X) * 0.70)
    split_cal = int(len(X) * 0.85)
    
    X_test = X.iloc[split_cal:]
    y_test = y[split_cal:]
    
    print(f" Test set: {len(X_test):,} muestras ({y_test.sum():.0f} rupturas)")
    
    # Generar predicciones en test set
    X_test_scaled = engine.ml_scaler.transform(X_test)
    y_proba = engine.ml_break_model.predict_proba(X_test_scaled)[:, 1]
    y_pred = (y_proba >= 0.5).astype(int)
    
    # --- 3a. Metricas basicas ---
    subsection("3a. Metricas Basicas")
    
    auc = roc_auc_score(y_test, y_proba) if len(np.unique(y_test)) > 1 else 0.5
    acc = accuracy_score(y_test, y_pred)
    brier = brier_score_loss(y_test, y_proba)
    corr = np.corrcoef(y_proba, y_test)[0, 1]
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    
    print(f" AUC-ROC:      {auc:.4f}")
    print(f" Correlacion:  {corr:.4f}")
    print(f" Accuracy:     {acc:.4f}")
    print(f" Brier Score:  {brier:.4f}")
    print(f" Precision:    {prec:.4f}")
    print(f" Recall:       {rec:.4f}")
    print(f" F1-Score:     {f1:.4f}")
    
    # --- 3b. Confusion Matrix ---
    subsection("3b. Matriz de Confusion")
    
    cm = confusion_matrix(y_test, y_pred)
    tn, fp, fn, tp = cm.ravel()
    print(f"                  Pred: NO    Pred: SI")
    print(f"  Real: NO       {tn:>7,}     {fp:>7,}")
    print(f"  Real: SI       {fn:>7,}     {tp:>7,}")
    
    # --- 3c. Distribucion de scores ---
    subsection("3c. Distribucion de Scores")
    
    print(f" Media:     {np.mean(y_proba):.4f}")
    print(f" Mediana:   {np.median(y_proba):.4f}")
    print(f" Std:       {np.std(y_proba):.4f}")
    print(f" Min:       {np.min(y_proba):.4f}")
    print(f" Max:       {np.max(y_proba):.4f}")
    
    # Bimodalidad check
    below_01 = np.sum(y_proba < 0.1)
    above_06 = np.sum(y_proba > 0.6)
    middle = np.sum((y_proba >= 0.1) & (y_proba <= 0.6))
    total = len(y_proba)
    print(f"\n Score < 0.10:  {below_01:>6,} ({below_01/total*100:.1f}%)")
    print(f" 0.10 - 0.60:  {middle:>6,} ({middle/total*100:.1f}%)")
    print(f" Score > 0.60:  {above_06:>6,} ({above_06/total*100:.1f}%)")
    
    bimodal = below_01 > total * 0.3 and above_06 > total * 0.3 and middle < total * 0.2
    print(f" Bimodal?:      {'SI - PROBLEMA!' if bimodal else 'NO - OK'}")
    
    # --- 3d. Calibracion ---
    subsection("3d. Calibracion")
    
    try:
        prob_true, prob_pred = calibration_curve(y_test, y_proba, n_bins=10, strategy='uniform')
        print(f" {'Bin':>12} {'Predicho':>10} {'Real':>10} {'Error':>10} {'N':>8}")
        print(f" {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
        
        # Contar por bin
        bin_edges = np.linspace(0, 1, 11)
        for i in range(len(prob_true)):
            n_in_bin = np.sum((y_proba >= bin_edges[i]) & (y_proba < bin_edges[i+1]))
            err = abs(prob_true[i] - prob_pred[i])
            print(f" {bin_edges[i]:.1f}-{bin_edges[i+1]:.1f}     {prob_pred[i]:>8.4f}   {prob_true[i]:>8.4f}   {err:>8.4f}   {n_in_bin:>6,}")
        
        cal_error = np.mean(np.abs(prob_true - prob_pred))
        print(f"\n Error medio de calibracion: {cal_error:.4f}")
        
        if cal_error < 0.05:
            print(" Calibracion: EXCELENTE (< 5%)")
        elif cal_error < 0.10:
            print(" Calibracion: BUENA (< 10%)")
        elif cal_error < 0.15:
            print(" Calibracion: ACEPTABLE (< 15%)")
        else:
            print(" Calibracion: MALA (>= 15%)")
    except Exception as e:
        print(f" Error calculando calibracion: {e}")
    
    return y_test, y_proba, X_test


# =============================================================================
# 4. FEATURE IMPORTANCE
# =============================================================================

def step_feature_importance(engine, df):
    section("4. FEATURE IMPORTANCE")
    
    feature_cols = engine.ML_FEATURES
    y = df['broke_snake'].values
    
    # Gini importance del base model
    base_model = engine._ml_base_model
    if base_model is not None and hasattr(base_model, 'feature_importances_'):
        importances = dict(zip(feature_cols, base_model.feature_importances_))
    elif engine.ml_training_result:
        importances = engine.ml_training_result.feature_importances
    else:
        print(" No hay feature importances disponibles")
        return
    
    # Correlaciones crudas
    correlations = {}
    for f in feature_cols:
        if f in df.columns:
            vals = df[f].fillna(0).values
            if np.std(vals) > 0:
                correlations[f] = np.corrcoef(vals, y)[0, 1]
            else:
                correlations[f] = 0.0
    
    # Tabla combinada
    sorted_feats = sorted(importances.items(), key=lambda x: x[1], reverse=True)
    
    print(f"\n {'Feature':<28s} {'Gini':>8s} {'Corr':>8s} {'|Corr|':>8s} {'Tipo':>10s}")
    print(f" {'-'*28} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    
    v6_new = {'n_matches_day', 'joint_prob_all_favs', 'min_favorite_prob_day',
              'mean_favorite_prob_day', 'weakest_link_rank', 'n_tight_matches_day'}
    
    for feat, gini in sorted_feats:
        corr = correlations.get(feat, 0)
        tipo = "v6 NEW" if feat in v6_new else "v5"
        print(f" {feat:<28s} {gini:>8.4f} {corr:>+8.4f} {abs(corr):>8.4f} {tipo:>10s}")
    
    # Resumen
    v6_gini = sum(importances.get(f, 0) for f in v6_new)
    v5_gini = sum(importances.get(f, 0) for f in feature_cols if f not in v6_new)
    print(f"\n Gini total v5 features: {v5_gini:.4f}")
    print(f" Gini total v6 features: {v6_gini:.4f}")
    print(f" Porcentaje v6:          {v6_gini/(v5_gini+v6_gini)*100:.1f}%")


# =============================================================================
# 5. SWEET SPOTS POR RANGO DE SCORE
# =============================================================================

def step_sweet_spots(y_test, y_proba, df_test_meta=None):
    section("5. SWEET SPOTS POR RANGO DE SCORE")
    
    subsection("5a. Tasa de ruptura por rango de score")
    
    bins = [(0.00, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
            (0.20, 0.30), (0.30, 0.40), (0.40, 0.50), (0.50, 0.60),
            (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)]
    
    print(f" {'Rango':>12} {'N':>8} {'Rupturas':>10} {'Tasa':>8} {'WinRate Fav':>12}")
    print(f" {'-'*12} {'-'*8} {'-'*10} {'-'*8} {'-'*12}")
    
    for lo, hi in bins:
        mask = (y_proba >= lo) & (y_proba < hi)
        n = mask.sum()
        if n == 0:
            continue
        breaks = y_test[mask].sum()
        rate = breaks / n
        win_rate = 1 - rate
        
        # Colorear: verde si win_rate > 0.65, rojo si < 0.50
        marker = " <<" if win_rate >= 0.70 else (" !!" if win_rate < 0.50 else "")
        print(f" {lo:.2f}-{hi:.2f}    {n:>6,}   {int(breaks):>8,}   {rate:>6.1%}      {win_rate:>6.1%}{marker}")
    
    subsection("5b. Metricas por umbral de decision")
    
    print(f" {'Umbral':>8} {'Acc':>8} {'Prec':>8} {'Rec':>8} {'F1':>8} {'N Flag':>8} {'%Flag':>8}")
    print(f" {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    
    for threshold in [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
        y_p = (y_proba >= threshold).astype(int)
        n_flagged = y_p.sum()
        pct_flagged = n_flagged / len(y_p) * 100
        
        acc = accuracy_score(y_test, y_p)
        prec = precision_score(y_test, y_p, zero_division=0)
        rec = recall_score(y_test, y_p, zero_division=0)
        f1 = f1_score(y_test, y_p, zero_division=0)
        
        print(f" {threshold:>8.2f} {acc:>8.4f} {prec:>8.4f} {rec:>8.4f} {f1:>8.4f} {n_flagged:>7,} {pct_flagged:>6.1f}%")


# =============================================================================
# 6. SIMULACION DE APUESTAS
# =============================================================================

def step_betting_sim(y_test, y_proba):
    section("6. SIMULACION DE APUESTAS")
    print(" Escenario: Apostamos al favorito. Cuota promedio = 1.30")
    print(" Score BAJO = favorito seguro = apostamos")
    print(" Score ALTO = riesgo de ruptura = no apostamos\n")
    
    cuota = 1.30
    
    print(f" {'Estrategia':<35s} {'Apostadas':>10} {'Ganadas':>8} {'WinRate':>8} {'ROI':>10}")
    print(f" {'-'*35} {'-'*10} {'-'*8} {'-'*8} {'-'*10}")
    
    # Sin filtro (baseline)
    n_total = len(y_test)
    n_wins_total = int((1 - y_test).sum())  # favorito gano = no ruptura
    wr_total = n_wins_total / n_total
    roi_total = wr_total * cuota - 1
    print(f" {'Sin filtro (baseline)':<35s} {n_total:>10,} {n_wins_total:>8,} {wr_total:>7.1%} {roi_total:>+9.1%}")
    
    # Filtros por umbral
    for max_score in [0.50, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.15, 0.10, 0.05]:
        mask = y_proba < max_score
        n = mask.sum()
        if n == 0:
            continue
        n_wins = int((1 - y_test[mask]).sum())
        wr = n_wins / n
        roi = wr * cuota - 1
        
        marker = " ***" if roi > 0 else ""
        label = f"Score < {max_score:.2f}"
        print(f" {label:<35s} {n:>10,} {n_wins:>8,} {wr:>7.1%} {roi:>+9.1%}{marker}")
    
    # Estrategia inversa: solo scores altos (para verificar que esos SI rompen)
    print()
    print(" Verificacion inversa (scores ALTOS = no apostar):")
    for min_score in [0.50, 0.60, 0.70, 0.80]:
        mask = y_proba >= min_score
        n = mask.sum()
        if n == 0:
            continue
        n_breaks = int(y_test[mask].sum())
        break_rate = n_breaks / n
        label = f"Score >= {min_score:.2f}"
        print(f"   {label:<25s} N={n:>6,}  Rupturas={break_rate:.1%}")


# =============================================================================
# 7. COMPARATIVA v5 vs v6 (si existe pkl v5)
# =============================================================================

def step_compare_v5(engine, df, y_test, y_proba_v6):
    v5_path = os.path.join(PROJECT_ROOT, 'anticulebra_ml_model_v5.pkl')
    if not os.path.exists(v5_path):
        print("\n (No se encontro anticulebra_ml_model_v5.pkl para comparar)")
        return
    
    section("7. COMPARATIVA v5 vs v6")
    
    try:
        with open(v5_path, 'rb') as f:
            v5_data = pickle.load(f)
        
        v5_model = v5_data.get('break_model')
        v5_scaler = v5_data.get('scaler')
        
        if v5_model is None or v5_scaler is None:
            print(" No se pudo cargar modelo v5")
            return
        
        # v5 solo tiene 8 features
        v5_features = ['prob_draw', 'prob_underdog', 'icf_diff', 'position_normalized',
                       'is_simultaneous', 'accumulated_tension', 'match_importance', 'rest_days_diff']
        
        split_cal = int(len(df) * 0.85)
        X_test_v5 = df[v5_features].fillna(0).iloc[split_cal:]
        y_test_both = df['broke_snake'].values[split_cal:]
        
        X_test_v5_scaled = v5_scaler.transform(X_test_v5)
        y_proba_v5 = v5_model.predict_proba(X_test_v5_scaled)[:, 1]
        
        auc_v5 = roc_auc_score(y_test_both, y_proba_v5) if len(np.unique(y_test_both)) > 1 else 0.5
        auc_v6 = roc_auc_score(y_test_both, y_proba_v6) if len(np.unique(y_test_both)) > 1 else 0.5
        brier_v5 = brier_score_loss(y_test_both, y_proba_v5)
        brier_v6 = brier_score_loss(y_test_both, y_proba_v6)
        corr_v5 = np.corrcoef(y_proba_v5, y_test_both)[0, 1]
        corr_v6 = np.corrcoef(y_proba_v6, y_test_both)[0, 1]
        
        print(f"\n {'Metrica':<25s} {'v5':>12s} {'v6':>12s} {'Delta':>12s} {'Mejor':>8s}")
        print(f" {'-'*25} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
        
        def compare_row(name, val_v5, val_v6, higher_better=True):
            delta = val_v6 - val_v5
            if higher_better:
                mejor = "v6" if delta > 0.001 else ("v5" if delta < -0.001 else "=")
            else:
                mejor = "v6" if delta < -0.001 else ("v5" if delta > 0.001 else "=")
            sign = "+" if delta > 0 else ""
            print(f" {name:<25s} {val_v5:>12.4f} {val_v6:>12.4f} {sign}{delta:>11.4f} {mejor:>8s}")
        
        compare_row("AUC-ROC", auc_v5, auc_v6, True)
        compare_row("Brier Score", brier_v5, brier_v6, False)
        compare_row("Correlacion", corr_v5, corr_v6, True)
        
        # Win rate comparison
        cuota = 1.30
        for thr in [0.30, 0.20, 0.10]:
            mask_v5 = y_proba_v5 < thr
            mask_v6 = y_proba_v6 < thr
            
            n_v5 = mask_v5.sum()
            n_v6 = mask_v6.sum()
            
            if n_v5 > 0 and n_v6 > 0:
                wr_v5 = (1 - y_test_both[mask_v5]).sum() / n_v5
                wr_v6 = (1 - y_test_both[mask_v6]).sum() / n_v6
                compare_row(f"WinRate (score<{thr})", wr_v5, wr_v6, True)
        
    except Exception as e:
        print(f" Error comparando con v5: {e}")
        import traceback
        traceback.print_exc()


# =============================================================================
# 8. DIAGNOSTICO FINAL
# =============================================================================

def step_diagnostico(auc, corr, brier, cal_error, bimodal, cv_scores):
    section("8. DIAGNOSTICO FINAL")
    
    diagnostics = []
    
    # AUC
    if auc >= 0.75:
        diagnostics.append(("BUENO", f"AUC-ROC = {auc:.4f} (>= 0.75)"))
    elif auc >= 0.65:
        diagnostics.append(("OK", f"AUC-ROC = {auc:.4f} (>= 0.65)"))
    elif auc >= 0.55:
        diagnostics.append(("BAJO", f"AUC-ROC = {auc:.4f} (apenas mejor que azar)"))
    else:
        diagnostics.append(("CRITICO", f"AUC-ROC = {auc:.4f} (no mejor que azar)"))
    
    # Correlacion
    if abs(corr) >= 0.15:
        diagnostics.append(("BUENO", f"Correlacion = {corr:.4f} (>= 0.15)"))
    elif abs(corr) >= 0.05:
        diagnostics.append(("OK", f"Correlacion = {corr:.4f} (>= 0.05)"))
    else:
        diagnostics.append(("CRITICO", f"Correlacion = {corr:.4f} (practicamente cero)"))
    
    # Brier
    if brier < 0.20:
        diagnostics.append(("BUENO", f"Brier Score = {brier:.4f} (< 0.20)"))
    elif brier < 0.25:
        diagnostics.append(("OK", f"Brier Score = {brier:.4f} (< 0.25)"))
    else:
        diagnostics.append(("BAJO", f"Brier Score = {brier:.4f} (>= 0.25)"))
    
    # Calibracion
    if cal_error is not None:
        if cal_error < 0.05:
            diagnostics.append(("BUENO", f"Error calibracion = {cal_error:.4f} (< 5%)"))
        elif cal_error < 0.10:
            diagnostics.append(("OK", f"Error calibracion = {cal_error:.4f} (< 10%)"))
        else:
            diagnostics.append(("BAJO", f"Error calibracion = {cal_error:.4f} (>= 10%)"))
    
    # Bimodalidad
    if bimodal:
        diagnostics.append(("CRITICO", "Distribucion bimodal detectada"))
    else:
        diagnostics.append(("BUENO", "Distribucion NO bimodal"))
    
    # CV stability
    if cv_scores is not None and len(cv_scores) > 1:
        cv_std = np.std(cv_scores)
        cv_range = max(cv_scores) - min(cv_scores)
        if cv_range < 0.10:
            diagnostics.append(("BUENO", f"CV estable (rango {cv_range:.4f})"))
        elif cv_range < 0.20:
            diagnostics.append(("OK", f"CV moderadamente estable (rango {cv_range:.4f})"))
        else:
            diagnostics.append(("BAJO", f"CV inestable (rango {cv_range:.4f})"))
    
    for severity, msg in diagnostics:
        icon = {"BUENO": "+", "OK": "~", "BAJO": "!", "CRITICO": "X"}.get(severity, "?")
        print(f" [{icon}] [{severity:>8s}] {msg}")
    
    # Veredicto
    n_bueno = sum(1 for s, _ in diagnostics if s == "BUENO")
    n_critico = sum(1 for s, _ in diagnostics if s == "CRITICO")
    
    print()
    if n_critico >= 2:
        print(" VEREDICTO: MODELO NECESITA MAS TRABAJO")
    elif n_critico >= 1:
        print(" VEREDICTO: MODELO CON PROBLEMAS SIGNIFICATIVOS")
    elif n_bueno >= 4:
        print(" VEREDICTO: MODELO FUNCIONAL - LISTO PARA PRODUCCION")
    else:
        print(" VEREDICTO: MODELO ACEPTABLE - PUEDE MEJORAR")


# =============================================================================
# MAIN
# =============================================================================

def main():
    t_start = time.time()
    
    # Setup
    EngineClass = setup_engine()
    print(f"\n [OK] AnticulebraEngine importado")
    print(f" [i]  ML_FEATURES: {len(EngineClass.ML_FEATURES)} features")
    
    # --- Smart cache ---
    v6_pkl = os.path.join(PROJECT_ROOT, 'anticulebra_ml_model_v6.pkl')
    
    if os.path.exists(v6_pkl):
        pkl_size = os.path.getsize(v6_pkl) / 1024
        pkl_date = datetime.fromtimestamp(os.path.getmtime(v6_pkl))
        print(f"\n [OK] PKL v6 encontrado ({pkl_size:.0f} KB, {pkl_date})")
        print(f" [>>] Saltando entrenamiento. Solo evaluar.")
    else:
        print(f"\n [!!] No se encontro anticulebra_ml_model_v6.pkl")
        print(f"      Entrena primero desde el frontend o cambia need_train = True")
        sys.exit(1)
    
    # Buscar CSV v6 existente (si ya se genero antes)
    existing_csv = None
    for f in sorted(os.listdir(PROJECT_ROOT), reverse=True):
        if f.startswith('evaluation_dataset_v6') and f.endswith('.csv'):
            existing_csv = os.path.join(PROJECT_ROOT, f)
            break
    
    df = None
    engine = None
    
    if existing_csv:
        print(f" [CACHE] CSV encontrado: {os.path.basename(existing_csv)}")
        df = pd.read_csv(existing_csv)
        v6_feats = ['n_matches_day', 'joint_prob_all_favs', 'min_favorite_prob_day',
                     'mean_favorite_prob_day', 'weakest_link_rank', 'n_tight_matches_day']
        if all(f in df.columns for f in v6_feats) and len(df) > 1000:
            print(f" [CACHE] {len(df):,} muestras con 14 features. Evaluacion inmediata!")
            engine = EngineClass()
        else:
            print(f" [CACHE] CSV incompleto. Regenerando dataset...")
            df = None
    
    if df is None:
        # Regenerar dataset (~12-15 min, inevitable para tener ground truth)
        print(f"\n [i] Generando dataset para evaluar (el pkl ya existe, NO se reentrena)")
        print(f"     Esto toma ~12-15 min. Despues se cachea en CSV.\n")
        df, engine = step_generate_dataset(EngineClass)
        csv_path = os.path.join(PROJECT_ROOT, f'evaluation_dataset_v6_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
        df.to_csv(csv_path, index=False)
        print(f" CSV guardado: {csv_path}")
        print(f" (La proxima vez se usa el cache y es instantaneo)")
    
    if engine is None:
        engine = EngineClass()
    
    result = engine.ml_training_result
    
    # 3. Evaluar
    y_test, y_proba, X_test = step_evaluate(engine, df)
    
    # Extraer metricas para diagnostico
    auc = roc_auc_score(y_test, y_proba) if len(np.unique(y_test)) > 1 else 0.5
    corr = np.corrcoef(y_proba, y_test)[0, 1]
    brier = brier_score_loss(y_test, y_proba)
    
    try:
        prob_true, prob_pred = calibration_curve(y_test, y_proba, n_bins=10, strategy='uniform')
        cal_error = np.mean(np.abs(prob_true - prob_pred))
    except Exception:
        cal_error = None
    
    below_01 = np.sum(y_proba < 0.1)
    above_06 = np.sum(y_proba > 0.6)
    middle = np.sum((y_proba >= 0.1) & (y_proba <= 0.6))
    total = len(y_proba)
    bimodal = below_01 > total * 0.3 and above_06 > total * 0.3 and middle < total * 0.2
    
    # 4. Feature importance
    step_feature_importance(engine, df)
    
    # 5. Sweet spots
    step_sweet_spots(y_test, y_proba)
    
    # 6. Simulacion apuestas
    step_betting_sim(y_test, y_proba)
    
    # 7. Comparativa v5 vs v6
    step_compare_v5(engine, df, y_test, y_proba)
    
    # 8. Diagnostico
    cv_scores = result.cross_val_scores if result else None
    step_diagnostico(auc, corr, brier, cal_error, bimodal, cv_scores)
    
    # Fin
    elapsed = time.time() - t_start
    print()
    hbar("=")
    print(f" TEST COMPLETADO en {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f" Modelo guardado: anticulebra_ml_model_v6.pkl")
    print(f" Dataset guardado: {os.path.basename(csv_path)}")
    hbar("=")


if __name__ == "__main__":
    main()