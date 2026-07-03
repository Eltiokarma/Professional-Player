"""SAD API — backend FastAPI de solo lectura sobre el pipeline SQLite.

Implementa el contrato docs/openapi.yaml del repo App-Profesional-de-Apuestas
(el frontend web lo consume con VITE_DATA_SOURCE=http). v0: sin escrituras,
sin auth (bearer opcional llega en fase 2), CORS abierto configurable.

Ejecutar junto a las DBs reales:
    uvicorn backend.app:app --port 8000
"""
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend import db

app = FastAPI(title="SAD API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("SAD_CORS_ORIGINS", "*").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)

API = "/api/v1"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

LIVE_SHORT = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"}
FIN_SHORT = {"FT", "AET", "PEN", "AWD", "WO"}

# Bins fijos v6 (Ley del Marcador) — mismos umbrales que el discretizador
BINS = [
    (0.6, "Sin datos"), (1.3, "Muy débil"), (1.6, "Débil"), (1.9, "Regular bajo"),
    (2.1, "Promedio bajo"), (2.35, "Promedio"), (2.55, "Promedio alto"),
    (2.85, "Fuerte"), (3.2, "Muy fuerte"), (float("inf"), "Élite"),
]

# Ley de la Regresión al Nivel (§5) — coeficientes de regresion_nivel_engine.py
MU = {"intercept": 1.110, "nivel": 0.686, "rival": -0.669, "localia": 0.422}
RECENT_WINDOW = 5


def level_bin(level: float) -> tuple[int, str]:
    for i, (mx, label) in enumerate(BINS):
        if level < mx:
            return i, label
    return 9, "Élite"


def mu(nivel: float, nivel_rival: float, localia: float) -> float:
    v = MU["intercept"] + MU["nivel"] * nivel + MU["rival"] * nivel_rival + MU["localia"] * localia
    return max(0.0, min(3.0, v))


def iso(dt_text) -> str:
    """Normaliza el DATETIME de SQLite a ISO-8601 con 'T' (y Z si es naive)."""
    if dt_text is None:
        return ""
    s = str(dt_text).replace(" ", "T")
    if "." in s:
        s = s.split(".")[0]
    if not s.endswith("Z") and "+" not in s[10:]:
        s += "Z"
    return s


def abrev(nombre: str) -> str:
    return (nombre or "???").replace(" ", "")[:3].upper()


def equipo_dto(team_id: int, nombre: str) -> dict:
    return {"id": team_id, "nombre": nombre, "abreviatura": abrev(nombre)}


def estado_de(status_short, status_long) -> str:
    ss = (status_short or "").upper()
    if ss in LIVE_SHORT:
        return "en_vivo"
    if ss in FIN_SHORT or (status_long or "") == "Match Finished":
        return "finalizado"
    return "programado"


def liga_nombre(league_id) -> str:
    try:
        row = db.query_one("sad", "SELECT name FROM leagues WHERE id=?", (league_id,))
        if row and row["name"]:
            return row["name"]
    except Exception:
        pass  # la tabla leagues puede no existir en DBs antiguas
    return f"Liga {league_id}"


def fixture_dto(f) -> dict:
    estado = estado_de(f["status_short"], f["status_long"])
    return {
        "id": f["id"],
        "fecha": iso(f["date"]),
        "ligaId": f["league_id"] or 0,
        "liga": liga_nombre(f["league_id"]),
        "temporada": f["league_season"] or 0,
        "estado": estado,
        "minuto": f["elapsed"] if estado == "en_vivo" else None,
        "estadio": f["venue_name"] or "",
        "local": equipo_dto(f["home_team_id"], f["home_name"]),
        "visitante": equipo_dto(f["away_team_id"], f["away_name"]),
        "golesLocal": f["goals_home"] if estado != "programado" else None,
        "golesVisitante": f["goals_away"] if estado != "programado" else None,
    }


FIXTURE_SQL = """
SELECT f.id, f.date, f.status_long, f.status_short, f.elapsed,
       f.league_id, f.league_season, f.venue_name,
       f.goals_home, f.goals_away,
       f.home_team_id, ht.name AS home_name,
       f.away_team_id, at.name AS away_name
FROM fixtures f
JOIN teams ht ON ht.id = f.home_team_id
JOIN teams at ON at.id = f.away_team_id
"""


def get_fixture(fixture_id: int):
    row = db.query_one("sad", FIXTURE_SQL + " WHERE f.id=?", (fixture_id,))
    if not row:
        raise HTTPException(404, f"fixture {fixture_id} no existe")
    return row


def nivel_a_fecha(team_id: int, fecha_iso: str | None) -> float:
    """Último level con date <= fecha (0.5 si no hay registros — §2.3)."""
    if fecha_iso:
        row = db.query_one(
            "levels",
            "SELECT level FROM team_levels WHERE team_id=? AND date<=? ORDER BY date DESC, id DESC LIMIT 1",
            (team_id, fecha_iso.replace("T", " ").rstrip("Z")),
        )
    else:
        row = db.query_one(
            "levels",
            "SELECT level FROM team_levels WHERE team_id=? ORDER BY date DESC, id DESC LIMIT 1",
            (team_id,),
        )
    return float(row["level"]) if row else 0.5


def pts_recientes(team_id: int, antes_de: str | None) -> float | None:
    """Promedio de puntos en los últimos 5 terminados (None si no hay 5)."""
    cond, params = "", [team_id, team_id]
    if antes_de:
        cond = " AND f.date < ?"
        params.append(antes_de.replace("T", " ").rstrip("Z"))
    rows = db.query(
        "sad",
        f"""SELECT f.home_team_id, f.goals_home, f.goals_away
            FROM fixtures f
            WHERE (f.home_team_id=? OR f.away_team_id=?)
              AND f.status_long='Match Finished'
              AND f.goals_home IS NOT NULL AND f.goals_away IS NOT NULL{cond}
            ORDER BY f.date DESC LIMIT {RECENT_WINDOW}""",
        tuple(params),
    )
    if len(rows) < RECENT_WINDOW:
        return None
    pts = 0
    for r in rows:
        gf, ga = (r["goals_home"], r["goals_away"]) if r["home_team_id"] == team_id else (r["goals_away"], r["goals_home"])
        pts += 3 if gf > ga else 1 if gf == ga else 0
    return pts / RECENT_WINDOW


def gap_equipo(team_id: int, fecha: str | None) -> dict:
    nivel = nivel_a_fecha(team_id, fecha)
    recientes = pts_recientes(team_id, fecha)
    esperados = mu(nivel, 2.0, 0.5)  # rival promedio, localía neutra
    gap = None if recientes is None else esperados - recientes
    senal = None
    tendencia = None
    if gap is not None:
        a = abs(gap)
        senal = "fuerte" if a > 0.5 else "leve" if a >= 0.3 else "equilibrio"
        tendencia = None if gap == 0 else ("mejora" if gap > 0 else "empeora")
    return {
        "equipoId": team_id,
        "nivel": round(nivel, 4),
        "ptsRecientes": recientes,
        "ptsEsperados": round(esperados, 4),
        "gap": None if gap is None else round(gap, 4),
        "senal": senal,
        "tendencia": tendencia,
    }


def constantes_de(team_id: int, limit: int) -> list[dict]:
    consts = db.query(
        "constants",
        "SELECT * FROM constants WHERE team_id=? ORDER BY date DESC, id DESC LIMIT ?",
        (team_id, limit),
    )
    if not consts:
        return []
    fixture_ids = tuple(r["fixture_id"] for r in consts)
    marks = ",".join("?" * len(fixture_ids))
    pm_rows = db.query(
        "discreto",
        f"SELECT * FROM processed_matches WHERE equipo_id=? AND fixture_id IN ({marks})",
        (team_id, *fixture_ids),
    )
    pm = {r["fixture_id"]: r for r in pm_rows}
    out = []
    z = lambda v: float(v) if v is not None else 0.0  # noqa: E731
    for c in consts:
        p = pm.get(c["fixture_id"])
        if p:
            es_local = (p["condicion"] or "") == "Local"
            gf, ga = (p["goals_home"], p["goals_away"]) if es_local else (p["goals_away"], p["goals_home"])
            rival_id, rival_nombre = p["rival_id"], p["rival_nombre"]
            nivel_rival = float(p["nivel_rival"] if p["nivel_rival"] is not None else 0)
        else:  # fallback si el discretizador va por detrás de constants
            f = db.query_one("sad", FIXTURE_SQL + " WHERE f.id=?", (c["fixture_id"],))
            if not f:
                continue
            es_local = f["home_team_id"] == team_id
            gf, ga = (f["goals_home"], f["goals_away"]) if es_local else (f["goals_away"], f["goals_home"])
            rival_id = f["away_team_id"] if es_local else f["home_team_id"]
            rival_nombre = f["away_name"] if es_local else f["home_name"]
            nivel_rival = 0.0
        out.append(
            {
                "equipoId": team_id,
                "fixtureId": c["fixture_id"],
                "fecha": iso(c["date"]),
                "condicion": "Local" if es_local else "Visita",
                "rivalId": rival_id,
                "rivalNombre": rival_nombre,
                "nivelRival": nivel_rival,
                "golesFavor": gf or 0,
                "golesContra": ga or 0,
                "q": {
                    "local": c["q_local"],
                    "visita": c["q_visita"],
                    "negativo": z(c["q_negativo"]),
                    "golesAnotado": z(c["q_goles_anotado"]),
                    "golesRecibido": z(c["q_goles_recibido"]),
                },
                "k": {
                    "positivo": z(c["k_positivo"]),
                    "negativo": z(c["k_negativo"]),
                    "positivoLocal": z(c["k_positivo_local"]),
                    "negativoLocal": z(c["k_negativo_local"]),
                    "positivoVisita": z(c["k_positivo_visita"]),
                    "negativoVisita": z(c["k_negativo_visita"]),
                    "golesAnotado": z(c["k_goles_anotado"]),
                    "golesRecibido": z(c["k_goles_recibido"]),
                    "golesLocalAnotado": z(c["k_goles_local_anotado"]),
                    "golesLocalRecibido": z(c["k_goles_local_recibido"]),
                    "golesVisitaAnotado": z(c["k_goles_visita_anotado"]),
                    "golesVisitaRecibido": z(c["k_goles_visita_recibido"]),
                },
                # fusión §4.2: k = k⁺ + k⁻ (NULL→0); los k_goles pasan tal cual
                "fusion": {
                    "k": z(c["k_positivo"]) + z(c["k_negativo"]),
                    "kLocal": z(c["k_positivo_local"]) + z(c["k_negativo_local"]),
                    "kVisita": z(c["k_positivo_visita"]) + z(c["k_negativo_visita"]),
                    "golesAnotado": z(c["k_goles_anotado"]),
                    "golesRecibido": z(c["k_goles_recibido"]),
                    "golesLocalAnotado": z(c["k_goles_local_anotado"]),
                    "golesLocalRecibido": z(c["k_goles_local_recibido"]),
                    "golesVisitaAnotado": z(c["k_goles_visita_anotado"]),
                    "golesVisitaRecibido": z(c["k_goles_visita_recibido"]),
                },
            }
        )
    return out


def niveles_de(team_id: int, limit: int) -> list[dict]:
    rows = db.query(
        "levels",
        "SELECT fixture_id, date, level FROM team_levels WHERE team_id=? ORDER BY date DESC, id DESC LIMIT ?",
        (team_id, limit),
    )
    out = []
    for r in rows:
        b, label = level_bin(float(r["level"]))
        out.append(
            {
                "equipoId": team_id,
                "fixtureId": r["fixture_id"],
                "fecha": iso(r["date"]),
                "nivel": round(float(r["level"]), 4),
                "bin": b,
                "binEtiqueta": label,
            }
        )
    return out


# Mapeo bet_name/value de API-Football → mercados del contrato
def cuota_key(bet_name: str, value: str):
    b = (bet_name or "").lower()
    v = (value or "").strip()
    if "match winner" in b or b == "1x2":
        return {"Home": ("1x2", "1"), "Draw": ("1x2", "X"), "Away": ("1x2", "2")}.get(v)
    if "double chance" in b:
        return {"Home/Draw": ("dc", "1X"), "Home/Away": ("dc", "12"), "Draw/Away": ("dc", "X2")}.get(v)
    if "over/under" in b or b == "goals over/under":
        return {"Over 2.5": ("ou", "O"), "Under 2.5": ("ou", "U")}.get(v)
    if "both teams" in b:
        return {"Yes": ("btts", "Y"), "No": ("btts", "N")}.get(v)
    if "asian handicap" in b:
        if v.startswith("Home -0.5"):
            return ("ah", "H1")
        if v.startswith("Away +0.5"):
            return ("ah", "H2")
    return None


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@app.get(API + "/health")
def health():
    db_ok = True
    last_run = None
    try:
        for name in db.DB_FILES:
            db.query_one(name, "SELECT 1")
        row = db.query_one("discreto", "SELECT MAX(processed_at) AS m FROM processed_matches")
        last_run = iso(row["m"]) if row and row["m"] else None
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "version": app.version, "dbOk": db_ok, "lastPipelineRun": last_run}


