# Pipeline Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 파이프라인의 실행 흐름과 결과를 로그로 추적 가능하게 만든다.

**Architecture:** 중앙 로깅 설정을 `src/agenttrace/logging_config.py`에 두고, API 서버/Worker 기동 시 초기화. 각 파이프라인 노드에 `logger = logging.getLogger(__name__)` + 핵심 진입·종료 로그 추가. 외부 라이브러리 로그 수준 조정으로 노이즈 최소화.

**Tech Stack:** Python `logging` 표준 라이브러리, uvicorn 로그 통합

---

### Task 1: 중앙 로깅 설정 모듈 생성

**Files:**
- Create: `src/agenttrace/logging_config.py`
- Modify: `src/agenttrace/app/main.py`
- Modify: `src/agenttrace/app/worker.py`
- Create: `tests/test_logging_config.py`

- [x] **Step 1: 테스트 작성**

```python
# tests/test_logging_config.py
import logging
from agenttrace.logging_config import setup_logging

def test_setup_logging_sets_root_level():
    setup_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG

def test_setup_logging_default_info():
    setup_logging()
    assert logging.getLogger().level == logging.INFO

def test_setup_logging_idempotent():
    setup_logging()
    setup_logging()
    root = logging.getLogger()
    assert len(root.handlers) <= 2
```

Run: `rtk .venv/bin/pytest tests/test_logging_config.py -x -q`
Expected: FAIL (모듈 없음)

- [x] **Step 2: logging_config.py 구현**

```python
# src/agenttrace/logging_config.py
from __future__ import annotations
import logging
import sys

def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(numeric_level)

    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)
```

- [x] **Step 3: 테스트 확인**

Run: `rtk .venv/bin/pytest tests/test_logging_config.py -x -q`
Expected: PASS

- [x] **Step 4: main.py 연결**

`src/agenttrace/app/main.py`의 `lifespan` 함수 첫 줄에 추가:
```python
from agenttrace.logging_config import setup_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()   # ← 추가
    settings = configure_runtime_environment()
    ...
```

- [x] **Step 5: worker.py 교체**

`worker.py`의 `logging.basicConfig(...)` 제거 후:
```python
from agenttrace.logging_config import setup_logging

def main() -> None:
    setup_logging()
    logger.info("Starting AgentTrace Durable Analysis Worker...")
```

- [x] **Step 6: 커밋**

```bash
rtk git add src/agenttrace/logging_config.py src/agenttrace/app/main.py src/agenttrace/app/worker.py tests/test_logging_config.py
rtk git commit -m "feat(logging): 중앙 로깅 설정 모듈 추가"
```

---

### Task 2: 파이프라인 핵심 노드에 로깅 추가

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/collect_inputs.py`
- Modify: `src/agenttrace/agents/analysis/nodes/claim_analyzer.py`
- Modify: `src/agenttrace/agents/analysis/nodes/analysis_planner.py`
- Modify: `src/agenttrace/agents/analysis/nodes/evidence_scout.py`
- Modify: `src/agenttrace/agents/analysis/nodes/repository_synthesizer.py`
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
- Modify: `src/agenttrace/agents/analysis/nodes/quality_gate.py`
- Modify: `src/agenttrace/agents/analysis/nodes/persist_analysis.py`

**모든 노드 공통 패턴:**
```python
import logging
logger = logging.getLogger(__name__)

def node_fn(state):
    run_id = state.get("run_id", "-")
    logger.info("[node_fn] 시작 — run_id=%s", run_id)
    # 기존 로직
    logger.info("[node_fn] 완료 — <핵심 결과>")
    return result
```

- [x] **Step 1: collect_inputs.py**

진입: `logger.info("[collect_inputs] 시작 — run_id=%s", run_id)`
종료: `logger.info("[collect_inputs] 완료 — source_files=%d, mode=%s, provider=%s", len(source_files), mode, provider)`

- [x] **Step 2: claim_analyzer.py**

진입: `logger.info("[claim_analyzer] 시작 — run_id=%s", run_id)`
종료: `logger.info("[claim_analyzer] 완료 — claims=%d, agent_type=%s", len(claims), agent_type)`

- [x] **Step 3: analysis_planner.py**

진입: `logger.info("[analysis_planner] 시작 — run_id=%s", run_id)`
종료: `logger.info("[analysis_planner] 완료 — tasks=%d", len(tasks))`

- [x] **Step 4: evidence_scout.py**

진입: `logger.info("[evidence_scout] 시작 — run_id=%s, task_id=%s", run_id, task_id)`
종료: `logger.info("[evidence_scout] 완료 — signals=%d", len(signals))`

- [x] **Step 5: repository_synthesizer.py**

진입: `logger.info("[repository_synthesizer] 시작 — run_id=%s", run_id)`
종료: `logger.info("[repository_synthesizer] 완료 — status=%s, agent_type=%s", status, agent_type)`

- [x] **Step 6: finalize_analysis.py**

진입: `logger.info("[finalize_analysis] 시작 — run_id=%s", run_id)`
종료: `logger.info("[finalize_analysis] 완료 — sections=%d, area_findings=%d, evidence_refs=%d", ...)`

- [x] **Step 7: quality_gate.py, persist_analysis.py**

각 노드 진입·종료 로그, quality_gate는 `errors=%d, warnings=%d` 포함.

- [x] **Step 8: 전체 테스트**

Run: `rtk .venv/bin/pytest -x -q`
Expected: PASS

- [x] **Step 9: 커밋**

```bash
rtk git add src/agenttrace/agents/analysis/nodes/
rtk git commit -m "feat(logging): 파이프라인 노드 로깅 추가"
```

---

### Task 3: AGENTS.md 로깅 지침 추가

**Files:**
- Modify: `AGENTS.md`

- [x] **Step 1: Logging 섹션 추가**

```markdown
## Logging

- 로깅 초기화는 `setup_logging()` (`src/agenttrace/logging_config.py`) 한 곳에서만.
- 새 노드 작성 시 상단에 반드시 선언:
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```
- 노드 진입·종료 시 INFO 로그 필수:
  ```python
  logger.info("[node_name] 시작 — run_id=%s", run_id)
  logger.info("[node_name] 완료 — <핵심 결과 요약>")
  ```
- LLM 실패·fallback 시 WARNING, 예외는 ERROR 사용.
- httpx, openai, langchain, langgraph는 WARNING 이상만 (logging_config.py에서 고정).
- 로그에 API 키·소스코드 전체 내용 포함 금지.
```

- [x] **Step 2: 커밋**

```bash
rtk git add AGENTS.md
rtk git commit -m "docs: 로깅 지침 AGENTS.md 추가"
```
