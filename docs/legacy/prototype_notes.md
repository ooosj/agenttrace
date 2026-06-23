# Prototype Notes

## 왜 6개 노드인가?

업로드된 설계의 MVP 권장안에 맞춰 처음에는 다음 6개 노드만 사용합니다.

```text
collect_snapshot → analyzer → evidence_scout → risk_and_followup_planner → quality_gate → persist_analysis
```

## 확장 방향

현재 `analyzer`는 다음 세 가지를 한 번에 처리합니다.

- 관련성 분류
- claim 추출
- agent_type 분류

정확도 문제가 보이면 아래처럼 분리합니다.

```text
classify_relevance → extract_claims → plan_evidence_tasks → evidence_scout workers
```

## LLM으로 교체할 위치

- `nodes/analyzer.py`의 `_detect_agent_type`
- `nodes/analyzer.py`의 `_extract_claims`
- `nodes/risk_and_followup.py`의 follow-up 생성 부분
- `nodes/quality_gate.py`의 과장 표현/스키마 평가 부분

## 운영에서 교체할 위치

- `collect_snapshot`: GitHub API / DB / cache collector
- `persist_analysis`: PostgreSQL 또는 app DB 저장
- `build_graph`: DB-backed checkpointer 추가
