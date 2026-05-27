# 1단계: 공통 라이브러리 + Web 패키지 빌드
FROM python:3.11-slim as builder

WORKDIR /app

# 필수 시스템 빌드 도구 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 가상환경 생성
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 공통 라이브러리 설치 (에디터블 모드)
COPY leadflow_common/pyproject.toml /app/leadflow_common/
COPY leadflow_common/src/ /app/leadflow_common/src/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir /app/leadflow_common/

# Web 패키지 설치
COPY leadflow/pyproject.toml /app/leadflow/
COPY leadflow/src/ /app/leadflow/src/
RUN pip install --no-cache-dir /app/leadflow/

# 2단계: 경량 실행 이미지
FROM python:3.11-slim as runner

WORKDIR /app

# 빌드 완료된 가상환경 복사
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Playwright 브라우저 바이너리 + 시스템 라이브러리 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 \
    libxkbcommon0 libgbm1 libasound2 libxcomposite1 \
    libxdamage1 libxrandr2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/* \
    && playwright install chromium

# 애플리케이션 소스 코드 복사
COPY leadflow_common/src/ /app/leadflow_common/src/
COPY leadflow_common/config/ /app/config/
COPY leadflow/src/ /app/leadflow/src/

# 데이터 보관용 디렉토리
RUN mkdir -p /app/data
VOLUME /app/data

# 환경 변수
ENV APP_ENV=production
ENV LOG_LEVEL=INFO
ENV PYTHONPATH="/app/leadflow_common/src:/app/leadflow/src"

# CLI 엔트리포인트
ENTRYPOINT ["python", "-m", "leadflow.cli"]
