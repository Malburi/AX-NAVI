---
name: cross-repo-modify
description: 페어 연동된 백엔드·프론트엔드(1:1) 또는 백엔드+여러 클라이언트(1:N) 중 한쪽에서 지시한 기존 기능 개선/수정을, 필요 시 관련 저장소들에 함께 반영한다. "이 기능 개선해줘", "API 필드 추가해줘", "이거 고쳐야 하는데 프론트도 같이", "양쪽 다 수정해줘", "cross-repo modify", "풀스택 수정", "백엔드 프론트 둘 다 고쳐줘", "이 API 바꾸는데 프론트 영향 있으면 같이 처리해줘" 요청 시 트리거.
---

# Cross-Repo Modify (오케스트레이터)

`pair-init`으로 연동된 저장소들 중 **한쪽에서 시작한 기존 기능 개선/수정**이 API 계약에
영향을 주는 경우, 파트너(들) 저장소까지 함께 안전하게 반영한다. 1:1(파트너 1개)과 1:N(hub-roots,
클라이언트 여러 개 — 예: 백엔드+웹+모바일+관리자)을 모두 지원한다.

`cross-repo-scaffold`(신규 기능 동시 생성)와 달리 이 스킬은 **이미 존재하는 기능의 변경**을 다룬다.
`safe-modify`의 사전 영향 분석 → 적용 → 사후 안전성 흐름을 그대로 따르되, 각 단계에 파트너 저장소
분기를 추가한 것.

---

## Phase 0: 사전 조건 확인

시작 저장소와 후보 파트너에서 변경 대상별 `check-adapter-coverage.mjs`를 실행한다. PARTIAL/UNSUPPORTED 저장소는 스택별 빌드·UI·통합 검증을 명시적으로 확보하기 전 최소 HOLD이며, 결과를 각 change-safety 입력에 포함한다.

### 페어 설정 확인 및 대상 파트너 결정

`_workspace/pair_config.md` 존재 확인:
- 없으면 → "파트너 연동이 없습니다. 이 프로젝트만 수정하려면 `safe-modify`를 사용하세요. 양쪽 연동은 `pair-init`으로 먼저 설정하세요." 안내 후 중단.
- `## Partner:` 블록이 있으면 hub-roots(1:N), 없으면 기존 paired-roots(1:1) flat 형식.

**1:1인 경우** pair_config에서 `project_type`(현재 역할), `partner_type`, `partner_root`,
`partner_workspace`, `api_contract_path`, `partner_api_contract` 로드. `initiating_root` = 현재
프로젝트 루트. `modify_targets = [{ label: partner_type, root: partner_root, api_contract: partner_api_contract }]`
(1개짜리 리스트)로 통일해 이후 Phase에서 1:N과 같은 코드 경로를 쓴다.

**1:N(hub-roots)인 경우** `## Partner: <label>` 블록마다 파싱해 클라이언트 후보 목록을 만든다.
현재 프로젝트가 hub(backend)인지 클라이언트인지에 따라 동작이 다르다:

| 현재 프로젝트 | 동작 |
|------|------|
| hub(backend) 쪽에서 시작 | 등록된 클라이언트가 2개 이상이면 매번 체크리스트로 반영 대상을 묻는다 (아래) |
| 클라이언트 쪽에서 시작 | 클라이언트의 pair_config.md는 항상 1:1 flat 형식(파트너=hub 1개뿐)이므로 위 "1:1인 경우"와 동일하게 처리 |

hub 쪽에서 시작하고 클라이언트가 2개 이상이면:

```
등록된 클라이언트: [role_label 1], [role_label 2], [role_label 3], ...

이 변경을 반영할 후보로 확인할 클라이언트를 선택하세요 (쉼표로 구분, 전체는 "all"):
```

선택된 항목만 `modify_targets = [{ label, root: partner_root, api_contract: partner_api_contract }, ...]`에 담는다 (실제로 파일까지 고칠지는 Phase 2의 영향 확인 결과와 Phase 3 게이트에서 각 타깃별로 다시 결정 — 이 체크리스트는 "확인 후보"를 좁히는 것뿐).

