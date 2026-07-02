# motor_sad/pipeline.py
"""
Orquestación del pipeline completo:

    sad.db ──► levels.db ──► constants.db ──► discreto.db

Regla de oro del orden: nunca calcular constantes sin niveles al día (cada q*
pondera con el nivel del rival), y nunca fusionar sin constantes al día.
Cada etapa es incremental e idempotente: se puede re-ejecutar tras cada
extracción de partidos nuevos.
"""
import logging
from typing import Dict

from .db import connect, db_path, init_all, SAD_DB
from .levels import LevelsEngine
from .constants import ConstantsEngine
from .discretizer import DiscreteProcessor

logger = logging.getLogger(__name__)


def sync_all(base_dir: str = '.') -> Dict:
    """
    Ejecuta el pipeline completo de forma incremental.
    Requiere que sad.db exista y esté poblado en base_dir.
    """
    init_all(base_dir)
    stats: Dict = {}

    # 1) Niveles (diff por fixture_id -> recalcular equipos afectados)
    levels = LevelsEngine(base_dir)
    try:
        stats['levels'] = levels.calculate_missing_levels()
        logger.info("Niveles: %s", stats['levels'])
    finally:
        levels.close()

    # 2) Constantes K (incremental, con detección de huecos retroactivos)
    sad = connect(db_path(base_dir, SAD_DB))
    try:
        team_ids = [tid for (tid,) in sad.execute("SELECT id FROM teams")]
    finally:
        sad.close()

    constants = ConstantsEngine(base_dir)
    try:
        stats['constants'] = constants.batch_calculate_teams(team_ids, incremental=True)
        logger.info("Constantes: %s", stats['constants'])
    finally:
        constants.close()

    # 3) Fusión + discretización (idempotente por UNIQUE(fixture_id, equipo_id))
    processor = DiscreteProcessor(base_dir)
    try:
        stats['processed_matches'] = processor.process_all_teams()
    finally:
        processor.close()

    return stats


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    result = sync_all(sys.argv[1] if len(sys.argv) > 1 else '.')
    print(result)
