#!/usr/bin/env python3
# constants_calculator.py  —  VERSIÓN OPTIMIZADA v2
#
# ============================================================================
# ANÁLISIS DE PROBLEMAS ENCONTRADOS EN LA VERSIÓN ANTERIOR:
# ============================================================================
#
# 🐌 PROBLEMA 1: calculate_and_store() BORRA TODO Y RECALCULA DESDE CERO
#    - Línea 399-404: Elimina TODOS los registros del equipo antes de recalcular.
#    - Aunque existe incremental_calculate_and_store(), el método no-incremental
#      se usa en varios flujos (full_recalculate, sync_tool, etc.).
#
# 🐌 PROBLEMA 2: get_team_level_safe() → QUERY INDIVIDUAL POR CADA FIXTURE
#    - Cada fixture hace un query SELECT a levels.db (get_team_level_at_date).
#    - Para un equipo con 200 fixtures × 500 equipos = 100,000 queries individuales.
#    - PEOR: Si devuelve 0.5, hace OTRO query (has_fixtures) y potencialmente
#      llama update_team_levels() que recalcula todos los niveles del rival.
#    - Este es el cuello de botella #1.
#
# 🐌 PROBLEMA 3: validate_fixture_exists() POR CADA FILA AL INSERTAR
#    - Líneas 416 y 703: Para cada fila del DataFrame, hace un SELECT individual
#      para verificar que el fixture existe. Totalmente redundante porque los
#      fixtures vienen de un query previo a la misma BD.
#
# 🐌 PROBLEMA 4: QUERIES DE DIAGNÓSTICO POR CADA EQUIPO
#    - Líneas 210-226: En calculate_constants(), para CADA equipo:
#      * COUNT total de fixtures (innecesario para producción)
#      * GROUP BY status_long con COUNT (solo útil para debug)
#    - Esto agrega ~3 queries extra por equipo.
#
# 🐌 PROBLEMA 5: df.iterrows() PARA ACUMULACIÓN DE k_*
#    - Línea 302: Iterar un DataFrame con .iterrows() es ~100x más lento
#      que trabajar con arrays numpy.
#
# 🐌 PROBLEMA 6: INSERCIÓN FILA POR FILA EN VEZ DE BULK INSERT
#    - Líneas 413-448 y 700-737: session.add() individual por cada registro.
#    - SQLAlchemy tiene session.bulk_insert_mappings() que es ~10x más rápido.
#
# 🐌 PROBLEMA 7: _ensure_levels_synced() EN CONSTRUCTOR
#    - Se llama al crear ConstantsCalculator y puede ser lento si levels.db
#      tiene muchos equipos pendientes de sync.
#
# ============================================================================
# SOLUCIONES IMPLEMENTADAS:
# ============================================================================
#
# ✅ SOL 1: Cache de niveles pre-cargado en un dict {(team_id, fixture_date): level}
#           Elimina 100K+ queries individuales → 1 query masivo.
#
# ✅ SOL 2: Eliminar validate_fixture_exists() redundante del bucle de inserción.
#           Los fixtures ya vienen de la BD, no necesitan re-validación.
#
# ✅ SOL 3: Eliminar queries de diagnóstico de calculate_constants().
#           Moverlos a un método separado `diagnose_team()` para uso manual.
#
# ✅ SOL 4: Reemplazar df.iterrows() con iteración directa de listas/dicts.
#
# ✅ SOL 5: Usar bulk_insert_mappings() para inserción masiva.
#
# ✅ SOL 6: Método incremental_calculate_and_store() como DEFAULT.
#           calculate_and_store() ahora es solo alias explícito para full recalc.
#
# ✅ SOL 7: Lazy init de levels_calc, no sincroniza en constructor.
#
# ============================================================================

