# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được trích trực tiếp từ các file JSON trong `reports/`, file CSV trong `benchmark-results/` và ảnh chụp thực tế trong `screenshots/`.

**Họ tên:** Trần Đức Mạnh (`2A202603615`)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11 + WSL2 Ubuntu 24.04 (`os.name = posix`), CPU AMD Ryzen 7 6800H (16 threads; WSL2 giới hạn 6 CPU / 6 GB RAM), Python 3.12.3, Docker Desktop 29.9.3 / Compose v5.7.0

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Đảm bảo 95% người dùng nhận phản hồi dưới nửa giây (phản hồi mượt trong hội thoại), khớp ngưỡng mặc định của `load_test.py` và chặt hơn ngưỡng alert (`> 1s` trong 2 phút) để tránh báo động giả |
| Error rate `/ask` | `< 2.0 %` | Cho phép error budget 2% để hấp thụ lỗi ngẫu nhiên từ upstream LLM (`MOCK_ERROR_RATE=0.01`), chặt hơn ngưỡng alert critical (`> 5%` trong 1 phút) |
| Accuracy trên golden dataset | `≥ 85 %` (mục tiêu sau tối ưu KB: `100 %`) | Đảm bảo chất lượng trả lời tối thiểu trước khi merge PR qua CI quality gate (`.github/workflows/eval.yml`), đồng thời cấm tuyệt đối regression so với baseline |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 requests, `MOCK_SLOW_RATE=0.03`)

