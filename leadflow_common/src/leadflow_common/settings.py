"""B2B 영업 자동화 파이프라인 중앙 설정 모듈.

pydantic-settings를 사용하여 .env 파일 또는 환경변수에서 설정을 로드한다.
민감한 값은 SecretStr로 자동 마스킹된다.
"""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """전역 설정. .env 파일과 환경변수에서 자동 로드."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 앱 ---
    app_env: str = "development"
    log_level: str = "INFO"

    # --- 데이터베이스 ---
    database_url: str = "sqlite:///./data/leadflow.db"

    # --- 네이버 API ---
    naver_client_id: SecretStr = SecretStr("")
    naver_client_secret: SecretStr = SecretStr("")

    # --- OpenAI ---
    openai_api_key: SecretStr = SecretStr("")

    # --- Gmail ---
    gmail_credentials_path: str = "config/gmail_credentials.json"
    gmail_token_path: str = "config/gmail_token.json"
    sender_email: str = ""
    sender_name: str = ""

    # --- Google Sheets ---
    google_sheets_credentials_path: str = "config/sheets_service_account.json"
    google_sheets_name: str = "영업_현황판"

    # --- AWS SES (선택) ---
    aws_access_key_id: SecretStr = SecretStr("")
    aws_secret_access_key: SecretStr = SecretStr("")
    aws_ses_region: str = "ap-northeast-2"

    # --- 수신거부 ---
    opt_out_base_url: str = "http://localhost:8080"
    opt_out_secret_key: SecretStr = SecretStr("change-me-to-random-secret")

    # --- 암호화 및 JWT ---
    encryption_secret_key: SecretStr = SecretStr("")
    jwt_secret_key: SecretStr = SecretStr("")

    @property
    def effective_encryption_key(self) -> str:
        """암호화 마스터 키를 반환한다. ENCRYPTION_SECRET_KEY가 없으면 opt_out_secret_key를 대체 사용한다."""
        key = self.encryption_secret_key.get_secret_value()
        if key:
            return key
        return self.opt_out_secret_key.get_secret_value()

    @property
    def effective_jwt_key(self) -> str:
        """JWT 서명 키를 반환한다. JWT_SECRET_KEY가 없으면 opt_out_secret_key를 대체 사용한다."""
        key = self.jwt_secret_key.get_secret_value()
        if key:
            return key
        return self.opt_out_secret_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Settings 싱글턴 인스턴스를 반환한다."""
    return Settings()
