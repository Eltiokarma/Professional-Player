# src/utils/levels_calculator.py
"""
Calculadora inteligente de niveles históricos de equipos.
Maneja comparación eficiente entre sad.db y levels.db para calcular solo lo necesario.
Mantiene consistencia en los cálculos de ventanas móviles.
"""
import logging
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple
from sqlalchemy import create_engine, or_, and_, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from data.database_manager import SessionOrig
from data.data_models.fixtures import Fixture
from data.data_models.teams import Team
from data.data_models.team_levels import Base as LevelBase, TeamLevel

logger = logging.getLogger(__name__)

class LevelsCalculator:
    """
    Calculadora inteligente de niveles que:
    1. Compara sad.db vs levels.db para identificar cambios
    2. Recalcula solo equipos afectados manteniendo consistencia
    3. Maneja ventanas móviles correctamente
    4. Optimiza rendimiento con cálculos incrementales
    """
    
    def __init__(self, sad_db_path: str = 'sad.db', levels_db_path: str = 'levels.db'):
        """
        Inicializa las conexiones a ambas bases de datos.
        
        Args:
            sad_db_path: Ruta a la base de datos fuente (fixtures y equipos)
            levels_db_path: Ruta a la base de datos de niveles calculados
        """
        # Configurar sesión para sad.db
        self.sad_engine = create_engine(f'sqlite:///{sad_db_path}', echo=False)
        SadSession = sessionmaker(bind=self.sad_engine)
        self.sad_session = SadSession()

        # Configurar sesión para levels.db
        self.levels_engine = create_engine(f'sqlite:///{levels_db_path}', echo=False)
        LevelBase.metadata.create_all(bind=self.levels_engine, checkfirst=True)
        LevelsSession = sessionmaker(bind=self.levels_engine)
        self.levels_session = LevelsSession()
        
        logger.info("LevelsCalculator inicializado correctamente")

    def get_fixture_signature(self, fixture_id: int) -> Optional[Tuple]:
        """
        Obtiene la 'firma' de un fixture para detectar cambios.
        Incluye: fecha, equipos, goles, estado
        """
        fixture = self.sad_session.query(Fixture).filter(Fixture.id == fixture_id).first()
        if not fixture:
            return None
        
        return (
            fixture.date,
            fixture.home_team_id,
            fixture.away_team_id,
            fixture.goals_home,
            fixture.goals_away,
            fixture.status_long
        )

    def detect_changes(self) -> Dict[str, Set[int]]:
        """
        Detecta todos los cambios entre sad.db y levels.db.
        
        Returns:
            Dict con:
            - 'new_fixtures': fixtures nuevos en sad.db
            - 'modified_fixtures': fixtures modificados
            - 'teams_affected': equipos que necesitan recálculo
        """
        # Obtener fixtures finalizados de sad.db
        sad_fixtures = self.sad_session.query(
            Fixture.id, Fixture.date, Fixture.home_team_id, 
            Fixture.away_team_id, Fixture.goals_home, Fixture.goals_away
        ).filter(Fixture.status_long == 'Match Finished').all()
        
        # Obtener fixtures ya procesados en levels.db
        processed_fixtures = self.levels_session.query(
            TeamLevel.fixture_id
        ).distinct().all()
        
        processed_fixture_ids = {fid for (fid,) in processed_fixtures}
        
        new_fixtures = set()
        modified_fixtures = set()
        teams_affected = set()
        
        for fx in sad_fixtures:
            if fx.id not in processed_fixture_ids:
                # Fixture completamente nuevo
                new_fixtures.add(fx.id)
                teams_affected.add(fx.home_team_id)
                teams_affected.add(fx.away_team_id)
            else:
                # Verificar si el fixture fue modificado
                # (Para simplificar, asumimos que fixtures procesados no cambian)
                # En un sistema real, aquí compararías con datos guardados
                pass
        
        logger.info(f"Detectados: {len(new_fixtures)} fixtures nuevos, "
                   f"{len(teams_affected)} equipos afectados")
        
        return {
            'new_fixtures': new_fixtures,
            'modified_fixtures': modified_fixtures,
            'teams_affected': teams_affected
        }

    def _get_team_fixtures(self, team_id: int) -> List[Fixture]:
        """
        Obtiene todos los fixtures finalizados de un equipo, ordenados por fecha.
        """
        return (
            self.sad_session
            .query(Fixture)
            .filter(
                or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id),
                Fixture.status_long == 'Match Finished'
            )
            .order_by(Fixture.date)
            .all()
        )

    def _process_fixture(self, fixture: Fixture, team_id: int) -> Optional[Dict]:
        """
        Procesa un fixture para extraer datos necesarios para el cálculo de nivel.
        
        Args:
            fixture: Objeto Fixture de SQLAlchemy
            team_id: ID del equipo desde cuya perspectiva procesar
            
        Returns:
            Dict con datos del fixture o None si hay datos inválidos
        """
        is_home = fixture.home_team_id == team_id
        goals_for = fixture.goals_home if is_home else fixture.goals_away
        goals_against = fixture.goals_away if is_home else fixture.goals_home
        
        # Validar que los goles no sean None
        if goals_for is None or goals_against is None:
            return None
        
        goal_difference = goals_for - goals_against
        
        # Calcular puntos: 3 victoria, 1 empate, 0 derrota
        if goals_for > goals_against:
            points = 3
        elif goals_for == goals_against:
            points = 1
        else:
            points = 0
        
        return {
            'fixture_id': fixture.id,
            'date': fixture.date,
            'goal_difference': goal_difference,
            'goals_for': goals_for,
            'goals_against': goals_against,
            'points': points
        }

    def _calculate_team_levels_complete(self, team_id: int) -> List[Dict]:
        """
        Calcula el historial completo de niveles para un equipo.
        
        Lógica:
        - Partidos 1-19: No hay nivel (o nivel por defecto 0.5)
        - Partido 20+: Nivel basado en últimos 20 partidos
        - Componente puntos: promedio de puntos en últimos 20
        - Componente goles: diferencia promedio en últimos 5 / total goles últimos 5
        
        Args:
            team_id: ID del equipo
            
        Returns:
            Lista de dicts con 'fixture_id', 'date', 'level'
        """
        fixtures = self._get_team_fixtures(team_id)
        processed_data = []
        
        # Procesar cada fixture
        for fixture in fixtures:
            data = self._process_fixture(fixture, team_id)
            if data:  # Solo añadir si los datos son válidos
                processed_data.append(data)
        
        levels_history = []
        
        # Si hay menos de 20 partidos, asignar nivel por defecto
        if len(processed_data) < 20:
            for data in processed_data:
                levels_history.append({
                    'fixture_id': data['fixture_id'],
                    'date': data['date'],
                    'level': 0.5
                })
            return levels_history
        
        # Calcular niveles para partidos 20+
        for i in range(len(processed_data)):
            if i < 19:  # Primeros 19 partidos sin nivel calculado aún
                continue
                
            # Obtener últimos 20 partidos (índices i-19 a i inclusive)
            last_20_matches = processed_data[i-19:i+1]
            
            # Componente de puntos: promedio de puntos en últimos 20
            points_component = sum(match['points'] for match in last_20_matches) / 20
            
            # Componente de goles: últimos 5 partidos
            last_5_matches = last_20_matches[-5:]
            total_goals_last_5 = sum(
                match['goals_for'] + match['goals_against'] 
                for match in last_5_matches
            )
            
            if total_goals_last_5 > 0:
                goals_component = sum(
                    match['goal_difference'] for match in last_5_matches
                ) / total_goals_last_5
            else:
                goals_component = 0
            
            # Nivel final: puntos + goles + constante
            level = points_component + goals_component + 1
            
            # En el partido 20 (índice 19), asignar este nivel a todos los primeros 20 partidos
            if i == 19:
                for j in range(20):
                    levels_history.append({
                        'fixture_id': processed_data[j]['fixture_id'],
                        'date': processed_data[j]['date'],
                        'level': level
                    })
            else:
                # Para partidos posteriores, solo asignar al partido actual
                levels_history.append({
                    'fixture_id': processed_data[i]['fixture_id'],
                    'date': processed_data[i]['date'],
                    'level': level
                })
        
        return levels_history

    def update_team_levels(self, team_id: int) -> int:
        """
        Actualiza todos los niveles de un equipo específico.
        Elimina registros existentes y recalcula todo para mantener consistencia.
        
        Args:
            team_id: ID del equipo a actualizar
            
        Returns:
            Número de registros insertados
        """
        try:
            # Eliminar registros existentes del equipo
            deleted_count = self.levels_session.query(TeamLevel).filter(
                TeamLevel.team_id == team_id
            ).delete()
            
            # Calcular nuevos niveles
            levels_data = self._calculate_team_levels_complete(team_id)
            
            # Insertar nuevos registros
            team_levels = []
            for level_data in levels_data:
                team_level = TeamLevel(
                    team_id=team_id,
                    fixture_id=level_data['fixture_id'],
                    date=level_data['date'],
                    level=level_data['level']
                )
                team_levels.append(team_level)
            
            if team_levels:
                self.levels_session.bulk_save_objects(team_levels)
            
            self.levels_session.commit()
            
            logger.info(f"Equipo {team_id}: eliminados {deleted_count}, "
                       f"insertados {len(team_levels)} registros")
            
            return len(team_levels)
            
        except Exception as e:
            self.levels_session.rollback()
            logger.error(f"Error actualizando equipo {team_id}: {e}")
            raise

    def calculate_missing_levels(self) -> Dict[str, int]:
        """
        Calcula solo los niveles faltantes de forma inteligente.
        
        Returns:
            Dict con estadísticas del proceso
        """
        changes = self.detect_changes()
        teams_to_update = changes['teams_affected']
        
        if not teams_to_update:
            logger.info("No hay equipos que necesiten actualización")
            return {'teams_updated': 0, 'records_inserted': 0}
        
        logger.info(f"Iniciando actualización de {len(teams_to_update)} equipos")
        
        teams_updated = 0
        total_records = 0
        
        for team_id in teams_to_update:
            try:
                records_inserted = self.update_team_levels(team_id)
                teams_updated += 1
                total_records += records_inserted
                
                # Commit por lotes para mejorar rendimiento
                if teams_updated % 10 == 0:
                    logger.info(f"Procesados {teams_updated}/{len(teams_to_update)} equipos")
                    
            except Exception as e:
                logger.error(f"Error procesando equipo {team_id}: {e}")
                # Continúa con el siguiente equipo
        
        result = {
            'teams_updated': teams_updated,
            'records_inserted': total_records,
            'new_fixtures': len(changes['new_fixtures'])
        }
        
        logger.info(f"Actualización completada: {result}")
        return result

    def force_recalculate_all(self) -> Dict[str, int]:
        """
        Fuerza el recálculo completo de todos los niveles.
        Usar solo cuando sea necesario reconstruir todo desde cero.
        
        Returns:
            Dict con estadísticas del proceso
        """
        logger.info("Iniciando recálculo completo de todos los niveles")
        
        # Limpiar completamente la tabla
        deleted_count = self.levels_session.query(TeamLevel).delete()
        self.levels_session.commit()
        logger.info(f"Eliminados {deleted_count} registros existentes")
        
        # Obtener todos los equipos
        teams = self.sad_session.query(Team).all()
        
        teams_processed = 0
        total_records = 0
        
        for team in teams:
            try:
                records_inserted = self.update_team_levels(team.id)
                teams_processed += 1
                total_records += records_inserted
                
                # Log de progreso
                if teams_processed % 20 == 0:
                    logger.info(f"Procesados {teams_processed}/{len(teams)} equipos")
                    
            except Exception as e:
                logger.error(f"Error procesando equipo {team.id}: {e}")
        
        result = {
            'teams_processed': teams_processed,
            'total_teams': len(teams),
            'records_inserted': total_records,
            'records_deleted': deleted_count
        }
        
        logger.info(f"Recálculo completo terminado: {result}")
        return result

    def get_team_level_at_date(self, team_id: int, date) -> float:
        """
        Obtiene el nivel más reciente de un equipo hasta una fecha específica.
        
        Args:
            team_id: ID del equipo
            date: Fecha límite (datetime o string ISO)
            
        Returns:
            Nivel del equipo (float), 0.5 por defecto si no hay datos
        """
        if isinstance(date, str):
            date = datetime.fromisoformat(date)
            
        record = (
            self.levels_session.query(TeamLevel)
            .filter(
                TeamLevel.team_id == team_id,
                TeamLevel.date <= date
            )
            .order_by(TeamLevel.date.desc())
            .first()
        )
        
        return record.level if record else 0.5

    def calculate_current_levels(self) -> Dict[int, float]:
        """
        Calcula los niveles actuales de todos los equipos.
        Primero actualiza automáticamente los niveles faltantes.
        
        Returns:
            Dict {team_id: nivel_actual}
        """
        # Actualizar niveles faltantes automáticamente
        self.calculate_missing_levels()
        
        # Obtener niveles actuales
        now = datetime.now()
        team_ids = [
            team_id for (team_id,) in 
            self.levels_session.query(TeamLevel.team_id).distinct()
        ]
        
        return {
            team_id: self.get_team_level_at_date(team_id, now) 
            for team_id in team_ids
        }

    def get_comprehensive_statistics(self) -> Dict:
        """
        Obtiene estadísticas detalladas del estado de ambas bases de datos.
        
        Returns:
            Dict con estadísticas completas
        """
        try:
            # Estadísticas de sad.db
            total_fixtures = self.sad_session.query(Fixture).filter(
                Fixture.status_long == 'Match Finished'
            ).count()
            
            total_teams = self.sad_session.query(Team).count()
            
            # Fixtures por equipo
            fixtures_per_team = self.sad_session.query(
                func.count(Fixture.id)
            ).filter(Fixture.status_long == 'Match Finished').scalar() // total_teams if total_teams > 0 else 0
            
            # Estadísticas de levels.db
            processed_fixtures = self.levels_session.query(TeamLevel.fixture_id).distinct().count()
            teams_with_levels = self.levels_session.query(TeamLevel.team_id).distinct().count()
            total_level_records = self.levels_session.query(TeamLevel).count()
            
            # Cambios pendientes
            changes = self.detect_changes()
            
            # Calcular porcentajes
            completion_percentage = (
                (processed_fixtures / total_fixtures * 100) 
                if total_fixtures > 0 else 0
            )
            
            teams_coverage = (
                (teams_with_levels / total_teams * 100) 
                if total_teams > 0 else 0
            )
            
            return {
                'sad_db': {
                    'total_fixtures': total_fixtures,
                    'total_teams': total_teams,
                    'avg_fixtures_per_team': fixtures_per_team
                },
                'levels_db': {
                    'processed_fixtures': processed_fixtures,
                    'teams_with_levels': teams_with_levels,
                    'total_level_records': total_level_records
                },
                'pending_changes': {
                    'new_fixtures': len(changes['new_fixtures']),
                    'teams_affected': len(changes['teams_affected'])
                },
                'completion': {
                    'fixture_completion_percentage': round(completion_percentage, 2),
                    'team_coverage_percentage': round(teams_coverage, 2)
                },
                'sync_status': 'UP_TO_DATE' if len(changes['teams_affected']) == 0 else 'NEEDS_UPDATE'
            }
            
        except Exception as e:
            logger.error(f"Error calculando estadísticas: {e}")
            return {'error': str(e)}

    def close_sessions(self):
        """Cierra todas las sesiones de base de datos."""
        try:
            self.sad_session.close()
            self.levels_session.close()
            logger.info("Sesiones de base de datos cerradas correctamente")
        except Exception as e:
            logger.error(f"Error cerrando sesiones: {e}")


