import json as _json
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from db.models import Profile, Resume, User
from db.session import get_db
from profiles.schemas import ParseProfileRequest, ProfileCreate, ProfileUpdate

router = APIRouter()       # mounted at /profiles
profile_ops = APIRouter()  # mounted at /profile


@router.post("", status_code=201)
async def create_profile(
    body: ProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile = Profile(
        user_id=current_user.id,
        label=body.label,
        label_confirmed=body.label_confirmed,
        raw_text=body.raw_text,
        sections=body.sections.model_dump(),
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return _to_dict(profile)


@router.get("")
async def list_profiles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await db.execute(
        select(Profile, func.count(Resume.id).label("use_count"))
        .outerjoin(Resume, Resume.profile_id == Profile.id)
        .where(Profile.user_id == current_user.id)
        .group_by(Profile.id)
        .order_by(Profile.created_at.desc())
    )
    return [_to_dict(p, use_count=c) for p, c in rows.all()]


@router.get("/{profile_id}")
async def get_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return _to_dict(await _get_owned(profile_id, current_user.id, db))


@router.put("/{profile_id}")
async def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile = await _get_owned(profile_id, current_user.id, db)
    if body.label is not None:
        profile.label = body.label
    if body.label_confirmed is not None:
        profile.label_confirmed = body.label_confirmed
    if body.sections is not None:
        profile.sections = body.sections.model_dump()
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(profile)
    return _to_dict(profile)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await _get_owned(profile_id, current_user.id, db)
    await db.delete(profile)
    await db.commit()


@profile_ops.post("/parse")
async def parse_profile(
    body: ParseProfileRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    return await _parse_sections(body.raw_text)


async def _parse_sections(raw_text: str) -> dict:
    from config import MODEL_PROFILE_PARSER
    from llm import complete

    prompt = f"""You are a resume parser. Extract structured data from the resume text below.
Return ONLY valid JSON with this exact shape:
{{
  "label": "<job title / role>",
  "summary": "<professional summary or empty string>",
  "experience": [
    {{"company": "", "title": "", "dates": "", "bullets": ["..."]}}
  ],
  "education": [
    {{"institution": "", "degree": "", "dates": ""}}
  ],
  "skills": ["skill1", "skill2"]
}}

Resume text:
{raw_text[:8000]}"""

    result = await complete(prompt, MODEL_PROFILE_PARSER)
    text = result["text"].strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return _json.loads(text)


async def _get_owned(profile_id: str, user_id, db: AsyncSession) -> Profile:
    try:
        pid = _uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Profile not found.")
    result = await db.execute(
        select(Profile).where(Profile.id == pid, Profile.user_id == user_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return p


def _to_dict(profile: Profile, use_count: int = 0) -> dict:
    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "label": profile.label or "",
        "label_confirmed": profile.label_confirmed,
        "raw_text": profile.raw_text or "",
        "sections": profile.sections or {},
        "use_count": use_count,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }
