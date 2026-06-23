# 8대 영역 & 11대 섹션 명세 동기화 구현 계획서

**Goal:** `src/agenttrace/agents/analysis/schemas/result.py` 및 `src/agenttrace/agents/analysis/nodes/finalize_analysis.py` 등 코드 내 정의된 8대 분석 영역 ID와 11대 보고서 섹션명을 `docs/reference/artifacts/current/AI_ANALYSIS_SPEC.md` 스펙과 일치시키고, 향후 불일치를 물리적으로 예방할 수 있는 자동화 테스트(`tests/test_spec_sync.py`)를 추가합니다.

**Architecture:**
- `schemas/result.py` 및 `services/analysis_jobs.py`에 선언된 `COMMON_ANALYSIS_AREAS` 상수를 V2 스펙 ID와 한글명으로 수정합니다.
- `nodes/finalize_analysis.py`의 `REPORT_SECTION_NAMES`를 V2 목차명으로 수정합니다.
- `tests/test_spec_sync.py` 테스트 파일을 작성하여, `AI_ANALYSIS_SPEC.md` 마크다운을 직접 파싱해 코드 내 영역 ID 및 섹션명과 항상 일치하는지 정적/동적 어서션 검증을 수행하게 만듭니다.
- 기존 단위/통합 테스트 코드에 모킹된 구형 상수 데이터를 업데이트하여 테스트 그린 상태를 보장합니다.

**Tech Stack:** Python 3.12, Pytest, Pydantic, Regular Expressions

---

### Task 1: 스펙 동기화 검증 자동화 테스트 추가 (TDD 준비)

**Files:**
- Create: `tests/test_spec_sync.py`

- [x] **Step 1: 정적 동기화 검증 테스트 파일 생성 (Failing Test)**
- [x] **Step 2: 테스트를 실행하여 실패하는지 확인**

---

### Task 2: 스키마 및 서비스 내 8대 영역 ID 동기화

**Files:**
- Modify: `src/agenttrace/agents/analysis/schemas/result.py`
- Modify: `src/agenttrace/services/analysis_jobs.py`

- [x] **Step 1: result.py 스키마 내 영역 상수 업데이트**
- [x] **Step 2: analysis_jobs.py 내 영역 상수 업데이트**
- [x] **Step 3: 영역 동기화 검증 테스트 실행**

---

### Task 3: 11대 보고서 섹션 상수 동기화

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`

- [x] **Step 1: finalize_analysis.py 내 섹션 상수 업데이트**
- [x] **Step 2: 동기화 정적 테스트 전체 실행**

---

### Task 4: 기존 단위/통합 테스트 코드 마이그레이션 및 최종 검증

**Files:**
- Modify: `tests/test_analysis_v2_schemas.py`

- [x] **Step 1: 스키마 검증 테스트의 모킹 영역 데이터 업데이트**
- [x] **Step 2: 전체 테스트 실행 및 검증 완료**
