"""업체 웹사이트에서 이메일 주소를 스크래핑하는 모듈.

네이버 API에는 이메일이 포함되지 않으므로,
수집된 웹사이트 URL에 접속하여 이메일을 2차 탐색한다.
"""
import random
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from leadflow.db.engine import get_db
from leadflow.db.repository import get_leads, update_lead_email
from leadflow.utils.logging import get_logger

log = get_logger("scraper.website")

# 이메일 추출 정규표현식
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# 제외할 이메일 패턴 (일반적인 이미지/파일 확장자 등)
_EXCLUDE_PATTERNS = {
    "example.com", "email.com", "domain.com", "your",
    ".png", ".jpg", ".gif", ".svg", ".webp",
}

# 연락처 페이지 키워드
_CONTACT_KEYWORDS = [
    "contact", "문의", "연락처", "about", "회사소개",
    "company", "info", "문의하기", "오시는길",
]

# User-Agent 목록
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _is_valid_email(email: str) -> bool:
    """추출된 이메일이 유효한지 검증한다."""
    email_lower = email.lower()
    for pattern in _EXCLUDE_PATTERNS:
        if pattern in email_lower:
            return False
    # 너무 짧거나 긴 이메일 제외
    if len(email) < 5 or len(email) > 100:
        return False
    return True


def _extract_emails_from_html(html: str) -> list[str]:
    """HTML에서 이메일 주소를 추출한다."""
    emails = _EMAIL_RE.findall(html)
    # mailto: 링크에서도 추출
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()
            if email:
                emails.append(email)

    # 중복 제거 및 유효성 검증
    seen: set[str] = set()
    valid_emails: list[str] = []
    for email in emails:
        email = email.strip().lower()
        if email not in seen and _is_valid_email(email):
            seen.add(email)
            valid_emails.append(email)

    return valid_emails


def _find_contact_pages(base_url: str, html: str) -> list[str]:
    """메인 페이지에서 연락처/문의 페이지 링크를 찾는다."""
    soup = BeautifulSoup(html, "html.parser")
    contact_urls: list[str] = []

    for link in soup.find_all("a", href=True):
        href = link["href"].lower()
        text = link.get_text().lower().strip()
        combined = f"{href} {text}"

        if any(kw in combined for kw in _CONTACT_KEYWORDS):
            full_url = urljoin(base_url, link["href"])
            # 같은 도메인만
            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                contact_urls.append(full_url)

    return list(set(contact_urls))[:3]  # 최대 3개 페이지만


def scrape_email_from_website(url: str) -> Optional[str]:
    """웹사이트에서 이메일 주소를 추출한다.

    전략:
    1. 메인 페이지에서 이메일 검색
    2. 없으면 연락처/문의 페이지를 찾아서 2차 검색

    Args:
        url: 업체 웹사이트 URL

    Returns:
        추출된 이메일 주소 또는 None
    """
    if not url:
        return None

    # URL 정규화
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    headers = {"User-Agent": random.choice(_USER_AGENTS)}

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, verify=False) as client:
            # 1단계: 메인 페이지
            response = client.get(url, headers=headers)
            response.raise_for_status()
            html = response.text

            emails = _extract_emails_from_html(html)
            if emails:
                log.info("메인 페이지에서 이메일 발견", url=url, email=emails[0])
                return emails[0]

            # 2단계: 연락처 페이지 탐색
            contact_pages = _find_contact_pages(url, html)
            for contact_url in contact_pages:
                time.sleep(random.uniform(0.5, 1.5))
                try:
                    resp = client.get(contact_url, headers=headers)
                    resp.raise_for_status()
                    emails = _extract_emails_from_html(resp.text)
                    if emails:
                        log.info("연락처 페이지에서 이메일 발견", url=contact_url, email=emails[0])
                        return emails[0]
                except Exception:
                    continue

    except httpx.TimeoutException:
        log.warning("웹사이트 타임아웃", url=url)
    except httpx.HTTPStatusError as e:
        log.warning("웹사이트 HTTP 오류", url=url, status=e.response.status_code)
    except Exception as e:
        log.warning("웹사이트 스크래핑 실패", url=url, error=str(e))

    return None


def enrich_leads_with_email(
    limit: int = 50,
    delay_range: tuple[float, float] = (1.0, 3.0),
) -> dict[str, int]:
    """이메일이 없는 리드의 웹사이트에서 이메일을 추출하여 업데이트한다.

    Args:
        limit: 처리할 최대 리드 수
        delay_range: 요청 간 딜레이 범위 (초)

    Returns:
        {'found': 이메일 발견 수, 'failed': 실패 수}
    """
    result = {"found": 0, "failed": 0}

    with get_db() as db:
        # 이메일 없고, 웹사이트 URL이 있는 리드 조회
        leads = get_leads(db, has_email=False, limit=limit)
        leads_with_url = [l for l in leads if l.website_url]

        log.info("웹사이트 이메일 추출 시작", total=len(leads_with_url))

        for lead in leads_with_url:
            email = scrape_email_from_website(lead.website_url)
            if email:
                update_lead_email(db, lead.id, email)
                result["found"] += 1
            else:
                result["failed"] += 1

            time.sleep(random.uniform(*delay_range))

    log.info("웹사이트 이메일 추출 완료", result=result)
    return result
