---
name: plan-migration
description: 스택 마이그레이션 계획을 수립한다(인벤토리, 매핑 테이블, 단계별 계획, 위험 등록, 테스트 전략, 롤백, 체크포인트). "마이그레이션 계획", "migration plan", "Spring Boot로 마이그레이션", "Struts → Spring", "iBatis → MyBatis", "Oracle → PostgreSQL", ".NET Core로 옮겨야 해", "Java 17 업그레이드", "JSP를 React로", "AngularJS → Angular", "마이그레이션 로드맵", "전환 계획", "리프트앤시프트" 요청 시 트리거. 축약 호출: "마이그 [현재 → 목표]".
---

# Plan Migration (오케스트레이터)

`migration-planner` 에이전트를 호출해 단계별 마이그레이션 계획·매핑·롤백을 생성한다.  
ITO/SI의 큰 단위 작업인 만큼 *대화형*으로 진행한다.

---

## Phase 0: 마이그레이션 컨텍스트 수집

대화형으로 다음 확인:

| 질문 | 예시 답 |
|------|--------|
| 소스 스택 | (analyzer 결과에서 자동 추출) "Struts 1.x + Spring 3 + Oracle" |
| 타겟 스택 | "Spring Boot 3 + PostgreSQL" |
| 범위 | "전체 모듈" / "Order 모듈만" / "DB만" |
| 주요 동기 | "기술 부채" / "라이선스 비용" / "성능" / "클라우드 이전" |
| 일정 제약 | "1년 내" / "고객사 요구 6개월" |
| 운영 중인가 | yes/no (운영 중이면 단계적 전환 권장) |
| 외부 시스템 연계 변경 가능? | "변경 불가 (API 동결)" / "협의 가능" |
| 백업·롤백 인프라 | "DB 백업 가능, 코드 git" / "VM 스냅샷" |

수집한 컨텍스트는 `_workspace/migration/00_context.md`에 저장.

---

## Phase 1: 인벤토리 사전 점검

`_workspace/01_analyzer_report.md` + `_workspace/index/*.json` 로드.

다음 인덱스가 필요:
- `call_graph.json` — 모듈 간 의존성 (Phase 분리 기준)
- `external_io.json` — 외부 시스템 연계 (위험 항목)
- `transactions.json` — 트랜잭션 경계 (분할 가능성)
- `dead_code.json` — 마이그레이션 *제외* 대상 후보
- `env_branches.json` — 환경별 처리
- `schema.json` — DB 객체 (DB 마이그레이션 시)

인덱스 누락 시 → analyzer 전체 재실행 권고 ("`하네스 초기화 — 인덱스 갱신`").

---

## Phase 2: migration-planner 호출

네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 "`agents/migration-planner.md`의 지침을 읽고 그대로 따른다"를 명시한다.

```
Agent(
  subagent_type="total-ito:migration-planner",
  description="마이그레이션 계획 수립",
  prompt="<컨텍스트: _workspace/migration/00_context.md. 소스: [...]. 타겟: [...]. 범위: [...]. 출력: _workspace/migration/00~05_*.md + checkpoints/>",
  model="opus"
)
```

migration-planner는 7개 문서를 생성한다 (inventory, mapping table, phased plan, risk register, test strategy, rollback plan, checkpoints).

---

## Phase 3: 결과 검토 + 결정 포인트

다음을 사용자에게 보여주고 확인:

```
마이그레이션 계획 수립 완료

소스 → 타겟: [...]
범위: [...]
예상 기간: N개월

생성 문서:
- _workspace/migration/00_context.md
- _workspace/migration/00_inventory.md
- _workspace/migration/01_mapping_table.md
- _workspace/migration/02_phased_plan.md
- _workspace/migration/03_risk_register.md
- _workspace/migration/04_test_strategy.md
- _workspace/migration/05_rollback_plan.md
- _workspace/migration/checkpoints/phase[1-4].md

핵심 의사결정 필요:

1. 데드 코드 제외 대상
   - migration-planner가 식별한 후보: N개 파일
   - 검토 위치: _workspace/migration/00_inventory.md
   - 결정 필요: 진짜 제외할 것 / 검증 후 결정 / 모두 마이그레이션

2. DB 마이그레이션 전략 (DB 마이그레이션인 경우)
   - In-place: 같은 DB에 점진적 변경
   - 병행: 새 DB로 데이터 복제 후 전환
   - 권고: 운영 중이면 병행

3. 외부 시스템 조율
   - 발견된 연계: N건
   - 검토 위치: _workspace/migration/03_risk_register.md (R006)
   - 사전 통지·동결 기간 필요

4. canary 비율 (Phase 3)
   - 권고: 1% → 10% → 50% → 100% (Phase 3 단계)
   - 변경 가능

5. Phase 0(준비) 시작일
   - 환경 셋업 시작 일자

답변하시면 의사결정을 문서에 반영합니다.
```

사용자 답변 후 문서 업데이트 + 변경 이력 기록.

---

## Phase 4: 다음 액션 안내

```
계획 확정 후 권장 작업:

[즉시]
- Phase 0 시작 — 타겟 환경 셋업
- 위험 등록부 사인오프 (PM/고객사)
- 외부 시스템 담당자 통지 ([연계 목록])

[Phase 1 시작 시]
- 변환할 모듈마다:
  - "scaffold-feature" 호출 (타겟 스택 컨벤션으로 빈 구조 생성)
  - 매핑 테이블에 따라 코드 변환
  - "test-generator" 호출 (회귀 테스트 생성)
  - "safe-modify" 호출 (안전성 평가)
  - 동등성 테스트 추가 (Phase 2부터)

[각 Phase 종료 시]
- 체크포인트 문서 확인: _workspace/migration/checkpoints/phase[N].md
- 모든 ✅ 완료 + 사용자 사인오프 후 다음 Phase

[문제 발생 시]
- 즉시 _workspace/migration/05_rollback_plan.md 절차 수행
- 사후 분석으로 위험 등록부 + 매핑 테이블 보완

계속 진행하시려면 "Phase 1 시작" 또는 "Phase 0 준비 항목 확인"
```

---

## 부분 재실행 시나리오

| 요청 | 동작 |
|------|------|
| "매핑 테이블만 다시" | migration-planner를 mapping-only 모드로 호출 |
| "위험 등록부 업데이트" | risk register만 갱신 |
| "체크포인트 추가" | 새 phase 체크포인트 생성 |
| "롤백 계획 보완" | rollback plan만 갱신 |

---

## 원칙

### 마이그레이션은 코드 작성이 아닌 *작전*

이 스킬은 *계획 수립*만 한다. 실제 코드 변환은 사용자가 매핑 테이블에 따라 수행하고, 각 모듈마다 *safe-modify* + *scaffold-feature* + *test-generator*를 조합해 안전하게 진행한다.

### 일정 보수성

migration-planner가 산출하는 일정에 50% 버퍼 적용. ITO/SI 마이그레이션은 거의 항상 예상보다 오래 걸린다.

### 외부 시스템 우선

내부 코드만 보고 계획하면 가장 큰 위험 (외부 시스템 인터페이스)을 놓친다. external_io.json 결과는 *항상* risk register에 반영.

### 사용자 결정 강제

자동 결정 불가 항목(데드 코드 제외, DB 전략, canary 비율, 외부 조율)은 명시적으로 사용자에게 묻는다. 자동 추측 금지.
