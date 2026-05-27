"""SQLAlchemy 2.0 데이터베이스 엔진 및 세션 관리.

환경변수 DATABASE_URL을 기반으로 엔진을 생성한다.
SQLite로 시작하되, PostgreSQL로 전환 가능한 구조.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from leadflow_common.settings import get_settings


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스 클래스."""

    pass


def _get_engine():
    """설정 기반으로 SQLAlchemy 엔진을 생성한다."""
    settings = get_settings()
    db_url = settings.database_url

    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        db_url,
        connect_args=connect_args,
        echo=(settings.app_env == "development"),
    )

    # SQLite WAL 모드 활성화 (동시 읽기 성능 향상)
    if db_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _get_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """데이터베이스 세션 컨텍스트 매니저.

    사용 예:
        with get_db() as db:
            db.query(Lead).all()

    Yields:
        SQLAlchemy Session 인스턴스
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_api() -> Generator[Session, None, None]:
    """FastAPI Depends 전용 데코레이팅되지 않은 순수 데이터베이스 세션 제너레이터."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()



def init_db() -> None:
    """모든 테이블을 생성한다. 개발 환경 초기화용."""
    from leadflow_common.db import models  # noqa: F401 - 모델 import로 테이블 등록

    Base.metadata.create_all(bind=engine)
