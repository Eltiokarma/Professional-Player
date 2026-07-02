#utils/models.py
# -*- coding: utf-8 -*-
"""
global_constant_predictor.py

Entrena modelos *globales* (usando múltiples ligas) por cada constante (k, k_local, k_visita, k_goles_*)
con filtros por status/fechas/ligas, e incluye la liga como variable categórica (OneHotEncoder).

Características clave:
- Carga datos desde una base SQLite (.db). Detecta automáticamente la(s) tabla(s) que contengan
  las columnas mínimas esperadas y concatena si hay varias.
- Limpieza y normalización: nombres (strip+upper), condición (LOCAL/VISITANTE/NEUTRAL), fechas,
  eliminación de duplicados exactos por (Equipo, Rival, Fecha, Liga).
- Construcción de variables previas/futuras con restricción opcional a misma liga.
  - Si el equipo NO tiene partido previo ⇒ descarta el sample.
  - Si el rival NO tiene partido previo ⇒ usa sentinelas -1 + flag prev_rival_hist_missing=1.
  - Si no hay partido futuro ⇒ usa sentinelas -1 + flags future_*_missing=1.
- Bug fix goles: para constantes k_goles_(local|visita)_(anotado|recibido) intenta mapear al
  base_col "k_goles_{anotado|recibido}" vía regex. Si no existe, usa el nombre literal.
- Pipeline sklearn: ColumnTransformer(OneHot liga) + RandomForest(class_weight='balanced').
  Búsqueda de hiperparámetros con CV estratificada dinámica y métrica macro-F1.
- Persistencia por constante en model_exports/global/:
  - global_{key}.joblib (pipeline completo)
  - params_{key}.json (hiperparámetros, clases, orden de features, métricas, fecha, n_samples)
- Predicción: recibe los features (incluye league_code) y devuelve % de incremento/mantiene/decremento.

Ejemplo mínimo de uso en main() al final de este archivo.
"""

from __future__ import annotations

import os
import re
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.metrics import f1_score, accuracy_score

import joblib


# ------------------------------- Configuración de logging --------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'global_training_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log', encoding="utf-8")
    ],
)
logger = logging.getLogger(__name__)


# ------------------------------- Utilidades de compatibilidad ------------------------------ #

def _safe_ohe(**kwargs) -> OneHotEncoder:
    """
    Crea OneHotEncoder(handle_unknown='ignore') con salida densa.
    Maneja compatibilidad entre versiones (sparse_output vs sparse).
    """
    params = dict(handle_unknown='ignore')
    # Preferimos denso para que el ColumnTransformer pueda devolver DataFrame con nombres
    try:
        # sklearn >= 1.2
        params["sparse_output"] = False
        return OneHotEncoder(**params, **kwargs)
    except TypeError:
        # sklearn < 1.2
        params["sparse"] = False
        return OneHotEncoder(**params, **kwargs)