`_workspace/wiki/architecture.md`(통합본, `generate-wiki`로 생성된 경우)가 있으면 먼저 훑어 시스템 전체 구조를
빠르게 파악하는 데 참고할 수 있다 — 단, 생성 시점 스냅샷이라 최신성이 보장되지 않으므로 실제 영향
분석·드리프트 검증은 반드시 아래 Phase 1/2/6의 라이브 재분석(`impact-analyzer`/`api-bridge`)으로 수행한다.

### 운영 모드 키워드 감지

safe-modify Phase 0과 동일한 키워드 표 적용 (`production`/`hotfix`/`legacy`/`customer_facing`/`normal`).
이후 양쪽 change-safety 호출 모두에 동일 mode 전달.

### 패턴 프로필 검증

시작 저장소와 후보 파트너 전부에서 `pattern_profile.py validate --root "[root]"`를 실행한다. 누락·실패 저장소는 pattern-extractor 재실행을 권고한다. 사용자가 계속 진행해도 그 저장소의 최종 판정은 최소 HOLD다.

---

## Phase 1: 시작 측 영향 분석

변경 대상이 명확하면 → `impact-analyzer`를 `initiating_root`에서 실행 (analyze-impact와 동일):
- 변경 대상 정규화 → 영향 리포트 `_workspace/reports/impact_<slug>.md`

리포트에서 변경 대상이 **API 엔드포인트/컨트롤러/DTO/서비스 계층 중 파트너 노출 대상**인지 판별:
- 해당하면 → Phase 2로.
- 순수 내부 로직(파트너 계약과 무관, 예: 프론트 전용 UI 스타일, 백엔드 전용 배치 잡)이면 → 파트너 영향 없음으로 판단, `safe-modify`와 동일하게 단독 진행 (Phase 4로 직행, Phase 2/3/5 스킵).

---

## Phase 2: 파트너(들) 영향 확인 — `modify_targets` 전체, 병렬

`modify_targets`의 각 항목에 대해 `api-bridge`를 `check-impact` 모드로 실행한다 (1:1이면 항목
1개라 기존과 동일하게 동작, 1:N이면 대상 수만큼 같은 메시지에서 병렬 발행). 네임스페이스를 지정한
호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인
네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 해당
`agents/<이름>.md`의 지침을 읽고 그대로 따르라고 명시한다.

```
Agent(
  subagent_type="ax-navi:api-bridge",
  description="[target.label] 영향 확인 — [변경 대상]",
  prompt="mode: check-impact.
  변경 엔드포인트/대상: [Phase 1에서 식별된 method+path 또는 DTO/함수].
  백엔드 루트: [backend_root]. 프론트엔드 루트: [target.root].
  출력: 콘솔 요약 (파트너 호출 위치·영향받는 컴포넌트 목록).",
  model="sonnet"
)
```

영향 있는 대상이 하나도 없으면(전부 호출 위치 0건) → 단독 진행 안내 후 Phase 4로.
영향 있는 대상이 하나라도 있으면 → Phase 3으로, 영향 없는 대상은 `modify_targets`에서 제외.

---

## Phase 3: 파트너(들) 반영 확인 게이트

파트너 저장소는 **별도 git/배포/리뷰 프로세스**를 가질 수 있으므로, 자동으로 파일을 고치기 전에 반드시 확인받는다. 영향 있는 대상이 여러 개(1:N)면 대상별로 나열한다:

```
이 변경은 아래 파트너 프로젝트(들)에도 영향을 줍니다:

[target 1.label] ([target 1.root])
  영향받는 파일/함수: N개
  - [파일:라인] — [함수명]

[target 2.label] ([target 2.root])   ← 영향 있는 대상마다 반복
  영향받는 파일/함수: M개
  - [파일:라인] — [함수명]

진행 옵션:
1. 전부 반영 (나열된 파트너 저장소 파일 전부 함께 수정 — 커밋은 하지 않음, 검토 후 각자 커밋)
2. 일부만 반영 (반영할 [label] 선택)
3. 이 프로젝트만 수정 (파트너(들)는 수동 안내만 출력)
4. 중단

선택? (1/2/3/4)
```

