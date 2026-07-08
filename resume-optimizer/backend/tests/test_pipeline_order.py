"""Delivered-text ordering contract (spec 4a): humanize -> normalize -> sanitize
-> guard -> verifier -> final score. Asserted on main.py source order, matching
the repo's existing source-grep test style for pipeline invariants."""

from pathlib import Path

SRC = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")


def _pos(needle: str) -> int:
    idx = SRC.find(needle)
    assert idx != -1, f"main.py no longer contains {needle!r}"
    return idx


def test_tail_order_humanize_guard_verifier_score():
    humanize = _pos("humanize_resume(")
    guard    = _pos("guard_result = await asyncio.to_thread(fabrication_guard")
    verifier = _pos("verify_final_draft(")
    final    = _pos('set_call_kind("final_scoring")')
    assert humanize < guard < verifier < final


def test_call_kinds_set_for_humanize_and_verifier():
    assert 'set_call_kind("humanize")' in SRC
    assert 'set_call_kind("verifier")' in SRC


def test_optimizer_no_longer_owns_verifier():
    opt_src = (Path(__file__).parent.parent / "orchestration" / "optimizer.py").read_text(encoding="utf-8")
    assert "_with_verifier" not in opt_src
    assert "verify_final_draft" not in opt_src


def test_report_carries_honest_gaps():
    from utils.optimization_report import build_report

    report = build_report(
        jd_result={}, original_text="a", optimized_text="b",
        baseline_score=50, final_scores={"average": 80}, iterations=1,
        honest_gaps=["Kubernetes"],
    )
    assert report["gaps_for_jd"] == ["Kubernetes"]
