from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import BASE_DIR
from .backtest_background import background_backtester
from .llm_background import background_evaluator
from .signal_background import signal_refresher


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Backtest/LLM запускаются первыми, чтобы автообновление сигналов не потеряло
    # downstream-запрос, если первый цикл завершится сразу после старта приложения.
    # Ни один из этих сервисов не отправляет ордера.
    background_evaluator.start()
    background_backtester.start()
    signal_refresher.start()
    try:
        yield
    finally:
        # Останавливаем producer первым, затем downstream-проверки.
        signal_refresher.stop()
        background_backtester.stop()
        background_evaluator.stop()


app = FastAPI(title="Bybit ML/LLM Research Lab", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router.build_fastapi_router() if hasattr(router, "build_fastapi_router") else router)

frontend_dir = BASE_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
def index():
    return FileResponse(frontend_dir / "index.html")
