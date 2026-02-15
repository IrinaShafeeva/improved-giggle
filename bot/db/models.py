import datetime as dt
from typing import Optional

from sqlalchemy import (
    BigInteger,
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Enum as SAEnum,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db.base import Base


# ── Users ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tone: Mapped[str] = mapped_column(String(20), default="neutral")  # neutral / soft / strict
    spheres: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # comma-separated
    tz_personal: Mapped[str] = mapped_column(String(50), default="Europe/Moscow")
    morning_ping_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "09:00"
    evening_report_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "21:00"
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # relationships
    focuses: Mapped[list["Focus"]] = relationship(back_populates="user", lazy="selectin")
    daily_sessions: Mapped[list["DailySession"]] = relationship(back_populates="user", lazy="selectin")


# ── Focuses ────────────────────────────────────────────────────────────────────

class Focus(Base):
    __tablename__ = "focuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(10))  # "week" | "month"
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="focuses")


# ── Daily Sessions ─────────────────────────────────────────────────────────────

class DailySession(Base):
    __tablename__ = "daily_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date_local: Mapped[dt.date] = mapped_column(Date)  # date in user's tz
    dump_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # original or transcribed
    is_voice: Mapped[bool] = mapped_column(Boolean, default=False)
    energy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5
    focus_option: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)  # "A" | "B"
    focus_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    step_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan_b_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # full LLM response for debugging
    llm_response_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    accepted_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="daily_sessions")
    checkins: Mapped[list["Checkin"]] = relationship(back_populates="session", lazy="selectin")
    evening_report: Mapped[Optional["EveningReport"]] = relationship(
        back_populates="session", uselist=False, lazy="selectin"
    )


# ── Checkins ───────────────────────────────────────────────────────────────────

class Checkin(Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_session_id: Mapped[int] = mapped_column(
        ForeignKey("daily_sessions.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(5))  # "t3" | "t6"
    status: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )  # done / progress / moved / help
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["DailySession"] = relationship(back_populates="checkins")


# ── Evening Reports ────────────────────────────────────────────────────────────

class EveningReport(Base):
    __tablename__ = "evening_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_session_id: Mapped[int] = mapped_column(
        ForeignKey("daily_sessions.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(10))  # done / partial / fail
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["DailySession"] = relationship(back_populates="evening_report")


# ── Analytics Events ───────────────────────────────────────────────────────────

class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
