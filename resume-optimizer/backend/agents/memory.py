"""Per-user fact memory — persist ClaimsLedger in Postgres per Profile."""

import json
import logging
from typing import Optional

from agents.fact_extractor import ClaimsLedger

_logger = logging.getLogger(__name__)


def _ledger_to_dict(ledger: ClaimsLedger) -> dict:
    return {
        "companies":   sorted(ledger.companies),
        "metrics":     sorted(ledger.metrics),
        "raw_bullets": list(ledger.raw_bullets),
        "job_titles":  sorted(ledger.job_titles),
        "degrees":     sorted(ledger.degrees),
        "date_ranges": sorted(ledger.date_ranges),
        "capabilities": sorted(ledger.capabilities),
    }


def _dict_to_ledger(d: dict) -> ClaimsLedger:
    return ClaimsLedger(
        companies   = frozenset(d.get("companies", [])),
        metrics     = frozenset(d.get("metrics", [])),
        raw_bullets = tuple(d.get("raw_bullets", [])),
        job_titles  = frozenset(d.get("job_titles", [])),
        degrees     = frozenset(d.get("degrees", [])),
        date_ranges = frozenset(d.get("date_ranges", [])),
        capabilities = frozenset(d.get("capabilities", [])),
    )


def merge_ledgers(base: ClaimsLedger, fresh: ClaimsLedger) -> ClaimsLedger:
    """Union two ledgers — accumulated facts grow over runs."""
    return ClaimsLedger(
        companies   = base.companies   | fresh.companies,
        metrics     = base.metrics     | fresh.metrics,
        raw_bullets = tuple(set(base.raw_bullets) | set(fresh.raw_bullets)),
        job_titles  = base.job_titles  | fresh.job_titles,
        degrees     = base.degrees     | fresh.degrees,
        date_ranges = base.date_ranges | fresh.date_ranges,
        capabilities = base.capabilities | fresh.capabilities,
    )


async def load_claims_ledger(db, profile_id) -> Optional[ClaimsLedger]:
    """Load the stored ClaimsLedger for a profile. Returns None if not set."""
    try:
        from db.models import Profile
        from sqlalchemy import select
        row = (await db.execute(
            select(Profile.claims_ledger_json).where(Profile.id == profile_id)
        )).scalar_one_or_none()
        if not row:
            return None
        return _dict_to_ledger(json.loads(row))
    except Exception:
        _logger.exception("Failed to load claims ledger for profile %s", profile_id)
        return None


async def save_claims_ledger(db, profile_id, ledger: ClaimsLedger) -> None:
    """Persist the ClaimsLedger JSON for a profile."""
    try:
        from db.models import Profile
        from sqlalchemy import update
        await db.execute(
            update(Profile)
            .where(Profile.id == profile_id)
            .values(claims_ledger_json=json.dumps(_ledger_to_dict(ledger)))
        )
        await db.commit()
    except Exception:
        _logger.exception("Failed to save claims ledger for profile %s", profile_id)
