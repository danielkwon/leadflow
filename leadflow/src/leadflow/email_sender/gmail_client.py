"""Gmail API 기반 이메일 발송 클라이언트.

Google Workspace Gmail API를 사용하여 이메일을 발송한다.
OAuth 2.0 인증 사용.
"""
import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from leadflow.db.engine import get_db
from leadflow.db.repository import create_email_log, get_lead_by_id
from leadflow.email_sender.template_engine import render_email_template
from leadflow.settings import get_settings
from leadflow.utils.logging import get_logger

log = get_logger("email.gmail")

# Gmail API 권한 범위
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _get_gmail_service():
    """Gmail API 서비스 객체를 생성한다.

    최초 실행 시 브라우저 기반 OAuth 인증이 필요하다.
    이후에는 토큰 파일로 자동 인증.
    """
    settings = get_settings()
    creds = None

    # 기존 토큰 로드
    if os.path.exists(settings.gmail_token_path):
        creds = Credentials.from_authorized_user_file(
            settings.gmail_token_path, SCOPES
        )

    # 토큰이 없거나 만료된 경우
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Gmail 토큰 갱신 중...")
            creds.refresh(Request())
        else:
            if not os.path.exists(settings.gmail_credentials_path):
                raise FileNotFoundError(
                    f"Gmail OAuth credentials 파일을 찾을 수 없습니다: "
                    f"{settings.gmail_credentials_path}\n"
                    f"Google Cloud Console에서 OAuth 2.0 클라이언트 ID를 생성하고 "
                    f"JSON 파일을 다운로드하세요."
                )
            log.info("Gmail OAuth 인증 시작 — 브라우저가 열립니다...")
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.gmail_credentials_path, SCOPES
            )
            creds = flow.run_local_server(port=0)

        # 토큰 저장
        os.makedirs(os.path.dirname(settings.gmail_token_path), exist_ok=True)
        with open(settings.gmail_token_path, "w") as token_file:
            token_file.write(creds.to_json())
        log.info("Gmail 토큰 저장 완료", path=settings.gmail_token_path)

    return build("gmail", "v1", credentials=creds)


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
) -> str:
    """Gmail API로 이메일을 발송한다.

    Args:
        to_email: 수신자 이메일
        subject: 이메일 제목
        html_body: HTML 본문
        plain_body: 텍스트 본문 (없으면 HTML에서 자동 추출)

    Returns:
        Gmail Message ID

    Raises:
        Exception: 발송 실패 시
    """
    settings = get_settings()
    service = _get_gmail_service()

    # MIME 메시지 구성
    message = MIMEMultipart("alternative")
    message["to"] = to_email
    message["from"] = f"{settings.sender_name} <{settings.sender_email}>"
    message["subject"] = subject

    # 텍스트 버전
    if not plain_body:
        from bs4 import BeautifulSoup
        plain_body = BeautifulSoup(html_body, "html.parser").get_text(separator="\n")
    message.attach(MIMEText(plain_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    # Base64 인코딩
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    # 발송
    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    message_id = sent.get("id", "")
    log.info("이메일 발송 완료", to=to_email, subject=subject, message_id=message_id)
    return message_id


def send_test_email(lead_id: int) -> None:
    """단건 테스트 이메일을 발송한다.

    Args:
        lead_id: 테스트 대상 리드 ID
    """
    with get_db() as db:
        lead = get_lead_by_id(db, lead_id)
        if not lead:
            raise ValueError(f"리드를 찾을 수 없습니다: ID {lead_id}")
        if not lead.email:
            raise ValueError(f"리드에 이메일이 없습니다: {lead.company_name} (ID {lead_id})")

        # 템플릿 렌더링
        subject, html_body = render_email_template(
            template_name="cold_email_v1",
            lead=lead,
        )

        # 발송
        message_id = send_email(
            to_email=lead.email,
            subject=subject,
            html_body=html_body,
        )

        # 발송 기록
        create_email_log(
            db,
            lead_id=lead.id,
            subject=subject,
            body_preview=html_body[:500],
            status="sent",
            message_id=message_id,
            sequence_number=1,
        )

    log.info("테스트 이메일 발송 완료", lead_id=lead_id, company=lead.company_name)
