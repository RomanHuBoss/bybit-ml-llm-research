from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import BASE_DIR
from .llm_background import background_evaluator


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # LLM-оценка запускается в фоне: интерфейс не должен ждать ручной кнопки
    # и не должен блокироваться на локальной модели Ollama.
    background_evaluator.start()
    try:
        yield
    finally:
        background_evaluator.stop()


app = FastAPI(title="Bybit ML/LLM Research Lab", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

frontend_dir = BASE_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.get("/")
def index():
    return FileResponse(frontend_dir / "index.html")
