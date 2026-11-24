from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .config import TWELVE_DATA_API_KEY, MARKET_DATA_PROVIDER, ENABLE_YAHOO_FALLBACK, APP_VERSION, STRATEGY_VERSION
from .market_data import MarketDataRouter
from .analysis import analyse, apply_volatility_gate, apply_candle_gate
from .backtest import run_backtest
from .db import init_db, save_signal, list_signals, list_trades, update_open_trades, performance

app=FastAPI(title="Trading Signal Lab",version=APP_VERSION,description="Local-first market analysis and paper-trading journal. No live order execution.")
BASE=Path(__file__).resolve().parent
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')
router=MarketDataRouter(MARKET_DATA_PROVIDER,TWELVE_DATA_API_KEY,ENABLE_YAHOO_FALLBACK)
INTERVALS={'5min','15min','1h','4h','1day'}
WATCHLIST=['NVDA','MU','AMD','INTC','MSFT','AAPL','AMZN','TSLA','IREN','CRWV','APLD','WDC','STX','TERA','RIOT','QBTS','RKLB','QQQ','SPY','DIA','IWM']

@app.on_event('startup')
def startup(): init_db()

@app.get('/',response_class=HTMLResponse)
def home(): return (BASE/'static'/'index.html').read_text(encoding='utf-8')

@app.get('/api/health')
def health(): return {'status':'ok','version':APP_VERSION,'strategy_version':STRATEGY_VERSION,'primary_provider':MARKET_DATA_PROVIDER,'yahoo_fallback_enabled':ENABLE_YAHOO_FALLBACK,'twelve_data_key_configured':bool(TWELVE_DATA_API_KEY),'live_trading_enabled':False}

@app.get('/api/watchlist')
def watchlist(): return WATCHLIST

@app.get('/api/candles/{symbol}')
async def candles(symbol:str,interval:str=Query('15min'),outputsize:int=Query(300,ge=60,le=5000)):
    if interval not in INTERVALS: raise HTTPException(400,'Unsupported interval')
    try:
        data,provider,errors=await router.candles(symbol.upper(),interval,outputsize)
        return {'symbol':symbol.upper(),'interval':interval,'provider':provider,'provider_fallbacks':errors,'candles':[c.to_dict() for c in data]}
    except Exception as e: raise HTTPException(502,str(e)) from e

@app.get('/api/analyse/{symbol}')
async def analyse_symbol(symbol:str,interval:str=Query('15min')):
    if interval not in INTERVALS: raise HTTPException(400,'Unsupported interval')
    symbol=symbol.upper().strip()
    if not symbol or len(symbol)>30: raise HTTPException(400,'Invalid symbol')
    try:
        data,provider,errors=await router.candles(symbol,interval,300)
        # Providers do not expose a shared closed flag. Conservatively omit the newest bar.
        signal_candles=data[:-1]
        result=analyse(signal_candles)
        result['base_direction']=result['direction']
        apply_volatility_gate(result, signal_candles)
        confirmation_interval={'5min':'1h','15min':'4h','1h':'4h','4h':'1day'}.get(interval)
        if confirmation_interval and result['direction'] in ('LONG','SHORT'):
            try:
                higher_data,higher_provider,higher_errors=await router.candles(symbol,confirmation_interval,200)
                higher=analyse(higher_data[:-1])
                result['base_direction']=result['direction']
                result['higher_timeframe']=confirmation_interval
                result['higher_timeframe_direction']=higher['direction']
                result['higher_timeframe_provider']=higher_provider
                errors.extend(higher_errors)
                if higher['direction'] != result['direction']:
                    result['direction']='WAIT'
                    result['entry_reference']=None; result['stop_loss']=None; result['take_profit']=None; result['risk_reward']=None
                    result['rationale'] += f"; higher timeframe ({confirmation_interval}) is {higher['direction']}, so the signal is downgraded to WAIT"
                    result['mtf_status']='Not confirmed; conflicting or neutral higher-timeframe signal'
                else:
                    result['mtf_status']='Confirmed by higher timeframe'
            except Exception as confirm_error:
                result['base_direction']=result['direction']
                result['higher_timeframe']=confirmation_interval
                result['higher_timeframe_direction']='UNAVAILABLE'
                result['direction']='WAIT'
                result['entry_reference']=None; result['stop_loss']=None; result['take_profit']=None; result['risk_reward']=None
                result['mtf_status']='Confirmation data unavailable; fail-safe WAIT'
                result['rationale'] += f"; higher-timeframe confirmation unavailable ({str(confirm_error)[:120]}), so no trade is opened"
        else:
            result['mtf_status']='Not applied to daily timeframe' if interval=='1day' else 'No directional signal to confirm'
        apply_candle_gate(result)
        closed_ids=update_open_trades(symbol,interval,data)
        signal_id,trade_opened=save_signal(symbol,interval,result,provider)
        return {'signal_id':signal_id,'symbol':symbol,'timeframe':interval,'provider':provider,'provider_fallbacks':errors,**result,'paper_trade_opened':trade_opened,'closed_paper_trade_ids':closed_ids,'tradingview_url':f'https://www.tradingview.com/chart/?symbol={symbol}'}
    except ValueError as e: raise HTTPException(422,str(e)) from e
    except Exception as e: raise HTTPException(502,str(e)) from e

@app.get('/api/signals')
def signals(limit:int=Query(100,ge=1,le=500)): return list_signals(limit)

@app.get('/api/paper-trades')
def paper_trades(status:str|None=None,limit:int=Query(200,ge=1,le=1000)):
    if status not in (None,'OPEN','CLOSED'): raise HTTPException(400,'status must be OPEN or CLOSED')
    return list_trades(status,limit)

@app.get('/api/performance')
def stats(): return performance()

@app.get('/api/backtest/{symbol}')
async def backtest_symbol(symbol:str,interval:str=Query('1day'),outputsize:int=Query(500,ge=100,le=2000),max_holding:int=Query(20,ge=1,le=100)):
    if interval not in INTERVALS: raise HTTPException(400,'Unsupported interval')
    try:
        data,provider,errors=await router.candles(symbol.upper(),interval,outputsize+1)
        result=run_backtest(data[:-1],max_holding)
        return {'symbol':symbol.upper(),'interval':interval,'provider':provider,'provider_fallbacks':errors,**result}
    except ValueError as e: raise HTTPException(422,str(e)) from e
    except Exception as e: raise HTTPException(502,str(e)) from e
