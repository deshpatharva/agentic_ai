#!/usr/bin/env python3
"""
TEMP full-pipeline cost/token profiler. Safe to delete.

Runs the REAL production LLM path of _run_pipeline_task (Phase 1 -> Phase 2
agent/debate -> verifier -> final score -> guard -> humanize) against live
providers, with per-call instrumentation at the litellm layer:

  - every LLM call: harness phase, prod call_kind, model, msgs, input/output/
    cached tokens, resolved cost, latency
  - phase + model rollups, strategist context growth, cache-hit evidence
  - diagnostics: post-humanize re-score (score drift after delivery-path
    mutations), [VERIFY] marker leak check, call_kind misattribution check

    cd resume-optimizer/backend
    ../.venv/Scripts/python.exe _try_optimizer.py [standard|pro] [max|high]

Writes full ledger + texts to _try_run_<plan>.json for inspection.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND.parent / ".env")
os.environ.setdefault("BOOTSTRAP_SECRET", "harness-bootstrap-secret-not-for-prod")
if not os.environ.get("JWT_SECRET") or "change-me" in os.environ.get("JWT_SECRET", ""):
    os.environ["JWT_SECRET"] = "harness-jwt-secret-32chars-minimum-aaaaaaaa"

for _k in ("GROQ_API_KEY", "DEEPSEEK_API_KEY"):
    if not os.environ.get(_k):
        sys.exit(f"{_k} not set - add it to .env")
if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_AI_STUDIO_API_KEY")):
    sys.exit("GEMINI_API_KEY / GOOGLE_AI_STUDIO_API_KEY not set - add it to .env")

PLAN   = sys.argv[1] if len(sys.argv) > 1 else "standard"
EFFORT = sys.argv[2] if len(sys.argv) > 2 else "max"

# ── Instrumentation (MUST happen before importing agents/orchestration) ──────
import litellm  # noqa: E402
import llm      # noqa: E402

litellm.modify_params = True
llm._DEEPSEEK_REASONING_EFFORT = EFFORT


async def _noop_record(*a, **k):  # no DB in harness
    return None
llm._record_call = _noop_record

ROWS: list[dict] = []          # one row per litellm.acompletion call
PHASE = "startup"              # harness-side ground-truth stage label
PHASE_WALL: dict[str, float] = {}


def _cached_tokens(usage) -> int:
    d = getattr(usage, "prompt_tokens_details", None)
    c = getattr(d, "cached_tokens", 0) or 0 if d else 0
    return c if isinstance(c, int) else 0


_orig_acompletion = litellm.acompletion


async def _traced_acompletion(**kwargs):
    from observability.trace import current_call_kind
    row = {
        "n": len(ROWS) + 1,
        "phase": PHASE,
        "kind": current_call_kind() or "-",
        "model": kwargs.get("model", "?"),
        "msgs": len(kwargs.get("messages") or []),
        "chars": sum(len(json.dumps(m, default=str)) for m in (kwargs.get("messages") or [])),
        "in": 0, "out": 0, "cached": 0,
        "cost": 0.0, "api": "?", "ms": 0, "status": "ok",
    }
    t0 = time.perf_counter()
    try:
        resp = await _orig_acompletion(**kwargs)
    except Exception as exc:
        row["ms"] = int((time.perf_counter() - t0) * 1000)
        row["status"] = f"error:{type(exc).__name__}"
        ROWS.append(row)
        raise
    row["ms"] = int((time.perf_counter() - t0) * 1000)
    usage = getattr(resp, "usage", None)
    row["in"] = getattr(usage, "prompt_tokens", 0) or 0
    row["out"] = getattr(usage, "completion_tokens", 0) or 0
    row["cached"] = _cached_tokens(usage)
    ROWS.append(row)
    return resp

litellm.acompletion = _traced_acompletion

_real_complete = llm.complete
_real_cwt = llm.complete_with_tools


async def _traced_complete(prompt, model, *args, **kwargs):
    n0 = len(ROWS)
    res = await _real_complete(prompt, model, *args, **kwargs)
    for r in ROWS[n0:]:
        r["api"] = "complete"
    if len(ROWS) > n0:
        ROWS[-1]["cost"] = res.get("cost_usd", 0.0)
    return res


async def _traced_complete_with_tools(messages, model, tools, **kwargs):
    n0 = len(ROWS)
    res = await _real_cwt(messages, model, tools, **kwargs)
    for r in ROWS[n0:]:
        r["api"] = "tools"
    if len(ROWS) > n0:
        ROWS[-1]["cost"] = res.get("cost_usd", 0.0)
    return res

llm.complete = _traced_complete
llm.complete_with_tools = _traced_complete_with_tools

# Pipeline imports AFTER patching so `from llm import complete` binds the traced fns.
from agents.fact_extractor import extract_claims            # noqa: E402
from agents.jd_analyzer import analyze_jd                   # noqa: E402
from agents.scorer import score_combined                    # noqa: E402
from agents.fabrication_guard import fabrication_guard      # noqa: E402
from agents.humanizer import humanize_resume                # noqa: E402
import orchestration.optimizer as opt                        # noqa: E402
from config import SCORE_DIMENSIONS, SCORE_TARGET           # noqa: E402
from observability.trace import new_trace, set_call_kind, set_job_context  # noqa: E402
from utils.cost import DEFAULT_PROVIDER_RATES, estimate_cache_savings      # noqa: E402

# ── Gemini substitution ──────────────────────────────────────────────────────
# The GEMINI_API_KEY in .env is currently invalid (Google rejects it), so every
# gemini/* slot is rebound to a stand-in model. Token flow, call structure, and
# cache behaviour stay representative; absolute executor costs/latencies differ.
# Pass "none" as argv[3] to disable once the key is fixed.
SUB_MODEL = sys.argv[3] if len(sys.argv) > 3 else "deepseek/deepseek-v4-flash"
if SUB_MODEL != "none":
    import agents.jd_analyzer as _jd_mod
    import agents.scorer as _sc_mod
    import agents.tools as _tools_mod
    import agents.humanizer as _hum_mod
    import agents.rewriter as _rw_mod
    import orchestration.debate_loop as _dl_mod
    _jd_mod.MODEL_JD_ANALYZER = SUB_MODEL
    _sc_mod.MODEL_SCORER = SUB_MODEL
    _tools_mod.MODEL_KEYWORD_INJECT = SUB_MODEL
    _tools_mod.MODEL_BULLET_STRENGTHEN = SUB_MODEL
    _tools_mod.MODEL_SKILLS_REWRITE = SUB_MODEL
    _hum_mod.MODEL_HUMANIZER = SUB_MODEL
    _rw_mod.MODEL_REWRITER = SUB_MODEL
    _rw_mod.MODEL_REWRITER_FAST = SUB_MODEL
    _dl_mod.MODEL_REVIEWER = SUB_MODEL

_GOOGLE_RATES = DEFAULT_PROVIDER_RATES["google"]  # what prod would pay on flash-lite


def _projected_google_cost(rows: list[dict]) -> float:
    """Cost of substituted-slot rows if billed at google flash-lite rates."""
    tot = 0.0
    for r in rows:
        if r["model"] == SUB_MODEL:
            tot += (r["in"] / 1e6) * _GOOGLE_RATES[0] + (r["out"] / 1e6) * _GOOGLE_RATES[1]
        else:
            tot += _est_cost(r)
    return tot


# Post-Task-12: the verifier is no longer owned by run_optimization_async -- it
# runs in main.py's reordered tail (humanize -> guard -> verifier -> score) on the
# delivered text. The harness mirrors that by calling verify_final_draft directly in
# main() at the new position; import it here (not monkeypatched onto opt anymore,
# which no longer defines it).
from agents.verifier import verify_final_draft  # noqa: E402

# ── Sample inputs (weak-but-real resume; JD with explicit must-haves) ────────

RESUME_TEXT = """John Carter
Boston, MA | john.carter@email.com | (555) 210-8890

