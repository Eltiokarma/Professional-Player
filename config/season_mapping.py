# config/season_mapping.py
"""
Mapeo de temporada en curso por liga/pais.

API-Football usa distintas convenciones de temporada segun el pais:
- Europa: temporada cruzada (2025 = 2025/26, de julio a mayo)
- Sudamerica y la mayoria de calendario: temporada = ano calendario
- Excepciones puntuales (Mexico, MLS, copas internacionales): override manual

ACTUALIZACION:
- Cada julio (inicio de temporadas europeas)
- Cada enero (inicio de temporadas calendario)
- Cuando API-Football confirme el numero de temporada para una copa internacional

Uso:
    from config.season_mapping import get_current_season
    season = get_current_season(league_id=39, country='England')  # -> 2025
    season = get_current_season(league_id=128, country='Argentina')  # -> 2026
"""

from datetime import date
from typing import Optional


# ============================================================================
# PAISES CON TEMPORADA CRUZADA (europea: julio-mayo)
# ============================================================================
# Para estos paises: si estamos en julio-diciembre la temporada es el ano actual;
# si estamos en enero-junio la temporada es el ano anterior.

EUROPEAN_COUNTRIES = {
    'England', 'Spain', 'Italy', 'Germany', 'France', 'Portugal',
    'Netherlands', 'Belgium', 'Scotland', 'Turkey', 'Greece',
    'Switzerland', 'Austria', 'Denmark', 'Sweden', 'Poland',
    'Czech-Republic', 'Croatia', 'Ukraine', 'Russia', 'Romania',
    'Serbia', 'Hungary', 'Bulgaria', 'Slovakia', 'Slovenia',
    'Israel', 'Cyprus', 'Iceland-Wales', 'Wales', 'Northern-Ireland',
    'Ireland', 'Finland',  # nota: algunos nordicos son calendario, ver abajo
}


# ============================================================================
# PAISES CON TEMPORADA POR ANO CALENDARIO (enero-diciembre)
# ============================================================================
# Para estos paises: la temporada siempre es el ano actual.

CALENDAR_YEAR_COUNTRIES = {
    'Argentina', 'Brazil', 'Chile', 'Colombia', 'Peru', 'Uruguay',
    'Ecuador', 'Paraguay', 'Bolivia', 'Venezuela',
    'USA', 'Canada',
    'Japan', 'South-Korea', 'China', 'Australia',
    'Norway',  # Noruega es calendario pese a ser europeo
}


# ============================================================================
# OVERRIDES ESPECIFICOS POR LEAGUE_ID
# ============================================================================
# Estas ligas no siguen la convencion de su pais. Se consultan PRIMERO, antes
# que EUROPEAN_COUNTRIES o CALENDAR_YEAR_COUNTRIES.
#
# Actualizar segun lo que API-Football exponga en /leagues?current=true

LEAGUE_SEASON_OVERRIDES = {
    # --- Norteamerica ---
    262: 2025,   # Mexico - Liga MX (Apertura 2025 + Clausura 2026)
    263: 2025,   # Mexico - Liga de Expansion MX
    253: 2026,   # USA - MLS

    # --- Copas internacionales sudamericanas ---
    13:  2026,   # Copa Libertadores
    11:  2026,   # Copa Sudamericana
    541: 2026,   # Recopa Sudamericana

    # --- Copas internacionales europeas (cruzadas) ---
    2:   2025,   # UEFA Champions League
    3:   2025,   # UEFA Europa League
    848: 2025,   # UEFA Europa Conference League
    531: 2025,   # UEFA Super Cup

    # --- Mundiales / seleccion (anadir si aplican) ---
    # 1: 2026,   # World Cup - ajustar segun corresponda
}


# ============================================================================
# FUNCION PRINCIPAL
# ============================================================================

