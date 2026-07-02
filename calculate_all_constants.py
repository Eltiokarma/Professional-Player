# calculate_all_constants.py
"""
Script optimizado para calcular constantes de todos los equipos.
Ahora usa la versión optimizada con mejor manejo de errores y progreso.
"""

import sys
import os
import logging
from datetime import datetime

# Añadir el directorio raíz al path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from utils.constants_calculator import ConstantsCalculator
from data.data_models.teams import Team

def setup_logging():
    """Configura el sistema de logging"""
    log_filename = f"constants_calculation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Iniciando cálculo de constantes - Log: {log_filename}")
    return logger

def progress_callback(progress):
    """Callback para mostrar progreso en consola"""
    print(f"\rProgreso: {progress}%", end="", flush=True)

def status_callback(status):
    """Callback para mostrar estado en consola"""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {status}")

def main():
    """Función principal optimizada"""
    logger = setup_logging()
    
    try:
        print("🚀 CALCULADORA DE CONSTANTES OPTIMIZADA")
        print("=" * 50)
        
        # Inicializar calculadora
        logger.info("Inicializando calculadora optimizada...")
        calculator = ConstantsCalculator()
        
        # Obtener lista de equipos
        logger.info("Obteniendo lista de equipos...")
        teams = calculator.session_orig.query(Team).order_by(Team.name).all()
        total_teams = len(teams)
        
        if total_teams == 0:
            logger.warning("No se encontraron equipos en la base de datos")
            print("❌ No hay equipos para procesar")
            return
        
        print(f"📊 Total de equipos encontrados: {total_teams}")
        
        # Preguntar al usuario qué hacer
        print("\nOpciones disponibles:")
        print("1. Calcular TODOS los equipos (puede tomar mucho tiempo)")
        print("2. Calcular solo equipos sin constantes")
        print("3. Recalcular equipos específicos")
        print("4. Salir")
        
        try:
            choice = input("\nSelecciona una opción (1-4): ").strip()
        except KeyboardInterrupt:
            print("\n\n❌ Operación cancelada por el usuario")
            return
        
        if choice == "4":
            print("👋 Saliendo...")
            return
        elif choice == "1":
            # Todos los equipos
            team_ids = [team.id for team in teams]
            print(f"\n🔄 Calculando constantes para {len(team_ids)} equipos...")
        elif choice == "2":
            # Solo equipos sin constantes
            print("\n🔍 Identificando equipos sin constantes...")
            team_ids = []
            for i, team in enumerate(teams):
                print(f"\rVerificando equipo {i+1}/{total_teams}: {team.name}", end="", flush=True)
                existing = calculator.get_stored_constants(team.id)
                if existing is None or existing.empty:
                    team_ids.append(team.id)
            print(f"\n📋 Encontrados {len(team_ids)} equipos sin constantes")
        elif choice == "3":
            # Equipos específicos
            print("\nIngresa los IDs de equipos separados por coma (ej: 1,2,3):")
            try:
                ids_input = input("IDs: ").strip()
                team_ids = [int(x.strip()) for x in ids_input.split(",") if x.strip()]
                print(f"📋 Seleccionados {len(team_ids)} equipos: {team_ids}")
            except ValueError:
                print("❌ Error: IDs inválidos")
                return
        else:
            print("❌ Opción inválida")
            return
        
        if not team_ids:
            print("ℹ️ No hay equipos para procesar")
            return
        
        # Confirmar antes de proceder
        print(f"\n⚠️ Se procesarán {len(team_ids)} equipos")
        confirm = input("¿Continuar? (s/N): ").strip().lower()
        if confirm not in ['s', 'si', 'sí', 'y', 'yes']:
            print("❌ Operación cancelada")
            return
        
        # Ejecutar cálculo en lotes
        print(f"\n🚀 Iniciando procesamiento de {len(team_ids)} equipos...")
        print("=" * 50)
        
        start_time = datetime.now()
        
        # Usar el método batch optimizado
        results = calculator.batch_calculate_teams(
            team_ids,
            progress_callback,
            status_callback
        )
        
        end_time = datetime.now()
        duration = end_time - start_time
        
        # Mostrar resumen final
        print("\n" + "=" * 50)
        print("🏁 PROCESAMIENTO COMPLETADO")
        print("=" * 50)
        print(f"⏱️ Tiempo total: {duration}")
        print(f"📊 Total procesados: {results['total']}")
        print(f"✅ Exitosos: {results['success']}")
        print(f"❌ Fallidos: {results['failed']}")
        
        if results['failed'] > 0:
            print(f"\n⚠️ Equipos con errores: {results['failed_teams']}")
        
        # Calcular estadísticas
        success_rate = (results['success'] / results['total']) * 100 if results['total'] > 0 else 0
        avg_time_per_team = duration.total_seconds() / results['total'] if results['total'] > 0 else 0
        
        print(f"📈 Tasa de éxito: {success_rate:.1f}%")
        print(f"⚡ Tiempo promedio por equipo: {avg_time_per_team:.1f} segundos")
        
        logger.info(f"Procesamiento completado - Éxito: {results['success']}/{results['total']}")
        
        if results['success'] > 0:
            print(f"\n✨ Constantes calculadas y guardadas exitosamente en constants.db")
        
    except KeyboardInterrupt:
        print("\n\n❌ Operación interrumpida por el usuario")
        logger.info("Operación interrumpida por el usuario")
    except Exception as e:
        logger.error(f"Error general durante el procesamiento: {str(e)}")
        print(f"\n❌ Error inesperado: {str(e)}")
        print("📝 Revisa el archivo de log para más detalles")
    finally:
        print("\n👋 Finalizando script...")

if __name__ == "__main__":
    main()