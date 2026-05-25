"""데이터베이스 CRUD 작업 모듈.

모든 DB 접근은 이 모듈의 함수를 통해 이루어진다.
"""
import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from sales_pipeline.db.models import Campaign, EmailLog, Lead, Reply
from sales_pipeline.utils.logging import get_logger

log = get_logger("db.repository")


# === Lead CRUD ===


def create_lead(db: Session, **kwargs) -> Lead:
    """새 리드를 생성한다."""
    lead = Lead(**kwargs)
    db.add(lead)
    db.flush()
    log.info("리드 생성 완료", lead_id=lead.id, company=lead.company_name, region=lead.region)
    return lead


def get_lead_by_id(db: Session, lead_id: int) -> Optional[Lead]:
    """ID로 리드를 조회한다."""
    return db.query(Lead).filter(Lead.id == lead_id).first()


def find_duplicate_lead(db: Session, company_name: str, phone: Optional[str] = None) -> Optional[Lead]:
    """업체명 + 전화번호 조합으로 중복 리드를 확인한다."""
    query = db.query(Lead).filter(Lead.company_name == company_name)
    if phone:
        query = query.filter(Lead.phone == phone)
    return query.first()


def get_leads(
    db: Session,
    status: Optional[str] = None,
    region: Optional[str] = None,
    has_email: Optional[bool] = None,
    opt_out: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[Lead]:
    """조건에 맞는 리드 목록을 조회한다."""
    query = db.query(Lead).filter(Lead.opt_out == opt_out)
    if status:
        query = query.filter(Lead.status == status)
    if region:
        query = query.filter(Lead.region == region)
    if has_email is True:
        query = query.filter(Lead.email.isnot(None), Lead.email != "")
    elif has_email is False:
        query = query.filter((Lead.email.is_(None)) | (Lead.email == ""))
    return query.order_by(Lead.created_at.desc()).limit(limit).offset(offset).all()


def update_lead_status(db: Session, lead_id: int, status: str) -> Optional[Lead]:
    """리드 상태를 업데이트한다."""
    lead = get_lead_by_id(db, lead_id)
    if lead:
        old_status = lead.status
        lead.status = status
        db.flush()
        log.info("리드 상태 변경", lead_id=lead_id, old=old_status, new=status)
    return lead


def set_lead_opt_out(db: Session, lead_id: int) -> Optional[Lead]:
    """리드를 수신거부 처리한다."""
    lead = get_lead_by_id(db, lead_id)
    if lead:
        lead.opt_out = True
        lead.opt_out_date = datetime.datetime.now(datetime.timezone.utc)
        db.flush()
        log.info("수신거부 처리 완료", lead_id=lead_id, company=lead.company_name)
    return lead


def update_lead_email(db: Session, lead_id: int, email: str) -> Optional[Lead]:
    """리드의 이메일 주소를 업데이트한다."""
    lead = get_lead_by_id(db, lead_id)
    if lead:
        lead.email = email
        db.flush()
        log.info("리드 이메일 업데이트", lead_id=lead_id, email=email)
    return lead


def count_leads(db: Session, status: Optional[str] = None) -> int:
    """리드 수를 카운트한다."""
    query = db.query(func.count(Lead.id))
    if status:
        query = query.filter(Lead.status == status)
    return query.scalar() or 0


# === Campaign CRUD ===


def create_campaign(db: Session, **kwargs) -> Campaign:
    """새 캠페인을 생성한다."""
    campaign = Campaign(**kwargs)
    db.add(campaign)
    db.flush()
    log.info("캠페인 생성", campaign_id=campaign.id, name=campaign.name)
    return campaign


def get_campaign_by_name(db: Session, name: str) -> Optional[Campaign]:
    """이름으로 캠페인을 조회한다."""
    return db.query(Campaign).filter(Campaign.name == name).first()


def get_active_campaigns(db: Session) -> list[Campaign]:
    """활성 캠페인 목록을 조회한다."""
    return db.query(Campaign).filter(Campaign.is_active == True).all()  # noqa: E712


# === EmailLog CRUD ===


def create_email_log(db: Session, **kwargs) -> EmailLog:
    """이메일 발송 기록을 생성한다."""
    email_log = EmailLog(**kwargs)
    db.add(email_log)
    db.flush()
    log.info("이메일 발송 기록", log_id=email_log.id, lead_id=email_log.lead_id, seq=email_log.sequence_number)
    return email_log


def get_last_email_for_lead(
    db: Session, lead_id: int, campaign_id: Optional[int] = None
) -> Optional[EmailLog]:
    """리드에게 마지막으로 발송한 이메일을 조회한다."""
    query = db.query(EmailLog).filter(EmailLog.lead_id == lead_id)
    if campaign_id:
        query = query.filter(EmailLog.campaign_id == campaign_id)
    return query.order_by(EmailLog.sent_at.desc()).first()


def get_email_count_for_lead(
    db: Session, lead_id: int, campaign_id: Optional[int] = None
) -> int:
    """리드에게 발송한 이메일 수를 카운트한다."""
    query = db.query(func.count(EmailLog.id)).filter(EmailLog.lead_id == lead_id)
    if campaign_id:
        query = query.filter(EmailLog.campaign_id == campaign_id)
    return query.scalar() or 0


def get_drip_candidates(
    db: Session,
    campaign: Campaign,
    as_of: Optional[datetime.datetime] = None,
) -> list[Lead]:
    """Drip 발송 대상 리드를 조회한다.

    조건:
    - 이메일이 있음
    - 수신거부 아님
    - 상태가 replied/converted가 아님
    - 마지막 발송 후 interval_days 경과
    - 발송 횟수 < max_sequence
    """
    if as_of is None:
        as_of = datetime.datetime.now()
    elif as_of.tzinfo is not None:
        as_of = as_of.replace(tzinfo=None)

    cutoff = as_of - datetime.timedelta(days=campaign.interval_days)

    # 이메일 있고, 수신거부 아니고, 아직 회신/전환 안 된 리드
    leads = db.query(Lead).filter(
        Lead.email.isnot(None),
        Lead.email != "",
        Lead.opt_out == False,  # noqa: E712
        Lead.status.notin_(["replied", "converted"]),
    ).all()

    candidates = []
    for lead in leads:
        email_count = get_email_count_for_lead(db, lead.id, campaign.id)
        if email_count >= campaign.max_sequence:
            continue

        last_email = get_last_email_for_lead(db, lead.id, campaign.id)
        if last_email and last_email.sent_at > cutoff:
            continue

        candidates.append(lead)

    return candidates


# === Reply CRUD ===


def create_reply(db: Session, **kwargs) -> Reply:
    """회신 기록을 생성한다."""
    reply = Reply(**kwargs)
    db.add(reply)
    db.flush()
    log.info("회신 기록 생성", reply_id=reply.id, lead_id=reply.lead_id)
    return reply


def get_unsynced_replies(db: Session) -> list[Reply]:
    """아직 Google Sheets에 동기화되지 않은 회신을 조회한다."""
    return db.query(Reply).filter(Reply.synced_to_sheet == False).all()  # noqa: E712


def mark_reply_synced(db: Session, reply_id: int) -> None:
    """회신을 동기화 완료로 표시한다."""
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if reply:
        reply.synced_to_sheet = True
        db.flush()
