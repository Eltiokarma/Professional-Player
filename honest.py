# evaluate_v61_honest.py
# -*- coding: utf-8 -*-
"""
Evaluacion HONESTA v6.1 - USA MODELO YA ENTRENADO
Genera dataset CHICO (2 ligas, 6 meses) solo para evaluar.
Deberia tardar 2-4 minutos, no 20.
"""

import sys, os
import numpy as np
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from ui.anticulebra.anticulebra_engine import AnticulebraEngine

def evaluate():
    engine = AnticulebraEngine()
    
    print("=" * 60)
    print("EVALUACION HONESTA v6.1")
    print("Modelo ya entrenado, dataset reducido para evaluar")
    print("=" * 60)
    
    if engine.ml_break_model is None:
        print("ERROR: No hay modelo cargado")
        return
    
    n_features = engine.ml_scaler.n_features_in_
    print(f"Modelo cargado: {n_features} features")
    
    # Dataset CHICO: 2 ligas, 6 meses
    # 667 = Liga 1 Peru, 128 = Liga Profesional Argentina
    test_leagues = [667, 128]
    start = date(2025, 6, 1)
    end = date(2026, 2, 9)
    
    print(f"\nGenerando dataset reducido...")
    print(f"  Ligas: {test_leagues}")
    print(f"  Periodo: {start} a {end}")
    
    df = engine.generate_ml_dataset(
        league_ids=test_leagues,
        start_date=start,
        end_date=end
    )
    
    if df.empty:
        print("ERROR: Dataset vacio")
        return
    
    total = len(df)
    total_breaks = int(df['broke_snake'].sum())
    
    # Separar culebra viva vs muerta
    df_alive = df[df['snake_intact_before'] == 1.0].copy()
    df_dead = df[df['snake_intact_before'] < 1.0].copy()
    
    alive_n = len(df_alive)
    alive_breaks = int(df_alive['broke_snake'].sum())
    dead_n = len(df_dead)
    dead_breaks = int(df_dead['broke_snake'].sum())
    
    print(f"\n--- DATASET ---")
    print(f"Total:          {total:>5} muestras, {total_breaks} breaks ({total_breaks/total*100:.1f}%)")
    print(f"Culebra VIVA:   {alive_n:>5} muestras, {alive_breaks} breaks ({alive_breaks/max(alive_n,1)*100:.1f}%)")
    print(f"Culebra MUERTA: {dead_n:>5} muestras, {dead_breaks} breaks")
    
    if alive_n < 30:
        print("ERROR: Muy pocas muestras con culebra viva")
        return
    
    # Predecir con modelo ya entrenado
    from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score, confusion_matrix
    
    features = engine.ML_FEATURES[:n_features]
    
    # === AUC GLOBAL (referencia) ===
    X_all = df[features].fillna(0)
    y_all = df['broke_snake'].values
    y_all_proba = engine.ml_break_model.predict_proba(engine.ml_scaler.transform(X_all))[:, 1]
    auc_global = roc_auc_score(y_all, y_all_proba)
    
    # === AUC HONESTO: solo culebra viva ===
    X_alive = df_alive[features].fillna(0)
    y_alive = df_alive['broke_snake'].values
    y_alive_proba = engine.ml_break_model.predict_proba(engine.ml_scaler.transform(X_alive))[:, 1]
    auc_honest = roc_auc_score(y_alive, y_alive_proba) if len(np.unique(y_alive)) > 1 else 0
    
    print(f"\n{'='*60}")
    print(f"AUC global (inflado):            {auc_global:.4f}")
    print(f"AUC honesto (solo culebra viva): {auc_honest:.4f}")
    print(f"{'='*60}")
    
    print(f"\n{'Umbral':>8} {'Prec':>7} {'Recall':>7} {'F1':>7} {'TP':>5} {'FP':>5} {'FN':>5} {'TN':>5}")
    print("-" * 62)
    
    for t in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]:
        yp = (y_alive_proba >= t).astype(int)
        prec = precision_score(y_alive, yp, zero_division=0)
        rec = recall_score(y_alive, yp, zero_division=0)
        f1 = f1_score(y_alive, yp, zero_division=0)
        tn, fp, fn, tp = confusion_matrix(y_alive, yp).ravel()
        mark = " <--" if t == 0.50 else ""
        print(f"  {t:.2f}   {prec*100:>5.1f}%  {rec*100:>5.1f}%  {f1*100:>5.1f}%  {tp:>4}  {fp:>4}  {fn:>4}  {tn:>4}{mark}")
    
    baseline = alive_breaks / max(alive_n, 1)
    print(f"\nBaseline: {baseline*100:.1f}% de breaks con culebra viva")
    
    # Sanity check culebra muerta
    if dead_n > 0:
        X_dead = df_dead[features].fillna(0)
        y_dead_proba = engine.ml_break_model.predict_proba(engine.ml_scaler.transform(X_dead))[:, 1]
        print(f"\nSanity check culebra muerta:")
        print(f"  ML score promedio: {y_dead_proba.mean():.4f} (deberia ser bajo)")
        print(f"  ML score maximo:   {y_dead_proba.max():.4f}")
    
    # Veredicto
    print(f"\n{'='*60}")
    if auc_honest >= 0.80:
        print(f"VEREDICTO: FUNCIONA BIEN (AUC honesto {auc_honest:.3f})")
    elif auc_honest >= 0.70:
        print(f"VEREDICTO: FUNCIONA DECENTE (AUC honesto {auc_honest:.3f})")
    elif auc_honest >= 0.60:
        print(f"VEREDICTO: FUNCIONA POCO (AUC honesto {auc_honest:.3f})")
    else:
        print(f"VEREDICTO: NO FUNCIONA (AUC honesto {auc_honest:.3f})")
    print(f"{'='*60}")


if __name__ == "__main__":
    evaluate()