- 옵션 1·2 선택 시에도 **어느 저장소든 git commit은 절대 자동 실행하지 않는다** (기존 정책 그대로 — 파일 작성까지만).
- 옵션 2 선택 시 선택되지 않은 대상은 `modify_targets`에서 제외하고 이후 Phase는 남은 대상만 처리.
- CRITICAL 등급(Phase 1 impact 결과)이면 옵션 1·2 선택 시 추가로 "운영 영향도가 높습니다. 정말 진행할까요?" 재확인.
- **무응답·다른 주제로 전환·비대화형 호출이면 4.중단과 동일 처리한다** (기본값: 파트너 저장소 미반영). 파트너 저장소는 별도 프로세스이므로 명시적 선택 없이 자동 반영하지 않는다 — `split-repo.md`의 게이트 무응답 규칙과 동일 정책.

---

## Phase 4: 시작 측 변경 적용

`safe-modify` Phase 2와 동일:
- 변경 전에 `pattern_profile.py select`로 변경 경로·모듈·레이어에 맞는 preferred 프로필을 고르고 실제 `reference_files`를 읽는다.
- 사용자가 직접 작성하거나, 자연어 설명 → 어시스턴트가 Edit/Write로 적용.
- 적용 후 변경 파일 목록 수집.

변경이 API 계약 형태(엔드포인트 경로/메서드/DTO 필드)를 바꾸면, 적용 후 `api-bridge extract`로
`[backend_root]/_workspace/index/api_contract.json` 갱신 (신규 필드만 append, 전체 재추출 불필요).

---

## Phase 5: 파트너(들) 측 변경 적용 (Phase 3에서 옵션 1·2 선택 시, 남은 `modify_targets` 전체 — 병렬)

`modify_targets`의 각 항목에 대해 아래 Agent 호출을 같은 메시지에서 병렬로 발행한다 (1:1이면
항목 1개라 기존과 동일하게 동작):

```
Agent(
  subagent_type="general-purpose",
  description="[target.label] 저장소 반영 — [변경 대상]",
  prompt="safe-modify 스킬의 Phase 2(변경 적용) 지침만 수행한다 (사전/사후 안전성 평가는 이 오케스트레이터의
  Phase 6에서 통합 실행하므로 생략).

  프로젝트 루트: [target.root]
  변경 배경: [initiating_root]에서 [변경 대상]이 다음과 같이 바뀜: [Phase 4 변경 요약]
  갱신된 API 계약: [backend_root]/_workspace/index/api_contract.json
  영향받는 파트너 파일: [Phase 2 check-impact 결과 목록 — target.label 것만]
  구조화 패턴: [target.root]/.claude/patterns/pattern_profile.json

  변경 방식:
  - 변경 전 pattern_profile.py select로 대상별 preferred 프로필을 선택하고 reference_files를 직접 읽어 동일 패턴 적용
  - 백엔드 계약 변경(필드 추가/제거, 경로 변경)에 맞춰 클라이언트 서비스 함수·타입 정의 수정, 또는
  - 클라이언트 요구사항 변경에 맞춰 백엔드 컨트롤러/서비스/DTO 수정
  - TODO로 남길 부분은 명시적으로 // TODO 표기 (cross-repo-scaffold 원칙과 동일)
  - git commit 금지 — 파일 작성까지만

  결과를 [target.root]/_workspace/reports/cross_modify_partner.md에 저장.",
  model="sonnet"
)
```

완료 후 각 `[target.root]/_workspace/reports/cross_modify_partner.md` 존재 확인. 일부 대상이 실패해도 나머지는 계속 진행 — 실패 목록은 Phase 7 보고에 명시.

---

## Phase 6: 통합 패턴·실행·안전성 평가 + 드리프트 재검증

시작 측과 Phase 5가 실행된 각 파트너에서 먼저 `pattern-conformance`를 실행한다. 이어서 각 저장소에서 실제 테스트·빌드·린트 명령을 실행하고 명령·exit code·핵심 출력을 수집한다. 이 두 증거를 아래 change-safety 입력에 반드시 포함한다. 미실행(`UNVERIFIED`)은 최소 HOLD, 패턴 FAIL 또는 필수 명령 실패는 STOP이다.

### change-safety (시작 측 + 반영된 파트너(들) 전부, 같은 메시지에서 병렬)

