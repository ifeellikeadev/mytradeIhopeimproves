import json
from types import SimpleNamespace

from app import analysis, strategy, timed_exits, backtest
from test_volatility import bars, candidate


def test_agreement_is_required_even_with_volume(monkeypatch):
    monkeypatch.setattr(analysis, '_rsi', lambda *args, **kw: 75)
    data = bars()
    for i, bar in enumerate(data):
        offset = i / 20 + (1 if i == len(data)-1 else 0)
        for key in ('open', 'close', 'high', 'low'):
            setattr(bar, key, getattr(bar, key) + offset)
    report = analysis.analyse(data)
    assert report['volume_pass'] and report['long_score'] == 2
    assert report['direction'] == 'WAIT'


def test_entry_gates_have_independent_vetoes():
    result = candidate()
    result['volume_pass'] = False
    strategy.prepare(result, bars())
    assert result['direction'] == 'WAIT' and result['blocked_by'] == 'volume'
    result = candidate()
    strategy.prepare(result, bars())
    strategy.finish(result, '4h', {'direction': 'WAIT', 'long_score': 2,
                                    'short_score': 0, 'score_checks': {}})
    assert result['direction'] == 'WAIT' and result['blocked_by'] == 'higher_timeframe'
    result = candidate()
    strategy.prepare(result, bars())
    strategy.finish(result, '4h', {'direction': 'LONG', 'long_score': 3,
                                    'short_score': 0, 'score_checks': {}})
    assert result['direction'] == 'LONG'


def test_time_exit_and_priority():
    data = bars(n=5)
    trade = dict(analysis_json=json.dumps({'max_holding_candles': 2}),
                 entry_candle_time=data[0].datetime, direction='SHORT',
                 entry=100, stop_loss=103, take_profit=94)
    assert timed_exits.exit_for_trade(trade, data[:2]) is None
    assert timed_exits.exit_for_trade(trade, data)[1:3] == (data[2].datetime, 'TIME_EXIT')
    data[2].high = 104
    assert timed_exits.exit_for_trade(trade, data)[2] == 'STOP_LOSS'
    assert timed_exits.exit_for_trade(trade, data[1:]) is None


def test_historical_confirmation_never_reads_open_higher_candle(monkeypatch):
    data = bars(n=63)
    monkeypatch.setattr(strategy, 'analyse', lambda seq: seq[-1].datetime)
    at = strategy.historical_confirmation(data)
    assert at(data[59].datetime) is None
    assert at(data[60].datetime) == data[59].datetime
    assert at(data[61].datetime) == data[60].datetime


def test_backtest_uses_cap_and_does_not_invent_time_exit(monkeypatch):
    def snapshot(_):
        result = candidate()
        result['atr14'] = 2
        return result
    monkeypatch.setattr(backtest, 'analyse', snapshot)
    result = backtest.run_backtest(bars(n=119), max_holding=2)
    assert result['trades'] == 1
    assert result['trade_log'][0]['exit_reason'] == 'TIME_EXIT'
    assert result['max_holding_candles'] == 2
