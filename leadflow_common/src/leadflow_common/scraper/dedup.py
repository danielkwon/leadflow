"""리드 중복 제거 유틸리티.

업체명과 전화번호를 정규화하여 중복을 판별한다.
"""
import re
from typing import Optional

from leadflow_common.utils.logging import get_logger

log = get_logger("scraper.dedup")

# 제거할 패턴: (주), ㈜, 주식회사 등
_CORP_PATTERNS = re.compile(r"[\(\(]주[\)\)]|㈜|주식회사|\(유\)|유한회사|\s+")


def normalize_company_name(name: str) -> str:
    """업체명을 정규화한다.

    - (주), ㈜, 주식회사 등 제거
    - 공백 제거
    - 소문자 변환
    """
    normalized = _CORP_PATTERNS.sub("", name)
    normalized = normalized.strip().lower()
    return normalized


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """전화번호를 정규화한다.

    - 하이픈, 공백, 괄호 제거
    - 국가코드 +82 → 0 변환
    """
    if not phone:
        return None
    cleaned = re.sub(r"[\s\-()\+]", "", phone)
    if cleaned.startswith("82"):
        cleaned = "0" + cleaned[2:]
    return cleaned if cleaned else None


def is_duplicate(name1: str, name2: str, phone1: Optional[str] = None, phone2: Optional[str] = None) -> bool:
    """두 업체가 중복인지 판별한다.

    업체명이 정규화 후 동일하면 중복.
    전화번호가 둘 다 있으면 전화번호도 비교.
    """
    norm_name1 = normalize_company_name(name1)
    norm_name2 = normalize_company_name(name2)

    if norm_name1 != norm_name2:
        return False

    # 이름이 같으면 전화번호 추가 비교
    if phone1 and phone2:
        return normalize_phone(phone1) == normalize_phone(phone2)

    # 전화번호 중 하나라도 없으면 이름만으로 중복 판정
    return True
