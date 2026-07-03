# SAD API — backend FastAPI (v0)

Servicio de **solo lectura** sobre las 4 SQLite del pipeline
(`sad.db → levels.db → constants.db → discreto.db`), implementando el contrato
`docs/openapi.yaml` del repo **App-Profesional-de-Apuestas** (la web SAD).
No escribe nada: la app de escritorio y el pipeline siguen siendo los dueños
de los datos.

## Endpoints

| Endpoint | Fuente |
|---|---|
| `GET /api/v1/health` | existencia/lectura de las 4 DBs + `MAX(processed_at)` |
| `GET /api/v1/fixtures[?fecha&estado&ligaId&limit]` | `sad.db` (fixtures + teams + leagues) |
| `GET /api/v1/fixtures/{id}` | ídem |
| `GET /api/v1/niveles/{equipoId}` | `levels.db` + bins fijos v6 |
| `GET /api/v1/constantes/{equipoId}` | `constants.db` + rival/goles de `discreto.db` + fusión k = k⁺ + k⁻ |
| `GET /api/v1/predicciones/{fixtureId}` | Ley de Regresión al Nivel §5 (μ = 1.110 + 0.686·nivel − 0.669·rival + 0.422·localía) |
| `GET /api/v1/analisis-prepartido/{fixtureId}` | composición de todo lo anterior |
| `GET /api/v1/cuotas/{fixtureId}` | tabla `odds` de `sad.db`, mapeada a mercados del contrato y promediada entre bookmakers |

## Correr con tus DBs reales

```bash
pip install -r backend/requirements.txt
# desde la raíz del proyecto (donde viven sad.db, levels.db, constants.db, discreto.db):
uvicorn backend.app:app --port 8000
# o apuntando a otra carpeta de datos:
SAD_DATA_DIR=/ruta/a/las/dbs uvicorn backend.app:app --port 8000
```

Luego, en la web SAD (`App-Profesional-de-Apuestas`):

```bash
cp .env.example .env
# VITE_DATA_SOURCE=http
# VITE_API_BASE_URL=http://localhost:8000/api/v1
npm run dev
```

## Demo y tests (sin DBs reales)

```bash
python3 -m backend.seed_demo        # genera ./demo_data con esquemas reales + pipeline fiel
SAD_DATA_DIR=./demo_data uvicorn backend.app:app --port 8000
python3 -m backend.test_api         # 23 verificaciones del contrato
```

## Configuración

| Variable | Default | Uso |
|---|---|---|
| `SAD_DATA_DIR` | raíz del proyecto | carpeta con las 4 SQLite |
| `SAD_CORS_ORIGINS` | `*` | orígenes permitidos (coma-separados) |

## Fase 2 (fuera de este v0)

Migración a PostgreSQL (Neon/Supabase) con Alembic, scheduler de ingesta
(APScheduler + API-Football), auth de sesión y despliegue 24/7 — ver
`docs/SERVICIOS_EXTERNOS.md` en el repo de la web.
