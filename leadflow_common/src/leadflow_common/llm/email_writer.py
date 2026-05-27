"""OpenAI GPT 기반 맞춤형 콜드 메일 도입부 생성 모듈.

수집된 업체의 카테고리(인력사무소, 건설사, 시공사 등), 지역, 대표자명 등을 분석하여
수신자가 메일을 열었을 때 친근감과 신뢰를 느낄 수 있는 초개인화된 도입부 1~2문장을 생성한다.
"""
from openai import OpenAI

from leadflow_common.settings import get_settings
from leadflow_common.utils.logging import get_logger

log = get_logger("llm.writer")


def generate_personalized_intro(
    company_name: str,
    region: str,
    category: str,
    representative: str = "대표님",
) -> str:
    """OpenAI GPT API를 사용하여 맞춤형 콜드 메일 도입부 문장을 생성한다.

    Args:
        company_name: 업체명
        region: 지역 (예: 서울, 경기)
        category: 카테고리 (예: 인력사무소, 건설사)
        representative: 대표자명 (없으면 '대표님')

    Returns:
        생성된 맞춤형 도입부 1~2문장 (실패 시 자연스러운 기본 문장 반환)
    """
    settings = get_settings()
    api_key = settings.openai_api_key.get_secret_value()

    # 대표자명이 누락되었거나 '대표님'이 아닌 실제 이름인 경우 처리
    rep_title = representative if representative and representative != "대표님" else "대표님"
    if rep_title != "대표님" and not rep_title.endswith("대표님"):
        rep_title = f"{rep_title} 대표님"

    # 기본 대체(Fallback) 문장 구성 (API 키 누락 또는 호출 에러 대비)
    fallback_intro = (
        f"{region} 지역에서 신뢰받는 {company_name} {rep_title}, 안녕하십니까. "
        f"매월 현장 근로자 배치와 일용직 노무 관리 및 정산 업무를 처리하시느라 노고가 많으십니다."
    )

    if not api_key:
        log.debug(
            "OpenAI API Key가 설정되지 않았습니다. 기본 템플릿 도입부를 사용합니다.",
            company=company_name,
        )
        return fallback_intro

    # GPT 프롬프트 구성
    system_prompt = (
        "당신은 B2B 콜드 메일 마케팅 및 영업 분야의 최고 전문가입니다. "
        "입력된 한국 업체의 정보(업체명, 업종, 지역, 대표자 호칭)를 바탕으로, "
        "메일 수신자인 대표가 읽었을 때 '진짜 사람이 우리 회사를 꼼꼼히 알아보고 썼구나'라는 "
        "강한 신뢰감과 흥미를 가질 수 있도록 초개인화된 맞춤형 첫 도입 문장(1~2문장)을 작성해 주세요.\n\n"
        "작성 규칙:\n"
        "1. 한국 정서에 깊이 맞춘 정중하고 전문적인 비즈니스 어조(하십시오체)를 사용할 것.\n"
        "2. 반드시 업종(인력사무소, 건설사, 시공사 등)의 현업 페인 포인트(Pain Point, 예: 일용직 노무 서류, 급여 정산 번거로움, 인프라 관리 등)를 부드럽게 언급할 것.\n"
        "3. AI가 기계적으로 쓴 느낌이나 과장된 미사여구는 절대 쓰지 말고 극도로 자연스러워야 함.\n"
        "4. 오직 이메일 본문 도입부에 즉시 삽입할 완성형 문장만 반환할 것. 서론, 부연설명, 마크다운 따옴표 등은 절대 금지함."
    )

    user_prompt = (
        f"업체명: {company_name}\n"
        f"업종: {category}\n"
        f"지역: {region}\n"
        f"대표자 호칭: {rep_title}"
    )

    try:
        log.info("맞춤형 AI 도입부 생성 시작", company=company_name, category=category)
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 가성비와 성능의 조화
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=250,
        )

        content = response.choices[0].message.content
        if content:
            personalized_sentence = content.strip()
            log.info("AI 도입부 생성 성공", company=company_name, result=personalized_sentence)
            return personalized_sentence

    except Exception as e:
        log.error(
            "OpenAI API 호출 중 예외 발생. Fallback 문장을 사용합니다.",
            company=company_name,
            error=str(e),
        )

    return fallback_intro
