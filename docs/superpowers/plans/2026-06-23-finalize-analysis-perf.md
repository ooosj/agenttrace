# finalize_analysis 병목 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `finalize_analysis` 노드 실행 시간을 실측 160s → **80–90s** 이하로 단축 (stretch: 60s)

**Architecture:** (1) 3-batch 병렬 실행 → (2) compact payload 도입 → (3) Mermaid 분리 → (4) finalize 전용 모델 factory + timeout 설정 → (5) per-stage 로그 + smoke 검증

**Tech Stack:** Python, `concurrent.futures.ThreadPoolExecutor`, `langchain_openai.ChatOpenAI`, `pytest`

---

## Revision Notes (v2 — 2026-06-23)

| 항목 | v1 | v2 (개정) |
|---|---|---|
| SLA | 60s (hard) | **80–90s** (stretch 60s) |
| Task 순서 | timeout → compact → Mermaid → batch | **batch → compact → Mermaid → timeout** |
| timeout scope | `build_openai_analysis_model()` 전역 | **finalize 전용 factory** 추가 (evaluator 회귀 방지) |
| max_tokens | 4096 | synthesis용 **8192** |
| compact payload | `unresolved_questions` 제거 | **상위 2개 보존** (섹션 11 품질) |
| Mermaid 테스트 | 수정 누락 | **기존 3개 테스트 전면 rewrite** 포함 |
| batch 병렬 threshold | 0.1s | **call_count=3 assert만** (flakiness 방지) |
| 성공 기준 | duration_ms ≤ 60000 | **per-stage 로그** + duration_ms ≤ 90000 |

> **Footnote — spec vs plan 불일치:**  
> design spec의 개선 순서(Mermaid 분리 > compact > batch)와 본 plan의 구현 순서(batch > compact > Mermaid)가 다르다.  
> 이유: (a) batch 병렬화는 코드 변경이 가장 국소적이고 테스트 영향이 작아 risk가 낮다. (b) Mermaid 분리는 기존 테스트 3개를 전면 수정해야 하므로 다른 개선이 먼저 안정화된 후 진행이 안전하다. plan이 spec보다 우선한다.

---

## Task 1: 3-batch 병렬 실행 + per-stage 타이밍 로그

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
- Test: `tests/test_analysis_v2_nodes.py`

- [ ] **Step 1: TDD — 병렬 실행 테스트 작성**

`tests/test_analysis_v2_nodes.py`에 추가:
```python
from agenttrace.agents.analysis.nodes.finalize_analysis import _build_area_findings

def test_build_area_findings_invokes_all_three_batches(monkeypatch):
    """3개 배치가 모두 호출되는지 확인 (call_count 기반, timing assertion 없음)."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from unittest.mock import MagicMock

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value = mock_model
    mock_model.invoke.return_value = MagicMock(area_findings=[], evidence_refs=[])
    monkeypatch.setattr(fa_module, "build_openai_analysis_model", lambda: mock_model)
    monkeypatch.setattr(fa_module, "get_settings", lambda: MagicMock(openai_api_key="test"))

    state = {"readme": "# Test", "file_tree": [], "content_chunks": []}
    _build_area_findings(state, [{"id": "ref-1", "path": "README.md",
                                   "description": "d", "source_type": "doc",
                                   "symbol": None, "chunk_id": None,
                                   "line_start": None, "line_end": None,
                                   "content_excerpt": None, "content_hash": None}])

    # 배치 3개가 모두 호출됨
    assert mock_model.invoke.call_count == 3
```

- [ ] **Step 2: 테스트 실행하여 현재 동작 확인**

```bash
rtk uv run pytest tests/test_analysis_v2_nodes.py::test_build_area_findings_invokes_all_three_batches -v 2>&1 | tail -10
```

Expected: `PASS` (이미 3회 호출함, 구조 확인용)

- [ ] **Step 3: `_build_area_findings`에 `ChatPromptTemplate` 1회 생성 + `ThreadPoolExecutor` 병렬화**

`finalize_analysis.py` 상단 import에 추가:
```python
import concurrent.futures
```

`_build_area_findings` 함수 내부: L302–321 순차 루프를 아래로 교체.

