# Motor SAD — Extracción técnica: Niveles, Constantes K y Organización de las DB

> Documento de extracción verificado contra el código real de este repositorio
> (SAD v3.4). Fuentes: `data/levels_calculator.py`, `utils/constants_calculator.py`,
> `data/discretizer_db.py`, `data/database_manager.py`, `regresion_nivel_engine.py`,
> más los documentos `formula_constantes_SAD_v2.docx` y `ley_regresion_nivel.docx`.
>
> Objetivo: poder reimplantar el motor (niveles + constantes + pipeline de DB)
> en otro proyecto. La implementación portable de referencia está en `motor_sad/`.

---

## 1. Organización de las bases de datos

El motor usa **4 bases SQLite separadas**, encadenadas en un pipeline unidireccional:

```
sad.db  ──►  levels.db  ──►  constants.db  ──►  discreto.db  ──►  ML / motores de ley
(fuente)     (niveles)       (q* y k*)          (fusión + bins)
```

| DB | Tabla(s) clave | Quién la escribe | Rol |
|---|---|---|---|
| `sad.db` | `fixtures`, `teams` | extractor de API | Fuente primaria: resultados, goles, fechas, ligas |
| `levels.db` | `team_levels` | `levels_calculator` | Nivel continuo por (equipo, fixture) |
| `constants.db` | `constants` | `constants_calculator` | Valores instantáneos q* y acumuladores k* |
| `discreto.db` | `processed_matches` | `discretizer_db` | K fusionadas + niveles discretizados (features ML) |

Todas las conexiones activan los mismos PRAGMA (crítico para concurrencia con UI):

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=30000;   -- 30 s
PRAGMA synchronous=NORMAL;
```

y en SQLAlchemy: `timeout=30`, `check_same_thread=False`, `pool_pre_ping=True`.

### 1.1 Esquemas mínimos

**`sad.db` — lo que el motor realmente necesita** (el esquema real tiene más columnas):

```sql
CREATE TABLE teams (
    id      INTEGER PRIMARY KEY,
    name    TEXT,
    country TEXT
);

