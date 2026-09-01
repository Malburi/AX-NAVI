# Index Specification

`_workspace/index/` 하위 JSON 파일들의 스키마 정의.

후속 에이전트(impact-analyzer, sql-reviewer, change-safety, migration-planner 등)가 조회한다.

## 생성 주체

| 파일 | 생성 주체 |
|------|---------|
| `symbols` · `call_graph` · `sql_usage` · `transactions` · `external_io` · `env_branches` · `schema` · `api_contract` · `dead_code` · `ui_flow` | `agents/lib/build-index.mjs` (결정론적 인덱서, LLM 미개입) |
| `call_graph`의 모호 관계 보강 | analyzer가 `_ai_patch.json`의 `add_edge` 오퍼레이션으로 제출 → 인덱서가 검증 후 병합 |
| `call_graph`의 `nodes[]`/`edges[]` 선택적 `note` | analyzer가 `_ai_patch.json`의 `set_node_note`(`{id, note}`)/`set_edge_note`(`{from, to, type, note}`) 오퍼레이션으로 제출 |
| `api_contract`의 `endpoints[]`/`consumers[]` 선택적 `description` | analyzer가 `_ai_patch.json`의 `set_endpoint_description`(`{id, description}`) 오퍼레이션으로 제출 |
| `external_io`의 `communications[]` 선택적 `description` | analyzer가 `_ai_patch.json`의 `set_communication_description`(`{id, description}`) 오퍼레이션으로 제출 |
| `data_flow`의 구조(`chains[]`: endpoint→call_graph→sql_usage 조인) · `client_index`의 구조(`type`·`js_count`·`domain_structure`·`sample_mappings`·`jquery_versions`) | `agents/lib/build-index.mjs` — call_graph·sql_usage가 이미 메모리에 있는 그래프를 조인/정규식으로 결정론적으로 도출(2026-08 이전엔 analyzer가 처음부터 작성했으나, 판단이 필요 없는 부분임이 확인돼 이관됨) |
| `data_flow`의 체인별 `note`(DTO/컬럼 의미·불일치) | analyzer가 `_ai_patch.json`의 `set_flow_note`(`{id, note}`) 오퍼레이션으로 제출 |
| `client_index`의 `ajax_contract`/`naming_convention`/`anti_patterns` | analyzer가 `_ai_patch.json`의 `set_client_index_narrative`(`{ajax_contract?, naming_convention?, anti_patterns?}`) 오퍼레이션으로 제출 |
| `owasp_top10` | analyzer (판단이 필요해 기계화 대상 아님 — 2026-08-04 검토로 유지 확정, 토큰 영향 작음) |
| `schema` (라이브 DB 접속으로 뜬 경우) | analyzer |
| Vue 컴포넌트·Pinia 스토어 노드와 `import`·`inject` 엣지 | `agents/lib/index_extractor_vue.py` (인덱서 결과에 병합) |

인덱서가 없는 환경(node 18 미만)에서는 스택별 Python 추출기가 `symbols`·`call_graph`만 만들고, 그것도 실패하면 analyzer가 전부 작성한다. 상세는 `skills/harness-init/SKILL.md` 2-0.5.

### 벤더·미니파이 소스 제외

인덱서는 서드파티 라이브러리와 미니파이 번들을 인덱싱하지 않는다. 판정은 세 층이다 — 디렉터리 이름(`ckeditor/`·`jquery*/`·`fck_editor/` 등 라이브러리 배포 디렉터리), 파일명(`*.min.js`·`*.pack.js`·`*.bundle.js`와 버전이 박힌 `jquery-1.5.2.js` 꼴), 그리고 파일 내용(앞 64KB의 줄당 평균 길이가 250자 이상이면 미니파이).

**파일명 접두사로는 판정하지 않는다.** `jquery.add.js`가 실제로는 배너 슬라이더 업무 코드였던 실측 사례(2026-08-16)가 있어, 라이브러리 이름을 접두사로 쓴 프로젝트 파일을 자르지 않는다.

제외 결과는 `_meta.json`의 `excluded_sources`에 남는다 — `count`, `by_reason`(vendor-path·vendor-filename·vendor-versioned·minified), `bytes`, 그리고 파일 목록 최대 100건. `indexer-config.json`에 `"vendor_exclude": false`를 두면 이 제외 전체를 끌 수 있다.

