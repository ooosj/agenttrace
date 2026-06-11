from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SummaryStatus(str, Enum):
    COMPLETED = "completed"
    LIMITED = "limited"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    FAILED = "failed"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class AgentRelevanceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class AgentRelevanceHint(BaseModel):
    level: AgentRelevanceLevel
    reason: str


class HarnessRelevanceHint(BaseModel):
    level: AgentRelevanceLevel = AgentRelevanceLevel.UNKNOWN
    reason: str = "[확인 필요] Harness relevance was not analyzed."
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class FollowupHints(BaseModel):
    readme_sections: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    directories: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class SummaryBasis(BaseModel):
    used_readme: bool = False
    used_description: bool = False
    used_topics: bool = False
    used_primary_language: bool = False
    used_file_tree: bool = False


class RepositorySummaryInput(BaseModel):
    repository_id: str
    full_name: str
    github_url: str
    description: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    primary_language: Optional[str] = None
    readme: Optional[str] = None
    file_tree: list[str] = Field(default_factory=list)


class RepositorySummary(BaseModel):
    repository_id: str
    full_name: str
    github_url: str
    one_line_summary: str
    readme_summary: str
    project_purpose: Optional[str] = None
    apparent_target_users: list[str] = Field(default_factory=list)
    readme_claims: list[str] = Field(default_factory=list)
    readme_described_features: list[str] = Field(default_factory=list)
    possible_agent_relevance: AgentRelevanceHint = Field(
        default_factory=lambda: AgentRelevanceHint(
            level=AgentRelevanceLevel.UNKNOWN,
            reason="AgentHub relevance was not assessed.",
        )
    )
    possible_harness_relevance: HarnessRelevanceHint = Field(
        default_factory=HarnessRelevanceHint
    )
    followup_hints: FollowupHints = Field(default_factory=FollowupHints)
    summary_basis: SummaryBasis = Field(default_factory=SummaryBasis)
    input_gaps: list[str] = Field(default_factory=list)
    missing_details: list[str] = Field(default_factory=list)
    summary_limitations: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    summary_status: SummaryStatus
    summary_status_reason: str
