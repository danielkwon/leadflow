"""Sales Pipeline CLI 인터페이스 (스케줄러/모니터 워커 전용).

사용법:
    sales scheduler
    sales monitor
    sales scrape run --region 서울 --keyword 인력사무소
    sales leads list --status new
"""
import typer

from leadflow_common.main import bootstrap

app = typer.Typer(
    name="sales",
    help="B2B 영업 자동화 파이프라인 CLI (워커 전용)",
    no_args_is_help=True,
)

# === 서브 커맨드 그룹 ===
scrape_app = typer.Typer(help="리드 수집 (스크래핑)")
leads_app = typer.Typer(help="리드 관리")
email_app = typer.Typer(help="이메일 발송")
campaign_app = typer.Typer(help="Drip 캠페인")
db_app = typer.Typer(help="데이터베이스 관리")

app.add_typer(scrape_app, name="scrape")
app.add_typer(leads_app, name="leads")
app.add_typer(email_app, name="email")
app.add_typer(campaign_app, name="campaign")
app.add_typer(db_app, name="db")


@app.callback()
def main_callback() -> None:
    """앱 초기화 콜백."""
    bootstrap()


# === DB 관리 ===


@db_app.command("init")
def db_init() -> None:
    """데이터베이스 테이블을 초기화한다."""
    from leadflow_common.db.engine import init_db

    init_db()
    typer.echo("✅ 데이터베이스 초기화 완료")


# === 리드 관리 ===


@leads_app.command("list")
def leads_list(
    status: str = typer.Option(None, help="상태 필터 (new, contacted, replied, converted)"),
    region: str = typer.Option(None, help="지역 필터"),
    has_email: bool = typer.Option(None, help="이메일 보유 여부"),
    limit: int = typer.Option(50, help="조회 수"),
) -> None:
    """리드 목록을 조회한다."""
    from leadflow_common.db.engine import get_db
    from leadflow_common.db.repository import count_leads, get_leads

    with get_db() as db:
        leads = get_leads(db, status=status, region=region, has_email=has_email, limit=limit)
        total = count_leads(db, status=status)

        typer.echo(f"\n📋 리드 목록 (총 {total}건, {len(leads)}건 표시)\n")
        typer.echo(f"{'ID':>5} | {'업체명':<20} | {'지역':<6} | {'이메일':<30} | {'전화번호':<15} | {'상태':<10}")
        typer.echo("-" * 95)
        for lead in leads:
            typer.echo(
                f"{lead.id:>5} | {lead.company_name:<20} | {lead.region:<6} | "
                f"{(lead.email or '-'):<30} | {(lead.phone or '-'):<15} | {lead.status:<10}"
            )


@leads_app.command("stats")
def leads_stats() -> None:
    """리드 현황 통계를 표시한다."""
    from leadflow_common.db.engine import get_db
    from leadflow_common.db.repository import count_leads

    with get_db() as db:
        total = count_leads(db)
        new = count_leads(db, status="new")
        contacted = count_leads(db, status="contacted")
        replied = count_leads(db, status="replied")
        converted = count_leads(db, status="converted")

    typer.echo("\n📊 리드 현황 통계")
    typer.echo(f"  전체: {total}")
    typer.echo(f"  신규: {new}")
    typer.echo(f"  연락 완료: {contacted}")
    typer.echo(f"  회신: {replied}")
    typer.echo(f"  전환: {converted}")


# === 스크래핑 ===


@scrape_app.command("run")
def scrape_run(
    region: str = typer.Option(..., help="검색 지역 (예: 서울, 경기)"),
    keyword: str = typer.Option(..., help="검색 키워드 (예: 인력사무소)"),
) -> None:
    """네이버 API로 업체를 검색하고 리드 DB에 저장한다."""
    typer.echo(f"🔍 '{region} {keyword}' 검색 시작...")
    from leadflow_common.scraper.naver_api import scrape_leads

    result = scrape_leads(region=region, keyword=keyword)
    typer.echo(f"✅ 완료: {result['added']}건 추가, {result['skipped']}건 중복 스킵, {result['errors']}건 오류")


@scrape_app.command("enrich")
def scrape_enrich(
    limit: int = typer.Option(50, help="처리할 리드 수"),
) -> None:
    """이메일이 없는 리드의 웹사이트에서 이메일을 추출한다."""
    typer.echo(f"🌐 웹사이트 이메일 추출 시작 (최대 {limit}건)...")
    from leadflow_common.scraper.website_scraper import enrich_leads_with_email

    result = enrich_leads_with_email(limit=limit)
    typer.echo(f"✅ 완료: {result['found']}건 이메일 발견, {result['failed']}건 실패")


# === 이메일 ===


@email_app.command("send-test")
def email_send_test(
    lead_id: int = typer.Option(..., help="테스트 발송할 리드 ID"),
) -> None:
    """단건 테스트 이메일을 발송한다."""
    typer.echo(f"📧 리드 #{lead_id}에 테스트 이메일 발송 중...")
    from leadflow_common.email_sender.gmail_client import send_test_email

    send_test_email(lead_id=lead_id)
    typer.echo("✅ 발송 완료")


# === 캠페인 ===


@campaign_app.command("run")
def campaign_run(
    name: str = typer.Option(..., help="캠페인 이름"),
) -> None:
    """캠페인을 수동 실행한다."""
    typer.echo(f"🚀 캠페인 '{name}' 실행 중...")
    from leadflow_common.campaign.drip import run_campaign_by_name

    result = run_campaign_by_name(name=name)
    typer.echo(f"✅ 완료: {result['sent']}건 발송, {result['skipped']}건 스킵")


@campaign_app.command("create")
def campaign_create(
    name: str = typer.Option(..., help="캠페인 이름"),
    template: str = typer.Option("cold_email_v1", help="이메일 템플릿 이름"),
    interval: int = typer.Option(30, help="후속 발송 주기 (일)"),
    max_seq: int = typer.Option(3, help="최대 후속 발송 횟수"),
) -> None:
    """새 캠페인을 생성한다."""
    from leadflow_common.db.engine import get_db
    from leadflow_common.db.repository import create_campaign

    with get_db() as db:
        campaign = create_campaign(
            db,
            name=name,
            template_name=template,
            interval_days=interval,
            max_sequence=max_seq,
        )
    typer.echo(f"✅ 캠페인 생성: #{campaign.id} '{name}'")


@app.command("scheduler")
def scheduler_start() -> None:
    """Drip 스케줄러를 시작한다."""
    typer.echo("⏰ Drip 스케줄러 시작...")
    from leadflow_common.campaign.scheduler import start_scheduler

    start_scheduler()


@app.command("monitor")
def monitor_start() -> None:
    """수신함 모니터링을 시작한다."""
    typer.echo("👁️ 수신함 모니터링 시작...")
    from leadflow_common.monitor.inbox_watcher import start_monitoring

    start_monitoring()


if __name__ == "__main__":
    app()
