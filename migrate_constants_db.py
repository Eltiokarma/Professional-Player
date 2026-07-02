#!/usr/bin/env python3
# migrate_constants_db.py
"""
🔧 Script de migración y diagnóstico para constants.db

Uso:
    python migrate_constants_db.py --diagnose    # Ver estado actual
    python migrate_constants_db.py --migrate     # Añadir columnas faltantes
    python migrate_constants_db.py --recalc-all  # Recalcular todo desde cero
    python migrate_constants_db.py --recalc-team 123  # Recalcular un equipo
"""

import sqlite3
import argparse
import os
import sys

# Ajustar path si es necesario
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Columnas esperadas en la tabla constants
EXPECTED_COLUMNS = {
    'id': 'INTEGER PRIMARY KEY',
    'team_id': 'INTEGER NOT NULL',
    'fixture_id': 'INTEGER NOT NULL', 
    'date': 'DATETIME NOT NULL',
    # Valores Q
    'q_local': 'FLOAT',
    'q_visita': 'FLOAT',
    'q_negativo': 'FLOAT',
    'q_goles_anotado': 'FLOAT',
    'q_goles_recibido': 'FLOAT',
    'q_goles_local_anotado': 'FLOAT',
    'q_goles_local_recibido': 'FLOAT',
    'q_goles_visita_anotado': 'FLOAT',
    'q_goles_visita_recibido': 'FLOAT',
    # Valores K
    'k_positivo': 'FLOAT',
    'k_negativo': 'FLOAT',
    'k_positivo_local': 'FLOAT',
    'k_negativo_local': 'FLOAT',
    'k_positivo_visita': 'FLOAT',
    'k_negativo_visita': 'FLOAT',
    'k_goles_anotado': 'FLOAT',
    'k_goles_recibido': 'FLOAT',
    'k_goles_local_anotado': 'FLOAT',
    'k_goles_local_recibido': 'FLOAT',
    'k_goles_visita_anotado': 'FLOAT',
    'k_goles_visita_recibido': 'FLOAT',
}


def get_db_path():
    """Obtiene la ruta a constants.db"""
    # Intentar diferentes ubicaciones
    paths = [
        'constants.db',
        '../constants.db',
        '../../constants.db',
        os.path.join(os.path.dirname(__file__), '..', '..', 'constants.db'),
    ]
    
    for path in paths:
        if os.path.exists(path):
            return os.path.abspath(path)
    
    # Intentar desde database_manager
    try:
        from data.database_manager import CONST_DB_PATH
        if os.path.exists(CONST_DB_PATH):
            return CONST_DB_PATH
    except ImportError:
        pass
    
    return 'constants.db'  # Default


