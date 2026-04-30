from __future__ import annotations

import copy
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _direction_strength(row: dict[str, Any]) -> float:
    """Считает силу строки для внутриснимочного выбора направления.

    Здесь не принимается торговое решение. Цель — понять, есть ли у рынка один
    доминирующий сценарий или же LONG/SHORT конкурируют настолько близко, что
    оператору нужно показать явный конфликт вместо мигающей очереди сигналов.
    """
    score = _finite(row.get("operator_score"), 0.0)
    confidence = max(0.0, min(1.0, _finite(row.get("confidence"), 0.0))) * 25.0
    mtf = max(0.0, min(1.0, _finite(row.get("mtf_score"), 0.0))) * 12.0
    rr = _finite(row.get("risk_reward"), 0.0)
    rr_bonus = max(0.0, min(12.0, (rr - 1.0) * 8.0)) if rr > 0 else 0.0
    level = str(row.get("operator_level") or "").lower()
    level_bonus = {"review": 12.0, "watch": 4.0, "reject": -8.0}.get(level, 0.0)
    return max(0.0, score + confidence + mtf + rr_bonus + level_bonus)


def _candidate_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("category") or "").lower(),
        str(row.get("symbol") or "").upper(),
        str(row.get("interval") or row.get("mtf_entry_interval") or "").upper(),
    )


def _same_bar_key(row: dict[str, Any]) -> str:
    parsed = _parse_time(row.get("bar_time"))
    return parsed.isoformat() if parsed else "no_bar_time"


def _append_operator_reason(row: dict[str, Any], bucket: str, code: str, title: str, detail: str) -> None:
    values = row.get(bucket)
    if not isinstance(values, list):
        values = []
    values = [item for item in values if isinstance(item, dict) and item.get("code") != code]
    values.insert(0, {"code": code, "title": title, "detail": detail})
    row[bucket] = values


def _force_conflict_decision(row: dict[str, Any], *, directions: dict[str, float], variants: int) -> dict[str, Any]:
    out = copy.deepcopy(row)
    out["operator_action"] = "NO_TRADE"
    out["operator_label"] = "КОНФЛИКТ СИГНАЛОВ"
    out["operator_level"] = "reject"
    out["operator_score"] = min(int(_finite(out.get("operator_score"), 0)), 35)
    out["direction_conflict"] = True
    out["direction_strength_long"] = round(directions.get("long", 0.0), 6)
    out["direction_strength_short"] = round(directions.get("short", 0.0), 6)
    out["direction_gap"] = round(abs(directions.get("long", 0.0) - directions.get("short", 0.0)), 6)
    out["operator_variant_count"] = variants
    _append_operator_reason(
        out,
        "operator_hard_reasons",
        "direction_conflict",
        "Конфликт LONG/SHORT внутри одного рынка",
        "Для одного symbol/TF на одной свежей свече есть конкурирующие стратегии. Вход запрещен до ручного разбора графика и причин.",
    )
    out["operator_queue_note"] = "Рынок не имеет единого доминирующего направления; рекомендация стабилизирована как NO_TRADE."
    return out


def _add_stability_warning(row: dict[str, Any], *, directions: dict[str, float], variants: int) -> dict[str, Any]:
    out = copy.deepcopy(row)
    own = str(out.get("direction") or "").lower()
    own_strength = directions.get(own, 0.0)
    opposite = directions.get("short" if own == "long" else "long", 0.0)
    total = max(1.0, own_strength + opposite)
    dominance = max(0.0, min(1.0, (own_strength - opposite) / total))
    variant_bonus = min(0.25, max(0, variants - 1) * 0.08)
    stability_score = max(0.0, min(1.0, 0.55 + dominance * 0.45 + variant_bonus))
    out["direction_conflict"] = False
    out["direction_strength_long"] = round(directions.get("long", 0.0), 6)
    out["direction_strength_short"] = round(directions.get("short", 0.0), 6)
    out["direction_gap"] = round(abs(directions.get("long", 0.0) - directions.get("short", 0.0)), 6)
    out["operator_variant_count"] = variants
    out["operator_stability_score"] = round(stability_score, 6)
    if stability_score < 0.72 and str(out.get("operator_level") or "").lower() in {"review", "research"}:
        out["operator_action"] = "WAIT"
        out["operator_label"] = "НАБЛЮДАТЬ"
        out["operator_level"] = "watch"
        out["operator_score"] = min(int(_finite(out.get("operator_score"), 0)), 55)
        _append_operator_reason(
            out,
            "operator_warnings",
            "weak_direction_dominance",
            "Слабое доминирование направления",
            "Лучший сетап не имеет достаточного отрыва от альтернативных сигналов этого рынка; вход переносится в наблюдение.",
        )
    return out


def consolidate_operator_queue(rows: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    """Возвращает устойчивую операторскую очередь: максимум одна строка на рынок.

    В исходных данных одна пара может иметь несколько стратегий и даже разные
    направления. Для trading-СППР это опасно: UI начинает показывать сменяющиеся
    «рекомендации», хотя фактически у рынка нет единого решения. Консолидация
    сохраняет лучший сетап, но явно блокирует рынки с близким LONG/SHORT конфликтом.
    """
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_candidate_key(row)].append(row)

    output: list[dict[str, Any]] = []
    for group_rows in grouped.values():
        # Сравниваем только строки последней bar_time внутри рынка, чтобы старые
        # стратегии не создавали ложный конфликт с новым свежим баром.
        latest_bar = max((_parse_time(row.get("bar_time")) for row in group_rows), default=None)
        if latest_bar is not None:
            same_bar_rows = [row for row in group_rows if _parse_time(row.get("bar_time")) == latest_bar]
        else:
            same_bar_rows = list(group_rows)

        enriched = [{**row, "_direction_strength": _direction_strength(row)} for row in same_bar_rows]
        enriched.sort(key=lambda row: (_finite(row.get("operator_score"), 0), row.get("_direction_strength", 0), _finite(row.get("confidence"), 0)), reverse=True)
        if not enriched:
            continue
        best = enriched[0]
        directions: dict[str, float] = {"long": 0.0, "short": 0.0}
        strong_direction_counts: dict[str, int] = {"long": 0, "short": 0}
        for row in enriched:
            direction = str(row.get("direction") or "").lower()
            if direction not in directions:
                continue
            strength = row.get("_direction_strength", 0.0)
            directions[direction] = max(directions[direction], strength)
            if _finite(row.get("confidence"), 0.0) >= 0.56 and str(row.get("operator_level") or "") != "reject":
                strong_direction_counts[direction] += 1

        gap = abs(directions["long"] - directions["short"])
        has_material_conflict = (
            strong_direction_counts["long"] > 0
            and strong_direction_counts["short"] > 0
            and min(directions["long"], directions["short"]) >= 50.0
            and gap < 18.0
        )
        variants = len(enriched)
        cleaned_best = {k: v for k, v in best.items() if not k.startswith("_")}
        if has_material_conflict:
            output.append(_force_conflict_decision(cleaned_best, directions=directions, variants=variants))
        else:
            output.append(_add_stability_warning(cleaned_best, directions=directions, variants=variants))

    def sort_key(row: dict[str, Any]) -> tuple[int, float, float, str]:
        priority = {"review": 4, "research": 3, "watch": 2, "reject": 1}.get(str(row.get("operator_level") or "").lower(), 0)
        return (priority, _finite(row.get("operator_score"), 0.0), _finite(row.get("confidence"), 0.0), str(row.get("symbol") or ""))

    output.sort(key=sort_key, reverse=True)
    return output[:limit] if limit is not None else output
