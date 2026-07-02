# src/data/database_manager.py

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from data.base import Base

# Registramos todos los modelos para que se incluyan en Base.metadata
import data.data_models.teams       # define la tabla "teams"
import data.data_models.fixtures    # define la tabla "fixtures"
import data.data_models.team_levels # define la tabla "team_levels"

# --------------------------------------------------------------------
# Configuración de rutas y motores de base de datos
# --------------------------------------------------------------------

# Subimos tres niveles para llegar a la raíz del proyecto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# Base de datos original (sad.db)
ORIG_DB_PATH = os.path.join(BASE_DIR, 'sad.db')
ORIG_ENGINE = create_engine(
    f'sqlite:///{ORIG_DB_PATH}',
    echo=False,
    connect_args={
        'timeout': 30,  # Esperar hasta 30 segundos si está bloqueada
        'check_same_thread': False  # Permitir uso desde múltiples threads
    },
    pool_pre_ping=True  # Verificar conexión antes de usar
)

# Base de datos de constantes (constants.db)
CONST_DB_PATH = os.path.join(BASE_DIR, 'constants.db')
CONST_ENGINE = create_engine(
    f'sqlite:///{CONST_DB_PATH}',
    echo=False,
    connect_args={
        'timeout': 30,
        'check_same_thread': False
    },
    pool_pre_ping=True
)


# --------------------------------------------------------------------
# Habilitar WAL mode para mejor concurrencia
# --------------------------------------------------------------------
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Configura SQLite para mejor rendimiento y concurrencia."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
    cursor.execute("PRAGMA busy_timeout=30000")  # 30 segundos en ms
    cursor.execute("PRAGMA synchronous=NORMAL")  # Balance velocidad/seguridad
    cursor.close()

# Aplicar configuración cuando se conecta
event.listen(ORIG_ENGINE, "connect", set_sqlite_pragma)
event.listen(CONST_ENGINE, "connect", set_sqlite_pragma)


# Para depuración: imprimimos rutas y existencia de ficheros
print(f"Ruta a la base de datos original: {ORIG_DB_PATH}")
print(f"¿Existe la base de datos original? {os.path.exists(ORIG_DB_PATH)}")
print(f"Ruta a la base de datos de constantes: {CONST_DB_PATH}")
print(f"¿Existe la base de datos de constantes? {os.path.exists(CONST_DB_PATH)}")

# Por defecto, operaremos sobre la base de datos original
engine = ORIG_ENGINE  

# --------------------------------------------------------------------
# Sesiones
# --------------------------------------------------------------------

SessionOrig  = sessionmaker(bind=ORIG_ENGINE)
SessionConst = sessionmaker(bind=CONST_ENGINE)

# --------------------------------------------------------------------
# Función de inicialización de esquemas
# --------------------------------------------------------------------

def init_db(target_engine: str = 'orig'):
    """
    Crea todas las tablas registradas en Base.metadata.
    
    :param target_engine: 'orig' para sad.db, 'const' para constants.db
    """
    eng = ORIG_ENGINE if target_engine == 'orig' else CONST_ENGINE
    Base.metadata.create_all(eng)
    print(f"Tablas creadas en {'sad.db' if target_engine=='orig' else 'constants.db'}")

# --------------------------------------------------------------------
# Ejemplo de uso al importar el módulo
# --------------------------------------------------------------------
if __name__ == '__main__':
    # Si ejecutas python database_manager.py directamente,
    # inicializa ambas bases de datos:
    init_db('orig')
    init_db('const')