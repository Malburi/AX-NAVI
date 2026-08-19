# 분리 저장소 초기화 (paired-roots · hub-roots)

`harness-init` 오케스트레이터가 **`init_layout`이 `paired-roots` 또는 `hub-roots`일 때만** 읽는 참조 문서다.
`single-root`·`monorepo`·`selected-paths`는 이 파일을 읽을 필요가 없다 — `SKILL.md`만으로 완결된다.

여기 담긴 것은 파트너 정보 수집, 레인 상태 파일, 대칭 2-레인 작업 그래프, 레인 실행 방식,
그리고 양쪽이 끝난 뒤의 P-BARRIER → P-PAIR → P-REFRESH다. Phase 0~2-5의 각 단계 절차 자체는
`SKILL.md`에 있는 것을 그대로 쓰며, 달라지는 것은 "그 절차를 자기 자신뿐 아니라 파트너 경로에도
병렬로 적용하고 끝나면 barrier로 합류한다"는 오케스트레이션 층위뿐이다.

`references/`의 경로는 이 스킬 디렉터리 기준이다(스킬 로드 시 안내되는 base directory).

---

## Phase -1: 파트너 정보 수집

### `paired-roots` — 파트너 1개

연속해서 파트너 정보를 입력받는다:

```
파트너 프로젝트 정보를 입력해주세요:

1. 현재 프로젝트 역할: backend / frontend / fullstack
2. 파트너 프로젝트 절대 경로:
   (예: C:\work\my-frontend 또는 /home/user/my-frontend)
3. API base URL (선택 — 로컬 개발 기준):
   (예: http://localhost:8080 — 모르면 빈칸)
```

입력받은 정보를 `partner_info = { role, path, api_url }` 변수에 저장.  
경로 유효성 확인 및 파트너 하네스 존재 여부는 pair-init Phase 1에서 수행.

> 수집한 `partner_info`는 Phase 3.5에서 pair-init 자동 실행 시 컨텍스트로 전달된다.

### 허브형(`hub-roots`) 파트너 목록 수집 (N개)

현재 프로젝트는 항상 hub(backend류) 역할로 취급한다 — hub-roots는 "1개 중심 + N개 클라이언트"
구조이기 때문이다 (현재 프로젝트가 클라이언트 중 하나라면 3번 `paired-roots`로 그 백엔드 하나와만
먼저 연결하거나, 백엔드 쪽 루트에서 harness-init을 실행하도록 안내).

```
클라이언트 프로젝트가 몇 개인가요? (2개 이상)
```

응답받은 개수만큼 아래 질문을 반복한다:

```
클라이언트 [i/N] 정보를 입력해주세요:

1. 역할 라벨 (예: web-frontend, mobile-ios, mobile-android, admin-panel — 자유 입력, 다른 클라이언트와 겹치지 않게)
2. 절대 경로:
3. API base URL (선택 — 로컬 개발 기준, 미입력 시 1번 클라이언트와 동일하다고 가정):
4. (선택) 스택 (예: React, Flutter, Swift — 모르면 빈칸)
```

수집한 정보를 `partner_list = [{ role_label, path, api_url, stack }, ...]` (N개 항목)에 저장.  
경로 유효성 확인 및 각 파트너 하네스 존재 여부는 pair-init Phase 1에서 (파트너별로 순회하며) 수행.

> 수집한 `partner_list`는 Phase 3.5에서 pair-init 자동 실행 시 컨텍스트로 전달된다.

---

## Phase -1: 레인 상태 초기화

목적: 분리 저장소는 자기 쪽과 파트너 쪽을 **대칭 2-레인으로 동시에** 진행한다(아래 "Phase 1: 작업 그래프" 절 참조) — 예전의 "조기 발사 후 늦게 join" 방식은 파트너 쪽 진행 상황이 보이지 않고 하드 배리어도 없었는데, 이번부터는 각 레인(I/A/W/V)을 이 orchestrator가 직접 지휘하므로 두 방식 모두 필요 없어졌다. 이 절은 그 레인들이 참조할 **상태 파일만** 준비한다 — 실제 레인 실행은 Phase 1/2에서 한다.

