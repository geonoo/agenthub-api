# AgentHub API Service

LLM 에이전트 및 개발자를 위한 한국형 데이터/크롤링/정제 API 허브입니다.

| 항목 | 값 |
|------|-----|
| 서비스 | [agenthub.co.kr](https://agenthub.co.kr) |
| API 전용 | [api.agenthub.co.kr](https://api.agenthub.co.kr) |
| Stack | FastAPI · Docker · Nginx · Let's Encrypt · MCP |
| Python | 3.11+ |

---

## 프로젝트 구조

```text
agenthub-api/
├── app/
│   ├── main.py                 # FastAPI 엔트리포인트 + 미들웨어
│   ├── core/
│   │   ├── config.py           # API_KEY / MASTER_API_KEY / Quota
│   │   └── security.py         # X-API-KEY + 일일 쿼터 미들웨어
│   ├── db/                     # SQLAlchemy + SQLite
│   ├── api/v1/endpoints/
│   │   ├── health.py
│   │   ├── auth.py             # issue-key / usage
│   │   ├── stock.py
│   │   ├── dart.py
│   │   ├── finance.py
│   │   └── mcp.py
│   ├── services/
│   └── schemas/
├── static/                     # 랜딩 + dashboard
├── data/                       # SQLite volume (./data:/app/data)
├── tests/
├── nginx/default.conf
├── Dockerfile                  # build → pytest → runtime
├── docker-compose.yml
└── .env.example
```

---

## 빠른 시작 (로컬)

```bash
cp .env.example .env
# API_KEY, MASTER_API_KEY, DART_API_KEY 설정

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- MCP: `POST http://localhost:8000/mcp`

### 테스트 (pytest)

```bash
pip install -r requirements.txt   # pytest / pytest-asyncio / httpx 포함
pytest -q
```

| 파일 | 범위 |
|------|------|
| `tests/test_health.py` | 헬스 체크 |
| `tests/test_auth.py` | X-API-KEY · MASTER · burst limit |
| `tests/test_key_issue.py` | 셀프 발급 · SHA-256 · 일일 쿼터 429 |
| `tests/test_dart.py` | DART 정제 API |
| `tests/test_finance.py` | 네이버 금융 뉴스 API |
| `tests/test_mcp.py` | MCP tools/list · tools/call |
| `tests/test_stock.py` | 스톡 스텁 · 랜딩 · OpenAPI |

Docker 이미지 빌드 시 `test` 스테이지에서 `pytest`가 자동 실행되며, 실패하면 빌드가 중단됩니다.

---

## API Key 셀프 발급 (SQLite)

랜딩(https://agenthub.co.kr)에서 **API Key 즉시 발급 받기** 또는:

```bash
curl -X POST https://api.agenthub.co.kr/api/v1/auth/issue-key \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'
```

응답의 `api_key`(`ah_live_...`)는 **한 번만** 보여집니다. DB에는 SHA-256 해시만 저장됩니다.

사용량 조회:

```bash
curl -H "X-API-KEY: ah_live_..." https://api.agenthub.co.kr/api/v1/auth/usage
```

대시보드 UI: https://agenthub.co.kr/dashboard

### Rate Limit / Quota

| 구분 | 규칙 |
|------|------|
| Free Tier (발급 키) | **일 1,000회** (`FREE_TIER_DAILY_LIMIT`, UTC 일 기준) |
| Burst | 기본 **60 req / 60s** (`RATE_LIMIT_*`) |
| `MASTER_API_KEY` / `.env` `API_KEY` | 일일 쿼터 **무제한** (관리용) |
| 한도 초과 | **429 Too Many Requests** |

SQLite 파일: Docker volume `./data:/app/data` → `/app/data/agenthub.db` (WAL 모드)

---

## X-API-KEY 인증

보호된 API는 헤더가 필요합니다.

```http
X-API-KEY: <your-api-key>
```

| 경로 | 인증 |
|------|------|
| `/`, `/dashboard`, `/docs`, `/redoc`, `/openapi.json`, `/static/*`, `/api/v1/health`, `/api/v1/auth/issue-key` | 불필요 |
| DART / Finance / Stock / MCP / `auth/usage` | 필수 |

잘못된·누락된 키 → **401 Unauthorized**

```bash
curl -H "X-API-KEY: $API_KEY" \
  "https://api.agenthub.co.kr/api/v1/stock/summary?code=005930"
```

Swagger **Authorize**에도 동일 키를 입력하면 됩니다.

---

## DART 공시 정제 API

| 항목 | 값 |
|------|-----|
| Path | `GET /api/v1/dart/company-disclosures` |
| Query | `stock_code` (6자리), `limit` (기본 5) |
| Auth | X-API-KEY |
| Upstream | `.env`의 `DART_API_KEY` ([Open DART](https://opendart.fss.or.kr/) 발급) |

```bash
curl -H "X-API-KEY: $API_KEY" \
  "https://api.agenthub.co.kr/api/v1/dart/company-disclosures?stock_code=005930&limit=3"
```

---

## 네이버 금융 뉴스 API

종목 뉴스를 크롤링한 뒤 광고/스크립트를 제거하고 Clean Markdown으로 반환합니다.

| 항목 | 값 |
|------|-----|
| Path | `GET /api/v1/finance/news` |
| Query | `stock_code` (6자리), `limit` (기본 5) |
| Auth | X-API-KEY |

```bash
curl -H "X-API-KEY: $API_KEY" \
  "https://api.agenthub.co.kr/api/v1/finance/news?stock_code=005930&limit=5"
```

---

## MCP (Claude Desktop / MCP 클라이언트)

JSON-RPC 엔드포인트: `POST /mcp` (동일 기능 `POST /api/v1/mcp`)

| Tool | 설명 |
|------|------|
| `get_dart_disclosures` | DART 공시 Clean Markdown/JSON |
| `get_stock_news` | 네이버 금융 뉴스 Clean Markdown |

### 호출 예시

```bash
# tools/list
curl -H "X-API-KEY: $API_KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  https://api.agenthub.co.kr/mcp

# tools/call — get_stock_news
curl -H "X-API-KEY: $API_KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_stock_news","arguments":{"stock_code":"005930","limit":3}}}' \
  https://api.agenthub.co.kr/mcp
```

SSE 핸드셰이크: `GET /mcp/sse` (X-API-KEY 필요)

### Claude Desktop 설정 예시

`claude_desktop_config.json`에 MCP 서버를 등록합니다. HTTP MCP를 지원하는 클라이언트/브리지에서는 아래를 참고하세요.

```json
{
  "mcpServers": {
    "agenthub": {
      "url": "https://api.agenthub.co.kr/mcp",
      "headers": {
        "X-API-KEY": "YOUR_AGENTHUB_API_KEY"
      }
    }
  }
}
```

stdio 브리지(예: `mcp-remote` 등)를 쓰는 경우:

```json
{
  "mcpServers": {
    "agenthub": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://api.agenthub.co.kr/mcp",
        "--header",
        "X-API-KEY: YOUR_AGENTHUB_API_KEY"
      ]
    }
  }
}
```

도구 목록만 REST로 확인할 때: `GET /mcp/tools`

---

## Docker Compose 배포

```bash
cp .env.example .env
# API_KEY, MASTER_API_KEY, DART_API_KEY 설정

docker compose down && docker compose up -d --build
```

빌드 중 pytest가 통과해야 이미지가 생성됩니다.

| 서비스 | 역할 |
|--------|------|
| `fastapi-app` | Uvicorn + FastAPI (내부 8000) |
| `nginx` | TLS · reverse proxy (80/443) |
| `certbot` | Let's Encrypt (`--profile certs`) |

---

## OCI 배포 요약

1. Ubuntu VM + Security List **80/443** 개방  
2. DNS: `agenthub.co.kr`, `api.agenthub.co.kr` → Public IP  
3. Docker 설치 후 코드 clone · `.env` 설정  
4. Let's Encrypt 발급 후 `docker compose up -d --build`  
5. `curl https://api.agenthub.co.kr/api/v1/health`

상세 절차는 저장소 내 기존 OCI 절을 따릅니다. 인증서 갱신 cron 예시:

```bash
0 3 * * * cd /opt/agenthub-api && docker compose run --rm certbot renew && docker compose exec nginx nginx -s reload
```

---

## API Docs

| 문서 | URL |
|------|-----|
| Swagger UI | https://api.agenthub.co.kr/docs |
| ReDoc | https://api.agenthub.co.kr/redoc |
| OpenAPI | https://api.agenthub.co.kr/openapi.json |

---

## 엔드포인트

| Method | Path | Auth | 설명 |
|--------|------|------|------|
| GET | `/api/v1/health` | 없음 | 헬스 체크 |
| POST | `/api/v1/auth/issue-key` | 없음 | API Key 셀프 발급 |
| GET | `/api/v1/auth/usage` | X-API-KEY | 당일/월간 사용량 |
| GET | `/api/v1/stock/summary?code=` | X-API-KEY | 종목 요약 (스텁) |
| GET | `/api/v1/dart/company-disclosures` | X-API-KEY | DART 공시 정제 |
| GET | `/api/v1/finance/news` | X-API-KEY | 네이버 금융 뉴스 정제 |
| POST | `/mcp` | X-API-KEY | MCP JSON-RPC |
| GET | `/mcp/tools` | X-API-KEY | MCP 도구 목록 |
| GET | `/mcp/sse` | X-API-KEY | MCP SSE |
| GET | `/dashboard` | 없음 | 사용량 대시보드 UI |

---

## 라이선스

Private — AgentHub
