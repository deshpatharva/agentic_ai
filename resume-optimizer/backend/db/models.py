"""
SQLAlchemy async models — PostgreSQL tables.
Transactional data only. Analytics in Delta Lake.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Index, Integer, JSON, String, Text, text, Uuid, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class PlanType(str, PyEnum):
    free       = "free"
    pro        = "pro"
    enterprise = "enterprise"


class JobStatus(str, PyEnum):
    pending = "pending"
    running = "running"
    done    = "done"
    error   = "error"


class User(Base):
    __tablename__ = "users"

    id                     = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    email                  = Column(String(255), unique=True, nullable=False, index=True)
    password_hash          = Column(String(255), nullable=False)
    full_name              = Column(String(255), nullable=True)
    plan                   = Column(Enum(PlanType), default=PlanType.free, nullable=False)
    stripe_customer_id     = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    is_active              = Column(Boolean, default=True, nullable=False)
    is_admin               = Column(Boolean, default=False, nullable=False)
    created_at             = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    trial_expires_at       = Column(DateTime(timezone=True), nullable=True)

    resumes  = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    profiles = relationship("Profile", back_populates="user", cascade="all, delete-orphan")


class PlanLimit(Base):
    __tablename__ = "plan_limits"

    plan                  = Column(String(50), primary_key=True)
    daily_uploads         = Column(Integer, nullable=False)
    max_stored_resumes    = Column(Integer, nullable=False)
    job_scraping_enabled  = Column(Boolean, nullable=False)
    price_cents           = Column(Integer, nullable=False)


class Resume(Base):
    __tablename__ = "resumes"

    id                = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id           = Column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = Column(String(500), nullable=False)
    file_path         = Column(String(1000), nullable=True)
    jd_text           = Column(Text, nullable=True)
    final_score       = Column(Float, nullable=True)
    scores_json       = Column(JSON, nullable=True)
    iterations        = Column(Integer, default=0, nullable=False)
    version           = Column(Integer, default=1, nullable=False)
    profile_id        = Column(Uuid(), ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user    = relationship("User", back_populates="resumes")
    profile = relationship("Profile", back_populates="resumes")


class PipelineJob(Base):
    """Persistent job state — replaces the in-memory jobs: dict."""
    __tablename__ = "pipeline_jobs"

    id                = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id           = Column(Uuid(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status            = Column(Enum(JobStatus), default=JobStatus.pending, nullable=False, index=True)
    original_filename = Column(String(500), nullable=False, default="resume")
    resume_text       = Column(Text, nullable=False)
    jd_text           = Column(Text, nullable=True)
    scores_json       = Column(JSON, nullable=True)
    download_path     = Column(String(1000), nullable=True)
    iteration         = Column(Integer, default=0, nullable=False)
    error_message     = Column(String(2000), nullable=True)
    created_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    events = relationship("PipelineEvent", back_populates="job", cascade="all, delete-orphan")


class PipelineEvent(Base):
    """Append-only SSE event log — replaces asyncio.Queue; survives restarts and multiple workers."""
    __tablename__ = "pipeline_events"

    id         = Column(Integer, primary_key=True, autoincrement=True)  # sequential ordering
    job_id     = Column(Uuid(), ForeignKey("pipeline_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    event_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    job = relationship("PipelineJob", back_populates="events")


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id                = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    code              = Column(String(50), unique=True, nullable=False, index=True)
    type              = Column(String(50), nullable=False)  # plan_upgrade, trial_extension, discount
    target_plan       = Column(String(20), nullable=True)
    days_to_add       = Column(Integer(), nullable=True)
    discount_percent  = Column(Integer(), nullable=True)
    max_uses          = Column(Integer(), nullable=False)
    current_uses      = Column(Integer(), default=0, nullable=False)
    expires_at        = Column(DateTime(timezone=True), nullable=True)
    created_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    deactivated_at    = Column(DateTime(timezone=True), nullable=True)


class UserPromoRedemption(Base):
    __tablename__ = "user_promo_redemptions"

    id              = Column(Integer(), primary_key=True, autoincrement=True)
    user_id         = Column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    promo_code_id   = Column(Uuid(), ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    redeemed_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "promo_code_id", name="uq_user_code"),
    )


class ProviderCost(Base):
    __tablename__ = "provider_costs"

    id                            = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    provider                      = Column(String(50), nullable=False)
    input_cost_per_1m_tokens      = Column(Float, nullable=False)
    output_cost_per_1m_tokens     = Column(Float, nullable=False)
    active                        = Column(Boolean, default=True, nullable=False)
    created_at                    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at                    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index(
            "uix_provider_active_true",
            "provider",
            postgresql_where=text("active = true"),
            unique=True,
        ),
    )


class DailyUsageCounter(Base):
    """Transactional daily pipeline run counter per user. Used for rate limiting.
    Delta Lake is for analytics only — not fast enough for real-time rate limits.
    """
    __tablename__ = "daily_usage_counters"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_date"),
    )

    id      = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date    = Column(String(10), nullable=False)   # ISO date "YYYY-MM-DD"
    runs    = Column(Integer, nullable=False, default=0)


class TokenBlocklist(Base):
    """Revoked JWT tokens. Checked on every authenticated request.
    Expired entries cleaned up by the stuck-job reaper.
    """
    __tablename__ = "token_blocklist"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    jti        = Column(String(36), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


# ── New models ────────────────────────────────────────────────────────────────

class Profile(Base):
    __tablename__ = "profiles"

    id              = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id         = Column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label           = Column(String(100), nullable=True)
    label_confirmed = Column(Boolean, default=False, nullable=False)
    raw_text        = Column(Text, nullable=True)
    sections        = Column(JSON, nullable=True)
    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user    = relationship("User", back_populates="profiles")
    resumes = relationship("Resume", back_populates="profile")


class JdScrapeCache(Base):
    __tablename__ = "jd_scrape_cache"

    url_hash   = Column(String(64), primary_key=True)
    jd_text    = Column(Text, nullable=False)
    scraped_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
