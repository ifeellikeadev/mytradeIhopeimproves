from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from .stock_search import find_stocks
from .config import TWELVE_DATA_API_KEY, MARKET_DATA_PROVIDER, ENABLE_YAHOO_FALLBACK, APP_VERSION, STRATEGY_VERSION
from .market_data import MarketDataRouter
from .analysis import analyse
from .strategy import CONFIRMATION, DEFAULT_HOLD, prepare, finish, historical_confirmation
from .timed_exits import update_paper_trades
from .backtest import run_backtest
from .db import init_db, save_signal, list_signals, list_trades, performance

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

@app.get('/api/stock-search')
async def stock_search(q: str = Query(..., min_length=1, max_length=60)):
    query = ' '.join(q.split())
    if not query:
        raise HTTPException(400, 'Enter a company name or ticker.')
    return await find_stocks(query, TWELVE_DATA_API_KEY, WATCHLIST)


@app.get('/api/candles/{symbol}')
async def candles(symbol:str,interval:str=Query('15min'),outputsize:int=Query(300,ge=60,le=5000)):
    if interval not in INTERVALS: raise HTTPException(400,'Unsupported interval')
    try:
        data,provider,errors=await router.candles(symbol.upper(),interval,outputsize)
        return {'symbol':symbol.upper(),'interval':interval,'provider':provider,'provider_fallbacks':errors,'candles':[c.to_dict() for c in data]}
    except Exception as e: raise HTTPException(502,str(e)) from e

@app.get('/api/analyse/{symbol}')
async def analyse_symbol(symbol:str,interval:str=Query('15min'),max_holding:int=DEFAULT_HOLD):
    if interval not in INTERVALS: raise HTTPException(400,'Unsupported interval')
    if not 1 <= max_holding <= 100: raise HTTPException(422,'Maximum hold must be 1 to 100 candles')
    symbol=symbol.upper().strip()
    if not symbol or len(symbol)>30: raise HTTPException(400,'Invalid symbol')
    try:
        data,provider,errors=await router.candles(symbol,interval,300)
        # Providers do not expose a shared closed flag. Conservatively omit the newest bar.
        signal_candles=data[:-1]
        result=analyse(signal_candles)
        prepare(result, signal_candles)
        confirmation_interval=CONFIRMATION.get(interval)
        higher=None
        if confirmation_interval:
            try:
                higher_data,higher_provider,higher_errors=await router.candles(symbol,confirmation_interval,200)
                higher=analyse(higher_data[:-1])
                result['higher_timeframe_provider']=higher_provider
                errors.extend(higher_errors)
            except Exception:
                pass  # A provider failure must never allow an unconfirmed entry.
        finish(result, confirmation_interval, higher)
        result['max_holding_candles']=max_holding if result['direction'] != 'WAIT' else None
        closed_ids=update_paper_trades(symbol,interval,signal_candles)
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
async def backtest_symbol(symbol:str,interval:str=Query('1day'),outputsize:int=Query(500,ge=100,le=2000),max_holding:int=Query(DEFAULT_HOLD,ge=1,le=100)):
    if interval not in INTERVALS: raise HTTPException(400,'Unsupported interval')
    try:
        data,provider,errors=await router.candles(symbol.upper(),interval,outputsize+1)
        higher_interval=CONFIRMATION.get(interval)
        at=None
        if higher_interval:
            higher,higher_provider,_=await router.candles(symbol.upper(),higher_interval,outputsize+201)
            if provider != higher_provider:
                raise ValueError('Backtest needs the same data provider for both timeframes')
            at=historical_confirmation(higher)
        result=run_backtest(data[:-1],max_holding,higher_interval,at)
        return {'symbol':symbol.upper(),'interval':interval,'provider':provider,'provider_fallbacks':errors,**result}
    except ValueError as e: raise HTTPException(422,str(e)) from e
    except Exception as e: raise HTTPException(502,str(e)) from e
