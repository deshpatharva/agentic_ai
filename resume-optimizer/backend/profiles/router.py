import json as _json
import re as _re
import uuid as _uuid
from datetime import datetime, timezone

import io as _io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from db.models import Profile, Resume, User
from db.session import get_db
from profiles.schemas import (
    InterviewFinishRequest,
    InterviewMessageRequest,
    ParseProfileRequest,
    PrepareJobRequest,
    ProfileCreate,
    ProfileUpdate,
)
from utils.profile_utils import sections_to_text as _sections_to_text

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
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict:
    contents = await file.read()
    raw_text = _extract_file_text(contents, file.filename or "")
    result = await _parse_sections(raw_text)
    result["raw_text"] = raw_text
    return result


def _extract_file_text(contents: bytes, filename: str) -> str:
    from parsers.pdf_parser import parse_pdf
    from parsers.docx_parser import parse_docx
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            return parse_pdf(_io.BytesIO(contents))["raw_text"]
        if name.endswith(".docx"):
            return parse_docx(_io.BytesIO(contents))["raw_text"]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read file: {exc}") from exc
    raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or DOCX.")


def _extract_json(text: str) -> str:
    """Extract the first JSON object from LLM output, handling thinking tags and markdown fences."""
    text = text.strip()
    text = _re.sub(r"<thinking>.*?</thinking>", "", text, flags=_re.DOTALL).strip()
    match = _re.search(r"\{.*\}", text, _re.DOTALL)
    if match:
        return match.group(0)
    if text.startswith("```"):
        parts = text.split("```")
        candidate = parts[1] if len(parts) > 1 else text
        if candidate.startswith("json"):
            candidate = candidate[4:]
        return candidate.strip()
    return text


async def _parse_sections(raw_text: str) -> dict:
    import logging as _logging
    from config import MODEL_PROFILE_PARSER
    from llm import complete

    _logger = _logging.getLogger(__name__)

    if not raw_text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the file. Ensure the file contains readable text (not a scanned image).")

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

    try:
        result = await complete(prompt, MODEL_PROFILE_PARSER)
    except Exception as exc:
        _logger.exception("LLM call failed in _parse_sections")
        raise HTTPException(status_code=502, detail=f"AI parsing service error: {exc}") from exc

    text = _extract_json(result["text"])
    try:
        parsed = _json.loads(text)
    except _json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Profile parser returned invalid JSON: {e}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Profile parser returned unexpected format.")

    return parsed


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


_INTERVIEW_QUESTIONS = [
    "What is your most recent role? Please share your job title, company name, and dates.",
    "What were your 3–5 key responsibilities or achievements in that role? Use bullet points if you like.",
    "Tell me about any other significant previous roles — title, company, dates, and one key achievement each.",
    "What is your education background? Institution, degree, and graduation year.",
    "What are your top technical and professional skills?",
    "Is there anything else you'd like to highlight — certifications, publications, or notable projects?",
]

_INTERVIEW_SYSTEM = """You are a friendly resume assistant conducting a structured interview to build a professional profile.
Ask exactly the questions you are given, one at a time. Acknowledge the user's answer warmly and ask the next question.
When all questions are covered, reply with exactly: INTERVIEW_COMPLETE"""


@profile_ops.post("/ai-interview/message")
async def interview_message(
    body: InterviewMessageRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """One stateless interview turn. Client sends full history; returns next question or INTERVIEW_COMPLETE."""
    from config import MODEL_INTERVIEW_SYNTH
    from llm import complete

    questions_block = "\n".join(f"{i+1}. {q}" for i, q in enumerate(_INTERVIEW_QUESTIONS))
    history_text = "\n".join(
        f"{'Assistant' if m.role == 'assistant' else 'User'}: {m.content}"
        for m in body.history
    )
    prompt = f"""{_INTERVIEW_SYSTEM}

Questions to ask (in order):
{questions_block}

Conversation so far:
{history_text}

User's latest message: {body.user_message}

Your response (next question or INTERVIEW_COMPLETE):"""

    result = await complete(prompt, MODEL_INTERVIEW_SYNTH)
    assistant_reply = result["text"].strip()
    done = "INTERVIEW_COMPLETE" in assistant_reply
    return {"reply": assistant_reply, "done": done}


@profile_ops.post("/ai-interview/finish")
async def interview_finish(
    body: InterviewFinishRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Synthesize the full conversation into structured sections JSON + label."""
    from config import MODEL_INTERVIEW_SYNTH
    from llm import complete

    history_text = "\n".join(
        f"{'Assistant' if m.role == 'assistant' else 'User'}: {m.content}"
        for m in body.history
    )
    prompt = f"""You are given a resume interview transcript. Extract structured resume data and return ONLY valid JSON.

Required JSON shape:
{{
  "label": "concise job title",
  "summary": "one-paragraph professional summary",
  "experience": [{{"company": "...", "title": "...", "dates": "...", "bullets": ["..."]}}],
  "education": [{{"institution": "...", "degree": "...", "dates": "..."}}],
  "skills": ["Skill1", "Skill2"]
}}

Interview transcript:
{history_text}"""

    result = await complete(prompt, MODEL_INTERVIEW_SYNTH)
    text = result["text"].strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
    return _json.loads(text)


@profile_ops.post("/prepare-job")
async def prepare_job_from_profile(
    body: PrepareJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a PipelineJob row seeded from profile sections, returning a job_id for run-pipeline."""
    from db.models import JobStatus, PipelineJob

    profile = await _get_owned(body.profile_id, current_user.id, db)
    resume_text = _sections_to_text(profile.sections or {}) or "Resume text not available."
    job = PipelineJob(
        user_id=current_user.id,
        original_filename=f"{profile.label or 'profile'}.txt",
        resume_text=resume_text,
        status=JobStatus.pending,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {"job_id": str(job.id)}


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
