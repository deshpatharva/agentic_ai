"""
Progress Streaming Module

Generates Server-Sent Events (SSE) for real-time optimization progress updates.
All methods return SSE-formatted strings suitable for streaming to clients.
"""

import json
from datetime import datetime, timezone


class ProgressStreamer:
    """Generates SSE-formatted events for real-time progress tracking."""

    @staticmethod
    async def stream_event(event_type: str, data: dict) -> str:
        """
        Generic event formatter that creates SSE-formatted output.

        Args:
            event_type: Type of event (e.g., 'start', 'iteration_start', 'complete')
            data: Event data dictionary

        Returns:
            SSE-formatted string with event and timestamp
        """
        payload = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        return f"data: {json.dumps(payload)}\n\n"

    @staticmethod
    async def optimization_start(optimization_id: str, max_iterations: int) -> str:
        """
        Stream event for optimization start.

        Args:
            optimization_id: Unique optimization identifier
            max_iterations: Maximum iterations for this optimization

        Returns:
            SSE-formatted start event
        """
        return await ProgressStreamer.stream_event(
            "start",
            {
                "optimization_id": optimization_id,
                "max_iterations": max_iterations,
            },
        )

    @staticmethod
    async def iteration_start(iteration: int, total_iterations: int) -> str:
        """
        Stream event for iteration start.

        Args:
            iteration: Current iteration number
            total_iterations: Total iterations expected

        Returns:
            SSE-formatted iteration start event
        """
        return await ProgressStreamer.stream_event(
            "iteration_start",
            {
                "iteration": iteration,
                "total_iterations": total_iterations,
            },
        )

    @staticmethod
    async def task_start(task_name: str, iteration: int) -> str:
        """
        Stream event for task start.

        Args:
            task_name: Name of the task being started
            iteration: Current iteration number

        Returns:
            SSE-formatted task start event
        """
        return await ProgressStreamer.stream_event(
            "task_start",
            {
                "task": task_name,
                "iteration": iteration,
            },
        )

    @staticmethod
    async def task_complete(task_name: str, iteration: int, duration_ms: int) -> str:
        """
        Stream event for task completion.

        Args:
            task_name: Name of the completed task
            iteration: Current iteration number
            duration_ms: Task duration in milliseconds

        Returns:
            SSE-formatted task complete event
        """
        return await ProgressStreamer.stream_event(
            "task_complete",
            {
                "task": task_name,
                "iteration": iteration,
                "duration_ms": duration_ms,
            },
        )

    @staticmethod
    async def iteration_score(iteration: int, quality_score: float, gaps: list) -> str:
        """
        Stream event for iteration quality score.

        Args:
            iteration: Current iteration number
            quality_score: Quality score for this iteration
            gaps: List of identified gaps in the resume

        Returns:
            SSE-formatted iteration score event
        """
        return await ProgressStreamer.stream_event(
            "iteration_score",
            {
                "iteration": iteration,
                "quality_score": quality_score,
                "gaps": gaps,
            },
        )

    @staticmethod
    async def iteration_decision(iteration: int, action: str, reason: str) -> str:
        """
        Stream event for iteration decision (continue or stop).

        Args:
            iteration: Current iteration number
            action: Decision action ('continue' or 'stop')
            reason: Reason for the decision

        Returns:
            SSE-formatted iteration decision event
        """
        return await ProgressStreamer.stream_event(
            "iteration_decision",
            {
                "iteration": iteration,
                "action": action,
                "reason": reason,
            },
        )

    @staticmethod
    async def optimization_complete(result: dict) -> str:
        """
        Stream event for optimization completion.

        Args:
            result: Dictionary containing optimization result data

        Returns:
            SSE-formatted completion event with result and timestamp
        """
        return await ProgressStreamer.stream_event(
            "complete",
            result,
        )