def diagnose(db_path: str):
    """🔍 Diagnostica el estado de constants.db"""
    print(f"\n{'='*60}")
    print(f"🔍 DIAGNÓSTICO DE constants.db")
    print(f"{'='*60}")
    print(f"📁 Ruta: {db_path}")
    print(f"📊 Existe: {os.path.exists(db_path)}")
    
    if not os.path.exists(db_path):
        print("\n❌ La base de datos no existe!")
        return False
    
    print(f"📏 Tamaño: {os.path.getsize(db_path) / 1024:.2f} KB")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Verificar si existe la tabla
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='constants'")
    if not cursor.fetchone():
        print("\n❌ La tabla 'constants' no existe!")
        conn.close()
        return False
    
    # Obtener columnas actuales
    cursor.execute("PRAGMA table_info(constants)")
    current_columns = {row[1]: row[2] for row in cursor.fetchall()}
    
    print(f"\n📋 COLUMNAS ACTUALES ({len(current_columns)}):")
    print("-" * 40)
    
    missing_columns = []
    for col_name, col_type in EXPECTED_COLUMNS.items():
        if col_name in current_columns:
            print(f"  ✅ {col_name}: {current_columns[col_name]}")
        else:
            print(f"  ❌ {col_name}: FALTANTE (debería ser {col_type})")
            missing_columns.append((col_name, col_type))
    
    # Estadísticas de datos
    print(f"\n📊 ESTADÍSTICAS DE DATOS:")
    print("-" * 40)
    
    cursor.execute("SELECT COUNT(*) FROM constants")
    total_records = cursor.fetchone()[0]
    print(f"  Total registros: {total_records:,}")
    
    cursor.execute("SELECT COUNT(DISTINCT team_id) FROM constants")
    unique_teams = cursor.fetchone()[0]
    print(f"  Equipos únicos: {unique_teams:,}")
    
    # Verificar valores NULL/NaN en columnas q_*
    print(f"\n📈 ANÁLISIS DE VALORES Q (si existen):")
    print("-" * 40)
    
    q_columns = [c for c in current_columns if c.startswith('q_')]
    if q_columns:
        for col in q_columns:
            cursor.execute(f"SELECT COUNT(*) FROM constants WHERE {col} IS NULL")
            null_count = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM constants WHERE {col} IS NOT NULL")
            not_null_count = cursor.fetchone()[0]
            pct_null = (null_count / total_records * 100) if total_records > 0 else 0
            print(f"  {col}: {not_null_count:,} con valor, {null_count:,} NULL ({pct_null:.1f}%)")
    else:
        print("  ⚠️ No hay columnas q_* en la tabla!")
    
    # Verificar valores K
    print(f"\n📈 ANÁLISIS DE VALORES K:")
    print("-" * 40)
    
    k_columns = [c for c in current_columns if c.startswith('k_')]
    if k_columns:
        for col in k_columns[:4]:  # Solo mostrar los primeros 4 para no saturar
            cursor.execute(f"SELECT COUNT(*) FROM constants WHERE {col} IS NULL")
            null_count = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM constants WHERE {col} IS NOT NULL")
            not_null_count = cursor.fetchone()[0]
            print(f"  {col}: {not_null_count:,} con valor, {null_count:,} NULL")
        if len(k_columns) > 4:
            print(f"  ... y {len(k_columns) - 4} columnas más")
    
    # Muestra de datos
    print(f"\n📋 MUESTRA DE DATOS (últimos 5 registros):")
    print("-" * 40)
    
    try:
        cursor.execute("""
            SELECT team_id, date, q_local, q_visita, k_positivo, k_negativo 
            FROM constants 
            ORDER BY date DESC 
            LIMIT 5
        """)
        rows = cursor.fetchall()
        print(f"  {'team_id':<10} {'date':<20} {'q_local':<10} {'q_visita':<10} {'k_pos':<10} {'k_neg':<10}")
        for row in rows:
            print(f"  {row[0]:<10} {str(row[1])[:19]:<20} {str(row[2]):<10} {str(row[3]):<10} {str(row[4]):<10} {str(row[5]):<10}")
    except Exception as e:
        print(f"  Error mostrando datos: {e}")
    
    conn.close()
    
    # Resumen
    print(f"\n{'='*60}")
    print("📋 RESUMEN:")
    if missing_columns:
        print(f"  ❌ Faltan {len(missing_columns)} columnas: {[c[0] for c in missing_columns]}")
        print(f"  💡 Ejecuta: python migrate_constants_db.py --migrate")
    else:
        print("  ✅ Todas las columnas están presentes")
    
    return len(missing_columns) == 0