실측(2026-08-16 xu25-client): 1,363개 25MB 제외 → 노드 34,674 → 11,120, `dead_code.unused_methods` 31,572 → 9,858. 제외 전에는 노드의 80%가 고아였고 데드코드 리포트가 사실상 전부 거짓양성이었다.

**테스트 파일도 같은 방식으로 제외한다** — `test`/`tests`/`__tests__`/`spec`/`specs` 디렉터리(세그먼트 완전 일치만, `abtest/`처럼 이름이 다르면 걸리지 않음)와 `*Test.java`/`*_test.go`/`test_*.py`/`*.test.ts`/`*Tests.cs` 같은 빌드 도구 강제 규약만 잡는다. 사유는 `by_reason`에 `test-path`·`test-filename`으로 추가되며, `"test_exclude": false`로 끌 수 있다. 업무 코드와 동일하게 전량 노드·엣지가 되어 `call_graph.json`을 부풀리는데 호출 그래프 분석에는 의미가 없는 것이 벤더와 같은 제외 사유다.

### 소스 파일 인코딩

인덱서는 소스를 무조건 UTF-8로 읽지 않는다. BOM → 파일이 스스로 선언한 인코딩(XML prolog의 `encoding=`, JSP의 `pageEncoding=`, HTML `charset=`) → 유효한 UTF-8 → 레거시 폴백(`euc-kr`) 순으로 판정한다. 선언이 레거시인데 바이트가 유효한 UTF-8 멀티바이트면 실제 저장을 믿고 UTF-8로 읽는다.

판정 결과는 `_meta.json`의 `encoding`에 남는다 — `by_encoding`(인코딩별 파일 수), `declared_non_utf8`(선언을 보고 정확히 읽은 파일), `guessed`(선언도 없고 UTF-8도 아니라 추측으로 읽은 파일, 잘못 읽혔을 수 있으므로 확인 대상). `guessed_count`가 0이 아니면 harness-init Phase 3 보고에 드러낸다.

EUC-KR로 저장된 Struts `actconf/*.xml`을 UTF-8로 읽어 한글이 전부 U+FFFD로 깨진 채 `api_contract.json`과 wiki까지 전파된 실사고(2026-08-15)의 재발 방지다. 회귀 테스트는 `agents/lib/tests/build-index.test.mjs`의 "EUC-KR 레거시 설정" 케이스.

### DDL이 없을 때의 스키마

`schema.json`은 원래 `.sql` DDL의 `CREATE TABLE` 파싱 또는 라이브 DB 접속에서만 만들어졌다. 쿼리를 전부 MyBatis/iBatis XML에 두고 DDL을 저장소에 두지 않는 레거시에서는 `tables: []`가 되어 DB가 없는 것처럼 보였다.

이제 DDL이 하나도 없으면 `sql_usage.json`의 `tables`를 집계해 스키마를 유도한다. `_meta.source`가 `derived-from-sql`이고 각 테이블은 `origin: "derived-from-sql"`·`confidence: "MEDIUM"`·`usage_count`·`source_sqls`(최대 10개)를 갖는다. **컬럼은 알 수 없으므로 빈 배열이며 지어내지 않는다.** DDL이 있으면 종전대로 DDL이 우선이고(`_meta.source: "ddl"`) 유도는 하지 않는다.

FROM/JOIN 절의 `ROWNUM`·`DUAL`·`SYSDATE`·`LEVEL` 같은 의사테이블은 걸러낸다. FROM 절의 콤마 구분 목록은 괄호 깊이를 세어 나눈다 — Oracle 페이징 관용구(`FROM( SELECT ... FROM A a, B b ) X ) Y`)에서 두 번째 테이블부터 누락되던 문제 때문이다.

실측(2026-08-16 xu25-server): `.sql` 0개 / SQL 5,348건 → 테이블 603개 유도.

인덱서는 제어 파일 3종을 함께 만든다 — `_meta.json`(전역 매니페스트: tier·복잡도·어댑터 커버리지·생성된 인덱스 목록), `_analysis_input.json`(analyzer가 읽는 상한 있는 요약과 계약), `_unresolved.jsonl`(이름 해석을 확정하지 못한 관계 — 후보가 둘 이상이라 판정이 필요한 것과, 대상이 인덱스에 아예 없어 후보가 0개인 것이 함께 들어간다). 이 셋은 `_meta` 블록을 갖지 않으므로 아래 9필드 규칙 대상이 아니다.

---

## 공통 규칙

