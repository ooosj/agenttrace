# Aider Repository Map 알고리즘 상세 분석 보고서

## 1. 조사 목적

본 보고서는 Aider가 대규모 코드베이스를 LLM 컨텍스트에 효율적으로 제공하기 위해 사용하는 Repository Map 알고리즘을 분석한다.

중점적으로 확인하는 내용은 다음과 같다.

* 전체 리포지토리에서 어떤 정보를 추출하는가
* 파일과 심볼 사이의 관계를 어떻게 그래프로 구성하는가
* PageRank가 정확히 무엇을 평가하는가
* 현재 대화나 사용자 요청이 랭킹에 어떻게 반영되는가
* 설정 파일과 CI/CD 파일을 어떻게 보호하는가
* 제한된 토큰 예산 안에 결과를 어떻게 압축하는가
* 이 방식을 AgentTrace에 그대로 적용할 수 있는가

분석 기준은 Aider 공식 Repository Map 문서와 현재 기본 브랜치의 다음 구현이다.

* `aider/repomap.py`
* `aider/special.py`
* 언어별 `*-tags.scm` Tree-sitter 쿼리

---

## 2. 핵심 결론

Aider Repository Map은 다음과 같은 시스템이다.

> 전체 리포지토리를 LLM에 입력하는 시스템이 아니라, 전체 리포지토리에서 심볼과 참조 관계를 추출한 뒤 현재 작업에 중요한 정의만 골라 제한된 토큰 안에 표현하는 구조적 컨텍스트 압축 시스템이다.

전체 흐름은 다음과 같다.

```text
Git 추적 파일 전체
  → 언어 판별
  → Tree-sitter AST 분석
  → 함수·클래스·상수 정의 추출
  → 함수 호출과 심볼 참조 추출
  → 파일 간 참조 그래프 생성
  → 현재 대화에 맞게 Personalized PageRank 실행
  → 중요 파일이 아니라 중요 정의를 랭킹
  → 필수 설정 파일 경로를 앞쪽에 추가
  → 상위 정의를 코드 구조 형태로 렌더링
  → 토큰 예산에 맞도록 이진 탐색
  → LLM 프롬프트에 Repository Map 첨부
```

중요한 점은 Aider가 처음부터 파일 수를 제한하지 않는다는 것이다.

Aider가 제한하는 것은 다음이다.

```text
전체 분석 대상 파일 수     제한하지 않음
전체 심볼 인덱스           가능한 범위에서 모두 생성
LLM에 보여주는 Repo Map    토큰 예산으로 제한
```

따라서 `상위 300개 파일만 수집하고 나머지를 버리는 방식`과 구조적으로 다르다. [S1]

---

## 3. Repository Map의 역할

Aider는 사용자가 직접 대화에 추가한 파일을 `chat files`로 관리한다. 이 파일들은 전체 내용이 LLM 컨텍스트에 제공된다.

나머지 리포지토리 파일은 `other files`로 관리되며, 전체 내용을 넣지 않고 Repository Map으로 요약한다.

```text
LLM Context
├─ 사용자 요청
├─ 대화에 직접 추가된 파일 전체 내용
└─ 나머지 리포지토리의 Repository Map
```

Repository Map에는 일반적으로 다음 정보가 표현된다.

* 파일 경로
* 주요 클래스
* 주요 함수와 메서드
* 함수 시그니처
* 일부 상수와 필드
* 해당 정의의 부모 클래스 또는 코드 구조
* 생략된 부분을 나타내는 표시

예시는 대략 다음과 같다.

```text
src/service/user_service.py:
⋮...
│class UserService:
│    def create_user(
│        self,
│        request: CreateUserRequest,
│    ) -> User:
⋮...
│    def delete_user(self, user_id: int):
```

함수 전체 구현을 넣는 것이 아니라, 코드베이스의 API와 구조를 이해하는 데 필요한 정의 부분만 표시한다.

이 지도만으로 충분하지 않으면 LLM은 특정 파일을 대화 컨텍스트에 추가해 전체 내용을 확인할 수 있다. 즉 Repository Map은 최종 근거 데이터라기보다 탐색을 돕는 전역 내비게이션에 가깝다. [S1]

---

## 4. 입력 데이터

Repository Map 생성 함수는 개념적으로 다음 입력을 받는다.

### 4.1 `chat_fnames`

현재 대화에 전체 내용이 포함된 파일이다.

예:

```text
src/api/user_controller.py
tests/test_user_api.py
```

이 파일들은 이미 전체 내용이 LLM에게 제공되므로 Repository Map 출력에서는 중복 표시하지 않는다.

하지만 그래프 계산에서는 매우 중요한 기준점으로 사용된다.

### 4.2 `other_fnames`

리포지토리에는 존재하지만 현재 대화에 전체 내용이 포함되지 않은 파일이다.

Aider는 이 파일 전체를 대상으로 심볼을 수집하고 그래프를 구성한다.

### 4.3 `mentioned_fnames`

사용자가 메시지에서 직접 언급한 것으로 감지된 파일 경로다.

예:

```text
"UserService가 정의된 user_service.py를 확인해줘"
```

