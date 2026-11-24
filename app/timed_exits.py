"""Apply a time stop to new paper positions without migrating or deleting records."""
import json
from .db import connect, update_trade


def exit_for_trade(trade, candles):
    cap = json.loads(trade['analysis_json']).get('max_holding_candles')
    if not isinstance(cap, int) or not 1 <= cap <= 100:
        cap = None  # Trades recorded under the old strategy keep their old rules.
    if cap and (not candles or candles[0].datetime > trade['entry_candle_time']):
        return None  # Cannot establish exact elapsed bars or earlier touches.
    long = trade['direction'] == 'LONG'
    following = (bar for bar in candles if bar.datetime > trade['entry_candle_time'])
    stop, target = trade['stop_loss'], trade['take_profit']
    for held, bar in enumerate(following, 1):
        if (bar.low <= stop if long else bar.high >= stop):
            price, reason = (min(bar.open, stop) if long else max(bar.open, stop)), 'STOP_LOSS'
        elif (bar.high >= target if long else bar.low <= target):
            price, reason = target, 'TAKE_PROFIT'
        elif cap is not None and held >= cap:
            price, reason = bar.close, 'TIME_EXIT'
        else:
            continue
        risk = abs(trade['entry']-stop)
        result = ((price-trade['entry']) if long else (trade['entry']-price))/risk if risk else 0.0
        return price, bar.datetime, reason, round(result, 3)
    return None


def update_paper_trades(symbol, timeframe, candles):
    with connect() as connection:
        trades = connection.execute("""SELECT p.*, s.analysis_json FROM paper_trades p
            JOIN signals s ON s.id=p.signal_id
            WHERE p.status='OPEN' AND p.symbol=? AND p.timeframe=?""", (symbol, timeframe)).fetchall()
    closed = []
    for trade in trades:
        exit_data = exit_for_trade(trade, candles)
        if exit_data:
            update_trade(trade['id'], *exit_data)
            closed.append(trade['id'])
    return closed
