"""FastAPI 메인 웹 애플리케이션 정의 모듈.

정적 자산 폴더 마운트 및 웹 통합 라우터를 등록한다.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from leadflow.web.router import router

app = FastAPI(
    title="LeadFlow SaaS Dashboard",
    description="LeadFlow B2B Sales Automation Dashboard Platform",
    version="1.0.0"
)

# 정적 파일 경로 마운트 (CSS, JS, 이미지 등)
# 실제 디렉터리 존재가 보장되어야 마운트 가능
app.mount("/static", StaticFiles(directory="src/leadflow/web/static"), name="static")

# 라우터 등록
app.include_router(router)