이 경우 `user_service.py`가 Repository Map 랭킹에서 우선된다.

### 4.4 `mentioned_idents`

사용자 메시지에서 언급된 클래스, 함수, 파일명 구성요소 등의 식별자다.

예:

```text
UserService
create_user
authentication
```

Aider는 이 식별자를 심볼 랭킹과 파일 개인화에 사용한다.

### 4.5 `max_map_tokens`

최종 Repository Map에 할당된 토큰 예산이다.

공식 문서의 일반적인 기본값은 약 1,024토큰이다. 다만 현재 대화에 추가된 파일이 하나도 없으면 더 넓은 리포지토리 구조를 보여주기 위해 예산을 크게 늘릴 수 있다.

구현 기본값인 `map_mul_no_files=8`을 적용하면 다음과 같이 동작한다.

```text
기본 map token 예산: 1,024
대화에 포함된 파일 없음:
  최대 약 8,192토큰까지 확대

단:
  전체 모델 컨텍스트 - 4,096토큰보다 커질 수 없음
```

즉 처음 리포지토리를 탐색할 때는 넓은 지도를 제공하고, 특정 파일이 대화에 추가된 이후에는 작은 관련 지도를 제공한다. [S2]

---

## 5. 1단계: 파일별 심볼 추출

## 5.1 언어 판별

Aider는 파일명을 이용해 프로그래밍 언어를 판별한다.

```text
.py   → Python
.ts   → TypeScript
.java → Java
.go   → Go
.rs   → Rust
```

지원되는 언어라면 해당 언어의 Tree-sitter parser와 `tags.scm` 쿼리를 불러온다.

Tree-sitter parser가 없거나 해당 언어의 `tags.scm` 쿼리가 없으면 그 파일에서는 구조적 심볼을 추출하지 못한다.

---

## 5.2 Tree-sitter 쿼리

언어별 `tags.scm`은 어떤 AST 노드를 정의 또는 참조로 인식할지 선언한다.

Python 쿼리의 핵심 구조는 다음과 같다.

```scheme
(class_definition
  name: (identifier) @name.definition.class)

(function_definition
  name: (identifier) @name.definition.function)

(call
  function: [
    (identifier) @name.reference.call
    (attribute
      attribute: (identifier) @name.reference.call)
  ])
```

이 쿼리는 Python에서 다음을 추출한다.

```python
class UserService:
    ...
```

```text
정의: UserService
종류: class
파일: user_service.py
라인: class 선언 위치
```

```python
def create_user(request):
    ...
```

```text
정의: create_user
종류: function
파일: 현재 파일
라인: 함수 선언 위치
```

```python
user_service.create_user(request)
```

```text
참조: create_user
종류: call
파일: 호출한 파일
```

결과는 내부적으로 다음과 같은 `Tag` 형태로 저장된다.

```text
Tag(
  rel_fname="src/service/user_service.py",
  fname="/absolute/path/src/service/user_service.py",
  line=42,
  name="create_user",
  kind="def"
)
```

또는:

```text
Tag(
  rel_fname="src/api/user_controller.py",
  line=73,
  name="create_user",
  kind="ref"
)
```

[S3]

---

## 5.3 추출 결과 데이터 구조

Aider는 수집한 태그를 세 가지 인덱스로 정리한다.

```python
defines[identifier] = {
    definition_file_1,
    definition_file_2,
}
```

예:

```text
defines["UserService"] = {
  "src/service/user_service.py"
}
```

참조는 파일별 호출 횟수를 계산할 수 있도록 리스트로 보관한다.

```python
references[identifier] = [
    referencer_file,
    referencer_file,
    another_referencer_file,
]
```

예:

```text
references["create_user"] = [
  "src/api/user_controller.py",
  "src/api/user_controller.py",
  "tests/test_user_service.py"
]
```

정의 위치도 별도로 보관한다.

```python
definitions[(file, identifier)] = {
    Tag(...)
}
```

이 구조를 통해 다음 두 가지를 동시에 계산할 수 있다.

1. 어떤 파일이 어떤 심볼을 정의하는가
2. 어떤 파일이 해당 심볼을 몇 번 참조하는가

---

## 5.4 참조 추출 실패에 대한 보완

일부 Tree-sitter 언어 쿼리는 정의는 잘 추출하지만 참조를 충분히 추출하지 못한다.

Aider는 한 파일에서 정의는 발견됐지만 참조가 하나도 발견되지 않은 경우, Pygments lexer를 이용해 `Token.Name` 유형의 토큰을 참조 후보로 추가한다.

이는 정확한 호출 관계 분석이라기보다 보완용 lexical reference extraction이다.

따라서 Aider의 참조 그래프는 컴파일러가 생성하는 정확한 call graph와는 다르다.

```text
정확한 타입·네임스페이스 해석
  → 하지 않음

동일한 문자열의 정의·참조 연결
  → 수행
```

동적 언어와 여러 언어를 저비용으로 처리하기 위한 현실적인 절충이다. [S3]

---

## 6. 2단계: 캐싱

전체 리포지토리를 매번 Tree-sitter로 다시 파싱하면 비용이 크기 때문에 파일별 태그 결과를 캐시한다.

