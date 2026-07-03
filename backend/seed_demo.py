"""Genera las 4 SQLite del pipeline con ESQUEMAS REALES y datos de demo.

Sirve para probar el backend (y la web) sin las DBs de producción. La
matemática es la del motor (verificada contra MOTOR_SAD_EXTRACCION.md):
niveles por ventana de 20 con regla retroactiva, q* = dif × res × nivel del
rival (visitante ×1.4, fallback 1.0), acumuladores k* con reseteo y fusión.

    python3 -m backend.seed_demo [dir_destino]   # por defecto ./demo_data
"""
import os
import random
import sqlite3
import sys
from bisect import bisect_right
from datetime import datetime, timedelta

# Equipos con sus ids reales de API-Football (LaLiga = 140)
TEAMS = [
    (543, "Real Betis"), (536, "Sevilla FC"), (530, "Atlético Madrid"),
    (533, "Villarreal"), (541, "Real Madrid"), (529, "Barcelona"),
]
LEAGUE_ID, SEASON = 140, 2025
STRENGTH = {543: 0.35, 536: 0.05, 530: 0.7, 533: 0.3, 541: 1.0, 529: 0.9}

BINS = [0.6, 1.3, 1.6, 1.9, 2.1, 2.35, 2.55, 2.85, 3.2]


def level_bin(level: float) -> int:
    return bisect_right(BINS, level) if level >= BINS[0] else 0


def poisson(rng: random.Random, lam: float) -> int:
    import math
    L, k, p = math.exp(-lam), 0, 1.0
    while p > L and k < 8:
        k += 1
        p *= rng.random()
    return k - 1


