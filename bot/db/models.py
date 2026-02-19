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
    JSON,
    Float,
    UniqueConstraint,
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
    tone: Mapped[str] = mapped_column(String(20), default="neutral")
    tz_personal: Mapped[str] = mapped_column(String(50), default="Europe/Moscow")
    morning_ping_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    evening_report_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # relationships
    spheres: Mapped[list["Sphere"]] = relationship(
        back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )
    focuses: Mapped[list["Focus"]] = relationship(
        back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )
    daily_sessions: Mapped[list["DailySession"]] = relationship(
        back_populates="user", lazy="selectin"
    )


# ── Spheres ────────────────────────────────────────────────────────────────────

class Sphere(Base):
    """Life sphere chosen by user with assessment scores."""
    __tablename__ = "spheres"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_sphere"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))  # e.g. "💼 Работа/Карьера" or custom
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    satisfaction: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-10
    importance: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-10
    pain_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # what hurts / what's wanted
    is_priority: Mapped[bool] = mapped_column(Boolean, default=False)  # selected as monthly priority
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="spheres")
    focuses: Mapped[list["Focus"]] = relationship(
        back_populates="sphere", lazy="selectin", cascade="all, delete-orphan"
    )


# ── Focuses (enhanced) ────────────────────────────────────────────────────────

class Focus(Base):
    """Monthly or weekly focus, tied to a sphere."""
    __tablename__ = "focuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    sphere_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("spheres.id", ondelete="SET NULL"), nullable=True
    )
    period: Mapped[str] = mapped_column(String(10))  # "month" | "week"
    text: Mapped[str] = mapped_column(Text)  # the focus formulation
    meaning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # why personally
    metric: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # how to measure success
    cost: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # price: time/effort/discomfort
    # LLM goal quality assessment
    llm_score: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # ok / vague / imposed / too_big
    llm_reframe: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # suggested reformulation
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    week_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-4 for weekly
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="focuses")
    sphere: Mapped[Optional["Sphere"]] = relationship(back_populates="focuses")
    steps: Mapped[list["StepBank"]] = relationship(
        back_populates="focus", lazy="selectin", cascade="all, delete-orphan"
    )


# ── Step Bank ──────────────────────────────────────────────────────────────────

class StepBank(Base):
    """Bank of pre-generated steps for a focus (30-45 min + plan B 10 min)."""
    __tablename__ = "step_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    focus_id: Mapped[int] = mapped_column(ForeignKey("focuses.id", ondelete="CASCADE"))
    week_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-4
    step_text: Mapped[str] = mapped_column(Text)  # main step 30-45 min
    plan_b_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # plan B 10 min
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)  # already assigned to a day
    order: Mapped[int] = mapped_column(Integer, default=0)  # ordering within week
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    focus: Mapped["Focus"] = relationship(back_populates="steps")


# ── Daily Sessions ─────────────────────────────────────────────────────────────

class DailySession(Base):
    __tablename__ = "daily_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date_local: Mapped[dt.date] = mapped_column(Date)
    dump_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_voice: Mapped[bool] = mapped_column(Boolean, default=False)
    energy: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5
    focus_option: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    focus_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    step_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan_b_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # household minimum tasks from dump
    household_tasks: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    llm_response_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    step_bank_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("step_bank.id", ondelete="SET NULL"), nullable=True
    )
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
    kind: Mapped[str] = mapped_column(String(5))
    status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
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
    status: Mapped[str] = mapped_column(String(10))
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["DailySession"] = relationship(back_populates="evening_report")


# ── Todo items (simple daily checklist) ───────────────────────────────────────

class TodoItem(Base):
    """Simple task for the day — no coaching, just checkbox tracking."""
    __tablename__ = "todo_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("daily_sessions.id", ondelete="SET NULL"), nullable=True
    )
    date_local: Mapped[dt.date] = mapped_column(Date, index=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending | done | carried_over
    carried_from_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("todo_items.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