캐시 키는 기본적으로 파일 경로이며, 값에는 다음이 저장된다.

```python
{
  "mtime": file_modified_time,
  "data": extracted_tags
}
```

파일의 수정 시간이 이전과 같으면 파싱 결과를 재사용한다.

```text
파일 수정 없음
  → 기존 Tag 캐시 사용

파일 수정됨
  → 해당 파일만 다시 Tree-sitter 분석
```

캐시는 `.aider.tags.cache.vN` 디렉터리에 저장된다.

SQLite 또는 디스크 캐시 오류가 발생하면 인메모리 딕셔너리로 대체된다.

따라서 최초 리포지토리 스캔은 느릴 수 있지만 이후 실행에서는 변경된 파일 중심으로 갱신할 수 있다. [S4]

---

## 7. 3단계: Personalized PageRank용 파일 그래프 생성

## 7.1 그래프 노드

그래프의 노드는 함수나 클래스가 아니라 파일이다.

```text
Node = source file
```

예:

```text
src/api/user_controller.py
src/service/user_service.py
src/repository/user_repository.py
src/model/user.py
```

Aider는 NetworkX의 `MultiDiGraph`를 사용한다.

같은 두 파일 사이에도 여러 심볼로 관계가 생길 수 있으므로 다중 방향 그래프를 사용한다.

---

## 7.2 그래프 간선

파일 A가 어떤 심볼을 참조하고, 해당 심볼이 파일 B에 정의되어 있으면 다음 방향의 간선을 생성한다.

```text
참조 파일 A → 정의 파일 B
```

예:

```python
# user_controller.py
user_service.create_user(request)
```

```python
# user_service.py
def create_user(request):
    ...
```

그래프:

```text
user_controller.py
  ── create_user ──>
user_service.py
```

이 방향이 중요한 이유는 PageRank 점수가 호출자에서 의존 대상 쪽으로 전달되기 때문이다.

현재 중요한 파일이 사용하는 서비스, 라이브러리, 추상화가 높은 점수를 받는다.

---

## 7.3 간선 생성 범위

Aider는 다음 조건을 만족하는 식별자만 정상 간선 생성에 사용한다.

```text
정의 목록에 존재
AND
참조 목록에도 존재
```

즉:

```python
idents = defines.keys ∩ references.keys
```

하나의 식별자가 여러 파일에서 정의됐다면 모든 참조 파일과 모든 정의 파일 사이에 간선을 만든다.

예:

```text
심볼: create

참조 파일:
- api.py
- cli.py

정의 파일:
- user_service.py
- order_service.py
```

생성 가능한 간선:

```text
api.py → user_service.py
api.py → order_service.py
cli.py → user_service.py
cli.py → order_service.py
```

이는 Aider가 실제 타입이나 import resolution을 이용해 정확한 대상을 판별하지 않기 때문에 생기는 특성이다.

---

## 7.4 참조 없는 정의의 self-edge

Tree-sitter 버전 또는 언어 쿼리 특성상 정의만 추출되고 참조가 발견되지 않는 심볼이 있다.

이 경우 Aider는 정의 파일 자신에게 작은 self-edge를 추가한다.

```text
definition_file → definition_file
weight = 0.1
```

이렇게 하면 참조가 없는 정의도 그래프에서 완전히 사라지지 않는다. [S5]

---

## 8. 간선 가중치 계산

Aider는 모든 참조를 동일하게 취급하지 않는다.

기본 가중치는 다음과 같이 표현할 수 있다.

```text
EdgeWeight
  = 심볼 중요도 보정
  × 현재 대화 보정
  × sqrt(참조 횟수)
```

보다 구체적으로는 다음과 같다.

```text
weight(r → d, symbol)
  = M_symbol
  × M_chat
  × sqrt(reference_count)
```

여기서:

* `r`: 심볼을 참조하는 파일
* `d`: 심볼을 정의하는 파일
* `reference_count`: r 파일에서 해당 심볼이 등장한 횟수

---

## 8.1 사용자 언급 심볼

사용자가 직접 언급한 심볼은 가중치를 10배 높인다.

```text
symbol ∈ mentioned_idents
  → ×10
```

예:

```text
사용자 요청:
"UserService의 인증 흐름을 분석해줘"

UserService 관련 간선:
  ×10
```

---

## 8.2 의미 있어 보이는 긴 식별자

다음 형태의 식별자이면서 길이가 8자 이상이면 10배 가중한다.

* `snake_case`
* `kebab-case`
* `camelCase`
* `PascalCase`

예:

```text
UserAuthenticationService → ×10
create_user_session        → ×10
auth-handler               → ×10
```

짧고 일반적인 이름보다 도메인 의미가 담긴 이름을 중요하게 보는 휴리스틱이다.

---

## 8.3 비공개 식별자

언더스코어로 시작하는 식별자는 0.1배로 낮춘다.

```text
_internal_helper → ×0.1
```

내부 구현 세부사항보다 외부에서 사용하는 API를 우선하려는 의도다.

