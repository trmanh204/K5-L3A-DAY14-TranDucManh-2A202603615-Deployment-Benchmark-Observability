"""
Rate limiting (tiêu chí 7) — Sliding Window 60 giây lưu bằng Redis Sorted Set.

- Mọi worker / instance dùng chung state trên Redis.
- State vẫn giữ nguyên sau khi restart agent.
"""
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Kiểm tra giới hạn RATE_LIMIT_PER_MINUTE trong cửa sổ 60 giây gần nhất."""
    redis_key = f"ratelimit:{key}"
    now = time.time()
    window_start = now - WINDOW_SECONDS

    try:
        r.zremrangebyscore(redis_key, 0, window_start)
        current_count = r.zcard(redis_key)

        if current_count >= settings.rate_limit_per_minute:
            oldest = r.zrange(redis_key, 0, 0, withscores=True)
            retry_after = (
                max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
                if oldest
                else WINDOW_SECONDS
            )
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit_per_minute": settings.rate_limit_per_minute,
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError:
        raise HTTPException(
            status_code=503,
            detail="Rate limiter backend (Redis) unavailable",
        )
