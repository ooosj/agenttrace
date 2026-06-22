from __future__ import annotations

from pydantic import BaseModel, Field


class ReportRepository(BaseModel):
    repository_id: str
    full_name: str
    description: str | None = None
    language: str | None = None
    category: str | None = None
    stars: int = 0
    star_delta: int = 0
    forks: int = 0
    fork_delta: int = 0
    open_issues: int = 0
    pushed_at: str | None = None
    analysis_summary: str | None = None


class TrendReportRequest(BaseModel):
    period_start: str
    period_end: str
    repositories: list[ReportRepository] = Field(default_factory=list)


class TrendSignal(BaseModel):
    label: str
    value: int = 0
    narrative: str


class FeaturedRepository(BaseModel):
    repository_id: str
    reason: str


class TrendReport(BaseModel):
    title: str
    executive_summary: str
    trend_signals: list[TrendSignal] = Field(default_factory=list)
    featured_repositories: list[FeaturedRepository] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: str | None = None
    model_name: str | None = None
    prompt_version: str = "weekly-trend-report@1.0.0"