- 파일 형식: JSON
- 인코딩: UTF-8 (BOM 없음)
- 들여쓰기: 2칸 (압축 안 함, 사람이 검토 가능)
- 용량 한도: 각 파일 종류별 한도 (analyzer.md 참조). 초과 시 분할.

`_meta`의 9개 필드(`generated_at`~`files_total`)는 모든 인덱스 파일에 필수다 — 없으면 `validator_checks.py`가 하드 FAIL 처리한다.

`generated_at`은 analyzer가 추측해 지어내는 값이 아니라 `agents/lib/now_kst.py` 실행 결과(KST, UTC+9, `+09:00` 오프셋)여야 한다 — `git_commit`을 `git rev-parse HEAD`로 얻는 것과 동일하게 실제 명령 실행 결과를 쓴다.

`call_graph.json`의 모든 edge는 `from`/`to`가 `nodes` 배열에 실존하는 id를 가리켜야 한다 (dangling 금지, `validator_checks.py`가 기계 검증). `_meta.node_count`/`edge_count`도 실제 배열 길이와 일치해야 한다.

각 인덱스 파일은 최상위에 메타 정보:

```json
{
  "_meta": {
    "generated_at": "2026-06-02T15:30:00+09:00",
    "generator": "analyzer",
    "version": "1.0",
    "source_root": "/path/to/project",
    "mode": "init|incremental|feature-scoped",
    "git_commit": "abc1234... (git rev-parse HEAD, git 저장소 아니면 null)",
    "sampled": false,
    "files_scanned": 1180,
    "files_total": 1234,
    "node_count": 1234,
    "edge_count": 5678
  },
  "data": [...]
}
```

---

## call_graph.json

호출 관계 그래프.

```json
{
  "_meta": {...},
  "nodes": [
    {
      "id": "com.example.OrderService.cancel",
      "type": "method",
      "file": "src/main/java/com/example/OrderService.java",
      "line": 42,
      "visibility": "public",
      "static": false,
      "annotations": ["@Transactional"],
      "signature": "void cancel(Long orderId)",
      "note": "주문 취소 업무 로직을 처리하는 서비스 메서드"
    }
  ],
  "edges": [
    {
      "from": "com.example.OrderController.cancel",
      "to": "com.example.OrderService.cancel",
      "type": "call",
      "file": "src/main/java/com/example/OrderController.java",
      "line": 56,
      "note": "취소 요청을 서비스 계층으로 위임한다"
    }
  ]
}
```

`type` 값:
- `call` — 메서드 직접 호출
- `inject` — DI 주입 관계 (Spring `@Autowired` 등)
- `inherit` — 상속/구현
- `import` — 파일/모듈 간 import 관계. 결정론적 인덱서는 **이 타입을 만들지 않는다**(파일 노드가 없는 순수 심볼 그래프라 `to`가 노드가 아니게 된다). Vue 추출기 등 파일 단위 관계를 내는 생성기만 쓴다
- `reflect` — 리플렉션 가능성 (heuristic, 신뢰도 낮음). 인덱서는 만들지 않고 analyzer가 `_ai_patch.json`으로만 추가한다
- `ui_event` · `markup_event` · `scheduler` · `process_entry` — 진입점에서 핸들러로 가는 관계. 출발점은 `trigger:<파일>#<트리거>` 형태의 합성 노드다

모든 레코드에는 `origin`(`deterministic-indexer` | `ai-enrichment` | `analyzer`)과 `confidence`(`HIGH`/`MEDIUM`/`LOW`)가 붙는다 — 어디서 온 사실인지 구분하기 위한 것이다.

`note`는 노드·엣지 모두 선택 필드다 — 인덱서는 채우지 않고, analyzer가 `_ai_patch.json`의 `set_node_note`/`set_edge_note`로 "이게 무엇을 하는지·왜 호출하는지"를 보강한다(위 "생성 주체" 표 참조). Controller·Service·DAO 같은 의미 있는 노드와, 이름만으로 목적이 분명하지 않은 엣지에만 선택적으로 붙는다 — 모든 노드/엣지에 다 있어야 하는 필드가 아니다. call-graph.html은 이 값을 노드 상세 패널과 연결 목록에 그대로 표시한다.

**후보가 하나로 좁혀지지 않으면 엣지를 만들지 않는다.** 인덱서는 이름 해석 결과가 정확히 하나일 때만 엣지를 쓰고, 하나도 없으면(외부 라이브러리 호출 등) 버린다. 그래서 dangling 엣지가 구조적으로 생기지 않는다. analyzer는 `_unresolved.jsonl`을 판정해 `_ai_patch.json`으로만 보강하며, 이때도 **기존 노드 사이의 엣지만** 추가할 수 있다.

