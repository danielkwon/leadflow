# B2B 영업 자동화 파이프라인 (Sales Pipeline Automation)

본 프로젝트는 건설사, 시공사, 인력사무소 대상 '근로자 관리 SaaS' 영업을 위해 개발된 리드 수집, 초개인화 콜드 메일 발송, Drip Campaign 관리, 그리고 실시간 Google Sheets CRM 연동을 지원하는 B2B 영업 자동화 시스템입니다.

---

## 🎨 핵심 아키텍처 및 특징

1. **자동 영업 DB 수집 (Phase 2)**
   - 네이버 검색 API 기반의 타깃 리드 리스트 실시간 스크래핑.
   - 2차 웹사이트 크롤링을 통해 메인 홈페이지 및 연락처 페이지에서 정규표현식 및 `mailto` 분석으로 이메일 주소를 자동 추출.
   - 주식회사, (주), ㈜ 등의 혼용 및 전화번호 국가코드(+82) 변환 등을 수행하는 강력한 중복 제거 모듈(Dedup) 내장.

2. **초개인화 콜드 이메일 발송 (Phase 3 & 6)**
   - Google Workspace Gmail API OAuth 2.0 연동을 통한 대외 신뢰도 극대화.
   - OpenAI GPT-4o-mini 모델을 사용하여, 업체의 지역/업종/대표자 호칭 분석 후 **실제 사람이 쓴 것과 같은 초개인화 도입부(1~2문장) 자동 생성**.
   - Jinja2 템플릿 엔진을 사용하여 광고 필수 규정 준수 및 **HMAC SHA-256 암호화 토큰 기반의 실시간 수신거부(FastAPI Unsubscribe 웹 서버) 처리**.

3. **시퀀스 Drip Campaign (Phase 4)**
   - 첫 번째 콜드 메일 발송 후, 지정된 주기(예: 30일)에 맞춰 자동으로 1차 및 2차 후속(Follow-up) 이메일을 순차 발송.
   - APScheduler 라이브러리를 통해 개발 환경(매 시간 정각) 및 운영 환경(매일 오전 9시)에 최적화된 자동 발송 스케줄러 내장.

4. **실시간 회신 감지 & CRM 연동 (Phase 5)**
   - 수신함 모니터링 데몬이 리드로부터 온 답장을 실시간 감지하여 DB 상태를 `replied`로 변경.
   - `gspread`를 활용해 모든 리드 데이터와 회신받은 메일의 제목, 본문 요약을 **Google Sheets 영업 현황판에 100% 자동 연동(실시간 동기화)**.

---

## 📂 디렉토리 구조

```text
sales_pipeline/
├── src/
│   └── sales_pipeline/
│       ├── db/               # SQLAlchemy ORM 모델 및 CRUD 레포지토리
│       ├── scraper/          # 네이버 API 및 웹사이트 이메일 추출기
│       ├── email_sender/     # Gmail API 발송 및 FastAPI 수신거부 서버
│       ├── campaign/         # Drip Campaign 및 APScheduler 스케줄러
│       ├── monitor/          # Gmail 수신함 모니터링 및 회신 감지 데몬
│       ├── crm/              # Google Sheets CRM 실시간 연동기
│       ├── llm/              # OpenAI GPT 초개인화 문장 작가
│       ├── settings.py       # Pydantic-Settings 전역 환경설정
│       ├── logging.py        # Structlog 기반 구조화 컨텍스트 로거
│       ├── main.py           # 애플리케이션 공통 부트스트랩
│       └── cli.py            # Typer CLI 통합 엔트리포인트
├── config/
│   ├── email_templates/      # Jinja2 HTML 이메일 템플릿
│   └── scraping_targets.yaml # 지역 및 키워드 기본 수집 타깃
├── tests/                    # pytest 기반 무모킹 통합 테스트
├── pyproject.toml            # Python 의존성 및 스크립트 선언
├── Dockerfile                # 경량 다단계 프로덕션 빌드 파일
└── README.md                 # 프로젝트 기술 문서
```

---

## 🛠️ 개발 환경 구축 및 실행 방법

### 1. 가상환경 구성 및 패키지 설치

파이썬 3.11 이상의 환경에서 아래 명령어를 실행하여 설치합니다.

