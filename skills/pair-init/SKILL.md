---
name: pair-init
description: 별도 저장소로 분리된 백엔드·프론트엔드(1:1) 또는 백엔드+여러 클라이언트(1:N, 예: 백엔드+웹+모바일+관리자) 프로젝트를 연동한다. "백엔드 프론트엔드 연결해줘", "페어 설정", "pair init", "두 프로젝트 연동", "백엔드랑 프론트 같이 분석해줘", "API 계약 추출해줘", "크로스리포 설정", "파트너 프로젝트 등록", "모바일도 추가해줘", "클라이언트 여러 개 연동", "허브형 연동" 요청 시 트리거.
---

# Pair Init (오케스트레이터)

분리된 저장소를 하네스 레벨에서 연동해 *교차 참조·전체 스택 스캐폴딩·API 드리프트 감지*를 활성화한다.
1:1(백엔드+프론트엔드 1개)과 1:N(백엔드+클라이언트 여러 개, 예: 웹+모바일+관리자)을 모두 지원한다.

연동 후 모든 연동 프로젝트 어디서나 `cross-repo-scaffold`로 전체 스택 기능을 동시 생성하고,
`analyze-impact`가 API 계약 변경 시 파트너(들) 영향을 자동으로 포함한다.

---

## Phase 0: 사전 확인 및 모드 판단

### 현재 프로젝트 확인

`pwd`로 현재 루트 파악. `_workspace/pair_config.md` 존재 확인.

### 하네스 존재 확인

`CLAUDE.md` + `.claude/` 존재 확인:
- 없으면 → "먼저 `harness-init`으로 현재 프로젝트 하네스를 생성한 뒤 실행하세요" 안내 후 중단.

### 모드 판단

| 상황 | 판단 |
|------|------|
| harness-init의 `P-PAIR`에서 `partner_info`/`partner_list` + `entry_point: "P-PAIR"`와 함께 호출됨 | 양쪽 하네스가 이미 대칭 2-레인으로 생성·검증된 상태(barrier 통과) — Phase 0/1(정보 수집·하네스 확인·자동 생성 3지선다) 전부 건너뛰고 **Phase 2로 직행** |
| harness-init에서 `partner_info`(단일 dict)와 함께, `entry_point` 없이 호출됨(구버전 호환) | 1:1 모드, Phase 1(1:1)로 — 질문 생략 |
| harness-init에서 `partner_list`(N개 리스트)와 함께, `entry_point` 없이 호출됨(구버전 호환) | 1:N 모드, Phase 1(1:N)로 — 질문 생략 |
| `pair_config.md` 없음, 위 컨텍스트도 없음 (사용자가 직접 호출) | "몇 개 프로젝트를 연동하나요? (1 = 1:1, 2개 이상 = 1:N)" 질문 후 해당 Phase 1로 |
| `pair_config.md`가 기존 1:1(flat) 형식 | 현재 설정(파트너 1개) 보여주고 "재설정 / 새 클라이언트 추가해서 1:N으로 전환" 확인 |
| `pair_config.md`가 기존 hub-roots(1:N, `## Partner:` 블록) 형식 | 현재 설정(클라이언트 목록) 보여주고 "새 클라이언트 추가 / 특정 클라이언트 재설정 / 전체 재설정" 3지선다 |

> `entry_point: "P-PAIR"`는 harness-init의 `references/split-repo.md` "Phase 3.5" 절 P-PAIR 호출에서만 쓰는 값이다 — Phase 1-A/1-B(정보 수집·하네스 존재 확인·3지선다)를 통째로 건너뛰는 유일한 경로이므로, standalone 호출이나 이전 버전 호환 경로와 혼동하지 않도록 이 값이 있을 때만 적용한다.

### 기존 hub-roots 설정 발견 시 3지선다

```
기존 클라이언트 연동이 있습니다: [role_label 목록]

1. 새 클라이언트 추가 — 기존 목록은 그대로 두고 1개 더 연동
2. 특정 클라이언트 재설정 — 목록에서 골라 그 정보만 다시 입력
3. 전체 재설정 — 전부 지우고 처음부터 다시 수집

선택? (1/2/3)
```

