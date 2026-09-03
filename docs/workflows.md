# Workflows — When to Use Which Skill

각 워크플로우 스킬을 *언제 어떻게* 쓰는지 시나리오 모음.

---

## 빠른 의사결정 트리

```
무엇을 하려고 하나?

├─ 처음 프로젝트 설정             → harness-init
├─ "이거 수정해도 돼?" (정보 수집) → analyze-impact
├─ 실제로 수정 진행                → safe-modify
├─ 새 기능 만들기                  → scaffold-feature
├─ 스택 자체를 바꾸기              → plan-migration
├─ SQL 점검                       → review-sql
├─ "이 코드 뭐하는 거야"          → legacy-decoder (직접 호출)
└─ 변경 후 문서 정리              → doc-syncer (직접 호출)
```

---

## 시나리오 1: 신규 프로젝트 투입 (Day 1)

상황: 처음 보는 코드베이스에 투입됨.

```
1. cd /path/to/project
2. cp -r [ax-navi]/.claude ./
3. cp [ax-navi]/CLAUDE.md ./
4. claude
5. "하네스 초기화해줘"
   → harness-init 실행 (15~30분, 프로젝트 크기에 따라)
6. 결과 검토:
   - validator 신뢰도 점수 확인 (80+ 즉시 사용 가능)
   - pattern-extractor 신뢰도 확인
   - (선택) "경계 QA 실행해줘" → qa 리포트의 🔴 HIGH 항목 확인
7. git add CLAUDE.md .claude/ && git commit
```

이 시점부터 *프로젝트별 맞춤 어시스턴트*가 활성화된다.

---

## 시나리오 2: 작은 버그 수정 (영향도 + 안전)

상황: "OrderService.cancel()에서 NPE 발생, null 체크 추가 필요"

```
1. "OrderService.cancel 영향도 분석해줘"
   → analyze-impact: LOW (3/10), 영향 테스트 4개
2. "이 변경 안전하게 적용해줘. null 체크 추가"
   → safe-modify:
      - 사전 영향 확인 (위와 동일)
      - 동일 모듈·레이어의 preferred 프로필과 실제 기준 파일 선택
      - 어시스턴트가 변경 적용
      - pattern-conformance → CONFORM
      - 영향 테스트 4개 실행, PASS 확인
      - change-safety 평가 → GO
3. 인덱스와 wiki 자동 갱신
4. commit
```

---

## 시나리오 3: 운영 핫픽스

상황: "운영에서 결제 검증 우회 사례 발견, 긴급 패치 필요"

```
1. "긴급 핫픽스 — PaymentValidator.validate 보강해야 해. 영향도 먼저"
   → analyze-impact: MEDIUM (5/10), 외부 결제 게이트웨이 호출 포함
2. 사용자: "회귀 테스트 먼저 만들어줘"
   → test-generator: 테스트 8개 골격
3. 사용자: 비즈니스 검증 채우기 (수동)
4. "이 변경 안전하게 적용해줘 — 긴급 핫픽스"
   → safe-modify (mode=hotfix):
      - 적용
      - change-safety → 보안 점수 6/10 → HOLD
      - 권고: 입력 검증 강화 패턴 추가
5. 보완 후 재평가 → GO
6. canary 배포 → 안정성 확인 → 전체 배포
7. "변경 사항 문서 동기화"
   → doc-syncer: CHANGELOG, ADR 업데이트 권고
```

---

## 시나리오 4: 신규 기능 개발 (스캐폴딩)

상황: "주문 일괄 취소 API를 추가해야 함"

```
1. "주문 일괄 취소 기능을 컨벤션 따라 만들어줘.
    엔드포인트는 POST /api/orders/cancel-batch, 
    TBL_ORDER.STATUS 업데이트, OrderRefund 비슷한 패턴"
   → scaffold-feature:
      - pattern_profile.json 검증 + OrderRefund 실제 기준 파일 선택 ✓
      - 영향도 사전 체크 → 충돌 없음
      - Controller, Service, DAO, DTO 생성
      - 쿼리 XML 추가 (ORDER_BATCH_CANCEL_U01)
      - 테스트 골격 (test-generator 호출)
      - pattern-conformance + 빌드/테스트 + change-safety → GO
2. 비즈니스 로직 TODO 채우기 (수동)
3. 테스트 assertion 보완 (수동)
4. "이 SQL 점검해줘 — ORDER_BATCH_CANCEL_U01"
   → review-sql: WHERE 인덱스 미사용 가능 → 권고 인덱스
5. 인덱스 추가 (DBA 협의)
6. 빌드/실행 → 테스트 PASS → commit
```

---

## 시나리오 5: 마이그레이션 프로젝트 시작

상황: "Struts 1.x → Spring Boot 3 마이그레이션 진행 결정"

```
1. "Struts에서 Spring Boot 3으로 마이그레이션 계획 짜줘"
   → plan-migration:
      - 컨텍스트 수집 대화 (소스/타겟/범위/외부 조율)
      - migration-planner 실행
      - 7개 문서 생성 (inventory, mapping, phased plan, risks, tests, rollback, checkpoints)
2. 사용자 결정:
   - 데드 코드 제외 대상 사인오프
   - DB 마이그레이션 전략 결정 (병행)
   - canary 비율 (1/10/50/100)
   - Phase 0 시작일
3. Phase 0 (환경 셋업): 외부 작업
4. Phase 1 시작 — 모듈 단위 변환:
   각 모듈마다:
     a. "OrderAction을 Spring Controller로 변환할 빈 구조 만들어줘"
        → scaffold-feature
     b. 매핑 테이블에 따라 코드 변환 (수동)
     c. "회귀 테스트 만들어줘"
        → test-generator
     d. "이 변환 안전한가?"
        → safe-modify
     e. canary 배포
   모듈 완료 후 체크포인트 확인.
5. Phase 종료 시 _workspace/migration/checkpoints/phase[N].md 확인 + 사인오프
6. 이후 Phase 2~4 반복
```

