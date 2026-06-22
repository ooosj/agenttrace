"""Weekly trend report generation."""

from agenttrace.agents.reports.schemas import (
    FeaturedRepository,
    ReportRepository,
    TrendReport,
    TrendReportRequest,
    TrendSignal,
)
from agenttrace.agents.reports.service import generate_trend_report

__all__ = [
    "FeaturedRepository",
    "ReportRepository",
    "TrendReport",
    "TrendReportRequest",
    "TrendSignal",
    "generate_trend_report",
]
