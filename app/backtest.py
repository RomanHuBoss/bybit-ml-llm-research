from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd

from .config import settings
from .db import DatabaseConnectionError, execute, execute_many_values, execute_many_values_returning
from .features import load_market_frame
from .strategies import (
    StrategySignal,
    bollinger_rsi_reversion,
    donchian_breakout,
    ema_pullback,
    funding_contrarian,
    oi_confirmation,
    regime_adaptive_combo,
    sentiment_filter,
    trend_continuation_setup,
    validate_signal,
    volatility_squeeze,
)

StrategyFn = Callable[[pd.Series], StrategySignal | None]

STRATEGY_MAP: dict[str, StrategyFn] = {
    "donchian_atr_breakout": donchian_breakout,
    "ema_pullback_trend": ema_pullback,
    "bollinger_rsi_reversion": bollinger_rsi_reversion,
    "funding_extreme_contrarian": funding_contrarian,
    "oi_trend_confirmation": oi_confirmation,
    "sentiment_fear_reversal": sentiment_filter,
    "sentiment_greed_reversal": sentiment_filter,
    "trend_continuation_setup": trend_continuation_setup,
    # Исторически эти стратегии требуют history; _build_signal передает его явно.
    "volatility_squeeze_breakout": volatility_squeeze,  # type: ignore[dict-item]
    "regime_adaptive_combo": regime_adaptive_combo,  # type: ignore[dict-item]
}

SAME_BAR_STOP_FIRST_REASON = "stop_loss_same_bar_ambiguous"
INTRABAR_EXECUTION_MODEL = "conservative_ohlc_stop_loss_first"



