#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bubble_exporter.py

Exportador de Burbujas (Constantes K) para análisis visual.
Genera CSV histórico con diferenciación de liga.

NOTA: La exportación de gráficos PNG por períodos fue desactivada.
      El código está comentado al final del archivo bajo
      "SECCIÓN APARTADA — EXPORTACIÓN DE GRÁFICOS".

Autor: Gerson (desarrollado con Claude)
Fecha: Febrero 2026
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

import pandas as pd
import numpy as np

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE COLORES Y CONSTANTES
# ═══════════════════════════════════════════════════════════════════

K_COLORS = {
    'k_positivo': '#2ecc71',
    'k_negativo': '#e74c3c',
    'k_positivo_local': '#27ae60',
    'k_negativo_local': '#c0392b',
    'k_positivo_visita': '#1abc9c',
    'k_negativo_visita': '#e67e22',
    'k_goles_anotado': '#3498db',
    'k_goles_recibido': '#9b59b6',
    'k_goles_local_anotado': '#2980b9',
    'k_goles_local_recibido': '#8e44ad',
    'k_goles_visita_anotado': '#5dade2',
    'k_goles_visita_recibido': '#af7ac5',
}

K_LABELS = {
    'k_positivo': 'K+ (Rendimiento)',
    'k_negativo': 'K- (Rendimiento)',
    'k_positivo_local': 'K+ Local',
    'k_negativo_local': 'K- Local',
    'k_positivo_visita': 'K+ Visita',
    'k_negativo_visita': 'K- Visita',
    'k_goles_anotado': 'K Goles Anotados',
    'k_goles_recibido': 'K Goles Recibidos',
    'k_goles_local_anotado': 'K Goles Anotados Local',
    'k_goles_local_recibido': 'K Goles Recibidos Local',
    'k_goles_visita_anotado': 'K Goles Anotados Visita',
    'k_goles_visita_recibido': 'K Goles Recibidos Visita',
}

# Ligas internacionales (Country Name == 'World')
INTERNATIONAL_KEYWORDS = ['World']


# ═══════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════════════

def _load_leagues_csv() -> pd.DataFrame:
    """Carga el CSV de ligas buscando en varias ubicaciones."""
    possible_paths = [
        os.path.join(os.path.dirname(__file__), 'leagues2024.csv'),
        os.path.join(os.path.dirname(__file__), '..', 'leagues2024.csv'),
        os.path.join(os.path.dirname(__file__), '..', 'src', 'leagues2024.csv'),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            df = pd.read_csv(path)
            df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]
            return df
    
    logger.warning("leagues2024.csv no encontrado")
    return pd.DataFrame()


def _is_international(league_id: int, leagues_df: pd.DataFrame) -> bool:
    """Determina si una liga es internacional basado en Country Name."""
    if leagues_df.empty or league_id is None:
        return False
    match = leagues_df[leagues_df['league_id'] == league_id]
    if match.empty:
        return False
    country = str(match.iloc[0].get('country_name', '')).strip()
    return country in INTERNATIONAL_KEYWORDS


def _get_league_info(league_id: int, leagues_df: pd.DataFrame) -> Dict:
    """Obtiene nombre y tipo de liga."""
    if leagues_df.empty or league_id is None:
        return {'name': f'Liga {league_id}', 'country': '?', 'type': 'desconocido'}
    match = leagues_df[leagues_df['league_id'] == league_id]
    if match.empty:
        return {'name': f'Liga {league_id}', 'country': '?', 'type': 'desconocido'}
    row = match.iloc[0]
    country = str(row.get('country_name', '?')).strip()
    return {
        'name': str(row.get('league_name', f'Liga {league_id}')).strip(),
        'country': country,
        'type': 'internacional' if country in INTERNATIONAL_KEYWORDS else 'local',
    }


# ═══════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

