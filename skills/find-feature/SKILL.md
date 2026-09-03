---
name: find-feature
description: 기능명·키워드·도메인 용어로 관련 파일·클래스·메서드·SQL을 찾아 목록으로 반환한다. "결제 관련 파일 어디 있어?", "회원가입 어디서 처리해?", "쿠폰 관련 코드 찾아줘", "배송 로직 어디 있어?", "find feature", "어디 있어?", "관련 코드 찾아줘", "관련 파일", "코드 어디에?", "찾아줘", "어디서 처리해?", "담당 파일", "담당 클래스" 요청 시 트리거.
---

# Find Feature (오케스트레이터)

키워드를 받아 `feature-finder` 에이전트를 호출하고 결과를 사용자에게 전달한다.

---

## Phase 0: 입력 파악

사용자 표현에서 검색 키워드와 범위 추출:

| 사용자 표현 | 추출 |
|-----------|------|
| "결제 관련 파일 어디 있어?" | 키워드: "결제", 범위: 전체 |
| "쿠폰 서비스 레이어만 찾아줘" | 키워드: "쿠폰", 범위: service 레이어 |
| "TBL_ORDER 건드리는 SQL 찾아줘" | 키워드: "TBL_ORDER", 범위: SQL |
| "com.example.order 패키지 회원 관련" | 키워드: "회원", 범위: 패키지 지정 |

키워드가 없으면 1회 확인 ("어떤 기능/키워드를 찾을까요?").

---

## Phase 1: 인덱스 확인

`$env:CLAUDE_PLUGIN_ROOT`가 비어 있으면(일부 환경에서 자동 설정 안 됨), 이 스킬 로드 시 표시된
"Base directory for this skill"에서 `/skills/find-feature`를 뗀 경로를 대신 쓴다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/build-index.mjs" --root "[프로젝트 루트 절대 경로]" --check-stale
```

- `symbols.json` 있고 fresh(exit 0)면 → `query-index.mjs symbol --name <키워드>`로 먼저 훑고, 결과를 feature-finder에 전달(빠른 탐색).
- stale(exit 1)이면 → `--mode incremental`로 재인덱싱 시도. 탐색성 질의라 급하지 않으면 재인덱싱 없이 "인덱스가 stale일 수 있음"만 feature-finder에 알리고 진행해도 된다(find-feature는 read-only라 safe-modify만큼 신선도에 민감하지 않음).
- 인덱스 자체가 없으면 → feature-finder가 다중 grep 전략으로 대체.

---

## Phase 2: feature-finder 호출

네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 "`agents/feature-finder.md`의 지침을 읽고 그대로 따른다"를 명시한다.

```
Agent(
  subagent_type="ax-navi:feature-finder",
  description="기능 위치 탐색",
  prompt="<키워드: [추출된 키워드]. 범위: [레이어/패키지 제한]. 프로젝트 루트: [절대경로]. 출력: _workspace/reports/found_<slug>.md>",
  model="sonnet"
)
```

slug: 키워드의 안전한 파일명 형태 (예: `payment`, `coupon`, `member`).

---

## Phase 3: 결과 전달

`_workspace/reports/found_<slug>.md` 읽어 사용자에게 요약 출력.

결과 끝에 다음 단계 안내:
- 흐름이 궁금하면 → "trace-logic으로 실행 흐름 추적 권고"
- 변경 계획이 있으면 → "analyze-impact로 영향도 확인 권고"
- 레거시 코드면 → "legacy-decoder로 상세 해석 권고"
