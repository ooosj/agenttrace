# Troubleshooting & Learnings Log

이 문서는 AgentTrace 개발 과정에서 발견된 중요 시행착오, 트러블슈팅 내역, 그리고 디자인 패턴 상의 레슨 런(Lesson Learned)을 기록하여 미래의 에이전트와 개발자가 동일한 실수를 반복하지 않도록 돕는 로그입니다.

---

## 1. structlog 설정 시 PrintLogger 명칭 처리 에러 (AttributeError)

* **문제 현상**: 파이프라인 로깅을 위해 `structlog` 설정을 적용한 후 테스트 실행 시 `PrintLogger`에 `name` 속성이 없다는 `AttributeError` 발생.
* **원인**:
  ```python
  structlog.configure(
      processors=[
          structlog.stdlib.add_logger_name,  # <- 원인
          ...
      ],
      logger_factory=structlog.PrintLoggerFactory()  # PrintLogger 반환
  )
  ```
  `structlog.stdlib.add_logger_name` 프로세서는 표준 라이브러리(stdlib) 스타일의 로거를 상정하므로 로거 객체에 `.name` 속성이 존재해야 합니다. 하지만 `PrintLoggerFactory`가 만드는 `PrintLogger`는 이 속성이 없어 에러가 발생합니다.
* **해결 방법**:
  `structlog` 설정의 `processors` 체인에서 `structlog.stdlib.add_logger_name`을 제거하여 명칭을 추가하는 프로세스를 우회했습니다.
* **레슨 런**: `PrintLogger`를 로거 팩토리로 쓸 때는 표준 라이브러리 의존적인 프로세서(예: `stdlib` 네임스페이스 하위 프로세서)의 동적 속성 접근을 주의해야 합니다.

---

## 2. 노드 내 레거시 함수(Legacy functions) 호출 시 스코프 에러 (NameError)

* **문제 현상**: `evidence_scout` 노드에 로깅을 추가한 뒤 테스트 실행 시 `NameError: name 'log' is not defined`로 실패.
* **원인**:
  ```python
  def evidence_scout(state):
      _t = time.perf_counter()
      log = logger.bind(node="evidence_scout")
      ...
      if not task:
          return _legacy_evidence_scout(state)  # 내부에서 log, _t 호출
  ```
  별도 모듈 레벨 함수로 정의된 `_legacy_evidence_scout` 함수 안에서 상위 로컬 스코프의 `log` 및 `_t`를 직접 참조하여 발생한 스코프 범위 에러입니다.
* **해결 방법**:
  `_legacy_evidence_scout(state, log, _t)` 형태로 로깅 컨텍스트(`log`)와 시간 측정 시작점(`_t`)을 인자로 명시적으로 넘겨주도록 함수 시그니처와 호출부를 수정했습니다. `_legacy_quality_gate` 역시 동일하게 보완했습니다.
* **레슨 런**: LangGraph 노드 내부에서 조건에 따라 별도 헬퍼 함수나 레거시 로직 함수로 분기할 경우, 로컬 바인딩 로거(`log`)와 측정 시작 시각(`_t`)을 인자로 투명하게 전달해야 합니다.

---

## 3. Worker 내 잡(Job) 데이터베이스 외래키 방어코드