# Utilidades para uso directo
def quick_update_levels(sad_db_path: str = 'sad.db', levels_db_path: str = 'levels.db') -> Dict:
    """
    Función de conveniencia para actualizar niveles rápidamente.
    
    Args:
        sad_db_path: Ruta a la BD fuente
        levels_db_path: Ruta a la BD de niveles
        
    Returns:
        Estadísticas del proceso
    """
    calculator = None
    try:
        calculator = LevelsCalculator(sad_db_path, levels_db_path)
        result = calculator.calculate_missing_levels()
        stats = calculator.get_comprehensive_statistics()
        
        return {
            'update_result': result,
            'final_statistics': stats
        }
    finally:
        if calculator:
            calculator.close_sessions()


def get_current_team_levels(sad_db_path: str = 'sad.db', levels_db_path: str = 'levels.db') -> Dict[int, float]:
    """
    Función de conveniencia para obtener niveles actuales de todos los equipos.
    
    Args:
        sad_db_path: Ruta a la BD fuente
        levels_db_path: Ruta a la BD de niveles
        
    Returns:
        Dict {team_id: nivel_actual}
    """
    calculator = None
    try:
        calculator = LevelsCalculator(sad_db_path, levels_db_path)
        return calculator.calculate_current_levels()
    finally:
        if calculator:
            calculator.close_sessions()


# Ejemplo de uso
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Usar la función de conveniencia
    result = quick_update_levels('sad.db', 'levels.db')
    
    print("=== RESULTADO DE ACTUALIZACIÓN ===")
    print(f"Equipos actualizados: {result['update_result']['teams_updated']}")
    print(f"Registros insertados: {result['update_result']['records_inserted']}")
    print(f"Fixtures nuevos: {result['update_result']['new_fixtures']}")
    
    print("\n=== ESTADÍSTICAS FINALES ===")
    stats = result['final_statistics']
    print(f"Estado de sincronización: {stats['sync_status']}")
    print(f"Cobertura de equipos: {stats['completion']['team_coverage_percentage']}%")
    print(f"Fixtures procesados: {stats['completion']['fixture_completion_percentage']}%")
    
    # Obtener niveles actuales
    current_levels = get_current_team_levels('sad.db', 'levels.db')
    print(f"\nNiveles calculados para {len(current_levels)} equipos")