```bash
# 가상환경 생성
python3 -m venv .venv
source .venv/bin/activate

# 패키지 및 개발 도구 설치 (editable 모드)
pip install --upgrade pip
pip install -e ".[dev]"
```

### 2. 환경변수 설정 (`.env`)

프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 적절한 키 값을 세팅합니다.

```env
# 네이버 OpenAPI 설정 (지역 검색 수집용)
NAVER_CLIENT_ID=your-naver-client-id
NAVER_CLIENT_SECRET=your-naver-client-secret

# OpenAI API 설정 (초개인화 도입부 생성용)
OPENAI_API_KEY=your-openai-api-key

# Gmail API OAuth 설정 (Gmail 발송용)
GMAIL_CREDENTIALS_PATH=config/gmail_credentials.json
GMAIL_TOKEN_PATH=config/gmail_token.json
SENDER_EMAIL=your-workspace-email@yourdomain.com
SENDER_NAME=영업본부_길동이

# Google Sheets CRM 설정
GOOGLE_SHEETS_CREDENTIALS_PATH=config/sheets_service_account.json
GOOGLE_SHEETS_NAME=영업_현황판

# 데이터베이스 및 수신거부 설정
DATABASE_URL=sqlite:///./data/sales_pipeline.db
APP_ENV=development
LOG_LEVEL=INFO
OPT_OUT_BASE_URL=http://localhost:8080
OPT_OUT_SECRET_KEY=generate-random-secure-string-key
```

> 💡 **OAuth 및 API 키 관련 주의사항:**
> - `gmail_credentials.json`은 Google Cloud Console에서 Gmail API 활성화 후 다운로드한 OAuth Client JSON 파일입니다.
> - `sheets_service_account.json`은 Google Cloud Console에서 생성한 서비스 계정 키 파일입니다. 신규 Google Sheets 사용 시 본인의 시트에 해당 서비스 계정 메일 주소를 공유해야 편집이 가능합니다.

---

## 🚀 통합 CLI 사용법 가이드

`sales` 명령어를 통해 모든 기능을 손쉽게 제어할 수 있습니다.

### 1. 데이터베이스 초기화
```bash
# SQLite DB 및 테이블 자동 생성
sales db init
```

### 2. 영업 대상 리드 수집 (Scraper)
```bash
# 특정 지역 및 키워드로 네이버 검색 수집 실행
sales scrape run --region "서울 영등포구" --keyword "인력사무소"

# 이메일 주소가 비어있는 리드의 웹사이트를 탐색하여 2차 이메일 주소 추출
sales scrape enrich --limit 50
```

### 3. 리드 현황 및 이메일 수동 테스트
```bash
# 수집된 전체 리드 및 영업 상태 목록 조회
sales leads list --limit 10

# 리드별 상태 통계 데이터 출력
sales leads stats

# 특정 리드 ID로 Gmail 콜드메일 테스트 발송 실행 (OAuth 최초인증 트리거)
sales email send-test --lead-id 1
```

### 4. Drip Campaign 관리 및 스케줄러 작동
```bash
# 영업용 Drip 캠페인 생성
sales campaign create --name "2026-솔루션영업" --template "cold_email_v1" --interval 30 --max-seq 3

# 지정한 Drip 캠페인을 즉시 수동 실행 (시퀀스 판별 및 발송 진행)
sales campaign run --name "2026-솔루션영업"

# Drip 캠페인 자동 발송 스케줄러 상주 가동 (development 모드 시 1시간마다 가동)
sales scheduler
```

### 5. 수신함 모니터링 및 실시간 CRM 연동
```bash
# Gmail 수신함을 모니터링하여 회신을 감지하고 Google Sheets로 실시간 동기화
sales monitor
```

---

## 🧪 통합 테스트 수행

Rule 5 (No Mocking) 표준에 맞춰, 실제 SQLite 인메모리 데이터베이스 및 실제 템플릿 환경을 토대로 온전한 비즈니스 로직을 검증합니다.

```bash
# 테스트 러너 기동
pytest -v
```

---

## 🐳 Docker를 통한 배포

시스템을 컨테이너화하여 상주 실행하려면 다단계 빌드 기반 경량 이미지를 사용합니다.

```bash
# Docker 이미지 빌드
docker build -t sales-pipeline:latest .

# 환경변수 파일을 주입하여 스케줄러 실행
docker run -d --name sales-scheduler \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config \
  sales-pipeline:latest scheduler
```