후보가 둘 이상일 때는 곧바로 넘기지 않고 **스코프 좁히기**를 한 번 시도한다(`call`·`inject`·`inherit`). 대부분의 언어가 좁은 스코프를 먼저 찾으므로 `same_file` → `same_package` → `same_workspace` 순으로 걸러, 어느 단계에서 **후보가 정확히 하나로 줄어들 때만** 결정론적으로 확정한다. 이렇게 확정한 엣지는 `confidence: "MEDIUM"`과 함께 근거를 `resolved_by`(`same_file` | `same_package` | `same_workspace`)로 남긴다. 좁혔는데 둘 이상 남으면(더 넓은 규칙으로는 갈라지지 않으므로) 즉시 중단하고, 끝까지 하나로 줄지 않으면 종전대로 `_unresolved.jsonl`에 후보 목록과 함께 넘긴다 — 없는 엣지를 지어내지 않는 것이 인덱서의 계약이고, 애매하면 analyzer에게 넘긴다.

`_unresolved.jsonl`은 미해결을 한 건도 빠뜨리지 않고 적지만, 그중 판정 대상은 **후보가 2개 이상인 레코드**뿐이다. 이들이 후보 적은 순으로 파일 앞부분에 오고, 상한(2000건)을 넘는 나머지는 위치와 `candidate_count`만 남고 `candidates_omitted: true`가 붙는다. 후보가 0~1개인 레코드(핸들러가 인덱스에 아예 없는 트리거 바인딩 등)는 고를 것이 없어 소스를 열어도 판정이 성립하지 않으므로, 뒤쪽에 감사 기록으로만 남기고 `no_candidates: true`를 붙여 판정 대상에서 제외한다. 판정 대상 레코드에는 `group_id`가 붙는다 — 아래 `_unresolved_groups.json`의 같은 필드와 대응하는 역추적용이며, 정상 판정 흐름에서는 이 파일이 아니라 그룹 파일을 기준으로 처리한다.

`_analysis_input.json`은 판정 가능 건수를 `coverage.unresolved_decidable_count`(후보 2개 이상인 레코드 수, 발생 위치 기준)로 싣고, `analyzer_contract.skip_no_candidate_records: true`로 제외 규칙을 명시한다. 다만 analyzer의 판정 예산·배치는 이 값이 아니라 `coverage.unresolved_decidable_group_count`(고유 패턴 수) 기준이다 — 아래 `_unresolved_groups.json` 참조. `analyzer_contract.process_all_unresolved`도 전체 미해결 수가 아니라 이 그룹 수를 상한(2000개 그룹)과 비교해 정하며, `false`면 `unresolved_priority`(후보 적은 순 상위 N개 **그룹**)만 판정 대상이 된다.

### `_unresolved_groups.json` — 판정 그룹핑 (2026-09-01)

레거시 코드베이스는 같은 애매함(같은 표현식/대상 + 같은 candidates 조합)이 코드 곳곳에서 반복되는 경우가 흔하다 — 실측(레거시 Java 프로젝트)에서 판정 대상 발생 위치 2,380건이 실제로는 고유 패턴 185개뿐이었고(한 패턴이 872곳에서 반복), 이 프로젝트의 견적은 그룹핑 도입 전 163분에서 도입 후 27분으로 줄었다. 발생 위치마다 파일을 열어 매번 같은 판정을 반복하는 대신, 이 파일은 `_unresolved.jsonl`의 판정 대상 레코드를 `(kind, 식별 필드, candidates)` 조합으로 묶어 낸다.

```json
{
  "_meta": { "generated_at": "...", "generator": "deterministic-indexer", "group_count": 185, "decidable_raw_count": 2380, "total_occurrences": 2380 },
  "groups": [
    {
      "group_id": "g0001",
      "kind": "ambiguous_call",
      "key_field": "user.getUserNo(...)",
      "candidates": ["eduport.common.login.model.StudySession.getUserNo", "eduport.common.login.model.UserSession.getUserNo"],
      "occurrence_count": 872,
      "occurrences": [
        { "from": "coperframe.common.servlet.AjaxController.processRequest", "file": "WEB-INF/src/java/coperframe/common/servlet/AjaxController.java", "line": 144, "workspace": "root" }
      ]
    }
  ]
}
```