CREATE TABLE fixtures (
    id            INTEGER PRIMARY KEY,
    date          DATETIME,          -- orden cronológico: es LA columna que gobierna todo
    status_long   TEXT,              -- filtro universal: 'Match Finished'
    status_short  TEXT,              -- 'FT' (lo usa solo regresion_nivel_engine)
    league_id     INTEGER,
    league_season INTEGER,
    home_team_id  INTEGER REFERENCES teams(id),
    away_team_id  INTEGER REFERENCES teams(id),
    goals_home    INTEGER,
    goals_away    INTEGER
);
```

**`levels.db`:**

```sql
CREATE TABLE team_levels (
    id         INTEGER PRIMARY KEY,
    team_id    INTEGER NOT NULL,
    fixture_id INTEGER NOT NULL,
    date       DATETIME NOT NULL,
    level      REAL NOT NULL          -- nivel continuo ~0.5–3.5
);
```

**`constants.db`:**

```sql
CREATE TABLE constants (
    id INTEGER PRIMARY KEY,
    team_id    INTEGER NOT NULL,
    fixture_id INTEGER NOT NULL,
    date       DATETIME NOT NULL,
    -- valores instantáneos (por partido)
    q_local REAL, q_visita REAL, q_negativo REAL,
    q_goles_anotado REAL, q_goles_recibido REAL,
    q_goles_local_anotado REAL, q_goles_local_recibido REAL,
    q_goles_visita_anotado REAL, q_goles_visita_recibido REAL,
    -- acumuladores de racha (con reseteo)
    k_positivo REAL, k_negativo REAL,
    k_positivo_local REAL, k_negativo_local REAL,
    k_positivo_visita REAL, k_negativo_visita REAL,
    k_goles_anotado REAL, k_goles_recibido REAL,
    k_goles_local_anotado REAL, k_goles_local_recibido REAL,
    k_goles_visita_anotado REAL, k_goles_visita_recibido REAL
);
CREATE INDEX ix_constants_team_date    ON constants(team_id, date);
CREATE INDEX ix_constants_fixture_team ON constants(fixture_id, team_id);
```

**`discreto.db`:**

```sql
CREATE TABLE processed_matches (
    id INTEGER PRIMARY KEY,
    fecha DATETIME NOT NULL,
    fixture_id INTEGER NOT NULL,
    equipo_id INTEGER NOT NULL,
    equipo_nombre TEXT NOT NULL,
    rival_id INTEGER NOT NULL,
    rival_nombre TEXT NOT NULL,
    condicion TEXT,                    -- 'Local' | 'Visita'
    status_long TEXT,
    league_id INTEGER, league_season TEXT,
    goals_home INTEGER, goals_away INTEGER,
    nivel_equipo INTEGER,              -- discretizado 0–9
    nivel_rival  INTEGER,              -- discretizado 0–9
    k REAL, k_local REAL, k_visita REAL,      -- K FUSIONADAS (pos + neg)
    k_goles_anotado REAL, k_goles_recibido REAL,
    k_goles_local_anotado REAL, k_goles_local_recibido REAL,
    k_goles_visita_anotado REAL, k_goles_visita_recibido REAL,
    processed_at DATETIME,
    UNIQUE(fixture_id, equipo_id)      -- idempotencia: ON CONFLICT DO NOTHING
);
CREATE INDEX idx_fecha_equipo ON processed_matches(fecha, equipo_id);
CREATE INDEX idx_status  ON processed_matches(status_long);
CREATE INDEX idx_fixture ON processed_matches(fixture_id);
CREATE INDEX idx_league  ON processed_matches(league_id);
```

### 1.2 Convenciones transversales

- **Filtro universal de partidos**: `status_long = 'Match Finished'` y goles no nulos.
  (Excepción: `regresion_nivel_engine` filtra por `status_short = 'FT'`.)
- **Doble fila por partido**: cada fixture genera registros desde la perspectiva de
  *cada* equipo (en `constants` y `processed_matches` hay 2 filas por fixture).
- **Orden cronológico estricto por `date`**: los acumuladores K dependen del orden;
  cualquier partido insertado retroactivamente invalida la racha (ver §3.4).
- **Sincronización por diff, no por eventos**: cada capa compara sus `fixture_id`
  procesados contra la capa anterior y recalcula solo lo pendiente.

---

## 2. Motor de Niveles (`levels_calculator` → `levels.db`)

El nivel mide el **rendimiento sostenido** de un equipo en una ventana móvil de
**20 partidos finalizados** (mezclando local y visita), con un componente de goles
enfocado en los **últimos 5**.

### 2.1 Fórmula

Para cada partido `i` (con `i >= 19`, índice 0-based) de la historia ordenada por fecha:

```
ventana20 = partidos[i-19 .. i]                      # 20 partidos
P  = Σ puntos(ventana20) / 20                        # puntos: 3/1/0
u5 = últimos 5 de ventana20
G  = Σ (gf - ga) en u5  /  Σ (gf + ga) en u5         # si Σ goles u5 == 0 → G = 0
Nivel = P + G + 1
```

- Rango de P: 0.0–3.0 (promedio de liga ≈ 1.3–1.5).
- Rango de G: −1.0 a +1.0.
- Rango típico del nivel: **0.5 a 3.5** (promedio ≈ 2.0–2.5; élite > 3.0).

### 2.2 Inicialización (regla retroactiva)

- Equipo con **menos de 20 partidos**: TODOS sus partidos reciben nivel por defecto **0.5**.
- En el **partido nº 20** se calcula el primer nivel real y se asigna
  **retroactivamente a los 20 primeros partidos** (los 20 comparten el mismo nivel).
- Del partido 21 en adelante, cada partido recibe solo su propio nivel.

### 2.3 Persistencia y sincronización incremental

- Se guarda una fila `(team_id, fixture_id, date, level)` por partido en `team_levels`.
- **Detección de cambios**: fixtures `Match Finished` de `sad.db` cuyo `fixture_id`
  no aparece en `team_levels` → ambos equipos del fixture quedan "afectados".
- **Recalculo por equipo = borrar y regenerar**: se eliminan todas las filas del
  equipo y se recalcula la historia completa (la ventana móvil hace inviable el
  parcheo parcial). Es barato: una query de fixtures + bulk insert.
- **Consulta de nivel a fecha**: último `level` con `date <= fecha`; si no hay
  registros → **0.5**.

### 2.4 Consumo del nivel

El nivel se consume de dos formas:

1. **Continuo (0.5–3.5)** — lo usa `constants_calculator` para ponderar el rival
   (¡ojo: NO usa el nivel discretizado, ver §5 discrepancias!) y
   `regresion_nivel_engine` para el Gap.
2. **Discretizado (0–9)** — features para ML, ver §4.

---

## 3. Motor de Constantes K (`constants_calculator` → `constants.db`)

Dos pasos por partido: valores instantáneos **q\*** (materia prima) y acumuladores
de racha **k\*** (momentum con reseteo).

### 3.1 Variables de entrada por partido

| Variable | Fuente |
|---|---|
| `gf`, `ga` | goles a favor / en contra del equipo analizado |
| `nivel` | nivel **continuo** del RIVAL a la fecha del partido (levels.db); fallback **1.0** si el rival no tiene niveles |
| `is_local` | `home_team_id == team_id` |

### 3.2 Valores instantáneos q*

```
dif = |gf − ga|
res = +1 si gf > ga;  0 si gf == ga;  −1 si gf < ga    (None si goles nulos)

