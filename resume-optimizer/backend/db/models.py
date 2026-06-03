"""
SQLAlchemy async models — PostgreSQL tables.
Transactional data only. Analytics in Delta Lake.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text, Uuid,
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
    created_at             = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    resumes = relationship("Resume", back_populates="user", cascade="all, delete-orphan")


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
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="resumes")


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
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    events = relationship("PipelineEvent", back_populates="job", cascade="all, delete-orphan")


class PipelineEvent(Base):
    """Append-only SSE event log — replaces asyncio.Queue; survives restarts and multiple workers."""
    __tablename__ = "pipeline_events"

    id         = Column(Integer, primary_key=True, autoincrement=True)  # sequential ordering
    job_id     = Column(Uuid(), ForeignKey("pipeline_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    event_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    job = relationship("PipelineJob", back_populates="events")