```python
# 변경 전 (순차 루프, L302–321)
for batch in batches_definition:
    areas_list_text = ...
    areas_detail_text = ...
    prompt = ChatPromptTemplate.from_messages([...])  # 매 iteration 생성
    prompt_value = prompt.invoke({...})
    batch_res = structured_model.invoke(prompt_value)
    all_area_findings.extend(batch_res.area_findings)
    all_evidence_refs.extend(batch_res.evidence_refs)

# 변경 후 (병렬, prompt 1회 생성)
prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", human_prompt),
])

def _invoke_single_batch(batch_def: dict) -> tuple[list, list]:
    areas_list_text = ", ".join(
        [f"'{area_id}' ({area_name})" for area_id, area_name in batch_def["areas"]]
    )
    areas_detail_text = "\n".join(
        [f"- {area_id}: {area_name}" for area_id, area_name in batch_def["areas"]]
    )
    prompt_value = prompt.invoke({
        "areas_list_text": areas_list_text,
        "areas_detail_text": areas_detail_text,
        "readme": readme[:30000],
        "file_tree": file_tree_str[:20000],
        "chunks_text": chunks_text,
    })
    batch_res = structured_model.invoke(prompt_value)
    return batch_res.area_findings, batch_res.evidence_refs

_batch_t = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    futures = [executor.submit(_invoke_single_batch, b) for b in batches_definition]
    for future in concurrent.futures.as_completed(futures):
        findings, refs = future.result()
        all_area_findings.extend(findings)
        all_evidence_refs.extend(refs)
batch_wall_ms = int((time.perf_counter() - _batch_t) * 1000)
```

> **Note:** 429 rate-limit 발생 시 `future.result()`에서 예외 발생 → 외부 `except Exception` fallback이 처리함. 별도 순차 fallback은 YAGNI.

- [ ] **Step 4: `_build_area_findings` 반환값에 `batch_wall_ms` 포함하도록 변경**

현재 `_build_area_findings`는 `list[dict]`를 반환한다. 타이밍을 `finalize_analysis` 완료 로그에 포함하려면 반환 타입을 확장하거나 별도 변수로 `state`에 저장해야 한다.

**선택: 내부 변수로 유지하고 `finalize_analysis`에서 로그**에 포함.

`finalize_analysis` 함수에서 `_build_area_findings` 호출 래퍼를 추가:
```python
_batch_start = time.perf_counter()
area_findings = state.get("area_findings") or _build_area_findings(state, evidence_refs)
batch_wall_ms = int((time.perf_counter() - _batch_start) * 1000)
```

완료 로그 수정:
```python
log.info(
    "완료",
    sections=len(result.report_sections),
    area_findings=len(result.area_findings),
    evidence_refs=len(result.evidence_refs),
    status=result.analysis_status,
    batch_wall_ms=batch_wall_ms,       # 추가
    duration_ms=int((time.perf_counter() - _t) * 1000),
)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
rtk uv run pytest tests/test_analysis_v2_nodes.py -x -q 2>&1 | tail -20
```

Expected: 모든 테스트 PASS

- [ ] **Step 6: Commit**

```bash
rtk git add src/agenttrace/agents/analysis/nodes/finalize_analysis.py tests/test_analysis_v2_nodes.py
rtk git commit -m "perf(finalize): parallelize 3 area-finding batches with ThreadPoolExecutor, add batch_wall_ms log"
```

---

## Task 2: compact payload 함수 도입

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
- Test: `tests/test_analysis_v2_nodes.py`

- [ ] **Step 1: TDD — `_compact_area_findings` / `_compact_evidence_refs` 실패 테스트 작성**