class BubbleExporter:
    """
    Exporta historial CSV de las constantes K (burbujas)
    para un equipo dado.
    """
    
    def __init__(self, project_root: str = None):
        """
        Args:
            project_root: Raíz del proyecto donde están sad.db y constants.db
        """
        if project_root is None:
            # Intentar encontrar raíz
            this_dir = os.path.dirname(os.path.abspath(__file__))
            for d in [this_dir, os.path.dirname(this_dir), 
                      os.path.dirname(os.path.dirname(this_dir))]:
                if os.path.exists(os.path.join(d, 'sad.db')):
                    project_root = d
                    break
            if project_root is None:
                project_root = this_dir
        
        self.project_root = project_root
        sad_path = os.path.join(project_root, 'sad.db')
        const_path = os.path.join(project_root, 'constants.db')
        
        self.sad_engine = create_engine(f'sqlite:///{sad_path}', echo=False)
        self.const_engine = create_engine(f'sqlite:///{const_path}', echo=False)
        self.leagues_df = _load_leagues_csv()
    
    def load_team_data(self, team_id: int) -> pd.DataFrame:
        """
        Carga datos completos de constantes K con info de partidos y ligas.
        
        Returns:
            DataFrame con columnas K + fecha + fixture_id + league_id + 
            league_name + league_type + rival + resultado
        """
        # 1. Constantes desde constants.db
        q_const = text("""
            SELECT 
                date as fecha, fixture_id,
                k_positivo, k_negativo,
                k_positivo_local, k_negativo_local,
                k_positivo_visita, k_negativo_visita,
                k_goles_anotado, k_goles_recibido,
                k_goles_local_anotado, k_goles_local_recibido,
                k_goles_visita_anotado, k_goles_visita_recibido
            FROM constants
            WHERE team_id = :team_id
            ORDER BY date
        """)
        
        df = pd.read_sql_query(q_const, self.const_engine, params={'team_id': int(team_id)})
        
        if df.empty:
            logger.warning(f"Sin datos de constantes para team_id={team_id}")
            return df
        
        # 2. Info de fixtures desde sad.db
        fixture_ids = df['fixture_id'].dropna().astype(int).tolist()
        if fixture_ids:
            ids_str = ','.join(str(int(fid)) for fid in fixture_ids)
            q_fix = f"""
                SELECT 
                    f.id as fixture_id,
                    f.home_team_id, f.away_team_id,
                    f.goals_home, f.goals_away,
                    f.league_id,
                    th.name as home_name,
                    ta.name as away_name
                FROM fixtures f
                LEFT JOIN teams th ON f.home_team_id = th.id
                LEFT JOIN teams ta ON f.away_team_id = ta.id
                WHERE f.id IN ({ids_str})
            """
            df_fix = pd.read_sql_query(q_fix, self.sad_engine)
            df = df.merge(df_fix, on='fixture_id', how='left')
        
        # 3. Parsear fecha
        df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
        
        # 4. Determinar rival y resultado
        df['es_local'] = (df['home_team_id'] == team_id).astype(int)
        df['rival'] = df.apply(
            lambda r: r.get('away_name', '?') if r.get('home_team_id') == team_id 
            else r.get('home_name', '?'), axis=1
        )
        df['goles_favor'] = df.apply(
            lambda r: r.get('goals_home') if r.get('home_team_id') == team_id 
            else r.get('goals_away'), axis=1
        )
        df['goles_contra'] = df.apply(
            lambda r: r.get('goals_away') if r.get('home_team_id') == team_id 
            else r.get('goals_home'), axis=1
        )
        df['resultado'] = df.apply(
            lambda r: f"{int(r['goles_favor'])}-{int(r['goles_contra'])}" 
            if pd.notna(r.get('goles_favor')) and pd.notna(r.get('goles_contra'))
            else '?', axis=1
        )
        
        # 5. Info de liga
        if 'league_id' in df.columns:
            df['league_name'] = df['league_id'].apply(
                lambda lid: _get_league_info(lid, self.leagues_df)['name'] if pd.notna(lid) else '?'
            )
            df['league_country'] = df['league_id'].apply(
                lambda lid: _get_league_info(lid, self.leagues_df)['country'] if pd.notna(lid) else '?'
            )
            df['league_type'] = df['league_id'].apply(
                lambda lid: _get_league_info(lid, self.leagues_df)['type'] if pd.notna(lid) else '?'
            )
        else:
            df['league_name'] = '?'
            df['league_country'] = '?'
            df['league_type'] = '?'
        
        return df
    
    def get_team_name(self, team_id: int) -> str:
        """Obtiene el nombre del equipo."""
        try:
            with self.sad_engine.connect() as conn:
                r = conn.execute(
                    text("SELECT name FROM teams WHERE id = :tid"),
                    {'tid': team_id}
                ).fetchone()
            return r[0] if r else f"Equipo_{team_id}"
        except:
            return f"Equipo_{team_id}"
    
    def export_csv(self, team_id: int, output_dir: str,
                   progress_callback=None) -> str:
        """
        Exporta el CSV histórico completo de constantes K.
        
        Incluye:
        - Todas las constantes K
        - Liga, país, tipo (local/internacional)
        - Rival, resultado, localía
        
        Returns:
            Ruta al archivo CSV generado
        """
        team_name = self.get_team_name(team_id)
        safe_name = team_name.replace(' ', '_').replace('/', '_')
        
        if progress_callback:
            progress_callback(f"Cargando datos de {team_name}...", 10)
        
        df = self.load_team_data(team_id)
        if df.empty:
            return None
        
        if progress_callback:
            progress_callback("Preparando CSV...", 60)
        
        # Seleccionar y ordenar columnas para el CSV
        k_cols = [c for c in df.columns if c.startswith('k_')]
        
        export_cols = [
            'fecha', 'fixture_id',
            'league_name', 'league_country', 'league_type',
            'es_local', 'rival', 'resultado',
            'goles_favor', 'goles_contra',
        ] + sorted(k_cols)
        
        # Solo incluir columnas que existen
        export_cols = [c for c in export_cols if c in df.columns]
        
        df_export = df[export_cols].copy()
        df_export['fecha'] = df_export['fecha'].dt.strftime('%Y-%m-%d')
        
        # Renombrar para claridad
        rename_map = {
            'fecha': 'Fecha',
            'fixture_id': 'Fixture_ID',
            'league_name': 'Liga',
            'league_country': 'Pais',
            'league_type': 'Tipo_Liga',
            'es_local': 'Es_Local',
            'rival': 'Rival',
            'resultado': 'Resultado',
            'goles_favor': 'GF',
            'goles_contra': 'GC',
        }
        df_export.rename(columns=rename_map, inplace=True)
        
        # Crear directorio de salida
        os.makedirs(output_dir, exist_ok=True)
        
        filepath = os.path.join(output_dir, f"burbujas_{safe_name}_historico.csv")
        df_export.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        if progress_callback:
            progress_callback(f"CSV exportado: {len(df_export)} registros", 100)
        
        return filepath
    
    def _sync_constants(self, team_id: int, progress_callback=None):
        """
        Sincroniza constantes pendientes antes de exportar.
        Calcula incrementalmente las K de partidos que aún no están en constants.db.
        """
        try:
            if progress_callback:
                progress_callback("⚡ Sincronizando constantes...", 5)
            
            from utils.constants_calculator import ConstantsCalculator
            with ConstantsCalculator() as calc:
                calc.incremental_calculate_and_store(team_id)
            
            logger.info(f"Constantes sincronizadas para team_id={team_id}")
        except ImportError:
            logger.warning("constants_calculator no disponible, exportando con datos existentes")
        except Exception as e:
            logger.warning(f"Error sincronizando constantes: {e}, exportando con datos existentes")
    
    def export_all(self, team_id: int, output_dir: str,
                   progress_callback=None) -> Dict:
        """
        Exporta CSV histórico de constantes K.
        Sincroniza constantes pendientes antes de exportar.
        
        Returns:
            Dict con resumen completo
        """
        results = {}
        
        # Sincronizar constantes antes de exportar
        self._sync_constants(team_id, progress_callback)
        
        # Exportar CSV
        if progress_callback:
            progress_callback("Exportando CSV...", 10)
        
        team_name = self.get_team_name(team_id)
        safe_name = team_name.replace(' ', '_').replace('/', '_')
        team_dir = os.path.join(output_dir, f"burbujas_{safe_name}")
        os.makedirs(team_dir, exist_ok=True)
        
        csv_path = self.export_csv(
            team_id, 
            team_dir,
            progress_callback=progress_callback
        )
        results['csv_path'] = csv_path
        results['output_dir'] = team_dir
        results['team_name'] = team_name
        results['team_id'] = team_id
        
        if progress_callback:
            progress_callback("¡Exportación completa!", 100)
        
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# ███  SECCIÓN APARTADA — EXPORTACIÓN DE GRÁFICOS PNG POR PERÍODOS  ███
# ═══════════════════════════════════════════════════════════════════════════════
# Las siguientes secciones fueron desactivadas pero se conservan para
# posible reactivación futura. Para restaurar:
#   1. Descomentar los imports de matplotlib al inicio del archivo
#   2. Descomentar las constantes CHART_GROUPS, PERIODS, PERIOD_FOLDERS
#   3. Descomentar los métodos filter_by_period, _create_chart, export_charts
#   4. Restaurar export_all para que llame a export_charts
# ═══════════════════════════════════════════════════════════════════════════════

