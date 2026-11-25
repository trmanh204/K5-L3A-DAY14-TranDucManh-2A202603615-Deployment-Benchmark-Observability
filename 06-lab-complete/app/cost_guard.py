"""
Cost guard (tiêu chí 8) — theo dõi và chặn chi phí LLM tập trung trên Redis.

- Kiểm tra ngân sách TRƯỚC khi gọi LLM → vượt trần trả HTTP 402.
- Cộng dồn chi phí SAU khi gọi LLM bằng INCRBYFLOAT (atomic).
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006
COST_TTL_SECONDS = 48 * 3600


def _daily_cost_key() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{today}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    key = _daily_cost_key()
    try:
        current = float(r.get(key) or 0.0)
    except redis.RedisError:
        raise HTTPException(
            status_code=503,
            detail="Cost guard backend (Redis) unavailable",
        )

    if current >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily LLM budget exceeded",
                "spent_usd": round(current, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng trong Redis."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    key = _daily_cost_key()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, COST_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError:
        pass
    return round(cost, 8)
