"""Gmail 수신함 모니터링 및 회신 감지 모듈.

정기적으로 Gmail API를 조회하여 우리가 발송한 메일에 대한
고객(리드)의 회신을 감지하고, DB 및 CRM(Google Sheets)에 즉시 연동한다.
"""
import datetime
import html
import re
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from leadflow_common.db.engine import get_db
from leadflow_common.db.models import Lead
from leadflow_common.db.repository import (
    create_reply,
    get_last_email_for_lead,
    get_leads,
    update_lead_status,
)
from leadflow_common.email_sender.gmail_client import _get_gmail_service
from leadflow_common.utils.logging import get_logger

log = get_logger("monitor.inbox")


def _clean_body_text(raw_html: str) -> str:
    """HTML 메일 본문에서 태그를 제거하고 텍스트만 청소하여 반환한다."""
    # 간단한 HTML 태그 제거 및 엔티티 변환
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    # 중복 공백 및 개행 정규화
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1000]  # 최대 1000자만 저장


def _get_email_body(payload: dict) -> str:
    """Gmail API 메세지 페이로드에서 본문 텍스트를 재귀적으로 추출한다."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            body += _get_email_body(part)
    else:
        mime_type = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data", "")
        if data and mime_type in ["text/plain", "text/html"]:
            import base64
            decoded = base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
            body += decoded
    return body


def check_lead_replies(db: Session, service: Any, lead: Lead) -> bool:
    """특정 리드로부터 온 이메일 회신이 있는지 검사하고 처리한다.

    Args:
        db: DB 세션
        service: Gmail API 빌드 객체
        lead: 대상 Lead 객체

    Returns:
        회신이 발견되어 처리되었는지 여부 (True/False)
    """
    if not lead.email:
        return False

    # 해당 리드에게 보낸 마지막 이메일 이력 조회
    last_sent = get_last_email_for_lead(db, lead.id, user_id=1)
    if not last_sent:
        # 발송 이력이 없으면 회신 감지 불필요
        return False

    # Gmail 검색 쿼리: 리드가 발송한 이메일
    query = f"from:{lead.email}"
    try:
        results = service.users().messages().list(userId="me", q=query).execute()
        messages = results.get("messages", [])
        if not messages:
            return False

        log.debug("Gmail 메시지 발견", lead_id=lead.id, company=lead.company_name, msg_count=len(messages))

        # 발견된 메세지 중 우리가 발송한 시각 이후에 온 메세지가 있는지 확인
        for msg in messages:
            msg_detail = service.users().messages().get(userId="me", id=msg["id"]).execute()
            
            # 발신 시간 파싱 (Header에서 Date 추출 또는 internalDate 사용)
            internal_date_ms = int(msg_detail.get("internalDate", 0))
            received_at = datetime.datetime.fromtimestamp(internal_date_ms / 1000.0, datetime.timezone.utc)

            # 우리가 보낸 메일 시각과 비교 (마지막 발송 시각은 naive일 수 있으므로 utc timezone 부여)
            sent_at_utc = last_sent.sent_at.replace(tzinfo=datetime.timezone.utc)
            
            if received_at > sent_at_utc:
                # 회신 메시지 상세 정보 파싱
                headers = msg_detail.get("payload", {}).get("headers", [])
                subject = ""
                for h in headers:
                    if h["name"].lower() == "subject":
                        subject = h["value"]
                        break

                raw_body = _get_email_body(msg_detail.get("payload", {}))
                cleaned_body = _clean_body_text(raw_body)

                log.info(
                    "🔥 신규 고객 회신 감지 완료!",
                    lead_id=lead.id,
                    company=lead.company_name,
                    received_at=received_at.isoformat(),
                    subject=subject,
                )

                # 1. DB에 회신 이력 저장
                create_reply(
                    db, user_id=1,
                    lead_id=lead.id,
                    email_log_id=last_sent.id,
                    received_at=received_at.replace(tzinfo=None), # naive datetime 저장
                    subject=subject,
                    body=cleaned_body,
                    synced_to_sheet=False,
                )

                # 2. 리드 상태를 'replied'로 변경
                update_lead_status(db, lead.id, user_id=1, status="replied")
                
                # 3. Google Sheets 즉시 동기화 연동을 위해 True 반환
                return True

    except Exception as e:
        log.error(
            "리드 회신 감지 실패 (스킵)",
            lead_id=lead.id,
            company=lead.company_name,
            error=str(e),
        )
        
    return False


def check_new_replies() -> None:
    """수신함 전체를 조회하여 새로운 회신이 있는지 체크하고 CRM 동기화를 트리거한다."""
    log.info("🔍 수신함 모니터링: 신규 회신 확인 루틴 가동...")
    service = _get_gmail_service()
    
    replies_found = False

    with get_db() as db:
        # 우리가 메일을 발송했고 아직 회신하지 않은 ('contacted') 상태의 리드들 조회
        contacted_leads = get_leads(db, user_id=1, status="contacted", limit=100)
        log.info("모니터링 대상 리드 조회 완료", count=len(contacted_leads))

        for lead in contacted_leads:
            if check_lead_replies(db, service, lead):
                replies_found = True

        # 새로운 회신이 있거나 수동 동기화가 필요한 경우 Google Sheets 동기화 실행
        if replies_found:
            try:
                from leadflow_common.crm.sheets_client import sync_data_to_sheets
                log.info("새 회신이 발견되어 Google Sheets CRM 실시간 동기화를 시작합니다.")
                sync_data_to_sheets()
            except ImportError:
                log.warning("sheets_client 모듈을 불러올 수 없어 Sheets 동기화를 생략합니다.")
            except Exception as e:
                log.error("Google Sheets 동기화 중 에러 발생", error=str(e))


def start_monitoring(interval_seconds: int = 300) -> None:
    """수신함 모니터링 서비스를 무한 루프로 실행한다.

    Args:
        interval_seconds: 모니터링 주기 (기본 5분)
    """
    log.info("👁️ Gmail 수신함 모니터링 서비스가 가동되었습니다.", interval_minutes=interval_seconds / 60)
    
    # 즉시 1회 실행
    try:
        check_new_replies()
    except Exception as e:
        log.error("모니터링 구동 초기 실행 실패", error=str(e))

    try:
        while True:
            time.sleep(interval_seconds)
            try:
                check_new_replies()
            except Exception as e:
                log.error("모니터링 주기 실행 중 오류 발생", error=str(e))
    except (KeyboardInterrupt, SystemExit):
        log.info("수신함 모니터링 서비스가 정상적으로 종료되었습니다.")