# --- Imports de matplotlib necesarios para gráficos ---
# import matplotlib
# matplotlib.use('Agg')  # Backend sin GUI
# import matplotlib.pyplot as plt
# import matplotlib.dates as mdates
# from matplotlib.ticker import MaxNLocator

# --- Constantes de agrupación de gráficos ---
# CHART_GROUPS = {
#     'rendimiento_general': {
#         'title': 'Rendimiento General',
#         'columns': ['k_positivo', 'k_negativo'],
#         'filename': 'rendimiento_general',
#     },
#     'rendimiento_local_visita': {
#         'title': 'Rendimiento Local vs Visita',
#         'columns': ['k_positivo_local', 'k_negativo_local',
#                      'k_positivo_visita', 'k_negativo_visita'],
#         'filename': 'rendimiento_local_visita',
#     },
#     'goles_general': {
#         'title': 'Goles General',
#         'columns': ['k_goles_anotado', 'k_goles_recibido'],
#         'filename': 'goles_general',
#     },
#     'goles_local': {
#         'title': 'Goles como Local',
#         'columns': ['k_goles_local_anotado', 'k_goles_local_recibido'],
#         'filename': 'goles_local',
#     },
#     'goles_visita': {
#         'title': 'Goles como Visitante',
#         'columns': ['k_goles_visita_anotado', 'k_goles_visita_recibido'],
#         'filename': 'goles_visita',
#     },
#     'todas': {
#         'title': 'Todas las Constantes K',
#         'columns': list(K_COLORS.keys()),
#         'filename': 'todas_las_k',
#     },
# }
#
# PERIODS = {
#     '3m': {'label': '3 Meses', 'days': 90},
#     '6m': {'label': '6 Meses', 'days': 180},
#     '12m': {'label': '12 Meses', 'days': 365},
#     'all': {'label': 'Histórico', 'days': None},
# }
#
# # Agrupación de carpetas: 3m y 6m juntos, 12m y all juntos
# PERIOD_FOLDERS = {
#     '3m': 'corto_plazo_3m_6m',
#     '6m': 'corto_plazo_3m_6m',
#     '12m': 'largo_plazo_12m_historico',
#     'all': 'largo_plazo_12m_historico',
# }

