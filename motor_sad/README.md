# motor_sad — Motor portable del SAD

Reimplementación autocontenida (solo `sqlite3` de la librería estándar, sin
SQLAlchemy/pandas/scikit-learn) del núcleo del Sistema de Análisis Deportivo:
**niveles**, **constantes K** y la **organización/pipeline de las 4 bases de datos**.

Especificación completa y verificada contra el código original:
[`docs/MOTOR_SAD_EXTRACCION.md`](../docs/MOTOR_SAD_EXTRACCION.md).

## Pipeline

```
sad.db ──► levels.db ──► constants.db ──► discreto.db ──► ML / leyes
```

| Módulo | Equivale a (proyecto original) |
|---|---|
| `db.py` | `data/database_manager.py` (rutas, PRAGMAs WAL, DDL) |
| `levels.py` | `data/levels_calculator.py` (ventana 20/5, retroactivo, sync incremental) |
| `constants.py` | `utils/constants_calculator.py` (q*, k*, incremental + retroactivo) |
| `discretizer.py` | `data/discretizer_db.py` (bins uniformes/fijos, fusión, processed_matches) |
| `pipeline.py` | orquestación: `sync_all()` |

## Uso

```python
from motor_sad import sync_all

# base_dir debe contener un sad.db poblado (tablas fixtures y teams)
stats = sync_all(base_dir="/ruta/del/proyecto")
```

O por etapas:

```python
from motor_sad import LevelsEngine, ConstantsEngine, DiscreteProcessor

levels = LevelsEngine(base_dir); levels.calculate_missing_levels(); levels.close()
const = ConstantsEngine(base_dir)
const.batch_calculate_teams(team_ids, incremental=True); const.close()
proc = DiscreteProcessor(base_dir); proc.process_all_teams(); proc.close()
```

## Verificación

```bash
python3 -m motor_sad.test_motor_sad
```

Los tests cubren la fórmula de niveles (incl. regla retroactiva del partido 20),
el ejemplo numérico oficial de las constantes (3–1 local vs rival nivel 4 →
q_local +8, reset del negativo, fusión +13), el modo incremental con detección
de huecos retroactivos, el discretizador y la idempotencia del pipeline.