다만 Python에서 중요한 내부 함수도 언더스코어로 시작할 수 있으므로 항상 정확한 기준은 아니다.

---

## 8.4 너무 많은 파일에 정의된 심볼

동일한 심볼이 5개보다 많은 파일에 정의되어 있으면 0.1배로 낮춘다.

```text
len(defines[symbol]) > 5
  → ×0.1
```

예:

```text
get
set
run
create
main
```

이런 일반적인 이름은 문자열 기반 연결에서 잘못된 관계를 대량 생성할 가능성이 크다.

이 보정은 공통 이름으로 인한 그래프 노이즈를 줄인다.

---

## 8.5 현재 대화 파일에서 발생한 참조

참조 파일이 현재 대화에 전체 내용으로 포함된 파일이면 간선 가중치를 50배 높인다.

```text
referencer ∈ chat_files
  → ×50
```

예:

```text
현재 대화 파일:
  user_controller.py

user_controller.py → user_service.py
  ×50
```

현재 작업 중인 파일이 의존하는 서비스와 추상화를 Repository Map에 강하게 노출하기 위한 장치다.

---

## 8.6 참조 횟수

한 파일에서 특정 심볼을 여러 번 사용하면 가중치는 증가한다.

다만 단순 횟수를 그대로 사용하지 않고 제곱근을 적용한다.

```text
reference contribution = sqrt(reference_count)
```

예:

```text
1회 참조   → 1.0
4회 참조   → 2.0
9회 참조   → 3.0
100회 참조 → 10.0
```

참조 횟수가 지나치게 많은 심볼 하나가 전체 랭킹을 독점하는 것을 막는다.

---

## 8.7 전체 가중치 예시

사용자가 `UserService`를 언급했고, 현재 대화의 `user_controller.py`가 `UserService`를 4번 참조한다고 가정한다.

`UserService`는 PascalCase이며 길이가 8자 이상이다.

```text
기본 가중치                    1
사용자 언급                    ×10
긴 PascalCase 식별자           ×10
현재 대화 파일에서 참조         ×50
참조 4회                       ×sqrt(4) = ×2
```

최종:

```text
1 × 10 × 10 × 50 × 2 = 10,000
```

반대로 여러 파일에서 정의된 `_get` 같은 심볼이라면:

```text
기본                           1
언더스코어 시작                 ×0.1
5개 초과 파일에 정의            ×0.1
참조 4회                        ×2
```

최종:

```text
1 × 0.1 × 0.1 × 2 = 0.02
```

즉 현재 작업과 관련 있는 구체적인 도메인 심볼을 매우 강하게 올리고, 일반적이거나 불확실한 심볼은 크게 낮춘다. [S5]

---

## 9. Personalized PageRank

## 9.1 일반 PageRank와의 차이

일반 PageRank는 그래프 전체에서 구조적으로 중요한 노드를 계산한다.

Aider는 현재 사용자 대화와 관련 있는 파일을 시작점으로 강조하기 위해 Personalized PageRank를 사용한다.

개인화 점수를 받는 대상은 다음과 같다.

* 현재 대화에 포함된 파일
* 사용자가 직접 언급한 파일
* 경로 구성요소가 사용자가 언급한 식별자와 일치하는 파일

예:

```text
mentioned identifier:
  authentication

일치 가능한 경로:
  src/authentication/service.py
  packages/authentication/index.ts
```

파일명과 디렉터리명도 현재 요청과 연관된 파일을 찾는 단서로 사용된다.

---

## 9.2 개인화 값

파일 수를 `N`이라고 할 때 기본 개인화 단위는 다음과 같다.

```text
personalize = 100 / N
```

현재 대화 파일이나 직접 언급된 파일에는 이 값을 할당한다.

파일 경로 구성요소가 언급된 식별자와 일치하면 개인화 값이 추가될 수 있다.

NetworkX는 이 값을 내부적으로 확률 분포로 정규화해 PageRank에 사용한다.

---

## 9.3 PageRank의 의미

PageRank 결과는 파일별 점수다.

```text
PageRank[file] = 현재 대화와 그래프 구조를 고려했을 때
                 이 파일이 얼마나 중요한가
```

간선 방향이 `참조 파일 → 정의 파일`이므로 높은 점수는 대체로 다음 파일에 모인다.

* 현재 작업 파일이 의존하는 파일
* 중요한 파일들이 많이 참조하는 파일
* 여러 핵심 흐름에서 재사용되는 추상화
* 사용자가 언급한 심볼을 정의하는 파일
* 도메인 의미가 강한 심볼을 제공하는 파일

이는 단순 파일 인기도가 아니라 현재 작업에 조건부로 계산되는 의존성 중요도다.

---

## 10. 파일 랭킹에서 정의 랭킹으로 변환

PageRank는 파일 단위 점수를 제공한다.

그러나 Repository Map에 필요한 것은 파일 전체 순위뿐 아니라 어떤 함수와 클래스를 보여줘야 하는지에 대한 순위다.

Aider는 각 참조 파일의 PageRank 점수를 해당 파일의 outgoing edge 가중치 비율에 따라 나눈다.

공식은 다음과 같이 정리할 수 있다.

