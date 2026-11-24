import asyncio
from unittest.mock import AsyncMock

from app import analysis, main, stock_search
from test_volatility import bars


def test_breakdown_uses_the_same_rules_as_score():
    series = bars()
    for i, bar in enumerate(series):
        bar.open += i / 20
        bar.close += i / 20
        bar.high += i / 20
        bar.low += i / 20
    report = analysis.analyse(series)
    assert report['score_checks']['LONG']['Trend'] is True
    assert report['score_checks']['SHORT']['Trend'] is False
    for direction in ('LONG', 'SHORT'):
        assert set(report['score_checks'][direction]) == {'Trend', 'Momentum', 'RSI'}
        assert report[direction.lower() + '_score'] == sum(report['score_checks'][direction].values())


def test_stock_search_without_key_is_safe():
    result = asyncio.run(stock_search.find_stocks('aap', '', ['AAPL', 'NVDA']))
    assert result == {'matches': [{'symbol': 'AAPL', 'name': '', 'exchange': ''}], 'status': 'ticker_only'}


def test_search_filters_and_caches_provider_results(monkeypatch):
    import httpx
    payload = {'data': [
        {'symbol': 'AAPL', 'instrument_name': 'Apple Inc.', 'exchange': 'NASDAQ', 'country': 'United States', 'instrument_type': 'Common Stock'},
        {'symbol': 'AAPL', 'instrument_name': 'Other listing', 'country': 'Germany', 'instrument_type': 'Common Stock'},
        {'symbol': 'bad/token', 'country': 'United States', 'instrument_type': 'Common Stock'},
    ]}
    get = AsyncMock(return_value=httpx.Response(200, json=payload, request=httpx.Request('GET', 'https://example.test')))
    monkeypatch.setattr(stock_search.httpx.AsyncClient, 'get', get)
    monkeypatch.setattr(stock_search, '_cache', {})
    monkeypatch.setattr(main, 'TWELVE_DATA_API_KEY', 'mock-test-key')
    result = asyncio.run(main.stock_search('  Apple  '))
    assert result == {'matches': [{'symbol': 'AAPL', 'name': 'Apple Inc.', 'exchange': 'NASDAQ'}], 'status': 'ok'}
    assert asyncio.run(main.stock_search('apple')) == result
    assert get.await_count == 1