`key_field`는 `kind`에 따라 `expression`(`ambiguous_call`) · `handler_name`(`unresolved_trigger`) · `target_name`(`ambiguous_injection`/`ambiguous_inherit`) 중 해당 값을 그대로 옮긴 것이다. `occurrences[]`는 그룹에 속한 모든 발생 위치를 담으며, 그룹 수가 상한(2000개)을 넘는 극단적인 경우에만 `occurrences_omitted: true`로 생략된다(실측 규모 대비 이 상한은 훨씬 넉넉하다). analyzer는 그룹당 `occurrences[0]`만 열어 판정하고 나머지 occurrence에는 같은 판정을 그대로 적용한다 — 상세 계약은 `agents/analyzer.md` Step 8 참조.

---

## symbols.json

모든 클래스/메서드/함수 심볼 인덱스.

```json
{
  "_meta": {...},
  "symbols": [
    {
      "id": "com.example.OrderService",
      "type": "class",
      "file": "src/main/java/com/example/OrderService.java",
      "line": 10,
      "package": "com.example",
      "extends": "AbstractService",
      "implements": ["OrderOperations"],
      "annotations": ["@Service"],
      "methods": [
        {"name": "cancel", "id": "com.example.OrderService.cancel", "line": 42, "visibility": "public"}
      ]
    }
  ]
}
```

언어별 식별자:
- Java: 완전 자격 이름 (`com.example.X.method`)
- Python: 모듈.클래스.함수 (`services.order.OrderService.cancel`)
- JavaScript/TypeScript: 파일경로::심볼명 (`src/services/order.ts::cancelOrder`)
- Go: 패키지.함수 (`services.CancelOrder`)

---

## sql_usage.json

어떤 쿼리를 어디서 실행하는가.

```json
{
  "_meta": {...},
  "sqls": [
    {
      "id": "ORDER_LMS_S01",
      "file": "WEB-INF/config/query/query-order-ora.xml",
      "line": 23,
      "type": "select",
      "tables": ["TBL_ORDER"],
      "columns_selected": ["ORDER_ID", "USER_ID", "STATUS"],
      "columns_where": ["USER_ID", "STATUS"],
      "text_preview": "SELECT ORDER_ID, USER_ID, STATUS FROM TBL_ORDER WHERE USER_ID = ? AND STATUS = ?"
    }
  ],
  "usages": [
    {
      "sql_id": "ORDER_LMS_S01",
      "file": "src/main/java/com/example/OrderService.java",
      "line": 78,
      "method": "com.example.OrderService.findByUser"
    }
  ]
}
```

`type` 값: `select`, `insert`, `update`, `delete`, `ddl`.

`tables`/`columns_*` 는 best-effort 파싱. 동적 SQL은 누락 가능.

---

## schema.json

테이블·컬럼과 관계(PK/FK) 구조.

```json
{
  "_meta": {
    ...,
    "source": "live_db|ddl_files|orm_mapping",
    "dialect": "oracle|postgresql|mysql|..."
  },
  "tables": [
    {
      "name": "TBL_ORDER",
      "schema": "PUBLIC",
      "columns": [
        {
          "name": "ORDER_ID",
          "type": "NUMBER(19)",
          "nullable": false,
          "default": null,
          "primary_key": true
        },
        {
          "name": "STATUS",
          "type": "VARCHAR2(20)",
          "nullable": false,
          "default": "'PENDING'"
        }
      ],
      "primary_key": ["ORDER_ID"],
      "foreign_keys": [
        {
          "name": "FK_ORDER_USER",
          "columns": ["USER_ID"],
          "references_table": "TBL_USER",
          "references_columns": ["USER_ID"]
        }
      ],
      "indexes": [
        {
          "name": "IDX_ORDER_USER_STATUS",
          "columns": ["USER_ID", "STATUS"],
          "unique": false
        }
      ],
      "row_count_estimate": 1234567
    }
  ],
  "views": [...],
  "procedures": [...],
  "functions": [...],
  "triggers": [...]
}
```

`source` 값:
- `live_db` — 운영/스테이징 DB read-only 직접 조회
- `ddl_files` — `*.sql`, `V*.sql`, Liquibase changeset 등에서 파싱
- `orm_mapping` — `@Entity` 클래스에서 역추출

`row_count_estimate` 는 live_db 모드일 때만 채워짐.

---

## transactions.json

트랜잭션 경계 식별.

