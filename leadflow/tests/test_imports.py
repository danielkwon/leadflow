"""leadflow Web 패키지 smoke test."""
import pytest


def test_cli_imports():
    """leadflow CLI 모듈이 정상적으로 임포트되는지 확인."""
    from leadflow.cli import app
    assert app is not None


def test_web_app_imports():
    """FastAPI 웹 앱이 정상적으로 임포트되는지 확인."""
    from leadflow.web.app import app as fastapi_app
    assert fastapi_app is not None
