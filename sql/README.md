# wiki-hub 중앙 DB 스크립트

`publish-wiki`가 쓰는 중앙 DB의 DDL이다. **평소에는 실행할 필요가 없다** —
`publish.py`가 접속할 때 없는 테이블과 컬럼을 알아서 만든다. 이 스크립트는 다음 경우에 쓴다.

| 상황 | 실행할 것 |
|------|----------|
| DBA 검토를 먼저 받아야 하는 조직 | `01_create_all.sql` → `03_seed_roles.sql` |
| 발행 계정에 DDL 권한을 주지 않는 운영 | 위와 같음 (DBA가 미리 생성) |
| 이미 쓰던 DB에 담당자·권한 표를 더할 때 | `02_upgrade_v1_to_v2.sql` → `03_seed_roles.sql` |
| 스키마를 눈으로 확인하고 싶을 때 | 읽기만 |

```
sql/
├── mssql/       01_create_all.sql  02_upgrade_v1_to_v2.sql  03_seed_roles.sql
├── postgresql/  (동일)
├── oracle/      (동일)
└── sqlite/      (동일)
```

스크립트는 `agents/lib/wikihub_db/models.py`를 SQLAlchemy 방언으로 컴파일해 뽑은 것이라
자동 생성 결과와 **테이블·컬럼·인덱스가 완전히 같다**(SQLite로 양쪽을 만들어 대조 검증함).
손으로 고치지 말고 `models.py`를 고친 뒤 다시 뽑는다.

전부 여러 번 실행해도 안전하다 — 있으면 건너뛴다(MSSQL `OBJECT_ID` 확인, PostgreSQL/SQLite
`IF NOT EXISTS`, Oracle은 ORA-00955/01430만 삼키는 PL/SQL 블록).

---

## 실행 방법

```bash
# MSSQL
sqlcmd -S 서버,1433 -d WIKIHUB -U 계정 -i sql/mssql/01_create_all.sql
sqlcmd -S 서버,1433 -d WIKIHUB -U 계정 -i sql/mssql/03_seed_roles.sql

# PostgreSQL
psql -h 서버 -d wikihub -U 계정 -f sql/postgresql/01_create_all.sql

# Oracle  (SQL*Plus는 PL/SQL 블록 종료를 위해 파일 그대로 실행하면 된다)
sqlplus 계정/비밀번호@서버:1521/서비스 @sql/oracle/01_create_all.sql

# SQLite
sqlite3 wikihub.db < sql/sqlite/01_create_all.sql
```

---

## 표 구성

```
                      ┌──────────────────────┐
                      │  wikihub_persons     │  담당자 마스터
                      │  회사·소속·사번      │  (회사명 + 사번) = 유일
                      │  성명·전화·이메일     │
                      └──────────┬───────────┘
             ┌───────────────────┼────────────────────┬──────────────────┐
             │                   │                    │                  │
   ┌─────────▼────────┐ ┌────────▼─────────┐ ┌────────▼───────┐ ┌────────▼────────┐
   │ system_owners    │ │ access_grants    │ │ accounts       │ │ access_log      │
   │ 누가 담당인가     │ │ 무엇을 볼 수     │ │ 로그인 아이디   │ │ 누가 무엇을     │
   │ owner/maintainer │ │ 있는가(범위·역할) │ │ (SSO 연동 자리) │ │ 봤는가·막혔는가 │
   └─────────┬────────┘ └────────┬─────────┘ └────────────────┘ └─────────────────┘
             │                   │
             │            ┌──────▼──────┐      ┌──────────────┐
             │            │ roles       │──────│ permissions  │
             │            │ admin/…     │ role_permissions    │
             │            └─────────────┘      └──────────────┘
             │
   ┌─────────▼──────────────────────────────────────────────────────┐
   │ systems ── components ── pages ── page_versions ── content_blobs │  기존 위키 본체
   │                       └─ api_endpoints / db_objects /            │
   │                          frontend_routes / external_links        │  구조화 인덱스
   │                       └─ publish_log                             │  발행 기록
   └──────────────────────────────────────────────────────────────────┘
```

담당자 도입으로 기존 표에 붙은 컬럼은 셋뿐이다. 전부 NULL 허용이라 기존 행에 영향이 없다.

| 표 | 추가 컬럼 | 뜻 |
|----|----------|----|
| `wikihub_systems` | `owner_person_id` | 시스템 대표 담당자 |
| `wikihub_page_versions` | `author_person_id` | 이 버전을 올린 사람 (기존 `author` 문자열은 표시용으로 유지) |
| `wikihub_publish_log` | `publisher_person_id` | 이 발행을 실행한 사람 |

### 왜 외래키가 없나

기존 `wikihub_*` 표가 전부 논리적 참조만 쓴다 — 발행은 시스템·컴포넌트·페이지가 서로 다른
시점에 들어오는 스냅샷 적재라, 물리 FK가 있으면 적재 순서에 묶여 부분 발행이 실패한다.
새 표도 같은 규칙을 따르고, 대신 조인에 쓰이는 컬럼마다 인덱스를 뒀다. 참조 무결성은
`store.py`의 단일 쓰기 경로에서 지킨다.

### 사번이 아니라 (회사명 + 사번)이 키인 이유

ITO 현장은 원청·협력사 인원이 섞인다. 사번만으로는 회사가 다른 동일 사번이 한 사람으로
합쳐진다. `uq_persons_company_empno`가 이걸 막는다.

---

## 권한은 표만 먼저, 강제는 스위치로

`wikihub_schema_meta`의 `access_control` 값이 **기본 `off`** 다. 이 상태에서는 역할·권한 표가
채워져 있어도 아무것도 차단하지 않는다 — 지금 쓰는 방식 그대로 동작한다.

```sql
-- 지금 상태 확인
SELECT meta_key, meta_value FROM wikihub_schema_meta;

-- 권한을 다 부여한 뒤에 켠다. 먼저 켜면 아무도 못 본다.
UPDATE wikihub_schema_meta SET meta_value = 'on' WHERE meta_key = 'access_control';
```

권한 부여는 SQL로 직접 하지 말고 CLI를 쓰는 편이 안전하다(사번으로 사람을 찾아 검증한다).

```powershell
python agents/lib/wikihub_db/publish.py --root . --list-owners
python agents/lib/wikihub_db/publish.py --root . --grant "20231234=reader" --system-key ORDER
python agents/lib/wikihub_db/publish.py --root . --list-grants
python agents/lib/wikihub_db/publish.py --root . --access-control on
```

| 역할 | 할 수 있는 일 |
|------|-------------|
| `reader` | 열람 · 검색 · 버전 이력 보기 |
| `editor` | reader + 발행 · 되돌리기 |
| `manager` | editor + 시스템 정보 수정 · 권한 부여 |
| `admin` | 전부 (범위 `global`로 주면 모든 시스템) |

범위는 `global`(허브 전체) · `system`(시스템 하나) · `component`(레이어 하나) 세 가지이고
위에서 아래로 상속된다. 회수는 행을 지우지 않고 `is_active=0`으로 두어 이력이 남는다.

> 실제 차단은 조회 서버(`wiki-hub-serve`)가 한다. 이 스크립트와 `store.can()`은 판정 근거를
> 준비해 두는 것까지다 — 서버가 배포되면 그때부터 화면에 적용된다.
