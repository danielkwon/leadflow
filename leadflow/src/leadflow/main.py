"""B2B 영업 자동화 파이프라인 메인 오케스트레이션 모듈."""
from leadflow.settings import get_settings
from leadflow.utils.logging import get_logger, setup_logging
from leadflow.db.engine import init_db

log = get_logger("main")


def bootstrap() -> None:
    """앱 초기화: 로깅 설정, DB 초기화."""
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db()
    log.info("앱 초기화 완료", env=settings.app_env)