q_local    = dif × res × nivel          solo si is_local  (si no → NULL)
q_visita   = 1.4 × dif × res × nivel    solo si visita    (si no → NULL)
q_negativo = dif × res × nivel          solo si res == −1 (si no → 0)

q_goles_anotado  = +gf × nivel          siempre
q_goles_recibido = −ga × nivel          siempre (negativo)
q_goles_local_*  / q_goles_visita_*     = los anteriores, pero NULL si la
                                          condición (local/visita) no aplica
```

El factor **1.4** premia/castiga más los resultados de visitante
(`CalculationSettings.visitor_multiplier` en `config/settings.py`).

### 3.3 Acumuladores k* (rachas con reseteo)

Se procesan en **orden cronológico**. Regla general: acumulan mientras el signo se
mantiene, **se resetean a 0** cuando el signo cambia (o hay empate). Solo uno de
los dos lados (positivo/negativo) puede ser ≠ 0 a la vez.

```
q_any = q_local si el partido fue de local, si no q_visita

k_positivo:  si q_any > 0 → k += q_any ;  si no (incl. empate/derrota/None) → k = 0
k_negativo:  si q_negativo < 0 → k += q_negativo ;  si no → k = 0

k_positivo_local / k_negativo_local:
    SOLO se actualizan en partidos de local (misma regla, con q_local).
    En partidos de visita CONSERVAN su valor anterior.
k_positivo_visita / k_negativo_visita: análogo con q_visita.

k_goles_anotado:  si q_ga > 0 → k += q_ga ; si no → k = 0
k_goles_recibido: si q_gr < 0 → k += |q_gr| ; si no → k = 0   ← acumula VALOR ABSOLUTO
k_goles_local_* / k_goles_visita_*: análogos, solo se actualizan en su condición.
```

Detalle de implementación fiel (importa para replicar bit a bit):

- `k_positivo` se resetea también cuando `q_any` es `None` (goles nulos).
- Los k de goles **no se tocan** cuando su q es `None` (mantienen valor); los k
  local/visita tampoco se tocan fuera de su condición.
- Cada fila guardada lleva la foto completa de los 12 acumuladores tras ese partido.

### 3.4 Modo incremental y detección retroactiva

`incremental_calculate_and_store(team_id)` es el camino por defecto tras cada sync:

1. **Detección de huecos retroactivos**: compara `fixture_id` terminados en `sad.db`
   vs ya calculados en `constants.db`. Si falta alguno con `date <= última fecha
   calculada` (p. ej. una Copa extraída tarde) → **recálculo completo del equipo**
   (borrar + regenerar), porque la racha quedó invalidada.
2. Si no hay retroactivos: recupera los **12 acumuladores de la última fila** del
   equipo, consulta solo fixtures con `date > última_fecha` y continúa la
   acumulación desde ese estado. Bulk insert de las filas nuevas.

Optimizaciones clave (aprendidas a golpes en este repo, replicarlas desde el día 1):

- **Cache de niveles en memoria**: 1 query masivo a `team_levels` →
  `{team_id: [(date, level), ...]}` ordenado, lookup por **bisect** (O(log n)).
  Sin esto, ~100K queries individuales.
- **Bulk insert** (`bulk_insert_mappings` / `executemany`), nunca fila a fila.
- Nada de validaciones por fila ni queries de diagnóstico dentro del bucle.
- Limpieza de basura: se consideran corruptas las filas con
  `q_local IS NULL AND q_visita IS NULL AND q_negativo = 0`.

### 3.5 Ejemplo numérico (del doc oficial, verificado)

Equipo A (LOCAL) gana 3–1 a un rival de nivel 4:

```
dif = 2, res = +1
q_local          = 2 × 1 × 4  = +8
q_negativo       = 0            (no hubo derrota)
q_goles_anotado  = 3 × 4      = +12
q_goles_recibido = −1 × 4     = −4

