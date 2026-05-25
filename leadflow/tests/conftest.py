"""테스트 공통 픽스처."""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 테스트용 인메모리 DB 사용
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from leadflow.db.engine import Base
from leadflow.db import models  # noqa: F401


@pytest.fixture
def db_session():
    """테스트용 인메모리 DB 세션을 제공한다."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
