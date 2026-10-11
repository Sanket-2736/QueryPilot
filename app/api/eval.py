"""Evaluation endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class EvalRunRequest(BaseModel):
    """Request model for evaluation run."""

    dataset_path: str | None = None
    num_samples: int | None = None


class EvalRunResponse(BaseModel):
    """Response model for evaluation run."""

    run_id: str
    status: str
    results: dict | None = None


@router.post("/run")
async def run_eval(request: EvalRunRequest) -> EvalRunResponse:
    """Run evaluation against a dataset.

    Args:
        request: Evaluation run configuration.

    Returns:
        EvalRunResponse with results and metrics.
    """
    # TODO: Implement evaluation runner
    raise HTTPException(status_code=501, detail="Not yet implemented")
