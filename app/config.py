from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw in (None, "") else int(raw)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(s.strip() for s in raw.split(",") if s.strip())


CORE_SYMBOLS_DEFAULT = (
    "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT,ADAUSDT,SUIUSDT,"
    "AAVEUSDT,LINKUSDT,AVAXUSDT,LTCUSDT,NEARUSDT,1000PEPEUSDT,HYPEUSDT"
)

RSS_URLS_DEFAULT = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/|CoinDesk,"
    "https://cointelegraph.com/rss|Cointelegraph"
)


@dataclass(frozen=True)
class Settings:
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = _int("POSTGRES_PORT", 5432)
    postgres_db: str = os.getenv("POSTGRES_DB", "bybit_lab")
    postgres_user: str = os.getenv("POSTGRES_USER", "bybit_lab_user")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "change_me")
    postgres_connect_timeout_sec: int = _int("POSTGRES_CONNECT_TIMEOUT_SEC", 5)

    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = _int("APP_PORT", 8000)

    bybit_base_url: str = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com").rstrip("/")
    bybit_request_sleep_sec: float = _float("BYBIT_REQUEST_SLEEP_SEC", 0.12)
    bybit_timeout_sec: float = _float("BYBIT_TIMEOUT_SEC", 30.0)
    bybit_max_retries: int = _int("BYBIT_MAX_RETRIES", 4)
    bybit_retry_backoff_sec: float = _float("BYBIT_RETRY_BACKOFF_SEC", 0.75)

    default_category: str = os.getenv("DEFAULT_CATEGORY", "linear")
    default_symbols: tuple[str, ...] = tuple(s.upper() for s in _csv("DEFAULT_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"))
    default_interval: str = os.getenv("DEFAULT_INTERVAL", "60")

    symbol_mode: str = os.getenv("SYMBOL_MODE", "hybrid").lower()  # core | dynamic | hybrid
    core_symbols: tuple[str, ...] = tuple(s.upper() for s in _csv("CORE_SYMBOLS", CORE_SYMBOLS_DEFAULT))
    exclude_symbols: tuple[str, ...] = tuple(s.upper() for s in _csv("EXCLUDE_SYMBOLS", "USDCUSDT,USDEUSDT,FDUSDUSDT"))
    dynamic_symbol_limit: int = _int("DYNAMIC_SYMBOL_LIMIT", 25)
    universe_limit: int = _int("UNIVERSE_LIMIT", 25)
    min_turnover_24h: float = _float("MIN_TURNOVER_24H", 20_000_000.0)
    min_open_interest_value: float = _float("MIN_OPEN_INTEREST_VALUE", 15_000_000.0)
    max_spread_pct: float = _float("MAX_SPREAD_PCT", 0.05)
    min_listing_age_days: int = _int("MIN_LISTING_AGE_DAYS", 45)
    allow_unverified_core_symbols: bool = _bool("ALLOW_UNVERIFIED_CORE_SYMBOLS", False)

    use_fear_greed: bool = _bool("USE_FEAR_GREED", True)
    use_gdelt: bool = _bool("USE_GDELT", True)
    use_rss: bool = _bool("USE_RSS", True)
    use_market_sentiment: bool = _bool("USE_MARKET_SENTIMENT", True)
    use_cryptopanic: bool = _bool("USE_CRYPTOPANIC", False)
    cryptopanic_token: str = os.getenv("CRYPTOPANIC_TOKEN", os.getenv("CRYPTOPANIC_API_KEY", ""))
    sentiment_lookback_days: int = _int("SENTIMENT_LOOKBACK_DAYS", 7)
    rss_urls: tuple[str, ...] = _csv("RSS_URLS", RSS_URLS_DEFAULT)

    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    ollama_timeout_sec: int = _int("OLLAMA_TIMEOUT_SEC", 60)

    llm_auto_eval_enabled: bool = _bool("LLM_AUTO_EVAL_ENABLED", True)
    llm_auto_eval_interval_sec: int = _int("LLM_AUTO_EVAL_INTERVAL_SEC", 300)
    llm_auto_eval_startup_delay_sec: int = _int("LLM_AUTO_EVAL_STARTUP_DELAY_SEC", 15)
    llm_auto_eval_max_candidates: int = _int("LLM_AUTO_EVAL_MAX_CANDIDATES", 8)
    llm_auto_eval_workers: int = _int("LLM_AUTO_EVAL_WORKERS", 2)
    llm_auto_eval_ttl_minutes: int = _int("LLM_AUTO_EVAL_TTL_MINUTES", 60)

    start_equity_usdt: float = _float("START_EQUITY_USDT", 500.0)
    risk_per_trade: float = _float("RISK_PER_TRADE", 0.005)
    max_daily_drawdown: float = _float("MAX_DAILY_DRAWDOWN", 0.03)
    fee_rate: float = _float("FEE_RATE", 0.00055)
    slippage_rate: float = _float("SLIPPAGE_RATE", 0.00020)
    max_position_notional_usdt: float = _float("MAX_POSITION_NOTIONAL_USDT", 1_000.0)
    max_leverage: float = _float("MAX_LEVERAGE", 2.0)
    require_liquidity_for_signals: bool = _bool("REQUIRE_LIQUIDITY_FOR_SIGNALS", True)
    max_signal_age_hours: int = _int("MAX_SIGNAL_AGE_HOURS", 48)
    max_symbols_per_request: int = _int("MAX_SYMBOLS_PER_REQUEST", 50)
    max_sync_days: int = _int("MAX_SYNC_DAYS", 730)

    @property
    def dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
            f"user={self.postgres_user} password={self.postgres_password} "
            f"connect_timeout={self.postgres_connect_timeout_sec}"
        )