```text
DefinitionContribution(edge)
  = PageRank(source_file)
  × edge_weight
  / source_file_total_outgoing_weight
```

같은 정의로 들어오는 모든 간선 기여도를 합산한다.

```text
DefinitionScore(definition_file, symbol)
  = Σ DefinitionContribution(edges to definition)
```

예:

```text
api.py PageRank = 0.4

api.py outgoing edges:
- api.py → user_service.py / create_user : weight 80
- api.py → logger.py / log               : weight 20

총 outgoing weight = 100
```

점수 전달:

```text
create_user 정의:
  0.4 × 80 / 100 = 0.32

log 정의:
  0.4 × 20 / 100 = 0.08
```

이렇게 하면 하나의 중요한 파일 안에서도 현재 작업에 더 관련 있는 심볼이 높은 점수를 받는다.

최종적으로 다음 단위가 정렬된다.

```text
(definition_file, identifier) → score
```

즉 Aider가 랭킹하는 최종 대상은 단순히 파일이 아니라 `파일 안의 정의`다. [S5]

---

## 11. 그래프에 잡히지 않은 파일 처리

모든 파일이 정의와 참조를 가지는 것은 아니다.

예:

* 설정 파일
* 문서
* SQL
* 단순 데이터 파일
* Tree-sitter 미지원 언어
* 정의가 없는 스크립트

Aider는 그래프에서 랭킹된 정의를 먼저 배치한 뒤 다음을 추가한다.

1. PageRank 노드에는 있지만 랭킹된 정의가 없는 파일
2. 아직 포함되지 않은 나머지 파일

이 파일들은 `파일 경로만 있는 항목`으로 Repository Map 후보에 남는다.

따라서 구조적 분석이 되지 않은 파일도 전체 후보에서 완전히 삭제되지는 않는다.

---

## 12. 중요 설정 파일 보호

Aider는 구조적 그래프와 별도로 중요한 파일 경로 목록을 관리한다.

주요 대상은 다음과 같다.

### 패키지 및 빌드

```text
pyproject.toml
requirements.txt
package.json
pom.xml
build.gradle
go.mod
Cargo.toml
Gemfile
```

### 컨테이너와 배포

```text
Dockerfile
docker-compose.yml
serverless.yml
main.tf
kubernetes.yaml
```

### CI/CD

```text
Jenkinsfile
.gitlab-ci.yml
.travis.yml
azure-pipelines.yml
.circleci/config.yml
.github/workflows/*.yml
```

### API 및 데이터베이스

```text
openapi.yaml
swagger.yaml
schema.sql
flyway.conf
liquibase.properties
```

### 프로젝트 설정

```text
tsconfig.json
pytest.ini
tox.ini
mypy.ini
.env.example
```

이 파일이 일반 심볼 랭킹에 들어있지 않으면 랭킹 결과 앞에 추가된다.

```python
ranked_tags = special_files + pagerank_ranked_tags
```

다만 중요한 한계가 있다.

Aider는 이 파일들의 내용을 반드시 분석해서 보여주는 것이 아니다.

구조적 Tag가 없는 중요 파일은 Repository Map에 다음과 같이 파일명만 표시될 수 있다.

```text
pyproject.toml

Dockerfile

.github/workflows/test.yml
```

즉 Aider의 중요 파일 보호는:

```text
파일 존재를 LLM에 알림        O
설정 내용을 구조적으로 분석    X
설정 간 의존 관계 분석          X
```

이다.

또한 현재 구현에서 GitHub Actions 자동 보호 조건은 `.github/workflows` 아래의 `.yml` 파일이다. `.yaml` 확장자까지 같은 조건으로 처리되는 것은 아니다.

AgentTrace가 Aider 방식을 도입한다면 설정 파일은 경로만 보호하는 수준을 넘어 별도의 구조화된 파서를 추가하는 것이 바람직하다. [S6]

---

## 13. 토큰 예산 최적화

## 13.1 랭킹된 Tag 목록

PageRank와 필수 파일 처리가 끝나면 다음과 같은 순서 목록이 생성된다.

```text
1. 필수 설정 파일
2. 가장 높은 점수의 정의
3. 두 번째로 높은 점수의 정의
4. ...
5. 그래프에 잡히지 않은 파일
```

이 전체를 모두 LLM에게 보내는 것이 아니라 앞부분 일부만 선택한다.

---

## 13.2 이진 탐색

Aider는 몇 개의 Tag를 선택하면 토큰 예산에 맞는지를 이진 탐색으로 찾는다.

개념적 의사 코드는 다음과 같다.

```python
low = 0
high = len(ranked_tags)

while low <= high:
    middle = (low + high) // 2

    selected = ranked_tags[:middle]
    rendered_map = render(selected)
    tokens = count_tokens(rendered_map)

    if tokens < max_map_tokens:
        low = middle + 1
    else:
        high = middle - 1
```

초기 추정값은 다음을 사용한다.

```text
middle = max_map_tokens / 25
```

즉 하나의 Tag가 평균 약 25토큰을 사용할 것이라고 가정한 초기값이다.

---

## 13.3 허용 오차

