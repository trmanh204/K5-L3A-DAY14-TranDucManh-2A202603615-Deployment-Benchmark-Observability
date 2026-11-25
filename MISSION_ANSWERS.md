# Day 14 Lab — Mission Answers

> **Môn học:** AICB-P1 · Day 14: Deployment, Benchmark & Observability  
> **Môi trường chạy kiểm chứng:** Ubuntu 24.04 (WSL2, `os.name = posix`), Python 3.12.3, Docker 29.9.3 / Compose v5.7.0

---

## Part 1: Localhost vs Production

### Exercise 1.1: Các anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

Phân tích file `01-localhost-vs-production/develop/app.py`, phát hiện **7 anti-patterns** nghiêm trọng khiến ứng dụng không sẵn sàng chạy production:

1. **Hardcode secrets trực tiếp trong mã nguồn (dòng 17–18):**
   - Code: `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`.
   - Rủi ro: Khi push lên Git/GitHub, secret bị lộ vĩnh viễn trong lịch sử commit; kẻ xấu có thể đánh cắp API key để gọi LLM gây thiệt hại tài chính hoặc truy cập trái phép cơ sở dữ liệu.
   - Cách `production/` khắc phục (`production/config.py`, dòng 27–32): Toàn bộ secret đọc từ biến môi trường (`os.getenv("OPENAI_API_KEY", "")`, `os.getenv("AGENT_API_KEY", "")`), kết hợp hàm `validate()` báo lỗi ngay (*fail fast*) nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production`.

2. **Hardcode cấu hình ứng dụng, không tách biệt môi trường (dòng 21–22):**
   - Code: `DEBUG = True`, `MAX_TOKENS = 500`.
   - Rủi ro: Muốn đổi cấu hình giữa `development` / `staging` / `production` phải sửa code và build lại, dễ vô tình bật `DEBUG=True` trên production.
   - Cách `production/` khắc phục (`production/config.py`, dòng 15–35): Gom tập trung vào `dataclass Settings`, mọi giá trị đọc từ env var với giá trị mặc định an toàn (`DEBUG=false`).

3. **Dùng `print()` thay cho structured logging và in thẳng secret ra log (dòng 33–38):**
   - Code: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`.
   - Rủi ro: Làm lộ API key ngay trong hệ thống log; đồng thời log dạng text thuần không có timestamp, log level hay cấu trúc JSON nên công cụ thu thập log (Loki, Datadog, Cloud Logging) rất khó lọc và tìm kiếm.
   - Cách `production/` khắc phục (`production/app.py`, dòng 28–32, 111–122): Dùng module `logging` chuẩn, xuất log dạng JSON (`json.dumps({"event": "agent_request", "question_length": len(question), ...})`), tuyệt đối không log secret.

4. **Không có Health Check và Readiness endpoint (dòng 42–43):**
   - Khi gọi `GET /health` bản `develop` trả về `404 Not Found`.
   - Rủi ro: Nền tảng cloud (Railway, Render, Kubernetes) hoặc Load Balancer không biết container còn sống hay đã treo để tự động restart, cũng không biết app đã khởi tạo xong chưa để định tuyến traffic.
   - Cách `production/` khắc phục (`production/app.py`, dòng 135–161): Cung cấp đầy đủ `GET /health` (liveness probe) và `GET /ready` (readiness probe trả `503` khi chưa sẵn sàng).

5. **Bind cứng `host="localhost"` và cố định `port=8000` (dòng 51–52):**
   - Code: `uvicorn.run("app:app", host="localhost", port=8000, ...)`.
   - Rủi ro: Trong Docker container, bind `localhost` (`127.0.0.1`) chỉ nhận kết nối từ bên trong container, không thể truy cập từ bên ngoài. Ngoài ra các cloud PaaS (Railway, Render, Cloud Run) cấp port động qua biến môi trường `PORT`; gắn cứng `8000` sẽ khiến deploy thất bại.
   - Cách `production/` khắc phục (`production/config.py` dòng 17–18 & `production/app.py` dòng 194–197): Đọc `HOST` (mặc định `0.0.0.0`) và `PORT` (mặc định `8000`) từ biến môi trường.

6. **Bật `reload=True` cố định khi chạy server (dòng 53):**
   - Code: `reload=True`.
   - Rủi ro: Chế độ WatchFiles theo dõi file tốn thêm CPU/RAM, tạo thêm tiến trình reloader, không ổn định và dễ gây rò rỉ tài nguyên trên production.
   - Cách `production/` khắc phục (`production/app.py`, dòng 198): Chỉ bật `reload=settings.debug` (mặc định `false`).

