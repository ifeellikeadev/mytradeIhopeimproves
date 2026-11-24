from __future__ import annotations
from .analysis import analyse, apply_volatility_gate, apply_candle_gate
from .market_data import Candle

def run_backtest(candles: list[Candle], max_holding: int = 20) -> dict:
    if len(candles) < 100:
        raise ValueError(f"At least 100 candles are required for a useful basic backtest; received {len(candles)}")
    trades=[]
    blocked={'volatility': 0, 'candlestick': 0}
    i=59
    while i < len(candles)-1:
        snapshot=analyse(candles[:i+1])
        apply_volatility_gate(snapshot, candles[:i+1])
        apply_candle_gate(snapshot)
        if snapshot.get('blocked_by') in blocked:
            blocked[snapshot['blocked_by']] += 1
        direction=snapshot['direction']
        if direction == 'WAIT':
            i += 1
            continue
        entry_bar=candles[i+1]
        entry=entry_bar.open
        risk=max(1.5*snapshot['atr14'],entry*.002)
        if direction == 'LONG': stop=entry-risk; target=entry+2*risk
        else: stop=entry+risk; target=entry-2*risk
        exit_price=None; exit_time=None; reason=None; exit_index=None
        end=min(len(candles),i+1+max_holding)
        for j in range(i+1,end):
            bar=candles[j]
            if direction == 'LONG':
                stop_hit=bar.low<=stop; target_hit=bar.high>=target
                if stop_hit:
                    exit_price=min(bar.open,stop) if bar.open<stop else stop
                    reason='STOP_LOSS'
                elif target_hit:
                    exit_price=target; reason='TAKE_PROFIT'
            else:
                stop_hit=bar.high>=stop; target_hit=bar.low<=target
                if stop_hit:
                    exit_price=max(bar.open,stop) if bar.open>stop else stop
                    reason='STOP_LOSS'
                elif target_hit:
                    exit_price=target; reason='TAKE_PROFIT'
            if exit_price is not None:
                exit_time=bar.datetime; exit_index=j; break
        if exit_price is None:
            exit_index=end-1
            exit_bar=candles[exit_index]
            exit_price=exit_bar.close; exit_time=exit_bar.datetime; reason='TIME_EXIT'
        r=(exit_price-entry)/risk if direction=='LONG' else (entry-exit_price)/risk
        trades.append({'direction':direction,'signal_time':candles[i].datetime,'entry_time':entry_bar.datetime,'exit_time':exit_time,'entry':round(entry,6),'stop_loss':round(stop,6),'take_profit':round(target,6),'exit':round(exit_price,6),'exit_reason':reason,'result_r':round(r,3)})
        i=max(i+1,exit_index+1)
    rs=[t['result_r'] for t in trades]
    wins=[r for r in rs if r>0]; losses=[r for r in rs if r<0]
    gross_win=sum(wins); gross_loss=abs(sum(losses))
    equity=peak=drawdown=0.0
    for r in rs:
        equity+=r; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    return {'candles_tested':len(candles),'blocked_candidates':blocked,'trades':len(trades),'wins':len(wins),'losses':len(losses),'win_rate_pct':round(len(wins)/len(rs)*100,2) if rs else None,'net_r':round(sum(rs),2),'expectancy_r':round(sum(rs)/len(rs),3) if rs else None,'profit_factor':round(gross_win/gross_loss,2) if gross_loss else (None if not gross_win else 'infinite'),'max_drawdown_r':round(drawdown,2),'max_holding_candles':max_holding,'trade_log':trades[-100:],'warning':'Historical simulation, not a forecast. It applies the volatility and candle gates but does not simulate live higher-timeframe confirmation. It uses a simple heuristic strategy, assumes next-candle-open entries, ignores spread/fees/slippage/borrow costs, and resolves same-candle stop/target ambiguity in favour of the stop. Results are not out-of-sample proof and do not establish a calibrated probability.'}