k_positivo_local: 5.0 → 13.0     (acumula)
k_negativo_local: −6.0 → 0       (RESET)
k_goles_anotado:  8.0 → 20.0
Fusión: k_local = 13.0 + 0 = +13.0  → feature prev_team_k_local para ML
```

---

## 4. Discretización y fusión (`discretizer_db` → `discreto.db`)

Última etapa antes del ML. Por cada (equipo, fixture terminado):

### 4.1 Niveles discretizados (0–9)

- **Lookup del nivel crudo**: nivel exacto por `(team_id, fixture_id)` en
  `team_levels`; si no existe, último nivel con `date <= fecha`; si tampoco → **0.5**.
- **Método A — KBinsDiscretizer calibrado** (Global Constant Predictor):
  `KBinsDiscretizer(n_bins=10, encode='ordinal', strategy='uniform')` ajustado
  sobre TODOS los `level` de `levels.db`. Con estrategia *uniform* equivale a:

  ```
  bin = floor( (nivel − min) / (max − min) × 10 ),  recortado a [0, 9]
  ```

- **Fallback lineal** (si no hay discretizer):
  `nivel_discreto = (nivel − 0.5) / (3.5 − 0.5) × 9`.
- **Método B — bins fijos** (Ley del Marcador v6), umbrales calibrados a mano:

  | Bin | Rango | Etiqueta |
  |---|---|---|
  | 0 | < 0.6 | Sin datos |
  | 1 | 0.6–1.3 | Muy débil |
  | 2 | 1.3–1.6 | Débil |
  | 3 | 1.6–1.9 | Regular bajo |
  | 4 | 1.9–2.1 | Promedio bajo |
  | 5 | 2.1–2.35 | Promedio |
  | 6 | 2.35–2.55 | Promedio alto |
  | 7 | 2.55–2.85 | Fuerte |
  | 8 | 2.85–3.2 | Muy fuerte |
  | 9 | > 3.2 | Élite |

### 4.2 Fusión de constantes

Como `k_positivo ≥ 0` y `k_negativo ≤ 0` y se resetean mutuamente, la suma neta
captura la dirección del momentum sin ambigüedad:

```
k        = k_positivo        + k_negativo
k_local  = k_positivo_local  + k_negativo_local
k_visita = k_positivo_visita + k_negativo_visita
(NULL se trata como 0.0)
```

Lectura: `k > 0` racha positiva activa · `k = 0` recién reseteado · `k < 0` mala racha.

Los `k_goles_*` pasan tal cual (ya son netos por diseño). Inserción idempotente con
`ON CONFLICT(fixture_id, equipo_id) DO NOTHING`.

---

## 5. Ley de la Regresión al Nivel (Gap) — resumen operativo

No es parte del pipeline de DB pero es el consumidor directo de `levels.db`:

- **Forma reciente**: `pts_recent` = promedio de puntos en los últimos **5**
  partidos (`WINDOW = 5`); `None` si no hay 5 partidos.
- **μ (puntos esperados)** — regresión lineal calibrada:

  ```
  μ = 1.110 + 0.686·nivel_equipo − 0.669·nivel_rival + 0.422·is_home
  (recortado a [0, 3])
  ```

- **Gap (según el CÓDIGO)**: `gap = pts_esperados − pts_recent`, donde
  `pts_esperados` usa μ con rival promedio (nivel 2.0) y 50 % de localía.
  `gap > 0` → rinde POR DEBAJO de su nivel (tiende a mejorar);
  `gap < 0` → rinde POR ENCIMA (tiende a empeorar).
- **Gap diferencial**: `gap_diff = gap_local − gap_visitante`.
- Umbrales de señal: |gap| > 0.5 fuerte, 0.3–0.5 leve, < 0.3 equilibrio.
- Principio rector: **"el value no cura el reset"** — con señal clara de regresión,
  la cuota no justifica ir en contra.

### ⚠️ Discrepancias documentación vs código (resueltas a favor del código)

1. **Nivel usado en las constantes**: el doc dice "nivel discretizado del rival
   (1–10)"; el código usa el **nivel continuo** (0.5–3.5) de `levels.db`. La
   discretización solo ocurre después, para features ML en `processed_matches`.
2. **Fallback de nivel en constantes**: **1.0** (no 0.5) cuando el rival no tiene
   registros en `levels.db` — deliberado, para no disparar recálculos y no anular
   los q* (`settings.py: default_level = 1.0`).
3. **Signo del Gap**: el doc define `Gap = forma − nivel` (Gap>0 = sobrerinde);
   el código implementa `gap = esperado(μ) − forma` (gap>0 = SUBrinde). Misma
   información, signo invertido y expectativa basada en μ, no en el nivel crudo.
4. **Filtro de partidos**: niveles/constantes/discreto usan
   `status_long='Match Finished'`; la forma reciente del motor de regresión usa
   `status_short='FT'`. Al portar, unificar (recomendado: `Match Finished`).

---

## 6. Flujo completo del pipeline (orden de ejecución)

```
1. EXTRACCIÓN   → sad.db            (nuevos fixtures terminados)
2. NIVELES      → levels.db         levels_calculator.calculate_missing_levels()
                                    (diff por fixture_id → recalcular equipos afectados)
