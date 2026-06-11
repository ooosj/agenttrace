HARNESS_CAPABILITY_NAMES = [
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


HARNESS_CAPABILITY_CRITERIA = {
    "agent_loop": {
        "path_keywords": ["agent_loop", "executor", "runner", "orchestrator", "workflow", "graph"],
        "code_keywords": ["max_iterations", "next_action", "run_step", "invoke_tool"],
    },
    "tool_system": {
        "path_keywords": ["tools", "tool_registry", "function_schema", "tool_call", "mcp"],
        "code_keywords": ["register_tool", "tool_call", "function_call", "invoke_tool"],
    },
    "permission_control": {
        "path_keywords": ["permission", "policy", "approval", "allowlist", "denylist"],
        "code_keywords": ["require_approval", "allowed_commands", "policy_check"],
    },
    "sandbox_or_workspace": {
        "path_keywords": ["sandbox", "workspace", "worktree", "container"],
        "code_keywords": ["sandbox", "workspace", "cwd", "container"],
    },
    "file_system_abstraction": {
        "path_keywords": ["filesystem", "file_system", "workspace", "files"],
        "code_keywords": ["read_file", "write_file", "list_files"],
    },
    "memory_or_context_management": {
        "path_keywords": ["memory", "context", "checkpoint", "state"],
        "code_keywords": ["conversation_memory", "context_window", "checkpoint"],
    },
    "context_compression": {
        "path_keywords": ["compress", "compression", "summarize_context"],
        "code_keywords": ["compress_context", "summarize_context"],
    },
    "skill_system": {
        "path_keywords": ["skill", "SKILL.md", "skills"],
        "code_keywords": ["load_skill", "skill"],
    },
    "sub_agent": {
        "path_keywords": ["subagent", "sub_agent", "multi_agent", "worker"],
        "code_keywords": ["spawn_agent", "delegate", "subagent"],
    },
    "planning": {
        "path_keywords": ["planner", "planning", "plan"],
        "code_keywords": ["create_plan", "planner", "steps"],
    },
    "execution_monitoring": {
        "path_keywords": ["monitor", "run_log", "execution", "trace"],
        "code_keywords": ["status", "run_id", "trace", "span"],
    },
    "error_recovery": {
        "path_keywords": ["retry", "recovery", "fallback", "error"],
        "code_keywords": ["retry", "except", "fallback"],
    },
    "human_in_the_loop": {
        "path_keywords": ["approval", "review", "human", "interrupt"],
        "code_keywords": ["interrupt", "approve", "human_review"],
    },
    "observability": {
        "path_keywords": ["trace", "tracing", "observability", "langsmith", "logs"],
        "code_keywords": ["trace", "span", "logger", "langsmith"],
    },
    "evaluation": {
        "path_keywords": ["eval", "evaluation", "benchmark", "score", "tests"],
        "code_keywords": ["score", "benchmark", "assert"],
    },
    "security_boundary": {
        "path_keywords": ["security", "policy", "sandbox", "permission", "guardrail"],
        "code_keywords": ["validate_policy", "deny", "allowlist", "sandbox"],
    },
}


CORE_HIGH_RELEVANCE_CAPABILITIES = {
    "agent_loop",
    "tool_system",
    "sandbox_or_workspace",
    "permission_control",
}
