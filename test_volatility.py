import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from app import analysis, main
from app.market_data import Candle


def bars(n=160, spike=False):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [Candle((start + timedelta(minutes=15*i)).isoformat(), 100,
                   108 if spike and i == n-1 else 101, 99, 100, 1000)
            for i in range(n)]


def candidate(side='LONG', pattern='Bullish engulfing'):
    return {'direction': side, 'rationale': 'directional setup', 'volume_pass': True, 'candlestick_pattern': pattern,
            'entry_reference': 100, 'stop_loss': 97, 'take_profit': 106, 'risk_reward': '1:2'}


@pytest.mark.parametrize('side', ['LONG', 'SHORT'])
def test_spike_blocks_either_side(side):
    result = candidate(side)
    analysis.apply_volatility_gate(result, bars(spike=True))
    assert result['direction'] == 'WAIT' and result['blocked_by'] == 'volatility'
    assert result['volatility']['high_threshold_pct'] == 2
    assert all(result[key] is None for key in ('entry_reference', 'stop_loss', 'take_profit', 'risk_reward'))


def test_history_required_and_equal_range_is_not_extreme():
    result = candidate()
    analysis.apply_volatility_gate(result, bars(n=114))
    assert result['direction'] == 'WAIT' and result['volatility']['status'] == 'UNAVAILABLE'
    result = candidate()
    analysis.apply_volatility_gate(result, bars(n=115))
    assert result['direction'] == 'LONG' and result['volatility']['status'] == 'TYPICAL'


def test_candle_gate_can_only_veto():
    unrelated = candidate(pattern='Doji-like candle')
    analysis.apply_candle_gate(unrelated)
    assert unrelated['direction'] == 'WAIT' and unrelated['blocked_by'] == 'candlestick'
    matched = candidate('SHORT', 'Bearish engulfing')
    analysis.apply_candle_gate(matched)
    assert matched['direction'] == 'SHORT'
    analysis.apply_candle_gate(unrelated)
    assert unrelated['direction'] == 'WAIT'


def test_sustained_volatility_can_block_without_a_single_spike():
    data = bars()
    for bar in data[-5:]:
        bar.high = 102
    result = analysis.volatility(data)
    assert result['status'] == 'EXTREME'
    assert result['bar_range_pct'] < result['spike_threshold_pct']


def test_latest_bar_omitted_and_extreme_signal_never_opens(monkeypatch):
    data = bars(spike=True) + [bars(n=161)[-1]]
    async def fetch(symbol, interval, n):
        if interval != '15min':
            raise RuntimeError('Unavailable higher timeframe')
        return data, 'test', []
    monkeypatch.setattr(main.router, 'candles', fetch)
    monkeypatch.setattr(main, 'analyse', lambda selected: candidate())
    monkeypatch.setattr(main, 'update_paper_trades', lambda *args: [42])
    def save(symbol, interval, result, provider):
        assert result['direction'] == 'WAIT'
        return 7, False
    monkeypatch.setattr(main, 'save_signal', save)
    response = asyncio.run(main.analyse_symbol('TEST', '15min'))
    assert response['blocked_by'] == 'volatility'
    assert response['paper_trade_opened'] is False and response['closed_paper_trade_ids'] == [42]
