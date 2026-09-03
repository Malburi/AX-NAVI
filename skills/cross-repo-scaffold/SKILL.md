---
name: cross-repo-scaffold
description: 페어 연동된 백엔드+프론트엔드(1:1) 또는 백엔드+여러 클라이언트(1:N, 예: 백엔드+웹+모바일+관리자) 전체 스택 기능을 한 번에 스캐폴딩한다. "전체 스택 기능 만들어줘", "백엔드랑 프론트 같이 만들어줘", "full-stack feature", "API부터 화면까지 만들어줘", "엔드투엔드 기능 추가", "cross-repo scaffold", "백엔드 API 만들고 프론트 연동해줘" 요청 시 트리거.
---

# Cross-Repo Scaffold (오케스트레이터)

`pair-init`으로 연동된 저장소들에 기능을 동시 스캐폴딩한다.  
백엔드 API 계약을 기준으로 클라이언트(들)의 서비스·컴포넌트·라우트를 정합하게 생성해 **드리프트 없는 풀스택 기능**을 만든다.
1:1(백엔드+프론트엔드 1개)과 1:N(백엔드+클라이언트 여러 개)을 모두 지원한다.

---

## Phase 0: 사전 조건 확인

백엔드와 선택된 모든 클라이언트에서 생성 예정 확장자별 `check-adapter-coverage.mjs`를 실행한다. 어느 한 저장소라도 PARTIAL/UNSUPPORTED이면 해당 저장소와 전체 판정은 수동 스택 검증 전까지 최소 HOLD다. 지원 수준이 다른 저장소의 GO를 합쳐 전체 GO로 올리지 않는다.

### 페어 설정 확인

`_workspace/pair_config.md` 존재·로드:
- 없으면 → "먼저 `pair-init`으로 연동하세요" 안내 후 중단.
- `## Partner:` 블록이 있으면 hub-roots(1:N) 형식, 없으면 기존 paired-roots(1:1) flat 형식.

**1:1(flat)인 경우** pair_config에서 읽어오는 변수:
- `project_type` (현재: backend/frontend)
- `partner_type`, `partner_root`, `partner_workspace`
- `api_contract_path`, `partner_api_contract`
- `api_base_url`

변수를 기반으로 `backend_root`·`frontend_root`를 결정하고, `frontend_targets = [{ label: partner_type, root: frontend_root, api_contract: partner_api_contract }]`(1개짜리 리스트)로 통일해 이후 Phase에서 1:N과 같은 코드 경로를 쓴다.

**1:N(hub-roots)인 경우** `## Partner: <label>` 블록마다 `{ label, partner_root, partner_workspace, partner_api_contract }`를 파싱해 클라이언트 후보 목록을 만든 뒤, 등록된 클라이언트가 2개 이상이면 매번 체크리스트로 포함 대상을 묻는다:

```
등록된 클라이언트: [role_label 1], [role_label 2], [role_label 3], ...

이번 스캐폴딩에 포함할 클라이언트를 선택하세요 (쉼표로 구분, 전체는 "all"):
```

응답으로 선택된 항목만 `frontend_targets = [{ label, root: partner_root, api_contract: partner_api_contract }, ...]`에 담는다. 무응답이면 전체(all)로 처리.

`backend_root`는 hub-roots에서 항상 현재 프로젝트(hub)다.

`_workspace/wiki/architecture.md`(통합본, `generate-wiki`로 생성된 경우)가 있으면 먼저 훑어 기존 시스템 구조를
빠르게 파악하는 데 참고할 수 있다 — 단, 생성 시점 스냅샷이므로 실제 API 계약·패턴은 아래처럼
반드시 `_workspace/index/api_contract.json`·패턴 파일을 라이브로 다시 확인한다.

### 패턴 프로필 확인 (백엔드 + 선택된 클라이언트 전부)

- 백엔드와 각 `frontend_targets` 루트에서 `pattern_profile.py validate --root "[root]"`를 실행한다.
- `.claude/patterns/pattern_profile.json`의 실제 기준 파일과 `.claude/patterns/*.md` 상세 문서를 함께 사용한다.

