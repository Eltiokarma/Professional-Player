"""Acceso de SOLO LECTURA a las 4 SQLite del pipeline SAD.

El backend no escribe nada: la app de escritorio / el pipeline siguen siendo
los únicos dueños de sad.db → levels.db → constants.db → discreto.db.
Las rutas se resuelven en SAD_DATA_DIR (por defecto, la raíz del proyecto,
que es donde database_manager.py las crea).
"""
import os
import sqlite3

BASE_DIR = os.environ.get(
    "SAD_DATA_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

DB_FILES = {
    "sad": "sad.db",
    "levels": "levels.db",
    "constants": "constants.db",
    "discreto": "discreto.db",
}


def db_path(name: str) -> str:
    return os.path.join(BASE_DIR, DB_FILES[name])


def connect(name: str) -> sqlite3.Connection:
    """Conexión de solo lectura (uri mode=ro) con filas tipo dict."""
    path = db_path(name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No existe {path} — ejecuta el pipeline o backend/seed_demo.py")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def query(name: str, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    conn = connect(name)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def query_one(name: str, sql: str, params: tuple = ()):
    rows = query(name, sql, params)
    return rows[0] if rows else None
