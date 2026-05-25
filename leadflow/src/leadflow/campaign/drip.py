"""Drip Campaign 시퀀스 관리 및 발송 핵심 로직.

설정된 Drip 캠페인 규칙에 따라 타깃 리드들에게
순차적으로 콜드 메일 및 후속 메일(Follow-up)을 발송한다.
"""
import datetime
from typing import Any

from leadflow.db.engine import get_db
from leadflow.db.repository import (
    create_email_log,
    get_campaign_by_name,
    get_drip_candidates,
    get_email_count_for_lead,
    update_lead_status,
)
from leadflow.email_sender.gmail_client import send_email
from leadflow.email_sender.template_engine import render_email_template
from leadflow.utils.logging import get_logger

log = get_logger("campaign.drip")


def run_campaign_by_name(name: str) -> dict[str, int]:
    """캠페인 이름에 해당하는 활성 Drip 캠페인을 실행한다.

    Args:
        name: 캠페인 이름 (예: '2025-Q2')

    Returns:
        {'sent': 발송 성공 건수, 'skipped': 스킵 건수, 'errors': 에러 건수}
    """
    result = {"sent": 0, "skipped": 0, "errors": 0}
    log.info("Drip 캠페인 수동 실행 요청", campaign_name=name)

    with get_db() as db:
        campaign = get_campaign_by_name(db, name)
        if not campaign:
            log.error("캠페인을 찾을 수 없습니다", campaign_name=name)
            raise ValueError(f"캠페인을 찾을 수 없습니다: '{name}'")

        if not campaign.is_active:
            log.warning("비활성화된 캠페인입니다", campaign_name=name, campaign_id=campaign.id)
            return result

        # 발송 대상자(리드) 조회
        candidates = get_drip_candidates(db, campaign)
        log.info("Drip 발송 대상자 조회 완료", campaign_name=name, candidates_count=len(candidates))

        for lead in candidates:
            if not lead.email:
                log.debug("이메일 주소가 없어 스킵합니다", lead_id=lead.id, company=lead.company_name)
                result["skipped"] += 1
                continue

            try:
                # 현재 리드에게 보낸 발송 수 확인하여 차기 시퀀스 결정
                email_count = get_email_count_for_lead(db, lead.id, campaign.id)
                sequence_number = email_count + 1

                # 최대 시퀀스 번호 초과 검증 (안전 장치)
                if sequence_number > campaign.max_sequence:
                    log.debug(
                        "최대 발송 시퀀스를 초과하여 스킵합니다",
                        lead_id=lead.id,
                        company=lead.company_name,
                        seq=sequence_number,
                        max_seq=campaign.max_sequence,
                    )
                    result["skipped"] += 1
                    continue

                # 시퀀스별 템플릿 파일 선택
                # 1차: 캠페인 기본 지정 템플릿 (예: cold_email_v1)
                # 2차: followup_v1
                # 3차: followup_v2
                if sequence_number == 1:
                    template_name = campaign.template_name
                elif sequence_number == 2:
                    template_name = "followup_v1"
                elif sequence_number == 3:
                    template_name = "followup_v2"
                else:
                    log.warning(
                        "알 수 없는 시퀀스 번호입니다. 기본 후속 템플릿을 사용합니다",
                        seq=sequence_number,
                    )
                    template_name = "followup_v1"

                log.info(
                    "메일 발송 준비 중",
                    lead_id=lead.id,
                    company=lead.company_name,
                    sequence=sequence_number,
                    template=template_name,
                )

                # LLM 등을 통한 맞춤형 도입부 생성
                extra_vars = {}
                if sequence_number == 1:
                    if not lead.notes:
                        from leadflow.llm.email_writer import generate_personalized_intro
                        intro = generate_personalized_intro(
                            company_name=lead.company_name,
                            region=lead.region,
                            category=lead.category,
                            representative=lead.representative or "대표님",
                        )
                        lead.notes = intro
                        db.flush()
                    extra_vars["personalized_intro"] = lead.notes
                else:
                    if lead.notes:
                        extra_vars["personalized_intro"] = lead.notes

                # 템플릿 렌더링
                subject, html_body = render_email_template(
                    template_name=template_name,
                    lead=lead,
                    extra_vars=extra_vars,
                )

                # 실제 이메일 발송 (Gmail API 호출)
                message_id = send_email(
                    to_email=lead.email,
                    subject=subject,
                    html_body=html_body,
                )

                # 발송 기록(EmailLog) 저장
                create_email_log(
                    db,
                    lead_id=lead.id,
                    campaign_id=campaign.id,
                    subject=subject,
                    body_preview=html_body[:300],
                    status="sent",
                    message_id=message_id,
                    sequence_number=sequence_number,
                )

                # 리드 상태를 'contacted'로 업데이트
                update_lead_status(db, lead.id, "contacted")

                result["sent"] += 1

            except Exception as e:
                log.error(
                    "Drip 메일 발송 중 오류 발생 (스킵 후 계속 진행)",
                    lead_id=lead.id,
                    company=lead.company_name,
                    error=str(e),
                )
                result["errors"] += 1
                continue

    log.info("Drip 캠페인 실행 완료", campaign_name=name, result=result)
    return result
