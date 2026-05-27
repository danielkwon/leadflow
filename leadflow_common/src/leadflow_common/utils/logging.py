"""structlog 기반 구조화 로깅 설정.

모든 모듈은 이 모듈의 get_logger()를 사용하여 로거를 생성한다.
로그에는 반드시 맥락(Context)이 포함되어야 한다.
"""
import logging
import sys

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """structlog 및 표준 logging을 초기화한다.

    Args:
        log_level: 로그 레벨 문자열 (DEBUG, INFO, WARNING, ERROR)
    """
    # 표준 logging 설정
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # structlog 설정
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """이름이 바인딩된 structlog 로거를 반환한다.

    Args:
        name: 모듈 또는 컴포넌트 이름 (예: 'scraper.naver_api')

    Returns:
        컨텍스트 바인딩이 가능한 structlog 로거
    """
    return structlog.get_logger(component=name)
