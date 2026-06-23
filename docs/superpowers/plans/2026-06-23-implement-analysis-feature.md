# 분석 기능 실구현 (LLM 연동) 구현 계획서

**Goal:** `finalize_analysis.py` 내부의 하드코딩된 플레이스홀더 결과 생성 구조를 실구현하여, 8대 영역별 LLM Batch Analysis와 11대 보고서 섹션 자동 작성 및 Mermaid 문법 정적 검증/재생성 흐름을 완성합니다.

**Architecture:**
- 기존 LangGraph 흐름의 복잡도를 낮추기 위해, 그래프 에지는 그대로 두고 `finalize_analysis.py` 내부의 `_build_area_findings` 및 `_build_report_sections` 함수를 고도화하여 실제 LLM을 호출하도록 변경합니다.
- `Settings.openai_api_key`가 제공되지 않은 환경에서는 기존처럼 플레이스홀더로 자동 폴백(Fallback)하도록 구현하여, API 키 없이 수행되는 로컬의 174개 pytest 테스트가 실패하지 않도록 보장합니다.

---

### Task 1: 응답 구조 스키마 정의 및 Mermaid 검증기 추가

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
- Test: `tests/test_analysis_v2_nodes.py`

- [x] **Step 1: Mermaid 문법 검증 함수 추가 및 Pydantic Structured Output 모델 정의**
- [x] **Step 2: Mermaid 검증 함수에 대한 단위 테스트 작성**
- [x] **Step 3: pytest 실행**
- [x] **Step 4: Commit**

---

### Task 2: 3대 Batch Analysis LLM 연동 구현

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`

- [x] **Step 1: `_build_area_findings` 내 3대 Batch Analysis 호출 로직 구현**
- [x] **Step 2: 기존 테스트 동작 확인**
- [x] **Step 3: Commit**

---

### Task 3: 11대 보고서 섹션 합성 및 Mermaid 재생성 루프 구현

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`

- [x] **Step 1: `_build_report_sections` 내 LLM 보고서 합성 및 Mermaid 재생성 연동**
- [x] **Step 2: 기존 테스트 동작 확인**
- [x] **Step 3: Commit**

---

### Task 4: 실전 API 연동 확인 및 최종 코드 검증

**Files:**
- Modify: `tests/test_analysis_v2_nodes.py`

- [x] **Step 1: 통합 Mock 테스트 추가**
- [x] **Step 2: 전체 검증 실행**
- [x] **Step 3: Commit**