렌더링 결과가 목표 토큰 수에서 15% 이내이면 충분히 근접했다고 판단해 탐색을 종료할 수 있다.

```text
오차율 =
  abs(actual_tokens - max_map_tokens)
  / max_map_tokens

오차율 < 0.15
  → 결과 채택 가능
```

또한 예산을 넘지 않는 결과 중 가장 많은 토큰을 사용한 결과를 보관한다.

목표는 단순히 예산 이하가 아니라 가능한 한 예산을 꽉 채우는 것이다.

---

## 13.4 랭킹 순서와 출력 순서

선택 단계에서는 PageRank 순서의 상위 N개를 선택한다.

```python
selected = ranked_tags[:N]
```

하지만 실제 Repository Map으로 렌더링할 때는 선택된 Tag를 파일 경로순으로 정렬한다.

```text
선택 기준: 중요도 순
출력 기준: 파일 경로 순
```

따라서 LLM에게 보여지는 결과는 읽기 쉬운 파일 구조로 정리되지만, 포함 여부 자체는 PageRank 중요도가 결정한다.

---

## 13.5 코드 구조 렌더링

선택된 정의의 라인 번호를 `lines of interest`로 지정한다.

그다음 `TreeContext`가 해당 라인의 부모 코드 구조와 필요한 문맥을 렌더링한다.

예:

```text
정의 라인:
  def create_user(...)

렌더링 결과:
  class UserService:
      ...
      def create_user(...):
```

전체 함수 본문보다는 정의가 어떤 클래스와 범위 안에 존재하는지를 보여주는 형태다.

---

## 13.6 긴 라인 보호

minified JavaScript나 비정상적으로 긴 코드가 컨텍스트를 독점하지 않도록 최종 출력의 각 라인을 최대 100자로 자른다.

```python
line[:100]
```

이는 비정상 데이터에 대한 단순하지만 효과적인 컨텍스트 보호 장치다. [S7]

---

## 14. 토큰 계산 최적화

짧은 Repository Map은 모델 tokenizer로 정확히 계산한다.

긴 문자열은 계산 비용을 줄이기 위해 전체 라인 중 약 100개를 샘플링하고 비례 계산한다.

```text
sample_tokens / sample_characters
  × total_characters
  ≈ estimated_total_tokens
```

따라서 이진 탐색에서 사용하는 토큰 수는 대규모 출력에서는 근삿값일 수 있다.

15% 허용 오차를 두는 이유 중 하나도 이러한 추정 방식과 관련이 있다고 해석할 수 있다. [S2]

---

## 15. Repository Map 캐시 갱신 정책

Aider는 파일별 Tag 캐시 외에도 완성된 Repository Map을 메모리에 캐시한다.

캐시 키에는 다음이 들어간다.

* chat files
* other files
* 토큰 예산
* 일부 모드에서는 언급 파일
* 일부 모드에서는 언급 식별자

지원되는 갱신 모드는 다음과 같다.

### `always`

매번 Repository Map을 다시 생성한다.

### `files`

파일 집합과 예산이 같으면 기존 결과를 재사용한다.

### `manual`

마지막으로 생성된 Repository Map을 계속 사용한다.

### `auto`

Repository Map 생성 시간이 1초보다 길었던 경우 캐시 사용을 활성화한다.

현재 대화의 언급 파일과 식별자도 캐시 키에 포함해 요청 변화에 따른 지도 변경을 반영한다.

즉 비싼 대형 리포지토리는 적극 캐싱하고, 작은 리포지토리는 최신성을 위해 자주 계산하는 방식이다. [S4]

---

## 16. 계산 복잡도

다음은 구현을 바탕으로 한 개략적인 복잡도 분석이다.

### 최초 파싱

```text
O(전체 분석 파일 크기)
```

모든 파일을 한 번 Tree-sitter로 파싱해야 한다.

### 증분 파싱

```text
O(변경된 파일 크기)
```

수정 시간 기반 캐시가 유효한 파일은 재사용된다.

### 그래프 생성

식별자별로 참조 파일과 정의 파일을 조합한다.

```text
O(
  Σ_identifier
  참조 파일 수 × 정의 파일 수
)
```

같은 이름이 많은 파일에서 정의될수록 간선 수가 늘어난다.

Aider는 5개보다 많은 파일에 정의된 식별자의 가중치를 낮추지만, 간선 생성을 생략하지는 않는다.

### PageRank

일반적으로 반복 횟수를 `I`라고 하면:

```text
O(I × (V + E))
```

* `V`: 파일 수
* `E`: 심볼 참조 기반 간선 수

### 토큰 맞춤

Tag 수를 `T`라고 하면 이진 탐색 자체는:

```text
O(log T)
```

번의 렌더링과 토큰 계산을 수행한다.

---

## 17. 장점

### 17.1 전체 리포지토리 범위 유지

파일 300개를 미리 삭제하는 방식과 달리 전체 리포지토리가 구조 분석 후보로 유지된다.

### 17.2 LLM 호출 없이 구조 분석

Tree-sitter, 문자열 매칭, PageRank를 사용하므로 Repository Map 생성 자체에는 LLM 호출이 필요하지 않다.