7. **Không xử lý Lifecycle & Graceful Shutdown (và thiếu kiểm soát CORS / nhận input qua query param):**
   - Bản `develop` không có `lifespan` hay xử lý `SIGTERM`, nên khi container dừng để deploy bản mới, request đang xử lý có thể bị cắt ngang đột ngột. Đồng thời `POST /ask` nhận `question` qua query string thay vì JSON body.
   - Cách `production/` khắc phục (`production/app.py`, dòng 39–67, 77–82, 102–108, 180–189): Dùng FastAPI `lifespan` quản lý startup/shutdown (`is_ready = False` trước khi tắt), đăng ký handler `SIGTERM`, cấu hình `CORSMiddleware` theo `ALLOWED_ORIGINS`, và kiểm tra dữ liệu đầu vào JSON body (trả `422` nếu thiếu `question`).

---

### Exercise 1.2: Kết quả chạy thực tế bản `develop`

Chạy trong Ubuntu WSL2 (`01-localhost-vs-production/develop/`):

```bash
python app.py
curl -sS -i http://localhost:8000/
curl -sS -i -X POST "http://localhost:8000/ask?question=Hello"
curl -sS -i http://localhost:8000/health
```

**Output thực tế:**

```http
--- GET / ---
HTTP/1.1 200 OK
content-type: application/json

{"message":"Hello! Agent is running on my machine :)"}

--- POST /ask?question=Hello ---
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

--- GET /health ---
HTTP/1.1 404 Not Found
content-type: application/json

{"detail":"Not Found"}
```

**Log server bản `develop` cho thấy rõ anti-pattern (chạy reloader, bind localhost, in lộ API key):**

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [233] using WatchFiles
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.
INFO:     127.0.0.1:42444 - "POST /ask?question=Hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:42448 - "GET /health HTTP/1.1" 404 Not Found
```

---

### Exercise 1.3: Chạy bản `production` và bảng so sánh

Chạy bản `production` với biến môi trường `ENVIRONMENT=staging PORT=8000 python app.py`:

```http
--- GET /health ---
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":0.2,"version":"1.0.0","environment":"staging","timestamp":"2026-11-25T11:08:58.185669+00:00"}

--- GET /ready ---
HTTP/1.1 200 OK
content-type: application/json

{"ready":true}

--- POST /ask (JSON) ---
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
```

**Bảng so sánh `develop` vs `production`:**

| Tính năng | Bản `develop` (Basic) | Bản `production` (Advanced — 12-Factor) | Tại sao quan trọng trên Production? |
| :--- | :--- | :--- | :--- |
| **Config & Secrets** | Hardcode trực tiếp trong `app.py` (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG=True`) | Đọc toàn bộ từ biến môi trường qua `config.py` (`Settings` + `.env.example`), fail-fast nếu thiếu `AGENT_API_KEY` ở prod | Không bao giờ lộ secret lên Git; dùng chung 1 artifact/code cho dev, staging, prod mà chỉ cần đổi env vars |
| **Health & Readiness** | Không có (`GET /health` → `404`) | Có `GET /health` (liveness) và `GET /ready` (readiness trả `200`/`503`) | Cloud platform biết khi nào container chết để tự restart (`/health`); Load Balancer biết khi nào instance sẵn sàng mới đẩy traffic vào (`/ready`) |
| **Logging** | `print("[DEBUG] ...")`, in lộ cả `OPENAI_API_KEY` | Dùng `logging` chuẩn, cấu trúc JSON (`event`, `question_length`, `client_ip`), không log secret | Log aggregators (Loki, Datadog, ELK) parse và truy vấn được theo field; bảo vệ bí mật không lọt vào log |
| **Host, Port & Reload** | Cố định `host="localhost"`, `port=8000`, `reload=True` | `host="0.0.0.0"`, `port` đọc từ `PORT` env var, `reload=settings.debug` (mặc định `false`) | Container/cloud bắt buộc bind `0.0.0.0` và nghe theo port platform cấp; tắt reload để ổn định và tiết kiệm tài nguyên |
| **Lifecycle & Shutdown** | Tắt đột ngột, không có `lifespan` hay `SIGTERM` handler | Có `lifespan` (quản lý `is_ready`, startup/shutdown) và đăng ký `signal.SIGTERM` | Khi deploy bản mới hoặc scale-in, server ngừng nhận request mới và hoàn tất request đang xử lý (in-flight), tránh lỗi 502/đứt kết nối cho người dùng |
| **Bảo mật & API Contract** | Không cấu hình CORS; nhận `question` qua query param | Cấu hình `CORSMiddleware` theo `ALLOWED_ORIGINS`; nhận JSON body và validate (trả `422` nếu rỗng) | Hạn chế truy cập cross-origin trái phép; tránh lộ nội dung nhạy cảm trên URL/access log khi truyền qua query string |

