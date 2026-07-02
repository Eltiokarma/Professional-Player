"""
run_tabla_law.py
================
Script principal para ejecutar la Ley de la Tabla de Clasificacion.

Uso:
    python run_tabla_law.py full                    # Calibracion + validacion + export
    python run_tabla_law.py calibrate               # Solo calibrar K y mu
    python run_tabla_law.py validate                # Solo validacion retroactiva
    python run_tabla_law.py leagues                 # Ver ligas disponibles
    python run_tabla_law.py table <league_id> <season> [matchday]
    python run_tabla_law.py analyze <league_id> <season> [team_id]
    python run_tabla_law.py test <team_id> <opp_id> <league_id> <season> <date> <H|A>
"""
import sys
import json
import logging
import os
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _find_db(filename: str) -> str:
    """Busca DB priorizando la MAS GRANDE entre src/ y parent/."""
    script_dir = Path(__file__).parent.resolve()
    parent_dir = script_dir.parent
    
    candidates = []
    seen = set()
    for d in [parent_dir, script_dir, Path.cwd()]:
        p = (d / filename).resolve()
        if p not in seen and p.exists():
            seen.add(p)
            candidates.append((str(p), p.stat().st_size))
    
    if not candidates:
        print(f"  !! {filename} NO ENCONTRADO")
        return filename
    
    candidates.sort(key=lambda x: x[1], reverse=True)
    chosen = candidates[0][0]
    
    if len(candidates) > 1:
        print(f"  Multiples {filename}:")
        for path, size in candidates:
            marker = " <--" if path == chosen else ""
            print(f"    {size/1024/1024:.1f} MB  {path}{marker}")
    
    return chosen


SAD_DB = _find_db('sad.db')
LEVELS_DB = _find_db('levels.db')
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tabla_law_output')


def cmd_calibrate(args):
    from tabla_law_calibrator import TablaLawCalibrator
    cal = TablaLawCalibrator(SAD_DB, LEVELS_DB)
    result = cal.full_calibration()
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, 'calibration.json')
    with open(path, 'w') as f:
        json.dump({'K': result.K, 'mu_coefficients': result.to_mu_coefficients(),
                   'mu_r_squared': result.mu_r_squared, 'band_coverage': result.band_coverage,
                   'n_matches_used': result.n_matches_used}, f, indent=2)
    print(f"\n  Guardado: {path}")
    return result


def cmd_validate(args):
    from tabla_law_validator import TablaLawValidator
    validator = TablaLawValidator(SAD_DB, LEVELS_DB)
    result = validator.validate()
    if result:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        validator.save_json(result, os.path.join(OUTPUT_DIR, 'validation.json'))
    return result


def _load_calibration():
    cal_path = os.path.join(OUTPUT_DIR, 'calibration.json')
    if os.path.exists(cal_path):
        with open(cal_path) as f:
            cal = json.load(f)
        print(f"  Calibracion cargada: K={cal['K']:.4f}")
        return cal['K'], cal['mu_coefficients']
    print("  Sin calibracion previa, usando defaults")
    return 1.20, None


def cmd_analyze(args):
    if len(args) < 2:
        print("Uso: analyze <league_id> <season> [team_id]")
        return
    
    lid, sea = int(args[0]), int(args[1])
    team_id = int(args[2]) if len(args) > 2 else None
    K, mu_coefs = _load_calibration()
    
    from tabla_law_engine import TablaLawEngine
    engine = TablaLawEngine(SAD_DB, LEVELS_DB, K=K, mu_coefficients=mu_coefs)
    
    if team_id:
        engine.print_team_trajectory(team_id, lid, sea)
    else:
        analyses = engine.analyze_league_season(lid, sea)
        team_d = []
        for tid, td in analyses.items():
            if td:
                last = td[-1]
                team_d.append((last.team_name, last.t, last.P_t, last.P_hat_t, last.D_t, last.D_norm))
        
        team_d.sort(key=lambda x: x[5], reverse=True)
        
        print(f"\n{'=' * 70}")
        print(f"  EQUIPOS POR D_norm — Liga {lid} Season {sea}")
        print(f"{'=' * 70}")
        print(f"{'Equipo':<25} {'t':>3} {'Pts':>4} {'Esp':>6} {'D':>7} {'D_norm':>8}")
        print("-" * 60)
        for name, t, pts, phat, d, dn in team_d:
            tag = "!!" if dn > 0.8 else ("++" if dn < -0.8 else "  ")
            print(f"{tag} {name:<23} {t:>3} {pts:>4} {phat:>6.1f} {d:>+7.2f} {dn:>+8.3f}")


