"""Unit tests for PipelineExecutor - sequential task execution."""

import sys
from pathlib import Path
import asyncio
from unittest.mock import Mock, AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestration.pipeline import PipelineExecutor
from orchestration.context import PipelineContext


@pytest.mark.asyncio
async def test_pipeline_executor_executes_single_task():
    """PipelineExecutor successfully executes a task and returns result."""
    # Setup context
    context = PipelineContext(
        resume_text="Senior engineer with 10 years experience",
        jd_text="Looking for a senior engineer",
        user_id="test_user",
        optimization_id="test_opt"
    )

    # Create mock agent with execute method
    mock_agent = Mock()
    mock_agent.execute = Mock(return_value={
        "claims": {"metric1": "value1"},
        "status": "success"
    })

    executor = PipelineExecutor()

    # Execute the task
    result = await executor.execute_task(
        task_name="extract_claims",
        agent=mock_agent,
        context=context,
        task_input={"resume": context.resume_text}
    )

    # Verify result is returned
    assert result is not None
    assert "claims" in result
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_pipeline_executor_updates_context():
    """PipelineExecutor correctly updates context with task results."""
    # Setup context
    context = PipelineContext(
        resume_text="Senior engineer with 10 years experience",
        jd_text="Looking for a senior engineer",
        user_id="test_user",
        optimization_id="test_opt"
    )

    # Create mock agent with execute method
    mock_agent = Mock()
    mock_agent.execute = Mock(return_value={
        "metrics": ["30%", "5x improvement"],
        "companies": ["TechCorp"]
    })

    executor = PipelineExecutor()

    # Execute task that updates claims_ledger
    result = await executor.execute_task(
        task_name="extract_claims",
        agent=mock_agent,
        context=context,
        task_input={"resume": context.resume_text}
    )

    # Verify context was updated
    assert context.claims_ledger is not None
    assert context.claims_ledger == result