`init_layout`이 `paired-roots`/`hub-roots`가 아니면 이 절 전체를 스킵. 이 절은 **`SKILL.md` Phase -1 서두의 "스킵 조건"과 무관하게 항상 실행한다** — `00_init_scope.md`가 이미 있어 사용자에게 구성을 다시 묻지 않는 경우(재시도 포함)에도 `init_layout` 값은 그 파일에서 읽을 수 있으므로, 레인 재개 판단(아래)이 항상 이뤄져야 한다.

`_workspace/pair_lane_state.md` 존재 확인:

- **없으면 새로 생성**(`_workspace/` 없으면 먼저 생성):
  ```markdown
  pair_state: pending
  self_role: [backend|frontend|hub]
  self_last_stage: none
  self_status: pending
  partner: [role_label] | path: [파트너 절대경로] | last_stage: none | status: pending
  (hub-roots는 partner_list 개수만큼 partner 줄 반복)
  ```
  `self_role`은 `hub-roots`면 항상 `hub`(=backend 취급), `paired-roots`면 `partner_info.role`의 반대.
- **이미 있으면 그대로 재사용** — `self_status`/각 `partner`의 `status`가 `done`인 레인은 Phase 1의 작업 그래프에서 완전히 제외하고(재분석 안 함), `failed`인 레인만 `last_stage` 다음 단계부터 포함한다. 전부 `done`이고 `pair_state: complete`면 Phase 1의 분리 저장소 그래프 자체를 스킵하고 곧장 Phase 3.6으로(파트너 연동은 이미 끝난 상태).

이 파일은 `_workspace/pair_config.md`(pair-init이 만드는 연동 설정)와 다른 파일이다 — `pair_config.md`를 읽는 기존 스크립트(`wiki_generator.py`/`skills_builder.py`)는 이 파일을 몰라도 되고, 건드리지 않는다.

**자기쪽 Phase 0~2~4 실행 방식 자체는 바뀌지 않는다** — 단일/모노레포와 동일한 2-0.5/2-1/2-2/2-3/2-4/2-5 절차를 그대로 쓴다. 달라지는 것은 "그 절차를 자기 자신뿐 아니라 파트너 경로에도 병렬로 적용하고, 끝나면 barrier로 합류한다"는 오케스트레이션 층위뿐이다.

---

## Phase 1: 작업 그래프

단일/모노레포의 `T-*` 그래프 대신 **대칭 2-레인**을 쓴다 — `B` 레인은 backend, `C` 레인은 consumer(hub-roots는 클라이언트 수만큼 `C1`, `C2`, ... 반복). `self`가 backend면 B 레인이 현재 프로젝트이고 C 레인(들)이 파트너, `self`가 frontend면 반대다(hub-roots는 항상 `self=backend`이므로 B=자기 자신, C1..CM=클라이언트 전부).

```
B-I → B-A → B-W → B-P → B-V
C-I → C-A → C-W → C-P → C-V      (hub-roots는 C1-I→C1-A→...부터 CM까지 각자 독립된 체인)

같은 단계(I/A/W/P/V)의 서로 다른 레인은 같은 메시지에서 병렬로 실행한다 (blockedBy는 자기 레인 안에서만).
B-V + 모든 C*-V 완료 → P-BARRIER (blockedBy: B-V, C1-V, ..., CM-V)
                       → P-PAIR    (blockedBy: P-BARRIER)
                       → P-REFRESH (blockedBy: P-PAIR)
```

표시 제목 예: `B-A · analyzer · [백엔드] 서비스·DB 업무 흐름 분석`, `C-A · analyzer · [프론트엔드] 화면에서 API까지 호출 흐름 분석`(hub-roots는 `C1-A · analyzer · [web-frontend] ...`처럼 role_label을 그대로 씀). `P-BARRIER · 양쪽 저장소 검증 결과 확인`, `P-PAIR · 프론트엔드와 백엔드 양방향 연결`, `P-REFRESH · API 계약과 미매칭 호출 갱신`.

