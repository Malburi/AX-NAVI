---
name: safe-modify
description: 코드 변경을 사전 영향 분석 → 적용 → 사후 안전성 평가 순으로 안전하게 수행. "안전하게 수정", "회귀 위험 없이 변경", "safe modify", "이 변경 안전한가?", "변경 전 체크", "이 패치 적용해도 돼?", "운영 패치 검토", "긴급 핫픽스", "이 수정 GO/NO-GO?", "변경 리뷰" 요청 시 트리거. 범용 수정 요청("수정해줘", "고쳐줘", "개선해줘", "버그 잡아줘", "이거 바꿔줘")도 기본적으로 이 스킬을 탄다 — 게이트 없이 바로 하려면 vibe 스킬("알아서 해줘"). 축약 호출: "안전수정 [내용]".
---

# Safe Modify (오케스트레이터)

변경을 적용하기 *전·중·후* 모두에 안전 게이트를 둔다.  
ITO/SI에서 "수정 → 곧장 commit → 운영 사고"의 사이클을 끊는 것이 목적.

---

## 변경 범위 원칙 (Rule: 외과적 변경)

> 모든 Phase에서 이 원칙이 최우선 적용된다.

- **요청된 부분만** 수정한다. 인접 코드·주석·포맷을 "개선"하지 않는다.
- **내가 만든 orphan만** 정리한다. 기존 dead code는 언급하되 삭제하지 않는다.
- 변경된 모든 줄은 사용자 요청에 직접 연결되어야 한다.
- 리팩터링이 필요해 보이면 *변경 후* 별도 제안으로만 언급한다.

---

## Phase 0: 컨텍스트 추출

사용자 자연어에서 운영 모드 키워드 감지:

| 키워드 | mode |
|--------|------|
| "운영 패치", "프로덕션", "운영 배포" | production |
| "긴급 핫픽스", "장애 대응" | hotfix |
| "레거시 손보기", "옛날 코드" | legacy |
| "고객 데모", "데모 직전" | customer_facing |
| (없음) | normal |

mode는 change-safety에 전달되어 가중치 조정에 사용된다.

변경 대상마다 어댑터 커버리지 게이트를 먼저 실행한다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/check-adapter-coverage.mjs" --root "[프로젝트 루트 절대 경로]" --target "[변경 대상 상대 경로]"
```

- `FULL/GO`: 다음 단계 진행 가능.
- `PARTIAL/HOLD`: 코드·설정·디자이너 파일을 함께 읽고 스택별 빌드/수동 시나리오까지 확보하기 전 GO 금지.
- `UNSUPPORTED/HOLD`: 지원되는 어댑터를 추가하거나 사용자가 지정한 전문 도구/수동 검증 절차를 확보하기 전 변경 금지.
- 여러 파일이면 가장 낮은 커버리지를 전체 변경의 커버리지로 사용한다. `change-safety` 입력에도 결과 JSON을 포함한다.

변경 대상 경로가 정해지면 `.claude/patterns/pattern_profile.json`을 검증하고 해당 모듈·레이어의 기준 패턴을 선택한다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/pattern_profile.py" validate --root "[프로젝트 루트 절대 경로]"
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/pattern_profile.py" select --root "[프로젝트 루트 절대 경로]" --target "[변경 대상 경로]" --module "[모듈명]" --limit 20
```

프로필이 없으면 Markdown 패턴과 동일 모듈의 유사 코드로 폴백할 수 있지만, 리포트에 `구조화 패턴 미검증`을 표시한다. 신규 파일 생성이 포함된 변경은 폴백하지 않고 pattern-extractor를 먼저 실행한다.

---

## Phase 1: 사전 영향 분석

변경 대상이 명확하면 → `analyze-impact` 호출 (위의 analyze-impact 스킬 그대로):
- 변경 대상 정규화
- 인덱스 준비
- impact-analyzer 실행 → `_workspace/reports/impact_<slug>.md`

영향도 결과를 사용자에게 보여주고 *진행 여부 확인*:

```
영향도: [N]/10 ([등급])
영향받는 테스트: K개

진행 옵션:
1. 변경 적용 후 안전성 평가까지 진행
2. 사전 회귀 테스트 작성 후 진행 (test-generator 호출)
3. 중단

선택?
```

CRITICAL 등급이면 옵션 2를 권장 + 추가 확인.

---

## Phase 2: 변경 적용

사용자가 진행 선택 시:
- 사용자가 직접 변경을 작성하거나
- 사용자가 변경 내용을 자연어로 설명 → 어시스턴트가 Edit/Write로 적용

적용 후 변경 파일 목록 수집 (git diff 또는 작업 추적).

변경 시 `_workspace/reports/pattern_selection.json`의 선택 프로필과 `reference_files`를 먼저 읽는다. 현재 파일의 레거시 패턴을 유지해야 하는 최소 수정과 신규 권장 패턴 적용을 구분하며, 요청 범위 밖의 전체 현대화는 하지 않는다.

---

## Phase 3: 사후 패턴·실행·안전성 평가

### 3-1. 패턴 적합성 검증

