"""보안 및 암호화 관련 유틸리티 모듈.

비밀번호 해싱/검증, 대칭 키를 이용한 민감한 자격증명(API Key 등) 암복호화, JWT 토큰 관리 기능을 제공한다.
"""
import base64
import datetime
import hashlib
from typing import Optional

import bcrypt
import jwt
from cryptography.fernet import Fernet

from leadflow.settings import get_settings
from leadflow.utils.logging import get_logger

log = get_logger("utils.security")

# 중앙 마스터 키 관리
# .env에 ENCRYPTION_SECRET_KEY가 없거나 길이가 부적합할 때를 대비하여 안전하게 32바이트 키를 유도한다.
def _derive_fernet_key(secret_key: str, salt: Optional[str] = None) -> bytes:
    """임의의 비밀키와 솔트를 조합하여 32바이트 Fernet 호환 base64 키를 유도한다."""
    base_str = secret_key
    if salt:
        base_str += salt
    
    # SHA-256을 활용해 항상 고정된 32바이트 해시 생성
    hasher = hashlib.sha256(base_str.encode("utf-8"))
    key_bytes = hasher.digest()
    
    # Fernet 규격에 맞춰 URL-safe Base64로 인코딩
    return base64.urlsafe_b64encode(key_bytes)


def encrypt_data(data: Optional[str], salt: Optional[str] = None) -> Optional[str]:
    """텍스트 데이터를 대칭 키 암호화하여 반환한다.

    Args:
        data: 암호화할 평문 텍스트
        salt: 사용자별 추가 엔트로피 솔트 (선택사항)

    Returns:
        Base64 인코딩된 암호화 텍스트
    """
    if data is None:
        return None
    try:
        settings = get_settings()
        # settings.opt_out_secret_key.get_secret_value()를 기본 마스터 키 대용으로 활용하거나 설정값 사용
        master_key = getattr(settings, "opt_out_secret_key", None)
        master_secret = master_key.get_secret_value() if master_key else "leadflow-fallback-secret-key-12345"
        
        fernet_key = _derive_fernet_key(master_secret, salt)
        fernet = Fernet(fernet_key)
        
        encrypted = fernet.encrypt(data.encode("utf-8"))
        return encrypted.decode("utf-8")
    except Exception as e:
        log.error("데이터 암호화 중 오류 발생", error=str(e))
        raise ValueError("데이터 암호화에 실패했습니다.") from e


def decrypt_data(encrypted_data: Optional[str], salt: Optional[str] = None) -> Optional[str]:
    """암호화된 데이터를 복호화하여 평문으로 반환한다.

    Args:
        encrypted_data: Base64 인코딩된 암호화 텍스트
        salt: 사용자별 추가 엔트로피 솔트 (선택사항)

    Returns:
        복호화된 평문 텍스트
    """
    if encrypted_data is None:
        return None
    try:
        settings = get_settings()
        master_key = getattr(settings, "opt_out_secret_key", None)
        master_secret = master_key.get_secret_value() if master_key else "leadflow-fallback-secret-key-12345"
        
        fernet_key = _derive_fernet_key(master_secret, salt)
        fernet = Fernet(fernet_key)
        
        decrypted = fernet.decrypt(encrypted_data.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception as e:
        log.error("데이터 복호화 중 오류 발생", error=str(e))
        raise ValueError("데이터 복호화에 실패했습니다. 올바른 키나 암호문인지 확인하십시오.") from e


# --- 비밀번호 암호화 및 검증 ---

def hash_password(password: str) -> str:
    """비밀번호를 Bcrypt 알고리즘으로 안전하게 해싱한다."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """입력받은 평문 비밀번호가 해싱된 비밀번호와 일치하는지 검증한다."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception as e:
        log.error("비밀번호 검증 중 오류 발생", error=str(e))
        return False


# --- JWT 토큰 생성 및 파싱 ---

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 60 * 24  # 24시간 유지


def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    """사용자 식별용 JWT access token을 생성한다."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=JWT_EXPIRATION_MINUTES)
    
    to_encode.update({"exp": expire})
    
    settings = get_settings()
    master_key = getattr(settings, "opt_out_secret_key", None)
    master_secret = master_key.get_secret_value() if master_key else "leadflow-fallback-secret-key-12345"
    
    encoded_jwt = jwt.encode(to_encode, master_secret, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """JWT access token을 디코딩하고 만료 여부를 확인하여 세션 데이터를 꺼낸다."""
    try:
        settings = get_settings()
        master_key = getattr(settings, "opt_out_secret_key", None)
        master_secret = master_key.get_secret_value() if master_key else "leadflow-fallback-secret-key-12345"
        
        payload = jwt.decode(token, master_secret, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        log.warning("JWT 토큰이 만료되었습니다.")
        return None
    except jwt.InvalidTokenError:
        log.warning("유효하지 않은 JWT 토큰입니다.")
        return None