각 레인의 I/A/W/P/V는 단일/모노레포의 T-I/T-A/T-W/T-P/T-V와 **완전히 같은 절차·프롬프트**를 쓴다(2-0.5/2-1/2-2/2-3/2-4) — 대상 프로젝트 루트만 그 레인의 경로(자기 자신 또는 파트너 절대경로)로 바꾼다. validator가 패턴 프로필 검증 결과까지 확인하므로 P는 V의 선행 단계이며 barrier에 간접 포함된다. T-E(harness-eval)도 레인마다 독립 실행한다. 실행 방식 상세는 아래 "Phase 2: 레인 실행" 절 참조.

**실패 처리 — 실패한 Lane만 재개, 성공 Lane은 보존:** 레인 상태는 `_workspace/pair_lane_state.md`에 기록한다(위 "Phase -1: 레인 상태 초기화" 절에서 생성). 어느 레인이든 I/A/W/P/V 중 하나가 실패하면 그 레인만 `status: failed`로 표시하고 P-BARRIER/P-PAIR/P-REFRESH로 진행하지 않는다 — 성공한 레인은 그대로 두고(`status: done`) 사용자에게 "[레인] 실패 — 재시도하려면 harness-init을 다시 요청하세요"만 안내한다. 다음 실행에서 Phase -1이 이 파일을 읽어 `status: done`인 레인은 완전히 건너뛰고 실패했던 레인의 실패 지점부터만 이 작업 그래프에 포함한다.

---

## Phase 2: 레인 실행

`SKILL.md`의 2-0.5~2-5는 **레인 한 개(자기 자신)를 대상으로 한 절차**로 서술돼 있다. 분리 저장소는 그 절차 자체를 바꾸지 않고, 레인 수만큼(B 1개 + C 1~M개) **같은 단계를 같은 메시지에서 병렬 실행**한다:

- **I 단계**: 2-0.5의 `pipeline-runner` `block: index` 호출을 자기 루트로 1회, 그리고 아직 `status: done`이 아닌 각 파트너 루트로 1회씩 — `root`만 그 레인의 대상으로 바꿔 **전부 같은 메시지에서** 발행한다(2026-08-16부터 스크립트 다중 도구 호출이 아니라 Agent 병렬이다). 전부 반환된 뒤 각 레인 `last_stage: I`로 갱신.
- **A/W/P/V 단계**: 2-1/2-2/2-3/2-4의 `Agent()` 템플릿을 그대로 쓰되, "프로젝트 루트: [절대경로]"만 그 레인의 대상(자기 자신 또는 해당 파트너 절대경로)으로 바꾼다. `description`도 레인 ID로 바꾼다(`T-A`→`B-A`/`C1-A` 등, 표시 이름 규칙은 Phase 1 참조). 같은 단계에 해당하는 레인들의 `Agent()` 호출을 **전부 같은 메시지에서** 발행하고, 전부 반환된 뒤 다음 단계로 넘어간다(자연스러운 barrier — 별도 폴링 불필요).
- **2-2.3(assemble)/2-3.5(verify)/3.7(wiki, 선택 시)의 `pipeline-runner` 호출과 2-5(harness-eval)**: 레인마다 독립 실행한다. 같은 블록에 해당하는 레인들의 `Agent()` 호출도 A/W/P/V와 같이 한 메시지에 모아 발행한다. 패턴 프로필 검증은 2-3.5에 포함되어 V 판정에 반영된다.
- 어느 레인이든 I/A/W/P/V 중 하나가 실패하면 그 레인의 `pair_lane_state.md` 항목을 `status: failed, last_stage: [실패 직전 완료 단계]`로 남기고, 나머지 레인은 계속 진행하되 **전부 끝나도 P-BARRIER로 넘어가지 않는다** — 위 "Phase 1: 작업 그래프"의 실패 처리 절 참조.
- B-V + 모든 C*-V가 `status: done`이면 `pair_lane_state.md`에 `pair_state: barrier_done`으로 갱신하고 아래 "Phase 3.5" 절로 진행. 그 사이의 `SKILL.md` Phase 3(결과 보고)는 레인별로 그대로 수행한다.

---

## Phase 3.5: P-BARRIER → P-PAIR → P-REFRESH

