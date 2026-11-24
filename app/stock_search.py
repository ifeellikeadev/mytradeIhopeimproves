"""Optional stock discovery; never expose the provider key or provider error bodies."""
from collections import deque
import re
from time import monotonic

import httpx

TICKER = re.compile(r'[A-Z0-9][A-Z0-9.-]{0,19}', re.ASCII)
_cache = {}
_requests = deque()


async def find_stocks(query, api_key, defaults):
    key = query.casefold()
    local = [{'symbol': s, 'name': '', 'exchange': ''} for s in defaults if s.startswith(query.upper())][:10]
    if not api_key:
        return {'matches': local, 'status': 'ticker_only'}
    now = monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < 3600:
        return {'matches': cached[1], 'status': 'ok'}
    while _requests and now - _requests[0] >= 60:
        _requests.popleft()
    if len(_requests) >= 8:
        return {'matches': local, 'status': 'busy'}
    _requests.append(now)
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            response = await client.get('https://api.twelvedata.com/symbol_search',
                                        params={'symbol': query, 'outputsize': 30, 'apikey': api_key})
        response.raise_for_status()
        rows = response.json().get('data')
        if not isinstance(rows, list):
            raise ValueError('Invalid symbol search response')
    except (httpx.HTTPError, TypeError, ValueError, AttributeError):
        return {'matches': local, 'status': 'unavailable'}
    # Analysis requests accept a ticker only. Avoid adding a non-US listing
    # whose bare ticker could resolve to a different security on a US exchange.
    matches = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('country') != 'United States':
            continue
        symbol = str(row.get('symbol') or '').upper()
        if not TICKER.fullmatch(symbol) or row.get('instrument_type') not in {
            'Common Stock', 'Preferred Stock', 'ETF', 'REIT', 'American Depositary Receipt'}:
            continue
        matches.setdefault(symbol, {'symbol': symbol, 'name': str(row.get('instrument_name') or '')[:120],
                                    'exchange': str(row.get('exchange') or '')[:30]})
    result = list(matches.values())[:10]
    if len(_cache) >= 256 and key not in _cache:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (now, result)
    return {'matches': result, 'status': 'ok'}
