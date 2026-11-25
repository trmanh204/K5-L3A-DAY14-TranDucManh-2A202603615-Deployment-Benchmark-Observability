"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

- Không hard-code secret trong code.
- Có giá trị mặc định hợp lý khi chạy local.
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Tự động nạp file .env nếu có ở môi trường local (không ghi đè env đã set từ platform)
load_dotenv(override=False)


def _get_float_budget() -> float:
    raw = os.getenv("DAILY_BUDGET_USD") or os.getenv("MONTHLY_BUDGET_USD") or "1.0"
    return float(raw)


@dataclass
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
    )
    daily_budget_usd: float = field(default_factory=_get_float_budget)
    monthly_budget_usd: float = field(
        default_factory=lambda: float(os.getenv("MONTHLY_BUDGET_USD", "10.0"))
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


settings = Settings()
