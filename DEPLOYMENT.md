# Deployment Information — Day 14 Production AI Agent

## Public URL
https://k5-l3a-day14-tranducmanh-2a202603615-deployment-production.up.railway.app

## Platform
- **Cloud Platform:** Railway (Project `peaceful-energy`, Root Directory: `06-lab-complete`, Builder: `DOCKERFILE` theo `railway.toml`)
- **Backing Service:** Railway Managed Redis (nối nội bộ qua biến tham chiếu `${{Redis.REDIS_URL}}`)

## Test Commands

Đặt biến môi trường trên terminal trước khi chạy để không lộ key trong ảnh chụp:

```bash
export BASE="https://k5-l3a-day14-tranducmanh-2a202603615-deployment-production.up.railway.app"
export AGENT_API_KEY="<YOUR_AGENT_API_KEY>"
```

### 1. Kiểm tra nhanh 4 mã HTTP chuẩn (CP6 — an toàn không lộ key)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"                                                                                 # Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"                                                                                  # Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'              # Expected: 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'  # Expected: 200
```

### 2. Health Check (`GET /health`)

```bash
curl -sS "$BASE/health"
# Output thực tế:
# {"status":"ok","environment":"production","uptime_seconds":3473.8}
```

### 3. Readiness Check (`GET /ready` — xác nhận kết nối Redis trên Railway)

```bash
curl -sS "$BASE/ready"
# Output thực tế:
# {"status":"ready","redis":"ok","environment":"production"}
```

### 4. API Test (có xác thực `X-API-Key`)

```bash
curl -sS -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: HTTP 200 với JSON chứa question, answer, user_id, usage (input_tokens, output_tokens, cost_usd)
```

### 5. Kiểm tra thiếu API key (chặn truy cập trái phép)

```bash
curl -sS -i -X POST "$BASE/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Output thực tế:
# HTTP/1.1 401 Unauthorized
# {"detail":"Invalid or missing API key. Provide header: X-API-Key"}
```

## Environment Variables Set on Railway
*(Toàn bộ đặt trực tiếp trên Railway Dashboard, tuyệt đối không commit vào mã nguồn)*

- `REDIS_URL` (`${{Redis.REDIS_URL}}` — nối tới Railway Redis)
- `AGENT_API_KEY` *(secret key đặt trên Railway Dashboard)*
- `ENVIRONMENT` (`production`)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `PORT` *(do Railway tự động inject: `8080`, container tự lắng nghe theo `${PORT:-8000}`)*

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running & JSON logs](screenshots/running.png)
- [Public API test results](screenshots/test.png)
