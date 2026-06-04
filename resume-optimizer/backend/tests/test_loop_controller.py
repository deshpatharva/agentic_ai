"""Unit tests for LoopController - iteration loop control with gap detection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestration.context import PipelineContext
from orchestration.loop_controller import LoopController


def test_loop_controller_stops_at_threshold():
    """LoopController should stop when quality_score >= threshold."""
    # Setup context with high quality score
    context = PipelineContext(
        resume_text="Senior engineer with 10 years experience",
        jd_text="Looking for a senior engineer",
        user_id="test_user",
        optimization_id="test_opt",
        quality_threshold=0.85,
        max_iterations=5
    )

    # Set iteration state
    context.iteration_count = 2
    context.quality_score = 0.90  # Above threshold

    # Create controller
    controller = LoopController(context)

    # Should return False (stop loop)
    assert controller.should_continue_loop() is False


def test_loop_controller_detects_persistent_gaps():
    """LoopController should detect gaps that persist across iterations."""
    # Setup context
    context = PipelineContext(
        resume_text="Senior engineer with 10 years experience",
        jd_text="Looking for a senior engineer",
        user_id="test_user",
        optimization_id="test_opt",
        quality_threshold=0.85,
        max_iterations=5
    )

    # Set iteration state with quality below threshold
    context.iteration_count = 2
    context.quality_score = 0.70  # Below threshold

    # Record improvement history with persistent gaps
    # Iteration 1: gaps = ["no metrics", "missing technical skills"]
    context.improvement_history.append({
        "iteration": 1,
        "quality_score": 0.65,
        "gaps": ["no metrics", "missing technical skills", "other gap"]
    })

    # Iteration 2: gaps = ["no metrics", "missing technical skills"] (persistent)
    context.improvement_history.append({
        "iteration": 2,
        "quality_score": 0.70,
        "gaps": ["no metrics", "missing technical skills", "different gap"]
    })

    # Create controller
    controller = LoopController(context)

    # Get persistent gaps
    persistent_gaps = controller.get_persistent_gaps()

    # Should detect the 2 gaps that appear in both iterations
    assert len(persistent_gaps) >= 2
    assert "no metrics" in persistent_gaps
    assert "missing technical skills" in persistent_gaps
