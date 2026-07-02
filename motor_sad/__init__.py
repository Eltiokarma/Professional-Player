# motor_sad — Motor portable del SAD: niveles, constantes K y pipeline de DB.
# Solo librería estándar (sqlite3). Ver docs/MOTOR_SAD_EXTRACCION.md.
from .db import init_all, connect, FINISHED_STATUS, DEFAULT_LEVEL, VISITOR_MULTIPLIER
from .levels import LevelsEngine
from .constants import ConstantsEngine
from .discretizer import DiscreteProcessor, UniformDiscretizer, fixed_bin, fuse
from .pipeline import sync_all

__all__ = [
    'init_all', 'connect', 'FINISHED_STATUS', 'DEFAULT_LEVEL', 'VISITOR_MULTIPLIER',
    'LevelsEngine', 'ConstantsEngine', 'DiscreteProcessor',
    'UniformDiscretizer', 'fixed_bin', 'fuse', 'sync_all',
]
