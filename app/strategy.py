from datetime import datetime
from bisect import bisect_right
from .analysis import analyse, apply_volatility_gate, apply_candle_gate, wait

CONFIRMATION = {'5min': '1h', '15min': '4h', '1h': '4h', '4h': '1day'}
DEFAULT_HOLD = 20


def prepare(result, candles):
    result['base_direction'] = result['direction']
    apply_volatility_gate(result, candles)
    if result['base_direction'] in ('LONG', 'SHORT') and not result.get('volume_pass', False):
        if result['direction'] != 'WAIT':
            wait(result, 'Volume below its 20-candle average or unavailable', 'volume')


def finish(result, higher_interval=None, higher=None):
    if higher_interval:
        result['higher_timeframe'] = higher_interval
        result['higher_timeframe_direction'] = higher['direction'] if higher else 'UNAVAILABLE'
        if higher:
            result['higher_timeframe_scores'] = {k: higher[k] for k in ('long_score', 'short_score', 'score_checks')}
        if result['direction'] in ('LONG', 'SHORT') and result['direction'] != result['higher_timeframe_direction']:
            wait(result, 'Higher timeframe did not confirm the direction', 'higher_timeframe')
    apply_candle_gate(result)


def historical_confirmation(higher_candles):
    # A higher bar is only eligible once the next higher bar is observed.
    # Compare to the ENTRY signal bar's opening timestamp for a conservative cutoff.
    stamps = [datetime.fromisoformat(c.datetime.replace('Z', '+00:00')) for c in higher_candles]
    if stamps != sorted(stamps) or len(set(stamps)) != len(stamps):
        raise ValueError('Higher timeframe has invalid candle ordering')
    cache = {}
    def at(stamp):
        end = bisect_right(stamps, datetime.fromisoformat(stamp.replace('Z', '+00:00'))) - 1
        if end < 60:
            return None
        if end not in cache:
            cache[end] = analyse(higher_candles[max(0, end-199):end])
        return cache[end]
    return at
