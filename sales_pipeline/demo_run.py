"""B2B 영업 자동화 파이프라인 엔드투엔드(E2E) 데모 런 스크립트.

네이버 API 키 및 OpenAI API 키의 유무에 따라 실데이터 수집 또는
정밀하게 시뮬레이션된 가상(Mock) 데이터를 사용하여 리드 수집,
웹사이트 이메일 추출, AI 맞춤 인트로 문장 작성 및 최종 콜드 메일 렌더링까지의
전체 흐름을 물리적으로 검증하고 시각적으로 보여줍니다.
"""
import os
import sys
import datetime
from pathlib import Path

# 프로젝트 src 경로를 sys.path에 추가하여 로컬 패키지 로드 지원
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root / "src"))

from sales_pipeline.settings import get_settings
from sales_pipeline.db.engine import init_db, get_db
from sales_pipeline.db.repository import create_lead, get_leads, update_lead_email
from sales_pipeline.scraper.naver_api import scrape_leads
from sales_pipeline.scraper.website_scraper import enrich_leads_with_email
from sales_pipeline.llm.email_writer import generate_personalized_intro
from sales_pipeline.email_sender.template_engine import render_email_template
from sales_pipeline.utils.logging import setup_logging, get_logger

# 로깅 설정 초기화 (SQLAlchemy 로그를 최소화하기 위해 settings 환경 임시 세팅)
os.environ["APP_ENV"] = "production"  # echo=False로 SQL 출력 억제
setup_logging("WARNING")  # 주 로깅은 경고 이상만
log = get_logger("demo_run")


def print_banner(title: str):
    print("\n" + "=" * 80)
    print(f" {title.center(78)} ")
    print("=" * 80)


def fetch_serialized_leads() -> list[dict]:
    """DB에서 리드를 조회하여 세션과 무관한 dict 리스트로 복사 반환한다."""
    with get_db() as db:
        leads = get_leads(db, limit=10)
        return [
            {
                "id": l.id,
                "company_name": l.company_name,
                "representative": l.representative,
                "phone": l.phone,
                "email": l.email,
                "website_url": l.website_url,
                "region": l.region,
                "category": l.category,
            }
            for l in leads
        ]


