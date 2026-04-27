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
Сделай предельно краткий риск-ориентированный разбор торговой ситуации.
Первая строка обязательна и должна иметь один из трех форматов:
ВЕРДИКТ: ДА, ВХОД ПОДТВЕРЖДАЮ — <короткая причина>
ВЕРДИКТ: НЕТ, ВХОД НЕ ПОДТВЕРЖДАЮ — <короткая причина>
ВЕРДИКТ: НАБЛЮДАТЬ, ВХОД НЕ ПОДТВЕРЖДАЮ — <короткая причина>
После вердикта дай не более 3 коротких пунктов: ключевой риск, условие отмены, что проверить вручную.
Не давай обещаний прибыли и не формулируй торговый приказ.
Данные JSON:
{json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2)}
""".strip()
    return ollama_generate(
        prompt,
        system="Ты риск-менеджер и quant-research аналитик. Пиши по-русски, очень кратко, структурно, без инвестиционных гарантий. Всегда начинай с явного ВЕРДИКТ в одном из разрешенных форматов.",
        temperature=0.2,
    )
