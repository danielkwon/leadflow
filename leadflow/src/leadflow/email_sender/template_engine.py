"""Jinja2 기반 이메일 템플릿 엔진.

이메일 템플릿을 렌더링하고, 법적 필수 요소를 자동 삽입한다.
"""
import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from leadflow.settings import get_settings
from leadflow.utils.logging import get_logger

log = get_logger("email.template")

# 프로젝트 루트 기준 템플릿 디렉토리
_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "config", "email_templates"
)


def _get_jinja_env() -> Environment:
    """Jinja2 환경을 생성한다."""
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _generate_opt_out_link(lead_id: int) -> str:
    """수신거부 링크를 생성한다."""
    import hashlib
    settings = get_settings()
    secret = settings.opt_out_secret_key.get_secret_value()
    # 간단한 HMAC 기반 토큰 (URL-safe)
    token = hashlib.sha256(f"{lead_id}:{secret}".encode()).hexdigest()[:16]
    return f"{settings.opt_out_base_url}/unsubscribe?id={lead_id}&token={token}"


def render_email_template(
    template_name: str,
    lead: object,
    extra_vars: Optional[dict] = None,
) -> tuple[str, str]:
    """이메일 템플릿을 렌더링한다.

    Args:
        template_name: 템플릿 파일명 (확장자 제외)
        lead: Lead ORM 객체
        extra_vars: 추가 변수 딕셔너리

    Returns:
        (subject, html_body) 튜플
    """
    settings = get_settings()
    env = _get_jinja_env()

    # 템플릿 파일 로드
    template_file = f"{template_name}.html"
    try:
        template = env.get_template(template_file)
    except Exception as e:
        log.error("템플릿 로드 실패", template=template_file, error=str(e))
        raise

    # 템플릿 변수
    context = {
        "company_name": getattr(lead, "company_name", ""),
        "representative": getattr(lead, "representative", "") or "대표",
        "region": getattr(lead, "region", ""),
        "category": getattr(lead, "category", ""),
        "phone": getattr(lead, "phone", ""),
        "email": getattr(lead, "email", ""),
        "sender_name": settings.sender_name,
        "sender_email": settings.sender_email,
        "opt_out_link": _generate_opt_out_link(getattr(lead, "id", 0)),
    }
    if extra_vars:
        context.update(extra_vars)

    # 렌더링
    html_body = template.render(**context)

    # 제목 추출 (템플릿의 첫 번째 주석 또는 기본 제목)
    subject = _extract_subject(html_body, context)

    log.info("템플릿 렌더링 완료", template=template_name, company=context["company_name"])
    return subject, html_body


def _extract_subject(html: str, context: dict) -> str:
    """HTML에서 제목을 추출한다. <title> 태그 또는 기본값."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    # 기본 제목
    return f"(광고) {context.get('company_name', '')} 대표님, 현장 근로자 관리 솔루션 안내"