하나라도 프로필 누락·검증 실패·스켈레톤 상태(pattern-extractor 미실행)면 경고:
```
[WARN] [대상] 패턴이 아직 추출되지 않았습니다.
       실제 기준 파일이 검증되지 않아 코드 스타일 일치를 보장할 수 없습니다.
       계속 진행할까요? (Y/N)
```

계속 진행하더라도 해당 저장소의 최종 판정은 최소 HOLD이며 GO로 승격하지 않는다.

### API 계약 로드

`[backend_root]/_workspace/index/api_contract.json` 로드:
- 없으면 → api-bridge(extract)로 즉시 추출 후 계속.

---

## Phase 1: 기능 명세 수집

사용자에게 한 번에 질문:

```
전체 스택 기능 스캐폴딩 정보 입력:

1. 기능명: (예: "주문 취소", "회원 등록", "상품 검색")
2. API 엔드포인트: (예: POST /api/orders/{id}/cancel)
   → 기존 api_contract.json에 없는 신규 엔드포인트입니다.
3. 백엔드 생성 범위:
   [전체] Controller + Service + DAO/Repository + DTO + Test  (기본)
   [일부] 원하는 레이어만 입력
4. 프론트엔드 생성 범위:
   [전체] Service 스텁 + Component + Route 등록  (기본)
   [스텁만] Service 함수만
5. 유사 기존 기능 (패턴 참조용, 선택): (예: "주문 환불처럼")
```

입력 처리:
- 엔드포인트 형식 정규화: `post /api/orders/{id}/cancel` → `POST /api/orders/{id}/cancel`
- 도메인 추출: `/api/orders/...` → `order` 도메인 → 파일명 접두사 결정

---

## Phase 2: 사전 충돌 검사

### 백엔드 충돌

`api_contract.json`에서 동일 경로·메서드 확인:
- 있으면 → "이미 존재하는 엔드포인트입니다. 덮어쓸까요, 다른 경로를 쓸까요?"

### 프론트엔드 충돌

`frontend_targets`의 **각 대상마다** `[target.root]/src/`(또는 그 스택의 소스 루트) 내 동일 도메인 서비스 파일·컴포넌트명을 검색한다 — 단일 대상만 보지 않는다(1:N에서 일부 클라이언트에만 있는 충돌을 놓치지 않기 위함):
- 있으면 → 해당 대상 label과 함께 "[label]에 기존 파일이 있습니다. 함수를 추가할까요, 신규 파일을 만들까요?"

---

## Phase 3: 백엔드 스캐폴딩

```
Agent(
  subagent_type="general-purpose",
  description="백엔드 레이어 생성 ([기능명])",
  prompt="scaffold-feature 스킬 지침에 따라 백엔드 레이어만 생성한다.
  
  프로젝트 루트: [backend_root]
  기능명: [기능명]
  API 엔드포인트: [METHOD /path]
  생성 범위: [백엔드 생성 범위]
  유사 모듈: [유사 기능명 — 없으면 생략]
  구조화 패턴: [backend_root]/.claude/patterns/pattern_profile.json
  분석 리포트: [backend_root]/_workspace/01_analyzer_report.md

  생성 전 pattern_profile.py select로 대상 경로·모듈·레이어별 preferred 프로필을 선택하고,
  선택 결과의 reference_files를 직접 읽어 구조·명명·예외·테스트 패턴을 복제한다.
  
  cross-repo 모드: true
  → Phase 3-6 (설정/라우팅 등록)까지만 수행.
  → Phase 4 (사후 안전성)는 cross-repo-scaffold가 Phase 6에서 통합 실행.
  → 생성된 파일 목록을 [backend_root]/_workspace/reports/cross_scaffold_backend.md에 저장.",
  model="sonnet"
)
```

완료 후 `_workspace/reports/cross_scaffold_backend.md` 존재 확인.

---

## Phase 4: API 계약 갱신

백엔드 생성 완료 후 api_contract.json에 신규 엔드포인트 추가. 네임스페이스를 지정한 호출은 에이전트
지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을
지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 "`agents/api-bridge.md`의 지침을
읽고 그대로 따른다"를 명시한다.