@app.get(API + "/fixtures")
def fixtures(
    fecha: str | None = None,
    estado: str | None = None,
    ligaId: int | None = None,
    limit: int = Query(default=50, le=200),
):
    cond, params = [], []
    if fecha:
        cond.append("date(f.date)=?")
        params.append(fecha)
    if ligaId is not None:
        cond.append("f.league_id=?")
        params.append(ligaId)
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    rows = db.query("sad", FIXTURE_SQL + where + " ORDER BY f.date DESC LIMIT ?", (*params, limit))
    out = [fixture_dto(r) for r in rows]
    if estado:
        out = [f for f in out if f["estado"] == estado]
    return out


@app.get(API + "/fixtures/{fixture_id}")
def fixture(fixture_id: int):
    return fixture_dto(get_fixture(fixture_id))


@app.get(API + "/niveles/{equipo_id}")
def niveles(equipo_id: int, limit: int = Query(default=50, le=500)):
    return niveles_de(equipo_id, limit)


@app.get(API + "/constantes/{equipo_id}")
def constantes(equipo_id: int, limit: int = Query(default=50, le=500)):
    return constantes_de(equipo_id, limit)


@app.get(API + "/predicciones/{fixture_id}")
def prediccion(fixture_id: int):
    f = get_fixture(fixture_id)
    fecha = iso(f["date"])
    local = gap_equipo(f["home_team_id"], fecha)
    visitante = gap_equipo(f["away_team_id"], fecha)
    gap_diff = None
    if local["gap"] is not None and visitante["gap"] is not None:
        gap_diff = round(local["gap"] - visitante["gap"], 4)
    return {
        "fixtureId": fixture_id,
        "local": local,
        "visitante": visitante,
        "gapDiff": gap_diff,
        "generadoEn": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@app.get(API + "/analisis-prepartido/{fixture_id}")
def analisis_prepartido(fixture_id: int):
    f = get_fixture(fixture_id)
    home_id, away_id = f["home_team_id"], f["away_team_id"]
    niveles_h = niveles_de(home_id, 1)
    niveles_a = niveles_de(away_id, 1)
    const_h = constantes_de(home_id, 1)
    const_a = constantes_de(away_id, 1)
    pred = prediccion(fixture_id)

    def nv(rows, team_id):
        if rows:
            return rows[0]
        b, label = level_bin(0.5)
        return {"equipoId": team_id, "fixtureId": 0, "fecha": "", "nivel": 0.5, "bin": b, "binEtiqueta": label}

    nh, na = nv(niveles_h, home_id), nv(niveles_a, away_id)
    dir_ = lambda g: (  # noqa: E731
        "tiende a mejorar" if g["tendencia"] == "mejora" else "tiende a empeorar" if g["tendencia"] == "empeora" else "en equilibrio"
    )
    resumen = (
        f"{f['home_name']} (nivel {nh['nivel']:.2f}, {nh['binEtiqueta']}) recibe a "
        f"{f['away_name']} (nivel {na['nivel']:.2f}, {na['binEtiqueta']}). "
        f"Regresión al nivel: local {dir_(pred['local'])}, visitante {dir_(pred['visitante'])}."
    )
    return {
        "fixtureId": fixture_id,
        "niveles": {"local": nh, "visitante": na},
        "constantes": {"local": const_h[0] if const_h else None, "visitante": const_a[0] if const_a else None},
        "prediccion": pred,
        "resumen": resumen,
    }


@app.get(API + "/equipos/{equipo_id}/stats")
def equipo_stats(equipo_id: int):
    """Stats de temporada calculadas de los fixtures terminados (siempre al día).
    xG/posesión/tiros/córners quedan null en v0 (no se derivan de fixtures)."""
    team = db.query_one("sad", "SELECT id, name FROM teams WHERE id=?", (equipo_id,))
    if not team:
        raise HTTPException(404, f"equipo {equipo_id} no existe")
    rows = db.query(
        "sad",
        """SELECT home_team_id, goals_home, goals_away FROM fixtures
           WHERE (home_team_id=? OR away_team_id=?)
             AND status_long='Match Finished'
             AND goals_home IS NOT NULL AND goals_away IS NOT NULL
           ORDER BY date DESC""",
        (equipo_id, equipo_id),
    )
    pts = gf_tot = gc_tot = 0
    forma = []
    for i, r in enumerate(rows):
        gf, ga = (r["goals_home"], r["goals_away"]) if r["home_team_id"] == equipo_id else (r["goals_away"], r["goals_home"])
        res = "W" if gf > ga else "D" if gf == ga else "L"
        pts += 3 if res == "W" else 1 if res == "D" else 0
        gf_tot += gf
        gc_tot += ga
        if i < RECENT_WINDOW:
            forma.append(res)  # más reciente primero
    pj = len(rows)
    return {
        "equipoId": equipo_id,
        "nombre": team["name"],
        "partidosJugados": pj,
        "puntos": pts,
        "forma": forma,
        "golesFavorProm": round(gf_tot / pj, 2) if pj else 0,
        "golesContraProm": round(gc_tot / pj, 2) if pj else 0,
        "xgProm": None,
        "posesionProm": None,
        "tirosPuertaProm": None,
        "cornersProm": None,
    }


@app.get(API + "/ligas/{liga_id}/standings")
def standings(liga_id: int, temporada: int | None = None):
    """Tabla de posiciones calculada de los fixtures terminados de la liga."""
    if temporada is None:
        row = db.query_one("sad", "SELECT MAX(league_season) AS s FROM fixtures WHERE league_id=?", (liga_id,))
        temporada = row["s"] if row and row["s"] is not None else 0
    rows = db.query(
        "sad",
        """SELECT f.home_team_id, f.away_team_id, f.goals_home, f.goals_away,
                  ht.name AS home_name, at.name AS away_name
           FROM fixtures f
           JOIN teams ht ON ht.id=f.home_team_id JOIN teams at ON at.id=f.away_team_id
           WHERE f.league_id=? AND f.league_season=? AND f.status_long='Match Finished'
             AND f.goals_home IS NOT NULL AND f.goals_away IS NOT NULL""",
        (liga_id, temporada),
    )
    acc: dict[int, dict] = {}

    def upsert(tid, nombre, gf, ga):
        e = acc.setdefault(tid, {"equipoId": tid, "nombre": nombre, "puntos": 0, "partidosJugados": 0, "golesFavor": 0, "golesContra": 0})
        e["partidosJugados"] += 1
        e["golesFavor"] += gf
        e["golesContra"] += ga
        e["puntos"] += 3 if gf > ga else 1 if gf == ga else 0

    for r in rows:
        upsert(r["home_team_id"], r["home_name"], r["goals_home"], r["goals_away"])
        upsert(r["away_team_id"], r["away_name"], r["goals_away"], r["goals_home"])
    tabla = sorted(acc.values(), key=lambda e: (-e["puntos"], -(e["golesFavor"] - e["golesContra"]), -e["golesFavor"], e["nombre"]))
    return [{"posicion": i + 1, **e} for i, e in enumerate(tabla)]


@app.get(API + "/cuotas/{fixture_id}")
def cuotas(fixture_id: int):
    rows = db.query(
        "sad",
        "SELECT bet_name, value, odd FROM odds WHERE fixture_id=? AND odd IS NOT NULL",
        (fixture_id,),
    )
    acc: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        key = cuota_key(r["bet_name"], r["value"])
        if key:
            acc.setdefault(key, []).append(float(r["odd"]))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        {
            "fixtureId": fixture_id,
            "mercado": mercado,
            "seleccion": seleccion,
            "cuota": round(sum(v) / len(v), 2),  # media entre bookmakers
            "actualizadoEn": now,
        }
        for (mercado, seleccion), v in sorted(acc.items())
    ]
