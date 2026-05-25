"""Google Sheets CRM 연동 모듈.

gspread 라이브러리를 사용하여 SQLite DB의 최신 영업 리드 정보와
수신함에서 감지된 고객 회신 목록을 Google Sheets에 실시간 동기화한다.
"""
import datetime
import os
from typing import Any, List

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy.orm import Session

from sales_pipeline.db.engine import get_db
from sales_pipeline.db.models import Lead, Reply
from sales_pipeline.db.repository import get_leads, get_unsynced_replies, mark_reply_synced
from sales_pipeline.settings import get_settings
from sales_pipeline.utils.logging import get_logger

log = get_logger("crm.sheets")

# 시트 헤더 정의
LEAD_HEADERS = [
    "리드 ID", "업체명", "대표자명", "전화번호", "이메일", "웹사이트 URL",
    "주소", "지역", "카테고리", "데이터 출처", "영업 상태", "수신거부", "수신거부일",
    "수집일", "최종 수정일"
]

REPLY_HEADERS = [
    "회신 ID", "리드 ID", "업체명", "고객 이메일", "회신 일시", "회신 제목",
    "본문 요약", "CRM 동기화 시간"
]


def _get_sheets_client() -> gspread.Client:
    """Google Service Account 인증을 통해 gspread 클라이언트를 반환한다."""
    settings = get_settings()
    path = settings.google_sheets_credentials_path

    if not os.path.exists(path):
        log.error("Google Sheets 서비스 계정 JSON 파일을 찾을 수 없습니다", path=path)
        raise FileNotFoundError(
            f"Google Sheets 서비스 계정 JSON credentials 파일이 없습니다: {path}\n"
            f"Google Cloud Console에서 서비스 계정을 생성하고 키(JSON)를 다운로드해 config 폴더에 넣어주세요."
        )

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    
    creds = Credentials.from_service_account_file(path, scopes=scopes)
    log.info("Google Sheets API 서비스 계정 인증 완료", service_account=creds.service_account_email)
    return gspread.authorize(creds)


def _get_or_create_spreadsheet(client: gspread.Client) -> gspread.Spreadsheet:
    """설정된 이름의 스프레드시트를 열거나, 없으면 새로 생성한다."""
    settings = get_settings()
    name = settings.google_sheets_name

    try:
        sh = client.open(name)
        log.info("기존 Google Sheet 오픈 성공", name=name)
        return sh
    except gspread.exceptions.SpreadsheetNotFound:
        log.info("기존 시트가 없어 신규 Google Sheet 생성을 시도합니다...", name=name)
        # 서비스 계정 권한으로 시트 생성
        sh = client.create(name)
        
        # 권한에 대한 안내문 출력 (사용자가 본인의 구글 계정으로 공유받아야 편집 가능)
        credentials = Credentials.from_service_account_file(settings.google_sheets_credentials_path)
        sa_email = credentials.service_account_email
        log.warning(
            "⚠️ 신규 구글 시트가 생성되었습니다. "
            "사용자의 구글 드라이브에서 보려면 아래 서비스 계정 이메일에 공유를 설정해야 합니다.",
            service_account_email=sa_email,
            spreadsheet_name=name,
        )
        return sh


def _ensure_worksheets(sh: gspread.Spreadsheet) -> tuple[gspread.Worksheet, gspread.Worksheet]:
    """필수 워크시트(리드 현황, 회신 이력)가 존재하는지 확인하고 없으면 생성한다."""
    # 1. 영업 리드 현황 워크시트
    try:
        leads_ws = sh.worksheet("영업 리드 현황")
    except gspread.exceptions.WorksheetNotFound:
        leads_ws = sh.add_worksheet(title="영업 리드 현황", rows=1000, cols=15)
        leads_ws.append_row(LEAD_HEADERS)
        log.info("영업 리드 현황 워크시트 신규 생성 완료")

    # 2. 고객 회신 이력 워크시트
    try:
        replies_ws = sh.worksheet("고객 회신 이력")
    except gspread.exceptions.WorksheetNotFound:
        replies_ws = sh.add_worksheet(title="고객 회신 이력", rows=1000, cols=8)
        replies_ws.append_row(REPLY_HEADERS)
        log.info("고객 회신 이력 워크시트 신규 생성 완료")

    return leads_ws, replies_ws


def sync_data_to_sheets() -> None:
    """SQLite DB의 리드 전체와 회신 목록을 Google Sheets와 동기화한다.

    네트워크 오버헤드를 방지하기 위해 벌크 업데이트(Batch Update) 방식으로 처리한다.
    """
    log.info("📊 Google Sheets CRM 동기화 작업을 개시합니다...")
    
    try:
        client = _get_sheets_client()
        sh = _get_or_create_spreadsheet(client)
        leads_ws, replies_ws = _ensure_worksheets(sh)
    except Exception as e:
        log.error("Google Sheets 연결 및 시트 준비 중 실패", error=str(e))
        return

    with get_db() as db:
        # === 1. 리드 현황 동기화 ===
        leads = get_leads(db, limit=2000)  # 최대 2000개 리드 동기화 지원
        lead_rows = []
        for l in leads:
            lead_rows.append([
                l.id,
                l.company_name,
                l.representative or "-",
                l.phone or "-",
                l.email or "-",
                l.website_url or "-",
                l.address or "-",
                l.region,
                l.category,
                l.source,
                l.status,
                "Y" if l.opt_out else "N",
                l.opt_out_date.strftime("%Y-%m-%d %H:%M:%S") if l.opt_out_date else "-",
                l.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                l.updated_at.strftime("%Y-%m-%d %H:%M:%S")
            ])

        # 시트 초기화 후 다시 쓰기 (벌크)
        leads_ws.clear()
        leads_ws.update('A1', [LEAD_HEADERS] + lead_rows)
        log.info("영업 리드 현황 시트 동기화 완료", synced_rows=len(lead_rows))

        # === 2. 고객 회신 이력 동기화 ===
        # SQLite에서 모든 회신 목록 가져오기
        all_replies = db.query(Reply).order_by(Reply.received_at.desc()).all()
        reply_rows = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for r in all_replies:
            reply_rows.append([
                r.id,
                r.lead_id,
                r.lead.company_name if r.lead else "-",
                r.lead.email if r.lead else "-",
                r.received_at.strftime("%Y-%m-%d %H:%M:%S"),
                r.subject or "(제목 없음)",
                r.body[:500] if r.body else "-", # 본문은 500자까지 잘라서 기록
                now_str
            ])

            # 미동기화 상태의 회신들은 동기화 완료 처리
            if not r.synced_to_sheet:
                mark_reply_synced(db, r.id)

        replies_ws.clear()
        replies_ws.update('A1', [REPLY_HEADERS] + reply_rows)
        log.info("고객 회신 이력 시트 동기화 완료", synced_rows=len(reply_rows))

    log.info("✅ Google Sheets CRM 동기화 작업이 성공적으로 완료되었습니다!")
