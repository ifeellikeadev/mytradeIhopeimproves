from app.analysis import analyse
from app.market_data import Candle

def test_analysis_returns_no_fake_probability():
    candles=[]
    price=100.0
    for i in range(100):
        op=price; price*=1.002 if i%7 else 0.999
        cl=price
        candles.append(Candle(f"2026-01-{(i%28)+1:02d}T00:00:00+00:00",op,max(op,cl)*1.002,min(op,cl)*.998,cl,1000+i))
    result=analyse(candles)
    assert result['direction'] in {'LONG','SHORT','WAIT'}
    assert result['probability'] is None
    assert result['stop_loss'] is None or result['take_profit'] is not None

def test_backtest_returns_metrics_and_trade_log():
    from app.backtest import run_backtest
    candles=[]
    price=100.0
    for i in range(260):
        op=price
        price *= 1.003
        cl=price
        candles.append(Candle(f"2026-02-{(i%28)+1:02d}T{i:04d}:00+00:00",op,max(op,cl)*1.001,min(op,cl)*.999,cl,2000))
    result=run_backtest(candles, max_holding=10)
    assert result['candles_tested']==260
    assert 'win_rate_pct' in result
    assert isinstance(result['trade_log'],list)
    assert 'warning' in result

def test_signal_is_not_opened_twice_for_same_candle(monkeypatch, tmp_path):
    import app.db as db
    monkeypatch.setattr(db, 'DATABASE_PATH', str(tmp_path / 'test.db'))
    db.init_db()
    analysis = {'direction':'LONG','entry_reference':100.0,'stop_loss':98.0,'take_profit':104.0,'last_candle_time':'2026-11-22T10:00:00+00:00'}
    first_id, first_opened = db.save_signal('NVDA','15min',analysis,'test-provider')
    second_id, second_opened = db.save_signal('NVDA','15min',analysis,'test-provider')
    assert first_id != second_id
    assert first_opened is True
    assert second_opened is False
    assert len(db.list_trades('OPEN')) == 1