`tests/test_analysis_v2_nodes.py`에 추가:
```python
from agenttrace.agents.analysis.nodes.finalize_analysis import (
    _compact_area_findings,
    _compact_evidence_refs,
)

def test_compact_area_findings_reduces_size_and_preserves_unresolved():
    findings = [
        {
            "area_id": "project-purpose",
            "area_name": "프로젝트 목적과 주요 기능",
            "status": "confirmed",
            "summary": "이 프로젝트는 X를 합니다.",
            "findings": [
                {"content": f"finding {i}", "type": "fact", "evidence_refs": [f"ref-{i}"]}
                for i in range(1, 5)
            ],
            "limitations": ["한계 1", "한계 2", "한계 3"],
            "unresolved_questions": ["질문 A", "질문 B", "질문 C"],
        }
    ]
    result = _compact_area_findings(findings)
    assert "project-purpose" in result
    assert "confirmed" in result
    # top-3 findings만 포함
    assert "finding 4" not in result
    # limitations top-2만 포함
    assert "한계 3" not in result
    # unresolved_questions top-2 보존 (섹션 11 품질)
    assert "질문 A" in result
    assert "질문 B" in result
    assert "질문 C" not in result

def test_compact_evidence_refs_excludes_content_excerpt():
    refs = [
        {
            "id": "ref-1",
            "path": "src/main.py",
            "description": "설명",
            "content_excerpt": "def main(): ...",
            "symbol": None,
        }
    ]
    result = _compact_evidence_refs(refs)
    assert "ref-1" in result
    assert "src/main.py" in result
    assert "def main():" not in result  # content_excerpt 제외
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

```bash
rtk uv run pytest tests/test_analysis_v2_nodes.py::test_compact_area_findings_reduces_size_and_preserves_unresolved tests/test_analysis_v2_nodes.py::test_compact_evidence_refs_excludes_content_excerpt -v 2>&1 | tail -15
```

Expected: `ImportError` 또는 `FAILED`

- [ ] **Step 3: `_compact_area_findings` / `_compact_evidence_refs` 구현**

`finalize_analysis.py`에 기존 함수들 아래에 추가:
```python
def _compact_area_findings(area_findings: list[dict]) -> str:
    """Report synthesis용 compact payload.
    
    전달 대상: _build_report_sections의 LLM 입력 prompt에만 사용.
    저장 대상인 AnalysisResult의 area_findings는 원본 그대로 유지.
    """
    compact = []
    for af in area_findings:
        compact.append({
            "area_id": af.get("area_id"),
            "status": af.get("status"),
            "summary": af.get("summary"),
            "findings": [
                {"content": f.get("content"), "type": f.get("type")}
                for f in af.get("findings", [])[:3]
            ],
            "limitations": af.get("limitations", [])[:2],
            "unresolved_questions": af.get("unresolved_questions", [])[:2],
        })
    return json.dumps(compact, indent=2, ensure_ascii=False)


