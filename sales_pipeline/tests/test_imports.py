"""sales_pipeline Worker 패키지 smoke test."""
import pytest


def test_cli_imports():
    """sales_pipeline CLI 모듈이 정상적으로 임포트되는지 확인."""
    from sales_pipeline.cli import app
    assert app is not None
