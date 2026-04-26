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


def test_llm_request_run_does_not_set_shutdown_flag():
    from app.llm_background import LLMBackgroundEvaluator

    evaluator = LLMBackgroundEvaluator()
    evaluator.request_run()

    assert evaluator._run_requested is True
    assert evaluator._stop_requested is False
