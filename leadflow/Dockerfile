# 1단계: 빌드 환경 정의
FROM python:3.11-slim as builder

WORKDIR /app

# 필수 시스템 빌드 도구 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 가상환경 생성 및 의존성 설치 준비
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 의존성 정의 파일 복사 및 설치
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# 2단계: 경량 실행 이미지 정의
FROM python:3.11-slim as runner

WORKDIR /app

# 빌드 완료된 가상환경 복사
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 어플리케이션 소스 코드 복사
COPY src/ /app/src/
COPY config/ /app/config/

# 데이터 보관용 디렉토리 생성 및 볼륨 설정
RUN mkdir -p /app/data
VOLUME /app/data

# 환경 변수 기본값 설정
ENV APP_ENV=production
ENV LOG_LEVEL=INFO
ENV PYTHONPATH="/app/src"

# CLI 엔트리포인트 실행
ENTRYPOINT ["python", "-m", "sales_pipeline.cli"]
