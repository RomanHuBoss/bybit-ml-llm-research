from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MTFIntervals:
    entry: str = "15"
    bias: str = "60"
    regime: str = "240"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in {float("inf"), float("-inf")}:
        return default
    return out


def _norm_interval(value: Any) -> str:
    return str(value or "").strip().upper()


def _empty_tf(interval: str) -> dict[str, Any]:
    return {
        "interval": interval,
        "direction": "neutral",
        "long_strength": 0.0,
        "short_strength": 0.0,
        "confidence": 0.0,
        "signals": 0,
    }


def summarize_timeframe(rows: Iterable[dict[str, Any]], interval: str) -> dict[str, Any]:
    """Сводит несколько стратегических сигналов одного TF в directional state.

    Используется max-confidence по направлению с небольшим бонусом за дополнительные
    подтверждающие стратегии. Это не раздувает силу только из-за большого числа
    однотипных сигналов, но сохраняет факт, что несколько независимых правил совпали.
    """
    relevant = [row for row in rows if _norm_interval(row.get("interval")) == interval]
    if not relevant:
        return _empty_tf(interval)

    by_direction: dict[str, list[float]] = {"long": [], "short": []}
    for row in relevant:
        direction = str(row.get("direction") or "").lower()
        if direction in by_direction:
            by_direction[direction].append(max(0.0, min(1.0, _num(row.get("confidence"), 0.0))))

    def strength(values: list[float]) -> float:
        if not values:
            return 0.0
        return min(1.0, max(values) + max(0, len(values) - 1) * 0.05)

    long_strength = strength(by_direction["long"])
    short_strength = strength(by_direction["short"])
    delta = long_strength - short_strength
    if long_strength >= 0.52 and delta >= 0.08:
        direction = "long"
        confidence = long_strength
    elif short_strength >= 0.52 and delta <= -0.08:
        direction = "short"
        confidence = short_strength
    else:
        direction = "neutral"
        confidence = max(long_strength, short_strength)

    return {
        "interval": interval,
        "direction": direction,
        "long_strength": round(long_strength, 6),
        "short_strength": round(short_strength, 6),
        "confidence": round(confidence, 6),
        "signals": len(relevant),
    }


def symbol_mtf_context(rows: Iterable[dict[str, Any]], intervals: MTFIntervals) -> dict[str, Any]:
    rows_list = list(rows)
    return {
        "entry": summarize_timeframe(rows_list, intervals.entry),
        "bias": summarize_timeframe(rows_list, intervals.bias),
        "regime": summarize_timeframe(rows_list, intervals.regime),
        "roles": {
            "entry_interval": intervals.entry,
            "bias_interval": intervals.bias,
            "regime_interval": intervals.regime,
        },
    }


