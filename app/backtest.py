from __future__ import annotations

import math
from dataclasses import asdict
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


def _max_drawdown(equity_curve: list[dict]) -> float:
    peak = -math.inf
    max_dd = 0.0
    for point in equity_curve:
        equity = float(point["equity"])
        peak = max(peak, equity)
        if peak > 0:
            max_dd = min(max_dd, equity / peak - 1)
    return abs(max_dd)


def _sharpe(equity_curve: list[dict]) -> float | None:
    if len(equity_curve) < 5:
        return None
    eq = pd.Series([float(p["equity"]) for p in equity_curve])
    ret = eq.pct_change().dropna()
    if ret.std() == 0 or ret.empty:
        return None
    return float((ret.mean() / ret.std()) * np.sqrt(252))


def _position_qty(equity: float, entry: float, stop: float) -> float:
    risk_budget = equity * settings.risk_per_trade
    per_unit_risk = abs(entry - stop)
    if per_unit_risk <= 0:
        return 0.0
    return risk_budget / per_unit_risk


def run_backtest(category: str, symbol: str, interval: str, strategy: str, limit: int = 5000) -> dict:
    df = load_market_frame(category, symbol, interval, limit=limit)
    if df.empty or len(df) < 300:
        raise ValueError("Not enough candles/features. Run market sync first.")
    if strategy not in STRATEGY_MAP:
        raise ValueError(f"Unknown strategy: {strategy}")

    fn = STRATEGY_MAP[strategy]
    equity = float(settings.start_equity_usdt)
    trades: list[dict] = []
    equity_curve: list[dict] = []
    open_trade: dict | None = None

    for i in range(220, len(df) - 1):
        row = df.iloc[i]
        next_row = df.iloc[i + 1]
        ts = row["start_time"]

        if open_trade:
            direction = open_trade["direction"]
            stop = open_trade["stop_loss"]
            take = open_trade["take_profit"]
            exit_price = None
            reason = None
            high = float(next_row["high"])
            low = float(next_row["low"])
            close = float(next_row["close"])
            if direction == "long":
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
            if exit_price is None and i - open_trade["entry_idx"] >= max_hold:
                exit_price = close
                reason = "time_exit"
            if exit_price is not None:
                qty = open_trade["qty"]
                entry = open_trade["entry"]
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
                        "exit_time": next_row["start_time"],
                        "entry": entry,
                        "exit": exit_price,
                        "pnl": pnl,
                        "pnl_pct": pnl / max(equity - pnl, 1e-9),
                        "reason": reason,
                    }
                )
                open_trade = None

        if open_trade is None:
            if strategy == "volatility_squeeze_breakout":
                sig = volatility_squeeze(row, df.iloc[:i])
            elif strategy == "regime_adaptive_combo":
                sig = regime_adaptive_combo(row, df.iloc[:i])
            else:
                sig = fn(row)
            if sig and sig.strategy == strategy and sig.direction in {"long", "short"} and sig.confidence >= 0.54:
                entry = sig.entry * (1 + settings.slippage_rate if sig.direction == "long" else 1 - settings.slippage_rate)
                qty = _position_qty(equity, entry, sig.stop_loss)
                if qty > 0:
                    open_trade = {
                        "entry_idx": i,
                        "entry_time": ts,
                        "direction": sig.direction,
                        "entry": entry,
                        "stop_loss": sig.stop_loss,
                        "take_profit": sig.take_profit,
                        "qty": qty,
                    }

        equity_curve.append({"time": str(ts), "equity": round(equity, 6)})

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    win_rate = len(wins) / len(trades) if trades else None
    total_return = equity / float(settings.start_equity_usdt) - 1

    start_time = df.iloc[220]["start_time"]
    end_time = df.iloc[-1]["start_time"]
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
            _max_drawdown(equity_curve),
            _sharpe(equity_curve),
            win_rate,
            profit_factor,
            len(trades),
            {"fee_rate": settings.fee_rate, "slippage_rate": settings.slippage_rate, "risk_per_trade": settings.risk_per_trade},
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
        "max_drawdown": round(_max_drawdown(equity_curve), 6),
        "sharpe": _sharpe(equity_curve),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trades_count": len(trades),
        "equity_curve": equity_curve[-300:],
    }