| 선택 | 동작 |
|------|------|
| 1 | Phase 1(1:N)의 "신규 클라이언트 1개 추가" 흐름으로 — 기존 `pair_config.md`에 `## Partner:` 블록 하나만 추가 |
| 2 | 재설정할 role_label 확인 후 Phase 1(1:N)의 해당 항목만 재수집 — 같은 블록을 덮어씀 |
| 3 | 기존 `pair_config.md` 백업 없이 덮어씀(사용자가 방금 "전체 재설정" 선택) — Phase 1(1:N) 처음부터 |

---

## Phase 1-A: 프로젝트 쌍 정보 수집 (1:1)

사용자에게 다음 질문 (한 번에 묻기):

```
페어 설정에 필요한 정보를 입력해주세요:

1. 현재 프로젝트 역할: backend / frontend
2. 파트너 프로젝트 절대 경로:
   (예: C:\work\my-frontend 또는 /home/user/my-frontend)
3. API base URL (로컬 개발 기준):
   (예: http://localhost:8080)
4. (선택) 파트너 스택: (예: Vue 3, React, Angular — 모르면 빈칸)
```

harness-init에서 `partner_info`와 함께 호출된 경우 이 질문 생략, 값 그대로 사용.

### 파트너 경로 유효성 확인

PowerShell: `Test-Path "[파트너 경로]"` 또는 bash: `[ -d "[파트너 경로]" ]`

- 경로 없음 → "경로를 확인해주세요" 안내 후 재입력 요청.
- 파트너에 `CLAUDE.md` 없음 → 다음 3개 선택지 제시:

```
파트너 프로젝트([파트너 경로])에 하네스가 없습니다.

1. 자동으로 파트너 하네스 생성 (권장) — subagent가 파트너 루트에서 harness-init을 대신 실행합니다.
2. 하네스 없이 진행 — API 계약 추출만 하고 드리프트 검증(validate)은 스킵합니다.
3. 중단 — 파트너 프로젝트에서 직접 harness-init 실행 후 재시도하세요.

선택? (1/2/3)
```

| 선택 | 동작 |
|------|------|
| 1 | 아래 "파트너 하네스 자동 생성" 실행 후 Phase 2-A로 진행 |
| 2 | API 계약 추출만 하고 validate 스킵 (기존 동작) |
| 3 | 중단 |

이 3지선다는 **pair-init을 standalone으로 호출한 경우에만** 나온다 — harness-init이 주도하는 흐름에서는 Phase 1-A 자체를 건너뛰므로(아래 "파트너 하네스 자동 생성" 절 상단 안내 참조) 이 질문에 도달하지 않는다.

### 파트너 하네스 자동 생성 (선택 1)

> 이 서브스텝은 **pair-init을 사용자가 직접(standalone) 호출한 경우에만** 쓰인다. harness-init이 주도하는 흐름(Phase -1에서 멀티레포로 확인된 경우)에서는 harness-init 자체의 Phase 1/2가 자기 쪽과 파트너 쪽을 대칭 레인(`B-I→B-A→B-W→B-P→B-V` / `C-I→C-A→C-W→C-P→C-V`)으로 직접 지휘해 양쪽 하네스와 패턴 프로필을 함께 만들고, `P-BARRIER`를 거친 뒤에야 이 pair-init(Phase 2부터)을 호출한다 — 그 흐름에서는 이 서브스텝을 호출하지 않는다(harness-init `references/split-repo.md`의 "Phase 1: 작업 그래프"·"Phase 3.5" 절 참조).

파트너 루트에서 harness-init을 subagent로 대신 실행한다(standalone 호출 시):

```
Agent(
  subagent_type="general-purpose",
  description="파트너 하네스 자동 생성 ([파트너 경로])",
  prompt="skills/harness-init/SKILL.md 파일을 읽고 그 지침을 그대로 따라 harness-init을 수행하라.
  프로젝트 루트: [파트너 절대경로] (cwd 아님 — 이 경로 기준으로 모든 파일 읽기/쓰기 수행).
  init_layout: 'paired-roots' (멀티레포 확정 상태 — Phase -1 구성 확인 재질문 불필요, source: explicit-request로 기록).
  partner_info: { role: '[현재 프로젝트 역할과 반대]', path: '[현재 프로젝트 절대경로]', api_url: '[api_base_url]' }.
  Phase -1은 위 init_layout/partner_info로 이미 충족되었으므로 구성 확인 질문 없이 Phase 0으로 직행.
  Phase 0 Step 2.5(Tier 확인) 질문도 이 호출에는 응답할 사용자가 없으므로 묻지 말고 override 키워드 '심층'과 동일하게 처리해 Full로 확정하고 진행(기존 harness-init 로직의 무응답 시 기본값과 동일).
  Phase 3.5(pair-init)는 이미 호출 중인 pair-init 상위 흐름과 중복이므로 스킵한다. Phase 3.6의 선택 작업 메뉴는 사용자가 없으므로 '3. 지금 안 함'으로 처리한다 — wiki도 QA도 실행하지 않고 Phase 4로 진행한다(파트너 wiki가 필요하면 연동 완료 후 그 저장소에서 generate-wiki를 따로 실행한다).
  완료 후 결과를 [파트너 절대경로]/_workspace/06_eval_report.md 및 CLAUDE.md 존재 여부로 보고하라.",
  model="opus"
)
```

