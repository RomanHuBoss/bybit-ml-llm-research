from __future__ import annotations


def test_llm_background_run_once_rejects_overlap():
    from app.llm_background import LLMBackgroundEvaluator

    evaluator = LLMBackgroundEvaluator()
    assert evaluator._run_lock.acquire(blocking=False)
    try:
        result = evaluator.run_once()
    finally:
        evaluator._run_lock.release()

    assert result["reason"] == "already_running"
    assert result["skipped"] == 1
