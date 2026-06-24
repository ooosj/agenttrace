from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from agenttrace.config import configure_runtime_environment
from agenttrace.logging_config import setup_logging


def main() -> None:
    configure_runtime_environment()
    setup_logging()

    from agenttrace.agents.analysis.graph import build_graph
    parser = argparse.ArgumentParser(description="Run AgentHub LangGraph analysis prototype.")
    parser.add_argument("snapshot", help="Path to repository snapshot JSON")
    parser.add_argument("--out", default="out/analysis.json", help="Output JSON path")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    graph = build_graph()
    run_id = str(uuid4())
    local_repo_dir = Path("tmp/agenttrace") / run_id
    try:
        result = graph.invoke({
            "run_id": run_id,
            "trigger": "NEW_REPO",
            "repository_snapshot": snapshot,
            "output_path": args.out,
            "evidence_signals": [],
            "risk_signals": [],
            "quality_warnings": [],
            "quality_errors": [],
            "retry_count": 0,
        })
    finally:
        import shutil
        if local_repo_dir.exists():
            shutil.rmtree(local_repo_dir, ignore_errors=True)

    print(json.dumps(result.get("persisted_analysis", result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
