"""네이버 지도 웹 스크래핑을 통한 업체 정보 수집.

Playwright 헤드리스 브라우저 환경을 활용하여 네이버 지도의 세션 및 보안 필터를 통과하고,
비공식 통합 검색 API(allSearch)를 직접 호출하여 API Key 없이
업체명, 전화번호, 주소, 도로명 주소, 홈페이지 URL 등의 모든 영업 정보를 정확하고 안전하게 대량 수집합니다.
"""
import re
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from sales_pipeline.db.engine import get_db
from sales_pipeline.db.repository import create_lead, find_duplicate_lead
from sales_pipeline.utils.logging import get_logger

log = get_logger("scraper.naver_map")

# HTML 태그 제거 패턴
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    """HTML 태그를 제거한다."""
    if not text:
        return ""
    return _HTML_TAG_RE.sub("", text).strip()


def _normalize_phone(phone: str) -> str:
    """전화번호를 정규화한다. 하이픈 및 공백 제거."""
    if not phone:
        return ""
    return re.sub(r"[\s\-()]", "", phone).strip()


def fetch_leads_via_playwright(
    query: str,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Playwright 헤드리스 브라우저를 기동하여 검색을 수행하고,
    실시간으로 나가는 allSearch API 응답을 가로채서 안전하게 대량 수집합니다.
    (네이버의 토큰 재사용 방지 필터인 CE_TOKEN_REUSE를 원천 회피)
    """
    from playwright.sync_api import sync_playwright

    collected_items = []
    seen_ids = set()

    log.info("Playwright 리스너 기반 크롤러 기동...", query=query)

    with sync_playwright() as p:
        # 헤드리스 크롬 실행 (필요 시 headless=True)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ko-KR",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        # 1. API 응답 인터셉터 리스너 등록
        def handle_response(response):
            url = response.url
            if "api/search/allSearch" in url and response.status == 200:
                try:
                    res_json = response.json()
                    result = res_json.get("result") or {}
                    
                    # 캡차 차단 필터 감출
                    if result.get("ncaptcha"):
                        log.error("네이버 지도 자동 크롤링 감지 경고 (CAPTCHA 차단)", uuid=result["ncaptcha"].get("uuid"))
                        return

                    place_data = result.get("place") or {}
                    items = place_data.get("list") or []
                    
                    added_count = 0
                    for item in items:
                        item_id = item.get("id")
                        if item_id and item_id not in seen_ids:
                            seen_ids.add(item_id)
                            collected_items.append(item)
                            added_count += 1
                            
                    if added_count > 0:
                        log.info(f"실시간 API 응답 감지 수집 성공: {added_count}건 추가 (누적: {len(collected_items)}건)")
                except Exception as e:
                    log.error("API 응답 JSON 파싱 실패", error=str(e))

        page.on("response", handle_response)

        # 2. 네이버 지도 서비스 접속
        log.info("네이버 지도 세션 접속 초기화 중...")
        page.goto("https://map.naver.com/p", timeout=30000)
        page.wait_for_timeout(3000)

        # 3. 실제 검색창 엘리먼트에 검색어 입력 및 엔터
        log.info("검색어 입력창 탐색 및 검색 실행 중...", query=query)
        try:
            search_input = page.wait_for_selector("input.input_search", timeout=5000)
            search_input.fill(query)
            page.keyboard.press("Enter")
            # 1페이지 호출 대기
            page.wait_for_timeout(5000)
        except Exception as e:
            log.error("검색어 입력 및 실행 실패", error=str(e))
            browser.close()
            return []

        # 4. 페이징 루프 구동 (UI 조작 시뮬레이션)
        current_page = 2
        last_collected_count = len(collected_items)

        try:
            # searchIframe 대기 및 locator 로드
            iframe_element = page.wait_for_selector("iframe#searchIframe", timeout=5000)
            if iframe_element:
                log.info("searchIframe 발견 완료. 순차적 페이징 수집 시작.")
                iframe = page.frame_locator("iframe#searchIframe")

                while len(collected_items) < max_results:
                    # 숫자 버튼이 활성화되어 있는지 체크 (예: 2, 3, 4...)
                    page_btn = iframe.locator(f"a:has-text('{current_page}')").first
                    
                    if page_btn.is_visible():
                        log.info(f"UI 페이지 {current_page} 이동 버튼 클릭 중...")
                        page_btn.click()
                        # 로딩 안정화 시간 부여
                        page.wait_for_timeout(4000)
                        
                        # 수집 증가량 확인
                        current_count = len(collected_items)
                        if current_count == last_collected_count:
                            # 3초 더 대기해봄 (네트워크 딜레이 대비)
                            page.wait_for_timeout(3000)
                            current_count = len(collected_items)
                            
                        if current_count == last_collected_count:
                            log.info("클릭 후 신규 수집 데이터 없음. 마지막 페이지 도달로 판단.")
                            break
                            
                        last_collected_count = current_count
                        current_page += 1
                    else:
                        # 숫자 버튼이 보이지 않는 경우, '다음' 페이지 뭉치 묶음 화살표가 있는지 확인
                        next_btn = iframe.locator("a:has-text('다음')").first
                        if next_btn.is_visible() and next_btn.get_attribute("aria-disabled") != "true":
                            log.info("UI '다음' 묶음 페이지 화살표 버튼 클릭 중...")
                            next_btn.click()
                            page.wait_for_timeout(4000)
                            
                            current_count = len(collected_items)
                            if current_count == last_collected_count:
                                break
                            last_collected_count = current_count
                        else:
                            log.info("더 이상 이동할 수 있는 페이지 이동 버튼이 발견되지 않습니다. 탐색 종료.")
                            break
            else:
                log.warning("searchIframe을 찾을 수 없어 단일 1페이지 데이터로 스크래핑을 종료합니다.")
        except Exception as e:
            log.error("searchIframe 페이징 조작 중 에러 발생 (단일 페이지 수집으로 종료)", error=str(e))

        browser.close()

    return collected_items[:max_results]


def scrape_leads(
    region: str,
    keyword: str,
    max_results: int = 100,
    delay_seconds: float = 0.5,
) -> dict[str, int]:
    """특정 지역/키워드로 네이버 지도 웹페이지를 스크래핑하여 업체를 수집하고 DB에 저장한다. (API Key 불필요)

    Args:
        region: 지역명 (예: '서울', '경기')
        keyword: 검색 키워드 (예: '인력사무소', '건설사')
        max_results: 최대 수집 건수
        delay_seconds: 보완 딜레이 (초)

    Returns:
        {'added': 추가 건수, 'skipped': 중복 스킵, 'errors': 오류 건수}
    """
    query = f"{region} {keyword}"
    result = {"added": 0, "skipped": 0, "errors": 0}
    
    log.info("비공식 웹 브라우저 크롤링 파이프라인 시작", region=region, keyword=keyword, max_results=max_results)
    
    try:
        items = fetch_leads_via_playwright(query=query, max_results=max_results)
    except Exception as e:
        log.error("Playwright 크롤러 기동 실패 (드라이버 미완료일 수 있음)", error=str(e))
        result["errors"] += 1
        return result

    if not items:
        log.warning("수집된 데이터가 없습니다.", query=query)
        return result

    with get_db() as db:
        for item in items:
            try:
                company_name = _clean_html(item.get("name", ""))
                phone = _normalize_phone(item.get("tel", ""))
                
                if not company_name:
                    continue

                # 중복 확인
                existing = find_duplicate_lead(db, company_name, phone if phone else None)
                if existing:
                    result["skipped"] += 1
                    log.debug("중복 리드 스킵", company=company_name)
                    continue

                # 도로명 주소 또는 일반 주소 확보
                address = item.get("address")
                road_address = item.get("roadAddress")
                homepage = item.get("homePage")
                
                # 플레이스 고유 상세 URL 구성
                place_id = item.get("id")
                naver_link = f"https://map.naver.com/p/entry/place/{place_id}" if place_id else None

                create_lead(
                    db,
                    company_name=company_name,
                    phone=phone if phone else None,
                    address=address,
                    road_address=road_address,
                    region=region,
                    category=keyword,
                    source="naver_map_scraper",
                    website_url=homepage if homepage else None,
                    naver_link=naver_link,
                )
                result["added"] += 1

            except Exception as e:
                log.error("리드 저장 실패", error=str(e), company=item.get("name"))
                result["errors"] += 1
                
    log.info("스크래핑 완료", region=region, keyword=keyword, result=result)
    return result
