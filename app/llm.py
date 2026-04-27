from __future__ import annotations

import json
from typing import Any

import requests

from .config import settings
from .serialization import to_jsonable


class LLMUnavailable(RuntimeError):
    pass


def ollama_generate(prompt: str, system: str | None = None, temperature: float = 0.1) -> str:
    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system
    try:
        response = requests.post(
            f"{settings.ollama_base_url}/api/generate",
            json=payload,
            timeout=settings.ollama_timeout_sec,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as exc:
        raise LLMUnavailable(f"LLM endpoint unavailable: {exc}") from exc


def classify_news_with_llm(title: str, symbol: str = "MARKET") -> dict[str, Any]:
    prompt = f"""
Classify the crypto market sentiment of this news headline for {symbol}.
Return only compact JSON with keys: score, label, rationale.
score must be from -1.0 bearish to +1.0 bullish.
Headline: {title}
""".strip()
    try:
        raw = ollama_generate(prompt, system="You are a strict financial-news sentiment classifier. Output JSON only.")
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw[start:end])
            score = max(-1.0, min(1.0, float(data.get("score", 0.0))))
            return {"score": score, "label": str(data.get("label", "neutral")), "rationale": str(data.get("rationale", ""))}
    except Exception:
        pass
    return {"score": 0.0, "label": "neutral", "rationale": "llm_unavailable_or_invalid_json"}


def market_brief(payload: dict[str, Any]) -> str:
    prompt = f"""
Оцени торговый сетап для СППР Bybit. Нужен не литературный отчёт, а машинно-читаемый LLM verdict.

Верни ровно 4 строки в таком формате:
LLM_RECOMMENDATION: LONG|SHORT|NEUTRAL
LLM_CONFIDENCE: число от 0 до 100
RATIONALE: одно короткое объяснение на русском языке, максимум 160 символов
MANUAL_CHECK: что оператор должен проверить вручную, максимум 120 символов

Правила:
- LONG означает, что LLM считает long-сценарий предпочтительным.
- SHORT означает, что LLM считает short-сценарий предпочтительным.
- NEUTRAL означает ждать/не входить/недостаточно подтверждений.
- Не обещай прибыль и не формулируй торговый приказ.
- Если направление алгоритма конфликтует с рисками, можешь вернуть NEUTRAL или противоположное направление.
- Не добавляй markdown, JSON, списки и лишний текст вне этих 4 строк.

Данные JSON:
{json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)}
""".strip()
    return ollama_generate(
        prompt,
        system="Ты строгий quant/risk LLM-классификатор для крипто-сетапов. Всегда возвращай только 4 строки: LLM_RECOMMENDATION, LLM_CONFIDENCE, RATIONALE, MANUAL_CHECK. Допустимые рекомендации: LONG, SHORT, NEUTRAL.",
        temperature=0.1,
    )
