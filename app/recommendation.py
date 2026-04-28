from __future__ import annotations

import math
from typing import Any

from .config import settings


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _boolish(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return None


def risk_reward(entry: Any, stop_loss: Any, take_profit: Any) -> float | None:
    entry_v = _finite(entry)
    stop_v = _finite(stop_loss)
    take_v = _finite(take_profit)
    if entry_v is None or stop_v is None or take_v is None:
        return None
    risk = abs(entry_v - stop_v)
    reward = abs(take_v - entry_v)
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def _directional_levels_problem(row: dict[str, Any], entry: float | None, stop: float | None, take: float | None) -> str | None:
    direction = str(row.get("direction") or "").lower()
    if entry is None or stop is None or take is None:
        return None
    if direction == "long" and not (stop < entry < take):
        return "Для LONG требуется stop_loss < entry < take_profit."
    if direction == "short" and not (take < entry < stop):
        return "Для SHORT требуется take_profit < entry < stop_loss."
    return None


def _add_reason(target: list[dict[str, str]], code: str, title: str, detail: str) -> None:
    target.append({"code": code, "title": title, "detail": detail})


def classify_operator_action(row: dict[str, Any]) -> dict[str, Any]:
    """Единая серверная классификация рекомендации для оператора.

    Система советующая, поэтому результат не является приказом на сделку. Класс
    REVIEW_ENTRY означает только право вынести сетап на ручную проверку; любое
    критическое veto переводит строку в NO_TRADE. Отсутствие optional-evidence
    (ML/LLM/бэктест) не должно навсегда держать сильный рыночный сетап в
    "наблюдении", но плохое доказательство явно снижает score или блокирует вход.
    """
    hard: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    evidence: list[dict[str, str]] = []

    direction = str(row.get("direction") or "").lower()
    if direction not in {"long", "short"}:
        _add_reason(hard, "direction", "Нет торгового направления", "Разрешены только LONG/SHORT; flat не является сделкой.")

    fresh = row.get("fresh")
    if fresh is False or str(row.get("data_status") or "").lower() in {"stale", "no_bar_time", "unclosed_bar"}:
        _add_reason(hard, "freshness", "Рыночные данные устарели", "Рекомендация не должна строиться по старой или незакрытой свече.")

    mtf_status = str(row.get("mtf_status") or "").lower()
    if row.get("mtf_veto") is True or row.get("higher_tf_conflict") is True or mtf_status in {"context_only", "no_trade_conflict", "entry_tf_conflict", "invalid_direction"}:
        _add_reason(hard, "mtf", "MTF запрещает вход", str(row.get("mtf_reason") or "60m/240m конфликтуют с entry-TF или строка не является entry-кандидатом."))
    elif mtf_status in {"tactical_only", "weak_alignment", ""}:
        _add_reason(warnings, "mtf_partial", "MTF подтвержден не полностью", str(row.get("mtf_reason") or "Есть только тактический сигнал без полного подтверждения старших TF."))

    eligible = _boolish(row.get("is_eligible"))
    if settings.require_liquidity_for_signals and eligible is False:
        _add_reason(hard, "liquidity", "Ликвидность не допущена", "Liquidity universe пометил инструмент как неeligible.")
    elif eligible is None:
        _add_reason(warnings, "liquidity_unknown", "Ликвидность не подтверждена", "Нет свежего liquidity snapshot; оператор должен проверить стакан вручную.")

    spread = _finite(row.get("spread_pct"))
    if spread is None:
        _add_reason(warnings, "spread_unknown", "Spread неизвестен", "Нет bid/ask snapshot для оценки исполнимости.")
    elif spread > settings.max_spread_pct:
        _add_reason(hard, "spread", "Spread шире лимита", f"Spread {spread:.4f}% > лимита {settings.max_spread_pct:.4f}%.")

    entry_v = _finite(row.get("entry"))
    stop_v = _finite(row.get("stop_loss"))
    take_v = _finite(row.get("take_profit"))
    rr = risk_reward(entry_v, stop_v, take_v)
    levels_problem = _directional_levels_problem(row, entry_v, stop_v, take_v)
    if rr is None:
        _add_reason(hard, "rr_missing", "SL/TP невалидны", "Нельзя оценить риск без корректных entry, stop-loss и take-profit.")
    elif levels_problem:
        # Абсолютный R/R может выглядеть приемлемо даже при перепутанных SL/TP.
        # Для торговой рекомендации порядок уровней должен соответствовать направлению.
        _add_reason(hard, "levels_order", "SL/TP противоречат направлению", levels_problem)
    elif rr < 1.15:
        _add_reason(hard, "rr_low", "Risk/Reward слишком низкий", f"R/R {rr:.2f} ниже минимального защитного порога 1.15.")
    elif rr < 1.45:
        _add_reason(warnings, "rr_moderate", "Risk/Reward умеренный", f"R/R {rr:.2f}; для уверенного сетапа желательно >= 1.45.")

    confidence = _finite(row.get("confidence"), 0.0) or 0.0
    if confidence < 0.52:
        _add_reason(hard, "confidence_low", "Confidence ниже входного минимума", f"Confidence {confidence:.2f} < 0.52.")
    elif confidence < 0.58:
        _add_reason(warnings, "confidence_moderate", "Confidence умеренный", f"Confidence {confidence:.2f}; требуется усиленная ручная проверка.")

    trades = _finite(row.get("trades_count"), 0.0) or 0.0
    pf = _finite(row.get("profit_factor"))
    max_dd = _finite(row.get("max_drawdown"))
    if trades <= 0 or pf is None:
        _add_reason(evidence, "backtest_missing", "Бэктест еще не готов", "Отсутствие бэктеста снижает доказательность, но не блокирует сам рыночный сетап.")
    elif trades >= 20 and pf < 1.0:
        _add_reason(hard, "backtest_negative", "Бэктест отрицательный", f"PF {pf:.2f} при {int(trades)} сделках — сетап нельзя выносить на вход.")
    elif trades < 20 or pf < 1.15:
        _add_reason(evidence, "backtest_weak", "Бэктест слабый или малый", f"Сделок {int(trades)}, PF {pf:.2f}; нужна ручная верификация.")
    if max_dd is not None and max_dd > max(settings.max_daily_drawdown * 2.5, 0.12):
        _add_reason(evidence, "drawdown_high", "Бэктест показывает высокий DD", f"Max DD {max_dd:.2%}; риск выше локального лимита.")

    roc_auc = _finite(row.get("roc_auc"))
    ml_probability = _finite(row.get("ml_probability"))
    if roc_auc is None and ml_probability is None:
        _add_reason(evidence, "ml_missing", "ML evidence ожидается", "Модель еще не дала пригодное подтверждение направления.")
    elif roc_auc is not None and roc_auc < 0.47:
        _add_reason(evidence, "ml_weak", "ML хуже случайного ориентира", f"ROC-AUC {roc_auc:.3f}; ML не подтверждает сетап.")

    base_score = _finite(row.get("research_score"), 0.0) or 0.0
    mtf_score = _finite(row.get("mtf_score"), 0.0) or 0.0
    score = 0.0
    score += max(0.0, min(1.0, base_score)) * 16.0
    score += max(0.0, min(1.0, mtf_score)) * 16.0
    score += max(0.0, min(1.0, confidence)) * 20.0
    score += max(0.0, min(1.0, ((rr or 0.0) - 1.0) / 1.5)) * 18.0
    score += 10.0 if eligible is True else 0.0
    score += 8.0 if spread is not None and spread <= settings.max_spread_pct else 0.0
    if pf is not None and trades > 0:
        score += max(0.0, min(1.0, pf / 1.8)) * 7.0 * max(0.25, min(1.0, trades / 40.0))
    if roc_auc is not None:
        score += max(0.0, min(1.0, (roc_auc - 0.5) / 0.18)) * 5.0
    if ml_probability is not None:
        score += max(0.0, min(1.0, (ml_probability - 0.5) / 0.25)) * 4.0
    if max_dd is not None:
        score += max(0.0, 1.0 - min(1.0, max_dd / 0.18)) * 4.0
    score -= min(18.0, len(evidence) * 3.0)
    score -= min(16.0, len(warnings) * 4.0)
    score = int(round(max(0.0, min(100.0, score))))

    confidence_band = "high" if confidence >= 0.70 else "normal" if confidence >= 0.58 else "low"
    core_entry_ok = not hard and confidence >= 0.58 and rr is not None and rr >= 1.45 and mtf_status not in {"context_only", "no_trade_conflict", "entry_tf_conflict", "invalid_direction"}
    if hard:
        action = "NO_TRADE"
        label = "НЕТ ВХОДА"
        level = "reject"
    elif core_entry_ok and (score >= 56 or confidence >= 0.66):
        action = "REVIEW_ENTRY"
        label = "РУЧНАЯ ПРОВЕРКА ВХОДА"
        level = "review"
    else:
        action = "WAIT"
        label = "НАБЛЮДАТЬ"
        level = "watch"

    return {
        "operator_action": action,
        "operator_label": label,
        "operator_level": level,
        "operator_score": score,
        "operator_confidence_band": confidence_band,
        "operator_hard_reasons": hard,
        "operator_warnings": warnings,
        "operator_evidence_notes": evidence,
        "risk_reward": round(rr, 6) if rr is not None else None,
    }


def annotate_recommendations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, **classify_operator_action(row)} for row in rows]
