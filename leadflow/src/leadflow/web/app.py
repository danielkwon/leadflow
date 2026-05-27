"""FastAPI 메인 웹 애플리케이션 정의 모듈."""
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from leadflow.web.router import router

app = FastAPI(
    title="LeadFlow SaaS Dashboard",
    description="LeadFlow B2B Sales Automation Dashboard Platform",
    version="1.0.0"
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(router)
