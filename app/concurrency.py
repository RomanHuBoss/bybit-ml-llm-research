from __future__ import annotations


def bounded_worker_count(requested: int | None, job_count: int, *, default: int = 1, hard_limit: int = 16) -> int:
    """Возвращает безопасное число worker-потоков для независимых I/O/CPU-lite задач.

    Параллелизм в торговой СППР нельзя включать без верхних границ: слишком много
    потоков легко превращает ускорение в rate-limit Bybit, лишние DB-соединения и
    шумные ошибки. Поэтому все фоновые тяжелые операции используют этот единый
    нормализатор и дополнительно ограничиваются настройками окружения.
    """
    try:
        value = int(requested if requested is not None else default)
    except (TypeError, ValueError):
        value = int(default)
    if job_count <= 0:
        return 0
    value = max(1, value)
    value = min(value, max(1, int(hard_limit)))
    return min(value, job_count)