- standalone 호출 시, 현재 진행 중인 다른 작업이 있다면 이 Agent 호출을 그와 병렬로 실행해도 된다.
- 완료 후 파트너 `CLAUDE.md` 존재 확인. 실패 시 → WARN 후 선택지 2(하네스 없이 진행)로 폴백.

---

## Phase 1-B: 클라이언트 목록 정보 수집 (1:N)

현재 프로젝트는 항상 `backend`(hub) 역할로 취급한다.

harness-init에서 `partner_list`(N개)와 함께 호출된 경우 아래 질문 전부 생략, 값 그대로 사용.
사용자가 직접 호출했고(모드 판단에서 "2개 이상" 응답), 신규 연동이면:

```
클라이언트 프로젝트가 몇 개인가요? (2개 이상)
```

개수만큼 반복:

```
클라이언트 [i/N] 정보를 입력해주세요:

1. 역할 라벨 (예: web-frontend, mobile-ios, mobile-android, admin-panel — 자유 입력, 다른 클라이언트와 겹치지 않게)
2. 절대 경로:
3. API base URL (선택 — 미입력 시 1번 클라이언트와 동일하다고 가정):
4. (선택) 스택 (예: React, Flutter, Swift — 모르면 빈칸)
```

Phase 0에서 "새 클라이언트 추가"를 선택한 경우 위 질문을 **1개 클라이언트분만** 반복(개수 질문 생략).
"특정 클라이언트 재설정"인 경우도 그 1개 클라이언트분만 재입력.

수집 결과를 `client_list = [{ role_label, path, api_url, stack }, ...]`에 저장.

### 클라이언트별 경로 유효성 확인 및 하네스 확인 (순회)

`client_list`의 각 항목에 대해 Phase 1-A와 동일한 확인을 반복한다:
- 경로 없음 → 그 클라이언트만 재입력 요청 (다른 클라이언트는 그대로 진행).
- `CLAUDE.md` 없음 → Phase 1-A와 동일한 3지선다(단, harness-init 주도 흐름이면 이 3지선다 자체를 pair-init이 묻지 않는다 — harness-init이 이미 대칭 2-레인으로 클라이언트별 하네스를 만들고 P-BARRIER를 거친 뒤 이 스킬은 Phase 2부터 호출되므로, 이 시점엔 모든 클라이언트가 이미 하네스를 갖고 있다).

### 하네스 없는 클라이언트 자동 생성 (선택 1, 순회) — 병렬 실행 (standalone 호출 시)

pair-init을 사용자가 직접 호출한 경우에만 해당(Phase 1-A 상단 안내 참조). 하네스가 없어 자동 생성이 필요한 클라이언트가 M개면, Phase 1-A의 "파트너 하네스 자동 생성" Agent 호출을 **클라이언트 M개 각각에 대해 같은 메시지에서 병렬로** 발행한다 (`role: '[역할 라벨]'`로 대체, `init_layout: 'paired-roots'`는 각 클라이언트 입장에서는 자신+hub 단둘의 1:1 관계이므로 그대로 사용 — 클라이언트 쪽 harness는 hub-roots를 모른다).

M개 전부 반환된 후 다음으로 진행. 일부 실패해도 나머지는 계속 — 실패한 클라이언트만 선택지 2(하네스 없이 진행)로 폴백.

---

## Phase 2-A: pair_config.md 생성 (1:1)

### 현재 프로젝트에 생성

`_workspace/` 없으면 생성 후 `_workspace/pair_config.md` 작성:

