# motor_sad/test_motor_sad.py
"""
Test de humo del motor portable. Ejecutar desde la raíz del repo:

    python3 -m motor_sad.test_motor_sad

Valida:
  1. Niveles: regla <20 partidos (0.5), fórmula P+G+1 y asignación retroactiva.
  2. Constantes: el ejemplo numérico oficial del doc (3-1 local vs rival nivel 4).
  3. Incremental: continuidad de acumuladores y recálculo por hueco retroactivo.
  4. Discretizador uniforme, bins fijos v6 y fusión.
"""
import os
import shutil
import tempfile

from .db import init_all, connect, db_path, SAD_DB, LEVELS_DB
from .levels import LevelsEngine
from .constants import ConstantsEngine
from .discretizer import UniformDiscretizer, fixed_bin, fuse
from .pipeline import sync_all

FINISHED = 'Match Finished'


def _insert_fixture(conn, fid, date, home, away, gh, ga):
    conn.execute(
        """INSERT INTO fixtures (id, date, status_long, status_short, league_id,
           league_season, home_team_id, away_team_id, goals_home, goals_away)
           VALUES (?,?,?,?,1,2024,?,?,?,?)""",
        (fid, date, FINISHED, 'FT', home, away, gh, ga),
    )


def test_levels(base):
    sad = connect(db_path(base, SAD_DB))
    sad.execute("INSERT INTO teams (id, name) VALUES (1, 'A'), (2, 'B')")
    # 25 partidos de A vs B: A gana 2-0 los primeros 10, empata 1-1 los 10
    # siguientes, pierde 0-1 los últimos 5.
    results = [(2, 0)] * 10 + [(1, 1)] * 10 + [(0, 1)] * 5
    for i, (gf, ga) in enumerate(results):
        _insert_fixture(sad, 100 + i, f"2024-01-{i+1:02d} 15:00:00", 1, 2, gf, ga)
    sad.commit()
    sad.close()

    eng = LevelsEngine(base)
    eng.calculate_missing_levels()

    lv = connect(db_path(base, LEVELS_DB))
    rows = lv.execute(
        "SELECT fixture_id, level FROM team_levels WHERE team_id = 1 ORDER BY date"
    ).fetchall()
    assert len(rows) == 25, f"esperaba 25 niveles, hay {len(rows)}"

    # Nivel del partido 20 (índice 19): P = (10*3 + 10*1)/20 = 2.0
    # últimos 5 = empates 1-1: G = 0/10 = 0 → nivel = 3.0, retroactivo a los 20 primeros
    first20 = [l for _, l in rows[:20]]
    assert all(abs(l - 3.0) < 1e-9 for l in first20), f"retroactivo mal: {set(first20)}"

    # Partido 25 (índice 24): ventana = partidos 6..25 = 5 victorias, 10 empates, 5 derrotas
    # P = (15+10+0)/20 = 1.25 ; últimos 5 = derrotas 0-1: G = -5/5 = -1 → nivel = 1.25
    assert abs(rows[24][1] - 1.25) < 1e-9, f"nivel final mal: {rows[24][1]}"

    # Equipo B jugó los mismos 25 partidos → también tiene 25 niveles
    rows_b = lv.execute("SELECT COUNT(*) FROM team_levels WHERE team_id = 2").fetchone()
    assert rows_b[0] == 25

    # Equipo con <20 partidos → todo 0.5
    sad = connect(db_path(base, SAD_DB))
    sad.execute("INSERT INTO teams (id, name) VALUES (3, 'C'), (4, 'D')")
    for i in range(5):
        _insert_fixture(sad, 300 + i, f"2024-03-{i+1:02d} 15:00:00", 3, 4, 1, 0)
    sad.commit()
    sad.close()
    eng2 = LevelsEngine(base)
    eng2.calculate_missing_levels()
    short = lv.execute("SELECT level FROM team_levels WHERE team_id = 3").fetchall()
    assert len(short) == 5 and all(l == 0.5 for (l,) in short)
    lv.close()
    eng.close()
    eng2.close()
    print("OK  niveles: ventana 20/5, retroactivo y default 0.5")


def test_constants_doc_example():
    """Ejemplo del doc §6: LOCAL gana 3-1 a rival de nivel 4."""
    q_rows = [{
        'date': '2024-05-01 15:00:00', 'fixture_id': 999,
        'q_local': 2 * 1 * 4.0,      # dif=2, res=+1, nivel=4 → +8
        'q_visita': None,
        'q_negativo': 0,
        'q_goles_anotado': 3 * 4.0,   # +12
        'q_goles_recibido': -1 * 4.0, # -4
        'q_goles_local_anotado': 12.0, 'q_goles_local_recibido': -4.0,
        'q_goles_visita_anotado': None, 'q_goles_visita_recibido': None,
    }]
    state = {'k_positivo_local': 5.0, 'k_negativo_local': -6.0, 'k_goles_anotado': 8.0}
    out = ConstantsEngine.accumulate_k_values(q_rows, state=state)[0]

    assert out['k_positivo_local'] == 13.0, out['k_positivo_local']
    assert out['k_negativo_local'] == 0, out['k_negativo_local']      # RESET
    assert out['k_goles_anotado'] == 20.0, out['k_goles_anotado']
    assert out['k_positivo'] == 8.0                                    # q_any = q_local
    assert out['k_negativo'] == 0
    assert fuse(out['k_positivo_local'], out['k_negativo_local']) == 13.0
    print("OK  constantes: ejemplo numérico oficial (+8, reset, fusión +13)")