---

## 시나리오 6: 레거시 코드 해석

상황: 변수명이 a1/b2인 PL/SQL 프로시저를 받음.

```
1. "PROC_BATCH_NIGHT 뭐하는 거야?"
   → legacy-decoder:
      - 구조 분해
      - 변수 의미 추적 ([추정] 표시)
      - 비즈니스 의도 추정
      - 사이드 이펙트 (어떤 테이블 UPDATE)
      - 의문점 (사람에게 물을 항목)
2. 리포트 확인 → 비즈니스 담당자에게 의문점 확인
3. "이 프로시저 영향도 분석해줘"
   → analyze-impact: 호출 위치 + 영향 SQL
4. 리팩토링 여부 결정
```

---

## 시나리오 7: DB 컬럼 추가

상황: TBL_ORDER에 STATUS 컬럼 추가 (운영 환경)

```
1. "운영 DB에 TBL_ORDER.STATUS 컬럼 추가해야 해.
    영향 분석해줘. NOT NULL DEFAULT 'PENDING' 으로"
   → review-sql (DDL mode=production):
      - 영향 SQL ID: 24개
      - 영향 @Entity: Order
      - DEFAULT 있음 → 기존 데이터 영향 LOW
      - 위험도: 4/10 (MEDIUM, HOLD)
      - 권고: 인덱스 추가 검토
2. "Order Entity에 status 필드 추가하면 어디 영향?"
   → analyze-impact: 호출자 + JSON 응답 shape 변경
3. 사용자: API 응답 호환성 검토 → 클라이언트 영향 없음 확인
4. ALTER 스크립트 실행 (DBA)
5. Entity 변경 + safe-modify로 적용
6. "변경 문서 동기화"
   → doc-syncer: API 스펙 업데이트 권고
```

---

## 시나리오 8: 코드 변경 없이 분석만

상황: 코드 리뷰 시 "이거 어디서 쓰여?"

```
1. "OrderService.cancel 영향도 분석"
   → analyze-impact (변경 없이 정보만)
2. 리포트만 확인하고 종료
```

→ analyze-impact는 *읽기 전용*. 안전.

---

## 시나리오 9: 패턴이 바뀐 것 같음

상황: 최근 팀이 새로운 컨벤션을 도입했는데 patterns/ 가 옛 컨벤션을 가리킴.

```
1. "패턴 다시 추출해줘"
   → harness-init "부분 재실행" 모드:
      - pattern-extractor만 실행
      - patterns/*.md 본문 갱신
      - pattern_profile.json 갱신 및 실제 기준 파일 검증
2. _workspace/05_patterns_extracted.md와 _workspace/pattern_profile_validation.json 확인
```

---

## 시나리오 10: 인덱스 갱신만

상황: 큰 리팩토링 후 인덱스가 stale.

```
1. "인덱스 갱신해줘"
   → harness-init "인덱스 리프레시" 모드:
      - analyzer incremental만 실행
      - 변경 파일만 재분석해 인덱스 부분 갱신
2. 갱신 보고
```

---

## 자주 묻는 질문

### Q. analyze-impact와 safe-modify의 차이?

A.
- `analyze-impact`: *읽기 전용*. 변경 의사가 있지만 *진행은 아직*.
- `safe-modify`: *변경까지 진행*. 사전 영향 + 적용 + 사후 안전성 한 번에.

작은 수정에 `safe-modify`만 써도 됨 (사전 영향 분석을 내부에서 수행).

### Q. scaffolder와 scaffold-feature의 차이?

A.
- `scaffolder`: *체크리스트만* 보여줌. 어떤 파일을 만들어야 하는지 안내.
- `scaffold-feature`: *실제 파일 생성*. 컨벤션 100% 준수 + 테스트 골격 + 사전 영향 체크.

### Q. 인덱스가 stale인지 어떻게 알 수 있나?

A. analyze-impact, review-sql 등 인덱스를 쓰는 스킬이 stale 경고를 자동 표시. 의심되면 "인덱스 갱신해줘"로 incremental 재실행.

### Q. 마이그레이션 도중에도 일반 작업을 할 수 있나?

A. 가능. plan-migration은 *계획만* 생성하므로 코드는 그대로. 변환 작업은 모듈 단위로 safe-modify + scaffold-feature 조합. 일반 버그 수정은 동시에 진행 가능 (마이그레이션 대상 모듈 충돌만 주의).

### Q. 자동 수정은 안 하나요?

A. 보안 위험 발견, DEAD/ORPHAN 발견 같은 *위험 항목*은 절대 자동 수정 X. *권고만*. safe-modify의 변경 적용도 사용자가 진행 의사를 명시한 경우에만.

### Q. legacy-decoder 결과는 신뢰할 수 있나?

A. 코드에서 *직접 읽힌 것*은 신뢰 가능 (변수 흐름, 사이드 이펙트). *비즈니스 의도 추정*은 [추정] 마크가 표시되니 사람 확인 필요.