`pattern-conformance` 에이전트를 호출한다.

네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 해당 `agents/<이름>.md`의 지침을 읽고 그대로 따르라고 명시한다.

```
Agent(
  subagent_type="total-ito:pattern-conformance",
  description="변경 코드 패턴 적합성 검증",
  prompt="<변경 파일: [목록]. 선택 결과: _workspace/reports/pattern_selection.json. 출력: _workspace/reports/pattern_conformance_<slug>.md>",
  model="sonnet"
)
```

FAIL이면 수정 후 재검증하고, HOLD이면 사용자 결정 전 GO로 진행하지 않는다.

### 3-2. 검증 명령 실행

먼저 결정론적 감지기로 프로젝트의 검증 명령 후보를 확보한다(부작용 없음).

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/verify-target.mjs" detect --root "[프로젝트 루트 절대 경로]" --target "[변경 대상 상대 경로]"
```

`detected` 목록(lint/typecheck/test/build)을 사용자에게 보여주고, 변경 범위에 해당하는 가장 작은 명령을 골라 실제 실행한다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/verify-target.mjs" run --root "[프로젝트 루트 절대 경로]" --cmd "[detected에서 고른 명령]"
```

`run`은 성공 시 요약만, 실패 시 `fail_lines`(명령당 상한)만 돌려준다 — 코드 전체를 다시 LLM에 넣지 않는다. 반환된 `commands[].cmd`·`exit`·`fail_lines`와 `overall`을 그대로 change-safety 입력에 넘긴다. `detected`가 비어 있으면(`count: 0`) 자동 검증이 없다는 뜻이므로 수동 검증 시나리오를 확보하기 전 PASS로 간주하지 않는다. 실행할 수 없거나 assertion까지 도달하지 못한 검사도 PASS로 간주하지 않는다.

### 3-3. 변경 안전성 평가

`change-safety` 에이전트 호출:

```
Agent(
  subagent_type="total-ito:change-safety",
  description="변경 안전성 평가",
  prompt="<변경 파일: [목록]. mode: [감지된 모드]. impact 리포트: _workspace/reports/impact_<slug>.md. 패턴 적합성: _workspace/reports/pattern_conformance_<slug>.md. 검증 결과: verify-target run의 commands(cmd·exit·fail_lines)와 overall. 출력: _workspace/reports/safety_<slug>.md>",
  model="sonnet"
)
```

---

## Phase 4: 결정 + 후속 조치

`_workspace/reports/safety_<slug>.md` 읽고 사용자에게 보고:

```
변경 안전성 평가 완료

차원별 점수:
| 회귀 | 컨벤션 | 사이드이펙트 | 롤백 | 보안 | 테스트 |
|------|--------|-----------|------|------|--------|
| X    | X      | X         | X    | X    | X      |

종합 위험도: X/10
즉시 STOP 트리거: [있음/없음]

패턴 적합성: [CONFORM / HOLD / FAIL]
검증 증거: [명령·exit code / UNVERIFIED]
결정: [GO / HOLD / STOP]

[GO]
권장 다음 액션:
- commit 메시지: [권고]
- 추가 권고:
  - doc-syncer 호출 ("문서 동기화") — 문서 영향 점검
  - (production mode) 단계적 배포

[HOLD]
보완 필요 항목:
1. [차원]: [구체 액션]
2. ...
보완 후 다시 호출하세요: "이 변경 다시 평가해줘"

[STOP]
사유: [...]
대안:
- [...]
권장: 변경 철회 또는 재설계

전체 리포트: _workspace/reports/safety_<slug>.md
```

GO는 `어댑터 FULL + 패턴 CONFORM + 필수 검증 exit 0 + change-safety GO`가 모두 충족될 때만 사용한다. 검증을 실행하지 못했거나 어댑터가 PARTIAL/UNSUPPORTED면 위험 점수가 낮아도 HOLD(`UNVERIFIED`)로 보고한다.

## Phase 5: 인덱스·위키 증분 갱신

GO 후 변경된 코드가 다음 작업과 인수인계 위키에 반영되도록 기본 실행한다.

1. 결정론적 인덱서를 incremental 모드로 실행한다.
2. API·SQL·호출 관계가 바뀌었으면 관련 인덱스가 실제 변경 파일을 포함하는지 확인한다.
3. `generate-wiki`를 재실행한다.
4. 생성된 wiki의 분석 커밋·시각과 현재 HEAD가 맞는지 보고한다.

갱신 실패는 코드 변경을 되돌리는 사유는 아니지만 `지식 모델 stale` WARN으로 명확히 남기고 재실행 명령을 안내한다.

---

## 자동 후속 (옵션)

GO 결정 시 추가 선택 작업:
- 사용자 명시 요청 있으면 → test-generator 자동 호출 (영향 코드 회귀 테스트 추가)
- 사용자 명시 요청 있으면 → doc-syncer 자동 호출 (문서 동기화)

test-generator·doc-syncer는 기본 OFF지만 Phase 3의 실제 테스트 실행과 Phase 5의 인덱스·wiki 갱신은 기본 ON이다.
