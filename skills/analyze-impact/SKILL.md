---
name: analyze-impact
description: 변경 대상(파일/함수/클래스/SQL/엔드포인트/DB 컬럼)의 직간접 영향과 위험도를 분석한다. "영향도 분석", "이거 수정하면 어디 영향?", "이 함수 수정해도 돼?", "이 SQL 바꾸면 어디 영향?", "이 컬럼 추가했을 때 영향", "impact analysis", "이 API 변경 영향", "분석해줘 영향", "이거 건드려도 돼?", "어디서 쓰이고 있어?", "이 메서드 호출처" 요청 시 트리거. 축약 호출 "영향도 [대상]", "임팩트 [대상]"도 트리거. 인덱스가 없으면 analyzer를 feature-scoped 모드로 먼저 호출.
---

# Analyze Impact (오케스트레이터)

변경 대상이 주어지면 `impact-analyzer` 에이전트를 호출해 직간접 영향과 위험도를 평가한다.

수정·개발·마이그레이션 작업의 *시작점*으로, 다른 작업 스킬(`safe-modify`, `scaffold-feature`, `plan-migration`)도 내부적으로 이 스킬을 호출한다.

---

## Phase 0: 입력 정규화

사용자의 자연어에서 변경 대상을 추출:

| 사용자 표현 | 추출 결과 |
|-----------|---------|
| "OrderService.cancel 수정하면" | 메서드 `OrderService.cancel` |
| "user_service.py 영향" | 파일 `user_service.py` |
| "ORDER_LMS_U02 쿼리 바꾸면" | SQL ID `ORDER_LMS_U02` |
| "TBL_ORDER에 STATUS 컬럼 추가" | DB 스키마 변경 |
| "/api/orders/{id} 응답 변경" | API 엔드포인트 |

모호하면 1회만 확인 질문 ("어떤 함수/클래스/엔드포인트를 의미하시나요?").

---

## Phase 1: 인덱스 준비

먼저 신선도를 확인한다. `$env:CLAUDE_PLUGIN_ROOT`가 비어 있으면(일부 환경에서 자동 설정 안 됨),
이 스킬 로드 시 표시된 "Base directory for this skill"에서 `/skills/analyze-impact`를 뗀 경로를
대신 쓴다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/build-index.mjs" --root "[프로젝트 루트 절대 경로]" --check-stale
```

exit 1(`stale:true`)이면 재인덱싱 후 진행한다 — `reason`이 `인덱스 없음`이면 `--mode init`, 그 외(소스 변경·인덱서 버전 변경)면 `--mode incremental`. 변경 대상 범위가 좁고 전체 재인덱싱이 부담스러우면 `feature-scoped` 모드로 analyzer를 호출해 대상 주변만 빠르게 재인덱싱해도 된다. 재인덱싱이 불가능한 상황이면(대형 모노레포 시간 초과 등) 이후 리포트에 `지식 모델 stale` 경고를 명시하고 진행한다.

이후 아래 인덱스를 `query-index.mjs` 질의로 활용한다(원본 JSON을 Read로 직접 열지 않는다 — 대형 인덱스는 수십 MB):

| 인덱스 | 필요한 분석 | 질의 예시 |
|--------|---------|---------|
| `call_graph.json` | 메서드/함수 영향 분석 | `callers --id <메서드>`, `trace --id <메서드> --depth 3` |
| `sql_usage.json` | SQL ID 영향 | `sql --id <SQL ID>` 또는 `sql --table <테이블>` |
| `schema.json` | DB 컬럼 영향 | `schema --table <테이블>` |
| `external_io.json` | 외부 시스템 영향 평가 | (해당 인덱스는 아직 query-index.mjs 명령 없음 — 필요 시 직접 열람) |
| `transactions.json` | 트랜잭션 경계 영향 | `transaction --id <메서드>` |

---

## Phase 2: impact-analyzer 호출

네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 "`agents/impact-analyzer.md`의 지침을 읽고 그대로 따른다"를 명시한다.

```
Agent(
  subagent_type="total-ito:impact-analyzer",
  description="변경 영향도 분석",
  prompt="<변경 대상: [정규화된 식별자]. 프로젝트 루트: [절대경로]. 출력: _workspace/reports/impact_<slug>.md>",
  model="opus"
)
```

호출 후 `_workspace/reports/impact_<slug>.md`가 실제로 생성됐는지 확인한다 — 드물게 에이전트가 실제
작업 없이 "백그라운드로 실행했다, 기다리겠다" 식 대기 응답만 내고 끝나는 경우(no-op)가 있다. 파일이
없으면 "이전 시도는 실제 작업 없이 끝났다. 대기 언급 없이 이번 턴 안에서 직접 산출물을 생성하라"를
프롬프트에 명시해 1회 재호출한다. 재시도도 실패하면 사용자에게 알린다.

slug 생성: 변경 대상의 안전한 파일명 형태 (예: `OrderService_cancel`, `TBL_ORDER_STATUS`).

---

## Phase 3: 결과 보고

`_workspace/reports/impact_<slug>.md` 읽고 사용자에게 다음 형식:

```
영향도 분석 완료: [변경 대상]

위험도: [N] / 10 ([LOW/MEDIUM/HIGH/CRITICAL])

직접 영향:
- 호출자 N개 ([대표 파일들])

간접 영향:
- BFS 3홉 내 영향 심볼: M개
- 허브 메서드: [상위 3개]

영향받는 테스트: K개
- 커버리지: X% (있는 경우)

외부 통신 영향: [있음/없음 — 있으면 대상 시스템]
트랜잭션 경계: [범위]
DB 스키마 영향: [있음/없음]
인증/인가 영향: [있음/없음]
환경 분기 영향: [있음/없음]

권고:
[LOW] 즉시 진행 가능. 영향 테스트만 실행 권고.
[MEDIUM] 영향 파일 단위 테스트 권고: [목록]
[HIGH] 회귀 테스트 + 사전 리뷰 필수.
[CRITICAL] 외부 조율 + 단계별 배포 + 롤백 계획.

⚠️ 정적 분석으로 잡히지 않는 항목 (수동 확인):
- 리플렉션/동적 호출 가능성
- 외부 cron/메시지 큐에서의 호출 가능성

다음 단계 권고:
- 진행하시려면: "safe-modify" 호출 또는 변경 적용 후 "안전성 평가"
- 회귀 테스트 추가: "test-generator" 호출 ("영향받는 코드 테스트 만들어줘")
- 마이그레이션이라면: "plan-migration" 으로 단계화

전체 리포트: _workspace/reports/impact_<slug>.md
```

---

## 트리거 우선순위

이 스킬은 다음 상황에서 *자동 우선* 실행:
- 사용자 질문에 "영향", "영향도", "impact", "어디 영향", "어디서 쓰여" 키워드 포함
- 사용자가 변경 의사를 표현 ("이거 바꿔도 돼", "수정 가능?")하며 대상이 식별 가능

자동 실행 후 결과를 사용자에게 보여주고 다음 액션 (safe-modify 또는 진행 중단)을 묻는다.

---

## 한계 정직 안내

리포트 끝에 항상 명시:
- "정적 분석 한계로 리플렉션/동적 바인딩/외부 트리거는 누락될 수 있습니다. 위험도 결과에 +1~2를 고려하세요."
