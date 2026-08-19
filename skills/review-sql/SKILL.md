---
name: review-sql
description: SQL 텍스트·SQL ID·DDL·SQL diff를 받아 사용처·인덱스 활용·N+1·인젝션·트랜잭션·락·대량 처리·스키마 영향을 종합 리뷰. "SQL 리뷰", "SQL review", "이 쿼리 점검", "N+1 확인", "이 쿼리 성능", "인덱스 잘 쓰고 있어?", "이 SQL 안전한가?", "DDL 영향 분석", "이 컬럼 추가해도 돼?", "프로시저 리뷰", "운영 SQL 검토" 요청 시 트리거. 축약 호출: "SQL리뷰 [SQL ID·쿼리]", "쿼리리뷰 [대상]".
---

# Review SQL (오케스트레이터)

`sql-reviewer` 에이전트를 호출해 SQL을 다각도로 리뷰한다.  
ITO/SI에서 *DB가 사고의 절반*이라는 점을 고려해, 운영 컨텍스트에 따라 평가를 보수적으로 조정.

---

## Phase 0: 입력 정규화

SQL 입력 형식 자동 감지:

| 입력 형식 | 처리 |
|---------|------|
| SQL ID (`ORDER_LMS_S01`) | sql_usage.json에서 텍스트 조회 |
| SQL 텍스트 (DML/SELECT) | 그대로 |
| DDL (CREATE/ALTER/DROP) | DDL 모드 |
| git diff (`*.sql` 또는 query XML) | diff 파싱 후 변경 SQL 추출 |
| 파일 경로 | 파일 내 SQL 모두 분석 |

---

## Phase 1: 운영 모드 감지

사용자 자연어에서 키워드:

| 키워드 | 모드 | 평가 조정 |
|--------|------|---------|
| "운영 DB", "프로덕션 쿼리" | production | 모든 차원 ×1.5 |
| "야간 배치", "배치 SQL" | batch | 대량 처리 ×0.5 |
| "운영 시간 패치" | live_patch | 락 ×2 |
| "OLTP", "온라인 트랜잭션" | oltp | 락 ×2 |
| "OLAP", "데이터 웨어하우스", "분석 쿼리" | olap | 성능 ×2, 락 ×0.5 |
| (없음) | normal | 기본 |

---

## Phase 2: sql-reviewer 호출

네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 "`agents/sql-reviewer.md`의 지침을 읽고 그대로 따른다"를 명시한다.

```
Agent(
  subagent_type="total-ito:sql-reviewer",
  description="SQL 종합 리뷰",
  prompt="<SQL: [원문 또는 ID]. mode: [감지된 모드]. 프로젝트 루트: [...]. 인덱스: _workspace/index/sql_usage.json, schema.json. 출력: _workspace/reports/sql_review_<slug>.md>",
  model="sonnet"
)
```

slug: SQL ID가 있으면 그대로, 텍스트면 첫 30자 해시.

---

## Phase 3: 결과 보고

```
SQL 리뷰 완료

대상:
```sql
[SQL 원문 1~5줄]
```

운영 모드: [감지된 모드]

차원별 평가:
| 사용처 | 인덱스 | N+1 | 인젝션 | 트랜잭션 | 락 | 대량 | DDL 영향 | 성능 |
|--------|--------|-----|--------|---------|-----|------|--------|------|
| [요약] | [...]  | ... | ...    | ...     | ... | ...  | ...    | ...  |

위험도: N / 10 ([LOW/MEDIUM/HIGH/CRITICAL])
즉시 STOP 트리거: [있음/없음]

결정: [GO / HOLD / STOP]

주요 발견:
- [핵심 발견 1~3개]

권고:
[GO]
- 실행 전 EXPLAIN 확인 권고
- 테스트 DB dry-run

[HOLD]
보완 항목:
1. [구체 액션]
2. ...

[STOP]
대안:
- [대안 1]
- [대안 2]

전체 리포트: _workspace/reports/sql_review_<slug>.md
```

---

## 자동 후속 (DDL인 경우)

DDL이고 GO 결정 시:
- "마이그레이션 스크립트로 만들어줘"라는 요청이 있으면 → 마이그레이션 도구 형식 (Liquibase/Flyway changeSet) 으로 변환 제안
- Down 스크립트 자동 작성 권고

DML 변경 SQL인 경우:
- 영향 받는 코드 위치를 analyze-impact로 추가 분석 권장

---

## 원칙

### 실행은 절대 자동으로 하지 않음

sql-reviewer는 *리뷰만*. 절대 운영 DB에 자동 실행하지 않는다.

### 운영 모드 가중치

운영 환경 키워드가 감지되면 평가가 보수적이 된다. 사용자가 "그래도 진행" 요청 시에도 사용자가 *알고* 진행해야 함을 명시.

### 인덱스/스키마 캐시 의존

`_workspace/index/schema.json` 이 있어야 정확한 분석. 없으면 → "DB 접속하여 스키마 추출 필요" 안내.