def _validate_settings(s: Settings) -> None:
    problems: list[str] = []
    if s.default_category not in {"linear", "inverse", "spot"}:
        problems.append("DEFAULT_CATEGORY должен быть linear, inverse или spot")
    if s.symbol_mode not in {"core", "dynamic", "hybrid"}:
        problems.append("SYMBOL_MODE должен быть core, dynamic или hybrid")
    if not (0 < s.risk_per_trade <= 0.05):
        problems.append("RISK_PER_TRADE должен быть в диапазоне (0; 0.05]")
    if not (0 <= s.max_daily_drawdown <= 0.5):
        problems.append("MAX_DAILY_DRAWDOWN должен быть в диапазоне [0; 0.5]")
    if not (0 <= s.fee_rate <= 0.01):
        problems.append("FEE_RATE должен быть в диапазоне [0; 0.01]")
    if not (0 <= s.slippage_rate <= 0.02):
        problems.append("SLIPPAGE_RATE должен быть в диапазоне [0; 0.02]")
    if s.max_leverage <= 0:
        problems.append("MAX_LEVERAGE должен быть > 0")
    if s.max_position_notional_usdt <= 0:
        problems.append("MAX_POSITION_NOTIONAL_USDT должен быть > 0")
    if s.llm_auto_eval_interval_sec < 30:
        problems.append("LLM_AUTO_EVAL_INTERVAL_SEC должен быть >= 30")
    if s.llm_auto_eval_startup_delay_sec < 0:
        problems.append("LLM_AUTO_EVAL_STARTUP_DELAY_SEC не может быть отрицательным")
    if not (1 <= s.llm_auto_eval_max_candidates <= 50):
        problems.append("LLM_AUTO_EVAL_MAX_CANDIDATES должен быть в диапазоне [1; 50]")
    if not (1 <= s.llm_auto_eval_workers <= 4):
        problems.append("LLM_AUTO_EVAL_WORKERS должен быть в диапазоне [1; 4]")
    if s.llm_auto_eval_ttl_minutes < 1:
        problems.append("LLM_AUTO_EVAL_TTL_MINUTES должен быть >= 1")
    if s.universe_limit <= 0 or s.dynamic_symbol_limit <= 0:
        problems.append("UNIVERSE_LIMIT и DYNAMIC_SYMBOL_LIMIT должны быть > 0")
    if s.bybit_max_retries < 0:
        problems.append("BYBIT_MAX_RETRIES не может быть отрицательным")
    if problems:
        raise ValueError("Некорректная конфигурация: " + "; ".join(problems))


settings = Settings()
_validate_settings(settings)