```markdown
# Pair Configuration

project_type: [backend/frontend]
partner_type: [frontend/backend]
partner_root: [절대경로]
partner_workspace: [절대경로/_workspace]
partner_stack: [프론트엔드/백엔드 스택 — 미입력 시 unknown]
api_base_url: [http://localhost:8080]
api_contract_path: _workspace/index/api_contract.json
partner_api_contract: [파트너 절대경로]/_workspace/index/api_contract.json
linked_at: [YYYY-MM-DD]
```

### 파트너 프로젝트에도 생성 (역방향)

파트너 `_workspace/` 없으면 생성 후 역방향 내용으로 `pair_config.md` 작성.
파트너 접근 불가 시 WARN 후 스킵 (현재 프로젝트 설정만 진행).

---

## Phase 2-B: pair_config.md 생성 (1:N)

### hub(현재 프로젝트)에 생성 — 다중 블록 형식

`_workspace/` 없으면 생성 후 `_workspace/pair_config.md`를 아래 형식으로 작성 (기존 1:1 flat 형식과
다른 신규 형식 — `## Partner: <role_label>` 블록을 클라이언트 수만큼 반복):

```markdown
# Pair Configuration

project_type: backend
init_mode: hub-roots
linked_at: [YYYY-MM-DD]

## Partner: [role_label 1]
partner_role_label: [role_label 1]
partner_type: frontend
partner_root: [절대경로 1]
partner_workspace: [절대경로 1]/_workspace
partner_stack: [스택 1 — 미입력 시 unknown]
api_base_url: [api_url 1]
api_contract_path: _workspace/index/api_contract.json
partner_api_contract: [절대경로 1]/_workspace/index/api_contract.json

## Partner: [role_label 2]
partner_role_label: [role_label 2]
partner_type: frontend
partner_root: [절대경로 2]
partner_workspace: [절대경로 2]/_workspace
partner_stack: [스택 2]
api_base_url: [api_url 2]
api_contract_path: _workspace/index/api_contract.json
partner_api_contract: [절대경로 2]/_workspace/index/api_contract.json

... (client_list 개수만큼 반복)
```

"새 클라이언트 추가"인 경우 기존 파일 맨 끝에 `## Partner:` 블록 하나만 덧붙인다(다른 블록은
건드리지 않음). "특정 클라이언트 재설정"인 경우 그 role_label의 블록만 통째로 교체한다.

### 각 클라이언트 쪽에는 기존 1:1 형식 그대로 생성 (역방향)

각 클라이언트 입장에서는 파트너가 hub 1개뿐이므로, Phase 2-A와 완전히 동일한 flat 형식으로
생성한다 (`project_type: frontend`, `partner_type: backend`, `partner_root: [hub 절대경로]`, ...).
**클라이언트 쪽 pair_config.md·CLAUDE.md·wiki 관련 코드는 이 문서를 hub-roots로 인식할 필요가
전혀 없다** — hub-roots 인식은 hub(backend) 쪽에서만 필요하다.

클라이언트 접근 불가 시 WARN 후 해당 클라이언트만 스킵 (다른 클라이언트·hub 설정은 계속 진행).

---

## Phase 3: API 계약 추출 (백엔드 프로젝트)

1:1/1:N 공통 — 백엔드는 항상 1개이므로 변경 없음. 백엔드 루트(현재 또는 파트너)에서
`api-bridge`를 `extract` 모드로 실행. 네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로
프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는
`general-purpose`로 폴백하되 프롬프트에 "`agents/api-bridge.md`의 지침을 읽고 그대로 따른다"를 명시한다.

```
Agent(
  subagent_type="total-ito:api-bridge",
  description="백엔드 API 계약 추출",
  prompt="mode: extract.
  프로젝트 루트: [백엔드 절대경로].
  출력: [백엔드 절대경로]/_workspace/index/api_contract.json.

  _workspace/index/ 폴더가 없으면 생성 후 작성.",
  model="sonnet"
)
```

완료 후 `api_contract.json` 존재 확인. 생성 실패 시 → "API 계약 추출 실패 — 수동으로 `api-bridge extract` 호출 가능" WARN 후 계속.

이 계약 하나를 모든 클라이언트(1:N인 경우 N개 전부)가 공유해서 참조한다.

---

## Phase 4-A: API 드리프트 검증 (1:1, 프론트엔드 하네스 있는 경우)

파트너 `CLAUDE.md`가 있고 Phase 3이 성공한 경우에만 실행:

