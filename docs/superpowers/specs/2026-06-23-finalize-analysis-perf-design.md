# finalize_analysis 병목 개선 설계 명세

**작성일:** 2026-06-23  
**대상 파일:** `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`

---

## 문제 정의

`finalize_analysis`는 최대 **5회의 순차 LLM 호출**로 구성되어 145~160초 소요:

```
현재 흐름:
  batch_1 → batch_2 → batch_3        (순차, 각 ~30-40s)
  → synthesis(+Mermaid) → retry?     (1~2회, ~40-60s)
```

각 배치에 `chunks_text` 최대 100K char을 **매 요청마다 반복 전달**.

---

## 개선 목표

- Context7 smoke 실행 시간: **145s → 60s 이하**
- 기존 테스트 100% 통과 유지
- 코드 구조: 기존 함수 인터페이스 유지 (점진적 개선)

---

## 개선 항목 (우선순위 순)

### 1. Mermaid 생성/재시도 분리 (최우선)

**현재:** `_build_report_sections`가 body_markdown + Mermaid 생성 + 검증 + retry를 한 LLM 호출에서 처리  
**개선:** body_markdown만 먼저 생성하고, Mermaid는 섹션 4·5에만 별도 호출로 분리

- 변경 전: 한 번의 합성에서 11개 섹션 + 2개 Mermaid
- 변경 후: 1단계(body_markdown 11개), 2단계(mermaid 2개, 별도 경량 호출)

기대 효과: main synthesis 토큰 25% 절감, retry 빈도 감소

---

### 2. Report synthesis 입력 축소 (compact payload)

**현재:** `area_findings_str` + `evidence_refs_str` 전체 JSON 전달  
**개선:** 섹션 생성에 필요한 요약 정보만 전달하는 compact 변환 함수 추가

- `_compact_area_findings()`: area_id, status, summary, top-3 findings content만 추출
- `_compact_evidence_refs()`: id, path, description만 추출 (content_excerpt 제외)

기대 효과: synthesis 입력 토큰 40~60% 절감

---

### 3. 3-batch 병렬 실행

**현재:** Batch 1 → Batch 2 → Batch 3 순차 실행  
**개선:** `concurrent.futures.ThreadPoolExecutor`로 병렬 실행

기대 효과: 3회 순차(~90s) → 1회 병렬(~30-40s)

---

### 4. timeout / max_tokens / max_retries 설정

**현재:** `build_openai_analysis_model()`에 timeout, max_tokens 미설정  
**개선:**
- `config.py`에 `analysis_model_timeout: int = 90`, `analysis_model_max_tokens: int = 4096` 추가
- `models.py`의 `build_openai_analysis_model()`에 적용
- 환경변수: `AGENTTRACE_ANALYSIS_MODEL_TIMEOUT`, `AGENTTRACE_ANALYSIS_MODEL_MAX_TOKENS`

기대 효과: 느린 응답에 의한 무한 대기 방지, 실패 시 빠른 fallback

---

## 변경 대상 파일

| 파일 | 변경 내용 |
|---|---|
| `src/agenttrace/agents/analysis/nodes/finalize_analysis.py` | batch 병렬화, Mermaid 분리, compact payload 함수 추가 |
| `src/agenttrace/models.py` | timeout, max_tokens, max_retries 설정 |
| `src/agenttrace/config.py` | `analysis_model_timeout`, `analysis_model_max_tokens` 필드 추가 |
| `tests/test_analysis_v2_nodes.py` | 병렬 실행 및 Mermaid 분리 관련 테스트 추가 |

---

## 변경하지 않는 것

- `finalize_analysis(state)` 함수 시그니처
- `AnalysisResult` 출력 스키마
- 기존 mock/fallback 경로
- `_build_evidence_refs` (이미 최적화됨)

---

## 성공 기준

- `pytest tests/test_analysis_v2_nodes.py` 100% 통과
- Context7 smoke: `finalize_analysis` 노드 duration_ms 로그 60,000ms 이하
- `AGENTTRACE_ANALYSIS_MODEL_TIMEOUT` 환경변수로 override 가능