---

## Part 2: Docker

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` (full Python distribution dựa trên Debian đầy đủ, bao gồm sẵn nhiều công cụ hệ thống và trình biên dịch như `gcc`, khiến kích thước gốc đã rất lớn).
2. **Working directory là gì?**
   - `/app` (khai báo qua `WORKDIR /app` — mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều chạy tương đối từ thư mục này bên trong container).
3. **Tại sao phải `COPY requirements.txt` trước `COPY app.py`?**
   - Để tận dụng cơ chế **Docker Layer Cache**. Docker cache từng bước theo thứ tự từ trên xuống; nếu chỉ sửa mã nguồn (`app.py`) mà không đổi `requirements.txt`, Docker sẽ tái sử dụng layer đã `pip install` trước đó thay vì tải và cài lại toàn bộ thư viện từ đầu, giúp thời gian rebuild giảm từ vài phút xuống chỉ vài giây.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - **`CMD`** quy định lệnh/tham số mặc định khi chạy container và **dễ dàng bị ghi đè** nếu người dùng truyền lệnh khác lúc chạy `docker run <image> <lệnh-khác>` (ví dụ `docker run -it my-agent:develop bash`).
   - **`ENTRYPOINT`** cố định chương trình thực thi chính của container; các tham số truyền thêm khi `docker run` sẽ được **nối vào sau** `ENTRYPOINT` (trừ khi dùng cờ `--entrypoint`). Thông thường dùng `ENTRYPOINT` cho binary cố định và `CMD` cho các tham số mặc định đi kèm.

---

### Exercise 2.2: Build và chạy container bản `develop`

Build từ thư mục gốc repository và chạy container:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --name cp2-dev -p 8000:8000 my-agent:develop
curl -sS -i http://localhost:8000/health
curl -sS -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
```

**Output thực tế từ container `my-agent:develop`:**

```http
--- GET http://localhost:8000/health ---
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"status":"ok","uptime_seconds":0.3,"container":true}

--- POST http://localhost:8000/ask?question=What%20is%20Docker%3F ---
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

---

### Exercise 2.3: Multi-stage build và so sánh kích thước image

Phân tích `02-docker/production/Dockerfile`:
- **Stage 1 (`builder` — `FROM python:3.11-slim AS builder`):** Cài build tools (`gcc`, `libpq-dev`) để biên dịch các thư viện Python có phần mở rộng C, sau đó chạy `pip install --no-cache-dir --user -r requirements.txt` cài gói vào `/root/.local`.
- **Stage 2 (`runtime` — `FROM python:3.11-slim AS runtime`):** Chỉ sao chép thư viện đã cài từ stage `builder` (`COPY --from=builder /root/.local /home/appuser/.local`) cùng mã nguồn ứng dụng; tạo user không có quyền root (`appuser`), thiết lập `HEALTHCHECK`, và chạy `uvicorn` với 2 worker.
- **Tại sao image nhỏ hơn và an toàn hơn?**
  1. Dùng base image gọn `python:3.11-slim` thay vì bản `python:3.11` đầy đủ.
  2. Toàn bộ công cụ biên dịch (`gcc`, `libpq-dev`, headers, cache build) chỉ tồn tại ở Stage 1 và **bị loại bỏ hoàn toàn** khỏi image cuối (Stage 2), vừa giảm mạnh dung lượng, vừa thu hẹp bề mặt tấn công (attack surface).

**Kết quả đo thực tế trên máy bằng `docker images my-agent` (build từ gốc repo):**

```text
IMAGE               ID             DISK USAGE   CONTENT SIZE   EXTRA
my-agent:advanced   fdd901dd1dac        240MB         57.4MB
my-agent:develop    6ab941d03891       1.67GB          426MB
```

| Image | Dung lượng thực tế (`docker images`) | Dung lượng chính xác (bytes / MiB) | Chênh lệch |
| :--- | :---: | :---: | :---: |
| `my-agent:develop` (single-stage, `python:3.11`) | **1.67 GB** (1,667.8 MB) | `1,667,792,294 bytes` (`1,590.5 MiB`) | — |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | **240 MB** (239.8 MB) | `239,815,297 bytes` (`228.7 MiB`) | **Giảm 85.6%** (nhỏ hơn ~7 lần) |

---

### Exercise 2.4: Docker Compose stack (`02-docker/production/`)

**Sơ đồ kiến trúc các service và cách giao tiếp:**

```text
                        (External: Host port 80 / 443)
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │       nginx (nginx:alpine)     │
                      │  Reverse Proxy, Rate Limit,    │
                      │  Security Headers              │
                      └───────────────┬───────────────┘
                                      │ Docker network: internal
                                      │ proxy_pass http://agent:8000
                                      ▼
                      ┌───────────────────────────────┐
                      │  agent (FastAPI + uvicorn x2)  │
                      │  Internal port 8000 (không     │
                      │  expose trực tiếp ra ngoài)    │
                      └───────┬───────────────┬───────┘
                              │               │
         REDIS_URL=           │               │  QDRANT_URL=
         redis://redis:6379/0 │               │  http://qdrant:6333
                              ▼               ▼
              ┌────────────────────┐     ┌────────────────────────┐
              │ redis:7-alpine     │     │ qdrant/qdrant:v1.9.0   │
              │ Cache & Rate Limit │     │ Vector DB cho RAG      │
              │ Vol: redis_data    │     │ Vol: qdrant_data       │
              └────────────────────┘     └────────────────────────┘
