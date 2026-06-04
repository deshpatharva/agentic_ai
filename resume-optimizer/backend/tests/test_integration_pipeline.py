"""Integration tests for the full resume optimization pipeline.

These tests exercise end-to-end flows:
- Extract claims -> Score flow
- Loop controller iteration logic

Uses mock agents to avoid LLM calls and external dependencies.
"""

import sys
from pathlib import Path
from unittest.mock import Mock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestration.context import PipelineContext
from orchestration.pipeline import PipelineExecutor
from orchestration.loop_controller import LoopController


# ── Test 1: Full pipeline with extract → score flow ─────────────────────────────

@pytest.mark.asyncio
async def test_full_pipeline_extracts_then_scores():
    """
    Full pipeline: extract claims, then score resume.

    Verifies:
    - PipelineContext can be created with sample data
    - Extract claims task populates claims_ledger
    - Score task sets quality_score >= 0.0
    """
    # Create context with sample resume and JD
    sample_resume = """
    Senior Software Engineer

    • Led development team of 5 engineers resulting in 30% performance improvement
    • Increased revenue by $2M through optimization of core systems
    • Implemented machine learning feature used by 100K+ users
    • Metrics: 3x faster load times, 99.9% uptime
    """

    sample_jd = """
    Senior Software Engineer
    Requirements:
    - 5+ years of experience
    - Leadership experience
    - Performance optimization
    - Revenue impact
    """

    context = PipelineContext(
        resume_text=sample_resume,
        jd_text=sample_jd,
        user_id="test_user_1",
        optimization_id="test_opt_1"
    )

    # Create executor
    executor = PipelineExecutor()

    # Mock fact extractor agent
    mock_fact_extractor = Mock()
    mock_fact_extractor.execute = Mock(return_value={
        "metrics": {"30%", "$2M", "3x", "99.9%"},
        "companies": {""},
        "raw_bullets": [
            "Led development team of 5 engineers resulting in 30% performance improvement",
            "Increased revenue by $2M through optimization of core systems",
            "Implemented machine learning feature used by 100K+ users"
        ]
    })

    # Execute extract_claims task
    extract_result = await executor.execute_task(
        task_name="extract_claims",
        agent=mock_fact_extractor,
        context=context,
        task_input={"resume": context.resume_text}
    )

    # Verify claims_ledger is populated
    assert context.claims_ledger is not None
    assert "metrics" in extract_result
    assert "30%" in extract_result["metrics"]
    assert "$2M" in extract_result["metrics"]

    # Mock scorer agent
    mock_scorer = Mock()
    mock_scorer.execute = Mock(return_value={
        "ats_match": 0.85,
        "impact_score": 0.78,
        "skills_gap": 0.92,
        "readability": 0.88,
        "overall": 0.86
    })

    # Execute score task
    score_result = await executor.execute_task(
        task_name="score",
        agent=mock_scorer,
        context=context,
        task_input={
            "resume": context.resume_text,
            "jd_analysis": context.jd_analysis
        }
    )

    # Verify score_breakdown is set
    assert context.score_breakdown is not None
    assert "overall" in score_result
    assert score_result["overall"] >= 0.0
    assert score_result["overall"] <= 1.0


# ── Test 2: Loop controller respects max_iterations ─────────────────────────────

@pytest.mark.asyncio
async def test_loop_controller_respects_max_iterations():
    """
    LoopController stops when iteration_count >= max_iterations.

    Verifies:
    - LoopController initialized with context
    - should_continue_loop() returns False when max_iterations reached
    """
    # Create context with max_iterations=2
    context = PipelineContext(
        resume_text="Sample resume",
        jd_text="Sample JD",
        user_id="test_user_2",
        optimization_id="test_opt_2",
        max_iterations=2
    )

    # Set iteration_count to max_iterations
    context.iteration_count = 2

    # Create loop controller
    loop_controller = LoopController(context)

    # Verify should_continue_loop returns False
    should_continue = loop_controller.should_continue_loop()
    assert should_continue is False

    # Verify the reason is "Maximum iterations reached"
    diagnostic = loop_controller.prepare_diagnostic()
    assert diagnostic["reason"] == "Maximum iterations reached"


# ── Additional edge case tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_loop_controller_continues_below_max_iterations():
    """
    LoopController continues when iteration_count < max_iterations
    and quality_score < threshold.
    """
    context = PipelineContext(
        resume_text="Sample resume",
        jd_text="Sample JD",
        user_id="test_user_3",
        optimization_id="test_opt_3",
        max_iterations=3,
        quality_threshold=0.85
    )

    # Set iteration_count below max
    context.iteration_count = 1
    context.quality_score = 0.70  # Below threshold

    loop_controller = LoopController(context)

    # Should continue
    should_continue = loop_controller.should_continue_loop()
    assert should_continue is True


@pytest.mark.asyncio
async def test_loop_controller_stops_at_quality_threshold():
    """
    LoopController stops when quality_score >= quality_threshold.
    """
    context = PipelineContext(
        resume_text="Sample resume",
        jd_text="Sample JD",
        user_id="test_user_4",
        optimization_id="test_opt_4",
        max_iterations=3,
        quality_threshold=0.85
    )

    # Set quality_score above threshold
    context.quality_score = 0.90
    context.iteration_count = 1

    loop_controller = LoopController(context)

    # Should stop
    should_continue = loop_controller.should_continue_loop()
    assert should_continue is False

    # Verify the reason
    diagnostic = loop_controller.prepare_diagnostic()
    assert diagnostic["reason"] == "Quality threshold reached"


@pytest.mark.asyncio
async def test_pipeline_context_records_errors():
    """
    PipelineContext can record errors with task name and timestamp.
    """
    context = PipelineContext(
        resume_text="Sample resume",
        jd_text="Sample JD",
        user_id="test_user_5",
        optimization_id="test_opt_5"
    )

    # Record an error
    context.record_error("extract_claims", "Failed to parse resume")

    # Verify error is recorded
    assert len(context.errors) == 1
    assert context.errors[0]["task_name"] == "extract_claims"
    assert "Failed to parse resume" in context.errors[0]["error"]
    assert "timestamp" in context.errors[0]


@pytest.mark.asyncio
async def test_pipeline_context_tracks_iteration_history():
    """
    PipelineContext can track improvement history across iterations.
    """
    context = PipelineContext(
        resume_text="Sample resume",
        jd_text="Sample JD",
        user_id="test_user_6",
        optimization_id="test_opt_6"
    )

    # Simulate iterations
    for iteration in range(1, 4):
        context.iteration_count = iteration
        context.quality_score = 0.70 + (iteration * 0.05)
        context.add_iteration_history()

    # Verify history is tracked
    assert len(context.improvement_history) == 3
    assert abs(context.improvement_history[0]["quality_score"] - 0.75) < 0.001
    assert abs(context.improvement_history[1]["quality_score"] - 0.80) < 0.001
    assert abs(context.improvement_history[2]["quality_score"] - 0.85) < 0.001