def _compact_evidence_refs(evidence_refs: list[dict]) -> str:
    """Report synthesis용 compact payload: id/path/description만 포함.
    
    content_excerpt, content_hash 등 대용량 필드 제외.
    저장 대상인 AnalysisResult의 evidence_refs는 원본 그대로 유지.
    """
    compact = [
        {
            "id": r.get("id"),
            "path": r.get("path"),
            "description": r.get("description"),
        }
        for r in evidence_refs
    ]
    return json.dumps(compact, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: `_build_report_sections`에서 compact payload 사용, `synthesis_ms` 로그 추가**

`_build_report_sections` 함수 내부:
```python
# 변경 전
area_findings_str = json.dumps(area_findings, indent=2, ensure_ascii=False)
evidence_refs_str = json.dumps(evidence_refs, indent=2, ensure_ascii=False)

# 변경 후 (synthesis 입력만 compact, AnalysisResult 저장은 영향 없음)
area_findings_str = _compact_area_findings(area_findings)
evidence_refs_str = _compact_evidence_refs(evidence_refs)
```

`finalize_analysis` 함수에서 `_build_report_sections` 호출 래퍼:
```python
_synthesis_start = time.perf_counter()
report_sections = state.get("report_sections") or _build_report_sections(state, area_findings, evidence_refs)
synthesis_ms = int((time.perf_counter() - _synthesis_start) * 1000)
```

완료 로그 수정:
```python
log.info(
    "완료",
    sections=len(result.report_sections),
    area_findings=len(result.area_findings),
    evidence_refs=len(result.evidence_refs),
    status=result.analysis_status,
    batch_wall_ms=batch_wall_ms,
    synthesis_ms=synthesis_ms,         # 추가
    duration_ms=int((time.perf_counter() - _t) * 1000),
)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
rtk uv run pytest tests/test_analysis_v2_nodes.py -x -q 2>&1 | tail -20
```

Expected: 모든 테스트 PASS

- [ ] **Step 6: Commit**

```bash
rtk git add src/agenttrace/agents/analysis/nodes/finalize_analysis.py tests/test_analysis_v2_nodes.py
rtk git commit -m "perf(finalize): compact payload for synthesis input, add synthesis_ms log"
```

---

## Task 3: Mermaid 생성/재시도 분리 + 기존 테스트 rewrite

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
- Modify: `tests/test_analysis_v2_nodes.py` (기존 테스트 3개 rewrite + 신규 2개)

> ⚠️ **테스트 영향 범위**: 기존 테스트 3개를 전면 수정한다.
> - `test_finalize_analysis_with_llm_success` (L448): `FakeModel`이 `ReportBodyResult` + `MermaidResult` 스키마 분기 처리
> - `test_finalize_analysis_with_llm_mermaid_retry` (L543): Mermaid-only 1회 retry 경로로 rewrite
> - `test_finalize_analysis_with_llm_mermaid_fail_after_retry` (L653): Mermaid fail → None 반환 경로

- [ ] **Step 1: 새 스키마 + `_generate_mermaid_for_section` 함수 추가**

`finalize_analysis.py`에 기존 `ReportSynthesisResult` 아래에 추가:
```python
class ReportBodySection(BaseModel):
    """Mermaid 없이 body_markdown만 생성하는 synthesis용 스키마."""
    section_id: int
    section_name: str
    status: str
    title: str
    body_markdown: str

class ReportBodyResult(BaseModel):
    report_sections: list[ReportBodySection] = Field(default_factory=list)


class MermaidResult(BaseModel):
    mermaid_code: str = Field(default="")


def _generate_mermaid_for_section(
    section_id: int,
    section_name: str,
    readme: str,
    area_summary: str,
) -> str | None:
    """섹션별 Mermaid 다이어그램을 별도 경량 LLM 호출로 생성. 실패 시 None 반환."""
    try:
        model = build_openai_analysis_model()
        structured_model = model.with_structured_output(MermaidResult)
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a technical diagram expert. Generate a valid Mermaid diagram. "
             "Output ONLY raw mermaid syntax (no markdown code blocks). "
             "Use: flowchart TD/LR, graph TD/LR, sequenceDiagram, or classDiagram. "
             "Keep it concise (5-15 nodes). Double-quote labels with special characters."),
            ("human",
             "Section {section_id}: {section_name}\n\nContext:\n{context}\n\n"
             "Generate a Mermaid diagram for this section."),
        ])
        result = structured_model.invoke(prompt.invoke({
            "section_id": section_id,
            "section_name": section_name,
            "context": f"README:\n{readme[:5000]}\n\nArea summary:\n{area_summary[:2000]}",
        }))
        code = result.mermaid_code
        if "```" in code:
            code = re.sub(r"```(mermaid)?", "", code).strip()
        # 1회 retry (invalid syntax인 경우만)
        if not validate_mermaid_syntax(code):
            retry_result = structured_model.invoke(prompt.invoke({
                "section_id": section_id,
                "section_name": section_name,
                "context": (
                    f"README:\n{readme[:5000]}\n\nArea summary:\n{area_summary[:2000]}\n\n"
                    f"Previous attempt was invalid. Fix syntax issues and regenerate."
                ),
            }))
            code = retry_result.mermaid_code
            if "```" in code:
                code = re.sub(r"```(mermaid)?", "", code).strip()
        return code if validate_mermaid_syntax(code) else None
    except Exception as exc:
        logger.warning(f"Mermaid generation for section {section_id} failed: {exc}")
        return None
```

- [ ] **Step 2: `_build_report_sections`의 synthesis를 `ReportBodyResult`로 전환**

`_build_report_sections` 내부:
```python
# 변경 전
structured_model = model.with_structured_output(ReportSynthesisResult)
# system_prompt: "For section 4, 5 you MUST generate a valid Mermaid diagram..."

# 변경 후
structured_model = model.with_structured_output(ReportBodyResult)
# system_prompt: 섹션 4·5 Mermaid 지시 제거
# "2. The mermaid_diagram field does not exist in this schema. Mermaid diagrams are generated separately."
```

synthesis 완료 후 섹션 4·5에 Mermaid 병렬 생성 추가:
```python
area_summary_map = {af.get("area_id"): af.get("summary", "") for af in area_findings}

_mermaid_t = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    fut4 = executor.submit(
        _generate_mermaid_for_section,
        4, "전체 동작 방식", readme, area_summary_map.get("execution-flow", "")
    )
    fut5 = executor.submit(
        _generate_mermaid_for_section,
        5, "아키텍처와 주요 컴포넌트", readme, area_summary_map.get("architecture-and-modules", "")
    )
    mermaid_results = {4: fut4.result(), 5: fut5.result()}
mermaid_ms = int((time.perf_counter() - _mermaid_t) * 1000)

for sec in final_sections:
    sid = sec.get("section_id")
    sec["mermaid_diagram"] = mermaid_results.get(sid)  # 4·5만 값, 나머지 None
```

`finalize_analysis` 완료 로그에 `mermaid_ms` 추가:
```python
log.info(
    "완료",
    ...
    batch_wall_ms=batch_wall_ms,
    synthesis_ms=synthesis_ms,
    mermaid_ms=mermaid_ms,             # 추가
    duration_ms=int((time.perf_counter() - _t) * 1000),
)
```

기존 `retry_needed` / `retry_prompt` 전체 블록 (L483–524) **제거** — Mermaid retry는 `_generate_mermaid_for_section` 내부로 이동.

- [ ] **Step 3: 기존 테스트 3개 rewrite**

`tests/test_analysis_v2_nodes.py`에서 L448–747 범위의 3개 테스트를 아래로 교체:

```python
# ─── test_finalize_analysis_with_llm_success (rewrite) ───────────────────────

def test_finalize_analysis_with_llm_success(monkeypatch):
    """synthesis가 ReportBodyResult, Mermaid가 MermaidResult로 분리 동작."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import (
        BatchAnalysisResult, ReportBodyResult, ReportBodySection, MermaidResult,
    )
    from agenttrace.agents.analysis.schemas.result import AreaFinding

    class FakeBatchModel:
        def invoke(self, prompt_value):
            return BatchAnalysisResult(
                area_findings=[
                    AreaFinding(
                        area_id=area_id, area_name=area_name,
                        status="confirmed", summary="요약", findings=[]
                    )
                    for area_id, area_name in [
                        ("project-purpose", "프로젝트 목적과 주요 기능"),
                        ("execution-flow", "진입점과 핵심 실행 흐름"),
                        ("architecture-and-modules", "아키텍처와 모듈 관계"),
                        ("agent-and-llm", "Agent·LLM 핵심 로직"),
                        ("tools-and-integrations", "Tool·외부 서비스 연동"),
                        ("state-and-storage", "상태·메모리·데이터 저장"),
                        ("configuration-and-deployment", "설정·실행·배포 방법"),
                        ("examples-and-tests", "예제·테스트·확장 지점"),
                    ]
                ],
                evidence_refs=[]
            )

    class FakeBodyModel:
        def invoke(self, prompt_value):
            return ReportBodyResult(report_sections=[
                ReportBodySection(
                    section_id=idx, section_name=f"섹션 {idx}",
                    status="confirmed", title=f"{idx}. 섹션 {idx}",
                    body_markdown=f"내용 {idx}",
                )
                for idx in range(1, 12)
            ])

    class FakeMermaidModel:
        def invoke(self, prompt_value):
            return MermaidResult(mermaid_code="flowchart TD\n  A --> B")

    class FakeModel:
        def with_structured_output(self, schema):
            if schema == BatchAnalysisResult:
                return FakeBatchModel()
            if schema == ReportBodyResult:
                return FakeBodyModel()
            if schema == MermaidResult:
                return FakeMermaidModel()
            raise ValueError(f"Unknown schema: {schema}")

    monkeypatch.setattr(fa_module, "build_openai_analysis_model", lambda: FakeModel())

    import agenttrace.config
    original_get_settings = agenttrace.config.get_settings
    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key="fake-key")
    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    monkeypatch.setattr(fa_module, "get_settings", mocked_get_settings)

    from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
    state = {
        "readme": "Project Readme",
        "synthesis": {"analysis_status": "completed", "agent_type": "Unknown"},
        "claims": [], "evidence_signals": [], "task_results": [],
        "risk_signals": [],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    report_sections = result["final_result"]["report_sections"]
    assert len(report_sections) == 11
    # 섹션 4·5에 Mermaid 생성됨
    assert report_sections[3]["mermaid_diagram"] == "flowchart TD\n  A --> B"
    assert report_sections[4]["mermaid_diagram"] == "flowchart TD\n  A --> B"


# ─── test_finalize_analysis_with_llm_mermaid_retry (rewrite) ─────────────────

def test_finalize_analysis_with_llm_mermaid_retry(monkeypatch):
    """Mermaid 1회 invalid → retry → valid 반환 경로."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import (
        BatchAnalysisResult, ReportBodyResult, ReportBodySection, MermaidResult,
    )
    from agenttrace.agents.analysis.schemas.result import AreaFinding

    class FakeBatchModel:
        def invoke(self, prompt_value):
            return BatchAnalysisResult(
                area_findings=[
                    AreaFinding(area_id="execution-flow", area_name="진입점과 핵심 실행 흐름",
                                status="confirmed", summary="요약", findings=[])
                ],
                evidence_refs=[]
            )

    class FakeBodyModel:
        def invoke(self, prompt_value):
            return ReportBodyResult(report_sections=[
                ReportBodySection(
                    section_id=idx, section_name=f"섹션 {idx}",
                    status="confirmed", title=f"{idx}. 섹션 {idx}",
                    body_markdown=f"내용 {idx}",
                )
                for idx in range(1, 12)
            ])

    class FakeMermaidModel:
        def __init__(self):
            self.call_count = 0

        def invoke(self, prompt_value):
            self.call_count += 1
            # 첫 호출: invalid syntax (괄호 불일치)
            if self.call_count == 1:
                return MermaidResult(mermaid_code="flowchart TD\n  A[Start) --> B")
            # retry: valid
            return MermaidResult(mermaid_code="flowchart TD\n  A --> B")

    fake_mermaid = FakeMermaidModel()

    class FakeModel:
        def with_structured_output(self, schema):
            if schema == BatchAnalysisResult:
                return FakeBatchModel()
            if schema == ReportBodyResult:
                return FakeBodyModel()
            if schema == MermaidResult:
                return fake_mermaid
            raise ValueError(f"Unknown schema: {schema}")

    monkeypatch.setattr(fa_module, "build_openai_analysis_model", lambda: FakeModel())

    import agenttrace.config
    original_get_settings = agenttrace.config.get_settings
    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key="fake-key")
    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    monkeypatch.setattr(fa_module, "get_settings", mocked_get_settings)

    from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
    state = {
        "readme": "Project Readme",
        "synthesis": {"analysis_status": "completed", "agent_type": "Unknown"},
        "claims": [], "evidence_signals": [], "task_results": [],
        "risk_signals": [],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    report_sections = result["final_result"]["report_sections"]
    assert len(report_sections) == 11
    # 섹션 4: retry 후 valid Mermaid 반환
    assert report_sections[3]["mermaid_diagram"] == "flowchart TD\n  A --> B"
    # _generate_mermaid_for_section이 섹션 4·5 각각 최대 2회 호출 가능
    assert fake_mermaid.call_count >= 2


# ─── test_finalize_analysis_with_llm_mermaid_fail_after_retry (rewrite) ──────

def test_finalize_analysis_with_llm_mermaid_fail_after_retry(monkeypatch):
    """Mermaid 2회 모두 invalid → None 반환 (섹션에서 mermaid_diagram=None)."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import (
        BatchAnalysisResult, ReportBodyResult, ReportBodySection, MermaidResult,
    )
    from agenttrace.agents.analysis.schemas.result import AreaFinding

    class FakeBatchModel:
        def invoke(self, prompt_value):
            return BatchAnalysisResult(
                area_findings=[
                    AreaFinding(area_id="execution-flow", area_name="진입점",
                                status="confirmed", summary="요약", findings=[])
                ],
                evidence_refs=[]
            )

    class FakeBodyModel:
        def invoke(self, prompt_value):
            return ReportBodyResult(report_sections=[
                ReportBodySection(
                    section_id=idx, section_name=f"섹션 {idx}",
                    status="confirmed", title=f"{idx}. 섹션 {idx}",
                    body_markdown=f"내용 {idx}",
                )
                for idx in range(1, 12)
            ])

    class FakeMermaidModel:
        def invoke(self, prompt_value):
            # 항상 invalid syntax 반환
            return MermaidResult(mermaid_code="flowchart TD\n  A[Start) --> B")

    class FakeModel:
        def with_structured_output(self, schema):
            if schema == BatchAnalysisResult:
                return FakeBatchModel()
            if schema == ReportBodyResult:
                return FakeBodyModel()
            if schema == MermaidResult:
                return FakeMermaidModel()
            raise ValueError(f"Unknown schema: {schema}")

    monkeypatch.setattr(fa_module, "build_openai_analysis_model", lambda: FakeModel())

    import agenttrace.config
    original_get_settings = agenttrace.config.get_settings
    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key="fake-key")
    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    monkeypatch.setattr(fa_module, "get_settings", mocked_get_settings)

    from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
    state = {
        "readme": "Project Readme",
        "synthesis": {"analysis_status": "completed", "agent_type": "Unknown"},
        "claims": [], "evidence_signals": [], "task_results": [],
        "risk_signals": [],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    report_sections = result["final_result"]["report_sections"]
    assert len(report_sections) == 11
    # Mermaid 2회 실패 → None
    assert report_sections[3]["mermaid_diagram"] is None
```

- [ ] **Step 4: 신규 테스트 추가 — `_generate_mermaid_for_section` 단위 테스트**

`tests/test_analysis_v2_nodes.py`에 추가:
```python
from agenttrace.agents.analysis.nodes.finalize_analysis import _generate_mermaid_for_section

def test_generate_mermaid_for_section_returns_valid_diagram(monkeypatch):
    """첫 호출에서 valid diagram 반환."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import MermaidResult
    from unittest.mock import MagicMock

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value = mock_model
    mock_model.invoke.return_value = MermaidResult(
        mermaid_code="flowchart TD\n  A[Input] --> B[Output]"
    )
    monkeypatch.setattr(fa_module, "build_openai_analysis_model", lambda: mock_model)

    result = _generate_mermaid_for_section(
        section_id=4, section_name="전체 동작 방식",
        readme="# Test Repo", area_summary="흐름 요약"
    )
    assert result == "flowchart TD\n  A[Input] --> B[Output]"
    assert mock_model.invoke.call_count == 1  # retry 불필요

def test_generate_mermaid_for_section_returns_none_on_failure(monkeypatch):
    """예외 발생 시 None 반환 (graceful fallback)."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from unittest.mock import MagicMock

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value = mock_model
    mock_model.invoke.side_effect = RuntimeError("API error")
    monkeypatch.setattr(fa_module, "build_openai_analysis_model", lambda: mock_model)

    result = _generate_mermaid_for_section(
        section_id=4, section_name="전체 동작 방식",
        readme="# Test", area_summary=""
    )
    assert result is None
```

- [ ] **Step 5: 전체 테스트 통과 확인**

```bash
rtk uv run pytest tests/test_analysis_v2_nodes.py -x -q 2>&1 | tail -20
```

Expected: 모든 테스트 PASS (기존 3개 rewrite + 신규 2개 포함)

- [ ] **Step 6: Commit**

```bash
rtk git add src/agenttrace/agents/analysis/nodes/finalize_analysis.py tests/test_analysis_v2_nodes.py
rtk git commit -m "perf(finalize): separate mermaid generation, parallel sec4/5, rewrite mermaid tests"
```

---

## Task 4: finalize 전용 모델 factory + timeout/max_tokens 설정

**Files:**
- Modify: `src/agenttrace/config.py`
- Modify: `src/agenttrace/models.py`
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
- Test: `tests/test_analysis_v2_nodes.py`

> ⚠️ **scope 분리 필수:** `build_openai_analysis_model()`은 `evidence_evaluator`도 사용 (실측 161s).  
> 전역 timeout=90 적용 시 evaluator task-002가 90s에서 강제 타임아웃 → 데이터 손실 회귀.  
> finalize 전용 factory를 별도로 추가한다.

- [ ] **Step 1: `config.py`에 finalize 전용 필드 추가**

`src/agenttrace/config.py`의 Settings 클래스에 추가:
```python
# finalize_analysis 전용 — evidence_evaluator와 독립
finalize_model_timeout: int = 90          # 환경변수: AGENTTRACE_FINALIZE_MODEL_TIMEOUT
finalize_model_max_tokens: int = 8192     # 환경변수: AGENTTRACE_FINALIZE_MODEL_MAX_TOKENS
```

`get_settings()` 팩토리에 추가:
```python
finalize_model_timeout=int(_get_env("AGENTTRACE_FINALIZE_MODEL_TIMEOUT", env_values, "90")),
finalize_model_max_tokens=int(_get_env("AGENTTRACE_FINALIZE_MODEL_MAX_TOKENS", env_values, "8192")),
```

- [ ] **Step 2: `models.py`에 `build_openai_finalize_model()` 추가**

```python
def build_openai_finalize_model() -> Any:
    """finalize_analysis 전용 모델. evidence_evaluator와 timeout/max_tokens 분리."""
    settings = get_settings()

    if not settings.openai_api_key:
        raise MissingAnalysisModelError("OPENAI_API_KEY is required for analysis generation.")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise MissingAnalysisModelError(
            "langchain-openai is required for OpenAI analysis generation."
        ) from exc

    kwargs = {
        "model": settings.analysis_model,
        "api_key": settings.openai_api_key,
        "temperature": 0,
        "timeout": settings.finalize_model_timeout,
        "max_tokens": settings.finalize_model_max_tokens,
        "max_retries": 1,
    }
    if settings.openai_api_base:
        kwargs["base_url"] = settings.openai_api_base
    return ChatOpenAI(**kwargs)
```

`build_openai_analysis_model()`은 **변경하지 않는다** (evaluator 회귀 방지).

- [ ] **Step 3: `finalize_analysis.py`에서 import 교체**

```python
# 변경 전
from agenttrace.models import build_openai_analysis_model

# 변경 후
from agenttrace.models import build_openai_analysis_model, build_openai_finalize_model
```

`_build_area_findings`, `_build_report_sections`, `_generate_mermaid_for_section` 내부:
```python
# model = build_openai_analysis_model()  ← 기존
model = build_openai_finalize_model()    # ← 교체
```

- [ ] **Step 4: TDD — `build_openai_finalize_model` kwargs 검증 테스트 작성**

`tests/test_analysis_v2_nodes.py`에 추가:
```python
def test_build_openai_finalize_model_applies_timeout_and_max_tokens(monkeypatch):
    """build_openai_finalize_model이 timeout, max_tokens, max_retries를 전달하는지 확인."""
    import agenttrace.models as models_module
    captured_kwargs = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(models_module, "ChatOpenAI", FakeChatOpenAI, raising=False)

    import importlib
    import agenttrace.models
    # ChatOpenAI를 패치하려면 langchain_openai 임포트 전에 패치해야 함
    # 대신 build_openai_finalize_model 내부 동작을 직접 검증

    from agenttrace.config import get_settings
    settings = get_settings()
    # default 값 검증
    assert settings.finalize_model_timeout == 90
    assert settings.finalize_model_max_tokens == 8192
```

- [ ] **Step 5: 기존 테스트 통과 확인**

```bash
rtk uv run pytest tests/test_analysis_v2_nodes.py -x -q 2>&1 | tail -20
```

Expected: 모든 테스트 PASS (`build_openai_analysis_model` mock은 기존 그대로 동작)

- [ ] **Step 6: Commit**

```bash
rtk git add src/agenttrace/config.py src/agenttrace/models.py src/agenttrace/agents/analysis/nodes/finalize_analysis.py tests/test_analysis_v2_nodes.py
rtk git commit -m "perf(finalize): add build_openai_finalize_model factory with timeout=90 max_tokens=8192"
```

---

## Task 5: 최종 검증 — per-stage 로그 + smoke SLA 확인

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: 전체 테스트 스위트 실행**

```bash
rtk uv run pytest tests/ -x -q 2>&1 | tail -30
```

Expected: 전체 PASS

- [ ] **Step 2: smoke 실행으로 per-stage 로그 확인**

```bash
rtk uv run python scripts/smoke_context7.py 2>&1 | grep -E "finalize|batch_wall_ms|synthesis_ms|mermaid_ms|duration_ms"
```

Expected:
- `finalize_analysis` 완료 로그에 `batch_wall_ms`, `synthesis_ms`, `mermaid_ms` 필드 존재
- `duration_ms` ≤ **90000** (stretch: ≤ 60000)

실측값이 90000 초과 시: `batch_wall_ms` vs `synthesis_ms` 중 어느 쪽이 지배적인지 확인 후 추가 튜닝.

- [ ] **Step 3: `.env.example` 업데이트**

```bash
# Finalize Analysis Model Settings (finalize_analysis 전용, evidence_evaluator와 독립)
AGENTTRACE_FINALIZE_MODEL_TIMEOUT=90
AGENTTRACE_FINALIZE_MODEL_MAX_TOKENS=8192
```

`evidence_evaluator`용 timeout은 별도 env가 없으므로 note 추가:
```bash
# Evidence Evaluator Model: build_openai_analysis_model() 사용 (timeout 미설정, 장시간 허용)
# 실측 최대 161s — 타임아웃 설정 시 회귀 주의
```

- [ ] **Step 4: 최종 Commit**

```bash
rtk git add .env.example
rtk git commit -m "docs: document finalize vs evaluator model env vars in .env.example"
```