시작 측:
```
Agent(
  subagent_type="ax-navi:change-safety",
  description="변경 안전성 평가 (시작 측)",
  prompt="<변경 파일: [Phase 4 목록]. mode: [Phase 0 감지 모드]. impact 리포트: _workspace/reports/impact_<slug>.md. 패턴 판정: _workspace/reports/pattern_conformance_<slug>.md. 실행 검증: [명령/exit code/핵심 출력]. 출력: _workspace/reports/safety_<slug>.md>",
  model="sonnet"
)
```

`modify_targets`마다(Phase 5 실행된 대상만), 시작 측 호출과 같은 메시지에서 전부 병렬(서로 독립적인 평가 대상):
```
Agent(
  subagent_type="ax-navi:change-safety",
  description="[target.label] 변경 안전성 평가",
  prompt="<프로젝트 루트: [target.root]. 변경 파일: [target.root]/_workspace/reports/cross_modify_partner.md 목록. mode: [Phase 0 감지 모드]. 패턴 판정: [target.root]/_workspace/reports/pattern_conformance_<slug>.md. 실행 검증: [명령/exit code/핵심 출력]. 출력: [target.root]/_workspace/reports/safety_<slug>.md>",
  model="sonnet"
)
```

모든 대상 어댑터가 FULL이고, 패턴 CONFORM, 필수 검증 exit 0, change-safety GO이며 API 드리프트가 0건일 때만 전체 GO다. GO인 각 저장소는 analyzer incremental로 인덱스를 갱신한 후 `generate-wiki`를 실행한다.

### API 드리프트 재검증 (Phase 5 실행된 대상마다, 병렬)

```
Agent(
  subagent_type="ax-navi:api-bridge",
  description="[target.label] 크로스 리포 드리프트 재검증",
  prompt="mode: validate.
  프론트엔드 루트: [target.root].
  파트너 api_contract: [backend_root]/_workspace/index/api_contract.json.
  검증 범위: 방금 수정된 파일만.
  출력: 콘솔 요약.",
  model="sonnet"
)
```

---

## Phase 7: 결과 보고

```
크로스 리포 수정 완료: [변경 대상]

━━━ [initiating_root 역할] ([initiating_root]) ━━━
  변경 파일: [목록]
  패턴 적합성: [CONFORM/HOLD/FAIL] — 기준 파일 [경로]
  실행 검증: [명령] (exit [N])
  안전성: [GO/HOLD/STOP] (종합 X/10)

━━━ [target.label] ([target.root]) ━━━ (Phase 5 실행된 대상마다 반복 — 1:1이면 1개, 1:N이면 반영된 클라이언트 수만큼)
  변경 파일: [목록]
  패턴 적합성: [CONFORM/HOLD/FAIL] — 기준 파일 [경로]
  실행 검증: [명령] (exit [N])
  안전성: [GO/HOLD/STOP] (종합 X/10)
  드리프트 재검증: [✓ 일치 / N건 발견]
  ⚠️ TODO: [cross_modify_partner.md에 명시된 항목]

실패한 대상 (있으면): [target.label] — [실패 사유]

결정: [GO / HOLD / STOP] (전체 대상 중 가장 낮은 등급 기준)

[GO]
다음 단계:
  [initiating 측] → 영향 테스트 실행 → commit
  [반영된 대상마다] → TODO 완성 → 자체 리뷰 → commit
  (각 저장소는 별도 PR/커밋 필요 — 이 스킬은 파일만 준비함)

[HOLD/STOP]
보완 필요 항목: [safety report 요약]
```

---

## 원칙

### 파트너 저장소는 남의 저장소다

Phase 3 확인 없이 파트너 파일을 고치지 않는다. 커밋도 절대 자동으로 하지 않는다 — 별도 git/배포
프로세스라는 전제(사용자가 명시한 구조) 때문에, 파트너 팀의 리뷰 흐름을 우회해서는 안 된다.

### 계약 우선, 추측 금지

파트너 측 변경은 항상 `api_contract.json` 갱신 이후, 갱신된 계약 기준으로 생성한다.

### 단독 실행 경로

파트너 영향이 없거나 사용자가 "이 프로젝트만"을 선택하면 사실상 `safe-modify`와 동일하게 동작한다 —
이 스킬은 safe-modify 위에 파트너 분기를 얹은 것이지 대체하는 것이 아니다.

### pair_config.md 없이 실행 불가

`cross-repo-scaffold`와 동일하게 페어 연동이 전제 조건이다.
