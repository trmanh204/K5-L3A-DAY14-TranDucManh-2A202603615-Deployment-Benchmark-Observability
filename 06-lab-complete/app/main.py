"""
Production AI Agent — Part 6 Final Project

Đạt đủ 12 tiêu chí Production Readiness:
  - Config từ biến môi trường (12-Factor)
  - Structured JSON logging
  - Health (/health) & Readiness (/ready) tách biệt
  - API Key authentication (X-API-Key → 401)
  - Sliding-window Rate Limiting trên Redis (→ 429 + Retry-After)
  - Cost Guard trên Redis (→ 402)
  - Graceful shutdown (lifespan + SIGTERM)
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import sys
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mọi dòng log của app thành đúng 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "env": settings.environment,
        }
        if isinstance(record.msg, dict):
            payload.update(record.msg)
        else:
            payload["msg"] = record.getMessage()

        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)

        return json.dumps(payload, ensure_ascii=False)


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("production_agent")
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log.setLevel(level)
    log.propagate = False
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        log.addHandler(handler)
    return log


logger = _setup_logger()
START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management & graceful shutdown."""
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        logger.info({"event": "sigterm_received", "signal": signum})
        if callable(previous_sigterm):
            previous_sigterm(signum, frame)

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):
        # Bỏ qua nếu không nằm trên main thread
        pass

    logger.info({
        "event": "startup",
        "environment": settings.environment,
        "port": settings.port,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "daily_budget_usd": settings.daily_budget_usd,
    })

    yield

    logger.info({"event": "shutdown_start"})
    try:
        r.close()
    except Exception:
        pass
    logger.info({"event": "shutdown_complete"})


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Ghi nhận mỗi HTTP request dưới dạng 1 dòng JSON log."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info({
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": elapsed_ms,
        })
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.error({
            "event": "http_error",
            "method": request.method,
            "path": request.url.path,
            "error_type": type(exc).__name__,
            "ms": elapsed_ms,
        })
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn sống (không phụ thuộc Redis)."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/ready")
def ready():
    """Readiness probe — 200 khi Redis sẵn sàng, 503 khi Redis mất kết nối."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis is not available")
    return {
        "status": "ready",
        "redis": "ok",
        "environment": settings.environment,
    }


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Protected endpoint: Auth → Rate Limit (Redis) → Cost Guard (Redis) → LLM."""
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost_usd = record_cost(input_tokens, output_tokens)

    logger.info({
        "event": "ask_completed",
        "user_id": body.user_id or "anonymous",
        "question_length": len(body.question),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    })

    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        },
    }