# --- Método: filter_by_period ---
#     def filter_by_period(self, df: pd.DataFrame, period_key: str) -> pd.DataFrame:
#         """Filtra el DataFrame por período temporal."""
#         if period_key == 'all' or PERIODS[period_key]['days'] is None:
#             return df
#         cutoff = datetime.now() - timedelta(days=PERIODS[period_key]['days'])
#         return df[df['fecha'] >= cutoff].copy()

# --- Método: _create_chart ---
#     def _create_chart(self, df: pd.DataFrame, columns: List[str],
#                       title: str, team_name: str, period_label: str,
#                       filepath: str):
#         """
#         Genera un gráfico de burbujas (constantes K) con estilo profesional.
#
#         Incluye:
#         - Línea de cada K con su color
#         - Línea de referencia en y=0
#         - Marcadores de partidos internacionales (triángulo)
#         - Fondo gris suave para partidos como visitante
#         - Eje X con fechas
#         """
#         # Filtrar columnas disponibles
#         available = [c for c in columns if c in df.columns and not df[c].isna().all()]
#         if not available:
#             logger.warning(f"Sin columnas disponibles para {title}")
#             return False
#
#         fig, ax = plt.subplots(figsize=(16, 6), dpi=120)
#         fig.patch.set_facecolor('#fafafa')
#         ax.set_facecolor('#ffffff')
#
#         x = df['fecha'].values
#
#         # Línea de referencia en y=0
#         ax.axhline(y=0, color='#999999', linewidth=0.8, linestyle='--', alpha=0.6)
#
#         # Marcar zonas de visitante con fondo gris suave
#         if 'es_local' in df.columns:
#             for i, row in df.iterrows():
#                 idx = df.index.get_loc(i)
#                 if row.get('es_local', 1) == 0 and idx < len(x):
#                     ax.axvspan(
#                         mdates.date2num(pd.Timestamp(x[idx])) - 0.5,
#                         mdates.date2num(pd.Timestamp(x[idx])) + 0.5,
#                         alpha=0.04, color='#e0e0e0', zorder=0
#                     )
#
#         # Plotear cada constante K
#         for col in available:
#             y = df[col].values
#             color = K_COLORS.get(col, '#333333')
#             label = K_LABELS.get(col, col)
#             ax.plot(x, y, color=color, linewidth=2.0, label=label, alpha=0.9, zorder=2)
#
#         # Marcar partidos internacionales con triángulo
#         if 'league_type' in df.columns:
#             intl_mask = df['league_type'] == 'internacional'
#             if intl_mask.any():
#                 intl_df = df[intl_mask]
#                 ref_col = available[0]
#                 ax.scatter(
#                     intl_df['fecha'].values,
#                     intl_df[ref_col].values,
#                     marker='^', s=50, color='#ff6b6b', zorder=3,
#                     label='Internacional', edgecolors='#333', linewidths=0.5
#                 )
#
#         # Formato
#         ax.set_title(f"{team_name} — {title} ({period_label})",
#                      fontsize=14, fontweight='bold', pad=12)
#         ax.set_xlabel('Fecha', fontsize=10)
#         ax.set_ylabel('Valor K', fontsize=10)
#
#         ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
#         ax.xaxis.set_major_locator(mdates.AutoDateLocator())
#         fig.autofmt_xdate(rotation=30)
#
#         ax.legend(loc='upper left', fontsize=8, framealpha=0.9)
#         ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
#         ax.spines['top'].set_visible(False)
#         ax.spines['right'].set_visible(False)
#
#         plt.tight_layout()
#         fig.savefig(filepath, dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
#         plt.close(fig)
#
#         return True

