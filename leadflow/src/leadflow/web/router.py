"""FastAPI 웹 라우터 모듈.

SaaS형 회원가입/로그인 관리, 대시보드 메트릭 시각화,
가변 지역/업종 기반 크롤링 제어, 개별 암호화 자격증명 관리 기능을 담당한다.
"""
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from leadflow_common.db.engine import get_db_api
from leadflow_common.db.models import User, UserCredential, Lead, Campaign, EmailLog, Reply, Feedback
from leadflow_common.db.repository import get_leads, count_leads, get_active_campaigns
from leadflow_common.utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    encrypt_data,
    decrypt_data,
)
from leadflow_common.utils.logging import get_logger
from leadflow_common.scraper.naver_api import scrape_leads, get_scrape_progress

log = get_logger("web.router")
router = APIRouter()

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

import re

def format_phone_number(phone: str) -> str:
    """전화번호 숫자를 하이픈(-)이 들어간 깔끔한 형식으로 변환한다."""
    if not phone:
        return ""
    clean = re.sub(r"\D", "", phone)
    if not clean:
        return phone
    
    length = len(clean)
    if length == 8:
        return f"{clean[:4]}-{clean[4:]}"
    elif length == 9:
        return f"{clean[:2]}-{clean[2:5]}-{clean[5:]}"
    elif length == 10:
        if clean.startswith("02"):
            return f"{clean[:2]}-{clean[2:6]}-{clean[6:]}"
        else:
            return f"{clean[:3]}-{clean[3:6]}-{clean[6:]}"
    elif length == 11:
        return f"{clean[:3]}-{clean[3:7]}-{clean[7:]}"
    return phone

# Jinja2 글로벌 필터 등록
templates.env.globals.update(format_phone_number=format_phone_number)


# --- 의존성: 현재 로그인 회원 조회 ---