def migrate(db_path: str):
    """🔧 Añade columnas faltantes a la tabla"""
    print(f"\n{'='*60}")
    print(f"🔧 MIGRACIÓN DE constants.db")
    print(f"{'='*60}")
    
    if not os.path.exists(db_path):
        print("❌ La base de datos no existe. Creándola...")
        # Crear la tabla completa
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cols_def = ', '.join([f"{name} {dtype}" for name, dtype in EXPECTED_COLUMNS.items()])
        cursor.execute(f"CREATE TABLE IF NOT EXISTS constants ({cols_def})")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_constants_team_id ON constants(team_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_constants_fixture_id ON constants(fixture_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_constants_date ON constants(date)")
        
        conn.commit()
        conn.close()
        print("✅ Tabla creada con todas las columnas")
        return True
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Obtener columnas actuales
    cursor.execute("PRAGMA table_info(constants)")
    current_columns = {row[1] for row in cursor.fetchall()}
    
    # Añadir columnas faltantes
    added = 0
    for col_name, col_type in EXPECTED_COLUMNS.items():
        if col_name not in current_columns:
            try:
                # SQLite solo soporta tipos básicos en ALTER TABLE
                simple_type = 'REAL' if 'FLOAT' in col_type else col_type.split()[0]
                cursor.execute(f"ALTER TABLE constants ADD COLUMN {col_name} {simple_type}")
                print(f"  ✅ Añadida columna: {col_name}")
                added += 1
            except sqlite3.OperationalError as e:
                print(f"  ⚠️ Error añadiendo {col_name}: {e}")
    
    conn.commit()
    conn.close()
    
    if added > 0:
        print(f"\n✅ Migración completada: {added} columnas añadidas")
        print("💡 Ahora ejecuta: python migrate_constants_db.py --recalc-all")
    else:
        print("\n✅ No hay columnas faltantes - la tabla está actualizada")
    
    return True


def recalculate_all(db_path: str):
    """🔄 Recalcula todas las constantes desde cero"""
    print(f"\n{'='*60}")
    print(f"🔄 RECÁLCULO COMPLETO DE CONSTANTES")
    print(f"{'='*60}")
    
    confirm = input("⚠️ Esto borrará y recalculará TODOS los datos. ¿Continuar? (s/N): ")
    if confirm.lower() != 's':
        print("Operación cancelada")
        return False
    
    try:
        from utils.constants_calculator import ConstantsCalculator
        
        print("\n🔄 Iniciando recálculo...")
        
        with ConstantsCalculator() as calc:
            calc.calculate_and_store_all_teams()
        
        print("\n✅ Recálculo completado!")
        return True
        
    except ImportError as e:
        print(f"❌ Error importando módulos: {e}")
        print("💡 Asegúrate de ejecutar desde el directorio correcto del proyecto")
        return False
    except Exception as e:
        print(f"❌ Error durante recálculo: {e}")
        return False


def recalculate_team(db_path: str, team_id: int):
    """🔄 Recalcula constantes de un equipo específico"""
    print(f"\n{'='*60}")
    print(f"🔄 RECÁLCULO DE EQUIPO {team_id}")
    print(f"{'='*60}")
    
    try:
        from utils.constants_calculator import ConstantsCalculator
        
        with ConstantsCalculator() as calc:
            team_name = calc.get_team_name(team_id)
            print(f"📋 Equipo: {team_name}")
            
            # Usar recálculo completo (no incremental)
            success = calc.full_recalculate_team(team_id)
            
            if success:
                print(f"\n✅ Recálculo completado para {team_name}")
            else:
                print(f"\n⚠️ No se generaron datos para {team_name}")
            
            return success
            
    except ImportError as e:
        print(f"❌ Error importando módulos: {e}")
        return False
    except Exception as e:
        print(f"❌ Error durante recálculo: {e}")
        return False


def cleanup_nan(db_path: str):
    """🧹 Elimina registros con valores NaN/NULL problemáticos"""
    print(f"\n{'='*60}")
    print(f"🧹 LIMPIEZA DE REGISTROS CON NaN")
    print(f"{'='*60}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Contar registros problemáticos
    cursor.execute("""
        SELECT COUNT(*) FROM constants 
        WHERE (q_local IS NULL AND q_visita IS NULL)
        AND q_negativo = 0
    """)
    problem_count = cursor.fetchone()[0]
    
    print(f"📊 Registros problemáticos encontrados: {problem_count}")
    
    if problem_count == 0:
        print("✅ No hay registros para limpiar")
        conn.close()
        return True
    
    confirm = input(f"⚠️ ¿Eliminar {problem_count} registros problemáticos? (s/N): ")
    if confirm.lower() != 's':
        print("Operación cancelada")
        conn.close()
        return False
    
    cursor.execute("""
        DELETE FROM constants 
        WHERE (q_local IS NULL AND q_visita IS NULL)
        AND q_negativo = 0
    """)
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"✅ Eliminados {deleted} registros")
    print("💡 Ahora sincroniza los equipos afectados para regenerar los datos")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='Herramienta de migración para constants.db')
    parser.add_argument('--diagnose', action='store_true', help='Diagnosticar estado de la BD')
    parser.add_argument('--migrate', action='store_true', help='Añadir columnas faltantes')
    parser.add_argument('--recalc-all', action='store_true', help='Recalcular todas las constantes')
    parser.add_argument('--recalc-team', type=int, help='Recalcular constantes de un equipo')
    parser.add_argument('--cleanup', action='store_true', help='Limpiar registros con NaN')
    parser.add_argument('--db-path', type=str, help='Ruta a constants.db')
    
    args = parser.parse_args()
    
    db_path = args.db_path or get_db_path()
    
    if args.diagnose:
        diagnose(db_path)
    elif args.migrate:
        migrate(db_path)
    elif args.recalc_all:
        recalculate_all(db_path)
    elif args.recalc_team:
        recalculate_team(db_path, args.recalc_team)
    elif args.cleanup:
        cleanup_nan(db_path)
    else:
        # Por defecto, mostrar diagnóstico
        diagnose(db_path)
        print("\n💡 Opciones disponibles:")
        print("  --diagnose    Ver estado de la BD")
        print("  --migrate     Añadir columnas faltantes")
        print("  --cleanup     Eliminar registros con NaN")
        print("  --recalc-team ID  Recalcular un equipo")
        print("  --recalc-all  Recalcular todo (¡lento!)")


if __name__ == '__main__':
    main()