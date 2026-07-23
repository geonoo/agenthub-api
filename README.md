# AgentHub API Service

LLM 에이전트 및 개발자를 위한 한국형 데이터/크롤링/정제 API 허브입니다.

| 항목 | 값 |
|------|-----|
| 서비스 | [agenthub.co.kr](https://agenthub.co.kr) |
| API 전용 | [api.agenthub.co.kr](https://api.agenthub.co.kr) |
| Stack | FastAPI · Docker · Nginx · Let's Encrypt |
| Python | 3.11+ |

---

## 프로젝트 구조

```text
agenthub-api/
├── app/
│   ├── main.py                 # FastAPI 엔트리포인트
│   ├── core/
│   │   ├── config.py           # 환경 설정 (pydantic-settings)
│   │   └── security.py         # X-API-KEY 헤더 검증
│   ├── api/v1/endpoints/
│   │   ├── health.py           # GET /api/v1/health
│   │   └── stock.py            # GET /api/v1/stock/summary
│   └── schemas/                # Pydantic 응답 모델
├── nginx/default.conf          # reverse proxy + SSL
├── Dockerfile                  # multi-stage (python:3.11-slim)
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 빠른 시작 (로컬)

```bash
# 1) 환경 변수
cp .env.example .env
# API_KEY 값을 안전한 값으로 변경하세요.

# 2) 의존성 (로컬 개발)
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

### API 호출 예시

```bash
# Health (인증 불필요)
curl http://localhost:8000/api/v1/health

# Stock summary (X-API-KEY 필요)
curl -H "X-API-KEY: change-me-in-production" \
  "http://localhost:8000/api/v1/stock/summary?code=005930"
```

---

## Docker Compose 배포

```bash
cp .env.example .env
# .env 의 API_KEY 수정

docker compose up -d --build
```

컨테이너:

| 서비스 | 역할 |
|--------|------|
| `fastapi-app` | Uvicorn + FastAPI (내부 8000) |
| `nginx` | TLS 종료 · reverse proxy (80/443) |
| `certbot` | Let's Encrypt 발급/갱신 (`--profile certs`) |

---

## OCI (Oracle Cloud Infrastructure) 배포 안내

1. **컴퓨트**  
   Ubuntu 22.04+ VM을 생성하고 Public IP를 할당합니다. Security List / NSG에서 **TCP 80, 443** 인바운드를 허용하세요.

2. **DNS**  
   `agenthub.co.kr`, `api.agenthub.co.kr` A 레코드를 VM Public IP로 지정합니다.

3. **Docker 설치**

   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2
   sudo usermod -aG docker $USER
   ```

4. **코드 배포**

   ```bash
   git clone <repo-url> /opt/agenthub-api
   cd /opt/agenthub-api
   cp .env.example .env
   # API_KEY 등 설정
   ```

5. **Let's Encrypt 인증서 (최초 1회)**  
   SSL 파일이 없으면 Nginx가 기동에 실패할 수 있으므로, 최초에는 HTTP(ACME)만 허용하거나 임시 self-signed로 부팅한 뒤 certbot을 실행하세요.

   ```bash
   mkdir -p certbot/conf certbot/www

   # HTTP로 앱만 먼저 올린 뒤 (필요 시 nginx conf의 SSL 블록을 잠시 주석 처리):
   docker compose run --rm --entrypoint certbot certbot certonly \
     --webroot -w /var/www/certbot \
     -d agenthub.co.kr -d api.agenthub.co.kr \
     --email admin@agenthub.co.kr --agree-tos --no-eff-email

   docker compose up -d --build
   ```

6. **인증서 갱신 (cron 예시)**

   ```bash
   0 3 * * * cd /opt/agenthub-api && docker compose run --rm certbot renew && docker compose exec nginx nginx -s reload
   ```

7. **헬스 확인**

   ```bash
   curl https://api.agenthub.co.kr/api/v1/health
   ```

---

## 인증

보호된 엔드포인트는 `X-API-KEY` 헤더가 필요합니다.

```http
X-API-KEY: <your-api-key>
```

키는 `.env`의 `API_KEY`로 설정합니다. Swagger UI(`/docs`) 우측 상단 **Authorize**에서 키를 입력할 수 있습니다.

---

## API Docs

| 문서 | URL |
|------|-----|
| Swagger UI | https://api.agenthub.co.kr/docs |
| ReDoc | https://api.agenthub.co.kr/redoc |
| OpenAPI | https://api.agenthub.co.kr/openapi.json |

Title: **AgentHub API Service**  
Description: LLM 에이전트 및 개발자를 위한 한국형 데이터/크롤링/정제 API 허브

---

## 엔드포인트

| Method | Path | Auth | 설명 |
|--------|------|------|------|
| GET | `/api/v1/health` | 없음 | 헬스 체크 |
| GET | `/api/v1/stock/summary?code=` | X-API-KEY | 종목 요약 (스텁) |

---

## 라이선스

Private — AgentHub