```
Agent(
  subagent_type="total-ito:api-bridge",
  description="프론트엔드 API 드리프트 검증",
  prompt="mode: validate.
  프론트엔드 루트: [프론트엔드 절대경로].
  파트너 api_contract: [백엔드 절대경로]/_workspace/index/api_contract.json.
  출력: [프론트엔드 절대경로]/_workspace/reports/api_drift_report.md.",
  model="sonnet"
)
```

파트너 하네스 없으면 Phase 4-A 스킵 (Phase 5로 직행).

---

## Phase 4-B: API 드리프트 검증 (1:N, 클라이언트별 순회 — 병렬)

Phase 4-A와 동일한 Agent 호출을 **하네스 있는 클라이언트 전부에 대해 같은 메시지에서 병렬로**
발행한다 (`프론트엔드 루트`만 클라이언트마다 다르게, `파트너 api_contract`는 전부 동일한 hub의
`api_contract.json`을 가리킴). 하네스 없는 클라이언트는 검증에서 제외.

각 클라이언트의 결과는 그 클라이언트 루트의 `_workspace/reports/api_drift_report.md`에 개별 저장된다
(공유 파일 아님 — 클라이언트마다 자기 드리프트만 본다).

---

## Phase 5-A: CLAUDE.md 파트너 섹션 추가 (1:1)

양쪽 프로젝트의 `CLAUDE.md`에 "## 파트너 프로젝트" 섹션을 추가/갱신한다.

### 백엔드 CLAUDE.md에 추가

```markdown
## 파트너 프로젝트 (프론트엔드)

- 파트너 경로: [절대경로]
- 스택: [프론트엔드 스택]
- API 계약: `_workspace/index/api_contract.json` ([엔드포인트 수]개)
- 연동일: [YYYY-MM-DD]

### 크로스 리포 워크플로우
| 상황 | 명령 |
|------|------|
| 전체 스택 기능 동시 생성 | "전체 스택 기능 만들어줘" → cross-repo-scaffold |
| 기존 기능 개선/수정 양쪽 반영 | "이 기능 개선해줘 (프론트도 같이)" → cross-repo-modify |
| API 변경 전 프론트 영향 확인 | "영향도 분석해줘" → analyze-impact (파트너 영향 자동 포함) |
| 프론트 서비스 스텁만 생성 | "프론트 스텁 만들어줘" → api-bridge generate-stub |
| API 드리프트 재확인 | "API 드리프트 확인해줘" → pair-init 재실행 |
| API 계약 갱신 | 코드 변경 후 "API 계약 갱신해줘" → api-bridge extract |
```

### 프론트엔드 CLAUDE.md에 추가

```markdown
## 파트너 프로젝트 (백엔드)

- 파트너 경로: [절대경로]
- 스택: [백엔드 스택]
- API 계약 위치: `[백엔드 절대경로]/_workspace/index/api_contract.json`
- 연동일: [YYYY-MM-DD]

### 크로스 리포 워크플로우
| 상황 | 명령 |
|------|------|
| 전체 스택 기능 동시 생성 | "전체 스택 기능 만들어줘" → cross-repo-scaffold |
| 기존 기능 개선/수정 양쪽 반영 | "이 기능 개선해줘 (백엔드도 같이)" → cross-repo-modify |
| 사용 가능한 API 목록 확인 | "API 목록 보여줘" → api-bridge extract (재읽기) |
| 드리프트 감지 | "API 드리프트 확인해줘" → pair-init 재실행 |
```

---

## Phase 5-B: CLAUDE.md 파트너 섹션 추가 (1:N)

### hub(백엔드) CLAUDE.md — 클라이언트 목록 형식

```markdown
## 파트너 프로젝트들 (클라이언트 [N]개)

| 역할 라벨 | 경로 | 스택 | 드리프트 |
|---|---|---|---|
| [role_label 1] | [절대경로 1] | [스택 1] | [🟢 없음 / 🟡 N건 / 하네스 없어 미검증] |
| [role_label 2] | [절대경로 2] | [스택 2] | ... |

- API 계약: `_workspace/index/api_contract.json` ([엔드포인트 수]개, 클라이언트 전체가 공유)
- 연동일: [YYYY-MM-DD]

### 크로스 리포 워크플로우
| 상황 | 명령 |
|------|------|
| 전체 스택 기능 동시 생성 (클라이언트 선택) | "전체 스택 기능 만들어줘" → cross-repo-scaffold (포함할 클라이언트 체크리스트 질문) |
| 기존 기능 개선/수정 (클라이언트 선택) | "이 기능 개선해줘" → cross-repo-modify (포함할 클라이언트 체크리스트 질문) |
| API 변경 전 클라이언트 영향 확인 | "영향도 분석해줘" → analyze-impact (등록된 클라이언트 전체 영향 자동 포함) |
| 특정 클라이언트 서비스 스텁만 생성 | "[role_label] 스텁 만들어줘" → api-bridge generate-stub |
| API 드리프트 재확인 (전체) | "API 드리프트 확인해줘" → pair-init 재실행 |
| 클라이언트 추가 | "[새 역할] 클라이언트 추가해줘" → pair-init 재실행 |
```