class ColumnTransformerWithNames(ColumnTransformer):
    """
    Wrapper de ColumnTransformer que intenta devolver DataFrame con nombres de columnas.

    Si la versión de sklearn soporta set_output(transform='pandas'), lo usa;
    de lo contrario, reconstruye un DataFrame a mano a partir de get_feature_names_out().
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def set_pandas_output(self):
        try:
            # sklearn >= 1.2
            self.set_output(transform="pandas")
            return True
        except Exception:
            return False

    def transform(self, X):
        out = super().transform(X)
        # Si ya es DataFrame (por set_output), retornarlo directamente
        if isinstance(out, pd.DataFrame):
            return out
        # Intentar construir DataFrame con nombres
        try:
            cols = self.get_feature_names_out()
        except Exception:
            cols = [f"f{i}" for i in range(out.shape[1])]
        # Convertir sparse a denso si aplica
        if hasattr(out, "toarray"):
            out = out.toarray()
        return pd.DataFrame(out, columns=cols, index=getattr(X, "index", None))


# ---------------------------------- Clase principal --------------------------------------- #

class GlobalConstantPredictor:
    """
    Entrena y utiliza modelos globales por constante, agregando liga como variable categórica.

    Métodos principales:
    - train_global(...): Entrena y persiste un pipeline por constante.
    - predict(...): Realiza inferencia con un pipeline cargado.
    - load_models(directory): Carga pipelines previamente guardados.
    """

    # Constantes canónicas a procesar (claves del modelo)
    CANONICAL_CONSTANTS: List[str] = [
        "k",
        "k_local",
        "k_visita",
        "k_goles_anotado",
        "k_goles_recibido",
        "k_goles_local_anotado",
        "k_goles_local_recibido",
        "k_goles_visita_anotado",
        "k_goles_visita_recibido",
    ]

    # Sinónimos aceptados → clave canónica
    CONSTANT_SYNONYMS: Dict[str, str] = {
        "k local": "k_local",
        "k_local": "k_local",
        "k visita": "k_visita",
        "k_visita": "k_visita",
        "k goles anotado": "k_goles_anotado",
        "k_goles_anotado": "k_goles_anotado",
        "k goles recibido": "k_goles_recibido",
        "k_goles_recibido": "k_goles_recibido",
        # locales/visita de goles
        "k goles local anotado": "k_goles_local_anotado",
        "k_goles_local_anotado": "k_goles_local_anotado",
        "k goles local recibido": "k_goles_local_recibido",
        "k_goles_local_recibido": "k_goles_local_recibido",
        "k goles visita anotado": "k_goles_visita_anotado",
        "k_goles_visita_anotado": "k_goles_visita_anotado",
        "k goles visita recibido": "k_goles_visita_recibido",
        "k_goles_visita_recibido": "k_goles_visita_recibido",
        "k": "k",
    }

    def __init__(self):
        self.models: Dict[str, Pipeline] = {}
        self.params_meta: Dict[str, dict] = {}
        self.model_dir = os.path.join("model_exports", "global")
        os.makedirs(self.model_dir, exist_ok=True)

    # --------------------------------- Carga de datos ------------------------------------- #

    @staticmethod
    def _find_col(df: pd.DataFrame, candidates: Iterable[str], raise_if_missing: bool = True) -> Optional[str]:
        """
        Busca una columna en df independiente de mayúsculas/minúsculas y espacios.
        Devuelve el nombre EXACTO de la columna encontrada, o None si no se encuentra (si raise_if_missing=False).
        """
        norm = {re.sub(r"\s+", "", c).lower(): c for c in df.columns}
        for cand in candidates:
            key = re.sub(r"\s+", "", cand).lower()
            if key in norm:
                return norm[key]
        if raise_if_missing:
            raise KeyError(f"No se encontró ninguna de las columnas requeridas: {list(candidates)}")
        return None

    def _load_from_db(self, data_path: str) -> pd.DataFrame:
        """
        Carga datos desde una base SQLite (.db). Detecta tablas que contengan las columnas mínimas
        y concatena filas. Si solo una tabla cumple, retorna esa.

        Se buscan al menos estas columnas (con tolerancia de nombres):
        - Equipo_Nombre, Rival_Nombre, Nivel_Equipo, Nivel_Rival_Numerico, Condición, Fecha,
          Liga (o League_Code/league) y Status.
        """
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"No se encontró el archivo '{data_path}'")

        conn = sqlite3.connect(data_path)
        try:
            tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", conn)["name"].tolist()
        except Exception as e:
            conn.close()
            raise RuntimeError(f"Error leyendo tablas de {data_path}: {e}")

        if not tables:
            conn.close()
            raise RuntimeError(f"No se encontraron tablas en la base de datos: {data_path}")

        required_base = [
            "Equipo_Nombre", "Rival_Nombre",
            "Nivel_Equipo", "Nivel_Rival_Numerico",
            "Condición", "Fecha",
            "Liga", "League_Code", "league",  # cualquiera de estas para liga
            "Status",
        ]

        dfs: List[pd.DataFrame] = []
        for t in tables:
            try:
                df_t = pd.read_sql_query(f"SELECT * FROM '{t}'", conn)
            except Exception as e:
                logger.warning(f"Tabla '{t}' no se pudo leer: {e}")
                continue

            # ¿Contiene las columnas mínimas? (al menos una para liga)
            cols_lower = {c.lower() for c in df_t.columns}
            has_min = all(any((cand.lower() in cols_lower) for cand in [r]) for r in [
                "Equipo_Nombre", "Rival_Nombre", "Nivel_Equipo", "Nivel_Rival_Numerico", "Condición", "Fecha", "Status"
            ])
            has_league = any((cand.lower() in cols_lower) for cand in ["Liga", "League_Code", "league"])

            if has_min and has_league:
                logger.info(f"Tabla '{t}' contiene columnas mínimas. Filas: {len(df_t)}")
                df_t["__source_table__"] = t  # referencia
                dfs.append(df_t)
            else:
                logger.info(f"Tabla '{t}' omitida: no cumple columnas mínimas.")

        conn.close()

        if not dfs:
            raise RuntimeError("Ninguna tabla cumple con las columnas mínimas requeridas.")

        if len(dfs) == 1:
            return dfs[0]
        return pd.concat(dfs, ignore_index=True, sort=False)

    # --------------------------------- Normalización -------------------------------------- #

    @staticmethod
    def _normalize_strings(series: pd.Series) -> pd.Series:
        return series.astype(str).str.strip().str.upper()

    @staticmethod
    def _normalize_condition(cond: Union[str, float, int, None]) -> Optional[str]:
        if pd.isna(cond):
            return None
        s = str(cond).strip().upper()
        if s in {"L", "LOC", "LOCAL", "HOME", "H"}:
            return "LOCAL"
        if s in {"V", "VIS", "VISITA", "VISITANTE", "AWAY", "A"}:
            return "VISITANTE"
        if s in {"N", "NEUTRAL", "NEUT"}:
            return "NEUTRAL"
        # Si no se puede mapear, devolver el original upper
        return s

    def _normalize_df(
        self,
        df: pd.DataFrame,
        league_col: str,
        status_col: str,
    ) -> pd.DataFrame:
        """
        Normaliza cadenas, mapea condición, fecha a datetime y elimina duplicados.
        Asegura la presencia de columnas canónicas:
          - Equipo_Nombre, Rival_Nombre, Nivel_Equipo, Nivel_Rival_Numerico, Condición, is_neutral, Fecha, league_code, Status.
          - Crea columnas canónicas para 'k_local' y 'k_visita' si vienen con espacios: 'k local'/'k visita'.
        """
        df = df.copy()

        # Resolver columnas principales (case-insensitive)
        equipo_col = self._find_col(df, ["Equipo_Nombre"])
        rival_col = self._find_col(df, ["Rival_Nombre"])
        nivel_equipo_col = self._find_col(df, ["Nivel_Equipo"])
        nivel_rival_col = self._find_col(df, ["Nivel_Rival_Numerico"])
        condicion_col = self._find_col(df, ["Condición", "Condicion", "Condition"])
        fecha_col = self._find_col(df, ["Fecha"])
        status_col_real = self._find_col(df, [status_col])
        league_col_real = self._find_col(df, [league_col, "League_Code", "league", "Liga"])

        # Normalizaciones
        df[equipo_col] = self._normalize_strings(df[equipo_col])
        df[rival_col] = self._normalize_strings(df[rival_col])

        # Condición + is_neutral
        df[condicion_col] = df[condicion_col].map(self._normalize_condition)
        df["is_neutral"] = (df[condicion_col] == "NEUTRAL").astype(int)

        # Fecha
        df[fecha_col] = pd.to_datetime(df[fecha_col], errors="coerce", utc=False)
        df = df.dropna(subset=[fecha_col])

        # Liga
        df["league_code"] = self._normalize_strings(df[league_col_real].astype(str))

        # Status
        df[status_col_real] = self._normalize_strings(df[status_col_real].astype(str))

        # Niveles a numéricos
        df[nivel_equipo_col] = pd.to_numeric(df[nivel_equipo_col], errors="coerce")
        df[nivel_rival_col] = pd.to_numeric(df[nivel_rival_col], errors="coerce")

        # Renombrados canónicos para uso interno
        df = df.rename(columns={
            equipo_col: "Equipo_Nombre",
            rival_col: "Rival_Nombre",
            nivel_equipo_col: "Nivel_Equipo",
            nivel_rival_col: "Nivel_Rival_Numerico",
            condicion_col: "Condición",
            fecha_col: "Fecha",
            status_col_real: "Status",
        })

        # Estandarizar columnas de k_local/k_visita si viniesen como "k local"/"k visita"
        if "k_local" not in df.columns:
            k_local_alt = self._find_col(df, ["k_local", "k local"], raise_if_missing=False)
            if k_local_alt:
                df["k_local"] = pd.to_numeric(df[k_local_alt], errors="coerce")

        if "k_visita" not in df.columns:
            k_vis_alt = self._find_col(df, ["k_visita", "k visita"], raise_if_missing=False)
            if k_vis_alt:
                df["k_visita"] = pd.to_numeric(df[k_vis_alt], errors="coerce")

        # Goles base (si existen)
        if "k_goles_anotado" in df.columns:
            df["k_goles_anotado"] = pd.to_numeric(df["k_goles_anotado"], errors="coerce")
        if "k_goles_recibido" in df.columns:
            df["k_goles_recibido"] = pd.to_numeric(df["k_goles_recibido"], errors="coerce")

        # Orden cronológico
        df = df.sort_values("Fecha").reset_index(drop=True)

        # Eliminar duplicados exactos por (Equipo, Rival, Fecha, Liga)
        before = len(df)
        df = df.drop_duplicates(subset=["Equipo_Nombre", "Rival_Nombre", "Fecha", "league_code"], keep="first")
        after = len(df)
        if before != after:
            logger.info(f"Eliminados {before - after} duplicados exactos por (Equipo, Rival, Fecha, Liga).")

        return df

    # --------------------------- Resolución de columnas de constantes ---------------------- #

    @staticmethod
    def _normalize_constant_key(constant_type: Union[str, Tuple[str, str]]) -> str:
        """
        Acepta:
          - 'k_local' o ('k_local','k_local')
          - sinónimos: 'k local'/'k visita'
        Devuelve clave canónica (ej. 'k_local').
        """
        if isinstance(constant_type, tuple):
            # Si viene ('k_local','k_local') o ('k_local','k local')
            constant_type = constant_type[0] if constant_type[0] else constant_type[1]
        s = str(constant_type).strip().lower().replace("__", "_").replace("  ", " ")
        s = s.replace("-", "_")
        s = re.sub(r"\s+", " ", s)
        return GlobalConstantPredictor.CONSTANT_SYNONYMS.get(s, s)

    @staticmethod
    def _resolve_goles_base_column(df: pd.DataFrame, const_key: str) -> Optional[str]:
        """
        Bug fix goles: si const_key es 'k_goles_(local|visita)_(anotado|recibido)',
        intenta mapear al base_col 'k_goles_{anotado|recibido}' vía regex.
        Si no coincide o no existe, devuelve None.
        """
        m = re.match(r"^(k_goles)_(local|visita)_(anotado|recibido)$", const_key)
        if m:
            base_col = f"{m.group(1)}_{m.group(3)}"  # k_goles_anotado | k_goles_recibido
            if base_col in df.columns:
                return base_col
        return None

    def _resolve_constant_value_column(self, df: pd.DataFrame, const_key: str) -> Optional[str]:
        """
        Determina qué columna usar para el valor "actual" de la constante:
        - Si es goles local/visita anotado/recibido, primero intenta el base_col (bug fix).
        - Si no, prueba la propia const_key.
        - Finalmente, intenta sinónimos para k_local/k_visita.
        Devuelve None si ninguna existe (el flujo posterior descartará filas NaN).
        """
        # bug fix goles
        base_col = self._resolve_goles_base_column(df, const_key)
        if base_col is not None:
            return base_col

        # columna literal
        if const_key in df.columns:
            return const_key

        # sinónimos para k_local / k_visita que pueden venir con espacios
        if const_key == "k_local":
            alt = self._find_col(df, ["k_local", "k local"], raise_if_missing=False)
            return alt
        if const_key == "k_visita":
            alt = self._find_col(df, ["k_visita", "k visita"], raise_if_missing=False)
            return alt

        # para k (global)
        if const_key == "k" and "k" in df.columns:
            return "k"

        # goles base simples
        if const_key in {"k_goles_anotado", "k_goles_recibido"} and const_key in df.columns:
            return const_key

        return None

    # ----------------------------- Previos y futuros (helper) ------------------------------ #

    def _get_match_constants(
        self,
        df: pd.DataFrame,
        match_row: pd.Series,
        const_key: str,
        const_value_col: str,
        restrict_prev_to_same_league: bool,
    ) -> Optional[dict]:
        """
        Obtiene info del último partido PREVIO del equipo y del rival, con reglas:
        - Si NO hay previo del equipo ⇒ None (descarta sample).
        - Si NO hay previo del rival ⇒ sentinelas (-1) + flags.

        Filtros por condición:
          - k_local ⇒ equipo prev LOCAL, rival prev VISITANTE
          - k_visita ⇒ equipo prev VISITANTE, rival prev LOCAL
          - k_goles_local_* ⇒ equipo prev LOCAL, rival prev LOCAL
          - k_goles_visita_* ⇒ equipo prev VISITANTE, rival prev VISITANTE
          - k / k_goles_{anotado|recibido} ⇒ sin filtro de condición
        """
        team = match_row["Equipo_Nombre"]
        rival = match_row["Rival_Nombre"]
        date = match_row["Fecha"]
        league = match_row["league_code"]

        # Base filtros previos
        team_prev = df[(df["Equipo_Nombre"] == team) & (df["Fecha"] < date)]
        rival_prev = df[(df["Equipo_Nombre"] == rival) & (df["Fecha"] < date)]

        if restrict_prev_to_same_league:
            team_prev = team_prev[team_prev["league_code"] == league]
            rival_prev = rival_prev[rival_prev["league_code"] == league]

        ck = const_key.lower()

        # Filtrado por condición según constante
        if ck == "k_local":
            team_prev = team_prev[team_prev["Condición"] == "LOCAL"]
            rival_prev = rival_prev[rival_prev["Condición"] == "VISITANTE"]
            team_col_use = self._resolve_constant_value_column(df, "k_local") or const_value_col
            rival_col_use = self._resolve_constant_value_column(df, "k_visita") or const_value_col

        elif ck == "k_visita":
            team_prev = team_prev[team_prev["Condición"] == "VISITANTE"]
            rival_prev = rival_prev[rival_prev["Condición"] == "LOCAL"]
            team_col_use = self._resolve_constant_value_column(df, "k_visita") or const_value_col
            rival_col_use = self._resolve_constant_value_column(df, "k_local") or const_value_col

        elif ck.startswith("k_goles_local_"):
            team_prev = team_prev[team_prev["Condición"] == "LOCAL"]
            rival_prev = rival_prev[rival_prev["Condición"] == "LOCAL"]
            # Para goles, el valor puede venir del base_col "k_goles_{...}"
            team_col_use = self._resolve_goles_base_column(df, const_key) or const_value_col
            rival_col_use = self._resolve_goles_base_column(df, const_key) or const_value_col

        elif ck.startswith("k_goles_visita_"):
            team_prev = team_prev[team_prev["Condición"] == "VISITANTE"]
            rival_prev = rival_prev[rival_prev["Condición"] == "VISITANTE"]
            team_col_use = self._resolve_goles_base_column(df, const_key) or const_value_col
            rival_col_use = self._resolve_goles_base_column(df, const_key) or const_value_col

        else:
            # k o k_goles_anotado/recibido (sin filtro de condición)
            team_col_use = const_value_col
            rival_col_use = const_value_col

        # Orden cronológico y toma del último
        team_prev = team_prev.sort_values("Fecha")
        rival_prev = rival_prev.sort_values("Fecha")

        out: dict = {}

        # Equipo: si no hay previo ⇒ descartar
        if len(team_prev) == 0:
            return None
        last_team = team_prev.iloc[-1]
        out.update({
            f"prev_team_{const_key}": pd.to_numeric(last_team.get(team_col_use, np.nan), errors="coerce"),
            "prev_team_nivel": pd.to_numeric(last_team.get("Nivel_Equipo", np.nan), errors="coerce"),
            "prev_team_rival_nivel": pd.to_numeric(last_team.get("Nivel_Rival_Numerico", np.nan), errors="coerce"),
        })

        # Rival: si no hay previo ⇒ sentinelas + flag
        if len(rival_prev) == 0:
            out.update({
                f"prev_rival_{const_key}": -1.0,
                "prev_rival_nivel": pd.to_numeric(match_row.get("Nivel_Rival_Numerico", np.nan), errors="coerce"),
                "prev_rival_rival_nivel": -1.0,
                "prev_rival_hist_missing": 1,
            })
        else:
            last_rival = rival_prev.iloc[-1]
            out.update({
                f"prev_rival_{const_key}": pd.to_numeric(last_rival.get(rival_col_use, np.nan), errors="coerce"),
                "prev_rival_nivel": pd.to_numeric(last_rival.get("Nivel_Equipo", np.nan), errors="coerce"),
                "prev_rival_rival_nivel": pd.to_numeric(last_rival.get("Nivel_Rival_Numerico", np.nan), errors="coerce"),
                "prev_rival_hist_missing": 0,
            })

        return out

    def _get_future_info(
        self,
        df: pd.DataFrame,
        team: str,
        after_date: pd.Timestamp,
        league: str,
        restrict_prev_to_same_league: bool
    ) -> dict:
        """
        Obtiene el próximo partido del equipo DESPUÉS de 'after_date'.
        - Si restrict_prev_to_same_league=True, filtra por misma liga.
        - Devuelve {'future_rival_nivel': nivel_o_-1, 'future_missing': 0/1}
        """
        fdf = df[(df["Equipo_Nombre"] == team) & (df["Fecha"] > after_date)]
        if restrict_prev_to_same_league:
            fdf = fdf[fdf["league_code"] == league]
        fdf = fdf.sort_values("Fecha")

        if len(fdf) == 0:
            return {"future_rival_nivel": -1.0, "future_missing": 1}
        nm = fdf.iloc[0]
        return {
            "future_rival_nivel": pd.to_numeric(nm.get("Nivel_Rival_Numerico", np.nan), errors="coerce"),
            "future_missing": 0
        }

    # ------------------------------- Construcción de samples -------------------------------- #

    def _build_samples_for_constant(
        self,
        df: pd.DataFrame,
        const_key: str,
        const_value_col: Optional[str],
        restrict_prev_to_same_league: bool,
    ) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
        """
        Construye el DataFrame de features X_df (con nombres de columnas) y el vector y para la constante dada.
        Reglas de descarte/flags según especificación.
        """
        if const_value_col is None:
            # Si no existe la columna de la constante, intentemos continuar: se descartarán filas NaN más adelante.
            logger.warning(f"[{const_key}] No se encontró columna explícita; se intentará continuar (podría generar NaN).")

        rows: List[dict] = []
        processed = 0
        added = 0
        skipped_no_prev_team = 0

        for _, m in df.iterrows():
            processed += 1

            # Determinar valor actual de la constante:
            # Para goles (local/visita) ya resolvimos a base_col si aplica.
            val_col = const_value_col or const_key
            current_val = pd.to_numeric(m.get(val_col, np.nan), errors="coerce")

            # Info previos (con filtros por liga/condición)
            prev_info = self._get_match_constants(
                df=df,
                match_row=m,
                const_key=const_key,
                const_value_col=val_col,
                restrict_prev_to_same_league=restrict_prev_to_same_league,
            )
            if prev_info is None:
                skipped_no_prev_team += 1
                continue

            # Futuros (para equipo y rival)
            fut_team = self._get_future_info(
                df, team=m["Equipo_Nombre"], after_date=m["Fecha"], league=m["league_code"],
                restrict_prev_to_same_league=restrict_prev_to_same_league
            )
            fut_rival = self._get_future_info(
                df, team=m["Rival_Nombre"], after_date=m["Fecha"], league=m["league_code"],
                restrict_prev_to_same_league=restrict_prev_to_same_league
            )

            # Calcular target (comparación con prev del equipo)
            prev_team_const = prev_info[f"prev_team_{const_key}"]
            # Si prev_team_const es NaN, no tiene sentido el target ⇒ saltar
            if pd.isna(prev_team_const) or pd.isna(current_val):
                skipped_no_prev_team += 1
                continue

            if current_val > prev_team_const:
                target = 1
            elif current_val < prev_team_const:
                target = -1
            else:
                target = 0

            row = {
                "team_nivel": pd.to_numeric(m.get("Nivel_Equipo", np.nan), errors="coerce"),
                "rival_nivel": pd.to_numeric(m.get("Nivel_Rival_Numerico", np.nan), errors="coerce"),
                f"prev_team_{const_key}": prev_info[f"prev_team_{const_key}"],
                f"prev_rival_{const_key}": prev_info[f"prev_rival_{const_key}"],
                "prev_team_nivel": prev_info["prev_team_nivel"],
                "prev_rival_nivel": prev_info["prev_rival_nivel"],
                "prev_team_rival_nivel": prev_info["prev_team_rival_nivel"],
                "prev_rival_rival_nivel": prev_info["prev_rival_rival_nivel"],
                "prev_rival_hist_missing": prev_info["prev_rival_hist_missing"],
                "future_team_rival_nivel": fut_team["future_rival_nivel"],
                "future_rival_rival_nivel": fut_rival["future_rival_nivel"],
                "future_team_missing": fut_team["future_missing"],
                "future_rival_missing": fut_rival["future_missing"],
                "league_code": m["league_code"],
                "is_neutral": int(m.get("is_neutral", 0)),
                "target": target,
            }

            # Verificación de numéricos clave requeridos
            required_numeric = [
                "team_nivel", "rival_nivel", f"prev_team_{const_key}", "prev_team_nivel", "prev_team_rival_nivel"
            ]
            if any(pd.isna(row[c]) for c in required_numeric):
                # Si por alguna razón hay NaN en columnas indispensables, saltar
                continue

            rows.append(row)
            added += 1

        logger.info(f"[{const_key}] Filas procesadas: {processed} | Agregadas: {added} | "
                    f"Descartadas sin previo del equipo: {skipped_no_prev_team}")

        if not rows:
            raise ValueError(f"[{const_key}] No hay suficientes registros tras procesamiento.")

        Xy = pd.DataFrame(rows)

        # Distribución de clases
        unique_cls, counts = np.unique(Xy["target"], return_counts=True)
        dist = {int(c): int(n) for c, n in zip(unique_cls, counts)}
        logger.info(f"[{const_key}] Distribución de clases: {dist}")

        # Definir orden de features numéricas/flags (is_neutral es opcional, pero ya está en Xy)
        numeric_and_flags = [
            "team_nivel", "rival_nivel",
            f"prev_team_{const_key}", f"prev_rival_{const_key}",
            "prev_team_nivel", "prev_rival_nivel",
            "prev_team_rival_nivel", "prev_rival_rival_nivel",
            "future_team_rival_nivel", "future_rival_rival_nivel",
            "prev_rival_hist_missing", "future_team_missing", "future_rival_missing",
            "is_neutral",
        ]
        # Categóricas
        categorical = ["league_code"]

        # X (conservando columnas de entrada con nombres)
        feature_order = numeric_and_flags + categorical
        X_df = Xy[feature_order].copy()
        y = Xy["target"].values

        return X_df, y, feature_order

    # ------------------------------------- Entrenamiento ----------------------------------- #

    def train_global(
        self,
        data_path: str,
        league_col: str = "Liga",
        status_col: str = "Status",
        finished_statuses: Iterable[str] = ("MATCH_FINISHED", "FINISHED", "FT"),
        restrict_prev_to_same_league: bool = True,
        league_whitelist: Optional[Iterable[str]] = None,
        date_min: Optional[str] = None,
        date_max: Optional[str] = None,
        constants: Optional[Iterable[Union[str, Tuple[str, str]]]] = None,
    ) -> None:
        """
        Entrena modelos globales por constante usando múltiples ligas y filtra por status/fechas.

        Parámetros
        ----------
        data_path : str
            Ruta del archivo .db (SQLite).
        league_col : str, opcional
            Nombre de la columna de liga en el archivo de entrada. Acepta 'League_Code' o 'league'.
        status_col : str, opcional
            Nombre de la columna de status en el archivo de entrada.
        finished_statuses : Iterable[str], opcional
            Conjunto de estados que representan partido finalizado. Se comparan en mayúsculas.
        restrict_prev_to_same_league : bool, opcional
            Si True, previos/futuros se calculan dentro de la misma liga.
        league_whitelist : Iterable[str] o None, opcional
            Si no es None, filtra a solo estas ligas (comparación en mayúsculas).
        date_min : str o None, opcional
            Fecha mínima (YYYY-MM-DD) inclusiva para filtrar.
        date_max : str o None, opcional
            Fecha máxima (YYYY-MM-DD) inclusiva para filtrar.
        constants : Iterable[str|tuple] o None, opcional
            Conjunto de constantes a entrenar. Si None, usa el set canónico por defecto.
        """
        # 1) Cargar y normalizar
        raw_df = self._load_from_db(data_path)
        orig = len(raw_df)
        logger.info(f"Dataset original: {orig} filas (desde {data_path})")

        df = self._normalize_df(raw_df, league_col=league_col, status_col=status_col)

        # 2) Filtros por status / fechas / ligas
        before_filters = len(df)
        finished_upper = {str(s).strip().upper() for s in finished_statuses}
        df = df[df["Status"].isin(finished_upper)]

        if league_whitelist is not None:
            lw = {str(x).strip().upper() for x in league_whitelist}
            df = df[df["league_code"].isin(lw)]

        if date_min:
            try:
                dt_min = pd.to_datetime(date_min)
                df = df[df["Fecha"] >= dt_min]
            except Exception:
                logger.warning(f"date_min inválida: {date_min} (se ignora)")
        if date_max:
            try:
                dt_max = pd.to_datetime(date_max)
                df = df[df["Fecha"] <= dt_max]
            except Exception:
                logger.warning(f"date_max inválida: {date_max} (se ignora)")

        after_filters = len(df)
        logger.info(f"Tras filtros -> status/ligas/fechas: {before_filters} → {after_filters} filas.")

        if after_filters == 0:
            raise ValueError("No hay datos tras aplicar filtros. Revise parámetros y columnas.")

        # 3) Determinar constantes a entrenar
        if constants is None:
            constants_list = self.CANONICAL_CONSTANTS
        else:
            constants_list = [self._normalize_constant_key(c) for c in constants]

        # 4) Entrenar por constante
        for ckey in constants_list:
            try:
                const_value_col = self._resolve_constant_value_column(df, ckey)
                X_df, y, feature_order = self._build_samples_for_constant(
                    df=df,
                    const_key=ckey,
                    const_value_col=const_value_col,
                    restrict_prev_to_same_league=restrict_prev_to_same_league,
                )

                # Si y tiene < 2 clases, omitir
                unique_classes, counts = np.unique(y, return_counts=True)
                if len(unique_classes) < 2:
                    logger.warning(f"[{ckey}] Omitido: solo una clase presente en y ({unique_classes.tolist()}).")
                    continue

                # División train/test
                X_train, X_test, y_train, y_test = train_test_split(
                    X_df, y, test_size=0.2, random_state=42, stratify=y
                )

                # CV estratificada dinámica
                cls_counts = {int(c): int(n) for c, n in zip(*np.unique(y_train, return_counts=True))}
                min_count = min(cls_counts.values())
                n_splits = min(5, max(2, min_count))
                logger.info(f"[{ckey}] CV estratificada con n_splits={n_splits} (min_count_por_clase={min_count})")
                cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

                # Preprocesador: OneHot(league_code) + passthrough numéricas/flags
                categorical_features = ["league_code"]
                numeric_and_flags = [col for col in feature_order if col not in categorical_features]

                pre = ColumnTransformerWithNames(
                    transformers=[
                        ("ohe_league", _safe_ohe(), categorical_features),
                        ("num", "passthrough", numeric_and_flags),
                    ],
                    remainder="drop",
                )
                # Intentar salida pandas
                pre.set_pandas_output()

                clf = RandomForestClassifier(
                    random_state=42,
                    class_weight="balanced",
                )

                pipe = Pipeline(steps=[
                    ("pre", pre),
                    ("clf", clf),
                ])

                param_grid = {
                    "clf__n_estimators": [200, 400],
                    "clf__max_depth": [10, 20, None],
                    "clf__min_samples_split": [5, 10],
                    "clf__max_features": ["sqrt", "log2"],
                }

                grid = GridSearchCV(
                    estimator=pipe,
                    param_grid=param_grid,
                    scoring="f1_macro",
                    n_jobs=-1,
                    cv=cv,
                    verbose=0,
                    refit=True,
                )
                grid.fit(X_train, y_train)

                best_pipe: Pipeline = grid.best_estimator_

                # Evaluación en test
                y_pred = best_pipe.predict(X_test)
                macro_f1 = f1_score(y_test, y_pred, average="macro")
                acc = accuracy_score(y_test, y_pred)
                logger.info(f"[{ckey}] Mejor hiperparámetros: {grid.best_params_}")
                logger.info(f"[{ckey}] Test macro-F1: {macro_f1:.4f} | accuracy: {acc:.4f}")

                # Guardar pipeline + params
                self.models[ckey] = best_pipe
                meta = {
                    "best_params": grid.best_params_,
                    "classes": best_pipe.named_steps["clf"].classes_.tolist(),
                    "input_feature_order": feature_order,
                    "date_trained": datetime.now().isoformat(timespec="seconds"),
                    "macro_f1_test": macro_f1,
                    "accuracy_test": acc,
                    "n_samples_total": int(len(X_df)),
                    "restrict_prev_to_same_league": bool(restrict_prev_to_same_league),
                }
                self.params_meta[ckey] = meta
                self._save_single(ckey, best_pipe, meta)

            except Exception as e:
                logger.exception(f"[{ckey}] Error durante entrenamiento: {e}")
                continue

    # -------------------------------------- Persistencia ----------------------------------- #

    def _save_single(self, key: str, pipeline: Pipeline, meta: dict) -> None:
        """
        Guarda el pipeline y los metadatos de la constante 'key'.
        """
        model_path = os.path.join(self.model_dir, f"global_{key}.joblib")
        params_path = os.path.join(self.model_dir, f"params_{key}.json")

        joblib.dump(pipeline, model_path)
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        logger.info(f"[{key}] Guardado pipeline → {model_path}")
        logger.info(f"[{key}] Guardado params   → {params_path}")

    def load_models(self, directory: Optional[str] = None) -> None:
        """
        Carga los pipelines guardados en 'directory' (o en model_exports/global si None).
        """
        base_dir = directory or self.model_dir
        if not os.path.isdir(base_dir):
            logger.warning(f"No existe el directorio '{base_dir}'.")
            return

        files = os.listdir(base_dir)
        joblibs = [f for f in files if f.startswith("global_") and f.endswith(".joblib")]
        for jf in joblibs:
            key = jf.replace("global_", "").replace(".joblib", "")
            model_path = os.path.join(base_dir, jf)
            params_path = os.path.join(base_dir, f"params_{key}.json")

            try:
                pipe: Pipeline = joblib.load(model_path)
                self.models[key] = pipe
                if os.path.exists(params_path):
                    with open(params_path, "r", encoding="utf-8") as f:
                        self.params_meta[key] = json.load(f)
                logger.info(f"Cargado modelo '{key}' desde {model_path}")
            except Exception as e:
                logger.warning(f"No se pudo cargar '{model_path}': {e}")

    # ---------------------------------------- Predicción ----------------------------------- #

    def predict(
        self,
        constant_type: Union[str, Tuple[str, str]],
        league_code: str,
        team_nivel: float,
        rival_nivel: float,
        prev_team_k: float,
        prev_rival_k: float,
        prev_team_nivel: float,
        prev_rival_nivel: float,
        prev_team_rival_nivel: float,
        prev_rival_rival_nivel: float,
        future_team_rival_nivel: float = -1,
        future_rival_rival_nivel: float = -1,
        prev_rival_hist_missing: Optional[int] = None,
        future_team_missing: Optional[int] = None,
        future_rival_missing: Optional[int] = None,
    ) -> Dict[str, float]:
        """
        Realiza la predicción para una constante dada.

        Si los flags prev_rival_hist_missing / future_*_missing vienen en None, se calculan
        automáticamente usando la regla del sentinela (-1 → flag=1, de lo contrario 0).

        Parámetros
        ----------
        constant_type : str o (str,str)
            Clave de la constante (admite sinónimos o tuplas como ('k_local','k_local')).
        league_code : str
            Código de la liga del partido a predecir (se hace OneHot internamente).
        team_nivel, rival_nivel, prev_* : float
            Variables numéricas/flags requeridas por el pipeline.
        future_* : float, opcional
            Niveles de próximos rivales (o -1 si no hay).
        prev_rival_hist_missing, future_team_missing, future_rival_missing : int|None, opcional
            Flags de faltantes. Si son None se calculan automáticamente.

        Returns
        -------
        dict
            Probabilidades en % para {'incremento','mantiene','decremento'}.
        """
        key = self._normalize_constant_key(constant_type)
        if key not in self.models:
            raise ValueError(f"No hay modelo cargado/entrenado para la constante '{key}'.")

        meta = self.params_meta.get(key, {})
        feature_order: List[str] = meta.get("input_feature_order", [
            # fallback en caso extremo
            "team_nivel", "rival_nivel",
            f"prev_team_{key}", f"prev_rival_{key}",
            "prev_team_nivel", "prev_rival_nivel",
            "prev_team_rival_nivel", "prev_rival_rival_nivel",
            "future_team_rival_nivel", "future_rival_rival_nivel",
            "prev_rival_hist_missing", "future_team_missing", "future_rival_missing",
            "is_neutral", "league_code"
        ])

        # Flags automáticos si vienen None
        if prev_rival_hist_missing is None:
            prev_rival_hist_missing = 1 if (prev_rival_k == -1) or (prev_rival_rival_nivel == -1) else 0
        if future_team_missing is None:
            future_team_missing = 1 if (future_team_rival_nivel == -1) else 0
        if future_rival_missing is None:
            future_rival_missing = 1 if (future_rival_rival_nivel == -1) else 0

        # Construir DataFrame de UNA fila con exactamente las columnas esperadas por el pipeline
        row = {
            "team_nivel": team_nivel,
            "rival_nivel": rival_nivel,
            f"prev_team_{key}": prev_team_k,
            f"prev_rival_{key}": prev_rival_k,
            "prev_team_nivel": prev_team_nivel,
            "prev_rival_nivel": prev_rival_nivel,
            "prev_team_rival_nivel": prev_team_rival_nivel,
            "prev_rival_rival_nivel": prev_rival_rival_nivel,
            "future_team_rival_nivel": future_team_rival_nivel,
            "future_rival_rival_nivel": future_rival_rival_nivel,
            "prev_rival_hist_missing": prev_rival_hist_missing,
            "future_team_missing": future_team_missing,
            "future_rival_missing": future_rival_missing,
            "is_neutral": 0,  # por defecto 0 en predicción (opcional); si tu caso requiere 1, edítalo antes de llamar
            "league_code": str(league_code).strip().upper(),
        }

        # Asegurar que existen todas las columnas requeridas por orden
        for col in feature_order:
            if col not in row:
                # Si es una columna dinámica distinta por la constante (p.ej., prev_team_{k_goles...})
                if col.startswith("prev_team_") or col.startswith("prev_rival_"):
                    # En escenarios poco probables de desalineo, inicializar con el valor de prev_*_k
                    if "prev_team_" in col:
                        row[col] = prev_team_k
                    elif "prev_rival_" in col:
                        row[col] = prev_rival_k
                elif col == "is_neutral":
                    row[col] = 0
                elif col == "league_code":
                    row[col] = str(league_code).strip().upper()
                else:
                    # Defaults seguros (no ideales, pero evita fallo)
                    row[col] = 0

        X = pd.DataFrame([row], columns=feature_order)

        pipe: Pipeline = self.models[key]
        proba = pipe.predict_proba(X)[0]
        classes = pipe.named_steps["clf"].classes_

        result = {"incremento": 0.0, "mantiene": 0.0, "decremento": 0.0}
        for c, p in zip(classes, proba):
            if c == -1:
                result["decremento"] = float(p * 100.0)
            elif c == 0:
                result["mantiene"] = float(p * 100.0)
            elif c == 1:
                result["incremento"] = float(p * 100.0)

        return result


# ----------------------------------------- main() ----------------------------------------- #

def main():
    """
    Ejemplo mínimo de entrenamiento y predicción.

    Ajusta las rutas/parámetros según tu entorno de datos.
    """
    predictor = GlobalConstantPredictor()

    # Entrenamiento desde un archivo SQLite (.db).
    predictor.train_global(
        data_path="discreto.db",
        league_col="Liga",  # acepta también 'League_Code' o 'league'
        status_col="Status",
        finished_statuses=("MATCH_FINISHED", "FINISHED", "FT"),
        restrict_prev_to_same_league=True,
        league_whitelist=None,
        date_min=None,
        date_max=None,
    )

    # (Opcional) Cargar modelos desde disco (si los quieres reusar en otro proceso)
    predictor.load_models()  # por defecto desde model_exports/global/

    # Predicción de ejemplo para la constante k_local
    result = predictor.predict(
        constant_type=("k_local", "k_local"),
        league_code="PER1",
        team_nivel=0.75,
        rival_nivel=0.65,
        prev_team_k=1.2,
        prev_rival_k=-1.0,  # -1 indica faltante histórico del rival
        prev_team_nivel=0.73,
        prev_rival_nivel=0.68,
        prev_team_rival_nivel=0.62,
        prev_rival_rival_nivel=-1.0,  # -1 faltante del rival
        future_team_rival_nivel=-1.0,  # -1 sin partido futuro
        future_rival_rival_nivel=0.67,
        # Flags en None ⇒ se auto-calculan a partir de los -1
        prev_rival_hist_missing=None,
        future_team_missing=None,
        future_rival_missing=None,
    )
    print("Predicción k_local:")
    for k, v in result.items():
        print(f"  {k}: {v:.2f}%")


if __name__ == "__main__":
    main()
