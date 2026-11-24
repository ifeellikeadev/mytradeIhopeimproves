from __future__ import annotations
from .market_data import Candle
import math

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

def analyse(candles: list[Candle]) -> dict:
    if len(candles)<60: raise ValueError(f"Need at least 60 candles; received {len(candles)}")
    closes=[c.close for c in candles]; volumes=[c.volume for c in candles]
    ema20=_ema(closes,20); ema50=_ema(closes,50); macd_line=[a-b for a,b in zip(_ema(closes,12),_ema(closes,26))]
    signal_line=_ema(macd_line,9); rsi=_rsi(closes); atr=_atr(candles)
    last=closes[-1]; volume_base=sum(volumes[-21:-1])/20 if sum(volumes[-21:-1])>0 else 0
    volume_ratio=(volumes[-1]/volume_base) if volume_base else None
    macd_bull=macd_line[-1]>signal_line[-1]; trend_bull=last>ema20[-1]>ema50[-1]
    trend_bear=last<ema20[-1]<ema50[-1]
    long_score=sum([trend_bull, macd_bull, rsi is not None and 50<rsi<72, volume_ratio is not None and volume_ratio>=1.0])
    short_score=sum([trend_bear, not macd_bull, rsi is not None and 28<rsi<50, volume_ratio is not None and volume_ratio>=1.0])
    if long_score>=3 and long_score>short_score: direction="LONG"
    elif short_score>=3 and short_score>long_score: direction="SHORT"
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
    return {"direction":direction,"probability":None,"probability_status":"Not available: no out-of-sample probability calibration yet.","last_close":round(last,6),"ema20":round(ema20[-1],6),"ema50":round(ema50[-1],6),"rsi14":round(rsi,2) if rsi is not None else None,"macd":round(macd_line[-1],6),"macd_signal":round(signal_line[-1],6),"atr14":round(atr,6),"volume_ratio":round(volume_ratio,2) if volume_ratio is not None else None,"candlestick_pattern":_pattern(candles),"long_score":int(long_score),"short_score":int(short_score),"entry_reference":round(entry,6) if direction!="WAIT" else None,"stop_loss":round(stop,6) if stop is not None else None,"take_profit":round(target,6) if target is not None else None,"risk_reward":"1:2" if direction!="WAIT" else None,"rationale":"; ".join(reasons),"candles_used":len(candles),"last_candle_time":candles[-1].datetime,"warning":"Rule-based research signal only. Not a validated strategy or investment recommendation; paper trading only."}
