"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

- Đọc REDIS_URL từ config.
- Không ping Redis lúc import để ứng dụng vẫn khởi động được khi Redis chưa sẵn sàng.
- redis_healthy() dùng cho GET /ready.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def redis_healthy() -> bool:
    """Kiểm tra kết nối Redis cho readiness probe (/ready)."""
    try:
        return bool(r.ping())
    except Exception:
        return False
