"""
LoopController - Iteration loop control with persistent gap detection.

Determines when to continue or stop the resume optimization loop based on:
- Quality score reaching threshold
- Maximum iterations reached
- Persistent gaps detected across iterations
"""

from typing import List, Dict, Any
from orchestration.context import PipelineContext


class LoopController:
    """Controls the iteration loop for resume optimization with gap detection."""

    def __init__(self, context: PipelineContext):
        """
        Initialize the loop controller with a pipeline context.

        Args:
            context: PipelineContext instance containing iteration state
        """
        self.context = context

    def should_continue_loop(self) -> bool:
        """
        Determine if the optimization loop should continue.

        Returns False (stop) if any of these conditions are met:
        - Quality score >= threshold
        - Iteration count >= max_iterations
        - Persistent gaps detected

        Returns:
            bool: True if loop should continue, False if it should stop
        """
        # Stop if quality threshold reached
        if self.context.quality_score >= self.context.quality_threshold:
            return False

        # Stop if max iterations reached
        if self.context.iteration_count >= self.context.max_iterations:
            return False

        # Stop if persistent gaps detected
        persistent_gaps = self.get_persistent_gaps()
        if persistent_gaps:
            return False

        # Continue loop if none of the stopping conditions are met
        return True

    def get_persistent_gaps(self) -> List[str]:
        """
        Get gaps that persist across the last 2+ iterations.

        Uses set intersection to find gaps common to all recent iterations.

        Returns:
            List of gap strings that appear in last 2+ iterations, empty if < 2 iterations
        """
        if len(self.context.improvement_history) < 2:
            return []

        # Extract gaps from the last 2 iterations
        gap_sets = []
        for iteration in self.context.improvement_history[-2:]:
            if "gaps" in iteration:
                gap_sets.append(set(iteration["gaps"]))

        # Find intersection (gaps that appear in all last 2 iterations)
        if gap_sets:
            persistent = set.intersection(*gap_sets)
            return list(persistent)

        return []

    def prepare_diagnostic(self) -> Dict[str, Any]:
        """
        Create a diagnostic report explaining why optimization stopped.

        Returns:
            Dict with keys:
                - reason: Why the loop stopped
                - persistent_gaps: List of persistent gaps (if any)
                - unfixable_gaps: List of gaps identified as unfixable
                - recommendation: User-facing recommendation text
        """
        persistent_gaps = self.get_persistent_gaps()
        unfixable_gaps = self._identify_unfixable_gaps(persistent_gaps)

        reason = self._determine_stop_reason()

        recommendation = self._generate_recommendation(persistent_gaps, unfixable_gaps)

        return {
            "reason": reason,
            "persistent_gaps": persistent_gaps,
            "unfixable_gaps": unfixable_gaps,
            "recommendation": recommendation
        }

    def _determine_stop_reason(self) -> str:
        """
        Determine the reason why the loop stopped.

        Returns:
            str: Description of stop reason
        """
        if self.context.quality_score >= self.context.quality_threshold:
            return "Quality threshold reached"

        if self.context.iteration_count >= self.context.max_iterations:
            return "Maximum iterations reached"

        if self.get_persistent_gaps():
            return "Persistent gaps detected that cannot be resolved"

        return "Unknown stop reason"

    def _identify_unfixable_gaps(self, persistent_gaps: List[str]) -> List[str]:
        """
        Identify gaps that are considered unfixable based on keywords.

        Gaps matching patterns like "no metrics", "no quantifiable", "lacks achievement",
        "missing data" are marked as unfixable.

        Args:
            persistent_gaps: List of gap strings to evaluate

        Returns:
            List of gap strings identified as unfixable
        """
        unfixable_keywords = [
            "no metrics",
            "no quantifiable",
            "lacks achievement",
            "missing data"
        ]

        unfixable = []
        for gap in persistent_gaps:
            gap_lower = gap.lower()
            for keyword in unfixable_keywords:
                if keyword in gap_lower:
                    unfixable.append(gap)
                    break

        return unfixable

    def _generate_recommendation(self, persistent_gaps: List[str], unfixable_gaps: List[str]) -> str:
        """
        Generate a user-facing recommendation based on optimization results.

        Args:
            persistent_gaps: List of gaps that persist across iterations
            unfixable_gaps: List of gaps identified as unfixable

        Returns:
            str: User-friendly recommendation text
        """
        if not persistent_gaps:
            return "Optimization complete. Resume quality has reached the target threshold."

        if unfixable_gaps:
            return (
                f"Optimization reached a plateau. The following gaps cannot be resolved "
                f"through rewording alone: {', '.join(unfixable_gaps)}. "
                f"Consider adding real achievements or quantifiable metrics to your resume."
            )

        return (
            f"Optimization complete. Remaining gaps ({', '.join(persistent_gaps)}) "
            f"may require additional content or experience to fully resolve."
        )