### 각 클라이언트 CLAUDE.md — 기존 1:1 형식 그대로

Phase 5-A의 "프론트엔드 CLAUDE.md에 추가" 템플릿을 그대로 사용한다 (클라이언트는 파트너가 hub
1개뿐이므로 1:N을 인식할 필요가 없음).

---

## Phase 6: 결과 보고

### 1:1

```
페어 설정 완료

백엔드:    [경로] ([스택])
프론트엔드: [경로] ([스택])
API base:  [url]

API 계약 추출: [성공/실패]
  엔드포인트: N개 (공개 A개 | 인증 B개)
  저장: [백엔드]/_workspace/index/api_contract.json

API 드리프트 검증: [실행됨/스킵]
  🔴 MISSING: N건
  🟡 MISMATCH: N건
  🟢 UNUSED: N건
  상세: [프론트엔드]/_workspace/reports/api_drift_report.md

이제 가능한 작업:
  "주문 취소 기능 전체 만들어줘"  →  cross-repo-scaffold (백엔드+프론트 동시)
  "이 API 수정 영향 분석해줘"      →  analyze-impact (파트너 영향 자동 포함)
  "API 드리프트 다시 확인"          →  pair-init 재실행

양쪽 프로젝트 어디서나 "전체 스택 기능 만들어줘"로 cross-repo-scaffold를 실행할 수 있습니다.
```

### 1:N

```
페어 설정 완료 (허브형, 클라이언트 N개)

백엔드(hub): [경로] ([스택])
API base:    [url]

API 계약 추출: [성공/실패]
  엔드포인트: N개 (공개 A개 | 인증 B개)
  저장: [백엔드]/_workspace/index/api_contract.json

클라이언트별 결과:
| 역할 라벨 | 경로 | 하네스 | 드리프트 검증 |
|---|---|---|---|
| [role_label 1] | [경로] | ✅/자동생성됨/❌ | 🟢 없음 / 🟡 N건 / ⏭ 스킵 |
| [role_label 2] | ... | ... | ... |

이제 가능한 작업:
  "주문 취소 기능 전체 만들어줘"     →  cross-repo-scaffold (포함할 클라이언트 물어봄)
  "이 API 수정 영향 분석해줘"        →  analyze-impact (등록된 클라이언트 전체 영향 자동 포함)
  "API 드리프트 다시 확인"           →  pair-init 재실행
  "[새 역할] 클라이언트 추가해줘"    →  pair-init 재실행 (기존 목록 유지, 1개만 추가)

hub·모든 클라이언트 프로젝트 어디서나 "전체 스택 기능 만들어줘"로 cross-repo-scaffold를 실행할 수 있습니다.
```

HIGH 드리프트가 있으면 "즉시 수정 권장" 항목 명시.

---

## 에러 핸들링

| 상황 | 대응 |
|------|------|
| 파트너/클라이언트 경로 접근 불가 | 그 파트너·클라이언트 설정만 스킵, 나머지는 계속 진행 (1:N에서 특히 중요) |
| api-bridge extract 실패 | WARN 기록, 나머지 Phase 계속 진행 |
| 파트너·클라이언트 CLAUDE.md 수정 권한 없음 | 현재 프로젝트 CLAUDE.md만 수정, 해당 쪽은 수동 안내 |
| pair_config.md 이미 있음 | 덮어쓰기 전 사용자 확인 (1:N은 Phase 0의 3지선다로 대체) |
| 파트너·클라이언트 하네스 자동 생성(선택 1) 실패 | 그 파트너·클라이언트만 WARN 후 선택지 2(하네스 없이 진행)로 폴백, 나머지는 계속 |
| hub-roots에서 클라이언트가 1개뿐 | 진행은 하되 "1개면 1:1(`paired-roots`)이 더 단순합니다" 안내만 (강제 전환 안 함) |