def round_robin(ids):
    arr, rounds = list(ids), []
    n = len(arr)
    for r in range(n - 1):
        pairs = [((arr[n - 1 - i], arr[i]) if r % 2 else (arr[i], arr[n - 1 - i])) for i in range(n // 2)]
        rounds.append(pairs)
        arr.insert(1, arr.pop())
    return rounds


def make_fixtures():
    """~40 terminados por equipo + 1 en vivo + 1 programado (con odds)."""
    ids = [t for t, _ in TEAMS]
    single = round_robin(ids)
    dbl = single + [[(a, h) for h, a in rd] for rd in single]
    rounds = dbl * 4  # 40 jornadas
    now = datetime(2026, 7, 2, 21, 0, 0)
    start = now - timedelta(days=4 * len(rounds))
    fixtures, fid = [], 900001
    for i, rd in enumerate(rounds):
        date = start + timedelta(days=4 * i)
        for home, away in rd:
            rng = random.Random(fid)
            sh, sa = STRENGTH[home], STRENGTH[away]
            gh = poisson(rng, max(0.25, 1.45 + 0.9 * (sh - sa) + 0.2))
            ga = poisson(rng, max(0.2, 1.25 + 0.9 * (sa - sh)))
            fixtures.append(dict(id=fid, date=date, home=home, away=away, gh=gh, ga=ga,
                                 status_long="Match Finished", status_short="FT", elapsed=90))
            fid += 1
    # partido EN VIVO (Betis 1-0 Sevilla, 67') y PROGRAMADO (Madrid-Barça mañana)
    fixtures.append(dict(id=fid, date=now, home=543, away=536, gh=1, ga=0,
                         status_long="Second Half", status_short="2H", elapsed=67))
    fid += 1
    fixtures.append(dict(id=fid, date=now + timedelta(days=1), home=541, away=529, gh=None, ga=None,
                         status_long="Not Started", status_short="NS", elapsed=None))
    return fixtures


def compute_levels(hist):
    """§2: P (20) + G (últimos 5) + 1, con regla retroactiva del partido 20."""
    n = len(hist)
    if n == 0:
        return []
    if n < 20:
        return [0.5] * n
    levels = [0.0] * n
    for i in range(19, n):
        pts = sum(3 if h["gf"] > h["ga"] else 1 if h["gf"] == h["ga"] else 0 for h in hist[i - 19 : i + 1])
        u5 = hist[i - 4 : i + 1]
        dg = sum(h["gf"] - h["ga"] for h in u5)
        tg = sum(h["gf"] + h["ga"] for h in u5)
        levels[i] = pts / 20 + (0 if tg == 0 else dg / tg) + 1
    for i in range(19):
        levels[i] = levels[19]
    return levels


def step_k(prev, is_local, gf, ga, nivel):
    """§3: q* y los 12 acumuladores con reseteo (fiel al doc, bit a bit)."""
    dif, res = abs(gf - ga), (1 if gf > ga else 0 if gf == ga else -1)
    q_local = dif * res * nivel if is_local else None
    q_visita = 1.4 * dif * res * nivel if not is_local else None
    q_neg = dif * res * nivel if res == -1 else 0.0
    q_ga, q_gr = gf * nivel, -ga * nivel
    k = dict(prev)
    q_any = q_local if is_local else q_visita
    k["k_positivo"] = k["k_positivo"] + q_any if (q_any is not None and q_any > 0) else 0.0
    k["k_negativo"] = k["k_negativo"] + q_neg if q_neg < 0 else 0.0
    if is_local:
        k["k_positivo_local"] = k["k_positivo_local"] + q_local if q_local > 0 else 0.0
        k["k_negativo_local"] = k["k_negativo_local"] + q_local if q_local < 0 else 0.0
        k["k_goles_local_anotado"] = k["k_goles_local_anotado"] + q_ga if q_ga > 0 else 0.0
        k["k_goles_local_recibido"] = k["k_goles_local_recibido"] + abs(q_gr) if q_gr < 0 else 0.0
    else:
        k["k_positivo_visita"] = k["k_positivo_visita"] + q_visita if q_visita > 0 else 0.0
        k["k_negativo_visita"] = k["k_negativo_visita"] + q_visita if q_visita < 0 else 0.0
        k["k_goles_visita_anotado"] = k["k_goles_visita_anotado"] + q_ga if q_ga > 0 else 0.0
        k["k_goles_visita_recibido"] = k["k_goles_visita_recibido"] + abs(q_gr) if q_gr < 0 else 0.0
    k["k_goles_anotado"] = k["k_goles_anotado"] + q_ga if q_ga > 0 else 0.0
    k["k_goles_recibido"] = k["k_goles_recibido"] + abs(q_gr) if q_gr < 0 else 0.0
    q = dict(q_local=q_local, q_visita=q_visita, q_negativo=q_neg,
             q_goles_anotado=q_ga, q_goles_recibido=q_gr,
             q_goles_local_anotado=q_ga if is_local else None,
             q_goles_local_recibido=q_gr if is_local else None,
             q_goles_visita_anotado=q_ga if not is_local else None,
             q_goles_visita_recibido=q_gr if not is_local else None)
    return q, k


K0 = {k: 0.0 for k in (
    "k_positivo", "k_negativo", "k_positivo_local", "k_negativo_local",
    "k_positivo_visita", "k_negativo_visita", "k_goles_anotado", "k_goles_recibido",
    "k_goles_local_anotado", "k_goles_local_recibido", "k_goles_visita_anotado", "k_goles_visita_recibido")}


ODDS_MARKETS = [
    ("Match Winner", [("Home", 2.4), ("Draw", 3.3), ("Away", 2.95)]),
    ("Double Chance", [("Home/Draw", 1.38), ("Home/Away", 1.30), ("Draw/Away", 1.55)]),
    ("Goals Over/Under", [("Over 2.5", 2.02), ("Under 2.5", 1.80)]),
    ("Both Teams Score", [("Yes", 1.74), ("No", 2.06)]),
    ("Asian Handicap", [("Home -0.5", 1.96), ("Away +0.5", 1.86)]),
]
BOOKMAKERS = [(8, "Bet365"), (11, "1xBet"), (32, "Pinnacle")]


def seed(base_dir: str):
    os.makedirs(base_dir, exist_ok=True)
    for f in ("sad.db", "levels.db", "constants.db", "discreto.db"):
        p = os.path.join(base_dir, f)
        if os.path.exists(p):
            os.remove(p)
    fixtures = make_fixtures()
    names = dict(TEAMS)

    # ---- sad.db -----------------------------------------------------------
    sad = sqlite3.connect(os.path.join(base_dir, "sad.db"))
    sad.executescript("""
        CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT, country TEXT, founded INTEGER, logo TEXT);
        CREATE TABLE leagues (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
        CREATE TABLE fixtures (
            id INTEGER PRIMARY KEY, referee TEXT, timezone TEXT, date DATETIME, timestamp INTEGER,
            first_half_start INTEGER, second_half_start INTEGER, venue_id INTEGER, venue_name TEXT,
            venue_city TEXT, status_long TEXT, status_short TEXT, elapsed INTEGER,
            league_id INTEGER, league_season INTEGER, league_round TEXT,
            home_team_id INTEGER, away_team_id INTEGER, goals_home INTEGER, goals_away INTEGER,
            halftime_home INTEGER, halftime_away INTEGER, fulltime_home INTEGER, fulltime_away INTEGER,
            extratime_home INTEGER, extratime_away INTEGER, penalty_home INTEGER, penalty_away INTEGER);
        CREATE TABLE odds (id INTEGER PRIMARY KEY AUTOINCREMENT, fixture_id INTEGER, league_id INTEGER,
            bookmaker_id INTEGER, bookmaker_name TEXT, bet_id INTEGER, bet_name TEXT, value TEXT, odd REAL);
    """)
    sad.executemany("INSERT INTO teams (id, name, country) VALUES (?,?, 'Spain')", TEAMS)
    sad.execute("INSERT INTO leagues (id, name, country) VALUES (?, 'LaLiga', 'Spain')", (LEAGUE_ID,))
    for f in fixtures:
        sad.execute(
            """INSERT INTO fixtures (id, date, venue_name, status_long, status_short, elapsed,
               league_id, league_season, home_team_id, away_team_id, goals_home, goals_away)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f["id"], f["date"].strftime("%Y-%m-%d %H:%M:%S"), f"Estadio {names[f['home']]}",
             f["status_long"], f["status_short"], f["elapsed"], LEAGUE_ID, SEASON,
             f["home"], f["away"], f["gh"], f["ga"]),
        )
    # cuotas para el vivo y el programado (3 bookmakers, con dispersión)
    for f in fixtures[-2:]:
        for bid, bname in BOOKMAKERS:
            rng = random.Random(f"{f['id']}|{bid}")
            for bet_id, (bet_name, sels) in enumerate(ODDS_MARKETS, start=1):
                for value, base in sels:
                    sad.execute(
                        "INSERT INTO odds (fixture_id, league_id, bookmaker_id, bookmaker_name, bet_id, bet_name, value, odd) VALUES (?,?,?,?,?,?,?,?)",
                        (f["id"], LEAGUE_ID, bid, bname, bet_id, bet_name, value,
                         round(base * (0.94 + rng.random() * 0.12), 2)),
                    )
    sad.commit()
    sad.close()

    # ---- pipeline: niveles → constantes → discreto ------------------------
    finished = [f for f in fixtures if f["status_long"] == "Match Finished"]
    hist = {tid: [] for tid, _ in TEAMS}
    for f in sorted(finished, key=lambda x: x["date"]):
        hist[f["home"]].append(dict(fixture_id=f["id"], date=f["date"], rival=f["away"], is_local=True, gf=f["gh"], ga=f["ga"]))
        hist[f["away"]].append(dict(fixture_id=f["id"], date=f["date"], rival=f["home"], is_local=False, gf=f["ga"], ga=f["gh"]))

    levels_by_team = {tid: compute_levels(h) for tid, h in hist.items()}

    lv = sqlite3.connect(os.path.join(base_dir, "levels.db"))
    lv.executescript("""CREATE TABLE team_levels (id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL,
        fixture_id INTEGER NOT NULL, date DATETIME NOT NULL, level REAL NOT NULL);""")
    for tid, h in hist.items():
        for m, level in zip(h, levels_by_team[tid]):
            lv.execute("INSERT INTO team_levels (team_id, fixture_id, date, level) VALUES (?,?,?,?)",
                       (tid, m["fixture_id"], m["date"].strftime("%Y-%m-%d %H:%M:%S"), level))
    lv.commit()
    lv.close()

    def rival_level_at(rival_id, date):
        h, lvls = hist[rival_id], levels_by_team[rival_id]
        dates = [m["date"] for m in h]
        i = bisect_right(dates, date) - 1
        return lvls[i] if i >= 0 else 1.0  # fallback 1.0 (§3.1)

    co = sqlite3.connect(os.path.join(base_dir, "constants.db"))
    co.executescript("""CREATE TABLE constants (id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL,
        fixture_id INTEGER NOT NULL, date DATETIME NOT NULL,
        q_local REAL, q_visita REAL, q_negativo REAL, q_goles_anotado REAL, q_goles_recibido REAL,
        q_goles_local_anotado REAL, q_goles_local_recibido REAL, q_goles_visita_anotado REAL, q_goles_visita_recibido REAL,
        k_positivo REAL, k_negativo REAL, k_positivo_local REAL, k_negativo_local REAL,
        k_positivo_visita REAL, k_negativo_visita REAL, k_goles_anotado REAL, k_goles_recibido REAL,
        k_goles_local_anotado REAL, k_goles_local_recibido REAL, k_goles_visita_anotado REAL, k_goles_visita_recibido REAL);
        CREATE INDEX ix_constants_team_date ON constants(team_id, date);""")
    di = sqlite3.connect(os.path.join(base_dir, "discreto.db"))
    di.executescript("""CREATE TABLE processed_matches (id INTEGER PRIMARY KEY, fecha DATETIME NOT NULL,
        fixture_id INTEGER NOT NULL, equipo_id INTEGER NOT NULL, equipo_nombre TEXT NOT NULL,
        rival_id INTEGER NOT NULL, rival_nombre TEXT NOT NULL, condicion TEXT, status_long TEXT,
        league_id INTEGER, league_season TEXT, goals_home INTEGER, goals_away INTEGER,
        nivel_equipo INTEGER, nivel_rival INTEGER,
        k REAL, k_local REAL, k_visita REAL, k_goles_anotado REAL, k_goles_recibido REAL,
        k_goles_local_anotado REAL, k_goles_local_recibido REAL, k_goles_visita_anotado REAL, k_goles_visita_recibido REAL,
        processed_at DATETIME, UNIQUE(fixture_id, equipo_id));""")

    now_txt = datetime(2026, 7, 2, 20, 30, 0).strftime("%Y-%m-%d %H:%M:%S")
    for tid, h in hist.items():
        k = dict(K0)
        for idx, m in enumerate(h):
            nivel_rival = rival_level_at(m["rival"], m["date"])
            q, k = step_k(k, m["is_local"], m["gf"], m["ga"], nivel_rival)
            co.execute(
                """INSERT INTO constants (team_id, fixture_id, date,
                   q_local, q_visita, q_negativo, q_goles_anotado, q_goles_recibido,
                   q_goles_local_anotado, q_goles_local_recibido, q_goles_visita_anotado, q_goles_visita_recibido,
                   k_positivo, k_negativo, k_positivo_local, k_negativo_local,
                   k_positivo_visita, k_negativo_visita, k_goles_anotado, k_goles_recibido,
                   k_goles_local_anotado, k_goles_local_recibido, k_goles_visita_anotado, k_goles_visita_recibido)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tid, m["fixture_id"], m["date"].strftime("%Y-%m-%d %H:%M:%S"),
                 q["q_local"], q["q_visita"], q["q_negativo"], q["q_goles_anotado"], q["q_goles_recibido"],
                 q["q_goles_local_anotado"], q["q_goles_local_recibido"], q["q_goles_visita_anotado"], q["q_goles_visita_recibido"],
                 k["k_positivo"], k["k_negativo"], k["k_positivo_local"], k["k_negativo_local"],
                 k["k_positivo_visita"], k["k_negativo_visita"], k["k_goles_anotado"], k["k_goles_recibido"],
                 k["k_goles_local_anotado"], k["k_goles_local_recibido"], k["k_goles_visita_anotado"], k["k_goles_visita_recibido"]),
            )
            di.execute(
                """INSERT INTO processed_matches (fecha, fixture_id, equipo_id, equipo_nombre, rival_id, rival_nombre,
                   condicion, status_long, league_id, league_season, goals_home, goals_away, nivel_equipo, nivel_rival,
                   k, k_local, k_visita, k_goles_anotado, k_goles_recibido,
                   k_goles_local_anotado, k_goles_local_recibido, k_goles_visita_anotado, k_goles_visita_recibido, processed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (m["date"].strftime("%Y-%m-%d %H:%M:%S"), m["fixture_id"], tid, names[tid], m["rival"], names[m["rival"]],
                 "Local" if m["is_local"] else "Visita", "Match Finished", LEAGUE_ID, str(SEASON),
                 m["gf"] if m["is_local"] else m["ga"], m["ga"] if m["is_local"] else m["gf"],
                 level_bin(levels_by_team[tid][idx]), level_bin(nivel_rival),
                 k["k_positivo"] + k["k_negativo"], k["k_positivo_local"] + k["k_negativo_local"],
                 k["k_positivo_visita"] + k["k_negativo_visita"], k["k_goles_anotado"], k["k_goles_recibido"],
                 k["k_goles_local_anotado"], k["k_goles_local_recibido"],
                 k["k_goles_visita_anotado"], k["k_goles_visita_recibido"], now_txt),
            )
    co.commit()
    co.close()
    di.commit()
    di.close()
    print(f"Demo lista en {base_dir}: {len(fixtures)} fixtures ({len(finished)} terminados) · {len(TEAMS)} equipos")


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "demo_data"))
