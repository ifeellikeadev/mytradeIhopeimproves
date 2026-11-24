from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Protocol
import asyncio
import httpx
import pandas as pd
import math

@dataclass
class Candle:
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    def to_dict(self): return asdict(self)

class MarketDataProvider(Protocol):
    name: str
    async def candles(self, symbol: str, interval: str, outputsize: int = 300) -> list[Candle]: ...

class TwelveDataProvider:
    name = "Twelve Data"
    BASE_URL = "https://api.twelvedata.com/time_series"
    def __init__(self, api_key: str): self.api_key = api_key
    async def candles(self, symbol: str, interval: str, outputsize: int = 300) -> list[Candle]:
        if not self.api_key: raise RuntimeError("Twelve Data API key is not configured")
        params = {"symbol": symbol, "interval": interval, "outputsize": outputsize, "apikey": self.api_key, "format": "JSON", "order": "ASC"}
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status(); payload = response.json()
        if "values" not in payload:
            raise RuntimeError(payload.get("message", payload.get("code", "Twelve Data returned no candle values")))
        rows=[]
        for item in payload["values"]:
            rows.append(Candle(str(item["datetime"]), float(item["open"]), float(item["high"]), float(item["low"]), float(item["close"]), float(item.get("volume") or 0)))
        return _clean(rows)[-outputsize:]

class YahooFinanceProvider:
    name = "Yahoo Finance (yfinance; unofficial)"
    async def candles(self, symbol: str, interval: str, outputsize: int = 300) -> list[Candle]:
        return await asyncio.to_thread(self._download, symbol, interval, outputsize)
    def _download(self, symbol: str, interval: str, outputsize: int) -> list[Candle]:
        import yfinance as yf
        yf_interval = {"5min":"5m", "15min":"15m", "1h":"60m", "4h":"60m", "1day":"1d"}[interval]
        period = "60d" if interval in {"5min", "15min", "1h", "4h"} else "2y"
        frame = yf.download(symbol, period=period, interval=yf_interval, auto_adjust=False, progress=False, threads=False)
        if frame is None or frame.empty: raise RuntimeError("Yahoo Finance returned no data for this symbol/interval")
        if isinstance(frame.columns, pd.MultiIndex): frame.columns = frame.columns.get_level_values(0)
        frame.columns = [str(c).lower() for c in frame.columns]
        if interval == "4h":
            frame.index = pd.to_datetime(frame.index, utc=True)
            frame = frame.resample("4h", label="left", closed="left").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna(subset=["open","high","low","close"])
        rows=[]
        for idx, row in frame.tail(outputsize).iterrows():
            stamp = pd.Timestamp(idx)
            if stamp.tzinfo is None: stamp = stamp.tz_localize("UTC")
            else: stamp = stamp.tz_convert("UTC")
            rows.append(Candle(stamp.isoformat(), float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row.get("volume",0) or 0)))
        return _clean(rows)

def _clean(rows: list[Candle]) -> list[Candle]:
    by_time={}
    for c in rows:
        if c.high < max(c.open,c.close,c.low) or c.low > min(c.open,c.close,c.high): continue
        if not all(math.isfinite(x) for x in (c.open,c.high,c.low,c.close,c.volume)): continue
        if min(c.open,c.high,c.low,c.close) <= 0: continue
        by_time[c.datetime]=c
    return [by_time[k] for k in sorted(by_time)]

class MarketDataRouter:
    def __init__(self, primary: str, api_key: str, yahoo_fallback: bool = True):
        self.primary_name=primary; self.api_key=api_key; self.yahoo_fallback=yahoo_fallback
    async def candles(self, symbol: str, interval: str, outputsize: int=300):
        errors=[]
        providers=[]
        if self.primary_name == "yahoo": providers.append(YahooFinanceProvider())
        else: providers.append(TwelveDataProvider(self.api_key))
        if self.yahoo_fallback and self.primary_name != "yahoo": providers.append(YahooFinanceProvider())
        for provider in providers:
            try:
                rows=await provider.candles(symbol,interval,outputsize)
                if len(rows) < 30: raise RuntimeError(f"Only {len(rows)} candles returned; at least 30 are required")
                return rows, provider.name, errors
            except Exception as exc:
                errors.append(f"{provider.name}: {str(exc)[:240]}")
        raise RuntimeError("All market-data providers failed. " + " | ".join(errors))
