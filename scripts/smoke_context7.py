import json
import time
import os
from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
from agenttrace.config import get_settings
from agenttrace.logging_config import setup_logging

def main():
    setup_logging()
    
    snapshot_path = "data/context7_snapshot.json"
    if not os.path.exists(snapshot_path):
        print(f"Snapshot not found at {snapshot_path}")
        return
        
    with open(snapshot_path, "r", encoding="utf-8") as f:
        snapshot = json.load(f)
        
    # Build a minimal valid state for finalize_analysis
    # We include some dummy content chunks so that it has something to synthesize if needed
    state = {
        "readme": snapshot.get("readme", ""),
        "file_tree": snapshot.get("file_tree", []),
        "content_chunks": [],
        "synthesis": {
            "analysis_status": "completed",
            "agent_type": "Framework",
            "tech_stack_summary": {"primary_language": "Python"}
        },
        "claims": [],
        "evidence_signals": [],
        "task_results": [],
        "risk_signals": [],
        "analysis_limitations": {
            "missing_inputs": [],
            "truncated_inputs": [],
            "notes": []
        },
    }
    
    print("Starting finalize_analysis...")
    t0 = time.perf_counter()
    try:
        result = finalize_analysis(state)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        
        print("\n=== Smoke Test Complete ===")
        print(f"Total finalize_analysis duration: {duration_ms} ms")
        
        # Verify result structure
        final_result = result.get("final_result", {})
        sections = final_result.get("report_sections", [])
        print(f"Generated {len(sections)} report sections.")
        
        # Check if Mermaid diagrams were generated for sections 4 and 5
        has_sec4_mermaid = any(s.get("section_id") == 4 and s.get("mermaid_diagram") for s in sections)
        has_sec5_mermaid = any(s.get("section_id") == 5 and s.get("mermaid_diagram") for s in sections)
        
        print(f"Section 4 Mermaid generated: {has_sec4_mermaid}")
        print(f"Section 5 Mermaid generated: {has_sec5_mermaid}")
        
    except Exception as e:
        print(f"Error during execution: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
