AGENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "MCP_SERVER": [
        "mcp server", "model context protocol", "tools", "resources", "prompts",
        "stdio", "sse", "server.py", "mcp.json",
    ],
    "MCP_CLIENT": ["mcp client", "connect to mcp", "mcp host"],
    "SKILL": [
        "skills/", "skill.md", "skill", "agentic skills", "reusable skills",
        "reusable instruction", "capability", "plugin", "plugin.json",
        "workflow instructions",
    ],
    "EVAL_HARNESS": ["eval", "benchmark", "dataset", "scoring", "harness"],
    "TOOL_USE": ["tool registry", "function schema", "tool call", "executor"],
    "AGENT_FRAMEWORK": [
        "agent framework", "coding agents", "methodology", "workflow", "plan",
        "review", "verify", "planner", "memory", "multi-agent", "orchestration",
    ],
    "OBSERVABILITY": ["trace", "monitoring", "observability", "telemetry"],
    "GUARDRAIL": ["guardrail", "policy", "safety", "moderation"],
}

EVIDENCE_PATH_HINTS: dict[str, list[str]] = {
    "MCP_SERVER": ["mcp", "server", "tools", "resources", "prompts", "examples"],
    "MCP_CLIENT": ["mcp", "client", "host", "examples"],
    "SKILL": ["SKILL.md", "skill", "manifest"],
    "EVAL_HARNESS": ["eval", "benchmark", "dataset", "score", "tests"],
    "TOOL_USE": ["tools", "registry", "schema", "executor"],
    "AGENT_FRAMEWORK": ["agent", "planner", "memory", "router", "workflow", "graph"],
    "OBSERVABILITY": ["trace", "log", "monitor", "telemetry"],
    "GUARDRAIL": ["guardrail", "policy", "safety", "moderation"],
}

RISKY_README_WORDS = [
    "production-ready",
    "secure by default",
    "fully autonomous",
    "guaranteed",
    "perfect",
    "100%",
]

BANNED_ASSERTIVE_WORDS = [
    "검증 완료",
    "완벽히 구현",
    "안전함",
    "무조건",
    "보장",
]
