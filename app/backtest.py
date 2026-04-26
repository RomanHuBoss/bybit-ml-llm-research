from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd

from .config import settings
from .db import execute_many_values, fetch_one
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
    "volatility_squeeze_breakout": lambda row: None,
    "regime_adaptive_combo": lambda row: None,
}


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


def _build_signal(strategy: str, fn: StrategyFn, row: pd.Series, history: pd.DataFrame) -> StrategySignal | None:
    if strategy == "volatility_squeeze_breakout":
        return volatility_squeeze(row, history)
    if strategy == "regime_adaptive_combo":
        return regime_adaptive_combo(row, history)
    return fn(row)


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
    elif direction == "long":
        # Если в одной свече достигнуты SL и TP, выбираем SL как более консервативный и проверяемый вариант.
        if low <= stop:
            exit_price = stop * (1 - settings.slippage_rate)
            reason = "stop_loss"
        elif high >= take:
            exit_price = take * (1 - settings.slippage_rate)
            reason = "take_profit"
    else:
        if high >= stop:
            exit_price = stop * (1 + settings.slippage_rate)
            reason = "stop_loss"
        elif low <= take:
            exit_price = take * (1 + settings.slippage_rate)
            reason = "take_profit"

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
                raw_entry = _safe_float(trade_bar.get("open"))
                if raw_entry is not None and raw_entry > 0:
                    entry = raw_entry * (1 + settings.slippage_rate if sig.direction == "long" else 1 - settings.slippage_rate)
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
                "same_bar_ambiguity": "stop_loss_first",
                "halted_by_risk": halted_by_risk,
            },
            equity_curve[-500:],
        )
    ]
    execute_many_values(
        """
        INSERT INTO backtest_runs(category, symbol, interval, strategy, start_time, end_time, initial_equity, final_equity,
                                  total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, params, equity_curve)
        VALUES %s
        """,
        run_rows,
    )
    run = fetch_one("SELECT id FROM backtest_runs ORDER BY id DESC LIMIT 1")
    run_id = int(run["id"]) if run else None
    if run_id and trades:
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
        "halted_by_risk": halted_by_risk,
        "equity_curve": equity_curve[-300:],
    }
