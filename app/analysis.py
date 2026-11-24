from __future__ import annotations
from .market_data import Candle

def _ema(values, period):
    alpha=2/(period+1); out=[]; current=values[0]
    for value in values:
        current=alpha*value+(1-alpha)*current; out.append(current)
    return out

def _rsi(values, period=14):
    if len(values) <= period: return None
    changes=[values[i]-values[i-1] for i in range(1,len(values))]
    gains=[max(x,0) for x in changes]; losses=[max(-x,0) for x in changes]
    avg_gain=sum(gains[:period])/period; avg_loss=sum(losses[:period])/period
    for i in range(period,len(changes)):
        avg_gain=((period-1)*avg_gain+gains[i])/period
        avg_loss=((period-1)*avg_loss+losses[i])/period
    if avg_loss == 0: return 100.0 if avg_gain else 50.0
    return 100-(100/(1+avg_gain/avg_loss))

def _atr(candles, period=14):
    trs=[]
    for i,c in enumerate(candles):
        prev=candles[i-1].close if i else c.close
        trs.append(max(c.high-c.low,abs(c.high-prev),abs(c.low-prev)))
    return sum(trs[-period:])/min(period,len(trs))

def _pattern(candles):
    if len(candles)<2: return "None detected"
    p,c=candles[-2],candles[-1]
    body=abs(c.close-c.open); span=max(c.high-c.low,1e-12)
    lower=min(c.open,c.close)-c.low; upper=c.high-max(c.open,c.close)
    if c.close>c.open and p.close<p.open and c.open<=p.close and c.close>=p.open: return "Bullish engulfing"
    if c.close<c.open and p.close>p.open and c.open>=p.close and c.close<=p.open: return "Bearish engulfing"
    if lower >= 2*max(body,1e-9) and upper <= body and body/span < .35: return "Hammer-like candle"
    if upper >= 2*max(body,1e-9) and lower <= body and body/span < .35: return "Shooting-star-like candle"
    if body/span < .1: return "Doji-like candle"
    return "None detected"

# Paper-research settings, not validated safety thresholds.
VOLATILITY_LOOKBACK = 100
VOLATILITY_PERCENTILE = 0.90
VOLATILITY_SPIKE_MULTIPLE = 3.0
# None reports quiet conditions without blocking them; set to 0.10 to test a quiet gate.
QUIET_BLOCK_PERCENTILE = None
CANDLE_GATE_ENABLED = True


def _percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    left = int(index)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (index - left) * (ordered[right] - ordered[left])


def volatility(candles):
    # Need a prior close for every true range, plus 100 prior ATR% observations.
    sample = candles[-(VOLATILITY_LOOKBACK + 15):]
    if len(sample) < VOLATILITY_LOOKBACK + 15:
        return {'status': 'UNAVAILABLE', 'atr_pct': None, 'high_threshold_pct': None,
                'bar_range_pct': None, 'spike_threshold_pct': None}
    ranges = []
    for previous, current in zip(sample, sample[1:]):
        ranges.append(max(current.high - current.low,
                          abs(current.high - previous.close), abs(current.low - previous.close)))
    atr_pcts = [100 * (sum(ranges[i-13:i+1]) / 14) / sample[i+1].close
                for i in range(13, len(ranges))]
    range_pcts = [100 * value / bar.close for value, bar in zip(ranges, sample[1:])]
    high = _percentile(atr_pcts[:-1], VOLATILITY_PERCENTILE)
    quiet = _percentile(atr_pcts[:-1], 0.10 if QUIET_BLOCK_PERCENTILE is None else QUIET_BLOCK_PERCENTILE)
    normal_range = _percentile(range_pcts[-(VOLATILITY_LOOKBACK+1):-1], 0.5)
    shock_limit = normal_range * VOLATILITY_SPIKE_MULTIPLE
    latest, bar_range = atr_pcts[-1], range_pcts[-1]
    status = ('EXTREME' if latest > high or bar_range > shock_limit
              else 'QUIET' if latest < quiet else 'TYPICAL')
    return {'status': status, 'atr_pct': round(latest, 6), 'high_threshold_pct': round(high, 6),
            'bar_range_pct': round(bar_range, 6), 'spike_threshold_pct': round(shock_limit, 6)}


def wait(result, reason, gate):
    result.update(direction='WAIT', entry_reference=None, stop_loss=None, take_profit=None,
                  risk_reward=None, blocked_by=gate)
    result['rationale'] += '; ' + reason


