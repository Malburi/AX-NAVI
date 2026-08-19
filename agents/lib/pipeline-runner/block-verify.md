# block: verify — 패턴 프로필 + 기계 검증 (Phase 2-3 후단 / 2-4 전단)

`pipeline-runner` 에이전트의 `block: verify` 절차 상세다. 공통 규칙(스크립트 경로·`--out`/`--summary` 생략·에러 원칙·반환 원칙)은 `agents/pipeline-runner.md` 헤더에 있으며 여기서 반복하지 않는다.

pattern-extractor 완료 후, validator Agent 호출 전에 실행한다. 세 스크립트를 순서대로 돌린다.

## Step 1 — 구조화 패턴 프로필 검증

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/pattern_profile.py" validate --root "[root]"
```

결과는 `_workspace/pattern_profile_validation.json`에 남는다. **exit 1이면 나머지 Step을 실행하지 않고 즉시 반환한다** — 프로필이 깨진 상태에서 validator 입력을 만드는 건 낭비다. 누락된 실제 참조 파일·잘못된 scope·부재한 preferred 규칙을 반환에 구체적으로 적어 오케스트레이터가 pattern-extractor 보완 재호출을 지시할 수 있게 한다.

## Step 2 — validator 기계 체크

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/validator_checks.py" --root "[root]"
```

validator 체크 1,2,3,4,6,7,8,9를 계산해 `_workspace/validator_mechanical.json`에 쓴다. 실패 시 WARN 후 계속 — validator가 해당 체크를 직접 수행하는 방식으로 폴백한다.

## Step 3 — 인덱스 스키마 검증

node ≥ 18일 때만. node가 없으면 스킵하고 WARN.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/validate-harness.mjs" --root "[root]" --plugin-root "[plugin_root]" --tier "[tier]" --out "_workspace/validator_schema.json"
```

`_workspace/index/*.json`을 `docs/index-schema/*.json` 대조로 검증한다. `validator_checks.py`의 check7/7b(실제 소스 대조, 내용 정확성)와 겹치지 않는 별개 층(형태 검증)이라 병행한다.

## 반환 형식

Phase 4의 인덱스 무결성 게이트가 이 값들로 분기하므로 **필드를 임의로 생략하지 않는다.**

```
BLOCK: verify | LANE: [lane] | RESULT: OK | PROFILE_FAIL | PARTIAL
profile: PASS | FAIL (preferred [N]개, 실제 기준 파일 [N]개)
profile_missing: [FAIL일 때만 — 누락 참조 파일·scope 오류·preferred 부재를 항목별로]
mechanical: index_integrity_fail=[true|false] index_spotcheck_fail=[true|false]
mechanical_gate_warns: [ "analyzer.md Step 8 참고" 또는 "generated_at" 문구를 포함한 warn만 원문 그대로, 없으면 "없음" ]
schema: failures=[N] plugin_contract_failures=[N] | skipped(node 없음)
schema_fail_messages: [failures > 0일 때만, FAIL 메시지 원문 최대 10줄]
WARN: [없으면 "없음"]
```

`profile: FAIL`이면 Step 2·3을 실행하지 않았다는 뜻이므로 `RESULT: PROFILE_FAIL`로 반환하고 `mechanical`·`schema`는 `미실행`으로 적는다.
