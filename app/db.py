import json, sqlite3
from datetime import datetime, timezone
from .config import DATABASE_PATH, STRATEGY_VERSION

def connect():
    conn=sqlite3.connect(DATABASE_PATH, timeout=20); conn.row_factory=sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA foreign_keys=ON"); return conn

def init_db():
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, direction TEXT NOT NULL, entry_reference REAL, stop_loss REAL, take_profit REAL, candle_time TEXT, provider TEXT, analysis_json TEXT NOT NULL, strategy_version TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id INTEGER NOT NULL UNIQUE REFERENCES signals(id), created_at TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, direction TEXT NOT NULL, entry REAL NOT NULL, stop_loss REAL NOT NULL, take_profit REAL NOT NULL, entry_candle_time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', exit REAL, exit_time TEXT, exit_reason TEXT, result_r REAL)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_paper_open ON paper_trades(status,symbol,timeframe)")

def save_signal(symbol, timeframe, analysis, provider):
    now=datetime.now(timezone.utc).isoformat()
    with connect() as c:
        cur=c.execute("INSERT INTO signals(created_at,symbol,timeframe,direction,entry_reference,stop_loss,take_profit,candle_time,provider,analysis_json,strategy_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(now,symbol,timeframe,analysis['direction'],analysis.get('entry_reference'),analysis.get('stop_loss'),analysis.get('take_profit'),analysis['last_candle_time'],provider,json.dumps(analysis),STRATEGY_VERSION))
        signal_id=cur.lastrowid
        trade_opened=False
        if analysis['direction'] in ('LONG','SHORT'):
            existing=c.execute("SELECT id FROM paper_trades WHERE symbol=? AND timeframe=? AND direction=? AND entry_candle_time=?",(symbol,timeframe,analysis['direction'],analysis['last_candle_time'])).fetchone()
            if not existing:
                c.execute("INSERT INTO paper_trades(signal_id,created_at,symbol,timeframe,direction,entry,stop_loss,take_profit,entry_candle_time) VALUES(?,?,?,?,?,?,?,?,?)",(signal_id,now,symbol,timeframe,analysis['direction'],analysis['entry_reference'],analysis['stop_loss'],analysis['take_profit'],analysis['last_candle_time']))
                trade_opened=True
        return int(signal_id), trade_opened

def list_signals(limit=100):
    with connect() as c: rows=c.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r)|{'analysis':json.loads(r['analysis_json'])} for r in rows]

def list_trades(status=None,limit=200):
    with connect() as c:
        if status: rows=c.execute("SELECT * FROM paper_trades WHERE status=? ORDER BY id DESC LIMIT ?",(status,limit)).fetchall()
        else: rows=c.execute("SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r) for r in rows]

def update_trade(trade_id, exit_price, exit_time, reason, result_r):
    with connect() as c: c.execute("UPDATE paper_trades SET status='CLOSED',exit=?,exit_time=?,exit_reason=?,result_r=? WHERE id=? AND status='OPEN'",(exit_price,exit_time,reason,result_r,trade_id))

def update_open_trades(symbol,timeframe,candles):
    closed=[]
    with connect() as c: rows=c.execute("SELECT * FROM paper_trades WHERE status='OPEN' AND symbol=? AND timeframe=?",(symbol,timeframe)).fetchall()
    for trade in rows:
        for candle in candles:
            if candle.datetime <= trade['entry_candle_time']: continue
            stop_hit = candle.low <= trade['stop_loss'] if trade['direction']=='LONG' else candle.high >= trade['stop_loss']
            target_hit = candle.high >= trade['take_profit'] if trade['direction']=='LONG' else candle.low <= trade['take_profit']
            if not stop_hit and not target_hit: continue
            if stop_hit: price=trade['stop_loss']; reason='STOP_LOSS'; r=-1.0
            else: price=trade['take_profit']; reason='TAKE_PROFIT'; r=2.0
            update_trade(trade['id'],price,candle.datetime,reason,r); closed.append(trade['id']); break
    return closed

def performance():
    trades=list_trades('CLOSED',10000); rs=[float(t['result_r']) for t in trades if t['result_r'] is not None]
    wins=sum(1 for x in rs if x>0); losses=sum(1 for x in rs if x<0); gross_win=sum(x for x in rs if x>0); gross_loss=abs(sum(x for x in rs if x<0))
    equity=peak=0.0; max_dd=0.0
    for x in rs:
        equity+=x; peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
    return {'closed_trades':len(rs),'open_trades':len(list_trades('OPEN',10000)),'wins':wins,'losses':losses,'win_rate_pct':round(wins/len(rs)*100,2) if rs else None,'net_r':round(sum(rs),2),'expectancy_r':round(sum(rs)/len(rs),3) if rs else None,'profit_factor':round(gross_win/gross_loss,2) if gross_loss else (None if not gross_win else 'infinite'),'max_drawdown_r':round(max_dd,2),'note':'Paper simulation only. Intrabar order is unknown; stop is assumed first when stop and target are both touched.'}
