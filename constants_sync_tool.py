#!/usr/bin/env python3
# constants_sync_tool.py
"""
Herramienta de sincronización de constantes.

Funciones:
1. Diagnóstico: Detecta equipos/fixtures sin constantes calculadas
2. Cálculo masivo: Calcula constantes faltantes para todos los equipos
3. Verificación: Muestra estadísticas de cobertura

Uso:
    python constants_sync_tool.py --diagnose       # Ver qué falta
    python constants_sync_tool.py --sync           # Calcular faltantes
    python constants_sync_tool.py --sync-league 39 # Solo una liga (ej: Premier League)
    python constants_sync_tool.py --full-recalc    # Recalcular TODO desde cero
"""

import argparse
import logging
import sys
from datetime import datetime
from typing import Dict, List, Set, Tuple
from collections import defaultdict

from sqlalchemy import func, distinct, or_, and_
from sqlalchemy.orm import sessionmaker

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("constants_sync.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Imports del proyecto
try:
    from data.database_manager import ORIG_ENGINE, CONST_ENGINE, SessionOrig, SessionConst
    from data.data_models.teams import Team
    from data.data_models.fixtures import Fixture
    from utils.constants_calculator import ConstantsCalculator, ConstantResult, init_db
except ImportError as e:
    logger.error(f"Error importando módulos: {e}")
    logger.error("Asegúrate de ejecutar desde el directorio raíz del proyecto")
    sys.exit(1)


class ConstantsSyncTool:
    """Herramienta para sincronizar y verificar constantes."""
    
    def __init__(self):
        self.session_orig = SessionOrig()
        self.session_const = SessionConst()
        
        # Asegurar que la tabla existe
        init_db()
    
    def close(self):
        """Cerrar sesiones."""
        self.session_orig.close()
        self.session_const.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # =========================================================================
    # 1. DIAGNÓSTICO
    # =========================================================================
    
    def get_all_teams_with_fixtures(self) -> Dict[int, dict]:
        """
        Obtiene todos los equipos que tienen partidos terminados.
        Returns: {team_id: {'name': str, 'fixture_count': int, 'leagues': set}}
        """
        # Equipos como local
        home_teams = (
            self.session_orig.query(
                Fixture.home_team_id,
                func.count(Fixture.id).label('count')
            )
            .filter(Fixture.status_short == 'FT')
            .group_by(Fixture.home_team_id)
            .all()
        )
        
        # Equipos como visitante
        away_teams = (
            self.session_orig.query(
                Fixture.away_team_id,
                func.count(Fixture.id).label('count')
            )
            .filter(Fixture.status_short == 'FT')
            .group_by(Fixture.away_team_id)
            .all()
        )
        
        # Combinar
        teams_data = defaultdict(lambda: {'name': '', 'fixture_count': 0, 'leagues': set()})
        
        for team_id, count in home_teams:
            if team_id:
                teams_data[team_id]['fixture_count'] += count
        
        for team_id, count in away_teams:
            if team_id:
                teams_data[team_id]['fixture_count'] += count
        
        # Obtener nombres y ligas
        for team_id in teams_data:
            team = self.session_orig.query(Team).filter(Team.id == team_id).first()
            if team:
                teams_data[team_id]['name'] = team.name
            
            # Obtener ligas donde juega
            leagues = (
                self.session_orig.query(distinct(Fixture.league_id))
                .filter(
                    or_(
                        Fixture.home_team_id == team_id,
                        Fixture.away_team_id == team_id
                    ),
                    Fixture.status_short == 'FT'
                )
                .all()
            )
            teams_data[team_id]['leagues'] = {l[0] for l in leagues if l[0]}
        
        return dict(teams_data)
    
    def get_teams_with_constants(self) -> Dict[int, int]:
        """
        Obtiene equipos que ya tienen constantes calculadas.
        Returns: {team_id: constant_count}
        """
        results = (
            self.session_const.query(
                ConstantResult.team_id,
                func.count(ConstantResult.id).label('count')
            )
            .group_by(ConstantResult.team_id)
            .all()
        )
        return {team_id: count for team_id, count in results}
    
    def diagnose(self, league_id: int = None) -> dict:
        """
        Ejecuta diagnóstico completo.
        
        Args:
            league_id: Si se especifica, solo diagnostica esa liga
            
        Returns:
            Diccionario con estadísticas y equipos faltantes
        """
        logger.info("=" * 60)
        logger.info("DIAGNÓSTICO DE CONSTANTES")
        logger.info("=" * 60)
        
        # Obtener datos
        all_teams = self.get_all_teams_with_fixtures()
        teams_with_constants = self.get_teams_with_constants()
        
        # Filtrar por liga si se especifica
        if league_id:
            all_teams = {
                tid: data for tid, data in all_teams.items()
                if league_id in data['leagues']
            }
            logger.info(f"Filtrando por liga: {league_id}")
        
        # Análisis
        total_teams = len(all_teams)
        teams_complete = 0
        teams_partial = 0
        teams_missing = 0
        
        missing_teams = []
        partial_teams = []
        
        for team_id, data in all_teams.items():
            expected_fixtures = data['fixture_count']
            actual_constants = teams_with_constants.get(team_id, 0)
            
            if actual_constants == 0:
                teams_missing += 1
                missing_teams.append({
                    'id': team_id,
                    'name': data['name'],
                    'fixtures': expected_fixtures,
                    'constants': 0,
                    'missing': expected_fixtures
                })
            elif actual_constants < expected_fixtures:
                teams_partial += 1
                partial_teams.append({
                    'id': team_id,
                    'name': data['name'],
                    'fixtures': expected_fixtures,
                    'constants': actual_constants,
                    'missing': expected_fixtures - actual_constants
                })
            else:
                teams_complete += 1
        
        # Mostrar resultados
        logger.info(f"\n📊 RESUMEN:")
        logger.info(f"   Total equipos con partidos: {total_teams}")
        logger.info(f"   ✅ Equipos completos:       {teams_complete} ({100*teams_complete/total_teams:.1f}%)")
        logger.info(f"   ⚠️  Equipos parciales:       {teams_partial} ({100*teams_partial/total_teams:.1f}%)")
        logger.info(f"   ❌ Equipos sin constantes:  {teams_missing} ({100*teams_missing/total_teams:.1f}%)")
        
        # Top equipos sin constantes
        if missing_teams:
            logger.info(f"\n❌ TOP 20 EQUIPOS SIN CONSTANTES:")
            missing_teams.sort(key=lambda x: x['fixtures'], reverse=True)
            for i, team in enumerate(missing_teams[:20], 1):
                logger.info(f"   {i:2}. {team['name'][:30]:<30} - {team['fixtures']} partidos")
        
        # Top equipos parciales
        if partial_teams:
            logger.info(f"\n⚠️  TOP 20 EQUIPOS PARCIALES:")
            partial_teams.sort(key=lambda x: x['missing'], reverse=True)
            for i, team in enumerate(partial_teams[:20], 1):
                logger.info(f"   {i:2}. {team['name'][:30]:<30} - Faltan {team['missing']}/{team['fixtures']}")
        
        # Estadísticas por liga
        if not league_id:
            logger.info(f"\n📋 ESTADÍSTICAS POR LIGA:")
            league_stats = self._get_league_stats(all_teams, teams_with_constants)
            for lid, stats in sorted(league_stats.items(), key=lambda x: x[1]['missing'], reverse=True)[:15]:
                pct = 100 * stats['with_constants'] / stats['total'] if stats['total'] > 0 else 0
                logger.info(f"   Liga {lid:4}: {stats['with_constants']:3}/{stats['total']:3} equipos ({pct:5.1f}%) - Faltan {stats['missing']}")
        
        return {
            'total_teams': total_teams,
            'complete': teams_complete,
            'partial': teams_partial,
            'missing': teams_missing,
            'missing_teams': missing_teams,
            'partial_teams': partial_teams
        }
    
    def _get_league_stats(self, all_teams: dict, teams_with_constants: dict) -> dict:
        """Obtiene estadísticas agrupadas por liga."""
        league_stats = defaultdict(lambda: {'total': 0, 'with_constants': 0, 'missing': 0})
        
        for team_id, data in all_teams.items():
            has_constants = team_id in teams_with_constants and teams_with_constants[team_id] > 0
            
            for league_id in data['leagues']:
                league_stats[league_id]['total'] += 1
                if has_constants:
                    league_stats[league_id]['with_constants'] += 1
                else:
                    league_stats[league_id]['missing'] += 1
        
        return dict(league_stats)

    # =========================================================================
    # 2. CÁLCULO MASIVO
    # =========================================================================
    
    def sync_missing_constants(
        self, 
        league_id: int = None, 
        incremental: bool = True,
        progress_callback=None
    ) -> dict:
        """
        Calcula constantes faltantes para todos los equipos.
        
        Args:
            league_id: Si se especifica, solo procesa esa liga
            incremental: Si True, solo calcula partidos nuevos; si False, recalcula todo
            progress_callback: Función callback(current, total, team_name) para progreso
            
        Returns:
            Diccionario con estadísticas de procesamiento
        """
        logger.info("=" * 60)
        logger.info("SINCRONIZACIÓN DE CONSTANTES")
        logger.info("=" * 60)
        
        # Obtener equipos a procesar
        all_teams = self.get_all_teams_with_fixtures()
        teams_with_constants = self.get_teams_with_constants()
        
        # Filtrar por liga si se especifica
        if league_id:
            all_teams = {
                tid: data for tid, data in all_teams.items()
                if league_id in data['leagues']
            }
            logger.info(f"Procesando solo liga: {league_id}")
        
        # Determinar equipos a procesar
        teams_to_process = []
        
        for team_id, data in all_teams.items():
            expected = data['fixture_count']
            actual = teams_with_constants.get(team_id, 0)
            
            if actual < expected:  # Tiene partidos sin constantes
                teams_to_process.append({
                    'id': team_id,
                    'name': data['name'],
                    'missing': expected - actual
                })
        
        # Ordenar por cantidad de faltantes (priorizar los que más faltan)
        teams_to_process.sort(key=lambda x: x['missing'], reverse=True)
        
        total = len(teams_to_process)
        logger.info(f"Equipos a procesar: {total}")
        
        if total == 0:
            logger.info("✅ Todos los equipos están sincronizados")
            return {'processed': 0, 'success': 0, 'errors': 0}
        
        # Procesar
        success = 0
        errors = 0
        
        # Usar ConstantsCalculator para el cálculo real
        with ConstantsCalculator() as calculator:
            for i, team_data in enumerate(teams_to_process, 1):
                team_id = team_data['id']
                team_name = team_data['name']
                
                if progress_callback:
                    progress_callback(i, total, team_name)
                
                logger.info(f"[{i}/{total}] Procesando: {team_name} (ID: {team_id}) - {team_data['missing']} faltantes")
                
                try:
                    if incremental:
                        result = calculator.incremental_calculate_and_store(team_id)
                    else:
                        result = calculator.calculate_and_store(team_id)
                    
                    if result:
                        success += 1
                        logger.info(f"   ✅ Completado")
                    else:
                        logger.warning(f"   ⚠️ Sin datos nuevos")
                        success += 1  # No es error, simplemente no había datos
                        
                except Exception as e:
                    errors += 1
                    logger.error(f"   ❌ Error: {e}")
        
        # Resumen
        logger.info("\n" + "=" * 60)
        logger.info("RESUMEN DE SINCRONIZACIÓN")
        logger.info("=" * 60)
        logger.info(f"   Procesados: {total}")
        logger.info(f"   Exitosos:   {success}")
        logger.info(f"   Errores:    {errors}")
        
        return {
            'processed': total,
            'success': success,
            'errors': errors
        }
    
    def full_recalculate(self, league_id: int = None, progress_callback=None) -> dict:
        """
        Recalcula TODAS las constantes desde cero.
        
        Args:
            league_id: Si se especifica, solo recalcula esa liga
            progress_callback: Función callback para progreso
            
        Returns:
            Estadísticas de procesamiento
        """
        logger.warning("⚠️ RECÁLCULO COMPLETO - Esto puede tomar mucho tiempo")
        
        # Obtener todos los equipos
        all_teams = self.get_all_teams_with_fixtures()
        
        if league_id:
            all_teams = {
                tid: data for tid, data in all_teams.items()
                if league_id in data['leagues']
            }
        
        teams_list = [
            {'id': tid, 'name': data['name']}
            for tid, data in all_teams.items()
        ]
        
        total = len(teams_list)
        logger.info(f"Recalculando {total} equipos...")
        
        success = 0
        errors = 0
        
        with ConstantsCalculator() as calculator:
            for i, team_data in enumerate(teams_list, 1):
                team_id = team_data['id']
                team_name = team_data['name']
                
                if progress_callback:
                    progress_callback(i, total, team_name)
                
                logger.info(f"[{i}/{total}] Recalculando: {team_name}")
                
                try:
                    # Usar calculate_and_store que borra y recalcula todo
                    if calculator.calculate_and_store(team_id):
                        success += 1
                    else:
                        logger.warning(f"   ⚠️ Sin datos")
                except Exception as e:
                    errors += 1
                    logger.error(f"   ❌ Error: {e}")
        
        return {
            'processed': total,
            'success': success,
            'errors': errors
        }

    # =========================================================================
    # 3. UTILIDADES
    # =========================================================================
    
    def get_league_name(self, league_id: int) -> str:
        """Obtiene nombre de liga (si está disponible)."""
        # Intentar obtener de la BD o devolver ID
        try:
            from data.data_models.leagues import League
            league = self.session_orig.query(League).filter(League.id == league_id).first()
            return league.name if league else f"Liga #{league_id}"
        except:
            return f"Liga #{league_id}"
    
    def sync_team(self, team_id: int, incremental: bool = True) -> bool:
        """Sincroniza constantes para un equipo específico."""
        with ConstantsCalculator() as calculator:
            if incremental:
                return calculator.incremental_calculate_and_store(team_id)
            else:
                return calculator.calculate_and_store(team_id)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Herramienta de sincronización de constantes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python constants_sync_tool.py --diagnose              # Ver estado actual
  python constants_sync_tool.py --diagnose --league 39  # Solo Premier League
  python constants_sync_tool.py --sync                  # Calcular faltantes
  python constants_sync_tool.py --sync --league 39      # Solo Premier League
  python constants_sync_tool.py --full-recalc           # Recalcular todo
  python constants_sync_tool.py --team 33               # Solo un equipo (Manchester United)
        """
    )
    
    parser.add_argument('--diagnose', action='store_true', 
                        help='Mostrar diagnóstico de constantes faltantes')
    parser.add_argument('--sync', action='store_true',
                        help='Calcular constantes faltantes (incremental)')
    parser.add_argument('--full-recalc', action='store_true',
                        help='Recalcular TODAS las constantes desde cero')
    parser.add_argument('--league', type=int, default=None,
                        help='Filtrar por ID de liga (ej: 39=Premier League)')
    parser.add_argument('--team', type=int, default=None,
                        help='Procesar solo un equipo específico')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Mostrar más detalles')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Si no se especifica ninguna acción, mostrar diagnóstico
    if not any([args.diagnose, args.sync, args.full_recalc, args.team]):
        args.diagnose = True
    
    with ConstantsSyncTool() as tool:
        if args.team:
            # Procesar equipo específico
            logger.info(f"Sincronizando equipo {args.team}...")
            result = tool.sync_team(args.team, incremental=True)
            if result:
                logger.info("✅ Equipo sincronizado correctamente")
            else:
                logger.warning("⚠️ No se pudieron calcular constantes")
        
        elif args.diagnose:
            tool.diagnose(league_id=args.league)
        
        elif args.sync:
            tool.sync_missing_constants(league_id=args.league, incremental=True)
        
        elif args.full_recalc:
            confirm = input("⚠️ Esto recalculará TODAS las constantes. ¿Continuar? (s/N): ")
            if confirm.lower() == 's':
                tool.full_recalculate(league_id=args.league)
            else:
                logger.info("Operación cancelada")


if __name__ == "__main__":
    main()