### 17.3 현재 작업에 적응

대화에 포함된 파일, 언급된 파일, 언급된 심볼에 따라 같은 리포지토리라도 다른 지도가 생성된다.

### 17.4 파일보다 세밀한 선택

파일 단위가 아니라 함수와 클래스 정의 단위로 중요도를 계산한다.

### 17.5 컨텍스트 효율성

함수 전체 구현 대신 시그니처와 코드 구조를 보여주므로 적은 토큰으로 전역 구조를 전달할 수 있다.

### 17.6 재현 가능성

같은 파일 상태와 같은 입력이면 결과가 대체로 결정적이다. 작은 LLM에게 전체 파일 선별을 맡기는 방식보다 결과를 추적하고 디버깅하기 쉽다.

---

## 18. 한계

## 18.1 정확한 의미 분석이 아니다

Aider는 동일한 이름의 정의와 참조를 문자열 중심으로 연결한다.

다음 코드를 정확히 구분하지 못할 수 있다.

```python
user_service.create()
order_service.create()
database.create()
```

모두 `create` 참조로 수집될 수 있다.

정확한 import resolution, 타입 추론, 오버로딩 해석을 수행하는 compiler-grade symbol graph는 아니다.

---

## 18.2 일반적인 이름으로 잘못된 간선 생성 가능

`run`, `get`, `create`, `execute` 같은 이름은 여러 모듈에서 사용된다.

Aider는 다수 파일 정의에 0.1 가중치를 적용하지만 잘못된 연결 자체를 제거하지는 않는다.

---

## 18.3 설정 파일 의미를 이해하지 않는다

`pyproject.toml`, `package.json`, Dockerfile, CI 파일을 중요한 경로로 보호하지만 내부 설정을 파싱해 의존 관계를 만들지는 않는다.

따라서 다음을 직접 알 수는 없다.

```text
package.json script → 실제 entrypoint
Dockerfile CMD → 실행 모듈
GitHub Actions step → 배포 스크립트
pyproject dependency → 사용 프레임워크
```

---

## 18.4 참조되지 않는 핵심 코드가 낮게 평가될 수 있다

다음 파일은 중요하지만 참조가 적을 수 있다.

* 애플리케이션 entrypoint
* 플러그인 진입점
* 리플렉션으로 호출되는 코드
* 프레임워크가 자동 탐색하는 설정
* CLI command registry
* 이벤트 핸들러
* 테스트 fixture
* migration

PageRank는 연결 중심성이 낮은 leaf 파일을 놓칠 수 있다.

---

## 18.5 구조적 중요도와 분석 중요도는 다르다

많이 참조되는 유틸리티가 높은 점수를 받을 수 있지만, 사용자가 알고 싶은 핵심 비즈니스 기능과는 무관할 수 있다.

```text
그래프 중심성 높음
≠
분석 목적상 중요함
```

---

## 18.6 Repository Map은 근거 원문이 아니다

함수 시그니처와 일부 구조만 보여주므로 다음을 판단하기에는 부족하다.

* 실제 비즈니스 로직
* 에러 처리
* 보안 정책
* 조건 분기
* 데이터 변환
* 런타임 동작
* README Claim 구현 여부

Repository Map은 탐색 시작점이고, 최종 분석은 원본 파일과 코드 청크를 다시 읽어야 한다.

---

## 18.7 모델에 따라 오히려 혼란을 줄 수 있음

Aider 공식 문서에서는 상대적으로 약한 모델이 Repository Map을 실제 편집 대상 코드로 오인하거나 과도한 정보에 혼란을 느낄 수 있다고 안내한다.

따라서 모든 모델에서 Repository Map을 항상 활성화하는 것이 최선은 아니다. [S8]

---

## 19. AgentTrace 적용 적합성

Aider Repository Map은 AgentTrace에 유용하지만 그대로 복제해서 최종 파일 선별기로 사용해서는 안 된다.

AgentTrace는 단순 코드 수정이 아니라 다음을 분석한다.

* 핵심 기능
* 아키텍처
* 실행 흐름
* 기술 스택
* README Claim 검증
* 배포·운영 설정
* 데이터베이스
* Agent 구조
* 리스크와 후속 확인 지점

따라서 Aider 방식은 `전역 구조 지도`로 사용하고, 실제 증거 검색은 별도 파이프라인으로 수행하는 것이 적합하다.

---

## 20. AgentTrace 권장 구조

```text
Repository Snapshot
  │
  ├─ 전체 유효 파일 카탈로그
  │
  ├─ Tree-sitter Symbol Index
  │    ├─ definitions
  │    └─ references
  │
  ├─ Structural File Graph
  │    └─ Personalized PageRank
  │
  ├─ Important Artifact Index
  │    ├─ package/build manifests
  │    ├─ Docker
  │    ├─ CI/CD
  │    ├─ API schemas
  │    └─ DB migrations
  │
  ├─ Full-text/BM25 Search
  │
  └─ Area-specific Retrieval
       ├─ 기능
       ├─ 아키텍처
       ├─ 실행 흐름
       ├─ Claim 검증
       ├─ 배포·운영
       └─ 리스크
```