def cmd_test(args):
    if len(args) < 6:
        print("Uso: test <team_id> <opp_id> <league_id> <season> <date> <H|A>")
        return
    
    K, mu_coefs = _load_calibration()
    from tabla_law_engine import TablaLawEngine
    engine = TablaLawEngine(SAD_DB, LEVELS_DB, K=K, mu_coefficients=mu_coefs)
    
    result = engine.victory_test(
        team_id=int(args[0]), opponent_id=int(args[1]),
        is_home=args[5].upper() == 'H',
        league_id=int(args[2]), league_season=int(args[3]), date=args[4],
    )
    if result:
        engine.print_victory_test(result)


def cmd_table(args):
    if len(args) < 2:
        print("Uso: table <league_id> <season> [matchday]")
        return
    from standings_calculator import StandingsCalculator
    calc = StandingsCalculator(SAD_DB)
    calc.print_table(int(args[0]), int(args[1]), int(args[2]) if len(args) > 2 else 38)


def cmd_leagues(args):
    from standings_calculator import StandingsCalculator
    calc = StandingsCalculator(SAD_DB)
    leagues = calc.get_available_leagues(only_sad_leagues=True)
    
    print(f"\n  LIGAS SAD DISPONIBLES ({len(leagues)})")
    print(f"  {'Liga':>6} {'Season':>8} {'Partidos':>9} {'Desde':>12} {'Hasta':>12}")
    print(f"  {'-' * 55}")
    for lg in leagues:
        print(f"  {lg['league_id']:>6} {lg['league_season']:>8} "
              f"{lg['n_matches']:>9} {str(lg['first_date'])[:10]:>12} "
              f"{str(lg['last_date'])[:10]:>12}")
    
    total_fixtures = sum(lg['n_matches'] for lg in leagues)
    print(f"\n  Total: {total_fixtures} fixtures en {len(leagues)} liga/temporadas")


def cmd_full(args):
    t0 = time.time()
    print(f"\n{'#' * 70}")
    print(f"  EJECUCION COMPLETA — Ley de la Tabla")
    print(f"{'#' * 70}")
    
    # 1. Calibrar
    print(f"\n>>> PASO 1: CALIBRACION")
    calibration = cmd_calibrate(args)
    
    # 2. Validar
    print(f"\n>>> PASO 2: VALIDACION")
    from tabla_law_validator import TablaLawValidator
    validator = TablaLawValidator(SAD_DB, LEVELS_DB)
    validation = validator.validate(calibration=calibration)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    if validation:
        validator.save_json(validation, os.path.join(OUTPUT_DIR, 'validation.json'))
        
        # 3. Export CSV
        print(f"\n>>> PASO 3: EXPORT CSV")
        validator.export_csv(calibration, os.path.join(OUTPUT_DIR, 'tabla_law_data.csv'))
    
    elapsed = time.time() - t0
    print(f"\n{'#' * 70}")
    print(f"  COMPLETO en {elapsed:.1f}s")
    print(f"  Archivos en: {OUTPUT_DIR}")
    print(f"{'#' * 70}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    print(f"\n  sad.db:    {SAD_DB} ({os.path.getsize(SAD_DB)/1024/1024:.1f} MB)")
    print(f"  levels.db: {LEVELS_DB} ({os.path.getsize(LEVELS_DB)/1024/1024:.1f} MB)")
    print(f"  output:    {OUTPUT_DIR}")
    print()
    
    commands = {
        'calibrate': cmd_calibrate, 'validate': cmd_validate,
        'analyze': cmd_analyze, 'test': cmd_test,
        'table': cmd_table, 'full': cmd_full, 'leagues': cmd_leagues,
    }
    
    cmd = sys.argv[1].lower()
    if cmd in commands:
        commands[cmd](sys.argv[2:])
    else:
        print(f"Comando desconocido: {cmd}")
        print(f"Disponibles: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
