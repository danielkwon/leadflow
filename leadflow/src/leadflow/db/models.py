"""ORM 모델 정의.

User(회원), UserCredential(자격증명), Lead(리드), Campaign(캠페인), EmailLog(발송 이력), Reply(회신) 테이블.
"""
import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadflow.db.engine import Base


class User(Base):
    """회원 정보 테이블."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # 관계
    credentials: Mapped[Optional["UserCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    leads: Mapped[list["Lead"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list["Campaign"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    email_logs: Mapped[list["EmailLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    replies: Mapped[list["Reply"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    feedbacks: Mapped[list["Feedback"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email='{self.email}'>"


class UserCredential(Base):
    """회원별 API Key 및 OAuth 인증 자격증명 정보 (대칭키 암호화 보관)."""

    __tablename__ = "user_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    encrypted_openai_key: Mapped[Optional[str]] = mapped_column(Text)
    encrypted_gmail_credentials: Mapped[Optional[str]] = mapped_column(Text)
    encrypted_gmail_token: Mapped[Optional[str]] = mapped_column(Text)
    sender_email: Mapped[Optional[str]] = mapped_column(String(200))
    sender_name: Mapped[Optional[str]] = mapped_column(String(200))
    encrypted_naver_id: Mapped[Optional[str]] = mapped_column(Text)
    encrypted_naver_secret: Mapped[Optional[str]] = mapped_column(Text)
    sheets_name: Mapped[str] = mapped_column(String(200), default="LeadFlow_영업_현황판")
    encryption_key_salt: Mapped[Optional[str]] = mapped_column(String(100))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 관계
    user: Mapped["User"] = relationship(back_populates="credentials")

    def __repr__(self) -> str:
        return f"<UserCredential id={self.id} user_id={self.user_id}>"


class Lead(Base):
    """수집된 업체(리드) 정보."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    representative: Mapped[Optional[str]] = mapped_column(String(100))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(500))
    address: Mapped[Optional[str]] = mapped_column(String(500))
    road_address: Mapped[Optional[str]] = mapped_column(String(500))
    region: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="naver_api")
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    opt_out_date: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    naver_link: Mapped[Optional[str]] = mapped_column(String(500))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 관계
    user: Mapped["User"] = relationship(back_populates="leads")
    email_logs: Mapped[list["EmailLog"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    replies: Mapped[list["Reply"]] = relationship(back_populates="lead", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Lead id={self.id} company='{self.company_name}' region='{self.region}' user_id={self.user_id}>"


class Campaign(Base):
    """이메일 캠페인 정의."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=30)
    max_sequence: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # 관계
    user: Mapped["User"] = relationship(back_populates="campaigns")
    email_logs: Mapped[list["EmailLog"]] = relationship(back_populates="campaign")

    # 제약조건: 사용자별로 캠페인 명칭 고유
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uix_user_campaign_name"),
    )

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name='{self.name}' user_id={self.user_id}>"


class EmailLog(Base):
    """이메일 발송 이력."""

    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("campaigns.id"), index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_preview: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="sent")
    message_id: Mapped[Optional[str]] = mapped_column(String(200))
    sequence_number: Mapped[int] = mapped_column(Integer, default=1)

    # 관계
    user: Mapped["User"] = relationship(back_populates="email_logs")
    lead: Mapped["Lead"] = relationship(back_populates="email_logs")
    campaign: Mapped[Optional["Campaign"]] = relationship(back_populates="email_logs")

    def __repr__(self) -> str:
        return f"<EmailLog id={self.id} lead_id={self.lead_id} seq={self.sequence_number} user_id={self.user_id}>"


class Reply(Base):
    """고객 회신 기록."""

    __tablename__ = "replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    email_log_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("email_logs.id"))
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text)
    synced_to_sheet: Mapped[bool] = mapped_column(Boolean, default=False)

    # 관계
    user: Mapped["User"] = relationship(back_populates="replies")
    lead: Mapped["Lead"] = relationship(back_populates="replies")

    def __repr__(self) -> str:
        return f"<Reply id={self.id} lead_id={self.lead_id} user_id={self.user_id}>"


class Feedback(Base):
    """검수자 피드백 및 개발 진행 상황 추적(Issue Tracker) 테이블."""

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    reporter_name: Mapped[str] = mapped_column(String(100), default="검수 직원")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="todo") # todo (대기), done (해결)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 관계
    user: Mapped["User"] = relationship(back_populates="feedbacks")

    def __repr__(self) -> str:
        return f"<Feedback id={self.id} user_id={self.user_id} reporter='{self.reporter_name}' status='{self.status}'>"
