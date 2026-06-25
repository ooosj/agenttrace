# AgentTrace

`Evidence-first Follow-up Analysis Workflow`를 최소 실행 가능한 MVP로 구현한 LangGraph 기반 AgentTrace 프로토타입입니다.

이 프로토타입은 처음부터 LLM API에 의존하지 않습니다. 먼저 규칙 기반으로 다음 흐름을 검증하고, 이후 `src/agenttrace/agents/analysis/nodes/analyzer.py`만 LLM structured output으로 교체할 수 있게 만들었습니다.

```text
수집 → 분석 → 근거 탐색 → 위험/팔로우업 → 품질 검사 → 저장
```

## 포함된 MVP 노드

```text
1. collect_inputs
2. extract_mentions
3. build_file_catalog
4. build_repo_map
5. analysis_precheck
6. area_explorer
7. risk_and_followup
8. finalize_analysis
9. quality_gate
10. critical_error_handler
11. persist_analysis
```

## 설치

```bash
uv sync --extra dev
```

## 실행

```bash
python -m agenttrace.agents.analysis.cli data/sample_repo.json --out out/analysis.json
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

---

## 🛠️ 운영 및 배포 가이드

### 1. 환경 변수 설정 (`.env`)
AgentTrace는 LLM 연동 및 DB 연동을 위해 다음 환경 변수를 필요로 합니다. `.env` 파일을 프로젝트 루트에 생성하고 설정하십시오.

```bash
# OpenAI API 관련 설정 (AGENTTRACE_ 프리픽스 권장)
AGENTTRACE_OPENAI_API_KEY=your-openai-api-key
AGENTTRACE_OPENAI_API_BASE=https://api.openai.com/v1

# 데이터베이스 연결 URL
DATABASE_URL=postgresql://agenthub_user:agenthub_password@localhost:5432/agenthub
```

### 2. pgvector 및 DB 마이그레이션 순서
AgentTrace는 소스코드 청크 검색을 위해 `pgvector` 확장을 사용합니다.

1. **pgvector 지원 데이터베이스 컨테이너 구동**:
   `agenthub-backend` 프로젝트 내의 `docker-compose.yml`을 사용하여 데이터베이스를 구동합니다. 이미 `pgvector/pgvector:pg16` 이미지가 적용되어 있습니다.
   ```bash
   # agenthub-backend 폴더에서 실행
   docker compose up -d
   ```
2. **테이블 및 마이그레이션 자동 초기화**:
   별도의 수동 SQL 실행이 필요하지 않습니다. API 서버 또는 워커 프로세스가 구동될 때, 내부적으로 `init_database`가 자동 실행되어 `pgvector` 확장을 활성화하고 필요한 스펙에 부합하는 모든 분석 관련 테이블(`repositories`, `repository_snapshots`, `content_indices`, `repository_analyses`, `analysis_reports`, `source_chunks`, `analysis_jobs`)을 자동 생성 및 마이그레이션합니다.

### 3. API 서버 및 백그라운드 워커(Worker) 실행 방식

#### API 서버 실행 (FastAPI)
```bash
# agenttrace 폴더에서 실행
uvicorn agenttrace.app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 백그라운드 분석 워커(Worker) 실행
AgentTrace는 긴 분석 작업을 처리하기 위한 Durable Task Worker 데몬을 제공합니다. `pyproject.toml`에 실행 명령어가 등록되어 있어 아래와 같이 구동할 수 있습니다.
```bash
# agenttrace 폴더에서 실행
# poetry 환경인 경우: poetry run agenttrace-worker
# venv 환경인 경우:
.venv/bin/agenttrace-worker
```

### 4. API 엔드포인트 사용 예시

#### 4.1 분석 요청 트리거 (`POST /api/v1/analysis`)
비동기 분석 작업을 예약합니다.
* **Request URL**: `http://localhost:8000/api/v1/analysis`
* **Method**: `POST`
* **Payload**:
  ```json
  {
    "analysisId": "8fca133b-fa44-4d18-a248-8902737bcc2e",
    "repositoryId": "be16bfc5-52d8-4d9d-b58d-a414d9b4cef5",
    "snapshotId": "258194b0-7039-4a83-a075-542a922b8b60",
    "commitSha": "abcdef1234567890",
    "githubUrl": "https://github.com/example/repo"
  }
  ```
* **Response (202 Accepted)**:
  ```json
  {
    "status": "queued",
    "message": "Analysis started asynchronously."
  }
  ```

#### 4.2 분석 진행 상태 확인 (`GET /api/v1/analysis/{analysisId}/status`)
트리거한 분석의 작업 진행 상태를 폴링하여 확인합니다.
* **Request URL**: `http://localhost:8000/api/v1/analysis/8fca133b-fa44-4d18-a248-8902737bcc2e/status`
* **Method**: `GET`
* **Response (200 OK)**:
  ```json
  {
    "analysisId": "8fca133b-fa44-4d18-a248-8902737bcc2e",
    "status": "completed",
    "errorMessage": null
  }
  ```

#### 4.3 분석 완료 보고서 조회 (`GET /api/v1/repositories/{repositoryId}/analysis/report`)
성공적으로 완료된 기술 분석 결과 Markdown 보고서를 조회합니다.
* **Request URL**: `http://localhost:8000/api/v1/repositories/be16bfc5-52d8-4d9d-b58d-a414d9b4cef5/analysis/report`
* **Method**: `GET`
* **Response (200 OK)**:
  ```json
  {
    "analysisId": "8fca133b-fa44-4d18-a248-8902737bcc2e",
    "lang": "ko",
    "title": "AgentTrace 기술 분석 보고서",
    "bodyMarkdown": "# 기술 분석 요약\n\n이 프로젝트는...",
    "generatedAt": "2026-06-23T10:00:00Z"
  }
  ```

