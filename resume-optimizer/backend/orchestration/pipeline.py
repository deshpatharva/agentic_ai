"""
PipelineExecutor - Sequential task execution orchestrator for resume optimization pipeline.

Executes CrewAI tasks sequentially, maintaining isolated context for each task
to prevent token doubling with CrewAI's auto-context feature.
"""

import asyncio
from typing import Any, Dict, Optional
from llm.cost_tracker import CostTracker
from orchestration.context import PipelineContext


class PipelineExecutor:
    """
    Executes tasks sequentially in the resume optimization pipeline.

    Maintains a CostTracker to monitor token usage and costs across all tasks.
    Each task receives only the minimal context it needs to prevent token doubling.
    """

    def __init__(self):
        """Initialize the executor with a CostTracker."""
        self.cost_tracker = CostTracker()

    async def execute_task(
        self,
        task_name: str,
        agent: Any,
        context: PipelineContext,
        task_input: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a single task asynchronously.

        Prepares minimal context for the task, executes it via CrewAI Task.execute(),
        and updates the pipeline context with the result.

        Args:
            task_name: Name of the task (e.g., "extract_claims", "analyze_jd")
            agent: CrewAI Agent instance to execute the task
            context: PipelineContext instance to update
            task_input: Optional task input dict (if not provided, prepares minimal context)

        Returns:
            Dict with task execution result
        """
        # Prepare minimal context input if not provided
        if task_input is None:
            task_input = self._prepare_task_input(task_name, context)

        # Create a mock CrewAI Task (since we're using agents directly)
        # In real usage with CrewAI, this would be a Task object
        # For now, we mock the execute call
        try:
            # Execute the task asynchronously using asyncio.to_thread
            # This allows calling sync CrewAI Task.execute in an async context
            result = await asyncio.to_thread(
                self._execute_task_sync,
                task_name,
                agent,
                task_input
            )
        except Exception as e:
            context.record_error(task_name, str(e))
            raise

        # Update the pipeline context with the result
        self._update_context(task_name, context, result)

        return result

    def _execute_task_sync(
        self,
        task_name: str,
        agent: Any,
        task_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Synchronously execute a task.

        This wraps the actual CrewAI Task.execute() call.
        In production, agent would have a task attribute or we'd create a Task object.

        Args:
            task_name: Name of the task
            agent: CrewAI Agent instance
            task_input: Input dictionary for the task

        Returns:
            Task execution result
        """
        # If agent has a task attribute (from CrewAI), execute it
        # Otherwise, this is a mock for testing
        if hasattr(agent, 'execute'):
            return agent.execute(task_input)

        # For mocking in tests, this won't be reached
        return {}

    def _prepare_task_input(
        self,
        task_name: str,
        context: PipelineContext,
    ) -> Dict[str, Any]:
        """
        Prepare minimal context input for a specific task.

        CRITICAL: Only includes what each task needs to prevent token doubling
        with CrewAI's auto-context feature.

        Args:
            task_name: Name of the task
            context: Full PipelineContext

        Returns:
            Minimal dict with only required context for this task
        """
        task_inputs = {
            # Extract claims from resume - needs only resume text
            "extract_claims": {
                "resume": context.resume_text,
            },
            # Analyze job description - needs only JD text
            "analyze_jd": {
                "jd_text": context.jd_text,
            },
            # Rewrite resume - needs resume text and JD analysis
            "rewrite": {
                "resume": context.resume_text,
                "jd_analysis": context.jd_analysis,
                "claims_ledger": context.claims_ledger,
            },
            # Humanize resume - needs the rewritten resume
            "humanize": {
                "resume": context.rewritten_resume or context.resume_text,
            },
            # Score resume - needs humanized resume and JD analysis
            "score": {
                "resume": context.humanized_resume or context.rewritten_resume or context.resume_text,
                "jd_analysis": context.jd_analysis,
            },
            # Validate resume - needs humanized resume and validation criteria
            "validate": {
                "resume": context.humanized_resume or context.rewritten_resume or context.resume_text,
                "claims_ledger": context.claims_ledger,
            },
        }

        # Return task-specific input, or empty dict if task not recognized
        return task_inputs.get(task_name, {})

    def _update_context(
        self,
        task_name: str,
        context: PipelineContext,
        result: Dict[str, Any],
    ) -> None:
        """
        Update the pipeline context with task result.

        Maps task-specific results to the appropriate context fields.

        Args:
            task_name: Name of the task
            context: PipelineContext to update
            result: Task execution result
        """
        # Map task results to context fields
        if task_name == "extract_claims":
            context.claims_ledger = result
        elif task_name == "analyze_jd":
            context.jd_analysis = result
        elif task_name == "rewrite":
            context.rewritten_resume = result.get("resume", "") if isinstance(result, dict) else str(result)
        elif task_name == "humanize":
            context.humanized_resume = result.get("resume", "") if isinstance(result, dict) else str(result)
        elif task_name == "score":
            context.score_breakdown = result
        elif task_name == "validate":
            context.validation_report = result

        # Update timestamp
        context.update_timestamp()