Summary
Software engineer with several years of experience working on web applications and backend services. Responsible for various parts of the development lifecycle and helping teams deliver features.

Experience
Meridian Software - Software Engineer (2021 - Present)
- Responsible for building and maintaining REST APIs for the customer portal in Python
- Worked on the PostgreSQL database and helped with query tuning when pages were slow
- Was part of a team that moved some services to AWS
- Helped with code reviews and mentored two junior developers
- Reduced page load time by 40% after reworking the caching layer
- Involved in the on-call rotation and fixed production issues

Brightline Analytics - Junior Developer (2019 - 2021)
- Helped maintain internal reporting dashboards built with Flask
- Wrote SQL queries for the analytics team
- Assisted with deploying applications and fixing bugs reported by users
- Worked on a data cleanup project that saved the team time

Education
B.S. Computer Science, State University (2019)

Skills
Python, Flask, SQL, PostgreSQL, Git, JavaScript, HTML, CSS, some AWS
"""

JD_TEXT = """Senior Backend Engineer - Platform Team

We are looking for a Senior Backend Engineer to design and scale the services behind our B2B SaaS platform.

Must have: 5+ years of backend experience, strong Python (FastAPI or Django), PostgreSQL, AWS (ECS, Lambda, RDS), Docker, and Kubernetes. Required: experience designing distributed systems, building CI/CD pipelines, and operating microservices in production.

