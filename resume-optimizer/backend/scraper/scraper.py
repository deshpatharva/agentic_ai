"""
Job Scraper — fetches postings from free job APIs and normalises them.

Sources (in priority order):
  1. Adzuna      — free, register at developer.adzuna.com
  2. RemoteOK    — public, no auth required
  3. The Muse    — free, register at themuse.com/api
  4. Apify       — optional paid ($49/mo); activated only if APIFY_TOKEN env exists

All sources return a list of normalised JobPosting dicts:
  {job_title, company, url, source, raw_description, scraped_at}

Call scrape_jobs(keywords) to get deduplicated results from all active sources.
"""

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import (
    ADZUNA_APP_ID,
    ADZUNA_APP_KEY,
    THE_MUSE_API_KEY,
    APIFY_TOKEN,
)

_TIMEOUT = httpx.Timeout(15.0)
_UA = "resumeoptimizer/1.0"


# ── Normalisation helper ──────────────────────────────────────────────────────

def _posting(
    job_title: str,
    company: Optional[str],
    url: Optional[str],
    source: str,
    raw_description: Optional[str],
) -> dict:
    return {
        "job_title":       job_title.strip(),
        "company":         company.strip() if company else None,
        "url":             url.strip() if url else None,
        "source":          source,
        "raw_description": raw_description.strip() if raw_description else None,
        "scraped_at":      datetime.now(timezone.utc).isoformat(),
    }


# ── Source 1: Adzuna ──────────────────────────────────────────────────────────

async def _scrape_adzuna(keywords: str, limit: int = 20) -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id":          ADZUNA_APP_ID,
        "app_key":         ADZUNA_APP_KEY,
        "what":            keywords,
        "results_per_page": min(limit, 50),
        "content-type":    "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = []
    for job in data.get("results", []):
        results.append(_posting(
            job_title=job.get("title", ""),
            company=job.get("company", {}).get("display_name"),
            url=job.get("redirect_url"),
            source="adzuna",
            raw_description=job.get("description"),
        ))
    return results


# ── Source 2: RemoteOK ────────────────────────────────────────────────────────

async def _scrape_remoteok(keywords: str, limit: int = 20) -> list[dict]:
    kw_set = {k.lower().strip() for k in keywords.replace(",", " ").split() if k.strip()}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
            resp = await client.get("https://remoteok.com/api")
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = []
    for job in data:
        if not isinstance(job, dict) or not job.get("position"):
            continue
        tags = {t.lower() for t in job.get("tags", [])}
        if not tags.intersection(kw_set):
            continue
        results.append(_posting(
            job_title=job.get("position", ""),
            company=job.get("company"),
            url=job.get("url"),
            source="remoteok",
            raw_description=job.get("description"),
        ))
        if len(results) >= limit:
            break
    return results


# ── Source 3: The Muse ────────────────────────────────────────────────────────

async def _scrape_the_muse(keywords: str, limit: int = 20) -> list[dict]:
    # The Muse works best with a single category keyword
    primary_kw = keywords.split()[0] if keywords.strip() else "engineering"
    params: dict = {"page": 0, "descending": "true", "category": primary_kw}
    if THE_MUSE_API_KEY:
        params["api_key"] = THE_MUSE_API_KEY

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://www.themuse.com/api/public/jobs",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = []
    for job in data.get("results", [])[:limit]:
        company = job.get("company", {}).get("name") if isinstance(job.get("company"), dict) else None
        # Combine contents (list of content blocks) into a single description
        contents = job.get("contents", "") or ""
        if isinstance(contents, list):
            contents = " ".join(c.get("body", "") for c in contents if isinstance(c, dict))
        refs = job.get("refs", {})
        url = refs.get("landing_page") if isinstance(refs, dict) else None
        results.append(_posting(
            job_title=job.get("name", ""),
            company=company,
            url=url,
            source="the_muse",
            raw_description=contents or None,
        ))
    return results


# ── Source 4: Apify (optional, paid) ─────────────────────────────────────────

async def _scrape_apify(keywords: str, limit: int = 20) -> list[dict]:
    if not APIFY_TOKEN:
        return []

    actor_id = "bebity~linkedin-jobs-scraper"
    run_url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    payload = {
        "searchTerms":   [keywords],
        "location":      "United States",
        "maxResults":    limit,
    }
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(run_url, json=payload, headers=headers)
            resp.raise_for_status()
            items = resp.json()
    except Exception:
        return []

    results = []
    for item in items[:limit]:
        results.append(_posting(
            job_title=item.get("title", ""),
            company=item.get("companyName"),
            url=item.get("jobUrl"),
            source="apify",
            raw_description=item.get("description"),
        ))
    return results


# ── Deduplication ─────────────────────────────────────────────────────────────

def _dedup(postings: list[dict]) -> list[dict]:
    """Remove duplicates by (normalised title + company) fingerprint."""
    seen: set[str] = set()
    unique = []
    for p in postings:
        key = hashlib.md5(
            f"{p['job_title'].lower()}|{(p['company'] or '').lower()}".encode()
        ).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


# ── Public entry point ────────────────────────────────────────────────────────

async def scrape_jobs(keywords: str, per_source: int = 20) -> list[dict]:
    """
    Scrape all active sources concurrently and return deduplicated job postings.

    Args:
        keywords:   Space or comma-separated search terms (e.g. "python backend")
        per_source: Max results to request from each source
    """
    results = await asyncio.gather(
        _scrape_adzuna(keywords, per_source),
        _scrape_remoteok(keywords, per_source),
        _scrape_the_muse(keywords, per_source),
        _scrape_apify(keywords, per_source),
        return_exceptions=True,
    )
    all_postings: list[dict] = []
    for batch in results:
        if isinstance(batch, list):
            all_postings.extend(batch)
    return _dedup(all_postings)