3. CONSTANTES   → constants.db      ConstantsCalculator.batch_calculate_teams(incremental=True)
                                    (precarga cache de niveles UNA vez;
                                     retroactivo → full recalc del equipo)
4. FUSIÓN + BINS→ discreto.db       DiscreteDBProcessor.process_all_teams()
                                    (k = k_pos + k_neg; niveles → 0–9; idempotente)
5. ML / LEYES   → models.py entrena por constante fusionada (target:
                  incremento / reset / decremento); anticulebra, marcador,
                  regresión al nivel y fe perdida consumen niveles + K.
```

**Regla de oro del orden**: nunca calcular constantes sin niveles al día (el q*
de hoy pondera con el nivel del rival de hoy), y nunca fusionar sin constantes
al día. Cada capa es idempotente y re-ejecutable.

---

## 7. Implementación portable

El paquete **`motor_sad/`** de este repo reimplementa todo lo anterior con
**solo la librería estándar de Python (sqlite3)** — sin SQLAlchemy, pandas ni
scikit-learn — manteniendo semántica idéntica a los módulos originales:

| Módulo portable | Reemplaza a | Contenido |
|---|---|---|
| `motor_sad/db.py` | `database_manager.py` | Rutas, PRAGMAs WAL, DDL de las 4 DB |
| `motor_sad/levels.py` | `levels_calculator.py` | Ventana 20/5, regla retroactiva, sync incremental |
| `motor_sad/constants.py` | `constants_calculator.py` | q*, k*, incremental + detección retroactiva, cache bisect |
| `motor_sad/discretizer.py` | `discretizer_db.py` | Discretizador uniforme 10 bins, bins fijos v6, fusión, processed_matches |
| `motor_sad/pipeline.py` | (orquestación manual) | `sync_all()`: niveles → constantes → discreto |

Uso mínimo en el proyecto destino:

```python
from motor_sad.pipeline import sync_all
stats = sync_all(base_dir="/ruta/del/proyecto")   # sad.db debe existir ahí
```