```
Agent(
  subagent_type="ax-navi:api-bridge",
  description="API 계약 갱신 — [기능명] 엔드포인트 추가",
  prompt="mode: extract.
  프로젝트 루트: [backend_root].
  
  기존 [backend_root]/_workspace/index/api_contract.json을 읽어
  Phase 3에서 생성된 [METHOD /path] 엔드포인트를 추가 후 저장.
  (전체 재추출 불필요 — 신규 엔드포인트만 append)",
  model="sonnet"
)
```

---

## Phase 5: 클라이언트 스캐폴딩 (선택된 `frontend_targets` 전체 — 병렬)

`frontend_targets`의 각 항목에 대해 아래 Agent 호출을 **같은 메시지에서 병렬로** 발행한다
(1:1이면 항목이 1개라 사실상 기존과 동일하게 동작, 1:N이면 선택된 클라이언트 수만큼 동시 실행):

```
Agent(
  subagent_type="general-purpose",
  description="[target.label] 서비스+컴포넌트 생성 ([기능명])",
  prompt="다음 순서로 클라이언트 파일을 생성하라.

  클라이언트 루트: [target.root]
  백엔드 API 계약: [backend_root]/_workspace/index/api_contract.json
  대상 엔드포인트: [METHOD /path]
  기능명: [기능명]
  생성 범위: [프론트엔드 생성 범위]
  패턴 파일: [target.root]/.claude/patterns/
  분석 리포트: [target.root]/_workspace/01_analyzer_report.md (있으면)

  Step 1 — 서비스 스텁 생성 (api-bridge generate-stub 지침 따름):
    - 먼저 pattern_profile.py select로 대상 경로·모듈·레이어의 preferred 프로필과 실제 기준 파일 선택
    - api_contract.json의 [METHOD /path] 항목 기반
    - 요청/응답 DTO 타입은 api_contract.json의 models{} 정의(엔드포인트가 참조하는 모델의 필드·타입)를 실제로 읽어 채운다. models에 해당 모델이 있으면 필드를 // TODO로 남기지 말고 스텁 타입/인터페이스에 반영한다. models에 없을 때만 // TODO로 표시한다.
    - 클라이언트 스택(분석 리포트 또는 package.json)에 맞는 스타일 적용
    - 기존 서비스 파일 있으면 함수 추가, 없으면 도메인 기반 신규 생성
    - axios 인스턴스 경로는 패턴 파일 또는 기존 서비스 파일에서 확인

  Step 2 — 컴포넌트 생성 (범위에 포함된 경우):
    - [target.root]/.claude/patterns/ 의 컴포넌트 패턴 참조
    - Step 1의 서비스 함수를 호출하는 구조
    - UI 구현은 TODO로 (비즈니스 로직 골격만)
    - 파일명: 도메인 + 기능명 기반 (예: OrderCancelPage.vue, OrderCancelModal.tsx)

  Step 3 — 라우트 등록 (범위에 포함된 경우):
    - Vue Router: router/index.ts(js)에 route 객체 추가
    - React Router: routes 설정 파일에 추가
    - Next.js: pages/ 또는 app/ 아래 폴더/파일 생성
    - 모바일(예: iOS/Android 네이티브, React Native, Flutter)이면 해당 스택의 화면 등록 관행을 분석 리포트에서 확인 후 그에 맞게
    - 기존 파일 덮어쓰지 말고 항목만 추가

  결과를 [target.root]/_workspace/reports/cross_scaffold_frontend.md에 저장.",
  model="sonnet"
)
```

완료 후 각 `[target.root]/_workspace/reports/cross_scaffold_frontend.md` 존재 확인. 일부 실패해도 나머지는 계속 — 실패 목록은 Phase 7 보고에 명시.

---

## Phase 6: 통합 적합성·실행·안전성 검사

백엔드와 생성에 성공한 각 클라이언트에서 다음 순서를 독립적으로 실행한다:

1. `pattern-conformance`: 변경 파일, `pattern_selection.json`, 실제 `reference_files`를 대조해 `CONFORM/HOLD/FAIL` 판정
2. 해당 저장소의 실제 테스트·빌드·린트 명령 실행 — 명령과 exit code를 증거로 저장
3. `change-safety`: 위 두 결과와 diff를 입력으로 `GO/HOLD/STOP` 판정

검증 명령 미실행은 `UNVERIFIED`이며 최소 HOLD다. 패턴 FAIL 또는 검증 명령 실패는 STOP이다.