# --- Método: export_charts ---
#     def export_charts(self, team_id: int, output_dir: str,
#                       periods: List[str] = None,
#                       groups: List[str] = None,
#                       progress_callback=None) -> Dict:
#         """
#         Exporta todos los gráficos de burbujas para un equipo.
#
#         Args:
#             team_id: ID del equipo
#             output_dir: Directorio de salida
#             periods: Lista de períodos ['3m', '6m', '12m', 'all']
#             groups: Lista de grupos de gráficos (None = todos)
#             progress_callback: Función callback(message, percent)
#
#         Returns:
#             Dict con resumen de archivos generados
#         """
#         if periods is None:
#             periods = list(PERIODS.keys())
#         if groups is None:
#             groups = list(CHART_GROUPS.keys())
#
#         team_name = self.get_team_name(team_id)
#         safe_name = team_name.replace(' ', '_').replace('/', '_')
#
#         # Crear subdirectorio para el equipo
#         team_dir = os.path.join(output_dir, f"burbujas_{safe_name}")
#         os.makedirs(team_dir, exist_ok=True)
#
#         if progress_callback:
#             progress_callback(f"Cargando datos de {team_name}...", 5)
#
#         # Cargar datos
#         df_full = self.load_team_data(team_id)
#         if df_full.empty:
#             return {'error': f'Sin datos para {team_name}', 'files': []}
#
#         total_charts = len(periods) * len(groups)
#         generated = []
#         chart_num = 0
#
#         for period_key in periods:
#             period_info = PERIODS[period_key]
#             df_period = self.filter_by_period(df_full, period_key)
#
#             if df_period.empty:
#                 continue
#
#             # Subdirectorio agrupado (3m+6m juntos, 12m+all juntos)
#             folder_name = PERIOD_FOLDERS.get(period_key, period_key)
#             period_dir = os.path.join(team_dir, folder_name)
#             os.makedirs(period_dir, exist_ok=True)
#
#             for group_key in groups:
#                 chart_num += 1
#                 group = CHART_GROUPS[group_key]
#
#                 filename = f"{safe_name}_{group['filename']}_{period_key}.png"
#                 filepath = os.path.join(period_dir, filename)
#
#                 if progress_callback:
#                     pct = int(10 + (chart_num / total_charts) * 70)
#                     progress_callback(
#                         f"{period_info['label']}: {group['title']}...", pct
#                     )
#
#                 success = self._create_chart(
#                     df=df_period,
#                     columns=group['columns'],
#                     title=group['title'],
#                     team_name=team_name,
#                     period_label=period_info['label'],
#                     filepath=filepath,
#                 )
#
#                 if success:
#                     generated.append(filepath)
#
#         return {
#             'team_name': team_name,
#             'team_id': team_id,
#             'output_dir': team_dir,
#             'files': generated,
#             'total_charts': len(generated),
#         }