```json
{
  "_meta": {...},
  "boundaries": [
    {
      "id": "tx_001",
      "entry_method": "com.example.OrderService.cancel",
      "file": "src/main/java/com/example/OrderService.java",
      "line": 42,
      "marker": "@Transactional",
      "propagation": "REQUIRED",
      "isolation": "DEFAULT",
      "rollback_for": ["Exception.class"],
      "methods_in_scope": [
        "com.example.OrderService.cancel",
        "com.example.OrderDao.updateStatus",
        "com.example.RefundService.process"
      ],
      "external_io_calls": [
        {"target": "com.example.PaymentGatewayClient.refund", "type": "http"}
      ]
    }
  ]
}
```

`external_io_calls` 는 트랜잭션 경계 안에서의 외부 호출 — 위험 항목.

---

## external_io.json

외부 통신 식별.

```json
{
  "_meta": {...},
  "communications": [
    {
      "id": "ext_001",
      "type": "http",
      "file": "src/main/java/com/example/PaymentClient.java",
      "line": 45,
      "method": "com.example.PaymentClient.charge",
      "target": "https://api.payment.example.com/charge",
      "timeout_ms": 30000,
      "retry_policy": "exponential_backoff(3)",
      "in_transaction": false,
      "description": "결제 게이트웨이에 승인 요청을 전달한다"
    },
    {
      "id": "ext_002",
      "type": "kafka_producer",
      "topic": "orders.events",
      "file": "src/main/java/com/example/OrderEventPublisher.java",
      "line": 12
    },
    {
      "id": "ext_003",
      "type": "file_io",
      "operation": "read",
      "path_pattern": "/data/batch/*.csv",
      "file": "src/main/java/com/example/BatchJob.java",
      "line": 30
    }
  ]
}
```

`type` 값: `http`, `kafka_producer`, `kafka_consumer`, `rabbit_*`, `sqs_*`, `file_io`, `external_db`, `ldap`, `mail`, `redis`, `s3`, etc.

`description`은 선택 필드다 — 인덱서는 채우지 않고, analyzer가 `_ai_patch.json`의 `set_communication_description`으로 보강한다(위 "생성 주체" 표 참조). 없어도 정상이다.

---

## env_branches.json

환경(운영/개발)에 따라 분기되는 코드·설정.

```json
{
  "_meta": {...},
  "profiles": ["dev", "stg", "prod"],
  "branches": [
    {
      "file": "src/main/java/com/example/SomeConfig.java",
      "line": 23,
      "type": "annotation",
      "marker": "@Profile(\"prod\")",
      "method": "com.example.SomeConfig.productionOnlyBean"
    },
    {
      "file": "src/main/resources/application.yml",
      "line": null,
      "type": "config_file",
      "marker": "spring.profiles.active",
      "values_per_profile": {
        "dev": "localhost",
        "prod": "prod-db.internal"
      }
    },
    {
      "file": "src/services/feature.ts",
      "line": 12,
      "type": "code_if",
      "marker": "if (process.env.NODE_ENV === 'production')",
      "method": "feature.ts::initialize"
    }
  ]
}
```

---

## owasp_top10.json

OWASP Top 10 (2021) 카테고리별 매핑. 정적 분석 증거 기반 — 증거 없는 카테고리는 `미탐지`로 남기며, 이는 "취약점 없음"의 보증이 아니다.

```json
{
  "_meta": {"generated_at": "2026-06-02T15:30:00+09:00", "sampled": false},
  "categories": [
    {
      "id": "A01:2021",
      "name": "Broken Access Control",
      "status": "발견",
      "findings": [
        {
          "file": "src/main/java/com/example/OrderController.java",
          "line": 56,
          "evidence": "cancel(Long orderId) — 소유자 검증 없이 orderId로 직접 조회",
          "severity": "high",
          "confidence": "medium"
        }
      ]
    }
  ]
}
```

`id` 값: `A01:2021` ~ `A10:2021` (OWASP Top 10 2021 edition), 10개 카테고리 고정.

`status` 값:
- `발견` — 코드에서 구체적 증거를 찾음
- `확인필요` — 정적 분석 한계로 사람 검토 필요 (예: A06 의존성 CVE 대조, A04 비즈니스 로직 설계)
- `미탐지` — 해당 패턴 자체를 코드에서 못 찾음

`severity` 값: `high`/`medium`/`low`/`unknown`. `confidence` 값: `high`/`medium`/`low`/`n/a` (샘플링 모드면 low로 낮춘다).

---

## dead_code.json