### P-BARRIER: 양쪽 저장소 검증 결과 확인

Phase 2에서 B-V(및 hub-roots면 전체 C*-V)가 모두 `status: done`으로 끝난 경우에만 여기 도달한다(실패 시 Phase 2에서 이미 중단·안내 완료 — 이 절 자체가 실행되지 않는다). 각 레인의 `_workspace/03_validator_report.md`(자기 쪽) 및 파트너 경로의 동일 파일을 읽어 신뢰도 점수를 확인하고, 사용자에게 한 줄로 보고한다:

```
[P-BARRIER] 검증 완료 — 백엔드: [점수]/100, [role_label]: [점수]/100 (...)
```

### P-PAIR: 프론트엔드와 백엔드 양방향 연결

`pair-init` 스킬을 `entry_point: "P-PAIR"`와 함께 실행한다 — 이미 양쪽 하네스가 방금 레인으로 생성·검증됐으므로 pair-init의 Phase 0/1(정보 수집·하네스 확인·자동 생성 3지선다)을 전부 건너뛰고 **Phase 2(pair_config.md 생성)로 직행**한다(pair-init.md Phase 0 "모드 판단" 표의 `entry_point: "P-PAIR"` 행 참조). 1:1은 `partner_info`, 1:N은 `partner_list`(N개)를 그대로 전달.

```
[P-PAIR] 프론트엔드-백엔드 연결 중
[1:1] 파트너 경로: [partner_info.path]
[1:N] 클라이언트: [role_label 목록]
```

이 단계에서 pair-init Phase 2(pair_config.md 생성) → 3(API 계약 추출) → 4(드리프트 검증, 1차) → 5(CLAUDE.md 파트너 섹션)를 순서대로 실행한다.

### P-REFRESH: API 계약과 미매칭 호출 갱신

P-PAIR의 1차 드리프트 검증 결과(`_workspace/reports/api_drift_report.md`, 1:N은 클라이언트별)에서 UNUSED/MISMATCH로 잡힌 "미매칭 호출"이 있으면, pair-init Phase 4(API 드리프트 검증)를 **1회 더** 실행해 최신 산출물 기준으로 재확인한다(레인 실행 중 파트너 쪽 writer가 막 생성한 서비스 스텁·엔드포인트가 1차 검증 시점엔 반영 안 됐을 수 있음). 미매칭 건수가 줄지 않아도 추가 재시도는 하지 않고 그대로 다음으로 진행 — 최종 드리프트 요약을 Phase 3 보고에 포함한다.

```
[P-REFRESH] API 계약·미매칭 호출 재확인
🔴 MISSING: N건 → M건
🟡 MISMATCH: N건 → M건
```

완료 후 `pair_lane_state.md`를 `pair_state: complete`로 갱신 → Phase 3.6으로.

> 레인 실패로 P-BARRIER에 도달하지 못했거나 P-PAIR/P-REFRESH 도중 실패해도 현재 프로젝트 파이프라인 자체는 막지 않는다 — WARN 기록 후 Phase 3.6 메뉴로 진행하되 wiki 항목에 "파트너 병합 없이 단독 wiki로 생성됨"을 표시한다.

### 연동 여부 질문 방식 (Phase -1 스킵 + pair_config.md 없는 경우)

```
백엔드/프론트엔드가 별도 저장소로 분리되어 있나요?
pair-init으로 연동하면 아래가 가능합니다:
  - 전체 스택 기능 동시 생성 (cross-repo-scaffold)
  - API 변경 시 파트너 영향 자동 감지 (analyze-impact 확장)
  - API 드리프트 감지 (프론트↔백엔드 호출 불일치 탐지)

연동하시겠습니까? (Y/N)
```

| 응답 | 동작 |
|------|------|
| Y / 예 / yes / 연동 | `pair-init` 스킬 실행 → 연동 완료 후 Phase 3.6으로 |
| N / 아니오 / no / 나중에 | "나중에 필요하면 `페어 설정해줘`라고 하세요" 안내 후 Phase 3.6으로 |
| 무응답·다른 주제로 전환 | N과 동일 처리 (기본값: 연동 안 함) → Phase 3.6으로 |

---
