import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "twelvedata").strip().lower()
ENABLE_YAHOO_FALLBACK = os.getenv("ENABLE_YAHOO_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/trading_signals.db")
Path(DATABASE_PATH).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
APP_VERSION = "1.2.0"
STRATEGY_VERSION = "unanimous-direction-time-exit-1.2"
