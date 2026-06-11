from typing import Literal

from pydantic import BaseModel, Field


HarnessCapabilityName = Literal[
    "agent_loop",
    "tool_system",
    "permission_control",
    "sandbox_or_workspace",
    "file_system_abstraction",
    "memory_or_context_management",
    "context_compression",
    "skill_system",
    "sub_agent",
    "planning",
    "execution_monitoring",
    "error_recovery",
    "human_in_the_loop",
    "observability",
    "evaluation",
    "security_boundary",
]


class HarnessEvidence(BaseModel):
    type: Literal["readme", "file_path", "source_code", "config", "test", "docs"]
    location: str
    summary: str
    supports: list[HarnessCapabilityName] = Field(default_factory=list)


class HarnessNegativeEvidence(BaseModel):
    type: Literal["file_path", "source_code", "docs", "test"]
    location: str = ""
    summary: str


class HarnessCapability(BaseModel):
    present: bool = False
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: list[str] = Field(default_factory=list)


class HarnessRelevance(BaseModel):
    level: Literal["high", "medium", "low", "none"] = "none"
    reason: str
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: list[HarnessEvidence] = Field(default_factory=list)
    negative_evidence: list[HarnessNegativeEvidence] = Field(default_factory=list)