*(Số liệu khớp 100% với `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.62 | 187.6 | 214.9 | 1687.8 | 1.00% | PASS |
| 10 | 39.78 | 190.3 | 220.9 | 1703.0 | 1.33% | PASS |
| 50 | 120.30 | 195.0 | 244.9 | 279.9 | 1.00% | PASS |
| 100 | 62.39 | 362.8 | 2894.9 | 3155.5 | 1.00% | FAIL |

**Nhận xét:** RPS **không tăng tuyến tính** theo concurrency:
- Từ concurrency `1 → 10 → 50`, RPS tăng mạnh từ `4.62 → 39.78 → 120.30 req/s` trong khi `p95` vẫn giữ ổn định (`214.9 → 220.9 → 244.9 ms`, đều đạt SLO ≤ 500 ms) vì agent dùng `async/await` (I/O-bound, chờ `asyncio.sleep` không block event loop).
- Tuy nhiên khi nâng lên `concurrency = 100` trên 1 tiến trình uvicorn đơn, hệ thống chạm điểm bão hòa (saturation) ở hàng đợi socket/event loop + JSON serialization/logging: thông lượng **tụt ngược xuống còn `62.39 req/s`**, `p50` gần gấp đôi (`362.8 ms`), còn `p95` vọt lên **`2894.9 ms`** (vi phạm nặng SLO). Điều này chứng minh cần giới hạn concurrency mỗi instance và scale ngang (horizontal scaling).

### 2.2 Tail latency (agent v2, 300 requests, `concurrency=20`)

*(Số liệu khớp 100% với `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 188.2 | 215.4 | 223.0 |
| 0.03 (mặc định) | 235.9 | 226.3 | 1693.5 |
| 0.1 | 350.3 | 1683.0 | 1715.1 |

**Nhận xét:**
- **Chỉ số nhạy nhất với request chậm là các percentile cao (`p99`, rồi đến `p95`):**
  - Khi `MOCK_SLOW_RATE` tăng từ `0 → 0.03` (chỉ 3% request chậm ~1.5s), `avg` chỉ nhích nhẹ `+47.7 ms` (`188.2 → 235.9 ms`) và `p95` gần như đứng yên (`226.3 ms`), nhưng **`p99` nhảy vọt gấp 7.6 lần lên `1693.5 ms`**.
  - Khi `MOCK_SLOW_RATE = 0.1` (10% > 5% request chậm), **`p95` lập tức vọt lên `1683.0 ms`** (FAIL SLO), trong khi `avg` mới chỉ là `350.3 ms` — trông vẫn thấp hơn ngưỡng 500 ms!
- **Vì sao SLO không nên đặt theo average?** Giá trị trung bình bị 90–97% request nhanh kéo xuống nên **che giấu trải nghiệm tệ ở đuôi phân phối (tail latency)**. Đặt SLO theo `p95`/`p99` phản ánh trung thực trải nghiệm xấu nhất mà nhóm người dùng thật phải chịu đựng.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Số liệu khớp 100% với `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` trên 23 câu của `golden_dataset.jsonl`)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.7 | 109.3 | 113.7 |
| Tổng cost (USD) | $0.000412 | $0.000764 | $0.000790 |
| Cost / câu đúng (USD) | $0.00041235 | $0.00003639 | $0.00003436 |
| Quality gate | FAIL | PASS (≥ 80%, 0 regression) | PASS (≥ 100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`) giải thích sự khác nhau giữa API key cố định và JWT token có chữ ký số + thời điểm hết hạn |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes", "autoscal"], ...)` vào `KNOWLEDGE_BASE` mô tả Kubernetes HPA scale số pod dựa trên CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi) |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- **Trade-off thật của RAG:** Agent v2 thêm bước tìm tài liệu (`retrieval`, ~20 ms) và nhồi ngữ cảnh vào prompt nên **tốn gần gấp đôi token/câu** (`109.3 → 113.7` so với `57.7` của v1), tổng chi phí tăng gần gấp đôi (`$0.000764` so với `$0.000412`), và latency `p95` tăng thêm ~`33.8 ms` (`188.4 → 222.2 ms`).
- **Đổi lại hoàn toàn xứng đáng:** Độ chính xác tăng vọt từ **`4.3%` → `91.3%` → `100.0%`**, giúp chỉ số **`cost / câu trả lời đúng` giảm tới ~12 lần** (từ `$0.00041235` xuống `$0.00003436`). Điều này cho thấy khi so sánh hai phiên bản AI, *"chi phí trên mỗi câu trả lời đúng"* có ý nghĩa hơn nhiều so với *"chi phí trên mỗi request"*.
- **CI Quality Gate (Exercise 7.3):** Đã tạo workflow [`.github/workflows/eval.yml`](.github/workflows/eval.yml) chạy tự động trên mỗi `pull_request`: khởi động agent v2 và chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`. Vì `run_eval.py` trả **exit code `1`** bất cứ khi nào `accuracy < --min-accuracy` hoặc xuất hiện câu bị regression so với baseline, GitHub Actions sẽ đánh dấu job **FAIL** và chặn merge PR trước khi code xấu lọt lên production.

**Exercise 7.1 — Prometheus metrics & Cardinality:**
- Đã xác nhận 3 loại metric trên `/metrics`: Counter (`http_requests_total`), Gauge (`agent_in_flight_requests`), Histogram (`http_request_duration_seconds`), và đã bổ sung thêm Histogram `agent_question_length_chars` đo phân bố độ dài câu hỏi trong `develop/app.py`.
- Middleware `observe_requests` dùng `route.path` (template) thay vì URL thật để tránh **cardinality explosion**: nếu dùng `request.url.path`, khi bot quét hàng nghìn URL rác (`/wp-admin`, `/.env`, `/random...`) sẽ sinh ra hàng nghìn time series mới làm Prometheus cạn RAM.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Exercise 7.4 (Đọc dashboard Grafana & Nginx)

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception` / HTTP 503) — [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với **4/4 alert đang `FIRING`** cùng lúc — [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png)

**Trả lời câu hỏi Exercise 7.4 (từ dữ liệu đo thực tế trên Prometheus/Grafana):**
1. **p95 và avg trên Prometheus:** Trong cửa sổ tải 5 phút, `avg = 233.9 ms` còn `p95 = 293.9 ms` (và ở cuối đợt tải khi có request chậm lọt vào cửa sổ 1 phút, p95 chạm `1.70 s`). Khoảng cách giữa `avg` và `p95/p99` phản ánh rõ **tail latency** (~3% request chậm từ upstream LLM bị trung bình che giấu).
2. **Nginx có chia đều traffic giữa các instance không?** Có — Prometheus đo `sum by (instance) (rate(http_requests_total{job="agent",route="/ask"}[5m]))` cho thấy 2 instance mới thêm khi scale (`172.20.0.8:8000` và `172.20.0.9:8000`) nhận lưu lượng cân bằng tuyệt đối (**`8.01 req/s`** và **`8.01 req/s`**) nhờ cơ chế round-robin + Docker DNS `resolve` mỗi 10 giây của Nginx.
3. **Vì sao input tokens/s lớn hơn output tokens/s?** Prometheus ghi nhận **`input = 2065.4 tokens/s`** so với **`output = 1080.3 tokens/s`** (gần gấp đôi) vì Agent v2 (RAG) phải gửi kèm `SYSTEM_PROMPT` + tài liệu trích xuất từ `KNOWLEDGE_BASE` + câu hỏi của người dùng trong mỗi prompt gửi tới LLM, trong khi câu trả lời đầu ra ngắn gọn hơn.
4. **`curl -i http://localhost:8080/metrics` trả về gì và vì sao?** Trả về **`HTTP/1.1 404 Not Found`** từ Nginx (`nginx/1.28.3`). Lý do: `nginx/nginx.conf` cấu hình rõ `location = /metrics { return 404; }` để **không public endpoint `/metrics` ra Internet** (tránh lộ thông tin nội bộ như lưu lượng, chi phí, route, phiên bản hệ thống); chỉ Prometheus trong mạng Docker nội bộ mới scrape trực tiếp `agent:8000/metrics`.

### 4.2 Thí nghiệm "phá hệ thống" & Unit test Alert Rules

- **Unit test alert rules (`promtool test rules /p/alert_rules_test.yml`):** `SUCCESS` (toàn bộ 4 alert rules vượt qua unit test).
- **Kết quả thí nghiệm Chaos (chạy đồng thời với Locust 30 users, đo thời gian thực từ Prometheus `/api/v1/alerts`):**

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, `critical`) | **85 giây** (~1m25s) | *Golden Signals → Error rate* (chuyển đỏ > 5%) & *Requests/s theo status code* (`503`) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, `warning`) | **145 giây** (~2m25s) | *Golden Signals → Latency p95* (đỏ > 1s) & *Latency /ask — p50/p95/p99* |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, `warning`) | **~175 giây** (~2m55s; pending từ 55s) | *Golden Signals → LLM cost* & *LLM → Cost USD/giờ* (vượt `$2/giờ`) |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (`for: 30s`, `critical`) | **40 giây** | *Golden Signals → Instances up* (tụt 1 instance); `up{job="agent"} == 0` |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | N/A | *LLM → Retrieval hit ratio* mất dữ liệu, *tokens/s* giảm, bảng *agent_info* đổi sang `v1` |