def test_constants_pipeline(base):
    """q* end-to-end con niveles reales + incremental + retroactivo."""
    eng = ConstantsEngine(base)
    eng.batch_calculate_teams([1, 2], incremental=True)

    rows = eng.const.execute(
        "SELECT COUNT(*) FROM constants WHERE team_id = 1").fetchone()
    assert rows[0] == 25, f"esperaba 25 constantes, hay {rows[0]}"

    # A es local en todos: q_visita siempre NULL, q_local poblado
    nulls = eng.const.execute(
        "SELECT COUNT(*) FROM constants WHERE team_id = 1 AND q_visita IS NOT NULL"
    ).fetchone()[0]
    assert nulls == 0

    # Derrota 0-1 (dif 1) vs rival nivel L → q_local = -L, k_negativo acumula
    last = eng._row_as_dict(eng.const.execute(
        "SELECT * FROM constants WHERE team_id = 1 ORDER BY date DESC LIMIT 1"
    ).fetchone())
    assert last['q_local'] < 0 and last['k_negativo'] < 0 and last['k_positivo'] == 0

    # Incremental: partido nuevo → solo 1 fila más, acumulador continúa
    sad = connect(db_path(base, SAD_DB))
    _insert_fixture(sad, 200, "2024-02-10 15:00:00", 1, 2, 5, 0)  # victoria 5-0
    sad.commit()
    sad.close()
    eng2 = ConstantsEngine(base)
    eng2.incremental_calculate_and_store(1)
    n = eng2.const.execute("SELECT COUNT(*) FROM constants WHERE team_id = 1").fetchone()[0]
    assert n == 26, f"incremental: esperaba 26, hay {n}"
    new_last = eng2._row_as_dict(eng2.const.execute(
        "SELECT * FROM constants WHERE team_id = 1 ORDER BY date DESC LIMIT 1"
    ).fetchone())
    assert new_last['k_negativo'] == 0 and new_last['k_positivo'] > 0  # racha reseteada

    # Retroactivo: partido con fecha ANTERIOR → recálculo completo (27 filas coherentes)
    sad = connect(db_path(base, SAD_DB))
    _insert_fixture(sad, 201, "2024-01-15 12:00:00", 2, 1, 3, 0)  # A pierde de visita
    sad.commit()
    sad.close()
    eng3 = ConstantsEngine(base)
    eng3.incremental_calculate_and_store(1)
    n = eng3.const.execute("SELECT COUNT(*) FROM constants WHERE team_id = 1").fetchone()[0]
    assert n == 27, f"retroactivo: esperaba 27, hay {n}"
    for e in (eng, eng2, eng3):
        e.close()
    print("OK  constantes: pipeline, incremental y recálculo retroactivo")


def test_discretizer():
    d = UniformDiscretizer().fit([0.5, 3.5])
    assert d.transform_one(0.5) == 0
    assert d.transform_one(3.5) == 9      # máximo recortado al último bin
    assert d.transform_one(2.0) == 5      # (2.0-0.5)/3.0*10 = 5.0
    assert d.transform_one(1.99) == 4

    assert fixed_bin(0.4) == 0 and fixed_bin(1.0) == 1 and fixed_bin(2.2) == 5
    assert fixed_bin(3.0) == 8 and fixed_bin(3.5) == 9

    assert fuse(None, None) == 0.0 and fuse(7.5, None) == 7.5 and fuse(5.0, -2.0) == 3.0
    print("OK  discretizador uniforme, bins fijos v6 y fusión")


def test_full_pipeline(base):
    stats = sync_all(base)
    assert stats['processed_matches'] > 0
    disc = connect(db_path(base, 'discreto.db'))
    n = disc.execute("SELECT COUNT(*) FROM processed_matches").fetchone()[0]
    two_per_fixture = disc.execute(
        "SELECT COUNT(DISTINCT fixture_id) FROM processed_matches").fetchone()[0]
    assert n == two_per_fixture * 2, "debe haber 2 filas (perspectivas) por fixture"
    # idempotencia
    stats2 = sync_all(base)
    n2 = disc.execute("SELECT COUNT(*) FROM processed_matches").fetchone()[0]
    assert n2 == n, "re-ejecutar el pipeline no debe duplicar filas"
    disc.close()
    print(f"OK  pipeline completo e idempotente ({n} filas en processed_matches)")


if __name__ == '__main__':
    base = tempfile.mkdtemp(prefix='motor_sad_test_')
    try:
        init_all(base)
        test_levels(base)
        test_constants_doc_example()
        test_constants_pipeline(base)
        test_discretizer()
        test_full_pipeline(base)
        print("\n✅ Todos los tests del motor portable pasaron")
    finally:
        shutil.rmtree(base, ignore_errors=True)
