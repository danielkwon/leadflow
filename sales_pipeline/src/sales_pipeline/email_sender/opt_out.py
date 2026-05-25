"""수신거부 처리 웹 엔드포인트.

FastAPI 기반 경량 서버로, 이메일의 수신거부 링크 클릭을 처리한다.
"""
import hashlib

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from sales_pipeline.db.engine import get_db
from sales_pipeline.db.repository import get_lead_by_id, set_lead_opt_out
from sales_pipeline.settings import get_settings
from sales_pipeline.utils.logging import get_logger

log = get_logger("email.opt_out")

opt_out_app = FastAPI(title="수신거부 처리", docs_url=None, redoc_url=None)


def _verify_token(lead_id: int, token: str) -> bool:
    """수신거부 토큰을 검증한다."""
    settings = get_settings()
    secret = settings.opt_out_secret_key.get_secret_value()
    expected = hashlib.sha256(f"{lead_id}:{secret}".encode()).hexdigest()[:16]
    return token == expected


@opt_out_app.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(
    id: int = Query(..., description="리드 ID"),
    token: str = Query(..., description="인증 토큰"),
) -> HTMLResponse:
    """수신거부를 처리한다."""
    # 토큰 검증
    if not _verify_token(id, token):
        log.warning("수신거부 토큰 검증 실패", lead_id=id)
        raise HTTPException(status_code=400, detail="유효하지 않은 요청입니다.")

    # DB 업데이트
    with get_db() as db:
        lead = get_lead_by_id(db, id)
        if not lead:
            raise HTTPException(status_code=404, detail="존재하지 않는 수신자입니다.")

        set_lead_opt_out(db, id)
        company_name = lead.company_name

    log.info("수신거부 처리 완료", lead_id=id, company=company_name)

    # 처리 완료 페이지
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html lang="ko">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>수신거부 처리 완료</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                    background: #f5f5f5;
                }}
                .card {{
                    background: white;
                    padding: 3rem;
                    border-radius: 12px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    text-align: center;
                    max-width: 400px;
                }}
                .icon {{ font-size: 3rem; margin-bottom: 1rem; }}
                h1 {{ font-size: 1.4rem; color: #333; margin-bottom: 0.5rem; }}
                p {{ color: #666; line-height: 1.6; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="icon">✅</div>
                <h1>수신거부 처리가 완료되었습니다</h1>
                <p>더 이상 영업 메일이 발송되지 않습니다.<br>
                불편을 드려 죄송합니다.</p>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )


@opt_out_app.get("/health")
async def health_check():
    """헬스체크 엔드포인트."""
    return {"status": "ok"}


def start_opt_out_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """수신거부 서버를 시작한다."""
    import uvicorn
    log.info("수신거부 서버 시작", host=host, port=port)
    uvicorn.run(opt_out_app, host=host, port=port)
