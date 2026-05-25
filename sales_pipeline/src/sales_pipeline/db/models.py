"""ORM 모델 정의.

Lead(리드), Campaign(캠페인), EmailLog(발송 이력), Reply(회신) 테이블.
"""
import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sales_pipeline.db.engine import Base


class Lead(Base):
    """수집된 업체(리드) 정보."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    email_logs: Mapped[list["EmailLog"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    replies: Mapped[list["Reply"]] = relationship(back_populates="lead", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Lead id={self.id} company='{self.company_name}' region='{self.region}'>"


class Campaign(Base):
    """이메일 캠페인 정의."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    template_name: Mapped[str] = mapped_column(String(200), nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=30)
    max_sequence: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # 관계
    email_logs: Mapped[list["EmailLog"]] = relationship(back_populates="campaign")

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name='{self.name}'>"


class EmailLog(Base):
    """이메일 발송 이력."""

    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("campaigns.id"), index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_preview: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="sent")
    message_id: Mapped[Optional[str]] = mapped_column(String(200))
    sequence_number: Mapped[int] = mapped_column(Integer, default=1)

    # 관계
    lead: Mapped["Lead"] = relationship(back_populates="email_logs")
    campaign: Mapped[Optional["Campaign"]] = relationship(back_populates="email_logs")

    def __repr__(self) -> str:
        return f"<EmailLog id={self.id} lead_id={self.lead_id} seq={self.sequence_number}>"


class Reply(Base):
    """고객 회신 기록."""

    __tablename__ = "replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    email_log_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("email_logs.id"))
    received_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text)
    synced_to_sheet: Mapped[bool] = mapped_column(Boolean, default=False)

    # 관계
    lead: Mapped["Lead"] = relationship(back_populates="replies")

    def __repr__(self) -> str:
        return f"<Reply id={self.id} lead_id={self.lead_id}>"
