# src/config/api_config.py
"""
Configuración para la API de Football.
Soporta dos gateways para duplicar cuota gratis (200 req/día):
  - api-sports.io directo (100/día) → key de dashboard.api-football.com
  - RapidAPI gateway (100/día)      → key de rapidapi.com

Variables de entorno:
  API_KEY          = key de api-sports.io (dashboard.api-football.com)
  RAPIDAPI_KEY     = key de RapidAPI (opcional, activa modo dual)
"""

import os

# =========================================================================
# KEYS — configurar en variables de entorno
# =========================================================================

# Key directa de api-sports.io (dashboard.api-football.com)
API_KEY = os.getenv('API_KEY')

# Key de RapidAPI (opcional — si existe, se activa modo dual)
RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY')

# =========================================================================
# GATEWAYS — configuración de cada proveedor
# =========================================================================

API_GATEWAYS = []

# Gateway 1: api-sports.io directo (prioridad)
if API_KEY:
    API_GATEWAYS.append({
        'name': 'api-sports.io',
        'base_url': 'https://v3.football.api-sports.io',
        'headers': {'x-apisports-key': API_KEY},
        'daily_limit': 100,
    })

# Gateway 2: RapidAPI (fallback)
if RAPIDAPI_KEY:
    API_GATEWAYS.append({
        'name': 'RapidAPI',
        'base_url': 'https://api-football-v1.p.rapidapi.com/v3',
        'headers': {
            'x-rapidapi-key': RAPIDAPI_KEY,
            'x-rapidapi-host': 'api-football-v1.p.rapidapi.com',
        },
        'daily_limit': 100,
    })

# =========================================================================
# CONFIGURACIÓN GENERAL
# =========================================================================

# Mantener compatibilidad: BASE_URL y get_api_headers() usan el primer gateway
BASE_URL = API_GATEWAYS[0]['base_url'] if API_GATEWAYS else 'https://v3.football.api-sports.io'

MAX_RETRIES = 3
RATE_LIMIT_DELAY = 60  # segundos a esperar si hay rate limit (429)

# Bookmakers preferidos para odds (en orden de preferencia)
PREFERRED_BOOKMAKERS = [26, 11, 20, 24, 1, 10, 5]  # 26 = bet365

# Regiones de ligas para la UI
LEAGUE_REGIONS = {
    'SUDAMERICA': [
        128, 129, 131, 132, 133, 134,  # Argentina
        71, 72, 75, 76,  # Brasil
        265,  # Chile
        239, 240,  # Colombia
        242, 243,  # Ecuador
        281, 282,  # Paraguay
        268, 269, 270,  # Uruguay
        299, 300,  # Venezuela
        157, 158,  # Perú
        259, 260,  # Bolivia
    ],
    'NORTEAMERICA': [
        253, 254, 255, 257,  # USA
        262, 263,  # Mexico
    ],
    'EUROPA': [
        39, 40, 41, 42, 43, 45, 48,  # Inglaterra
        140, 141,  # España
        135, 136,  # Italia
        78, 79, 80, 81,  # Alemania
        61, 62, 63, 66,  # Francia
        94, 96,  # Portugal
        88,  # Holanda
        144,  # Bélgica
    ],
    'OTROS': [
        98, 99, 100, 101, 102,  # Japón
        292, 293,  # Corea del Sur
        169, 170,  # China
        296, 297,  # Tailandia
    ],
}


def get_api_headers():
    """Retorna los headers del primer gateway disponible (compatibilidad)."""
    if not API_GATEWAYS:
        raise ValueError(
            "Ninguna API key configurada.\n"
            "  API_KEY      → key de https://dashboard.api-football.com\n"
            "  RAPIDAPI_KEY → key de RapidAPI (opcional)\n"
            "Ejemplo: export API_KEY='tu-key'"
        )
    return API_GATEWAYS[0]['headers'].copy()