### API 계약 정합성 (선택된 `frontend_targets` 전체 — 병렬)

생성 완료 후 각 클라이언트마다 API 계약 정합성 확인 — Phase 5와 동일하게 대상 수만큼 병렬 발행:

```
Agent(
  subagent_type="ax-navi:api-bridge",
  description="[target.label] 크로스 리포 정합성 검증",
  prompt="mode: validate.
  프론트엔드 루트: [target.root].
  파트너 api_contract: [backend_root]/_workspace/index/api_contract.json.
  
  검증 범위: 방금 생성된 파일([target.root]/_workspace/reports/cross_scaffold_frontend.md 목록)만.
  출력: 콘솔 요약 (drift 없으면 '정합성 OK', 있으면 항목 나열). 파일 저장 불필요.",
  model="sonnet"
)
```

모든 저장소의 대상 어댑터가 FULL이고, 패턴 CONFORM, 필수 검증 exit 0, change-safety GO이며 모든 클라이언트의 API 드리프트가 0건일 때만 전체 GO다. 그 외에는 가장 낮은 판정을 사용한다. GO인 저장소는 analyzer incremental로 인덱스를 갱신한 뒤 `generate-wiki`를 실행해 구조화 패턴 표와 변경된 계약을 반영한다.

---

## Phase 7: 결과 보고

```
전체 스택 스캐폴딩 완료: [기능명]

━━━ 백엔드 ([backend_root]) ━━━
  Controller  : [파일 경로]
  Service     : [파일 경로]
  DAO/Mapper  : [파일 경로]
  DTO         : [파일 경로]
  Test        : [파일 경로]
  패턴 적합성: [CONFORM/HOLD/FAIL] — 기준 파일 [경로]
  실행 검증   : [명령] (exit [N])
  안전성      : [GO/HOLD/STOP]
  설정 변경   : [파일]: [추가 항목] (있으면)

━━━ 클라이언트 ([target.label] — [target.root]) ━━━ (frontend_targets 개수만큼 반복, 1:1이면 1개)
  Service 스텁: [파일 경로] → [함수명]()
  Component   : [파일 경로] (있으면)
  Route 등록  : [파일 경로] (있으면)
  정합성 검증 : ✓ / ✗ (드리프트 항목)
  패턴 적합성 : [CONFORM/HOLD/FAIL] — 기준 파일 [경로]
  실행 검증   : [명령] (exit [N])
  안전성      : [GO/HOLD/STOP]

━━━ API 계약 ━━━
  [METHOD /path] → api_contract.json 갱신 완료

⚠️  TODO (수동 완성 필요)
  [백엔드]
  - [Service 파일]: 비즈니스 로직 구현 (// TODO 위치)
  - [DAO 파일]: 실제 쿼리 작성
  [클라이언트별]
  - [Component 파일]: UI 구현 (// TODO 위치)
  - [Service 파일]: DTO 타입 — api_contract.json models에 있던 필드는 반영 완료, models에 없어 // TODO로 남은 필드만 백엔드 실제 필드 기준으로 보완

실패한 대상 (있으면): [target.label] — [실패 사유]

다음 단계:
  백엔드    → TODO 채우기 → 테스트 실행 → [빌드 명령]
  클라이언트 → UI 구현 → [개발 서버 명령]으로 확인
  통합      → 백엔드 실행 후 각 클라이언트에서 API 연동 테스트

전체 판정: [GO / HOLD / STOP]
```

---

## 원칙

### 계약 우선

프론트엔드 스텁은 **항상 백엔드 api_contract.json 기준**으로 생성.  
계약 없이 추측으로 URL·메서드 설정 금지.

### TODO 정직 표기

자동 생성된 비즈니스 로직·UI는 `// TODO` 로 명시. 가짜 구현으로 채우지 않는다.

### 충돌 자동 회피

기존 파일/메서드와 충돌 시 덮어쓰지 않고 사용자에게 확인.

### 단독 실행 불가 시 안내

pair_config.md 없이 실행 시 → pair-init 먼저 안내.  
`scaffold-feature`와 차이: scaffold-feature는 단일 레포 전용, cross-repo-scaffold는 페어 연동 필수.
