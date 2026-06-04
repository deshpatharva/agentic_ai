"""Pipeline context - shared state for the entire resume optimization pipeline."""

from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict
from datetime import datetime


@dataclass
class PipelineContext:
    """Shared state context for the entire resume optimization pipeline."""

    # Input fields
    resume_text: str
    jd_text: str
    user_id: str
    optimization_id: str

    # Configuration fields
    max_iterations: int = 3
    quality_threshold: float = 0.85

    # Task outputs
    claims_ledger: Dict[str, Any] = field(default_factory=dict)
    jd_analysis: Dict[str, Any] = field(default_factory=dict)
    rewritten_resume: str = ""
    humanized_resume: str = ""
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    validation_report: Dict[str, Any] = field(default_factory=dict)

    # Loop tracking
    iteration_count: int = 0
    quality_score: float = 0.0
    improvement_history: List[Dict[str, Any]] = field(default_factory=list)
    persistent_gaps: List[str] = field(default_factory=list)

    # Token/cost tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_cents: int = 0

    # Error tracking
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def record_error(self, task_name: str, error: str) -> None:
        """Record an error with task name and timestamp."""
        self.errors.append({
            "task_name": task_name,
            "error": error,
            "timestamp": datetime.utcnow().isoformat()
        })

    def record_warning(self, task_name: str, warning: str) -> None:
        """Record a warning with task name and timestamp."""
        self.warnings.append({
            "task_name": task_name,
            "warning": warning,
            "timestamp": datetime.utcnow().isoformat()
        })

    def add_iteration_history(self) -> None:
        """Record current iteration state to improvement history."""
        self.improvement_history.append({
            "iteration": self.iteration_count,
            "quality_score": self.quality_score,
            "timestamp": datetime.utcnow().isoformat()
        })

    def update_timestamp(self) -> None:
        """Update the updated_at timestamp to now."""
        self.updated_at = datetime.utcnow().isoformat()