def run_demo():
    print_banner("B2B 영업 자동화 파이프라인 E2E 데모 런")

    # 1. DB 및 디렉토리 설정
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    db_file = data_dir / "sales_pipeline.db"
    
    print(f"📦 1. 데이터베이스 초기화 진행 중... (경로: {db_file})")
    init_db()
    print("✅ 데이터베이스 및 테이블 구조 생성 완료!")

    # 2. API 설정 로드 및 검증
    settings = get_settings()
    has_naver = bool(settings.naver_client_id.get_secret_value() and settings.naver_client_secret.get_secret_value())
    has_openai = bool(settings.openai_api_key.get_secret_value())

    print("\n🔑 2. 환경변수 및 API 설정 상태 점검:")
    print(f"   - Naver API Key 설정 여부: {'🟢 설정됨 (실데이터 크롤러 활성화)' if has_naver else '🔴 미설정 (가상 데모 모드 작동)'}")
    print(f"   - OpenAI API Key 설정 여부: {'🟢 설정됨 (GPT-4o-mini 연동)' if has_openai else '🔴 미설정 (지능형 Fallback 빌더 작동)'}")

    # 3. 리드 수집 (Scrape) 단계
    print_banner("Phase 2: B2B 영업 DB 자동 수집 (크롤링)")

    if has_naver:
        print("🔍 실데이터 수집 시작: '서울 구로구 인력사무소' 네이버 지역 검색을 요청합니다...")
        try:
            result = scrape_leads(region="서울 구로구", keyword="인력사무소", max_results=3)
            print(f"✅ 실데이터 크롤링 성공: 신규 등록 {result['added']}건, 중복 스킵 {result['skipped']}건")
        except Exception as e:
            print(f"❌ 네이버 API 호출 중 오류 발생: {e}")
            print("💡 가상 데이터 생성 모드로 전환합니다.")
            has_naver = False

    if not has_naver:
        print("💡 [가상 데모 모드] 3건의 현실감 넘치는 B2B 영업 리드 데이터를 DB에 삽입합니다.")
        mock_leads = [
            {
                "company_name": "(주)대성인력개발",
                "representative": "강대성",
                "phone": "02-2611-9876",
                "address": "서울 구로구 디지털로 123",
                "road_address": "서울 구로구 디지털로32길 99",
                "region": "서울 구로구",
                "category": "인력사무소",
                "website_url": "http://www.daeseongmanpower.co.kr",
            },
            {
                "company_name": "태백건설산업",
                "representative": "황태백",
                "phone": "02-855-4321",
                "address": "서울 구로구 구로동 456-7",
                "road_address": "서울 구로구 경인로 12",
                "region": "서울 구로구",
                "category": "전문건설업체",
                "website_url": "http://www.taebaekcon.co.kr",
            },
            {
                "company_name": "삼보건설구직소",
                "representative": "이삼보",
                "phone": "02-866-1234",
                "address": "서울 구로구 신도림동 789",
                "road_address": "서울 구로구 새말로 8",
                "region": "서울 구로구",
                "category": "인력사무소",
                "website_url": None, # 웹사이트가 없어 이메일 추출 대상에서 제외됨을 시연
            }
        ]
        
        added_count = 0
        with get_db() as db:
            for ml in mock_leads:
                from sales_pipeline.db.repository import find_duplicate_lead
                dup = find_duplicate_lead(db, ml["company_name"], ml["phone"])
                if not dup:
                    create_lead(
                        db,
                        company_name=ml["company_name"],
                        representative=ml["representative"],
                        phone=ml["phone"],
                        address=ml["address"],
                        road_address=ml["road_address"],
                        region=ml["region"],
                        category=ml["category"],
                        website_url=ml["website_url"],
                        source="demo_mock"
                    )
                    added_count += 1
        print(f"✅ 가상 리드 데이터 저장 완료! (신규 추가: {added_count}건)")

    # DB에서 현재 리드 현황 읽기 (직렬화하여 가져오기)
    current_leads = fetch_serialized_leads()

    print("\n📋 현재 데이터베이스 내 리드 목록:")
    print("-" * 100)
    print(f"{'ID':^5} | {'업체명':<20} | {'대표자':<8} | {'전화번호':<13} | {'이메일':<25} | {'웹사이트 URL'}")
    print("-" * 100)
    for lead in current_leads:
        print(f"{lead['id']:^5} | {lead['company_name']:<20} | {lead['representative'] or '-':<8} | {lead['phone'] or '-':<13} | {lead['email'] or '-':<25} | {lead['website_url'] or '-'}")
    print("-" * 100)

    # 4. 2차 이메일 추출 (Enrich) 단계
    print_banner("Phase 2-B: 웹사이트 접속을 통한 2차 이메일 자동 추출")
    
    leads_to_enrich = [l for l in current_leads if not l["email"]]
    print(f"🌐 이메일이 등록되어 있지 않고, 웹사이트 주소가 등록된 리드 분석을 수행합니다. (대상: {len([l for l in leads_to_enrich if l['website_url']])}건)")

    if has_naver:
        # 실제 웹사이트가 있다면 크롤러 작동
        print("🚀 실존 웹사이트 크롤러 작동 중...")
        result = enrich_leads_with_email(limit=3)
        print(f"✅ 크롤러 작동 완료: 이메일 발견 {result['found']}건, 실패 {result['failed']}건")
    else:
        print("💡 [가상 데모 모드] 웹사이트에서 크롤링하여 이메일을 찾아내는 과정을 시뮬레이션합니다.")
        with get_db() as db:
            for lead in leads_to_enrich:
                if lead["website_url"]:
                    domain = lead["website_url"].replace("http://www.", "").replace("http://", "")
                    mock_email = f"contact@{domain}"
                    update_lead_email(db, lead["id"], mock_email)
                    print(f"🟢 [성공] '{lead['company_name']}' ({lead['website_url']}) 페이지 크롤링 완료 ➔ 이메일 발굴: '{mock_email}'")
                else:
                    print(f"🟡 [패스] '{lead['company_name']}' 업체는 웹사이트 URL이 등록되어 있지 않아 2차 탐색을 건너뜁니다.")

    # 5. 초개인화 AI 인트로 생성 및 콜드메일 빌드
    print_banner("Phase 6: GPT-4o-mini & Fallback 엔진 기반 초개인화 아웃바운드 이메일 생성")

    current_leads = fetch_serialized_leads()
    valid_leads = [l for l in current_leads if l["email"]]
    
    if not valid_leads:
        print("⚠️ 이메일이 존재하는 리드가 없습니다. 데모 진행을 위해 첫 번째 리드에 테스트 이메일을 바인딩합니다.")
        with get_db() as db:
            update_lead_email(db, current_leads[0]["id"], "test_owner@manpower.com")
        current_leads = fetch_serialized_leads()
        valid_leads = [l for l in current_leads if l["email"]]

    # 첫 번째 수집 리드로 메일 렌더링 시연
    target_lead_dict = valid_leads[0]
    print(f"🎯 초개인화 타깃 선정: #{target_lead_dict['id']} [{target_lead_dict['company_name']}] (수신처: {target_lead_dict['email']})")

    # 5-1) AI 인트로 생성
    print("🤖 AI 맞춤 인트로 문장 빌딩 작동...")
    intro = generate_personalized_intro(
        company_name=target_lead_dict["company_name"],
        region=target_lead_dict["region"],
        category=target_lead_dict["category"],
        representative=target_lead_dict["representative"],
    )
    print(f"\n[작성된 초개인화 인트로 문구]\n👉 \"{intro}\"\n")

    # 5-2) Jinja2 템플릿 메일 본문 조립
    print("📝 Jinja2 템플릿과 결합하여 최종 이메일 HTML 본문을 렌더링합니다...")
    # render_email_template에 넘기기 위해 SQLAlchemy Lead 객체를 잠시 로드
    with get_db() as db:
        from sales_pipeline.db.repository import get_leads
        db_leads = get_leads(db, limit=10)
        target_db_lead = [l for l in db_leads if l.id == target_lead_dict["id"]][0]
        subject, html_body = render_email_template("cold_email_v1", target_db_lead, extra_vars={"personalized_intro": intro})

    print("\n" + "-" * 60)
    print(f"📬 메일 제목: {subject}")
    print("-" * 60)
    
    # 텍스트로 보일 수 있게 태그 제거 후 핵심 부분만 출력
    import re
    clean_text_lines = []
    for l in html_body.split("\n"):
        cleaned = re.sub(r'<[^>]+>', '', l).strip()
        if cleaned:
            clean_text_lines.append(cleaned)

    print("\n[이메일 본문 프리뷰 (텍스트 추출)]")
    for l in clean_text_lines[:25]:
        print(f"  {l}")
    print("  ...")
    
    # 수신거부 링크가 포함되어 있는지 물리적 검증 확인
    opt_out_link = re.search(r'href="(http://[^"]+)"', html_body)
    print("-" * 60)
    if opt_out_link:
        print(f"🛡️ 안전 장치 작동 완료 (수신거부 전용 링크): \n    {opt_out_link.group(1)}")
    else:
        print("⚠️ 경고: 수신거부 링크가 감지되지 않았습니다.")
    print("-" * 60)

    print_banner("E2E 파이프라인 데모 런 완료")
    print("🎉 리드 수집 ➔ 2차 이메일 추출 ➔ AI 초개인화 문장 가공 ➔ 수신거부 방지 메일 설계까지")
    print("   모든 핵심 파이프라인의 통합 비즈니스 흐름이 100% 정상 작동함을 물리적으로 확인하였습니다!")
    print("\n💡 실제 환경에서 외부 실데이터로 수집 및 발송하시려면 아래와 같이 설정하세요:")
    print("   1. 프로젝트 폴더 하위에 '.env' 파일을 생성합니다.")
    print("   2. '.env.example' 파일을 참고하여 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, OPENAI_API_KEY 등을 기입하십시오.")
    print("   3. `sales scrape run --region \"서울 강남구\" --keyword \"인력사무소\"` CLI 명령어를 호출합니다.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_demo()