데드 코드 후보 (확정 아님 — 리플렉션 등 동적 호출 가능성).

```json
{
  "_meta": {
    ...,
    "warning": "Static analysis only. Dynamic invocation (reflection, DI by name, external triggers) NOT detected. Verify before removal."
  },
  "unused_methods": [
    {
      "id": "com.example.LegacyService.unusedMethod",
      "file": "src/main/java/com/example/LegacyService.java",
      "line": 88,
      "visibility": "public",
      "reason": "in_degree=0 in call_graph"
    }
  ],
  "unused_sql_ids": [
    {
      "id": "ORDER_LMS_OLD_S01",
      "file": "WEB-INF/config/query/query-order-ora.xml",
      "line": 99,
      "reason": "not referenced in sql_usage"
    }
  ],
  "unused_jsps": [
    {
      "file": "WEB-INF/jsp/back/order/oldList.jsp",
      "reason": "not in any forward path"
    }
  ]
}
```

각 데드 코드 항목에 `reason`을 명시한다. 사용자 검토 후에만 제거한다.

---

## ui_flow.json

화면 이벤트와 서버 호출 흐름. 현재 Nexacro XFDL/XJS를 결정적으로 추출하며, 다른 데스크톱/리치 클라이언트 어댑터도 같은 계약으로 확장한다.

```json
{
  "_meta": {"generator": "deterministic-indexer", "version": "1.8.0"},
  "screens": [{"id": "OrderForm", "file": "forms/Order.xfdl", "workspace": "frontend"}],
  "events": [{"component": "btnSave", "event": "onclick", "handler": "btnSave_onclick", "file": "forms/Order.xfdl", "line": 20}],
  "datasets": [{"id": "dsOrder", "columns": [{"name": "ORDER_ID", "type": "STRING"}], "file": "forms/Order.xfdl"}],
  "transactions": [{"service_id": "saveOrder", "url": "svc::/orders/save.do", "path_pattern": "/orders/save.do", "callback": "fnCallback", "file": "forms/Order.xfdl", "line": 42}]
}
```

`adapter_coverage.status`가 `PARTIAL`/`WARN`이거나 대상 확장자가 레지스트리에 없으면, 이 인덱스가 일부 존재해도 변경 안전성 판정은 자동으로 `HOLD`다.

---

## data_flow.json

요청 → 로직 → DB까지 데이터 경로.

```json
{
  "_meta": {...},
  "chains": [
    {
      "id": "flow_001",
      "endpoint_id": "POST /orders/{id}/cancel",
      "method_chain": [
        "com.example.OrderController.cancel",
        "com.example.OrderService.cancel",
        "com.example.OrderDao.updateStatus"
      ],
      "sql_ids": ["ORDER_LMS_U01"],
      "tables_read": ["TBL_ORDER"],
      "tables_written": ["TBL_ORDER"],
      "confidence": "HIGH",
      "note": "주문 취소 시 상태 컬럼만 갱신한다"
    }
  ]
}
```

각 체인은 엔드포인트(`api_contract`) → 호출 경로(`call_graph`) → SQL(`sql_usage`) → 읽은/쓴 테이블을 조인해 결정론적으로 도출한다. 인덱서가 이미 메모리에 있는 그래프를 조인하며 LLM은 개입하지 않는다.

`note`는 선택 필드다 — 인덱서는 채우지 않고, analyzer가 `_ai_patch.json`의 `set_flow_note`로 DTO/컬럼 의미·불일치를 보강한다. 없어도 정상이다.

---

## api_contract.json

API 명세(요청·응답)와 호출처.

```json
{
  "_meta": {...},
  "endpoints": [
    {
      "id": "POST /orders/{id}/cancel",
      "workspace": "backend",
      "source": "local",
      "method": "POST",
      "path": "/orders/{id}/cancel",
      "handler": "com.example.OrderController.cancel",
      "framework": "spring-mvc",
      "file": "src/main/java/com/example/OrderController.java",
      "line": 56,
      "request_shape": {"orderId": "Long"},
      "response_shape": {"status": "String"},
      "auth_required": true,
      "origin": "deterministic-indexer",
      "confidence": "HIGH",
      "description": "주문을 취소한다"
    }
  ],
  "consumers": [
    {
      "id": "cons_001",
      "workspace": "frontend",
      "source": "local",
      "call_type": "axios",
      "method": "POST",
      "path_literal": "/orders/${id}/cancel",
      "file": "src/api/order.ts",
      "line": 30,
      "function": "cancelOrder",
      "origin": "deterministic-indexer",
      "confidence": "HIGH"
    }
  ],
  "matches": [
    {
      "endpoint_id": "POST /orders/{id}/cancel",
      "consumer_id": "cons_001",
      "match_type": "path_pattern",
      "confidence": "HIGH",
      "shape_match": "MATCH"
    }
  ],
  "unmatched_endpoints": [],
  "unmatched_consumers": []
}
```

