#!/usr/bin/env python3
"""
Test de conexión dual: api-sports.io + RapidAPI.
Verifica ambos gateways y muestra cuota combinada.

Uso:
    $env:API_KEY = "tu-key-de-api-sports"
    $env:RAPIDAPI_KEY = "tu-key-de-rapidapi"
    python test_dual_api.py
"""

import os
import sys
import requests

# Definir gateways
GATEWAYS = []

api_key = os.getenv('API_KEY')
rapidapi_key = os.getenv('RAPIDAPI_KEY')

if api_key:
    GATEWAYS.append({
        'name': 'api-sports.io (directo)',
        'base_url': 'https://v3.football.api-sports.io',
        'headers': {'x-apisports-key': api_key},
        'key_preview': f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else api_key,
        'type': 'direct',
    })

if rapidapi_key:
    GATEWAYS.append({
        'name': 'RapidAPI',
        'base_url': 'https://api-football-v1.p.rapidapi.com/v3',
        'headers': {
            'x-rapidapi-key': rapidapi_key,
            'x-rapidapi-host': 'api-football-v1.p.rapidapi.com',
        },
        'key_preview': f"{rapidapi_key[:8]}...{rapidapi_key[-4:]}" if len(rapidapi_key) > 12 else rapidapi_key,
        'type': 'rapidapi',
    })


def test_direct_gateway(gw):
    """Testea gateway api-sports.io con /status (no consume requests)."""
    url = f"{gw['base_url']}/status"
    resp = requests.get(url, headers=gw['headers'], timeout=15)
    
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}")
        return None
    
    data = resp.json()
    
    if data.get('errors'):
        errors = data['errors']
        if isinstance(errors, dict):
            error_msg = ', '.join(f"{v}" for v in errors.values())
        else:
            error_msg = str(errors)
        
        # Verificar si es "límite alcanzado" (la API funciona pero cuota agotada hoy)
        if 'limit' in error_msg.lower() or 'request' in error_msg.lower():
            print(f"  ⚠️  Cuota agotada hoy (se resetea a medianoche UTC)")
            print(f"  ✅ Conexión OK — gateway funcional")
            return {
                'name': gw['name'],
                'current': '100',
                'limit': 100,
                'remaining': 0,
                'ok': True,
            }
        
        print(f"  ❌ Error: {error_msg}")
        return None
    
    account = data.get('response', {}).get('account', {})
    sub = data.get('response', {}).get('subscription', {})
    reqs = data.get('response', {}).get('requests', {})
    
    current = reqs.get('current', 0)
    limit = reqs.get('limit_day', 100)
    remaining = int(limit) - int(current)
    
    print(f"  Cuenta: {account.get('firstname', '?')} {account.get('lastname', '?')}")
    print(f"  Plan: {sub.get('plan', '?')}")
    print(f"  Requests: {current} / {limit} (quedan: {remaining})")
    print(f"  ✅ Conexión OK")
    
    return {
        'name': gw['name'],
        'current': current,
        'limit': limit,
        'remaining': remaining,
        'ok': True,
    }


def test_rapidapi_gateway(gw):
    """Testea gateway RapidAPI con /timezone (consume 1 request)."""
    url = f"{gw['base_url']}/timezone"
    resp = requests.get(url, headers=gw['headers'], timeout=15)
    
    if resp.status_code == 403:
        print(f"  ❌ HTTP 403 — No estás suscrito a API-Football en RapidAPI")
        print(f"     Ve a: https://rapidapi.com/api-sports/api/api-football → Subscribe (Basic/Free)")
        return None
    
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}")
        return None
    
    data = resp.json()
    
    if data.get('errors'):
        error_msg = str(data['errors'])
        if 'limit' in error_msg.lower():
            print(f"  ⚠️  Cuota agotada hoy")
            print(f"  ✅ Conexión OK — gateway funcional")
            return {
                'name': gw['name'],
                'current': '?',
                'limit': 100,
                'remaining': 0,
                'ok': True,
            }
        print(f"  ❌ Error: {error_msg}")
        return None
    
    results = data.get('results', 0)
    
    # Leer headers de rate-limit de RapidAPI
    req_remaining = resp.headers.get('x-ratelimit-requests-remaining', '?')
    req_limit = resp.headers.get('x-ratelimit-requests-limit', '100')
    
    print(f"  Respuesta: {results} timezones (API activa)")
    print(f"  Rate-limit headers: {req_remaining} restantes de {req_limit}")
    print(f"  ✅ Conexión OK")
    
    try:
        remaining = int(req_remaining)
        limit = int(req_limit)
    except (ValueError, TypeError):
        remaining = '?'
        limit = 100
    
    return {
        'name': gw['name'],
        'current': '?',
        'limit': limit,
        'remaining': remaining,
        'ok': True,
    }


def test_gateway(gw):
    """Testea un gateway según su tipo."""
    print(f"\n{'='*60}")
    print(f"  {gw['name']}")
    print(f"  Key: {gw['key_preview']}")
    print(f"{'='*60}")
    
    try:
        if gw['type'] == 'direct':
            return test_direct_gateway(gw)
        else:
            return test_rapidapi_gateway(gw)
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


if __name__ == '__main__':
    print("🔌 Test de conexión DUAL — API-Football")
    print(f"   Gateways detectados: {len(GATEWAYS)}")
    
    if not GATEWAYS:
        print("\n⚠️  No hay keys configuradas.")
        print("  $env:API_KEY = 'tu-key-de-api-sports'")
        print("  $env:RAPIDAPI_KEY = 'tu-key-de-rapidapi'")
        sys.exit(1)
    
    results = []
    total_remaining = 0
    total_limit = 0
    
    for gw in GATEWAYS:
        r = test_gateway(gw)
        results.append(r)
        if r and isinstance(r.get('remaining'), int):
            total_remaining += r['remaining']
        if r and isinstance(r.get('limit'), int):
            total_limit += r['limit']
    
    # Resumen
    print(f"\n{'='*60}")
    print("  RESUMEN")
    print(f"{'='*60}")
    
    ok_count = 0
    for r in results:
        if r and r.get('ok'):
            remaining_str = r['remaining'] if isinstance(r['remaining'], int) else '?'
            print(f"  ✅ {r['name']}: {remaining_str} restantes de {r['limit']}")
            ok_count += 1
        else:
            print(f"  ❌ Gateway falló")
    
    print(f"\n  📊 TOTAL DISPONIBLE: {total_remaining} / {total_limit} requests")
    
    if ok_count >= 2:
        print(f"\n  🎉 Modo DUAL activo — {total_limit} requests/día")
    elif ok_count == 1:
        print(f"\n  ⚠️  Solo 1 gateway activo. Configura el otro para duplicar cuota.")
    else:
        print(f"\n  ❌ Ningún gateway funciona. Revisa tus keys.")
    
    sys.exit(0 if ok_count > 0 else 1)