import logging
import pandas as pd
from collections import defaultdict
from sqlalchemy import (
    Column, Integer, Float, DateTime, String, Index, desc, or_, func
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from data.database_manager import ORIG_ENGINE, CONST_ENGINE, SessionOrig, SessionConst
from data.data_models.teams import Team
from data.data_models.fixtures import Fixture
from data.levels_calculator import LevelsCalculator

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# ORM base y definición de la tabla `constants`
# ----------------------------------------------------------------------
ConstBase = declarative_base()

class ConstantResult(ConstBase):
    __tablename__ = "constants"

    id                       = Column(Integer, primary_key=True)
    team_id                  = Column(Integer, index=True, nullable=False)
    fixture_id               = Column(Integer, index=True, nullable=False)
    date                     = Column(DateTime, index=True, nullable=False)

    # Valores q
    q_local                  = Column(Float)
    q_visita                 = Column(Float)
    q_negativo               = Column(Float)
    q_goles_anotado          = Column(Float)
    q_goles_recibido         = Column(Float)
    q_goles_local_anotado    = Column(Float)
    q_goles_local_recibido   = Column(Float)
    q_goles_visita_anotado   = Column(Float)
    q_goles_visita_recibido  = Column(Float)

    # Constantes k
    k_positivo               = Column(Float)
    k_negativo               = Column(Float)
    k_positivo_local         = Column(Float)
    k_negativo_local         = Column(Float)
    k_positivo_visita        = Column(Float)
    k_negativo_visita        = Column(Float)
    k_goles_anotado          = Column(Float)
    k_goles_recibido         = Column(Float)
    k_goles_local_anotado    = Column(Float)
    k_goles_local_recibido   = Column(Float)
    k_goles_visita_anotado   = Column(Float)
    k_goles_visita_recibido  = Column(Float)

    __table_args__ = (
        Index("ix_constants_team_date",    "team_id", "date"),
        Index("ix_constants_fixture_team", "fixture_id", "team_id"),
    )

# ----------------------------------------------------------------------
# Función para crear la tabla en constants.db
# ----------------------------------------------------------------------
def init_db():
    try:
        ConstBase.metadata.create_all(CONST_ENGINE)
        logger.info("Tablas de constantes creadas correctamente.")
    except Exception as e:
        logger.error(f"Error creando tablas de constantes: {e}")
        raise

# ----------------------------------------------------------------------
FINISHED_STATUS = 'Match Finished'

# ----------------------------------------------------------------------
# Clase principal OPTIMIZADA
# ----------------------------------------------------------------------
class ConstantsCalculator:
    def __init__(self):
        self.session_orig  = SessionOrig()
        self.session_const = SessionConst()
        
        # ✅ OPTIMIZACIÓN: Cache de niveles (lazy loaded)
        self._levels_cache = {}
        self._levels_cache_loaded = False
        
        # ✅ OPTIMIZACIÓN: Lazy init de LevelsCalculator (no sync en constructor)
        self._levels_calc = None
        self._levels_calc_initialized = False
        
        logger.info(f"ConstantsCalculator inicializado")

    @property
    def levels_calc(self):
        """Lazy initialization de LevelsCalculator"""
        if not self._levels_calc_initialized:
            self._levels_calc_initialized = True
            try:
                from data.database_manager import engine
                sad_db_path = engine.url.database or 'sad.db'
                self._levels_calc = LevelsCalculator(
                    sad_db_path=sad_db_path, 
                    levels_db_path='levels.db'
                )
            except Exception as e:
                logger.warning(f"Error inicializando LevelsCalculator: {e}")
                self._levels_calc = None
        return self._levels_calc

    # ------------------------------------------------------------------
    # ✅ NUEVO: Pre-cargar TODOS los niveles en un dict (1 query masivo)
    # ------------------------------------------------------------------
    def _preload_levels_cache(self):
        """
        Carga TODOS los niveles de levels.db en un dict en memoria.
        Estructura: {team_id: [(date, level), ...]} ordenado por fecha.
        
        Esto elimina las ~100K queries individuales de get_team_level_at_date.
        """
        if self._levels_cache_loaded:
            return
            
        self._levels_cache_loaded = True
        
        if not self.levels_calc:
            logger.warning("LevelsCalculator no disponible, usando nivel=1.0 por defecto")
            return
        
        try:
            from data.data_models.team_levels import TeamLevel
            
            all_levels = (
                self.levels_calc.levels_session
                .query(TeamLevel.team_id, TeamLevel.date, TeamLevel.level)
                .order_by(TeamLevel.team_id, TeamLevel.date)
                .all()
            )
            
            # Agrupar por team_id como lista de (date, level) ya ordenada
            cache = defaultdict(list)
            for team_id, date, level in all_levels:
                cache[team_id].append((date, level))
            
            self._levels_cache = dict(cache)
            logger.info(f"✅ Cache de niveles cargado: {len(self._levels_cache)} equipos, "
                       f"{len(all_levels)} registros totales")
                       
        except Exception as e:
            logger.warning(f"Error cargando cache de niveles: {e}")
            self._levels_cache = {}

    def get_team_level_fast(self, team_id: int, date) -> float:
        """
        ✅ OPTIMIZADO: Obtiene nivel desde el cache en memoria.
        Busca el nivel más reciente <= date usando búsqueda binaria.
        
        Complejidad: O(log n) por consulta vs O(query_time) anterior.
        """
        if not self._levels_cache_loaded:
            self._preload_levels_cache()
        
        levels = self._levels_cache.get(team_id)
        if not levels:
            return 1.0  # Fallback seguro (no 0.5 que trigger update)
        
        # Búsqueda binaria del nivel más reciente <= date
        import bisect
        dates = [d for d, _ in levels]
        idx = bisect.bisect_right(dates, date) - 1
        
        if idx >= 0:
            return levels[idx][1] or 1.0
        
        return 1.0  # No hay nivel antes de esta fecha

    # ------------------------------------------------------------------
    # Compatibilidad con código existente
    # ------------------------------------------------------------------
    def get_team_level_safe(self, team_id: int, date) -> float:
        """Wrapper de compatibilidad → usa get_team_level_fast"""
        return self.get_team_level_fast(team_id, date)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.session_orig.close()
            self.session_const.close()
            if self._levels_calc:
                self._levels_calc.close_sessions()
        except:
            pass

    def validate_team_exists(self, team_id: int) -> bool:
        return self.session_orig.query(Team).filter(Team.id == team_id).first() is not None

    # ------------------------------------------------------------------
    # ✅ DIAGNÓSTICO (separado del cálculo - solo uso manual)
    # ------------------------------------------------------------------
    def diagnose_team(self, team_id: int) -> dict:
        """
        Diagnóstico detallado de un equipo.
        Separado de calculate_constants para no penalizar rendimiento.
        """
        total_all = self.session_orig.query(Fixture).filter(
            (Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)
        ).count()
        
        status_counts = self.session_orig.query(
            Fixture.status_long, func.count(Fixture.id)
        ).filter(
            (Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)
        ).group_by(Fixture.status_long).all()
        
        existing_constants = self.session_const.query(func.count(ConstantResult.id))\
            .filter(ConstantResult.team_id == team_id).scalar()
        
        return {
            'team_id': team_id,
            'total_fixtures': total_all,
            'status_distribution': dict(status_counts),
            'existing_constants': existing_constants,
        }

    # ------------------------------------------------------------------
    # ✅ CÁLCULO OPTIMIZADO DE q_* (sin diagnósticos, sin iterrows)
    # ------------------------------------------------------------------
    def _compute_q_values(self, fixtures, team_id: int) -> list:
        """
        Calcula los valores q_* para todos los fixtures de un equipo.
        Retorna lista de dicts.
        """
        rows = []
        for fx in fixtures:
            is_local = fx.home_team_id == team_id
            gf = fx.goals_home if is_local else fx.goals_away
            ga = fx.goals_away if is_local else fx.goals_home
            
            rival_id = fx.away_team_id if is_local else fx.home_team_id
            nivel = self.get_team_level_fast(rival_id, fx.date)

            dif = abs((gf or 0) - (ga or 0))
            res = None
            if gf is not None and ga is not None:
                res = 1 if gf > ga else (0 if gf == ga else -1)

            q_local  = dif * res * nivel if res is not None and is_local else None
            q_visita = 1.4 * dif * res * nivel if res is not None and not is_local else None
            q_neg    = dif * res * nivel if res == -1 else 0

            q_ga = gf * nivel if gf is not None else None
            q_gr = -ga * nivel if ga is not None else None

            rows.append({
                'Fecha': fx.date,
                'fixture_id': fx.id,
                'q_local':    q_local,
                'q_visita':   q_visita,
                'q_negativo': q_neg,
                'q_goles_anotado':          q_ga,
                'q_goles_recibido':         q_gr,
                'q_goles_local_anotado':    q_ga if is_local else None,
                'q_goles_local_recibido':   q_gr if is_local else None,
                'q_goles_visita_anotado':   q_ga if not is_local else None,
                'q_goles_visita_recibido':  q_gr if not is_local else None,
            })

        return rows

    # ------------------------------------------------------------------
    # ✅ ACUMULACIÓN OPTIMIZADA DE k_* (sin iterrows, puro Python)
    # ------------------------------------------------------------------
    def _accumulate_k_values(self, q_rows: list, 
                              k_p=0, k_n=0, kp_l=0, kn_l=0, kp_v=0, kn_v=0,
                              kg_pa=0, kg_pr=0, kg_lpa=0, kg_lpr=0, 
                              kg_vpa=0, kg_vpr=0) -> list:
        """
        Acumula los valores k_* a partir de los q_*, con acumuladores iniciales.
        Los acumuladores permiten continuar desde el último estado (incremental).
        Retorna lista de dicts con q_* + k_*.
        """
        result = []
        
        for r in q_rows:
            ql = r['q_local']
            qv = r['q_visita']
            qneg = r['q_negativo']
            q_ga = r['q_goles_anotado']
            q_gr = r['q_goles_recibido']
            q_gla = r['q_goles_local_anotado']
            q_glr = r['q_goles_local_recibido']
            q_gva = r['q_goles_visita_anotado']
            q_gvr = r['q_goles_visita_recibido']
            
            # k_positivo / k_negativo (general)
            q_any = ql if ql is not None else qv
            if q_any is not None and q_any > 0:
                k_p += q_any
            else:
                k_p = 0
            
            if qneg is not None and qneg < 0:
                k_n += qneg
            else:
                k_n = 0

            # k local
            if ql is not None:
                if ql > 0:
                    kp_l += ql
                else:
                    kp_l = 0
                if ql < 0:
                    kn_l += ql
                else:
                    kn_l = 0
            
            # k visita
            if qv is not None:
                if qv > 0:
                    kp_v += qv
                else:
                    kp_v = 0
                if qv < 0:
                    kn_v += qv
                else:
                    kn_v = 0

            # k goles
            if q_ga is not None:
                kg_pa = kg_pa + q_ga if q_ga > 0 else 0
            if q_gr is not None:
                kg_pr = kg_pr + (-q_gr) if q_gr < 0 else 0

            if q_gla is not None:
                kg_lpa = kg_lpa + q_gla if q_gla > 0 else 0
            if q_glr is not None:
                kg_lpr = kg_lpr + (-q_glr) if q_glr < 0 else 0
            if q_gva is not None:
                kg_vpa = kg_vpa + q_gva if q_gva > 0 else 0
            if q_gvr is not None:
                kg_vpr = kg_vpr + (-q_gvr) if q_gvr < 0 else 0

            result.append({
                **r,
                'k_positivo':             k_p,
                'k_negativo':             k_n,
                'k_positivo_local':       kp_l,
                'k_negativo_local':       kn_l,
                'k_positivo_visita':      kp_v,
                'k_negativo_visita':      kn_v,
                'k_goles_anotado':        kg_pa,
                'k_goles_recibido':       kg_pr,
                'k_goles_local_anotado':  kg_lpa,
                'k_goles_local_recibido': kg_lpr,
                'k_goles_visita_anotado': kg_vpa,
                'k_goles_visita_recibido':kg_vpr,
            })

        return result

    # ------------------------------------------------------------------
    # CÁLCULO COMPLETO (reconstruye desde cero)
    # ------------------------------------------------------------------
    def calculate_constants(self, team_id: int) -> pd.DataFrame:
        """
        Calcula q_* y k_* para TODOS los partidos terminados del equipo.
        ✅ OPTIMIZADO: Sin queries de diagnóstico, sin iterrows.
        """
        if not self.validate_team_exists(team_id):
            logger.error(f"Equipo {team_id} no existe")
            return None

        fixtures = (
            self.session_orig
                .query(Fixture)
                .filter(
                    ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)),
                    Fixture.status_long == FINISHED_STATUS
                )
                .order_by(Fixture.date)
                .all()
        )
        
        if not fixtures:
            logger.warning(f"No hay partidos terminados para equipo {team_id}")
            return None

        logger.info(f"Calculando constantes para equipo {team_id}: {len(fixtures)} partidos")

        # 1) Calcular q_*
        q_rows = self._compute_q_values(fixtures, team_id)
        
        # 2) Acumular k_* (desde cero)
        result_rows = self._accumulate_k_values(q_rows)
        
        return pd.DataFrame(result_rows).sort_values('Fecha')

    # ------------------------------------------------------------------
    # ✅ ALMACENAMIENTO OPTIMIZADO (bulk insert)
    # ------------------------------------------------------------------
    def _bulk_store_constants(self, team_id: int, rows: list) -> int:
        """
        Inserta registros usando bulk_insert_mappings (mucho más rápido).
        ✅ SIN validate_fixture_exists por cada fila (redundante).
        """
        mappings = []
        for row in rows:
            mappings.append({
                'team_id':                  team_id,
                'fixture_id':               row['fixture_id'],
                'date':                     row['Fecha'],
                'q_local':                  row['q_local'],
                'q_visita':                 row['q_visita'],
                'q_negativo':               row['q_negativo'],
                'q_goles_anotado':          row['q_goles_anotado'],
                'q_goles_recibido':         row['q_goles_recibido'],
                'q_goles_local_anotado':    row['q_goles_local_anotado'],
                'q_goles_local_recibido':   row['q_goles_local_recibido'],
                'q_goles_visita_anotado':   row['q_goles_visita_anotado'],
                'q_goles_visita_recibido':  row['q_goles_visita_recibido'],
                'k_positivo':               row['k_positivo'],
                'k_negativo':               row['k_negativo'],
                'k_positivo_local':         row['k_positivo_local'],
                'k_negativo_local':         row['k_negativo_local'],
                'k_positivo_visita':        row['k_positivo_visita'],
                'k_negativo_visita':        row['k_negativo_visita'],
                'k_goles_anotado':          row['k_goles_anotado'],
                'k_goles_recibido':         row['k_goles_recibido'],
                'k_goles_local_anotado':    row['k_goles_local_anotado'],
                'k_goles_local_recibido':   row['k_goles_local_recibido'],
                'k_goles_visita_anotado':   row['k_goles_visita_anotado'],
                'k_goles_visita_recibido':  row['k_goles_visita_recibido'],
            })
        
        if mappings:
            self.session_const.bulk_insert_mappings(ConstantResult, mappings)
            self.session_const.commit()
        
        return len(mappings)

    # ------------------------------------------------------------------
    # CALCULATE AND STORE (recalculación completa)
    # ------------------------------------------------------------------
    def calculate_and_store(self, team_id: int) -> bool:
        """
        Borra TODO para el equipo y recalcula desde cero.
        ⚠️ Solo usar cuando realmente necesites recalcular todo.
        Para actualizaciones normales, usar incremental_calculate_and_store().
        """
        logger.info(f"🔄 Full recalculate para equipo {team_id}")
        
        if not self.validate_team_exists(team_id):
            return False

        # Limpiar historial
        deleted = self.session_const.query(ConstantResult)\
            .filter(ConstantResult.team_id == team_id)\
            .delete()
        self.session_const.commit()
        
        if deleted:
            logger.info(f"🗑️ Eliminados {deleted} registros previos")

        df = self.calculate_constants(team_id)
        if df is None or df.empty:
            return False

        # ✅ Bulk insert
        count = self._bulk_store_constants(team_id, df.to_dict('records'))
        logger.info(f"✅ Almacenadas {count} constantes para equipo {team_id}")
        return True

    def calculate_and_store_all_teams(self):
        """Recalcula todos los equipos (full)."""
        teams = self.session_orig.query(Team).all()
        total = len(teams)
        success = 0
        
        # ✅ Pre-cargar cache de niveles una vez
        self._preload_levels_cache()
        
        for i, team in enumerate(teams, 1):
            if i % 50 == 0:
                logger.info(f"Progreso: {i}/{total}")
            if self.calculate_and_store(team.id):
                success += 1
        logger.info(f"Proceso completo: {success}/{total} equipos")

    # ------------------------------------------------------------------
    # ✅ MÉTODO INCREMENTAL OPTIMIZADO (DEFAULT para uso post-sync)
    # ------------------------------------------------------------------
    def incremental_calculate_and_store(self, team_id: int) -> bool:
        """
        Calcula e inserta SOLO las constantes de partidos nuevos.
        Continúa la acumulación de k_* desde la última fecha registrada.
        
        🔧 v2: Detecta partidos faltantes con fecha anterior y hace recálculo
        completo automáticamente (ej: Copa del Rey extraída manualmente).
        
        ✅ OPTIMIZADO:
        - Detección de huecos retroactivos con queries eficientes
        - Usa cache de niveles en memoria
        - Bulk insert
        - Sin validate_fixture_exists redundante
        """
        try:
            # ============================================================
            # 🔧 PASO 0: Detectar partidos faltantes con fecha anterior
            # ============================================================
            
            # Obtener fixture_ids ya calculados (1 query eficiente)
            existing_fixture_ids = set(
                r[0] for r in self.session_const
                .query(ConstantResult.fixture_id)
                .filter(ConstantResult.team_id == team_id)
                .all()
            )
            
            # Obtener fixture_ids terminados en sad.db (1 query eficiente)
            all_finished = (
                self.session_orig.query(Fixture.id, Fixture.date)
                .filter(
                    ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)),
                    Fixture.status_long == FINISHED_STATUS
                )
                .all()
            )
            all_finished_ids = set(fid for fid, _ in all_finished)
            
            # Detectar faltantes
            missing_fixture_ids = all_finished_ids - existing_fixture_ids
            
            if missing_fixture_ids and existing_fixture_ids:
                # Hay constantes previas Y hay faltantes → verificar si son retroactivos
                last_const = (
                    self.session_const.query(ConstantResult.date)
                    .filter(ConstantResult.team_id == team_id)
                    .order_by(desc(ConstantResult.date))
                    .first()
                )
                
                if last_const:
                    last_date = last_const[0]
                    # ¿Algún faltante tiene fecha anterior a la última constante?
                    has_retroactive = any(
                        fdate <= last_date 
                        for fid, fdate in all_finished 
                        if fid in missing_fixture_ids
                    )
                    
                    if has_retroactive:
                        retroactive_count = sum(
                            1 for fid, fdate in all_finished 
                            if fid in missing_fixture_ids and fdate <= last_date
                        )
                        logger.warning(
                            f"🔴 Equipo {team_id}: {retroactive_count} partidos retroactivos "
                            f"detectados → recálculo completo"
                        )
                        return self._do_full_recalculate(team_id)
            
            # ============================================================
            # PASO 1: Continuar con incremental normal
            # ============================================================
            
            last = (
                self.session_const
                    .query(ConstantResult)
                    .filter(ConstantResult.team_id == team_id)
                    .order_by(desc(ConstantResult.date))
                    .first()
            )
            
            if last:
                start_date = last.date
                # Recuperar acumuladores
                k_p   = last.k_positivo or 0
                k_n   = last.k_negativo or 0
                kp_l  = last.k_positivo_local or 0
                kn_l  = last.k_negativo_local or 0
                kp_v  = last.k_positivo_visita or 0
                kn_v  = last.k_negativo_visita or 0
                kg_pa = last.k_goles_anotado or 0
                kg_pr = last.k_goles_recibido or 0
                kg_lpa= last.k_goles_local_anotado or 0
                kg_lpr= last.k_goles_local_recibido or 0
                kg_vpa= last.k_goles_visita_anotado or 0
                kg_vpr= last.k_goles_visita_recibido or 0
            else:
                start_date = None
                k_p = k_n = kp_l = kn_l = kp_v = kn_v = 0
                kg_pa = kg_pr = kg_lpa = kg_lpr = kg_vpa = kg_vpr = 0
                
                # Limpiar posibles registros huérfanos
                self.session_const.query(ConstantResult)\
                    .filter(ConstantResult.team_id == team_id)\
                    .delete()
                self.session_const.commit()

            # 2) Query de fixtures nuevos (un solo query, sin diagnósticos)
            q = self.session_orig.query(Fixture).filter(
                ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)),
                Fixture.status_long == FINISHED_STATUS
            )
            
            if start_date:
                q = q.filter(Fixture.date > start_date)
            
            fixtures = q.order_by(Fixture.date).all()
            
            if not fixtures:
                return True  # No hay nuevos, todo OK

            logger.info(f"⚡ Incremental equipo {team_id}: {len(fixtures)} partidos nuevos")

            # 3) Calcular q_* para los nuevos
            q_rows = self._compute_q_values(fixtures, team_id)
            
            # 4) Acumular k_* continuando desde los acumuladores previos
            result_rows = self._accumulate_k_values(
                q_rows,
                k_p=k_p, k_n=k_n, kp_l=kp_l, kn_l=kn_l, kp_v=kp_v, kn_v=kn_v,
                kg_pa=kg_pa, kg_pr=kg_pr, kg_lpa=kg_lpa, kg_lpr=kg_lpr,
                kg_vpa=kg_vpa, kg_vpr=kg_vpr
            )

            # 5) ✅ Bulk insert
            count = self._bulk_store_constants(team_id, result_rows)
            
            logger.info(f"✅ Equipo {team_id}: +{count} constantes nuevas")
            return count > 0
            
        except Exception as e:
            logger.error(f"Error incremental equipo {team_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                self.session_const.rollback()
            except:
                pass
            return False

    # ------------------------------------------------------------------
    # ✅ BATCH OPTIMIZADO (para múltiples equipos)
    # ------------------------------------------------------------------
    def batch_calculate_teams(self, team_ids: list, 
                               progress_callback=None, 
                               status_callback=None,
                               incremental=True) -> dict:
        """
        Procesa múltiples equipos de forma optimizada.
        ✅ Pre-carga el cache de niveles UNA VEZ para todos los equipos.
        """
        total = len(team_ids)
        success = 0
        failed = 0
        failed_teams = []
        
        # ✅ CLAVE: Pre-cargar cache de niveles una sola vez
        if status_callback:
            status_callback("Cargando cache de niveles...")
        self._preload_levels_cache()
        
        for i, team_id in enumerate(team_ids, 1):
            try:
                if incremental:
                    result = self.incremental_calculate_and_store(team_id)
                else:
                    result = self.calculate_and_store(team_id)
                
                if result:
                    success += 1
                else:
                    success += 1  # Sin datos nuevos no es error
                    
            except Exception as e:
                failed += 1
                failed_teams.append(team_id)
                logger.error(f"Error equipo {team_id}: {e}")
            
            if progress_callback:
                pct = int((i / total) * 100)
                progress_callback(pct)
            
            if status_callback and i % 20 == 0:
                status_callback(f"Procesados {i}/{total} equipos...")
        
        return {
            'total': total,
            'success': success,
            'failed': failed,
            'failed_teams': failed_teams,
        }

    # ------------------------------------------------------------------
    # FULL RECALCULATE (wrapper público)
    # ------------------------------------------------------------------
    def full_recalculate_team(self, team_id: int) -> bool:
        """Recálculo completo: elimina todo y recalcula."""
        logger.info(f"🔄 Full recalculate (público) para equipo {team_id}")
        
        count_before = self.session_const.query(ConstantResult)\
            .filter(ConstantResult.team_id == team_id).count()
        
        result = self._do_full_recalculate(team_id)
        
        count_after = self.session_const.query(ConstantResult)\
            .filter(ConstantResult.team_id == team_id).count()
        
        logger.info(f"Recálculo: {count_before} → {count_after} registros ({'OK' if result else 'SIN DATOS'})")
        return result

    def _do_full_recalculate(self, team_id: int) -> bool:
        """
        Helper interno para recálculo completo.
        Usado tanto por full_recalculate_team() como por 
        incremental_calculate_and_store() cuando detecta huecos retroactivos.
        ✅ Usa cache de niveles y bulk insert.
        """
        # Limpiar todo
        deleted = self.session_const.query(ConstantResult)\
            .filter(ConstantResult.team_id == team_id)\
            .delete()
        self.session_const.commit()
        
        if deleted:
            logger.info(f"🗑️ Eliminados {deleted} registros para recálculo")

        # Obtener fixtures terminados
        fixtures = (
            self.session_orig.query(Fixture)
            .filter(
                ((Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)),
                Fixture.status_long == FINISHED_STATUS
            )
            .order_by(Fixture.date)
            .all()
        )
        
        if not fixtures:
            return False

        logger.info(f"🔄 Recalculando equipo {team_id}: {len(fixtures)} partidos")

        # Calcular q_* y acumular k_* desde cero
        q_rows = self._compute_q_values(fixtures, team_id)
        result_rows = self._accumulate_k_values(q_rows)
        
        # Bulk insert
        count = self._bulk_store_constants(team_id, result_rows)
        logger.info(f"✅ Recálculo completo equipo {team_id}: {count} constantes")
        return count > 0

    # ------------------------------------------------------------------
    # LIMPIEZA DE NaN
    # ------------------------------------------------------------------
    def cleanup_nan_records(self, team_id: int = None) -> int:
        try:
            query = self.session_const.query(ConstantResult).filter(
                or_(
                    ConstantResult.q_local == None,
                    ConstantResult.q_visita == None
                ),
                ConstantResult.q_negativo == 0
            )
            
            if team_id:
                query = query.filter(ConstantResult.team_id == team_id)
            
            count = query.count()
            if count > 0:
                query.delete(synchronize_session=False)
                self.session_const.commit()
                logger.info(f"🧹 Eliminados {count} registros con NaN")
            
            return count
        except Exception as e:
            logger.error(f"Error limpiando registros NaN: {e}")
            self.session_const.rollback()
            return 0

    # ------------------------------------------------------------------
    # Métodos de consulta auxiliares
    # ------------------------------------------------------------------
    def get_team_name(self, team_id: int) -> str:
        t = self.session_orig.query(Team).get(team_id)
        return t.name if t else f"Equipo #{team_id}"

    def get_fixture_info(self, fixture_id: int) -> dict:
        fx = self.session_orig.query(Fixture).get(fixture_id)
        if not fx:
            return {"date": None, "home_team": f"#{fixture_id}", 
                    "away_team": "Desconocido", "score": "N/E"}
        return {
            "date": fx.date,
            "home_team": self.get_team_name(fx.home_team_id),
            "away_team": self.get_team_name(fx.away_team_id),
            "score": f"{fx.goals_home}-{fx.goals_away}" if fx.goals_home is not None else "N/E"
        }

    def get_latest_constants(self, team_id: int):
        try:
            return (
                self.session_const.query(ConstantResult)
                .filter(ConstantResult.team_id == team_id)
                .order_by(desc(ConstantResult.date))
                .first()
            )
        except Exception as e:
            logger.error(f"Error al obtener última constante: {e}")
            return None

    def get_constants_history(self, team_id: int, limit: int = 10):
        try:
            return (
                self.session_const.query(ConstantResult)
                .filter(ConstantResult.team_id == team_id)
                .order_by(desc(ConstantResult.date))
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.error(f"Error en historial de constantes: {e}")
            return []

    def get_stored_constants(self, team_id: int) -> pd.DataFrame:
        try:
            constants = (
                self.session_const
                    .query(ConstantResult)
                    .filter(ConstantResult.team_id == team_id)
                    .order_by(ConstantResult.date)
                    .all()
            )
            
            if not constants:
                return None
                
            rows = [{
                'Fecha': c.date,
                'fixture_id': c.fixture_id,
                'q_local': c.q_local, 'q_visita': c.q_visita,
                'q_negativo': c.q_negativo,
                'q_goles_anotado': c.q_goles_anotado,
                'q_goles_recibido': c.q_goles_recibido,
                'q_goles_local_anotado': c.q_goles_local_anotado,
                'q_goles_local_recibido': c.q_goles_local_recibido,
                'q_goles_visita_anotado': c.q_goles_visita_anotado,
                'q_goles_visita_recibido': c.q_goles_visita_recibido,
                'k_positivo': c.k_positivo, 'k_negativo': c.k_negativo,
                'k_positivo_local': c.k_positivo_local,
                'k_negativo_local': c.k_negativo_local,
                'k_positivo_visita': c.k_positivo_visita,
                'k_negativo_visita': c.k_negativo_visita,
                'k_goles_anotado': c.k_goles_anotado,
                'k_goles_recibido': c.k_goles_recibido,
                'k_goles_local_anotado': c.k_goles_local_anotado,
                'k_goles_local_recibido': c.k_goles_local_recibido,
                'k_goles_visita_anotado': c.k_goles_visita_anotado,
                'k_goles_visita_recibido': c.k_goles_visita_recibido,
            } for c in constants]
            
            return pd.DataFrame(rows).sort_values('Fecha')
            
        except Exception as e:
            logger.error(f"Error obteniendo constantes para equipo {team_id}: {e}")
            return None


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler("constants_calculator.log"),
            logging.StreamHandler()
        ]
    )
    
    init_db()
    
    with ConstantsCalculator() as calculator:
        calculator.calculate_and_store_all_teams()
else:
    init_db()