```

- **Các service được khởi động:** `redis` (healthcheck `redis-cli ping`), `qdrant` (healthcheck TCP port 6333), `agent` (`depends_on` cả `redis` và `qdrant` ở trạng thái `service_healthy`), và `nginx` (cổng vào duy nhất mở port 80/443 ra ngoài).
- **Cách giao tiếp:** Tất cả cùng nằm trong Docker bridge network `internal`, gọi nhau bằng **tên service qua Docker DNS** (`agent:8000`, `redis:6379`, `qdrant:6333`). Dữ liệu Redis và Qdrant lưu bền vững qua named volumes (`redis_data`, `qdrant_data`).

**Kết quả chạy thực tế (`docker compose -p k5-day14-docker up -d --build`):**

```text
NAME                       IMAGE                   SERVICE   STATUS                           PORTS
k5-day14-docker-agent-1    k5-day14-docker-agent   agent     Up 1 second (health: starting)   8000/tcp
k5-day14-docker-nginx-1    nginx:alpine            nginx     Up 1 second                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1   qdrant/qdrant:v1.9.0    qdrant    Up 12 seconds (healthy)          6333-6334/tcp
k5-day14-docker-redis-1    redis:7-alpine          redis     Up 12 seconds (healthy)          6379/tcp
```

**Kết quả test qua Nginx (`http://localhost`):**

```http
--- GET http://localhost/health ---
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":0.4,"version":"2.0.0","timestamp":"2026-11-25T11:16:59.329543"}

--- GET http://localhost/ready ---
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json

{"ready":true}

--- POST http://localhost/ask ---
HTTP/1.1 200 OK
Server: nginx
Content-Type: application/json
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

*(Sau khi kiểm chứng đã dọn stack bằng `docker compose -p k5-day14-docker down -v` để trả lại cổng 80 và giải phóng tài nguyên).*

---

## Part 3: Cloud Deployment

### Exercise 3.1: Deploy Production Agent (`06-lab-complete/`) lên Railway
- **Nền tảng chính:** Railway (deploy trực tiếp từ thư mục `06-lab-complete/` dùng `Dockerfile` + `railway.toml`, kết nối Redis trên Railway)
- **Public URL:** *(Đang chờ hoàn tất deploy trên Railway — sẽ điền ngay sau khi Generate Domain)*
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png` *(chi tiết lệnh test nằm trong `DEPLOYMENT.md`)*

---

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) | Tại sao khác nhau? |
| :--- | :--- | :--- | :--- |
| **Định dạng & phạm vi** | File TOML cấu hình cho **1 service đơn lẻ** (`[build]`, `[deploy]`) | File YAML **Infrastructure as Code (IaC)** khai báo **cả stack nhiều service** (`services:` gồm web + redis/database) | Railway quản lý topology multi-service trực quan trên Project Canvas, còn Render Blueprint định nghĩa toàn bộ hạ tầng bằng file YAML để sync tự động từ Git |
| **Cách build & runtime** | Khai báo `builder = "DOCKERFILE"` (hoặc `"NIXPACKS"`) và `dockerfilePath` | Khai báo `type: web`, `runtime: docker` (hoặc `python` với `buildCommand`/`startCommand`), chọn sẵn `region` và `plan` | Render yêu cầu khai báo rõ gói (`free`/`starter`) và vùng (`singapore`) ngay trong Blueprint; Railway chọn tài nguyên linh hoạt theo usage |
| **Health check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | `healthCheckPath: /health`, `autoDeploy: true` | Railway cho chỉnh chi tiết chính sách retry khi crash ngay trong TOML; Render quản lý restart tự động ở nền tảng |
| **Quản lý biến môi trường & Secrets** | Không khai báo env/secret trong `railway.toml` — toàn bộ đặt trên Railway Dashboard hoặc `railway variables set` và nối service qua reference (`${{Redis.REDIS_URL}}`) | Khai báo trực tiếp danh sách `envVars:` trong `render.yaml`, dùng `generateValue: true` (tự sinh key) hoặc `sync: false` (nhập tay trên dashboard, không commit secret) | Cả hai đều tuân thủ 12-Factor (không lưu secret plaintext trong Git), nhưng Render mô tả schema biến môi trường ngay trong file IaC |

