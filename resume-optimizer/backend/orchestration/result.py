"""Result formatter - structures final output from the optimization pipeline."""

from typing import Optional, Dict, Any
from .context import PipelineContext


def format_result(context: PipelineContext, reached_threshold: bool, diagnostic: Optional[Dict[str, Any]] = None) -> dict:
    """
    Format the final result of a successful optimization run.

    Args:
        context: The pipeline context containing optimization results
        reached_threshold: Whether the quality score reached the threshold
        diagnostic: Optional diagnostic information if threshold not reached

    Returns:
        Dictionary with formatted result data
    """
    result = {
        "success": True,
        "optimization_id": context.optimization_id,
        "resume": context.humanized_resume or context.resume_text,
        "quality_score": context.quality_score,
        "reached_threshold": reached_threshold,
        "iterations_used": context.iteration_count,
        "improvement_history": context.improvement_history,
        "token_cost": {
            "input_tokens": context.total_input_tokens,
            "output_tokens": context.total_output_tokens,
            "total_tokens": context.total_input_tokens + context.total_output_tokens,
            "cost_cents": context.total_cost_cents
        },
        "timestamp": context.updated_at,
    }

    # Add conditional fields if threshold not reached
    if not reached_threshold:
        result["persistent_gaps"] = context.persistent_gaps
        if diagnostic:
            result["diagnosis"] = diagnostic

    # Add errors if present
    if context.errors:
        result["errors"] = context.errors

    # Add warnings if present
    if context.warnings:
        result["warnings"] = context.warnings

    return result


def format_error_result(optimization_id: str, error: str, context: Optional[PipelineContext] = None) -> dict:
    """
    Format an error result when optimization fails.

    Args:
        optimization_id: The optimization ID
        error: Error message describing the failure
        context: Optional pipeline context for token cost information

    Returns:
        Dictionary with error result data
    """
    result = {
        "success": False,
        "optimization_id": optimization_id,
        "error": error,
    }

    # Add token cost if context provided
    if context:
        result["token_cost"] = {
            "input_tokens": context.total_input_tokens,
            "output_tokens": context.total_output_tokens,
            "total_tokens": context.total_input_tokens + context.total_output_tokens,
            "cost_cents": context.total_cost_cents
        }

    return result