async def get_current_user(request: Request, db: Session = Depends(get_db_api)) -> User:
    """HTTP-Only 쿠키에서 access_token을 파싱하여 현재 로그인된 User를 반환한다.
    비로그인 시 로그인 페이지로 즉각 리다이렉트 예외를 발생시킨다.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    user_email = payload["sub"]
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    return user


async def get_optional_current_user(request: Request, db: Session = Depends(get_db_api)) -> Optional[User]:
    """비로그인 상태를 허용하는 유효 유저 헬퍼."""
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


# --- 인증 라우트 (Sign Up, Sign In, Logout) ---

@router.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request, user: Optional[User] = Depends(get_optional_current_user)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup", response_class=HTMLResponse)
async def signup_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    company_name: str = Form(None),
    db: Session = Depends(get_db_api)
):
    # 중복 가입 체크
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "이미 존재하거나 가입된 이메일 주소입니다."}
        )
    
    try:
        # 비밀번호 안전한 암호 해싱 후 신규 가입 처리
        hashed = hash_password(password)
        new_user = User(
            email=email,
            hashed_password=hashed,
            company_name=company_name
        )
        db.add(new_user)
        db.commit()
        
        # 최초 자격증명 바인딩 레코드 삽입
        new_cred = UserCredential(user_id=new_user.id)
        db.add(new_cred)
        db.commit()
        
        log.info("SaaS 회원 가입 완료", email=email, user_id=new_user.id)
        return RedirectResponse(url="/login?registered=true", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        db.rollback()
        log.error("회원 가입 중 예외 터짐", error=str(e))
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "회원 가입 중 알 수 없는 오류가 발생했습니다."}
        )


@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, registered: Optional[str] = None, user: Optional[User] = Depends(get_optional_current_user)):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    
    msg = "회원 가입이 완료되었습니다! 가입하신 정보로 로그인하세요." if registered else None
    return templates.TemplateResponse(request, "login.html", {"info_msg": msg, "error": None})


@router.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db_api)
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "이메일 또는 비밀번호가 정확하지 않습니다.", "info_msg": None}
        )
    
    # 로그인 성공 시 24시간 유효 토큰 발급
    access_token = create_access_token(data={"sub": user.email})
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    
    # 보안 HTTP-Only 세션 쿠키 부여
    from leadflow_common.settings import get_settings
    settings = get_settings()
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=60 * 60 * 24, # 24시간
        samesite="lax",
        secure=(settings.app_env == "production"),
    )
    log.info("SaaS 로그인 성공", email=email, user_id=user.id)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")
    log.info("사용자 로그아웃 완료")
    return response


# --- 대시보드 메인 화면 ---

@router.get("/", response_class=HTMLResponse)
async def root_get():
    """루트 접속 시 대시보드로 자동 연결 유도."""
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_get(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db_api)):
    # 사용자별 격리된 리드 통계 수집
    total = count_leads(db, user_id=user.id)
    new_leads = count_leads(db, user_id=user.id, status="new")
    replied = count_leads(db, user_id=user.id, status="replied")
    converted = count_leads(db, user_id=user.id, status="converted")
    
    # 최신 리드 5개만 목록 로드
    recent_leads = get_leads(db, user_id=user.id, limit=5)
    
    # 설정 상태 체크 (API Key 셋업 완료 여부 판단용)
    creds = db.query(UserCredential).filter(UserCredential.user_id == user.id).first()
    has_openai = bool(creds.encrypted_openai_key) if creds else False
    has_gmail = bool(creds.encrypted_gmail_credentials) if creds else False
    
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "stats": {
                "total": total,
                "new": new_leads,
                "replied": replied,
                "converted": converted
            },
            "recent_leads": recent_leads,
            "setup": {
                "openai": has_openai,
                "gmail": has_gmail
            },
            "active_page": "dashboard"
        }
    )


# --- 업종 및 지역 가변 크롤링 수집 제어 ---

@router.get("/scrape", response_class=HTMLResponse)
async def scrape_get(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db_api)):
    # 해당 사용자가 모은 최신 리드 목록과 수집 통계 로드
    leads = get_leads(db, user_id=user.id, limit=30)
    total_scraped = count_leads(db, user_id=user.id)
    
    return templates.TemplateResponse(
        request,
        "scrape.html",
        {
            "user": user,
            "leads": leads,
            "total_scraped": total_scraped,
            "success_msg": None,
            "error_msg": None,
            "active_page": "scrape"
        }
    )


def _background_scrape_task(user_id: int, region: str, keyword: str, max_results: int):
    """백그라운드 스크래핑 워커 함수."""
    try:
        log.info("백그라운드 스크래핑 태스크 개시", user_id=user_id, region=region, keyword=keyword)
        scrape_leads(user_id=user_id, region=region, keyword=keyword, max_results=max_results)
    except Exception as e:
        log.error("백그라운드 수집 동작 중 예외 발생", error=str(e), user_id=user_id)


@router.post("/scrape")
async def scrape_post(
    request: Request,
    background_tasks: BackgroundTasks,
    region: str = Form(...),
    keyword: str = Form(...),
    max_results: int = Form(50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_api)
):
    try:
        # 백그라운드로 Playwright 스크래퍼 즉각 예약 구동 (SaaS 대기 시간 최소화)
        background_tasks.add_task(
            _background_scrape_task,
            user_id=user.id,
            region=region,
            keyword=keyword,
            max_results=max_results
        )
        
        success = f"'{region} {keyword}' 수집 요청이 정상 등록되었습니다! 백그라운드에서 안전하게 크롤링이 작동 중입니다. 잠시 후 새로고침해 주세요."
        leads = get_leads(db, user_id=user.id, limit=30)
        total_scraped = count_leads(db, user_id=user.id)
        
        return templates.TemplateResponse(
            request,
            "scrape.html",
            {
                "user": user,
                "leads": leads,
                "total_scraped": total_scraped,
                "success_msg": success,
                "error_msg": None,
                "active_page": "scrape"
            }
        )
    except Exception as e:
        log.error("수집 등록 실패", error=str(e))
        leads = get_leads(db, user_id=user.id, limit=30)
        total_scraped = count_leads(db, user_id=user.id)
        return templates.TemplateResponse(
            request,
            "scrape.html",
            {
                "user": user,
                "leads": leads,
                "total_scraped": total_scraped,
                "success_msg": None,
                "error_msg": f"수집 요청 중 장애 발생: {str(e)}",
                "active_page": "scrape"
            }
        )


# --- 사용자 자격증명 및 API Key 설정 연동 ---

@router.get("/settings", response_class=HTMLResponse)
async def settings_get(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db_api)):
    creds = db.query(UserCredential).filter(UserCredential.user_id == user.id).first()
    
    # 저장된 자격증명 복호화 로드 (비노출 마스킹 문자열 구성)
    openai_key = ""
    naver_id = ""
    naver_secret = ""
    sender_name = ""
    sender_email = ""
    sheets_name = "LeadFlow_영업_현황판"
    
    if creds:
        # 복호화 시도 (암호화된 내역이 있을 시만 처리)
        if creds.encrypted_openai_key:
            try:
                dec = decrypt_data(creds.encrypted_openai_key, str(user.id))
                # 일부 마스킹 처리하여 보장
                openai_key = dec[:8] + "*" * (len(dec) - 12) + dec[-4:] if len(dec) > 12 else dec
            except Exception:
                openai_key = "Decryption Error"
                
        if creds.encrypted_naver_id:
            try:
                naver_id = decrypt_data(creds.encrypted_naver_id, str(user.id))
            except Exception:
                naver_id = "Decryption Error"
                
        if creds.encrypted_naver_secret:
            try:
                naver_secret = "********"
            except Exception:
                naver_secret = ""
                
        sender_name = creds.sender_name or ""
        sender_email = creds.sender_email or ""
        sheets_name = creds.sheets_name or "LeadFlow_영업_현황판"
        
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "creds": {
                "openai_key": openai_key,
                "naver_id": naver_id,
                "naver_secret": naver_secret,
                "sender_name": sender_name,
                "sender_email": sender_email,
                "sheets_name": sheets_name,
                "gmail_connected": bool(creds and creds.encrypted_gmail_credentials)
            },
            "success_msg": None,
            "error_msg": None,
            "active_page": "settings"
        }
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_post(
    request: Request,
    openai_key: str = Form(None),
    naver_id: str = Form(None),
    naver_secret: str = Form(None),
    sender_name: str = Form(None),
    sender_email: str = Form(None),
    sheets_name: str = Form("LeadFlow_영업_현황판"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_api)
):
    try:
        creds = db.query(UserCredential).filter(UserCredential.user_id == user.id).first()
        if not creds:
            creds = UserCredential(user_id=user.id)
            db.add(creds)
        
        # 새로운 입력값이 제공되었을 때만 갱신 및 암호화하여 저장
        if openai_key and not openai_key.startswith("sk-...") and "*" not in openai_key:
            creds.encrypted_openai_key = encrypt_data(openai_key.strip(), str(user.id))
            
        if naver_id and "Error" not in naver_id:
            creds.encrypted_naver_id = encrypt_data(naver_id.strip(), str(user.id))
            
        if naver_secret and naver_secret != "********":
            creds.encrypted_naver_secret = encrypt_data(naver_secret.strip(), str(user.id))
            
        if sender_name:
            creds.sender_name = sender_name.strip()
        if sender_email:
            creds.sender_email = sender_email.strip()
            
        creds.sheets_name = sheets_name.strip()
        
        db.commit()
        log.info("회원 설정 자격증명 안전 갱신 및 대칭키 암호화 완수", user_id=user.id)
        
        # 화면 노출을 위한 재구축
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "user": user,
                "creds": {
                    "openai_key": "sk-..." + "*" * 12 if openai_key else "",
                    "naver_id": naver_id or "",
                    "naver_secret": "********" if naver_secret else "",
                    "sender_name": sender_name or "",
                    "sender_email": sender_email or "",
                    "sheets_name": sheets_name,
                    "gmail_connected": bool(creds.encrypted_gmail_credentials)
                },
                "success_msg": "설정이 성공적으로 저장되었습니다. API 자격증명이 대칭키 암호화되어 안전하게 암호화 격리 보호되고 있습니다.",
                "error_msg": None,
                "active_page": "settings"
            }
        )
    except Exception as e:
        db.rollback()
        log.error("설정 갱신 에러", error=str(e), user_id=user.id)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "user": user,
                "creds": {
                    "openai_key": "",
                    "naver_id": "",
                    "naver_secret": "",
                    "sender_name": "",
                    "sender_email": "",
                    "sheets_name": sheets_name,
                    "gmail_connected": False
                },
                "success_msg": None,
                "error_msg": f"설정 저장에 실패했습니다: {str(e)}",
                "active_page": "settings"
            }
        )


# --- 캠페인 이메일 발송 현황 및 회신 이력 ---

@router.get("/emails", response_class=HTMLResponse)
async def emails_get(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db_api)):
    """테넌트별 격리된 콜드메일 발송 로그(EmailLog) 및 수집된 고객 회신(Reply) 이력을 로드한다."""
    try:
        # 이메일 발송 이력 50개 조회
        email_logs = db.query(EmailLog).filter(EmailLog.user_id == user.id).order_by(EmailLog.sent_at.desc()).limit(50).all()
        # 회신 기록 50개 조회
        replies = db.query(Reply).filter(Reply.user_id == user.id).order_by(Reply.received_at.desc()).limit(50).all()
        
        return templates.TemplateResponse(
            request,
            "emails.html",
            {
                "user": user,
                "email_logs": email_logs,
                "replies": replies,
                "active_page": "emails"
            }
        )
    except Exception as e:
        log.error("이메일/회신 이력 로딩 에러", error=str(e), user_id=user.id)
        raise HTTPException(status_code=500, detail="데이터 로드 중 오류가 발생했습니다.")


# --- 실시간 스크래핑 모니터링 및 비동기 데이터 API ---

@router.get("/api/scrape/progress")
async def scrape_progress_api(user: User = Depends(get_current_user)):
    """현재 로그인 유저의 백그라운드 크롤링 수집 진척률을 실시간 반환한다."""
    progress = get_scrape_progress(user.id)
    return progress


@router.post("/api/scrape/start")
async def scrape_start_api(
    background_tasks: BackgroundTasks,
    region: str = Form(...),
    keyword: str = Form(...),
    max_results: int = Form(50),
    user: User = Depends(get_current_user)
):
    """실시간 가변 스크래핑 백그라운드 태스크를 예약 개시하고 즉시 성공 상태를 반환한다."""
    background_tasks.add_task(
        _background_scrape_task,
        user_id=user.id,
        region=region,
        keyword=keyword,
        max_results=max_results
    )
    return {
        "status": "success",
        "message": f"'{region} {keyword}' 수집 태스크가 백그라운드에 등록되었습니다."
    }


@router.get("/api/scrape/leads")
async def scrape_leads_api(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_api)
):
    """현재 로그인 유저가 수집 완료한 리드 목록 데이터를 실시간 JSON 형식으로 반환한다."""
    leads = get_leads(db, user_id=user.id, limit=50)
    lead_list = []
    for lead in leads:
        lead_list.append({
            "id": lead.id,
            "company_name": lead.company_name,
            "representative": lead.representative or "",
            "phone": format_phone_number(lead.phone) if lead.phone else "",
            "email": lead.email or "",
            "website_url": lead.website_url or "",
            "road_address": lead.road_address or lead.address or "",
            "category": lead.category,
            "region": lead.region,
            "status": lead.status,
            "naver_link": lead.naver_link or ""
        })
    return lead_list


# --- 검수자 실시간 피드백 챗봇 & 백로그 트래커 API ---

@router.post("/api/feedback/submit")
async def feedback_submit_api(
    reporter_name: str = Form("검수 직원"),
    content: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_api)
):
    """플로팅 챗봇을 통해 들어온 의견을 격리 DB에 안전하게 기록한다."""
    try:
        new_feedback = Feedback(
            user_id=user.id,
            reporter_name=reporter_name.strip(),
            content=content.strip(),
            status="todo"
        )
        db.add(new_feedback)
        db.commit()
        log.info("새로운 검수 피드백 수집 완료", user_id=user.id, reporter=reporter_name)
        return {
            "status": "success",
            "message": "피드백이 개발팀에 성공적으로 전달되었습니다! 소중한 의견 감사합니다."
        }
    except Exception as e:
        db.rollback()
        log.error("피드백 전송 실패", error=str(e), user_id=user.id)
        raise HTTPException(status_code=500, detail="피드백 저장에 실패했습니다.")


@router.get("/feedback", response_class=HTMLResponse)
async def feedback_tracker_get(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_api)
):
    """사내 검수 피드백 백로그 및 이슈 트래커 화면을 렌더링한다."""
    feedbacks = db.query(Feedback).filter(Feedback.user_id == user.id).order_by(Feedback.created_at.desc()).all()
    todo_list = [f for f in feedbacks if f.status == "todo"]
    done_list = [f for f in feedbacks if f.status == "done"]
    
    return templates.TemplateResponse(
        request,
        "feedback.html",
        {
            "user": user,
            "todo_list": todo_list,
            "done_list": done_list,
            "active_page": "feedback"
        }
    )


@router.post("/api/feedback/{feedback_id}/status")
async def feedback_status_update_api(
    feedback_id: int,
    status: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_api)
):
    """백로그 트래커에서 특정 피드백의 해결 상태(Todo/Done)를 체크 변경한다."""
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id, Feedback.user_id == user.id).first()
    if not feedback:
        raise HTTPException(status_code=404, detail="해당 피드백 항목을 찾을 수 없습니다.")
    
    try:
        feedback.status = status
        db.commit()
        log.info("피드백 이슈 상태 변경 완수", feedback_id=feedback_id, status=status, user_id=user.id)
        return {"status": "success", "message": f"이슈 상태가 '{status}'로 변경되었습니다."}
    except Exception as e:
        db.rollback()
        log.error("피드백 상태 변경 중 오류 발생", error=str(e), user_id=user.id)
        raise HTTPException(status_code=500, detail="이슈 상태 변경에 실패했습니다.")


@router.get("/api/feedback/todo-count")
async def feedback_todo_count_api(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_api)
):
    """현재 로그인 유저가 해결해야 하는 todo 상태의 피드백 총 건수를 반환한다."""
    try:
        count = db.query(Feedback).filter(Feedback.user_id == user.id, Feedback.status == "todo").count()
        return {"count": count}
    except Exception as e:
        log.error("피드백 미처리 카운트 조회 에러", error=str(e), user_id=user.id)
        raise HTTPException(status_code=500, detail="카운트 조회에 실패했습니다.")