---

### Exercise 3.3: Phân tích CI/CD Pipeline trên GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Pipeline định nghĩa trong `cloudbuild.yaml` và `service.yaml` tự động hóa toàn bộ quy trình triển khai khi có commit mới lên nhánh `main` qua 4 bước tuần tự (`waitFor`):
1. **Test (`test`):** Dùng container `python:3.11-slim` cài `requirements.txt` + `pytest` và chạy toàn bộ test suite (`pytest tests/`); nếu có test fail thì dừng pipeline ngay.
2. **Build (`build`):** Build Docker image gắn đồng thời 2 tag (`:$COMMIT_SHA` để truy vết từng bản phát hành và `:latest`) có tận dụng `--cache-from` để tăng tốc build.
3. **Push (`push`):** Đẩy tất cả các tag image vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`deploy`):** Gọi `gcloud run deploy` triển khai image `:$COMMIT_SHA` lên Cloud Run khu vực `asia-southeast1`, mở public endpoint, tự động scale từ `min-instances=1` (tránh cold start) đến `max-instances=10` (concurrency 80 req/instance, 1 CPU / 512Mi RAM trong `service.yaml`), cấu hình `livenessProbe` (`/health`) + `startupProbe` (`/ready`) và inject secret an toàn từ **Google Secret Manager** (`secretKeyRef` / `--set-secrets`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/`)

**Trả lời câu hỏi phân tích `develop/app.py`:**
- **API key được kiểm tra ở đâu?** Trong dependency `verify_api_key()` (dòng 39–54) đọc header `X-API-Key` thông qua `APIKeyHeader(name="X-API-Key", auto_error=False)`, sau đó inject vào endpoint `POST /ask` bằng `Depends(verify_api_key)` (dòng 70). Các endpoint `/health` và `/` để public để platform kiểm tra sức khỏe.
- **Điều gì xảy ra nếu thiếu hoặc sai key?**
  - Thiếu header `X-API-Key` → trả `401 Unauthorized` (`Missing API key`).
  - Sai giá trị key → trong bản `develop` trả `403 Forbidden` (`Invalid API key`) *(lưu ý ở Part 6, hợp đồng chuẩn yêu cầu cả thiếu và sai key đều trả `401`)*.
- **Làm sao xoay vòng (rotate) API key không gây gián đoạn?**
  - Lưu key trong biến môi trường/Secret Manager thay vì code; hỗ trợ đồng thời 2 key (key cũ + key mới) trong giai đoạn chuyển tiếp (`ALLOWED_API_KEYS`), cập nhật client sang key mới rồi mới thu hồi key cũ.

**Output `curl -i` thực tế (chạy với `AGENT_API_KEY=secret-key-123`):**

```http
--- Không có API key ---
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

--- Sai API key ---
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

--- Đúng API key ---
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

---

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

**Phân tích cơ chế (`auth.py` và `rate_limiter.py`):**
- **Luồng JWT (`auth.py`):** Client gửi `username`/`password` đến `POST /auth/token` → server xác thực và ký JWT bằng thuật toán `HS256` kèm payload (`sub`, `role`, `iat`, `exp` 60 phút). Khi gọi `/ask` với `Authorization: Bearer <token>`, server chỉ cần xác minh chữ ký và thời hạn bằng `SECRET_KEY` (stateless, không cần truy vấn DB mỗi request).
- **Thuật toán Rate Limiting (`rate_limiter.py`):** Dùng **Sliding Window** (cửa sổ trượt 60 giây, lưu hàng đợi `deque` các timestamp của từng `user_id`, liên tục bỏ các timestamp cũ hơn `now - 60s`).
- **Giới hạn & cách phân quyền theo role (`app.py`, dòng 141):**
  - User thường (`student`, `role="user"`): `rate_limiter_user` → **10 requests/phút**.
  - Admin (`teacher`, `role="admin"`): `rate_limiter_admin` → **100 requests/phút** (hoặc có thể bỏ qua bước kiểm tra limiter nếu `role == "admin"`).

**Output `curl -i` thực tế (đã che token):**

```http
--- 1) POST /ask không có token (401) ---
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

--- 2) POST /auth/token (student / demo123) ---
Token nhận được (đã che): eyJhbGciOiJIUzI1Ni...38B6x8U0

--- 3) Vòng lặp 12 request liên tiếp với token của student (giới hạn 10 req/phút) ---
>>> Request #1:
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY

{"question":"Test 1","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
>>> Request #2..#10 -> HTTP 200 OK (requests_remaining giảm dần về 0)

>>> Request #11 (chạm ngưỡng rate limit):
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795605727
retry-after: 59
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
>>> Request #12 -> HTTP 429 Too Many Requests

--- 4) Kiểm tra GET /me/usage sau 10 request thành công ---
HTTP/1.1 200 OK
content-type: application/json

{"user_id":"student","date":"2026-11-25","requests":10,"input_tokens":40,"output_tokens":296,"cost_usd":0.000184,"budget_usd":1.0,"budget_remaining_usd":0.999816,"budget_used_pct":0.0}
```

---

### Exercise 4.4: Cost Guard — Bảo vệ ngân sách LLM

- **Tại sao cần cả Rate Limiting lẫn Cost Guard?**
  - **Rate Limiting** bảo vệ **tốc độ gọi và hạ tầng** (ngăn spam hàng trăm request/phút làm sập server hoặc hết quota RPM của nhà cung cấp).
  - **Cost Guard** bảo vệ **ngân sách tiền thật** (một người dùng vẫn có thể gọi rất chậm đúng rate limit nhưng gửi prompt cực dài hoặc sinh output lớn làm tốn nhiều token; Cost Guard tính tổng chi phí theo input/output token và chặn với mã **`402 Payment Required`** khi chạm trần ngân sách).
- **Cách triển khai chuẩn Production với Redis:**
  - Trong `04-api-gateway/production/cost_guard.py`, bản demo đang lưu `self._records` trong RAM (sẽ mất khi restart và không đồng bộ giữa nhiều container).
  - Ở production (và Part 6), chi phí được lưu trên **Redis** theo khóa chu kỳ (`budget:{user_id}:{YYYY-MM}` hoặc `cost:daily:{YYYY-MM-DD}`):
    1. **Trước khi gọi LLM (`check_budget`):** Đọc tổng chi phí hiện tại từ Redis (`float(r.get(key) or 0)`). Nếu đã `>= budget_limit`, lập tức từ chối với **`HTTP 402`** để không phát sinh thêm chi phí LLM.
    2. **Sau khi gọi LLM (`record_cost`):** Tính chi phí thực tế từ `input_tokens` và `output_tokens` (`(in/1000)*price_in + (out/1000)*price_out`), dùng lệnh nguyên tử `r.incrbyfloat(key, cost)` để cộng dồn (tránh race condition giữa nhiều worker) và đặt `r.expire(key, ttl)` để tự động reset khi sang chu kỳ ngày/tháng mới.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health Check (`/health`) vs Readiness Check (`/ready`)

- **Liveness Probe (`GET /health`)** trả lời câu hỏi: *"Process/container còn sống không?"*
  - Phải luôn trả `200 OK` khi process đang chạy bình thường (không phụ thuộc vào Redis/DB bên ngoài). Nếu `/health` thất bại hoặc timeout, platform (Docker, Railway, Kubernetes) sẽ **restart container**.
- **Readiness Probe (`GET /ready`)** trả lời câu hỏi: *"Instance đã sẵn sàng nhận traffic từ người dùng chưa?"*
  - Kiểm tra kết nối tới các dependency thiết yếu (như `redis.ping()`, trạng thái khởi tạo model `_is_ready`). Nếu chưa sẵn sàng hoặc mất kết nối Redis thì trả **`503 Service Unavailable`**. Khi `/ready` fail, Load Balancer sẽ **tạm ngừng định tuyến traffic** vào instance đó (nhưng **không restart container**), tránh vòng lặp restart vô ích khi chính Redis mới là bên gặp sự cố.

**Kết quả test thực tế trên `05-scaling-reliability/develop/app.py`:**

```http
--- GET /health ---
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":0.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T11:25:45.944949+00:00","checks":{"memory":{"status":"ok","note":"psutil not installed"}}}

--- GET /ready ---
HTTP/1.1 200 OK
content-type: application/json

{"ready":true,"in_flight_requests":1}
```

---

### Exercise 5.2: Graceful Shutdown (`SIGTERM`)

- Khi thực hiện rolling deploy hoặc `docker stop`, orchestrator gửi tín hiệu **`SIGTERM`** (signal 15) trước khi ép tắt bằng `SIGKILL`.
- Ứng dụng chuẩn phải: (1) chuyển `_is_ready = False` để ngừng nhận request mới, (2) chờ các request đang xử lý (`in-flight`) hoàn thành, (3) đóng kết nối sạch sẽ, và (4) thoát với exit code `0`.

**Kết quả test thực tế (gửi `kill -TERM` ngay lúc `POST /ask?question=Long+task` đang chạy):**

```text
--- Phản hồi của request đang chạy (in-flight) ---
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

--- Server log ---
INFO:     Shutting down
INFO:     127.0.0.1:42718 - "POST /ask?question=Long+task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 18:25:49,111 INFO 🔄 Graceful shutdown initiated...
2026-11-25 18:25:49,111 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [668]
```

→ Request đang chạy **vẫn hoàn thành và trả `200 OK`** trước khi tiến trình đóng hẳn, không bị cắt ngang kết nối.

---

### Exercise 5.3, 5.4 & 5.5: Stateless Design, Load Balancing (3 instances) & `test_stateless.py`

- **Tại sao lưu state trong RAM bị hỏng khi scale ngang?**
  - Khi chạy nhiều instance sau Load Balancer (Nginx round-robin), request 1 của user có thể vào `instance-1`, còn request 2 vào `instance-2`. Nếu lịch sử hội thoại hoặc bộ đếm rate limit lưu trong biến `dict` của RAM từng process, `instance-2` sẽ không có dữ liệu của request 1, và toàn bộ state cũng mất sạch mỗi khi container restart.
  - **Giải pháp (`05-scaling-reliability/production/app.py`):** Thiết kế **stateless** — toàn bộ session và conversation history lưu tập trung vào **Redis** (`session:{session_id}` với TTL 3600s).

**Chạy stack với 3 instance Agent + Redis + Nginx (`05-scaling-reliability/production/`):**

```bash
touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
docker compose -p k5-day14-scaling ps
python test_stateless.py
```

**Trạng thái container (`docker compose ps`):**

```text
NAME                       IMAGE                    SERVICE   STATUS                           PORTS
k5-day14-scaling-agent-1   k5-day14-scaling-agent   agent     Up 1 second (health: starting)   8000/tcp
k5-day14-scaling-agent-2   k5-day14-scaling-agent   agent     Up 1 second (health: starting)   8000/tcp
k5-day14-scaling-agent-3   k5-day14-scaling-agent   agent     Up 1 second (health: starting)   8000/tcp
k5-day14-scaling-nginx-1   nginx:alpine             nginx     Up 1 second                      0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   redis:7-alpine           redis     Up 12 seconds (healthy)          6379/tcp
```

**Output thực tế của `python test_stateless.py` (gọi `POST http://localhost:8080/chat`):**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 7d9bc874-9c2c-4118-8663-b54658a14a01

Request 1: [instance-2932dc]  Q: What is Docker?
Request 2: [instance-0e17c1]  Q: Why do we need containers?
Request 3: [instance-4747e0]  Q: What is Kubernetes?
Request 4: [instance-2932dc]  Q: How does load balancing work?
Request 5: [instance-0e17c1]  Q: What is Redis used for?

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-2932dc', 'instance-0e17c1', 'instance-4747e0'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Kiểm chứng Nginx Load Balancing qua header `X-Served-By` (6 lần gọi `/health` liên tiếp):**

```text
X-Served-By: 172.20.0.5:8000 -> instance-2932dc (redis_connected: true)
X-Served-By: 172.20.0.3:8000 -> instance-0e17c1 (redis_connected: true)
X-Served-By: 172.20.0.4:8000 -> instance-4747e0 (redis_connected: true)
X-Served-By: 172.20.0.5:8000 -> instance-2932dc (redis_connected: true)
X-Served-By: 172.20.0.3:8000 -> instance-0e17c1 (redis_connected: true)
X-Served-By: 172.20.0.4:8000 -> instance-4747e0 (redis_connected: true)
```

**Giải thích kết quả:** Nginx phân phối đều request theo thuật toán **round-robin** tới cả 3 container (`instance-2932dc`, `instance-0e17c1`, `instance-4747e0`). Dù 5 câu hỏi trong cùng session `7d9bc874-9c2c-4118-8663-b54658a14a01` rơi vào 3 instance khác nhau, khi gọi `GET /chat/{session_id}/history`, toàn bộ **10 tin nhắn** (5 user + 5 assistant) vẫn nguyên vẹn vì tất cả đều đọc/ghi chung trên **Redis**. *(Sau khi hoàn tất đã chạy `docker compose -p k5-day14-scaling down -v` để dọn sạch stack và trả cổng 8080).*

---

## Part 6: Output `check_production_ready.py`

Chạy kiểm tra đầy đủ (3 lớp: kiểm tra tĩnh + runtime với Redis + build/run/stop Docker image) trong thư mục `06-lab-complete/` trên Ubuntu WSL2 (`python check_production_ready.py`):

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

**Một số chỉ số đo thực tế từ script chấm:**
- Kích thước Docker image (multi-stage `python:3.11-slim`, user non-root `appuser`): **`238 MB`** (`< 500 MB`, build trong `39s`).
- Rate limiting (Redis Sorted Set sliding window): trả **`429`** sau đúng `5` request khi `RATE_LIMIT_PER_MINUTE=5`, vẫn giữ nguyên trạng thái `429` sau khi restart agent.
- Cost guard (Redis `INCRBYFLOAT`): trả **`402`** khi vượt ngân sách.
- Structured logging: `17` dòng log JSON hợp lệ.
- Graceful shutdown: `SIGTERM` khi đang có request trả `200` + `exit code 0`; `docker stop` tắt êm với **`exit code 0` trong `1.0s`** (`< 10s`).

---

## AI Log

*(Ghi nhận minh bạch quá trình sử dụng AI theo quy định `RULES.md`)*

1. **CP0 — Thiết lập môi trường WSL2 & Docker:**
   - **Đã hỏi AI:** Kiểm tra tài nguyên máy, cài đặt Ubuntu 24.04 trên WSL2 (ổ `E:`), tạo `.wslconfig`, cài `venv` Python 3.12 và cấu hình kết nối Docker Desktop WSL Integration.
   - **Đã nhận & tự kiểm tra:** Mình trực tiếp mở Docker Desktop và bật WSL Integration cho `Ubuntu-24.04`, sau đó xác nhận `os.name == posix`, `Python 3.12.3` và `docker run --rm hello-world` chạy thành công trong Ubuntu.
2. **Checkpoint 1 — Part 1 (Localhost vs Production):**
   - **Đã hỏi AI:** Hỗ trợ chạy kiểm chứng 2 bản `develop` và `production` trong `01-localhost-vs-production/`, đối chiếu các anti-patterns theo chuẩn 12-Factor và tổng hợp kết quả vào `MISSION_ANSWERS.md`.
   - **Đã nhận & tự kiểm tra:** Đã đối chiếu trực tiếp từng dòng code trong `develop/app.py`, `production/app.py`, `production/config.py` và các output `curl` thực tế chạy trên máy.
3. **Checkpoint 2 — Part 2 (Docker Containerization):**
   - **Đã hỏi AI:** Hỗ trợ build 2 Docker image (`my-agent:develop` và `my-agent:advanced`), đo kích thước thực tế, dựng stack Docker Compose (`-p k5-day14-docker`) và test qua Nginx.
   - **Đã nhận & tự kiểm tra:** Toàn bộ số đo dung lượng (`1.67 GB` vs `240 MB`, giảm `85.6%`) và output HTTP từ container/Nginx đều lấy trực tiếp từ kết quả chạy thật trên Docker WSL2 của máy.
4. **Checkpoint 3 — Part 4 (API Security):**
   - **Đã hỏi AI:** Hỗ trợ chạy kiểm chứng API Key auth (`develop`), JWT auth + Rate Limiting (`production`) và tổng hợp phân tích Cost Guard vào `MISSION_ANSWERS.md`.
   - **Đã nhận & tự kiểm tra:** Đã chạy thật các kịch bản `401` / `403` / `200` / `429` và `/me/usage`, đã che JWT token trước khi lưu vào tài liệu.
5. **Checkpoint 4 — Part 5 (Scaling & Reliability):**
   - **Đã hỏi AI:** Hỗ trợ chạy kiểm chứng `/health`, `/ready`, `SIGTERM` trên bản `develop`, dựng stack 3 instance Agent + Redis + Nginx (`-p k5-day14-scaling`) và chạy `test_stateless.py`.
   - **Đã nhận & tự kiểm tra:** Đã xác nhận request in-flight vẫn trả `200 OK` khi gửi `SIGTERM`, và 5 request trong cùng session được Nginx chia đều qua cả 3 instance (`instance-2932dc`, `instance-0e17c1`, `instance-4747e0`) nhưng vẫn bảo toàn đủ 10 tin nhắn trên Redis.
6. **Checkpoint 5 — Part 6 (Final Project `06-lab-complete/`):**
   - **Đã hỏi AI:** Hỗ trợ thiết kế và hoàn thiện các module `app/` (`config.py`, `redis_client.py`, `auth.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`) cùng `Dockerfile` multi-stage, `.dockerignore`, `docker-compose.yml`, `.env.example`, `railway.toml`, `render.yaml`.
   - **Đã nhận & tự kiểm tra:** Đã chạy nguyên bản `python check_production_ready.py` (không chỉnh sửa script chấm) trong Ubuntu WSL2 với Docker, đạt trọn vẹn **`PASS 12/12` (`43/43 checks passed`)**, image `238 MB`, `docker stop` tắt êm trong `1.0s`.
