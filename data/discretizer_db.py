# src/data/discretizer_db.py
import pandas as pd
import numpy as np
from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime,
    Index, text, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sklearn.preprocessing import KBinsDiscretizer
from datetime import datetime
import logging
from data.database_manager import ORIG_ENGINE, CONST_ENGINE, BASE_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("src.data.discretizer_db")

Base = declarative_base()


class ProcessedMatch(Base):
    __tablename__ = 'processed_matches'

    id = Column(Integer, primary_key=True)
    fecha = Column(DateTime, nullable=False)
    fixture_id = Column(Integer, nullable=False)
    equipo_id = Column(Integer, nullable=False)
    equipo_nombre = Column(String, nullable=False)
    rival_id = Column(Integer, nullable=False)
    rival_nombre = Column(String, nullable=False)
    condicion = Column(String)
    status_long = Column(String)

    league_id = Column(Integer)
    league_season = Column(String)
    goals_home = Column(Integer)
    goals_away = Column(Integer)

    nivel_equipo = Column(Integer)
    nivel_rival = Column(Integer)

    k = Column(Float)
    k_local = Column(Float)
    k_visita = Column(Float)
    k_goles_anotado = Column(Float)
    k_goles_recibido = Column(Float)
    k_goles_local_anotado = Column(Float)
    k_goles_local_recibido = Column(Float)
    k_goles_visita_anotado = Column(Float)
    k_goles_visita_recibido = Column(Float)

    processed_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_fecha_equipo', 'fecha', 'equipo_id'),
        Index('idx_status', 'status_long'),
        Index('idx_fixture', 'fixture_id'),
        Index('idx_league', 'league_id'),
        UniqueConstraint('fixture_id', 'equipo_id', name='uq_fixture_equipo'),
    )