* **문제 현상**: 과도기적/독립적 워커 런 실행 시 parent 레코드 누락으로 인한 외래키(Foreign Key) 무결성 에러 발생 가능성 존재.
* **해결 방법**:
  [worker.py](file:///Users/wolyong/workspace/AgentHub/agenttrace/src/agenttrace/app/worker.py) 내 `run_analysis_pipeline` 진입 시 `repositories` 및 `repository_snapshots` 테이블에 방어적 삽입(`INSERT ON CONFLICT DO NOTHING`)을 수행하여 외래키 에러를 예방합니다.

---

## 4. pytest 환경에서의 structlog sys.stderr 바인딩 closed file 에러

* **문제 현상**: CLI 표준 출력 오염 방지를 위해 로깅 출력을 `sys.stderr`로 변경 후, pytest 실행 시 일부 CLI 테스트에서 `ValueError: I/O operation on closed file.` 발생.
* **원인**:
  pytest는 각 테스트 진행 시 표준 입출력 스트림(`sys.stdout`, `sys.stderr`)을 동적으로 캡처하고 테스트 종료 시 닫습니다. `setup_logging` 호출 단계에서 `structlog.PrintLoggerFactory(sys.stderr)` 형태로 넘기면, 해당 시점에 바인딩되어 있던 특정 파일 객체(`sys.stderr`)를 상시 캐싱하게 됩니다. 이로 인해 다음 테스트 차례에 이미 닫혀버린 파일 객체에 접근을 시도하여 오류가 유발됩니다.
* **해결 방법**:
  런타임에 동적으로 `sys.stderr`를 조회하여 기록하는 `StderrPrintLogger` 클래스를 구현하고, `logger_factory`를 `lambda *args, **kwargs: StderrPrintLogger()` 형태로 동적 할당하도록 구조화하여 문제를 해결했습니다.
* **레슨 런**: 글로벌 싱글톤이나 한 번만 설정되는 프레임워크 로깅 초기화 시, 테스트 러너가 가로채어 관리하는 시스템 스트림 파일 객체를 직접 참조 보관해서는 안 됩니다. 반드시 지연 평가(Lazy evaluation)를 통해 런타임의 최신 파일 핸들을 획득하도록 구현해야 합니다.

---

## 5. DB 테이블 격리 및 격리명 적용 시 기존 테스트 깨짐 현상

* **문제 현상**: `repository_analyses` 테이블명을 `agenttrace_repository_analyses`로 격리 패치 적용 후 `test_content_index_store.py` 내의 테스트에서 어서션 에러 발생.
* **원인**:
  기존 단위 테스트 코드 내에서 DB 마이그레이션 쿼리 생성이 제대로 작동하는지 검사할 때, 하드코딩된 `"CREATE TABLE repository_analyses"` 및 `"INSERT INTO repository_analyses"` 문자열 매칭을 검사하고 있어 바뀐 테이블명을 찾지 못해 에러가 발생했습니다.
* **해결 방법**:
  [test_content_index_store.py](file:///Users/wolyong/workspace/AgentHub/agenttrace/tests/test_content_index_store.py) 내 어서션 타겟을 `agenttrace_repository_analyses`로 수정하여 테스트가 변경된 테이블명을 정확히 검증하도록 복구했습니다.
* **레슨 런**: 데이터베이스 테이블 설계나 스키마 명칭을 리팩토링할 때는 연계된 SQL 유효성 검사기 정적 테스트 및 Mock 연결(RecordingConnection) 어서션을 전량 확인하여 테이블명 격리가 테스트 레벨에서도 반영되도록 동기화해야 합니다.

---

## 6. 마크다운 스펙 자동 파싱 테스트(test_spec_sync.py) 정규식 및 파싱 범위 에러

* **문제 현상**: `test_spec_sync.py` 테스트 생성 후 실행 시 `AssertionError: 스펙에서 8개 영역을 찾지 못했습니다 (찾은 개수: 0)` 및 목차 순서 불일치 에러 발생.
* **원인**:
  1. `AI_ANALYSIS_SPEC.md` 원문에는 영역 ID 백틱(`project-purpose`)을 감싸는 괄호 `(...)`가 존재했으나, 정규식에 괄호 매칭 기호가 누락되어 8대 영역을 매칭하지 못했습니다.
  2. 11대 섹션명을 파싱할 때 `\d+\.\s+\*\*([^*]+)\*\*` 패턴이 문서 전체를 스캔하면서 상위 개요 부분의 목차들(예: `1. **Repository 기술 분석 중심 설계**`)까지 매칭하여 순서가 불일치했습니다.
* **해결 방법**:
  1. 영역 ID 정규식을 `re.findall(r"영역 \d+:\s+\*\*([^*]+)\*\*\s+\(\\?`([^`]+)\\?`\)", content)`로 수정하여 괄호 짝을 맞춰 매칭하도록 수정했습니다.
  2. 전체 스캔 대신 `section_block = content.split("#### 6.13.2 11대 고정 보고서 섹션")[1].split("#### 6.13.3")[0]` 방식을 적용하여 **11대 섹션이 선언된 본문 블록만 타겟팅**해 파싱 범위를 고립시켰습니다.
* **레슨 런**: 기획/설계 문서를 읽어 코드를 검증하는 Specification-as-Code 기법을 적용할 때는 정규식 매칭이 전체 문서의 불필요한 영역(Header, Intro)을 오탐하지 않도록 대상 텍스트 영역을 물리적으로 슬라이싱(Slicing)한 후 검사를 적용하는 것이 안전합니다.

