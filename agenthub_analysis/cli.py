from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from agenthub_analysis.graph import build_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgentHub LangGraph analysis prototype.")
    parser.add_argument("snapshot", help="Path to repository snapshot JSON")
    parser.add_argument("--out", default="out/analysis.json", help="Output JSON path")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    graph = build_graph()
    result = graph.invoke({
        "run_id": str(uuid4()),
        "trigger": "NEW_REPO",
        "repository_snapshot": snapshot,
        "output_path": args.out,
        "claims": [],
        "evidence_signals": [],
        "risk_signals": [],
        "quality_warnings": [],
        "quality_errors": [],
        "retry_count": 0,
    })

    print(json.dumps(result.get("persisted_analysis", result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