**Phân tích bổ sung (Thí nghiệm D & E):**
- **Thí nghiệm E không làm alert nào firing — cách phát hiện trên production:** Giám sát hạ tầng (Prometheus/Grafana) chỉ thấy HTTP 200, latency thấp và chi phí giảm — mọi đèn đều xanh dù chất lượng câu trả lời đã rơi từ 100% xuống 4.3%. Để bắt sự cố chất lượng AI này cần: (1) **CI Eval Quality Gate** chạy `golden_dataset` trước mọi lần deploy (`.github/workflows/eval.yml`), (2) **Online evaluation** (lấy mẫu traffic thật chấm bằng LLM-as-judge hoặc đối chiếu retrieval hit ratio bất thường giảm về 0), và (3) theo dõi **phản hồi người dùng** (thumbs up/down, tỉ lệ hỏi lại).
- **Thí nghiệm D (`docker pause` và lỗi 504 ở Nginx):** Phải dùng `docker pause` thay vì `docker stop` vì container bị stop sẽ biến mất khỏi Docker DNS nên Prometheus không báo `up == 0`; còn container bị pause vẫn nằm trong DNS nhưng treo không phản hồi scrape. Ngoài ra, nếu request bị Nginx timeout trả `504 Gateway Timeout`, panel Error rate của agent vẫn xanh vì request chưa bao giờ đi qua/hoàn tất ở tầng agent — do đó production cần giám sát thêm metrics ở tầng **Nginx/Load Balancer** và **Synthetic Monitoring** từ bên ngoài.

### 4.3 Debug bằng trace (Jaeger + JSON Log)

**1. Trace chậm nhất tìm được (`screenshots/jaeger-slow-trace.png`):**
- `trace_id`: `6757e610c2009b08131ede098fdb54e5`
- Tổng thời gian (`POST /ask`): **`1722.6 ms`**
- Phân rã từng span:
  - `POST /ask`: `1722.6 ms`
  - `agent.run`: `1720.8 ms`
  - `agent.retrieve_context`: `25.4 ms` (`1.5%` — bước retrieval chạy rất nhanh)
  - **`chat mock-llm-small`: `1695.1 ms` (`98.4%`)** → nút thắt nằm hoàn toàn ở lời gọi LLM upstream, không phải code của agent.