`endpoints`는 서버가 제공하는 API, `consumers`는 그 API를 호출하는 클라이언트/코드다. `matches`는 둘을 경로·shape로 연결한 결과이며, `shape_match`가 `MISMATCH`면 요청/응답 필드가 어긋난 **드리프트**다. 짝을 못 찾은 쪽은 `unmatched_endpoints`/`unmatched_consumers`에 id만 남는다.

`source` 값: `local`(같은 저장소) / `external`(페어 연동된 상대 저장소, `external_repo_path` 동반). `match_type` 값: `path_pattern` / `path_literal` / `heuristic_string_match`. `shape_match` 값: `MATCH` / `MISMATCH` / `UNKNOWN`.

`origin`(`deterministic-indexer` | `ai-enrichment` | `api-bridge` | `analyzer-fallback`)·`confidence`(`HIGH`/`MEDIUM`/`LOW`) 규칙은 `call_graph`와 동일하다. `description`은 선택 필드로 analyzer가 `_ai_patch.json`의 `set_endpoint_description`으로 보강한다. 이 계약의 추출·드리프트 검증·프론트 스텁 생성은 `api-bridge` 에이전트가 담당한다(상단 "생성 주체" 표 참조).

---

## client_index.json

JS ↔ JSP 매핑 (레거시 정적 JS).

```json
{
  "_meta": {...},
  "type": "legacy-static-js",
  "build_tool": null,
  "js_count": 342,
  "domain_structure": {"order": 28, "member": 19},
  "sample_mappings": [
    {
      "js": "js/order/orderList.js",
      "jsps": ["WEB-INF/jsp/order/orderList.jsp"],
      "functions": ["fnSearch", "fnCancel"]
    }
  ],
  "jquery_versions": ["1.8.3", "1.12.4"],
  "ajax_contract": "$.ajax → /order/*.do, JSON 응답",
  "naming_convention": {"function_prefix": "fn"},
  "anti_patterns": ["전역 함수 남발", "인라인 onclick 핸들러"]
}
```

빌드 도구 없이 JSP에 직접 로드되는 레거시 정적 JS의 구조를 담는다 — 각 JS 파일이 어느 JSP에서 쓰이고 어떤 함수를 정의하는지(`sample_mappings`), 혼재하는 jQuery 버전, AJAX 호출 관례, 네이밍·안티패턴이다.

구조(`type`·`build_tool`·`js_count`·`domain_structure`·`sample_mappings`·`jquery_versions`)는 인덱서가 결정론적으로 생성한다. `ajax_contract`·`naming_convention`·`anti_patterns`는 선택 필드로, analyzer가 `_ai_patch.json`의 `set_client_index_narrative`로 보강한다(상단 "생성 주체" 표 참조).

---

## 인덱스 갱신 정책

| 시나리오 | 동작 |
|---------|------|
| 최초 분석 (init) | 전체 인덱스 생성 |
| incremental | git diff 또는 mtime 비교로 변경 파일만 재분석. 영향받는 노드/엣지만 갱신 |
| feature-scoped | 사용자 지정 범위만. 인덱스에 부분 추가 (기존 데이터 보존) |

인덱스 stale 감지:
- 각 인덱스의 `_meta.generated_at`과 코드 파일 mtime 비교
- 코드 파일이 더 최신이면 stale 경고

---

## 인덱스가 없거나 stale일 때의 fallback

각 에이전트는 인덱스 우선 조회, 없으면 grep fallback:

| 에이전트 | 인덱스 의존 | Fallback |
|---------|---------|---------|
| impact-analyzer | call_graph, sql_usage, schema | grep 호출 패턴 |
| sql-reviewer | sql_usage, schema | grep SQL ID, DDL 파일 파싱 |
| change-safety | call_graph, external_io | impact-analyzer 결과 활용 |
| migration-planner | call_graph, external_io, transactions, dead_code | analyzer 리포트 마크다운만 활용 |

Fallback은 느리고 정확도가 떨어진다. 인덱스 정기 갱신을 권장.