def get_current_season(
    league_id: int,
    country: str = '',
    today: Optional[date] = None
) -> int:
    """
    Retorna la temporada actualmente en curso para una liga.

    Args:
        league_id: ID de la liga en API-Football.
        country: Nombre del pais tal como aparece en leagues2024.csv
                 (columna 'Country Name'). Opcional si league_id esta
                 en LEAGUE_SEASON_OVERRIDES.
        today: Fecha de referencia (para testing). Default: hoy.

    Returns:
        Numero de temporada (ej: 2025 para 2025/26 europea o 2026 para
        calendario sudamericano).

    Ejemplos:
        >>> get_current_season(39, 'England', date(2026, 4, 10))
        2025
        >>> get_current_season(128, 'Argentina', date(2026, 4, 10))
        2026
        >>> get_current_season(262, 'Mexico', date(2026, 4, 10))
        2025
        >>> get_current_season(13, '', date(2026, 4, 10))
        2026
    """
    if today is None:
        today = date.today()

    # 1. Override explicito tiene prioridad absoluta
    if league_id in LEAGUE_SEASON_OVERRIDES:
        return LEAGUE_SEASON_OVERRIDES[league_id]

    # 2. Temporada cruzada europea
    if country in EUROPEAN_COUNTRIES:
        # Julio-diciembre: temporada = ano actual (ej: 2025 para 2025/26)
        # Enero-junio: temporada = ano anterior (seguimos en 2025/26 hasta mayo)
        return today.year if today.month >= 7 else today.year - 1

    # 3. Temporada calendario
    if country in CALENDAR_YEAR_COUNTRIES:
        return today.year

    # 4. Default conservador: asumir cruzada (la mayoria de ligas desconocidas
    #    en la BD son europeas menores)
    return today.year if today.month >= 7 else today.year - 1


def group_leagues_by_season(
    leagues: list,
    country_by_id: dict,
    today: Optional[date] = None
) -> dict:
    """
    Agrupa una lista de league_ids por su temporada en curso.

    Util para hacer llamadas batch a la API: una corrida por temporada
    que cubra todas las ligas de esa temporada.

    Args:
        leagues: Lista de league_ids (int).
        country_by_id: Dict {league_id: country_name}.
        today: Fecha de referencia (opcional).

    Returns:
        Dict {season: [league_ids]} ordenado por season.

    Ejemplo:
        >>> groups = group_leagues_by_season(
        ...     [39, 140, 128, 71, 262],
        ...     {39:'England', 140:'Spain', 128:'Argentina', 71:'Brazil', 262:'Mexico'},
        ...     date(2026, 4, 10)
        ... )
        >>> sorted(groups.keys())
        [2025, 2026]
    """
    groups: dict = {}
    for lid in leagues:
        country = country_by_id.get(lid, '')
        season = get_current_season(lid, country, today)
        groups.setdefault(season, []).append(lid)
    return dict(sorted(groups.items()))


# ============================================================================
# SELF-TEST
# ============================================================================

if __name__ == '__main__':
    # Fecha de prueba: abril 2026 (como hoy)
    test_date = date(2026, 4, 10)

    test_cases = [
        # (league_id, country, expected_season, descripcion)
        (39,  'England',   2025, 'Premier League (2025/26 en curso)'),
        (140, 'Spain',     2025, 'La Liga (2025/26 en curso)'),
        (135, 'Italy',     2025, 'Serie A'),
        (78,  'Germany',   2025, 'Bundesliga'),
        (61,  'France',    2025, 'Ligue 1'),
        (128, 'Argentina', 2026, 'Liga Profesional Argentina'),
        (71,  'Brazil',    2026, 'Brasileirao'),
        (265, 'Chile',     2026, 'Primera Division Chile'),
        (281, 'Peru',      2026, 'Liga 1 Peru'),
        (262, 'Mexico',    2025, 'Liga MX (override -> 2025)'),
        (253, 'USA',       2026, 'MLS (override -> 2026)'),
        (13,  '',          2026, 'Copa Libertadores (override)'),
        (2,   '',          2025, 'Champions League (override)'),
        (103, 'Norway',    2026, 'Eliteserien Noruega (calendario)'),
    ]

    print(f"Self-test con fecha: {test_date}")
    print("=" * 70)
    all_ok = True
    for lid, country, expected, desc in test_cases:
        got = get_current_season(lid, country, test_date)
        mark = 'OK' if got == expected else 'FAIL'
        if got != expected:
            all_ok = False
        print(f"  [{mark}] L{lid:<4} {country:<12} esperado={expected} got={got}  {desc}")

    print("=" * 70)
    print("Todos los tests pasaron" if all_ok else "HAY FALLOS")

    # Test de agrupacion
    print("\nTest group_leagues_by_season:")
    groups = group_leagues_by_season(
        [39, 140, 128, 71, 262, 13, 2],
        {39: 'England', 140: 'Spain', 128: 'Argentina',
         71: 'Brazil', 262: 'Mexico', 13: '', 2: ''},
        test_date
    )
    for season, lids in groups.items():
        print(f"  Temporada {season}: {lids}")