class DiscreteDBProcessor:
    def __init__(self):
        # Ajusta rutas si corresponde
        self.sad_engine = ORIG_ENGINE          # Ya existe
        self.constants_engine = CONST_ENGINE   # Ya existe
        self.levels_engine = create_engine(f'sqlite:///{BASE_DIR}/levels.db', future=True)
        self.discreto_engine = create_engine(f'sqlite:///{BASE_DIR}/discreto.db', future=True)

        # Crear tablas
        Base.metadata.create_all(self.discreto_engine)

        # Sesión
        Session = sessionmaker(bind=self.discreto_engine, future=True)
        self.discreto_session = Session()

        self.discretizer = None

        # Pequeña mejora en sqlite
        for eng in (self.sad_engine, self.constants_engine, self.levels_engine, self.discreto_engine):
            with eng.connect() as conn:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL;")

    def get_last_processed_date(self, equipo_id: int):
        row = self.discreto_session.query(ProcessedMatch.fecha)\
            .filter(ProcessedMatch.equipo_id == equipo_id)\
            .order_by(ProcessedMatch.fecha.desc())\
            .first()
        return row[0] if row else None

    def load_all_levels(self):
        logger.info("Cargando todos los niveles para discretización...")
        q = text("SELECT level FROM team_levels WHERE level IS NOT NULL")
        with self.levels_engine.connect() as conn:
            df = pd.read_sql_query(q, conn)
        if df.empty:
            raise ValueError("No se encontraron niveles en la base de datos levels.db")
        return df['level'].values.reshape(-1, 1)

    def create_discretizer(self):
        if self.discretizer is None:
            all_levels = self.load_all_levels()
            self.discretizer = KBinsDiscretizer(n_bins=10, encode='ordinal', strategy='uniform')
            self.discretizer.fit(all_levels)
            logger.info("Discretizador creado correctamente")

    @staticmethod
    def _parse_fecha(v):
        if isinstance(v, str):
            if '.' in v:
                v = v.split('.')[0]
            try:
                return datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    # fallback ISO
                    return datetime.fromisoformat(v)
                except Exception:
                    return None
        return v

    def _read_matches_for_team(self, team_id: int, team_name: str, last_date: datetime) -> pd.DataFrame:
        # Construimos SQL parametrizado (nada de f-strings con nombres)
        base = """
        WITH matches_data AS (
            SELECT
                f.id AS fixture_id,
                f.date AS fecha,
                f.league_id,
                f.league_season,
                f.goals_home,
                f.goals_away,
                :team_id AS equipo_id,
                :team_name AS equipo_nombre,
                CASE WHEN f.home_team_id = :team_id THEN f.away_team_id ELSE f.home_team_id END AS rival_id,
                CASE WHEN f.home_team_id = :team_id THEN at.name ELSE ht.name END AS rival_nombre,
                CASE WHEN f.home_team_id = :team_id THEN 'Local' ELSE 'Visita' END AS condicion,
                f.status_long
            FROM fixtures f
            JOIN teams ht ON f.home_team_id = ht.id
            JOIN teams at ON f.away_team_id = at.id
            WHERE (f.home_team_id = :team_id OR f.away_team_id = :team_id)
              AND f.status_long = 'Match Finished'
              {date_clause}
        )
        SELECT * FROM matches_data
        """
        date_clause = "AND f.date > :last_date" if last_date else ""
        sql = text(base.format(date_clause=date_clause))
        params = {"team_id": team_id, "team_name": team_name}
        if last_date:
            # sqlite soporta ISO sin TZ
            params["last_date"] = last_date.strftime('%Y-%m-%d %H:%M:%S')

        with self.sad_engine.connect() as conn:
            df = pd.read_sql_query(sql, conn, params=params)

        if not df.empty:
            df['fecha'] = df['fecha'].apply(self._parse_fecha)
        return df

    @staticmethod
    def _mk_in_params(prefix: str, values):
        """Crea placeholders (:prefix0,:prefix1,...) y dict de params."""
        values = list(values)
        placeholders = []
        params = {}
        for i, val in enumerate(values):
            key = f"{prefix}{i}"
            placeholders.append(f":{key}")
            params[key] = val
        return placeholders, params

    def _read_constants_for_fixtures(self, team_id: int, fixture_ids: list) -> pd.DataFrame:
        if not fixture_ids:
            return pd.DataFrame()

        ph, p = self._mk_in_params("fid_", fixture_ids)
        sql = text(f"""
            SELECT fixture_id,
                   k_positivo, k_negativo,
                   k_positivo_local, k_negativo_local,
                   k_positivo_visita, k_negativo_visita,
                   k_goles_anotado, k_goles_recibido,
                   k_goles_local_anotado, k_goles_local_recibido,
                   k_goles_visita_anotado, k_goles_visita_recibido
            FROM constants
            WHERE team_id = :team_id AND fixture_id IN ({",".join(ph)})
        """)
        params = {"team_id": team_id, **p}
        with self.constants_engine.connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def _read_level_single(self, team_id: int, fixture_id: int, fecha_dt: datetime):
        """Busca nivel exacto por fixture; si no hay, toma el último <= fecha."""
        sql_exact = text("""
            SELECT level FROM team_levels
            WHERE team_id = :tid AND fixture_id = :fid
            LIMIT 1
        """)
        sql_prev = text("""
            SELECT level FROM team_levels
            WHERE team_id = :tid AND date <= :fdt
            ORDER BY date DESC
            LIMIT 1
        """)
        with self.levels_engine.connect() as conn:
            df = pd.read_sql_query(sql_exact, conn, params={"tid": team_id, "fid": fixture_id})
            if not df.empty:
                return float(df['level'].iloc[0])
            # fallback por fecha
            fdt = (fecha_dt.strftime('%Y-%m-%d %H:%M:%S') if isinstance(fecha_dt, datetime) else None)
            df2 = pd.read_sql_query(sql_prev, conn, params={"tid": team_id, "fdt": fdt})
        if not df2.empty:
            return float(df2['level'].iloc[0])
        return 0.5  # sentinela

    def process_team_data(self, team_id: int, team_name: str) -> int:
        try:
            last_date = None
            if last_date:
                logger.info(f"Procesando equipo {team_name} desde {last_date}")
            else:
                logger.info(f"Procesando equipo {team_name} por primera vez")

            df_matches = self._read_matches_for_team(team_id, team_name, last_date)
            if df_matches.empty:
                logger.info(f"No hay nuevos partidos para {team_name}")
                return 0

            fixture_ids = df_matches['fixture_id'].tolist()
            df_const = self._read_constants_for_fixtures(team_id, fixture_ids)

            df = df_matches.merge(df_const, on='fixture_id', how='left')

            # Niveles (per-row fallback; se puede vectorizar luego)
            niveles_equipo = []
            niveles_rival = []
            for _, row in df.iterrows():
                f_id = int(row['fixture_id'])
                fecha_dt = row['fecha']
                niveles_equipo.append(self._read_level_single(team_id, f_id, fecha_dt))
                niveles_rival.append(self._read_level_single(int(row['rival_id']), f_id, fecha_dt))
            df['nivel_equipo_raw'] = niveles_equipo
            df['nivel_rival_raw'] = niveles_rival

            # Discretizar niveles
            if self.discretizer is None:
                self.create_discretizer()

            df['nivel_equipo'] = self.discretizer.transform(
                df['nivel_equipo_raw'].values.reshape(-1, 1)
            ).astype(int)
            df['nivel_rival'] = self.discretizer.transform(
                df['nivel_rival_raw'].values.reshape(-1, 1)
            ).astype(int)

            # Fusionar k
            def fsum(a, b):
                a = 0.0 if pd.isna(a) else float(a)
                b = 0.0 if pd.isna(b) else float(b)
                return a + b

            df['k'] = [fsum(a, b) for a, b in zip(df.get('k_positivo'), df.get('k_negativo'))]
            df['k_local'] = [fsum(a, b) for a, b in zip(df.get('k_positivo_local'), df.get('k_negativo_local'))]
            df['k_visita'] = [fsum(a, b) for a, b in zip(df.get('k_positivo_visita'), df.get('k_negativo_visita'))]

            # Insert seguro (ON CONFLICT DO NOTHING)
            insert_sql = text("""
                INSERT INTO processed_matches (
                    fecha, fixture_id, equipo_id, equipo_nombre, rival_id, rival_nombre,
                    condicion, status_long, league_id, league_season, goals_home, goals_away,
                    nivel_equipo, nivel_rival, k, k_local, k_visita,
                    k_goles_anotado, k_goles_recibido,
                    k_goles_local_anotado, k_goles_local_recibido,
                    k_goles_visita_anotado, k_goles_visita_recibido, processed_at
                ) VALUES (
                    :fecha, :fixture_id, :equipo_id, :equipo_nombre, :rival_id, :rival_nombre,
                    :condicion, :status_long, :league_id, :league_season, :goals_home, :goals_away,
                    :nivel_equipo, :nivel_rival, :k, :k_local, :k_visita,
                    :k_goles_anotado, :k_goles_recibido,
                    :k_goles_local_anotado, :k_goles_local_recibido,
                    :k_goles_visita_anotado, :k_goles_visita_recibido, :processed_at
                )
                ON CONFLICT(fixture_id, equipo_id) DO NOTHING
            """)

            rows = []
            for _, r in df.iterrows():
                rows.append({
                    "fecha": r['fecha'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(r['fecha'], datetime) else None,
                    "fixture_id": int(r['fixture_id']),
                    "equipo_id": int(r['equipo_id']),
                    "equipo_nombre": str(r['equipo_nombre']),
                    "rival_id": int(r['rival_id']),
                    "rival_nombre": str(r['rival_nombre']),
                    "condicion": str(r['condicion']),
                    "status_long": str(r['status_long']),
                    "league_id": int(r['league_id']) if not pd.isna(r['league_id']) else None,
                    "league_season": '' if pd.isna(r.get('league_season')) else str(r.get('league_season')),
                    "goals_home": int(r['goals_home']) if not pd.isna(r['goals_home']) else None,
                    "goals_away": int(r['goals_away']) if not pd.isna(r['goals_away']) else None,
                    "nivel_equipo": int(r['nivel_equipo']),
                    "nivel_rival": int(r['nivel_rival']),
                    "k": float(r['k']) if not pd.isna(r['k']) else 0.0,
                    "k_local": float(r['k_local']) if not pd.isna(r['k_local']) else 0.0,
                    "k_visita": float(r['k_visita']) if not pd.isna(r['k_visita']) else 0.0,
                    "k_goles_anotado": float(r['k_goles_anotado']) if not pd.isna(r.get('k_goles_anotado')) else 0.0,
                    "k_goles_recibido": float(r['k_goles_recibido']) if not pd.isna(r.get('k_goles_recibido')) else 0.0,
                    "k_goles_local_anotado": float(r['k_goles_local_anotado']) if not pd.isna(r.get('k_goles_local_anotado')) else 0.0,
                    "k_goles_local_recibido": float(r['k_goles_local_recibido']) if not pd.isna(r.get('k_goles_local_recibido')) else 0.0,
                    "k_goles_visita_anotado": float(r['k_goles_visita_anotado']) if not pd.isna(r.get('k_goles_visita_anotado')) else 0.0,
                    "k_goles_visita_recibido": float(r['k_goles_visita_recibido']) if not pd.isna(r.get('k_goles_visita_recibido')) else 0.0,
                    "processed_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                })

            inserted = 0
            with self.discreto_engine.begin() as conn:
                for params in rows:
                    conn.execute(insert_sql, params)
                    inserted += 1
            logger.info(f"Insertados {inserted} registros para {team_name}")
            return inserted

        except Exception as e:
            logger.error(f"Error procesando equipo {team_name}: {e}")
            self.discreto_session.rollback()
            return 0

    def process_all_teams(self):
        logger.info("Iniciando procesamiento de todos los equipos...")

        self.create_discretizer()

        teams_query = text("""
        SELECT DISTINCT t.id, t.name
        FROM teams t
        WHERE EXISTS (
            SELECT 1 FROM fixtures f
            WHERE (f.home_team_id = t.id OR f.away_team_id = t.id)
              AND f.status_long = 'Match Finished'
        )
        ORDER BY t.name
        """)
        with self.sad_engine.connect() as conn:
            df_teams = pd.read_sql_query(teams_query, conn)

        logger.info(f"Encontrados {len(df_teams)} equipos para procesar")

        total = 0
        for _, team in df_teams.iterrows():
            try:
                total += self.process_team_data(int(team['id']), str(team['name']))
            except Exception as e:
                logger.error(f"Error procesando equipo {team['name']}: {e}")
                continue

        logger.info(f"Procesamiento completado. Total de registros procesados: {total}")

    def close(self):
        self.discreto_session.close()


def update_discrete_db():
    processor = DiscreteDBProcessor()
    try:
        processor.process_all_teams()
    finally:
        processor.close()


if __name__ == "__main__":
    update_discrete_db()
