from typing import Optional
from pydantic import BaseModel


class BootstrapRequest(BaseModel):
    email: str


class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    plan: str
    is_active: bool
    is_admin: bool
    trial_expires_at: Optional[str] = None
    created_at: str
    resume_count: int


class UserDetail(UserListItem):
    runs_today: int
    total_resumes: int
    last_active: Optional[str]


class UserUpdate(BaseModel):
    plan: Optional[str] = None         # "free" | "pro" | "enterprise"
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None    # True promotes; False rejected by server


class AdminStats(BaseModel):
    total_users: int
    active_users: int
    pipeline_runs_today: int
    total_resumes: int
    stuck_jobs: int
