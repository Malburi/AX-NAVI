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

`_workspace/index/` 확인:

| 인덱스 | 필요한 분석 |
|--------|---------|
| `call_graph.json` | 메서드/함수 영향 분석 |
| `sql_usage.json` | SQL ID 영향 |
| `schema.json` | DB 컬럼 영향 |
| `external_io.json` | 외부 시스템 영향 평가 |
| `transactions.json` | 트랜잭션 경계 영향 |

필요한 인덱스가 없거나 stale(코드보다 오래됨)이면:
- `feature-scoped` 모드로 analyzer를 먼저 호출 → 변경 대상 주변만 빠르게 재인덱싱
- 또는 사용자에게 "전체 인덱스 갱신 권고 — `하네스 초기화`로 incremental 실행" 안내

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
