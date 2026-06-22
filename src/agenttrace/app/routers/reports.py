from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from agenttrace.agents.reports import TrendReport, TrendReportRequest, generate_trend_report
from agenttrace.app.dependencies import get_summary_model_factory

router = APIRouter(tags=["trend-reports"])


@router.post("/trend-reports", response_model=TrendReport)
def create_trend_report(
    request: TrendReportRequest,
    model_factory: Annotated[Callable[[], Any], Depends(get_summary_model_factory)],
) -> TrendReport:
    if not request.repositories:
        raise HTTPException(status_code=422, detail="At least one repository is required.")
    try:
        return generate_trend_report(request, model=model_factory())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trend report generation failed: {exc}") from exc
