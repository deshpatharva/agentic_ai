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


class PromoCodeDetail(BaseModel):
    id: str
    code: str
    type: str  # plan_upgrade, trial_extension, discount
    target_plan: Optional[str] = None
    days_to_add: Optional[int] = None
    discount_percent: Optional[int] = None
    max_uses: int
    current_uses: int
    expires_at: Optional[str] = None
    created_at: str
    deactivated_at: Optional[str] = None


class PromoCodeListItem(BaseModel):
    id: str
    code: str
    type: str
    max_uses: int
    current_uses: int
    expires_at: Optional[str] = None
    created_at: str
    status: str  # active, expired, deactivated
    days_until_expiry: Optional[int] = None


class PromoCodeStats(BaseModel):
    code: str
    type: str
    discount_percent: Optional[int] = None
    max_uses: int
    current_uses: int
    remaining_uses: int
    redeemed_by_plan: dict  # {free: N, pro: N, enterprise: N}
    last_redeemed_at: Optional[str] = None
    first_redeemed_at: Optional[str] = None
