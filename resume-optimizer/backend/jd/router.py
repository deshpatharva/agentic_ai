import asyncio
import hashlib
import json as _json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from config import MODEL_PROFILE_PARSER
from db.models import JdScrapeCache, Profile, User
from db.session import get_db
from llm import complete
from utils.llm_json import parse_llm_json

router = APIRouter()

_logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 24


class ScrapeRequest(BaseModel):
    url: str


class MatchRequest(BaseModel):
    jd_text: str


@router.post("/jd/scrape")
async def scrape_jd(
    body: ScrapeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch JD text from URL, cache for 24 hours."""
    url_hash = hashlib.sha256(body.url.encode()).hexdigest()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)

    result = await db.execute(
        select(JdScrapeCache).where(
            JdScrapeCache.url_hash == url_hash,
            JdScrapeCache.scraped_at >= cutoff,
        )
    )
    cached = result.scalar_one_or_none()
    if cached:
        return {"jd_text": cached.jd_text, "source_url": body.url, "from_cache": True}

    try:
        jd_text = await _fetch_jd_from_url(body.url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch that URL: {exc}")

    # Upsert
    old = await db.execute(select(JdScrapeCache).where(JdScrapeCache.url_hash == url_hash))
    old_row = old.scalar_one_or_none()
    if old_row:
        old_row.jd_text = jd_text
        old_row.scraped_at = datetime.now(timezone.utc)
    else:
        db.add(JdScrapeCache(url_hash=url_hash, jd_text=jd_text))
    await db.commit()

    return {"jd_text": jd_text, "source_url": body.url, "from_cache": False}


@router.post("/profile/match")
async def match_profiles(
    body: MatchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Rank the user's profiles against a JD. Returns up to 3 matches with match_pct."""
    result = await db.execute(select(Profile).where(Profile.user_id == current_user.id))
    profiles = result.scalars().all()
    if not profiles:
        return []

    profile_dicts = [
        {
            "id": str(p.id),
            "label": p.label or "",
            "skills": (p.sections or {}).get("skills", []),
            "summary": (p.sections or {}).get("summary", ""),
        }
        for p in profiles
    ]
    ranked = await _score_profiles(profile_dicts, body.jd_text)
    return sorted(ranked, key=lambda x: x["match_pct"], reverse=True)[:3]


def _extract_jd_text(html: str) -> str:
    """Extract job description text from HTML. CPU-bound — call via to_thread."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    selectors = [
        "[data-testid='jobDescriptionText']",
        ".job-description",
        ".jobDescriptionContent",
        "article",
        "main",
        "[role='main']",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return text[:15000]

    return soup.get_text(separator="\n", strip=True)[:15000]


async def _fetch_jd_from_url(url: str) -> str:
    """Fetch URL and extract job description text via HTML parsing."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 ResumeOptimizer/1.0"})
        response.raise_for_status()

    # Parsing multi-MB job pages can take long enough to stall other requests.
    return await asyncio.to_thread(_extract_jd_text, response.text)


async def _score_profiles(profile_dicts: list[dict], jd_text: str) -> list[dict]:
    """LLM scores each profile against the JD; returns list with match_pct 0-100."""
    profiles_json = _json.dumps(profile_dicts, ensure_ascii=False)
    prompt = f"""Score how well each candidate profile matches the job description.
Return ONLY a JSON array — no markdown, no explanation.

Array shape:
[{{"profile_id": "...", "label": "...", "match_pct": 0-100, "reason": "one sentence"}}]

Profiles:
{profiles_json}

Job description (first 3000 chars):
{jd_text[:3000]}"""

    result = await complete(prompt, MODEL_PROFILE_PARSER)

    # LLM output is untrusted — recover the array from fences/prose, degrade
    # with a clear 502 instead of an unhandled 500.
    try:
        scored = parse_llm_json(result["text"], kind="array")
    except ValueError:
        _logger.error("profile match returned unparseable JSON (first 300 chars): %s", result["text"][:300])
        raise HTTPException(status_code=502, detail="Profile matching failed — please try again.")

    score_map = {item.get("profile_id"): item for item in scored if isinstance(item, dict)}
    return [
        {
            **p,
            "match_pct": score_map.get(p["id"], {}).get("match_pct", 0),
            "reason": score_map.get(p["id"], {}).get("reason", ""),
        }
        for p in profile_dicts
    ]
