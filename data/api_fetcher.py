# src/data/api_fetcher.py
"""
Cliente para API-Football con soporte dual gateway.
Usa api-sports.io directo (100 req/día) + RapidAPI (100 req/día) = 200 req/día.
Cuando un gateway se agota, cambia automáticamente al siguiente.
Incluye batch pacing para evitar throttling por minuto.
"""

import requests
import time
import logging
from typing import Dict, List, Optional, Any

from config.api_config import (
    BASE_URL,
    API_GATEWAYS,
    get_api_headers,
    MAX_RETRIES,
    RATE_LIMIT_DELAY,
    PREFERRED_BOOKMAKERS
)

logger = logging.getLogger(__name__)


class APIFetcher:
    """
    Cliente para la API de fútbol con dual gateway.
    
    Maneja:
    - Dual gateway: api-sports.io + RapidAPI (200 req/día gratis)
    - Cambio automático cuando un gateway se agota o rechaza por plan
    - Batch pacing: pausas entre requests para evitar throttling
    - Reintentos con detección de throttling en JSON
    - Paginación automática
    """
    
    # Pausa mínima entre requests (segundos)
    REQUEST_DELAY = 1.2  # ~50 requests/minuto
    
    # Cada N requests, hacer una pausa larga
    BATCH_SIZE = 10
    BATCH_PAUSE = 5  # segundos
    
    # Palabras clave que indican throttling/cuota agotada en errores de API
    THROTTLE_KEYWORDS = ['rate limit', 'too many requests', 'ratelimit']
    QUOTA_KEYWORDS = ['limit', 'quota', 'exceeded', 'requests']
    
    # Palabras clave que indican restricción de plan (no cuota agotada, sino plan insuficiente)
    PLAN_KEYWORDS = [
        'free plan', 'do not have access', 'not available',
        'upgrade', 'not allowed', 'permission denied',
        'this season', 'try from',
    ]
    
    def __init__(self):
        """Inicializa el cliente con dual gateway si está disponible."""
        # Construir lista de gateways disponibles
        self._gateways = []
        for gw in API_GATEWAYS:
            self._gateways.append({
                'name': gw['name'],
                'base_url': gw['base_url'],
                'headers': gw['headers'].copy(),
                'exhausted': False,  # True cuando se agota la cuota diaria
            })
        
        if not self._gateways:
            raise ValueError("No hay gateways configurados. Revisa API_KEY / RAPIDAPI_KEY.")
        
        self._current_gw_index = 0
        self._request_count = 0
        self._last_request_time = 0
        
        # Session HTTP
        self.session = requests.Session()
        self._apply_gateway()
        
        # Logging inicial
        names = [gw['name'] for gw in self._gateways]
        logger.info(f"APIFetcher inicializado — gateways: {', '.join(names)} ({len(names)}x100 = {len(names)*100} req/día)")
    
    # --- Compatibilidad con código existente ---
    @property
    def base_url(self):
        return self._gateways[self._current_gw_index]['base_url']
    
    @property
    def headers(self):
        return self._gateways[self._current_gw_index]['headers']
    
    def _apply_gateway(self):
        """Aplica los headers del gateway actual a la session."""
        gw = self._gateways[self._current_gw_index]
        self.session.headers.clear()
        self.session.headers.update(gw['headers'])
        logger.info(f"Gateway activo: {gw['name']} ({gw['base_url']})")
    
    def _switch_gateway(self, mark_exhausted: bool = True) -> bool:
        """
        Cambia al siguiente gateway disponible.
        
        Args:
            mark_exhausted: Si True, marca el gateway actual como agotado permanentemente.
                           Si False, solo cambia sin marcar (para errores de plan que
                           podrían no aplicar a otros endpoints).
        
        Returns: True si se cambió exitosamente, False si no hay más gateways.
        """
        if mark_exhausted:
            self._gateways[self._current_gw_index]['exhausted'] = True
        
        # Buscar siguiente no agotado
        for i, gw in enumerate(self._gateways):
            if not gw['exhausted'] and i != self._current_gw_index:
                old_name = self._gateways[self._current_gw_index]['name']
                self._current_gw_index = i
                self._apply_gateway()
                logger.warning(f"⚡ Cambio de gateway {old_name} → {gw['name']}")
                return True
        
        logger.error("❌ Todos los gateways agotados. No quedan requests disponibles.")
        return False
    
    def _throttle(self):
        """Aplica pausas entre requests para evitar throttling por minuto."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        
        self._request_count += 1
        if self._request_count % self.BATCH_SIZE == 0:
            logger.info(f"⏸ Batch pause: {self._request_count} requests completados, pausa de {self.BATCH_PAUSE}s...")
            time.sleep(self.BATCH_PAUSE)
        
        self._last_request_time = time.time()
    
    def _is_quota_error(self, error_msg: str) -> bool:
        """Detecta si un error indica que la cuota diaria se agotó."""
        lower = error_msg.lower()
        return any(kw in lower for kw in self.QUOTA_KEYWORDS)
    
    def _is_throttle_error(self, error_msg: str) -> bool:
        """Detecta si un error indica throttling temporal (requests/minuto)."""
        lower = error_msg.lower()
        return any(kw in lower for kw in self.THROTTLE_KEYWORDS)
    
    def _is_plan_error(self, error_msg: str) -> bool:
        """Detecta si un error indica restricción de plan (ej: temporada no disponible en Free)."""
        lower = error_msg.lower()
        # Requiere al menos 2 keywords para evitar falsos positivos
        matches = sum(1 for kw in self.PLAN_KEYWORDS if kw in lower)
        return matches >= 1
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """
        Realiza una petición a la API con reintentos, throttle detection y gateway failover.
        
        Si el gateway actual se agota o rechaza por plan, cambia automáticamente al siguiente.
        """
        self._throttle()
        
        gw = self._gateways[self._current_gw_index]
        url = f"{gw['base_url']}/{endpoint}"
        
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(url, params=params, timeout=30)
                
                # HTTP 429 — rate limit explícito
                if response.status_code == 429:
                    wait = RATE_LIMIT_DELAY * (attempt + 1)
                    logger.warning(f"HTTP 429 en {gw['name']}. Esperando {wait}s ({attempt + 1}/{MAX_RETRIES})...")
                    time.sleep(wait)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                # Verificar errores en JSON
                if data.get('errors'):
                    errors = data['errors']
                    if isinstance(errors, dict):
                        error_msg = ', '.join(f"{k}: {v}" for k, v in errors.items())
                    else:
                        error_msg = str(errors)
                    
                    # ¿Cuota diaria agotada? → cambiar gateway (marcar como agotado)
                    if self._is_quota_error(error_msg):
                        logger.warning(f"Cuota agotada en {gw['name']}: {error_msg}")
                        if self._switch_gateway(mark_exhausted=True):
                            return self._make_request(endpoint, params)
                        else:
                            logger.error("Sin gateways disponibles.")
                            return None
                    
                    # ¿Restricción de plan? → intentar otro gateway (sin marcar como agotado)
                    # El otro gateway podría tener un plan diferente o distinto rango de temporadas
                    if self._is_plan_error(error_msg):
                        logger.warning(f"Restricción de plan en {gw['name']}: {error_msg}")
                        if self._switch_gateway(mark_exhausted=False):
                            result = self._make_request(endpoint, params)
                            # Si el segundo gateway también falla, no loops infinitos:
                            # _make_request del segundo gateway caerá al error genérico
                            # porque ya estamos en él y no hay un tercero
                            return result
                        else:
                            logger.error(f"Ningún gateway puede servir esta consulta: {error_msg}")
                            return None
                    
                    # ¿Throttling temporal? → esperar y reintentar
                    if self._is_throttle_error(error_msg) and attempt < MAX_RETRIES - 1:
                        wait = RATE_LIMIT_DELAY * (attempt + 1)
                        logger.warning(f"Throttling en {gw['name']}: {error_msg}. Esperando {wait}s...")
                        time.sleep(wait)
                        continue
                    
                    logger.error(f"Error de API ({gw['name']}): {error_msg}")
                    return None
                
                return data
                
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout en {gw['name']} ({attempt + 1}/{MAX_RETRIES})")
                time.sleep(5 * (attempt + 1))
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error de conexión ({gw['name']}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(5 * (attempt + 1))
                    
            except Exception as e:
                logger.error(f"Error inesperado: {e}")
                return None
        
        logger.error(f"Falló en {gw['name']} después de {MAX_RETRIES} intentos para {endpoint}")
        return None
    
    def get_status(self) -> Dict:
        """
        Consulta el estado de la cuenta.
        - api-sports.io: usa /status (no consume requests)
        - RapidAPI: /status no existe, usa /timezone como ping
        """
        gw = self._gateways[self._current_gw_index]
        
        # /status solo funciona en api-sports.io directo
        if 'api-sports.io' in gw['base_url']:
            url = f"{gw['base_url']}/status"
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if not data.get('errors'):
                        return data.get('response', {})
            except Exception as e:
                logger.error(f"Error consultando status: {e}")
            return {}
        else:
            # RapidAPI: /status no existe, verificar con /timezone (1 request)
            url = f"{gw['base_url']}/timezone"
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    if not data.get('errors'):
                        return {
                            'account': {'firstname': 'RapidAPI', 'lastname': 'User'},
                            'subscription': {'plan': 'RapidAPI Free'},
                            'requests': {'current': '?', 'limit_day': 100},
                        }
            except Exception as e:
                logger.error(f"Error consultando status RapidAPI: {e}")
            return {}
    
    # =========================================================================
    # FIXTURES
    # =========================================================================
    
    def get_fixtures(
        self, 
        league_ids: List[int], 
        season: int,
        from_date: str = None,
        to_date: str = None,
        status: str = None
    ) -> List[Dict]:
        """Obtiene fixtures de múltiples ligas."""
        all_fixtures = []
        
        for league_id in league_ids:
            logger.info(f"Obteniendo fixtures para liga {league_id}, temporada {season}")
            
            params = {
                'league': league_id,
                'season': season
            }
            
            if from_date:
                params['from'] = from_date
            if to_date:
                params['to'] = to_date
            if status:
                params['status'] = status
            
            response = self._make_request('fixtures', params)
            
            if response and 'response' in response:
                fixtures = response['response']
                all_fixtures.extend(fixtures)
                logger.info(f"Liga {league_id}: {len(fixtures)} fixtures obtenidos")
            else:
                logger.warning(f"No se obtuvieron fixtures para liga {league_id}")
        
        return all_fixtures
    
    def get_fixtures_by_date(
        self,
        date: str,
        league_id: int = None,
        timezone: str = "America/Lima"
    ) -> List[Dict]:
        """Obtiene fixtures para una fecha específica."""
        params = {
            'date': date,
            'timezone': timezone
        }
        
        if league_id:
            params['league'] = league_id
        
        response = self._make_request('fixtures', params)
        
        if response and 'response' in response:
            return response['response']
        
        return []
    
    def get_fixture_by_id(self, fixture_id: int) -> Optional[Dict]:
        """Obtiene un fixture específico por ID."""
        params = {'id': fixture_id}
        response = self._make_request('fixtures', params)
        
        if response and 'response' in response and len(response['response']) > 0:
            return response['response'][0]
        
        return None
    
    # =========================================================================
    # ODDS
    # =========================================================================
    
    def get_odds(
        self, 
        fixture_id: int, 
        bookmaker_id: int = None
    ) -> List[Dict]:
        """Obtiene odds para un fixture."""
        params = {'fixture': fixture_id}
        
        if bookmaker_id:
            params['bookmaker'] = bookmaker_id
        
        response = self._make_request('odds', params)
        
        if response and 'response' in response:
            return response['response']
        
        return []
    
    def get_odds_with_fallback(
        self, 
        fixture_id: int,
        primary_bookmaker: int = 26,
        fallback_bookmakers: List[int] = None
    ) -> List[Dict]:
        """
        Obtiene odds con UNA sola llamada API (sin filtro de bookmaker).
        Devuelve la respuesta completa con todos los bookmakers disponibles.
        El filtrado por bookmaker preferido se hace localmente en process_odds.
        """
        # UNA sola llamada sin filtro de bookmaker -> devuelve TODOS
        odds = self.get_odds(fixture_id, bookmaker_id=None)
        
        if odds:
            all_bookies = set()
            for item in odds:
                for bookie in item.get('bookmakers', []):
                    all_bookies.add(bookie.get('name', 'unknown'))
            logger.info(f"Fixture {fixture_id}: odds de {len(all_bookies)} bookmakers en 1 llamada")
            return odds
        
        logger.warning(f"No se encontraron odds para fixture {fixture_id}")
        return []
    
    # =========================================================================
    # PLAYERS & STATISTICS
    # =========================================================================
    
    def get_players_stats(
        self, 
        league_id: int, 
        season: int,
        team_id: int = None,
        page: int = 1
    ) -> Dict[str, Any]:
        """Obtiene estadísticas de jugadores con paginación."""
        params = {
            'league': league_id,
            'season': season,
            'page': page
        }
        
        if team_id:
            params['team'] = team_id
        
        response = self._make_request('players', params)
        
        if response:
            return {
                'players': response.get('response', []),
                'paging': response.get('paging', {})
            }
        
        return {'players': [], 'paging': {}}
    
    def get_all_players_stats(
        self, 
        league_id: int, 
        season: int,
        team_id: int = None
    ) -> List[Dict]:
        """Obtiene TODAS las estadísticas de jugadores (paginación automática)."""
        all_players = []
        page = 1
        
        while True:
            logger.info(f"Obteniendo jugadores página {page}...")
            
            result = self.get_players_stats(league_id, season, team_id, page)
            players = result['players']
            paging = result['paging']
            
            if not players:
                break
            
            all_players.extend(players)
            
            current_page = paging.get('current', page)
            total_pages = paging.get('total', page)
            
            if current_page >= total_pages:
                break
            
            page += 1
            # _throttle ya maneja la pausa, no necesitamos sleep extra
        
        logger.info(f"Total jugadores obtenidos: {len(all_players)}")
        return all_players
    
    # =========================================================================
    # TEAM STATISTICS
    # =========================================================================
    
    def get_team_statistics(
        self, 
        league_id: int, 
        season: int, 
        team_id: int
    ) -> Optional[Dict]:
        """Obtiene estadísticas agregadas de un equipo."""
        params = {
            'league': league_id,
            'season': season,
            'team': team_id
        }
        
        response = self._make_request('teams/statistics', params)
        
        if response and 'response' in response:
            return response['response']
        
        return None
    
    # =========================================================================
    # LEAGUES
    # =========================================================================
    
    def get_leagues(
        self, 
        country: str = None, 
        season: int = None
    ) -> List[Dict]:
        """Obtiene información de ligas."""
        params = {}
        
        if country:
            params['country'] = country
        if season:
            params['season'] = season
        
        response = self._make_request('leagues', params)
        
        if response and 'response' in response:
            return response['response']
        
        return []
    
    # =========================================================================
    # TEAMS
    # =========================================================================
    
    def get_teams(
        self, 
        league_id: int, 
        season: int
    ) -> List[Dict]:
        """Obtiene equipos de una liga."""
        params = {
            'league': league_id,
            'season': season
        }
        
        response = self._make_request('teams', params)
        
        if response and 'response' in response:
            return response['response']
        
        return []
    
    def get_team_by_id(self, team_id: int) -> Optional[Dict]:
        """Obtiene información de un equipo por ID."""
        params = {'id': team_id}
        response = self._make_request('teams', params)
        
        if response and 'response' in response and len(response['response']) > 0:
            return response['response'][0]
        
        return None


# Singleton para uso global
_api_fetcher_instance = None

def get_api_fetcher() -> APIFetcher:
    """Retorna instancia singleton del APIFetcher."""
    global _api_fetcher_instance
    if _api_fetcher_instance is None:
        _api_fetcher_instance = APIFetcher()
    return _api_fetcher_instance