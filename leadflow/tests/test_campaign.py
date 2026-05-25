"""리드 수집, 중복 제거, Drip 캠페인 및 AI 도입부 생성에 대한 통합 테스트 모듈.

Rule 5 (No Mocking) 원칙에 따라 가짜 모의 객체 대신 실제 인메모리 SQLite DB 흐름을 검증한다.
"""
import datetime
import pytest
from sqlalchemy.orm import Session

from leadflow.db.models import Lead, Campaign, EmailLog, Reply
from leadflow.db.repository import (
    create_lead,
    find_duplicate_lead,
    create_campaign,
    get_drip_candidates,
    get_email_count_for_lead,
    create_email_log,
)
from leadflow.scraper.dedup import is_duplicate, normalize_company_name, normalize_phone
from leadflow.llm.email_writer import generate_personalized_intro
from leadflow.email_sender.template_engine import render_email_template


def test_lead_lifecycle_and_duplication(db_session: Session):
    """리드 수집 및 중복 판별 로직 통합 검증."""
    # 1. 신규 리드 생성
    lead = create_lead(
        db_session,
        company_name="(주)대성인력공사",
        representative="홍길동",
        phone="02-123-4567",
        email="daeseong@manpower.com",
        region="서울",
        category="인력사무소",
    )
    assert lead.id is not None
    assert lead.status == "new"

    # 2. 중복 검출 검증
    # 2-1) 동일 이름 + 동일 번호
    dup_lead = find_duplicate_lead(db_session, "(주)대성인력공사", "02-123-4567")
    assert dup_lead is not None
    assert dup_lead.id == lead.id

    # 2-2) 정규화 유틸리티를 활용한 중복 검증
    assert is_duplicate("(주)대성인력공사", "대성인력공사", "02-123-4567", "021234567") is True
    assert is_duplicate("대성인력공사", "대성인력공사", "02-123-4567", "02-999-9999") is False


def test_drip_campaign_logic(db_session: Session):
    """Drip 캠페인 발송 대상자 필터링 및 시퀀스 흐름 통합 검증."""
    # 1. 테스트 캠페인 생성 (30일 주기, 최대 3회 발송)
    campaign = create_campaign(
        db_session,
        name="2026-B2B",
        template_name="cold_email_v1",
        interval_days=30,
        max_sequence=3,
    )

    # 2. 테스트용 리드 생성
    # 2-1) 발송 가능 리드 (이메일 보유, new 상태)
    lead_valid = create_lead(
        db_session,
        company_name="현대건설인력",
        email="hyundai@manpower.com",
        region="경기",
        category="인력사무소",
    )
    # 2-2) 이메일이 없는 리드 (스킵 대상)
    lead_no_email = create_lead(
        db_session,
        company_name="삼성건설인력",
        email=None,
        region="경기",
        category="인력사무소",
    )
    # 2-3) 이미 수신거부한 리드 (스킵 대상)
    lead_opt_out = create_lead(
        db_session,
        company_name="LG건설인력",
        email="lg@manpower.com",
        region="경기",
        category="인력사무소",
        opt_out=True,
    )

    # 3. Drip 발송 후보군 조회 검증
    candidates = get_drip_candidates(db_session, campaign)
    assert len(candidates) == 1
    assert candidates[0].id == lead_valid.id

    # 4. 1차 메일 발송 시뮬레이션
    create_email_log(
        db_session,
        lead_id=lead_valid.id,
        campaign_id=campaign.id,
        subject="[1차] 근로자 관리 솔루션 안내",
        sequence_number=1,
    )
    db_session.commit()

    # 5. 발송 즉시는 다시 발송 후보군에서 제외되는지 검사 (30일이 경과되지 않았으므로 제외)
    candidates_after_sent = get_drip_candidates(db_session, campaign)
    assert len(candidates_after_sent) == 0

    # 6. 31일이 경과한 시점 시뮬레이션 (as_of 날짜 강제 이동)
    future_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=31)
    candidates_future = get_drip_candidates(db_session, campaign, as_of=future_time)
    assert len(candidates_future) == 1
    assert candidates_future[0].id == lead_valid.id


def test_llm_fallback_personalized_intro():
    """OpenAI API가 비활성화되거나 오류 상황 시 Fallback 로직 작동 검증."""
    intro = generate_personalized_intro(
        company_name="대성인력공사",
        region="서울 영등포구",
        category="인력사무소",
        representative="김대표",
    )
    # API Key 미설정 시 Fallback 문장이 자연스럽게 조립되는지 검증
    assert "서울 영등포구" in intro
    assert "대성인력공사" in intro
    assert "김대표 대표님" in intro
    assert "노고가 많으십니다" in intro


def test_email_template_rendering(db_session: Session):
    """Jinja2 템플릿 렌더링 및 수신거부 암호화 토큰 링크 결합성 검증."""
    lead = create_lead(
        db_session,
        company_name="대성인력공사",
        representative="김대표",
        email="test@test.com",
        region="서울",
        category="인력사무소",
    )
    
    subject, html_body = render_email_template(
        template_name="cold_email_v1",
        lead=lead,
    )
    
    assert "대성인력공사" in html_body
    assert "김대표" in html_body
    assert "unsubscribe" in html_body  # 수신거부 링크 포함 여부
    assert "token=" in html_body       # HMAC 토큰 탑재 여부