---

## 21. Aider 방식에서 그대로 가져올 부분

### 도입 권장

* 전체 소스 파일을 Tree-sitter 분석 대상으로 유지
* 함수·클래스 정의와 참조 추출
* 파일 단위 MultiDiGraph
* 참조 파일에서 정의 파일로 향하는 간선
* PageRank 기반 구조 중요도
* 현재 분석 영역에 따른 personalization
* 긴 일반 이름과 공통 이름에 대한 가중치 보정
* 수정 시간 기반 파일별 인덱스 캐시
* 토큰 예산에 따른 구조 지도 생성
* 중요 설정 파일의 별도 보호

---

## 22. AgentTrace에서 보완해야 할 부분

### 22.1 설정 파일 구조화 분석

경로만 보호하지 말고 별도 파서로 내용을 추출한다.

```text
package.json
  → dependencies
  → scripts
  → workspace
  → entrypoint

pyproject.toml
  → dependencies
  → build system
  → tool configuration

Dockerfile
  → base image
  → build stages
  → ENTRYPOINT/CMD

GitHub Actions
  → trigger
  → build/test/deploy steps
```

### 22.2 분석 영역별 Personalized PageRank

하나의 Repository Map만 생성하지 않고 분석 영역별로 다른 seed를 사용한다.

예:

```text
기능 분석:
  controller, service, feature, handler, command

아키텍처 분석:
  interface, adapter, repository, module, provider

Agent 분석:
  graph, node, tool, agent, prompt, state

배포 분석:
  Dockerfile, workflow, deployment, terraform

Claim 검증:
  README에서 추출한 Claim 식별자
```

### 22.3 PageRank와 검색 결합

최종 검색 점수는 다음처럼 혼합하는 것이 적합하다.

```text
FinalRetrievalScore
  = α × PageRank
  + β × BM25
  + γ × PathPrior
  + δ × SymbolMatch
  + ε × ArtifactPriority
```

필요하다면 마지막 후보에만 소형 LLM reranker를 적용한다.

### 22.4 파일 영구 제거 금지

PageRank가 낮더라도 인덱스에서는 제거하지 않는다.

```text
PageRank 낮음
  → 초기 컨텍스트에서 제외 가능
  → 검색 대상에서는 계속 유지
```

### 22.5 실제 분석에는 원문 코드 사용

Repository Map으로 후보 파일과 심볼을 찾은 후 원문 청크를 다시 수집한다.

```text
Repo Map
  → 후보 심볼
  → 원본 파일 검색
  → 관련 코드 청크
  → 근거 생성
  → Finding 작성
```

---

## 23. 권장 데이터 모델

```python
class SymbolTag:
    file_path: str
    symbol_name: str
    symbol_kind: str
    line_start: int
    line_end: int | None
    tag_kind: Literal["definition", "reference"]
```

```python
class SymbolEdge:
    source_file: str
    target_file: str
    symbol_name: str
    reference_count: int
    weight: float
```

```python
class FileRank:
    file_path: str
    pagerank_score: float
    personalization_reasons: list[str]
```

```python
class DefinitionRank:
    file_path: str
    symbol_name: str
    score: float
    supporting_edges: list[str]
```

```python
class RepoMapEntry:
    file_path: str
    selected_symbols: list[str]
    rendered_context: str | None
    selection_reason: list[str]
```

특히 `selection_reason`과 `supporting_edges`를 저장하면 어떤 파일과 심볼이 선택됐는지 추적할 수 있다.

---

## 24. 최종 판단

Aider Repository Map은 다음 문제에 매우 효과적인 해법이다.

> 리포지토리 전체를 버리지 않으면서도 제한된 LLM 컨텍스트 안에 전역 코드 구조를 전달하는 문제

핵심 설계 원칙은 다음 세 가지다.

```text
1. 전체 리포지토리는 구조 인덱스에 유지한다.
2. 현재 작업과 관련 있는 정의를 PageRank로 선택한다.
3. 선택된 구조 표현만 토큰 예산에 맞춰 LLM에게 제공한다.
```

AgentTrace의 현재 `파일 점수 정렬 → 상위 300개 절단` 방식보다 정보 보존과 추적 가능성이 높다.

그러나 Aider 방식만으로 AgentTrace의 전체 분석을 수행할 수는 없다.

Aider Repository Map은 다음 역할이 가장 적절하다.

```text
최종 분석기             X
최종 증거 검색기         X
전체 파일 제거 기준      X

구조 인덱스              O
분석 시작점 생성기        O
후보 파일·심볼 랭커       O
LLM용 전역 코드 지도      O
```

따라서 AgentTrace에서는 다음 조합을 권장한다.

```text
Aider식 Tree-sitter + PageRank Repo Map
  + 중요 설정 파일 구조화 파서
  + BM25/Full-text Search
  + 분석 영역별 반복 검색
  + 원본 코드 근거 검증
```

이 구조라면 전체 파일을 무작정 LLM에 넣지 않으면서도, 초기 300개 파일 제한으로 인한 복구 불가능한 정보 손실을 피할 수 있다.
