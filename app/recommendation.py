from __future__ import annotations

import math
from typing import Any

from .config import settings
from .strategy_quality import APPROVED, REJECTED, RESEARCH, STALE, WATCHLIST, effective_strategy_quality
from .trade_contract import enrich_recommendation_row


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


def _risk_score(*, hard_count: int, warning_count: int, rr: float | None, confidence: float, spread: float | None, max_dd: float | None, quality_status: str) -> int:
    score = 0.0
    score += min(45.0, hard_count * 22.0)
    score += min(22.0, warning_count * 7.0)
    score += 0.0 if rr is not None and rr >= 1.8 else 8.0 if rr is not None and rr >= 1.45 else 18.0
    score += 0.0 if confidence >= 0.66 else 8.0 if confidence >= 0.58 else 18.0
    if spread is None:
        score += 6.0
    elif spread > settings.max_spread_pct:
        score += 18.0
    elif spread > settings.max_spread_pct * 0.65:
        score += 7.0
    if max_dd is None:
        score += 5.0
    else:
        score += min(18.0, max(0.0, max_dd) * 100.0)
    if quality_status == APPROVED:
        score -= 8.0
    elif quality_status == WATCHLIST:
        score += 5.0
    elif quality_status in {REJECTED, STALE}:
        score += 25.0
    else:
        score += 10.0
    return int(round(max(0.0, min(100.0, score))))


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
    mtf_veto = _boolish(row.get("mtf_veto")) is True
    higher_tf_conflict = _boolish(row.get("higher_tf_conflict")) is True
    # API/DB/JSON-слои иногда возвращают булевы флаги строками. Для veto это
    # критично: строка "false" не должна становиться truthy, а строка "true"
    # не должна обходить запрет на вход.
    if mtf_veto or higher_tf_conflict or mtf_status in {"context_only", "no_trade_conflict", "entry_tf_conflict", "invalid_direction"}:
        _add_reason(hard, "mtf", "MTF запрещает вход", str(row.get("mtf_reason") or "60m/240m конфликтуют с entry-TF или строка не является entry-кандидатом."))
    elif mtf_status in {"tactical_only", "weak_alignment", ""}:
        _add_reason(warnings, "mtf_partial", "MTF подтвержден не полностью", str(row.get("mtf_reason") or "Есть только тактический сигнал без полного подтверждения старших TF."))

    eligible = _boolish(row.get("is_eligible"))
    liquidity_required = bool(settings.require_liquidity_for_signals)
    if liquidity_required and eligible is False:
        _add_reason(hard, "liquidity", "Ликвидность не допущена", "Liquidity universe пометил инструмент как non-eligible.")
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

    if rr is not None and entry_v and entry_v > 0 and stop_v is not None and take_v is not None:
        risk_pct_v = abs(entry_v - stop_v) / entry_v
        reward_pct_v = abs(take_v - entry_v) / entry_v
        fee_drag_pct = max(0.0, 2.0 * float(settings.fee_rate) + 2.0 * float(settings.slippage_rate))
        net_reward_pct = reward_pct_v - fee_drag_pct
        net_rr = net_reward_pct / risk_pct_v if risk_pct_v > 0 else None
        if net_rr is None or net_rr <= 1.0:
            _add_reason(hard, "net_rr_low", "Net R/R после комиссий слишком низкий", f"После fee/slippage net R/R {net_rr or 0:.2f}; вход не должен проходить review gate.")
        elif net_rr < 1.25:
            _add_reason(warnings, "net_rr_moderate", "Net R/R после комиссий умеренный", f"После fee/slippage net R/R {net_rr:.2f}; нужен уменьшенный риск или лучший entry.")

    confidence_raw = _finite(row.get("confidence"))
    if confidence_raw is None or confidence_raw < 0.0 or confidence_raw > 1.0:
        _add_reason(hard, "confidence_range", "Confidence вне диапазона", "Confidence должен быть конечным числом в диапазоне [0,1]; это инженерный скоринг, а не вероятность прибыли.")
    confidence = max(0.0, min(1.0, confidence_raw if confidence_raw is not None else 0.0))
    if confidence < 0.52:
        _add_reason(hard, "confidence_low", "Confidence ниже входного минимума", f"Confidence {confidence:.2f} < 0.52.")
    elif confidence < 0.58:
        _add_reason(warnings, "confidence_moderate", "Confidence умеренный", f"Confidence {confidence:.2f}; требуется усиленная ручная проверка.")

    trades = _finite(row.get("trades_count"), 0.0) or 0.0
    pf = _finite(row.get("profit_factor"))
    max_dd = _finite(row.get("max_drawdown"))
    total_return = _finite(row.get("total_return"))
    win_rate = _finite(row.get("win_rate"))
    wf_rate = _finite(row.get("walk_forward_pass_rate"))
    wf_windows = int(_finite(row.get("walk_forward_windows"), 0) or 0)
    no_loss_backtest = trades > 0 and pf is None and win_rate is not None and win_rate >= 0.999

    quality = effective_strategy_quality(row)
    quality_status = str(quality.get("quality_status") or RESEARCH).upper()
    quality_score = _finite(quality.get("quality_score"), 0.0) or 0.0
    if quality_status == APPROVED:
        _add_reason(evidence, "strategy_approved", "Стратегия approved", str(quality.get("quality_reason") or "Strategy-quality фильтр пройден."))
    elif quality_status == STALE:
        _add_reason(hard, "strategy_stale", "Strategy evidence устарел", str(quality.get("quality_reason") or "Нужна актуализация бэктеста/quality перед ручной проверкой входа."))
    elif quality_status == WATCHLIST:
        _add_reason(evidence, "strategy_watchlist", "Стратегия в наблюдении", str(quality.get("quality_reason") or "Evidence близок к допуску, но approval еще не пройден."))
    elif quality_status == REJECTED:
        _add_reason(hard, "strategy_rejected", "Стратегия отклонена quality-фильтром", str(quality.get("quality_reason") or "Бэктест/риск-профиль стратегии неприемлем."))
    else:
        _add_reason(evidence, "strategy_research", "Стратегия не approved", str(quality.get("quality_reason") or "Сетап остается исследовательским кандидатом до прохождения quality-фильтра."))

    if trades <= 0:
        _add_reason(evidence, "backtest_missing", "Бэктест еще не готов", "Отсутствие бэктеста теперь блокирует REVIEW_ENTRY: сетап остается RESEARCH_CANDIDATE.")
    elif no_loss_backtest:
        _add_reason(evidence, "backtest_no_losses", "Бэктест без убыточных сделок", f"Сделок {int(trades)}, win rate {win_rate:.0%}; PF не конечен, поэтому оператор должен проверить размер выборки.")
    elif pf is None:
        _add_reason(evidence, "backtest_incomplete", "Бэктест неполный", f"Сделок {int(trades)}, но profit factor не рассчитан; требуется ручная проверка отчета.")
    elif trades >= 20 and pf < 1.0:
        _add_reason(hard, "backtest_negative", "Бэктест отрицательный", f"PF {pf:.2f} при {int(trades)} сделках — сетап нельзя выносить на вход.")
    elif trades < settings.strategy_approval_min_trades or pf < settings.strategy_approval_min_profit_factor:
        _add_reason(evidence, "backtest_weak", "Бэктест слабый или малый", f"Сделок {int(trades)}, PF {pf:.2f}; требуется approval: сделок >= {settings.strategy_approval_min_trades}, PF >= {settings.strategy_approval_min_profit_factor:.2f}.")
    if max_dd is not None and max_dd > max(settings.strategy_approval_max_drawdown, settings.max_daily_drawdown * 2.5, 0.12):
        _add_reason(evidence, "drawdown_high", "Бэктест показывает высокий DD", f"Max DD {max_dd:.2%}; риск выше quality-лимита.")
    if wf_rate is None or wf_windows < settings.strategy_walk_forward_min_windows:
        _add_reason(evidence, "walk_forward_missing", "Walk-forward еще не рассчитан", "Quality gate работает по обычному backtest evidence; нужен rolling stability / walk-forward блок.")
    elif wf_rate < settings.strategy_walk_forward_min_pass_rate:
        _add_reason(evidence, "walk_forward_weak", "Walk-forward нестабилен", f"WF pass {wf_rate:.0%} ниже лимита {settings.strategy_walk_forward_min_pass_rate:.0%}.")
    else:
        _add_reason(evidence, "walk_forward_ok", "Walk-forward подтверждает устойчивость", f"WF pass {wf_rate:.0%} по {wf_windows} окнам.")

    recent_count = int(_finite(row.get("recent_outcomes_count"), 0.0) or 0)
    recent_loss_count = int(_finite(row.get("recent_loss_count"), 0.0) or 0)
    recent_loss_rate = _finite(row.get("recent_loss_rate"))
    recent_average_r = _finite(row.get("recent_average_r"))
    recent_profit_factor = _finite(row.get("recent_profit_factor"))
    recent_consecutive_losses = int(_finite(row.get("recent_consecutive_losses"), 0.0) or 0)
    if recent_count > 0:
        pf_text = "∞/недоступен" if recent_profit_factor is None else f"{recent_profit_factor:.2f}"
        avg_r_text = "н/д" if recent_average_r is None else f"{recent_average_r:.2f}R"
        _add_reason(
            evidence,
            "recent_outcome_quality",
            "Проверены последние фактические исходы",
            f"Последних исходов: {recent_count}, убыточных: {recent_loss_count}, средний R: {avg_r_text}, PF: {pf_text}.",
        )
    enough_recent = recent_count >= settings.recommendation_loss_quarantine_min_trades
    if recent_consecutive_losses >= settings.recommendation_loss_quarantine_consecutive_losses and recent_count >= recent_consecutive_losses:
        _add_reason(
            hard,
            "loss_streak_quarantine",
            "Серия последних рекомендаций убыточна",
            (
                f"Последние {recent_consecutive_losses} завершенных рекомендаций по этому symbol/TF/strategy/direction были убыточны. "
                "Новая сделка запрещена до переоценки стратегии."
            ),
        )
    elif (
        enough_recent
        and recent_loss_rate is not None
        and recent_average_r is not None
        and recent_loss_rate >= settings.recommendation_loss_quarantine_max_loss_rate
        and recent_average_r <= settings.recommendation_loss_quarantine_min_expectancy_r
    ):
        _add_reason(
            hard,
            "recent_loss_quarantine",
            "Недавние исходы запрещают новый вход",
            (
                f"Убыточность последних похожих рекомендаций {recent_loss_rate:.0%}, средний результат {recent_average_r:.2f}R. "
                "Это не слабый evidence, а активный блок на REVIEW_ENTRY."
            ),
        )
    elif enough_recent and recent_average_r is not None and recent_average_r < 0:
        _add_reason(
            warnings,
            "recent_expectancy_negative",
            "Недавняя expectancy отрицательная",
            f"Средний результат последних похожих рекомендаций {recent_average_r:.2f}R; риск должен быть снижен или сетап пропущен.",
        )

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
    score += max(0.0, min(1.0, quality_score / 100.0)) * 10.0
    if no_loss_backtest:
        score += 5.0 * max(0.25, min(1.0, trades / max(settings.strategy_approval_min_trades, 1)))
    elif pf is not None and trades > 0:
        score += max(0.0, min(1.0, pf / 1.8)) * 5.0 * max(0.25, min(1.0, trades / max(settings.strategy_approval_min_trades, 1)))
    if roc_auc is not None:
        score += max(0.0, min(1.0, (roc_auc - 0.5) / 0.18)) * 5.0
    if ml_probability is not None:
        score += max(0.0, min(1.0, (ml_probability - 0.5) / 0.25)) * 4.0
    if max_dd is not None:
        score += max(0.0, 1.0 - min(1.0, max_dd / 0.18)) * 4.0
    if wf_rate is not None and wf_windows >= settings.strategy_walk_forward_min_windows:
        score += max(0.0, min(1.0, wf_rate)) * 4.0
    if enough_recent and recent_loss_rate is not None:
        score -= min(14.0, max(0.0, recent_loss_rate) * 14.0)
    if enough_recent and recent_average_r is not None and recent_average_r < 0:
        score -= min(10.0, abs(recent_average_r) * 8.0)
    score -= min(18.0, len(evidence) * 3.0)
    score -= min(16.0, len(warnings) * 4.0)
    score = int(round(max(0.0, min(100.0, score))))

    confidence_band = "high" if confidence >= 0.70 else "normal" if confidence >= 0.58 else "low"
    liquidity_confirmed = (not liquidity_required) or eligible is True
    core_entry_ok = (
        not hard
        and liquidity_confirmed
        and confidence >= 0.58
        and rr is not None
        and rr >= 1.45
        and mtf_status not in {"context_only", "no_trade_conflict", "entry_tf_conflict", "invalid_direction"}
    )
    strategy_approved = (not settings.require_strategy_approval_for_review) or quality_status == APPROVED
    wf_not_catastrophic = (
        wf_rate is None
        or wf_windows < settings.strategy_walk_forward_min_windows
        or wf_rate >= settings.provisional_review_min_walk_forward_pass_rate
    )
    provisional_review_allowed = (
        bool(settings.allow_provisional_review_for_sample_only)
        and settings.require_strategy_approval_for_review
        and quality_status in {RESEARCH, WATCHLIST}
        and trades >= settings.provisional_review_min_trades
        and pf is not None
        and pf >= settings.provisional_review_min_profit_factor
        and (max_dd is None or max_dd <= settings.provisional_review_max_drawdown)
        and (total_return is None or total_return >= -0.03)
        and wf_not_catastrophic
        and score >= settings.provisional_review_min_score
    )
    quality_mode = "approved" if strategy_approved else "provisional" if provisional_review_allowed else "research"
    provisional_dd_text = "—" if max_dd is None else f"{max_dd:.2%}"

    if hard:
        action = "NO_TRADE"
        label = "НЕТ ВХОДА"
        level = "reject"
        quality_mode = "blocked"
    elif core_entry_ok and strategy_approved and score >= 56:
        action = "REVIEW_ENTRY"
        label = "РУЧНАЯ ПРОВЕРКА ВХОДА"
        level = "review"
    elif core_entry_ok and provisional_review_allowed:
        action = "REVIEW_ENTRY"
        label = "ПИЛОТНАЯ ПРОВЕРКА ВХОДА"
        level = "review"
        _add_reason(
            evidence,
            "provisional_review",
            "Пилотный допуск без полного approval",
            (
                f"Локальная выборка еще меньше полного approval ({int(trades)}/{settings.strategy_approval_min_trades}), "
                f"но PF {pf:.2f} >= {settings.provisional_review_min_profit_factor:.2f}, "
                f"DD {provisional_dd_text} <= {settings.provisional_review_max_drawdown:.2%}; "
                "это только ручная проверка, не приказ на сделку."
            ),
        )
    elif core_entry_ok and not strategy_approved:
        action = "RESEARCH_CANDIDATE"
        label = "ИССЛЕДОВАТЕЛЬСКИЙ КАНДИДАТ"
        level = "research"
    else:
        action = "WAIT"
        label = "НАБЛЮДАТЬ"
        level = "watch"

    risk_score = _risk_score(
        hard_count=len(hard),
        warning_count=len(warnings),
        rr=rr,
        confidence=confidence,
        spread=spread,
        max_dd=max_dd,
        quality_status=quality_status,
    )
    trust_status = (
        "BLOCKED" if hard
        else "REVIEW_ALLOWED" if action == "REVIEW_ENTRY" and quality_mode == "approved"
        else "PROVISIONAL_REVIEW" if action == "REVIEW_ENTRY" and quality_mode == "provisional"
        else "RESEARCH_ONLY" if action == "RESEARCH_CANDIDATE"
        else "WAIT"
    )
    risk_grade = "high" if risk_score >= 70 else "elevated" if risk_score >= 45 else "controlled"

    return {
        "operator_action": action,
        "operator_label": label,
        "operator_level": level,
        "operator_score": score,
        "operator_risk_score": risk_score,
        "operator_risk_grade": risk_grade,
        "operator_trust_status": trust_status,
        "operator_confidence_band": confidence_band,
        "operator_quality_mode": quality_mode,
        "quality_status": quality_status,
        "quality_score": int(round(quality_score)),
        "evidence_grade": quality.get("evidence_grade"),
        "quality_reason": quality.get("quality_reason"),
        "quality_diagnostics": quality.get("quality_diagnostics"),
        "operator_hard_reasons": hard,
        "operator_warnings": warnings,
        "operator_evidence_notes": evidence,
        "risk_reward": round(rr, 6) if rr is not None else None,
    }


def ensure_operator_decisions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Возвращает строки с operator_* полями без построения финального контракта.

    Консолидация очереди должна происходить между классификацией и enrichment.
    Иначе nested `recommendation` уже содержит старое решение, а последующая
    блокировка конфликта LONG/SHORT меняет только top-level поля. Для trading UI
    это критичный рассинхрон: карточка может показать NO_TRADE с вложенным
    REVIEW_ENTRY.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("operator_action") and isinstance(row.get("operator_hard_reasons"), list):
            out.append(dict(row))
        else:
            out.append({**row, **classify_operator_action(row)})
    return out


def annotate_recommendations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds the canonical operator decision and the frontend-ready trade ticket contract.

    The legacy row remains intact for backward compatibility, but every returned
    item now also has flat recommendation fields and a nested `recommendation`
    object. This keeps `/api/signals/latest` stable while giving the UI and new
    `/api/recommendations/*` endpoints one validated source of truth.
    """
    annotated: list[dict[str, Any]] = []
    for row in ensure_operator_decisions(rows):
        annotated.append(enrich_recommendation_row(row))
    return annotated