Nice to have: Terraform, Kafka or event-driven architectures, observability tooling (Prometheus, Grafana), and mentoring experience.

You will own services end to end: design, implementation, deployment, and monitoring. You will work with product engineers to ship scalable APIs and improve reliability across the platform.
"""

TOOL_STEPS: list[str] = []


def _on_event(ev: dict):
    t = ev.get("type", "")
    if t in ("agent_step", "debate_review"):
        msg = ev.get("message", "")[:150]
        TOOL_STEPS.append(msg)
        print(f"    . {msg}")
    elif t == "stage":
        print(f"  [stage] {ev.get('message', '')[:120]}")


def _phase(name: str):
    global PHASE
    PHASE = name
    PHASE_WALL.setdefault(name, 0.0)
    return time.perf_counter()


def _phase_end(name: str, t0: float):
    PHASE_WALL[name] = PHASE_WALL.get(name, 0.0) + (time.perf_counter() - t0)


def _avg(scores: dict) -> int:
    return round(sum(scores.get(k, {}).get("score", 0) for k in SCORE_DIMENSIONS) / len(SCORE_DIMENSIONS))


def _flat(scores: dict) -> dict:
    return {k: scores.get(k, {}).get("score", 0) for k in SCORE_DIMENSIONS}


def _est_cost(row: dict) -> float:
    """Resolved cost if litellm priced it, else DEFAULT_PROVIDER_RATES estimate."""
    if row["cost"] > 0:
        return row["cost"]
    provider = row["model"].split("/", 1)[0]
    provider = {"gemini": "google"}.get(provider, provider)
    rates = DEFAULT_PROVIDER_RATES.get(provider)
    if not rates:
        return 0.0
    return (row["in"] / 1e6) * rates[0] + (row["out"] / 1e6) * rates[1]


async def main():
    overall_t0 = time.perf_counter()
    new_trace("harness")
    set_job_context(None, None)

    print("=" * 78)
    print(f"  FULL-PIPELINE PROFILER  plan={PLAN}  effort={EFFORT}")
    print(f"  optimizer={os.environ.get('MODEL_OPTIMIZER', 'deepseek/deepseek-v4-pro')}")
    if SUB_MODEL != "none":
        print(f"  NOTE: GEMINI_API_KEY invalid -> gemini/* slots substituted with {SUB_MODEL}")
    print("=" * 78)

    # ── Phase 1 (mirrors main.py:951-1004) ──────────────────────────────────
    t = _phase("claims_extraction")
    ledger = extract_claims(RESUME_TEXT)
    _phase_end("claims_extraction", t)

    t = _phase("jd_analysis")
    set_call_kind("jd_analysis")
    jd_dict = await analyze_jd(JD_TEXT)
    _phase_end("jd_analysis", t)
    jd = jd_dict.get("text", jd_dict)
    jd_keywords = jd.get("keywords", [])
    required_hard_skills = jd.get("required_hard_skills", [])
    seniority = jd.get("seniority_level", "mid")
    industry = jd.get("industry", "")

    t = _phase("baseline_scoring")
    set_call_kind("baseline_scoring")
    baseline_dict = await score_combined(
        RESUME_TEXT, JD_TEXT, jd_keywords=jd_keywords,
        seniority_level=seniority, required_hard_skills=required_hard_skills,
    )
    _phase_end("baseline_scoring", t)
    baseline = baseline_dict.get("text", {})
    print(f"\n  baseline: avg={_avg(baseline)} {_flat(baseline)}")
    print(f"  jd: seniority={seniority} keywords={len(jd_keywords)} required={required_hard_skills[:8]}")

    # ── Phase 2 (mirrors main.py:1014-1043) ─────────────────────────────────
    t = _phase("phase2_agent")
    result = await opt.run_optimization_async(
        job_id="harness", resume_text=RESUME_TEXT, jd_text=JD_TEXT,
        jd_keywords=jd_keywords, claims_ledger=ledger,
        scores=baseline, seniority_level=seniority,
        required_hard_skills=required_hard_skills,
        on_event=_on_event, plan=PLAN,
    )
    _phase_end("phase2_agent", t)
    optimized = result["text"]
    print(f"\n  phase2: iterations={result['iterations']} fallback={result.get('fallback')} "
          f"honest_gaps={result.get('honest_gaps')}")

    # ── Delivered-text tail (mirrors Task 12 main.py:1053-1157) ──────────────
    # New prod order: humanize -> (normalize/sanitize, pure-CPU, omitted here as
    # they make no LLM calls) -> guard -> verifier -> final score. Everything
    # downstream now operates on the actual delivered text.
    t = _phase("humanize")
    set_call_kind("humanize")
    humanize_dict = await humanize_resume(optimized, industry=industry, seniority_level=seniority)
    _phase_end("humanize", t)
    humanized = humanize_dict.get("text", optimized)

    t = _phase("fabrication_guard")
    guard = fabrication_guard(humanized, ledger, RESUME_TEXT)
    _phase_end("fabrication_guard", t)
    final_text = guard.text  # the delivered text: guarded, post-humanize

    t = _phase("verifier")
    set_call_kind("verifier")
    vr = await verify_final_draft(final_text, ledger, RESUME_TEXT)
    _phase_end("verifier", t)

    # ── Final score on the DELIVERED text (mirrors main.py:1136) ─────────────
    t = _phase("final_scoring")
    set_call_kind("final_scoring")
    final_dict = await score_combined(
        final_text, JD_TEXT, jd_keywords=jd_keywords,
        seniority_level=seniority, required_hard_skills=required_hard_skills,
    )
    _phase_end("final_scoring", t)
    final_scores = final_dict.get("text", {})
    print(f"  final score (on delivered text): avg={_avg(final_scores)}  "
          f"verifier_flagged={len(vr.flagged)}  honest_gaps={result.get('honest_gaps')}")

    # ── Diagnostics: re-score the delivered text again. Post-Task-12, delivered
    # == scored, so this must MATCH the final score (LRU-cache hit, 0 tokens) --
    # a consistency check, no longer a "delivery drift" measurement. ─────────
    t = _phase("diag_rescore")
    set_call_kind("harness_diag")
    n_before = len(ROWS)
    diag_dict = await score_combined(
        final_text, JD_TEXT, jd_keywords=jd_keywords,
        seniority_level=seniority, required_hard_skills=required_hard_skills,
    )
    _phase_end("diag_rescore", t)
    diag_scores = diag_dict.get("text", {})
    diag_lru_hit = len(ROWS) == n_before
    print(f"  diag re-score (consistency): avg={_avg(diag_scores)}  "
          f"LRU-hit={diag_lru_hit} (expect True: delivered text scored twice)")

    wall = time.perf_counter() - overall_t0

    # ══ REPORT ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 78)
    print("  CALL LEDGER (every litellm call, in order)")
    print("=" * 78)
    hdr = f"  {'#':>2} {'phase':<18} {'prod call_kind':<17} {'model':<28} {'api':<8} {'in':>6} {'out':>6} {'cach':>5} {'cost$':>8} {'ms':>6}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in ROWS:
        model_short = r["model"].split("/", 1)[-1][:28]
        print(f"  {r['n']:>2} {r['phase']:<18} {r['kind']:<17} {model_short:<28} {r['api']:<8} "
              f"{r['in']:>6} {r['out']:>6} {r['cached']:>5} {_est_cost(r):>8.5f} {r['ms']:>6}"
              + ("" if r["status"] == "ok" else f"  {r['status']}"))

    print("\n  PHASE ROLLUP")
    print(f"  {'phase':<20} {'calls':>5} {'in':>7} {'out':>7} {'cached':>7} {'cost$':>9} {'wall_s':>7}")
    order = ["claims_extraction", "jd_analysis", "baseline_scoring", "phase2_agent",
             "humanize", "fabrication_guard", "verifier", "final_scoring", "diag_rescore"]
    for ph in order:
        rows = [r for r in ROWS if r["phase"] == ph]
        note = ""
        if ph == "final_scoring" and not rows:
            note = "  <- LRU result-cache hit (0 LLM calls)"
        if ph in ("claims_extraction", "fabrication_guard") and not rows:
            note = "  (CPU only)"
        print(f"  {ph:<20} {len(rows):>5} {sum(r['in'] for r in rows):>7} {sum(r['out'] for r in rows):>7} "
              f"{sum(r['cached'] for r in rows):>7} {sum(_est_cost(r) for r in rows):>9.5f} "
              f"{PHASE_WALL.get(ph, 0.0):>7.1f}{note}")

    print("\n  MODEL ROLLUP")
    by_model: dict[str, list] = {}
    for r in ROWS:
        by_model.setdefault(r["model"], []).append(r)
    for m, rows in sorted(by_model.items(), key=lambda kv: -sum(_est_cost(r) for r in kv[1])):
        print(f"  {m:<38} calls={len(rows):>2} in={sum(r['in'] for r in rows):>7} "
              f"out={sum(r['out'] for r in rows):>6} cached={sum(r['cached'] for r in rows):>6} "
              f"cost=${sum(_est_cost(r) for r in rows):.5f}")

    strat = [r for r in ROWS if r["api"] == "tools"]
    if strat:
        print("\n  STRATEGIST CONTEXT GROWTH (complete_with_tools turns)")
        print(f"  {'turn':>4} {'msgs':>5} {'chars':>7} {'in':>7} {'cached':>7} {'cache%':>7} {'out':>6} {'ms':>6}")
        for i, r in enumerate(strat, 1):
            pct = (100.0 * r["cached"] / r["in"]) if r["in"] else 0.0
            print(f"  {i:>4} {r['msgs']:>5} {r['chars']:>7} {r['in']:>7} {r['cached']:>7} {pct:>6.0f}% {r['out']:>6} {r['ms']:>6}")

    prod_rows = [r for r in ROWS if r["phase"] != "diag_rescore"]
    resolved = sum(r["cost"] for r in prod_rows)
    estimated = sum(_est_cost(r) for r in prod_rows)
    cached_total = sum(r["cached"] for r in prod_rows)
    savings = estimate_cache_savings([(r["model"], r["cached"]) for r in prod_rows])
    print("\n  TOTALS (prod-path calls only, diag excluded)")
    print(f"  llm calls: {len(prod_rows)}   input: {sum(r['in'] for r in prod_rows):,}   "
          f"output: {sum(r['out'] for r in prod_rows):,}   cached-input: {cached_total:,}")
    print(f"  cost resolved by litellm: ${resolved:.5f}   with fallback estimates: ${estimated:.5f}")
    if SUB_MODEL != "none":
        print(f"  projected cost if substituted slots ran on gemini flash-lite rates: ${_projected_google_cost(prod_rows):.5f}")
    print(f"  est. saved by provider prompt caches: ${savings:.5f}")
    print(f"  wall time: {wall:.1f}s")

    print("\n  SCORES  (baseline -> final[on delivered text] -> diag re-score)")
    # Post-Task-12 the final score already runs on the delivered text, so final
    # and diag are the SAME text scored twice -- they must match (consistency),
    # replacing the old pre-humanize-vs-delivered "delivery drift" measurement.
    fb, ff, fd = _flat(baseline), _flat(final_scores), _flat(diag_scores)
    for k in SCORE_DIMENSIONS:
        delta = fd[k] - ff[k]
        print(f"  {k:<14} {fb[k]:>3} -> {ff[k]:>3} -> {fd[k]:>3}   (consistency {delta:+d}, expect 0)")
    print(f"  {'average':<14} {_avg(baseline):>3} -> {_avg(final_scores):>3} -> {_avg(diag_scores):>3}   "
          f"(prod reports {_avg(final_scores)} on the exact text the user receives)")

    print("\n  INTEGRITY CHECKS")
    print(f"  guard gaps: {len(guard.gaps)}  {guard.gaps[:3]}")
    print(f"  guard capability_gaps: {guard.capability_gaps}")
    print(f"  verifier flagged: {vr.flagged[:3]}")
    print(f"  honest_gaps (phase2 result): {result.get('honest_gaps')}")
    print(f"  [VERIFY] in agent output: {'[VERIFY]' in optimized} | in humanized: {'[VERIFY]' in humanized} "
          f"| in delivered: {'[VERIFY]' in final_text}")
    ver_rows = [r for r in ROWS if r["phase"] == "verifier"]
    hum_rows = [r for r in ROWS if r["phase"] == "humanize"]
    if ver_rows:
        print(f"  verifier rows call_kind: {set(r['kind'] for r in ver_rows)} (correct = 'verifier')")
    if hum_rows:
        print(f"  humanize rows call_kind: {set(r['kind'] for r in hum_rows)} (correct = 'humanize')")
    print(f"  words: original={len(RESUME_TEXT.split())} optimized={len(optimized.split())} delivered={len(final_text.split())}")

    # ── TRUTHFULNESS ASSERTIONS (regression gate; spec Testing section) ──────
    from utils.skills_normalizer import taxonomy_terms
    import re as _re

    failures: list[str] = []
    if "[VERIFY]" in final_text:
        failures.append("[VERIFY] marker leaked into delivered text")
    _allowed = set(ledger.capabilities) | {
        t for t in taxonomy_terms()
        if _re.search(r"(?<![\w+#])" + _re.escape(t) + r"(?![\w+#])", RESUME_TEXT.lower())
    }
    _leaked = sorted(
        t for t in taxonomy_terms()
        if _re.search(r"(?<![\w+#])" + _re.escape(t) + r"(?![\w+#])", final_text.lower())
        and t not in _allowed
    )
    if _leaked:
        failures.append(f"unevidenced capabilities in delivered text: {_leaked}")
    if not result.get("honest_gaps"):
        failures.append("phase2 result missing honest_gaps (None or empty)")

    print("\n  TRUTHFULNESS ASSERTIONS")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
    else:
        print("  all passed: no markers, no unevidenced capabilities, gaps reported")

    out = {
        "plan": PLAN, "effort": EFFORT, "wall_s": wall,
        "rows": ROWS, "phase_wall": PHASE_WALL, "tool_steps": TOOL_STEPS,
        "scores": {"baseline": fb, "final_on_delivered": ff, "diag_rescore": fd},
        "texts": {"original": RESUME_TEXT, "optimized": optimized,
                  "humanized": humanized, "delivered": final_text},
        "guard_gaps": guard.gaps, "capability_gaps": guard.capability_gaps,
        "verifier_flagged": vr.flagged, "honest_gaps": result.get("honest_gaps"),
        "truthfulness_failures": failures,
    }
    dump = BACKEND / f"_try_run_{PLAN}.json"
    dump.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n  full ledger + texts -> {dump.name}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