def classify_candidate(candidate: dict[str, Any], context: dict[str, Any], intervals: MTFIntervals) -> dict[str, Any]:
    """Назначает intraday-класс кандидату с учетом 15m/60m/240m иерархии.

    Безопасный принцип: только entry-TF может быть кандидатом на вход. 60m и 240m
    остаются контекстом/фильтрами. Если старший TF явно против направления 15m,
    кандидат получает veto независимо от красивого локального сигнала.
    """
    direction = str(candidate.get("direction") or "").lower()
    interval = _norm_interval(candidate.get("interval"))
    entry = context.get("entry") or _empty_tf(intervals.entry)
    bias = context.get("bias") or _empty_tf(intervals.bias)
    regime = context.get("regime") or _empty_tf(intervals.regime)

    def aligned(tf: dict[str, Any]) -> bool:
        return direction in {"long", "short"} and tf.get("direction") == direction

    def conflicts(tf: dict[str, Any]) -> bool:
        tf_dir = tf.get("direction")
        return direction in {"long", "short"} and tf_dir in {"long", "short"} and tf_dir != direction

    entry_aligned = aligned(entry)
    bias_aligned = aligned(bias)
    regime_aligned = aligned(regime)
    entry_conflict = conflicts(entry)
    bias_conflict = conflicts(bias)
    regime_conflict = conflicts(regime)
    higher_tf_conflict = bias_conflict or regime_conflict
    is_entry_interval = interval == intervals.entry

    if direction not in {"long", "short"}:
        status = "invalid_direction"
        action_class = "NO_TRADE_INVALID"
        score = 0.0
        veto = True
        reason = "У сигнала нет торгового направления long/short."
    elif not is_entry_interval:
        status = "context_only"
        action_class = "CONTEXT_ONLY"
        score = 0.25 if not higher_tf_conflict else 0.05
        veto = True
        reason = f"{interval} используется как контекст. Вход разрешен только по {intervals.entry}."
    elif entry_conflict:
        status = "entry_tf_conflict"
        action_class = "NO_TRADE_ENTRY_CONFLICT"
        score = 0.05
        veto = True
        reason = "На entry-TF есть более сильный противоположный агрегированный сигнал."
    elif higher_tf_conflict:
        status = "no_trade_conflict"
        action_class = "NO_TRADE_CONFLICT"
        score = 0.05
        veto = True
        reason = "Старший таймфрейм против направления входа."
    elif bias_aligned and regime_aligned:
        status = "aligned_intraday"
        action_class = "HIGH_CONVICTION_INTRADAY"
        score = 1.0
        veto = False
        reason = "15m вход согласован с 60m и 240m."
    elif bias_aligned and regime.get("direction") == "neutral":
        status = "aligned_bias"
        action_class = "BIAS_ALIGNED_INTRADAY"
        score = 0.82
        veto = False
        reason = "15m вход согласован с 60m; 240m нейтрален или без сигнала."
    elif bias.get("direction") == "neutral" and not regime_conflict:
        status = "tactical_only"
        action_class = "TACTICAL_ONLY"
        score = 0.60
        veto = False
        reason = "Есть только тактический 15m сигнал без подтверждения 60m."
    else:
        status = "weak_alignment"
        action_class = "LOW_CONVICTION_INTRADAY"
        score = 0.48
        veto = False
        reason = "Согласованность неполная; требуется ручная проверка."

    return {
        "mtf_status": status,
        "mtf_action_class": action_class,
        "mtf_score": round(score, 6),
        "mtf_veto": veto,
        "mtf_reason": reason,
        "mtf_is_entry_candidate": is_entry_interval,
        "entry_tf_conflict": entry_conflict,
        "higher_tf_conflict": higher_tf_conflict,
        "bias_conflict": bias_conflict,
        "regime_conflict": regime_conflict,
        "entry_aligned": entry_aligned,
        "bias_aligned": bias_aligned,
        "regime_aligned": regime_aligned,
        "mtf_entry": entry,
        "mtf_bias": bias,
        "mtf_regime": regime,
        "mtf_entry_interval": intervals.entry,
        "mtf_bias_interval": intervals.bias,
        "mtf_regime_interval": intervals.regime,
    }


def apply_mtf_consensus(
    rows: list[dict[str, Any]],
    *,
    entry_interval: str = "15",
    bias_interval: str = "60",
    regime_interval: str = "240",
) -> list[dict[str, Any]]:
    """Добавляет MTF-поля и пересчитывает итоговый research score.

    Расчет выполняется поверх уже найденных latest-сигналов. Это keeps schema stable:
    не нужна новая таблица, а API/LLM/UI получают единый MTF-контекст на лету.
    """
    intervals = MTFIntervals(_norm_interval(entry_interval), _norm_interval(bias_interval), _norm_interval(regime_interval))
    by_market: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        # MTF-контекст нельзя смешивать между spot/linear/inverse с одинаковым symbol.
        market_key = (str(row.get("category") or "").lower(), str(row.get("symbol") or "").upper())
        by_market.setdefault(market_key, []).append(row)

    contexts = {market_key: symbol_mtf_context(symbol_rows, intervals) for market_key, symbol_rows in by_market.items()}
    out: list[dict[str, Any]] = []
    for row in rows:
        market_key = (str(row.get("category") or "").lower(), str(row.get("symbol") or "").upper())
        base_score = _num(row.get("research_score"), 0.0)
        mtf = classify_candidate(row, contexts.get(market_key, symbol_mtf_context([], intervals)), intervals)
        adjusted = base_score + mtf["mtf_score"] * 0.18
        if mtf["mtf_veto"]:
            adjusted -= 0.35
        if mtf["mtf_status"] == "aligned_intraday":
            adjusted += 0.08
        elif mtf["mtf_status"] == "aligned_bias":
            adjusted += 0.04
        elif mtf["mtf_status"] == "tactical_only":
            adjusted -= 0.03
        adjusted = max(-1.0, min(1.5, adjusted))
        out.append(
            {
                **row,
                "research_score_base": row.get("research_score"),
                "research_score": round(adjusted, 6),
                **mtf,
            }
        )

    out.sort(key=lambda item: (_num(item.get("research_score"), -999), item.get("created_at") is not None), reverse=True)
    return out