def ensure_backtest_trades_storage() -> None:
    """Создает хранилище сделок бэктеста для старых БД без V20-миграции."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS backtest_trades (
            id BIGSERIAL PRIMARY KEY,
            run_id BIGINT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            strategy TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_time TIMESTAMPTZ NOT NULL,
            exit_time TIMESTAMPTZ NOT NULL,
            entry NUMERIC NOT NULL,
            exit NUMERIC NOT NULL,
            pnl NUMERIC NOT NULL,
            pnl_pct NUMERIC NOT NULL,
            reason TEXT
        )
        """
    )
    execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades(run_id)")
    execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_exit ON backtest_trades(run_id, exit_time)")
    execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_quality_lookup_v41 ON backtest_trades(symbol, strategy, direction, exit_time DESC)")
    execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_reason_v42 ON backtest_trades(run_id, reason)")
    execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_direction_v41') THEN
                ALTER TABLE backtest_trades
                ADD CONSTRAINT chk_backtest_trades_direction_v41
                CHECK (direction IN ('long','short')) NOT VALID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_prices_v41') THEN
                ALTER TABLE backtest_trades
                ADD CONSTRAINT chk_backtest_trades_prices_v41
                CHECK (entry > 0 AND exit > 0) NOT VALID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_time_order_v41') THEN
                ALTER TABLE backtest_trades
                ADD CONSTRAINT chk_backtest_trades_time_order_v41
                CHECK (exit_time >= entry_time) NOT VALID;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_backtest_trades_reason_v42') THEN
                ALTER TABLE backtest_trades
                ADD CONSTRAINT chk_backtest_trades_reason_v42
                CHECK (reason IS NULL OR btrim(reason) <> '') NOT VALID;
            END IF;
        END $$;
        """
    )


def _try_ensure_backtest_trades_storage() -> str | None:
    """Пытается выполнить idempotent-миграцию, не ломая уже рассчитанный backtest.

    В штатном production-запуске PostgreSQL и psycopg2 обязательны: если их нет,
    INSERT backtest_runs упадет раньше. Но в тестах и в аварийной maintenance-среде
    DB-writer может быть заменен стабом, а проверка структуры таблицы не должна
    превращаться в ложный отказ бэктеста. Поэтому ошибку миграции возвращаем как
    предупреждение, а запись самих сделок всё равно пытаемся выполнить далее.
    """
    try:
        ensure_backtest_trades_storage()
        return None
    except DatabaseConnectionError as exc:
        return f"backtest_trades_storage_unverified: {exc}"
    except Exception as exc:
        return f"backtest_trades_storage_unverified: {exc}"


def _interval_to_minutes(interval: str) -> int:
    if interval.isdigit():
        return int(interval)
    return {"D": 1440, "W": 10080, "M": 43200}.get(interval.upper(), 60)


def _safe_float(value, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    if not math.isfinite(out):
        return default
    return out


def _max_drawdown(equity_curve: list[dict]) -> float:
    peak = -math.inf
    max_dd = 0.0
    for point in equity_curve:
        equity = float(point["equity"])
        peak = max(peak, equity)
        if peak > 0:
            max_dd = min(max_dd, equity / peak - 1)
    return abs(max_dd)


def _sharpe(equity_curve: list[dict], interval: str) -> float | None:
    if len(equity_curve) < 5:
        return None
    eq = pd.Series([float(p["equity"]) for p in equity_curve])
    ret = eq.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    std = ret.std()
    if std == 0 or ret.empty or not math.isfinite(float(std)):
        return None
    bars_per_year = max(1.0, 365 * 24 * 60 / max(_interval_to_minutes(interval), 1))
    return float((ret.mean() / std) * np.sqrt(bars_per_year))


def _position_qty(equity: float, entry: float, stop: float) -> float:
    risk_budget = equity * settings.risk_per_trade
    per_unit_risk = abs(entry - stop)
    if per_unit_risk <= 0 or entry <= 0 or equity <= 0:
        return 0.0
    qty_by_risk = risk_budget / per_unit_risk
    max_notional = min(settings.max_position_notional_usdt, equity * settings.max_leverage)
    qty_by_notional = max_notional / entry if max_notional > 0 else 0.0
    return max(0.0, min(qty_by_risk, qty_by_notional))


def _adjust_levels_for_executable_entry(sig: StrategySignal, executable_entry: float) -> tuple[float, float]:
    stop_distance = abs(sig.entry - sig.stop_loss)
    take_distance = abs(sig.take_profit - sig.entry)
    if sig.direction == "long":
        return executable_entry - stop_distance, executable_entry + take_distance
    return executable_entry + stop_distance, executable_entry - take_distance


def _entry_drift_gate(sig: StrategySignal, executable_entry: float) -> tuple[bool, dict[str, float | str]]:
    """Не даёт бэктесту догонять цену, если следующий open ушёл от signal-entry.

    Live-контракт уже имеет price_actionability/entry_window. Бэктест должен
    моделировать ту же дисциплину исполнения: сигнал на закрытой свече может быть
    взят только рядом с рассчитанным entry, а не по любому следующему open.
    """
    signal_entry = _safe_float(sig.entry)
    atr = _safe_float(sig.atr)
    if signal_entry is None or signal_entry <= 0 or executable_entry <= 0:
        return False, {"reason": "invalid_entry_for_drift_gate"}
    zone_pct = 0.0025
    if atr is not None and atr > 0:
        zone_pct = max(0.0015, min(0.018, (atr / signal_entry) * 0.35))
    drift_pct = abs(executable_entry - signal_entry) / signal_entry
    if drift_pct > zone_pct:
        return False, {"reason": "entry_drift_exceeded", "price_drift_pct": drift_pct, "entry_zone_pct": zone_pct}
    return True, {"reason": "entry_drift_ok", "price_drift_pct": drift_pct, "entry_zone_pct": zone_pct}


def _build_signal(strategy: str, fn: StrategyFn, row: pd.Series, history: pd.DataFrame) -> StrategySignal | None:
    if strategy == "volatility_squeeze_breakout":
        return volatility_squeeze(row, history)
    if strategy == "regime_adaptive_combo":
        return regime_adaptive_combo(row, history)
    return fn(row)


def _intrabar_exit_reason(direction: str, high: float, low: float, stop: float, take: float) -> tuple[str | None, float | None]:
    """Возвращает консервативный исход свечи с явной маркировкой same-bar SL/TP.

    OHLC не содержит порядка событий внутри свечи. Если в одной свече задеты и
    stop-loss, и take-profit, бэктест обязан считать SL первым и пометить сделку
    как неоднозначную, чтобы quality/UI не воспринимали такой результат как
    обычный стоп без методологического риска.
    """
    if direction == "long":
        stop_hit = low <= stop
        take_hit = high >= take
        if stop_hit and take_hit:
            return SAME_BAR_STOP_FIRST_REASON, stop
        if stop_hit:
            return "stop_loss", stop
        if take_hit:
            return "take_profit", take
        return None, None

    stop_hit = high >= stop
    take_hit = low <= take
    if stop_hit and take_hit:
        return SAME_BAR_STOP_FIRST_REASON, stop
    if stop_hit:
        return "stop_loss", stop
    if take_hit:
        return "take_profit", take
    return None, None


def _exit_trade_if_needed(open_trade: dict, bar: pd.Series, bar_index: int, *, force_reason: str | None = None) -> tuple[dict | None, str | None, float | None]:
    direction = open_trade["direction"]
    stop = open_trade["stop_loss"]
    take = open_trade["take_profit"]
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    exit_price = None
    reason = None

    if force_reason:
        exit_price = close * (1 - settings.slippage_rate if direction == "long" else 1 + settings.slippage_rate)
        reason = force_reason
    else:
        reason, raw_exit_price = _intrabar_exit_reason(direction, high, low, stop, take)
        if raw_exit_price is not None and reason is not None:
            # Проскальзывание ухудшает исполнение в сторону позиции. Same-bar ambiguity
            # остается отдельной причиной, но цена исполнения такая же консервативная,
            # как у обычного stop-loss.
            exit_price = raw_exit_price * (1 - settings.slippage_rate if direction == "long" else 1 + settings.slippage_rate)

    max_hold = 48
    if exit_price is None and bar_index - open_trade["entry_idx"] >= max_hold:
        exit_price = close * (1 - settings.slippage_rate if direction == "long" else 1 + settings.slippage_rate)
        reason = "time_exit"
    return open_trade, reason, exit_price


def _unrealized_pnl(open_trade: dict | None, close: float) -> float:
    if not open_trade:
        return 0.0
    qty = open_trade["qty"]
    entry = open_trade["entry"]
    direction = open_trade["direction"]
    return (close - entry) * qty if direction == "long" else (entry - close) * qty


def _exit_reason_counts(trades: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in trades:
        reason = str(trade.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _ambiguous_exit_count(trades: list[dict]) -> int:
    return sum(1 for trade in trades if str(trade.get("reason") or "") == SAME_BAR_STOP_FIRST_REASON)


def run_backtest(category: str, symbol: str, interval: str, strategy: str, limit: int = 5000) -> dict:
    df = load_market_frame(category, symbol, interval, limit=limit)
    if df.empty or len(df) < 300:
        raise ValueError("Not enough candles/features. Run market sync first.")
    if strategy not in STRATEGY_MAP:
        raise ValueError(f"Unknown strategy: {strategy}")

    fn = STRATEGY_MAP[strategy]
    equity = float(settings.start_equity_usdt)
    start_equity = float(settings.start_equity_usdt)
    trades: list[dict] = []
    equity_curve: list[dict] = []
    open_trade: dict | None = None
    halted_by_risk = False
    skipped_signals: dict[str, int] = {}

    def skip_signal(reason: str) -> None:
        skipped_signals[reason] = skipped_signals.get(reason, 0) + 1

    def close_trade(bar: pd.Series, reason: str, exit_price: float) -> None:
        nonlocal equity, open_trade
        assert open_trade is not None
        qty = open_trade["qty"]
        entry = open_trade["entry"]
        direction = open_trade["direction"]
        gross = (exit_price - entry) * qty if direction == "long" else (entry - exit_price) * qty
        fees = (entry * qty + exit_price * qty) * settings.fee_rate
        pnl = gross - fees
        equity += pnl
        trades.append(
            {
                "symbol": symbol.upper(),
                "strategy": strategy,
                "direction": direction,
                "entry_time": open_trade["entry_time"],
                "exit_time": bar["start_time"],
                "entry": entry,
                "exit": exit_price,
                "pnl": pnl,
                "pnl_pct": pnl / max(equity - pnl, 1e-9),
                "reason": reason,
            }
        )
        open_trade = None

    for i in range(220, len(df) - 1):
        signal_bar = df.iloc[i]
        trade_bar = df.iloc[i + 1]
        ts = signal_bar["start_time"]

        if open_trade is not None:
            _, reason, exit_price = _exit_trade_if_needed(open_trade, trade_bar, i + 1)
            if exit_price is not None and reason is not None:
                close_trade(trade_bar, reason, exit_price)

        if equity <= start_equity * (1 - settings.max_daily_drawdown):
            halted_by_risk = True

        if open_trade is None and not halted_by_risk:
            sig = _build_signal(strategy, fn, signal_bar, df.iloc[:i])
            if sig and sig.strategy == strategy and sig.direction in {"long", "short"} and sig.confidence >= 0.54:
                valid_signal, invalid_reason = validate_signal(sig)
                if not valid_signal:
                    # Backtest не должен открывать сделку по сигналу, который live-контур
                    # отказался бы сохранять из-за перепутанных уровней или NaN-значений.
                    skip_signal(str(invalid_reason or "invalid_signal"))
                    equity_curve.append({"time": str(trade_bar["start_time"]), "equity": round(equity + _unrealized_pnl(open_trade, float(trade_bar["close"])), 6), "skipped_signal": invalid_reason})
                    continue
                raw_entry = _safe_float(trade_bar.get("open"))
                if raw_entry is not None and raw_entry > 0:
                    entry = raw_entry * (1 + settings.slippage_rate if sig.direction == "long" else 1 - settings.slippage_rate)
                    drift_ok, drift_meta = _entry_drift_gate(sig, entry)
                    if not drift_ok:
                        # Бэктест теперь не покупает/шортит рынок, который уже ушёл от
                        # расчетной зоны входа. Иначе quality может оценивать сделки,
                        # которые live-интерфейс честно заблокировал бы как missed_entry.
                        skip_signal(str(drift_meta.get("reason") or "entry_drift_blocked"))
                        equity_curve.append({"time": str(trade_bar["start_time"]), "equity": round(equity + _unrealized_pnl(open_trade, float(trade_bar["close"])), 6), "skipped_signal": drift_meta})
                        continue
                    stop_loss, take_profit = _adjust_levels_for_executable_entry(sig, entry)
                    qty = _position_qty(equity, entry, stop_loss)
                    if qty > 0:
                        open_trade = {
                            "entry_idx": i + 1,
                            "entry_time": trade_bar["start_time"],
                            "signal_time": ts,
                            "direction": sig.direction,
                            "entry": entry,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "qty": qty,
                        }
                        _, reason, exit_price = _exit_trade_if_needed(open_trade, trade_bar, i + 1)
                        if exit_price is not None and reason is not None:
                            close_trade(trade_bar, reason, exit_price)
                    else:
                        skip_signal("zero_position_size")
                else:
                    skip_signal("invalid_next_open")

        mtm_equity = equity + _unrealized_pnl(open_trade, float(trade_bar["close"]))
        equity_curve.append({"time": str(trade_bar["start_time"]), "equity": round(mtm_equity, 6)})

    if open_trade is not None:
        final_bar = df.iloc[-1]
        _, reason, exit_price = _exit_trade_if_needed(open_trade, final_bar, len(df) - 1, force_reason="end_of_data")
        if exit_price is not None and reason is not None:
            close_trade(final_bar, reason, exit_price)
            equity_curve.append({"time": str(final_bar["start_time"]), "equity": round(equity, 6)})

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    win_rate = len(wins) / len(trades) if trades else None
    total_return = equity / start_equity - 1

    start_time = df.iloc[220]["start_time"]
    end_time = df.iloc[-1]["start_time"]
    max_drawdown = _max_drawdown(equity_curve)
    sharpe = _sharpe(equity_curve, interval)
    exit_reason_counts = _exit_reason_counts(trades)
    ambiguous_exit_count = _ambiguous_exit_count(trades)
    ambiguous_exit_rate = ambiguous_exit_count / len(trades) if trades else 0.0
    run_rows = [
        (
            category,
            symbol.upper(),
            interval,
            strategy,
            start_time,
            end_time,
            settings.start_equity_usdt,
            equity,
            total_return,
            max_drawdown,
            sharpe,
            win_rate,
            profit_factor,
            len(trades),
            {
                "fee_rate": settings.fee_rate,
                "slippage_rate": settings.slippage_rate,
                "risk_per_trade": settings.risk_per_trade,
                "max_position_notional_usdt": settings.max_position_notional_usdt,
                "max_leverage": settings.max_leverage,
                "entry_model": "signal_on_closed_bar_execution_on_next_bar_open",
                "intrabar_execution_model": INTRABAR_EXECUTION_MODEL,
                "same_bar_ambiguity": "explicit_stop_loss_first",
                "same_bar_stop_first_reason": SAME_BAR_STOP_FIRST_REASON,
                "ambiguous_exit_count": ambiguous_exit_count,
                "ambiguous_exit_rate": ambiguous_exit_rate,
                "exit_reason_counts": exit_reason_counts,
                "halted_by_risk": halted_by_risk,
                "skipped_signals": skipped_signals,
                "entry_drift_gate": "next_open_must_remain_inside_server_equivalent_entry_zone",
            },
            equity_curve[-500:],
        )
    ]
    returned = execute_many_values_returning(
        """
        INSERT INTO backtest_runs(category, symbol, interval, strategy, start_time, end_time, initial_equity, final_equity,
                                  total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, params, equity_curve)
        VALUES %s
        RETURNING id
        """,
        run_rows,
    )
    # Не используем SELECT ORDER BY id DESC: при параллельных запусках backtest это
    # создает race condition и может привязать сделки к чужому run_id.
    run_id = int(returned[0]["id"]) if returned else None
    quality = None
    persistence_warnings: list[str] = []
    if run_id and trades:
        storage_warning = _try_ensure_backtest_trades_storage()
        if storage_warning:
            persistence_warnings.append(storage_warning)
        execute_many_values(
            """
            INSERT INTO backtest_trades(run_id, symbol, strategy, direction, entry_time, exit_time, entry, exit, pnl, pnl_pct, reason)
            VALUES %s
            """,
            [
                (
                    run_id,
                    t["symbol"],
                    t["strategy"],
                    t["direction"],
                    t["entry_time"],
                    t["exit_time"],
                    t["entry"],
                    t["exit"],
                    t["pnl"],
                    t["pnl_pct"],
                    t["reason"],
                )
                for t in trades
            ],
        )
    if run_id:
        try:
            from .strategy_quality import upsert_strategy_quality_from_run_id

            quality = upsert_strategy_quality_from_run_id(run_id)
        except Exception:
            # Бэктест должен сохранить результат даже если quality-слой еще не мигрирован
            # или временно недоступен. Следующий фоновый цикл сможет пересчитать quality.
            quality = None
    return {
        "run_id": run_id,
        "symbol": symbol.upper(),
        "strategy": strategy,
        "initial_equity": settings.start_equity_usdt,
        "final_equity": round(equity, 4),
        "total_return": round(total_return, 6),
        "max_drawdown": round(max_drawdown, 6),
        "sharpe": sharpe,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trades_count": len(trades),
        "skipped_signals": skipped_signals,
        "exit_reason_counts": exit_reason_counts,
        "ambiguous_exit_count": ambiguous_exit_count,
        "ambiguous_exit_rate": round(ambiguous_exit_rate, 6),
        "intrabar_execution_model": INTRABAR_EXECUTION_MODEL,
        "halted_by_risk": halted_by_risk,
        "quality": quality,
        "persistence_warnings": persistence_warnings,
        "equity_curve": equity_curve[-300:],
    }
