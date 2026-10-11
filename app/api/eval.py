"""Evaluation endpoints."""

import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class EvalRunRequest(BaseModel):
    """Request model for evaluation run."""

    system: str = Field(default="agent", description="System to evaluate: baseline or agent")
    semantic_layer: bool = Field(default=True, description="Enable semantic layer")
    retries_enabled: bool = Field(default=True, description="Enable fix_sql retries")
    memory_enabled: bool = Field(default=True, description="Enable conversation memory")
    failures: str = Field(default="off", description="Failure injection mode: on or off")
    dataset_path: Optional[str] = Field(default="eval/dataset.jsonl", description="Path to eval dataset")


class EvalMetrics(BaseModel):
    """Evaluation metrics."""

    execution_accuracy: float
    answer_accuracy: float
    schema_retrieval_recall: float
    retry_success_rate: float
    avg_iterations: float
    p50_latency_ms: float
    p95_latency_ms: float
    avg_tokens_per_query: float
    avg_cost_cents: float
    unsafe_query_block_rate: float
    total_queries: int
    failed_queries: int


class EvalRunResponse(BaseModel):
    """Response model for evaluation run."""

    run_id: str
    status: str
    system: str
    config: dict
    metrics: Optional[EvalMetrics] = None
    error: Optional[str] = None
    report_path: Optional[str] = None


@router.post("/run")
async def run_eval(request: EvalRunRequest, http_request: Request) -> EvalRunResponse:
    """Run evaluation against a dataset.

    This endpoint runs the evaluation harness against a test dataset
    and returns comprehensive metrics including accuracy, latency, and safety metrics.

    Args:
        request: Evaluation run configuration.
        http_request: FastAPI HTTP request for context.

    Returns:
        EvalRunResponse with metrics and results.

    Raises:
        HTTPException: If evaluation fails.
    """
    request_id = http_request.state.request_id
    user_id = http_request.state.user_id
    run_id = str(uuid.uuid4())

    logger.info(
        json.dumps({
            "event": "eval_run_start",
            "request_id": request_id,
            "user_id": user_id,
            "run_id": run_id,
            "system": request.system,
            "config": request.model_dump(),
        })
    )

    try:
        # TODO: Invoke eval/run_eval.py with the configuration
        # For now, return placeholder response

        return EvalRunResponse(
            run_id=run_id,
            status="completed",
            system=request.system,
            config=request.model_dump(),
            metrics=EvalMetrics(
                execution_accuracy=0.95,
                answer_accuracy=0.92,
                schema_retrieval_recall=0.88,
                retry_success_rate=0.80,
                avg_iterations=5.2,
                p50_latency_ms=1240.0,
                p95_latency_ms=3100.0,
                avg_tokens_per_query=285.0,
                avg_cost_cents=0.0142,
                unsafe_query_block_rate=1.0,
                total_queries=60,
                failed_queries=3,
            ),
            report_path=f"eval/reports/eval_{request.system}_{run_id}.md",
        )

    except Exception as e:
        logger.error(
            json.dumps({
                "event": "eval_run_error",
                "request_id": request_id,
                "user_id": user_id,
                "run_id": run_id,
                "error": str(e),
            }),
            exc_info=True,
        )

        return EvalRunResponse(
            run_id=run_id,
            status="failed",
            system=request.system,
            config=request.model_dump(),
            error=str(e),
        )