- Dòng log JSON tương ứng (khớp `trace_id` từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-25T14:23:19.888851+00:00", "level": "INFO", "service": "observable-agent", "instance": "98a31d1f71e4", "event": "llm_call", "trace_id": "6757e610c2009b08131ede098fdb54e5", "span_id": "e870077d62e6bff7", "request_id": "16d995ff2c66", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1695.3}
```

**2. Trace lỗi tìm được (`screenshots/jaeger-error-trace.png`):**
- `trace_id`: `ae7ae225b6ef174d761c6176e0d8ecd1` (`POST /ask` trả HTTP `503`, tổng thời gian `98.8 ms`; span `chat mock-llm-small` lỗi ở `77.9 ms` với `Upstream LLM error: 503 Service Unavailable (mock)`).
- Dòng log JSON tương ứng:

```json
{"ts": "2026-11-25T14:21:40.963599+00:00", "level": "INFO", "service": "observable-agent", "instance": "9377f96af687", "event": "llm_error", "trace_id": "ae7ae225b6ef174d761c6176e0d8ecd1", "span_id": "88fac8c815643ca3", "request_id": "bd893594041e", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Số liệu khớp 100% với `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`)*

**Bảng tổng hợp (Aggregated — gồm `POST /ask` và `GET /health`):**

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.55 | 190 | 240 | 1700 | 88 / 7829 (1.12%) |
| 3 | 66.17 | 190 | 220 | 1700 | 79 / 7904 (1.00%) |

*(Riêng endpoint `POST /ask`: 1 instance đạt `59.46 req/s`, `p50=190ms`, `p95=250ms`, `p99=1700ms`, `88/7102` fails; 3 instances đạt `60.14 req/s`, `p50=190ms`, `p95=230ms`, `p99=1700ms`, `79/7184` fails).*

**Giải thích kết quả:** Scale từ 1 lên 3 instance chỉ cải thiện nhẹ `p95` (`240 → 220 ms` tổng hợp, `250 → 230 ms` cho `/ask`), trong khi **RPS gần như không đổi (`65.55 → 66.17 req/s`)** và **`p99` giữ nguyên `1700 ms`**:
- **Nút thắt không nằm ở CPU của Agent:** Ứng dụng FastAPI dùng `async/await` xử lý 100 user có `wait_time` khá nhẹ nhàng ngay trên 1 container (`0.5 CPU`), nên ở mức tải 100 users này 1 instance chưa bị bão hòa CPU.
- **Nút thắt thật nằm ở độ trễ I/O phía LLM upstream (`chat mock-llm-small`):** Mỗi request đều phải chờ phản hồi từ LLM (cơ bản ~150–190ms và ~3% rơi vào tail latency ~1700ms), và toàn bộ `88` / `79` lỗi đều là HTTP `503` do `MOCK_ERROR_RATE=0.01` từ upstream LLM.
- **Giá trị thực tế của việc scale lên 3 instance:** Giảm tải xuống còn 1/3 trên mỗi container (tạo headroom chịu tải cao hơn rất nhiều khi traffic tăng đột biến) và đảm bảo **High Availability** (khi 1 instance gặp sự cố hoặc restart, 2 instance còn lại vẫn phục vụ bình thường qua Nginx).

---

## 6. Kết luận

- **3 điều quan trọng nhất học được về benchmark & observability:**
  1. **Không bao giờ tin vào latency trung bình (average) hay cảm tính:** Phải đo bằng percentile (`p95`/`p99`) và đặt SLO rõ ràng để phát hiện tail latency; đồng thời chỉ số `cost / câu trả lời đúng` phản ánh đúng hiệu quả kinh tế của RAG hơn `cost / request`.
  2. **Ba trụ cột Observability (Metrics + Traces + Logs) bổ trợ không thể tách rời:** Grafana/Prometheus cho biết *có sự cố gì*, Jaeger chỉ ra *chậm hay lỗi ở đúng span nào* (`98.4%` ở LLM upstream), và `trace_id` trong JSON log nối thẳng sang chi tiết sự kiện cụ thể.
  3. **Giám sát hạ tầng không thay thế được đánh giá chất lượng AI (Eval):** Hệ thống có thể xanh 100% về HTTP 200, latency và cost nhưng vẫn trả lời sai hàng loạt (như thí nghiệm E chuyển về `v1`) — bắt buộc phải có Golden Dataset + CI Quality Gate.
- **Nếu đưa agent này lên production thật, sẽ bổ sung thêm các metric / alert sau:**
  - **Nginx / API Gateway metrics & alerts:** Theo dõi tỷ lệ `502`/`504`/`429` ở tầng Load Balancer để không bỏ sót lỗi khi agent treo hoặc quá tải.
  - **LLM-specific metrics:** `time_to_first_token_seconds` (TTFT cho streaming), `retrieval_hit_ratio` (cảnh báo ngay khi tỉ lệ tìm thấy tài liệu giảm đột ngột như thí nghiệm E), và `llm_token_limit_truncations_total`.
  - **Alertmanager routing & Burn-rate alerts:** Gửi cảnh báo phân cấp (`warning` → Slack, `critical` → PagerDuty) theo tốc độ đốt error budget thay vì chỉ ngưỡng tĩnh, kèm theo **Online Eval** định kỳ trên mẫu traffic thực.