def apply_volatility_gate(result, candles):
    metrics = result['volatility'] = volatility(candles)
    if result['direction'] not in ('LONG', 'SHORT'):
        return
    reason = {'EXTREME': 'Volatility too high: ATR% or latest candle range exceeded its limit',
              'UNAVAILABLE': 'Not enough data to assess volatility'}.get(metrics['status'])
    if metrics['status'] == 'QUIET' and QUIET_BLOCK_PERCENTILE is not None:
        reason = 'Volatility below the configured quiet-market limit'
    if reason:
        wait(result, reason, 'volatility')


def apply_candle_gate(result):
    if not CANDLE_GATE_ENABLED or result['direction'] not in ('LONG', 'SHORT'):
        return
    expected = {'LONG': 'Bullish engulfing', 'SHORT': 'Bearish engulfing'}[result['direction']]
    if result['candlestick_pattern'] != expected:
        wait(result, 'Candle gate: expected ' + expected, 'candlestick')


def analyse(candles: list[Candle]) -> dict:
    if len(candles)<60: raise ValueError(f"Need at least 60 candles; received {len(candles)}")
    closes=[c.close for c in candles]; volumes=[c.volume for c in candles]
    ema20=_ema(closes,20); ema50=_ema(closes,50); macd_line=[a-b for a,b in zip(_ema(closes,12),_ema(closes,26))]
    signal_line=_ema(macd_line,9); rsi=_rsi(closes); atr=_atr(candles)
    last=closes[-1]; volume_base=sum(volumes[-21:-1])/20 if sum(volumes[-21:-1])>0 else 0
    volume_ratio=(volumes[-1]/volume_base) if volume_base else None
    macd_bull=macd_line[-1]>signal_line[-1]; trend_bull=last>ema20[-1]>ema50[-1]
    trend_bear=last<ema20[-1]<ema50[-1]
    volume_ok = volume_ratio is not None and volumes[-1] > 0 and volume_ratio >= 1.0
    score_checks = {
        'LONG': {'Trend': trend_bull, 'Momentum': macd_bull,
                 'RSI': rsi is not None and 50 < rsi < 72},
        'SHORT': {'Trend': trend_bear, 'Momentum': not macd_bull,
                  'RSI': rsi is not None and 28 < rsi < 50},
    }
    long_score = sum(score_checks['LONG'].values())
    short_score = sum(score_checks['SHORT'].values())
    if long_score==3 and long_score>short_score: direction="LONG"
    elif short_score==3 and short_score>long_score: direction="SHORT"
    else: direction="WAIT"
    risk_distance=max(1.5*atr,last*.002)
    entry=last
    stop=entry-risk_distance if direction=="LONG" else entry+risk_distance if direction=="SHORT" else None
    target=entry+2*risk_distance if direction=="LONG" else entry-2*risk_distance if direction=="SHORT" else None
    reasons=[]
    reasons.append("Price/EMA trend is bullish" if trend_bull else "Price/EMA trend is bearish" if trend_bear else "EMA trend is mixed")
    reasons.append("MACD momentum is bullish" if macd_bull else "MACD momentum is bearish")
    reasons.append(f"RSI(14) is {rsi:.1f}" if rsi is not None else "RSI unavailable")
    reasons.append(f"Latest volume is {volume_ratio:.2f}x its 20-candle average" if volume_ratio is not None else "Volume unavailable")
    return {"direction":direction,"score_checks":score_checks,"volume_pass":volume_ok,"probability":None,"probability_status":"Not available: no out-of-sample probability calibration yet.","last_close":round(last,6),"ema20":round(ema20[-1],6),"ema50":round(ema50[-1],6),"rsi14":round(rsi,2) if rsi is not None else None,"macd":round(macd_line[-1],6),"macd_signal":round(signal_line[-1],6),"atr14":round(atr,6),"volume_ratio":round(volume_ratio,2) if volume_ratio is not None else None,"candlestick_pattern":_pattern(candles),"long_score":int(long_score),"short_score":int(short_score),"entry_reference":round(entry,6) if direction!="WAIT" else None,"stop_loss":round(stop,6) if stop is not None else None,"take_profit":round(target,6) if target is not None else None,"risk_reward":"1:2" if direction!="WAIT" else None,"rationale":"; ".join(reasons),"candles_used":len(candles),"last_candle_time":candles[-1].datetime,"warning":"Rule-based research signal only. Not a validated strategy or investment recommendation; paper trading only."}
