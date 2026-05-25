"""APScheduler 기반 Drip 캠페인 자동 스케줄러 모듈.

매일 지정된 시간에 활성화된 모든 Drip 캠페인을 조회하여
대상 리드에게 적절한 시퀀스의 이메일을 자동으로 발송한다.
"""
import signal
import sys
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from sales_pipeline.campaign.drip import run_campaign_by_name
from sales_pipeline.db.engine import get_db
from sales_pipeline.db.repository import get_active_campaigns
from sales_pipeline.settings import get_settings
from sales_pipeline.utils.logging import get_logger

log = get_logger("campaign.scheduler")


def run_active_campaigns_job() -> None:
    """스케줄러 작업: 활성화된 모든 Drip 캠페인을 순차적으로 실행한다."""
    log.info("⏰ 자동 스케줄러: Drip 캠페인 실행 시작...")
    try:
        with get_db() as db:
            active_campaigns = get_active_campaigns(db)
            if not active_campaigns:
                log.info("자동 스케줄러: 활성화된 캠페인이 없습니다.")
                return

            log.info(
                "자동 스케줄러: 활성 캠페인 리스트 조회 완료",
                count=len(active_campaigns),
                campaigns=[c.name for c in active_campaigns],
            )

            for campaign in active_campaigns:
                try:
                    run_campaign_by_name(campaign.name)
                except Exception as e:
                    log.error(
                        "자동 스케줄러: 개별 캠페인 실행 중 에러 발생",
                        campaign_name=campaign.name,
                        error=str(e),
                    )
    except Exception as e:
        log.error("자동 스케줄러: 작업 실행 중 치명적인 에러 발생", error=str(e))


def start_scheduler() -> None:
    """스케줄러를 초기화하고 무한 루프로 실행한다."""
    settings = get_settings()
    scheduler = BlockingScheduler()

    # 시그널 핸들러 등록 (Graceful Shutdown)
    def shutdown_handler(signum, frame):
        log.info("스케줄러 종료 시그널 수신. 종료 프로세스를 시작합니다...")
        scheduler.shutdown(wait=False)
        log.info("스케줄러 정상 종료 완료.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # 개발 환경(development)인 경우 1시간마다 즉시 실행해 테스트 가능하게 구성
    # 실서비스 환경(production)인 경우 매일 오전 9시에 정기 발송
    if settings.app_env == "development":
        trigger = CronTrigger(minute="0")  # 매 시간 정각
        log.info(
            "개발자 모드: Drip 스케줄러가 매 시간 정각에 실행되도록 설정되었습니다.",
            env=settings.app_env,
        )
        # 테스트를 위해 즉시 1회 실행
        scheduler.add_job(
            run_active_campaigns_job,
            trigger=trigger,
            id="drip_campaign_job",
            replace_existing=True,
        )
        # 즉시 실행을 위해 별도 스레드로 한번 큐에 넣거나 바로 실행
        log.info("개발 환경 스케줄러 구동: 즉시 1회 시범 작동을 시작합니다...")
        run_active_campaigns_job()
    else:
        # 매일 오전 9시 0분 발송
        trigger = CronTrigger(hour="9", minute="0")
        log.info(
            "운영 모드: Drip 스케줄러가 매일 오전 9시에 실행되도록 설정되었습니다.",
            env=settings.app_env,
        )
        scheduler.add_job(
            run_active_campaigns_job,
            trigger=trigger,
            id="drip_campaign_job",
            replace_existing=True,
        )

    log.info("Drip 캠페인 스케줄러가 성공적으로 시작되었습니다. (대기 중...)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("스케줄러가 키보드 인터럽트에 의해 종료되었습니다.")
