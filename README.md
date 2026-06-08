# AgentHub LangGraph Prototype

`Evidence-first Follow-up Analysis Workflow`를 최소 실행 가능한 MVP로 구현한 LangGraph 프로토타입입니다.

이 프로토타입은 처음부터 LLM API에 의존하지 않습니다. 먼저 규칙 기반으로 다음 흐름을 검증하고, 이후 `agenthub_analysis/nodes/analyzer.py`만 LLM structured output으로 교체할 수 있게 만들었습니다.

```text
수집 → 분석 → 근거 탐색 → 위험/팔로우업 → 품질 검사 → 저장
```

## 포함된 MVP 노드

```text
1. collect_snapshot
2. analyzer
3. evidence_scout
4. risk_and_followup_planner
5. quality_gate
6. persist_analysis
```

## 설치

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

또는 빠르게:

```bash
pip install -U langgraph
```

## 실행

```bash
python -m agenthub_analysis.cli data/sample_repo.json --out out/analysis.json
```

성공하면 `out/analysis.json`에 분석 결과가 저장됩니다.

## 출력 예시

```json
{
  "status": "COMPLETED",
  "agent_type": "MCP_SERVER",
  "claims": [...],
  "evidence_signals": [...],
  "risk_signals": [...],
  "followup_actions": [...]
}
```

## 다음에 붙일 수 있는 것

- GitHub API collector
- DB 저장용 `persist_analysis`
- LLM structured output analyzer
- 병렬 evidence worker
- human review interrupt
- DB-backed LangGraph checkpointer

## 설계 원칙

LLM이 최종 판정자가 되지 않게 하고, README claim과 구현 근거를 분리해서 보여줍니다. 근거가 약하면 `COMPLETED`가 아니라 `INSUFFICIENT_EVIDENCE` 또는 `NEEDS_HUMAN_REVIEW`로 내려갑니다.
