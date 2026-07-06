"""The provider allowlist and default fallback rates must live in one place, so
admin validation, init_db seeding, and the migration can't drift (which would
let a new provider record cost_source='zero' until every copy is updated).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("BOOTSTRAP_SECRET", "test-bootstrap")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-long-enough-x")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_providers.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("GOOGLE_AI_STUDIO_API_KEY", "test")
os.environ.setdefault("GROQ_API_KEY", "test")


def test_allowed_providers_derive_from_default_rates():
    from utils.cost import ALLOWED_PROVIDERS, DEFAULT_PROVIDER_RATES
    assert set(ALLOWED_PROVIDERS) == set(DEFAULT_PROVIDER_RATES)
    assert "deepseek" in ALLOWED_PROVIDERS


def test_default_rates_are_positive_per_million():
    from utils.cost import DEFAULT_PROVIDER_RATES
    for provider, (in_rate, out_rate) in DEFAULT_PROVIDER_RATES.items():
        assert in_rate > 0 and out_rate > 0, provider


def test_admin_validation_uses_shared_allowlist():
    # create_provider_cost validates membership against the shared constant, not
    # a hand-typed inline list.
    from admin import router as admin_router
    from utils.cost import ALLOWED_PROVIDERS
    assert admin_router.ALLOWED_PROVIDERS is ALLOWED_PROVIDERS
