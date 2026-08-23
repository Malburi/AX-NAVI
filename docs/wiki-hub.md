# 시스템 위키 중앙 DB (wiki-hub)

여러 시스템의 harness wiki를 한 DB에 모으고, 버전 관리하는 구조를 설명한다.
**저장(쓰기)과 조회(열람·관리)를 서로 다른 곳에 뒀다** — 저장은 harness 플러그인에
내장돼 있고, 조회는 별도 프로젝트 `wiki-hub`가 서버로 떠서(운영 계획 수립 중) 전담한다.

---

## 왜 나눴는가

harness 플러그인은 Claude Code 마켓플레이스로 설치되어 여러 대상 프로젝트 각각에 흩어져
동작한다. 반면 "여러 시스템의 wiki를 한 곳에 모아 보는 조회 화면"은 그 반대 성격이다 —
한 번 설치해서 계속 떠 있어야 하는 서버다.

문제는 **저장(발행) 기능까지 그 별도 서버/패키지 설치에 의존하면 안 된다는 것**이었다 —
대부분의 PC에는 wiki-hub가 설치돼 있지 않아, "발행"이 wiki-hub 로컬 설치를 전제로 하면
정작 DB 저장 자체가 되지 않는 프로젝트가 태반이었다(2026-07-31 발견). 그래서 저장에
필요한 스키마·버전관리 로직(`models.py`/`store.py`/`config.py`/`index_extract.py`/
`publish.py`)만 harness 플러그인 안(`agents/lib/wikihub_db/`)에 그대로 옮겨왔다 — 이
경로는 `SQLAlchemy` + 엔진별 드라이버(pymssql 등)만 있으면 되고, wiki-hub 프로젝트를
따로 clone·설치할 필요가 없다.

조회(열람·검색·버전 비교·되돌리기, `wiki-hub-serve`)는 여전히 별도 프로젝트다 — 여러
harness 프로젝트가 쓴 같은 DB를 한 사이트에서 통합해서 보여주는 건 "한 번 설치해서 계속
떠 있는 서버"의 역할이라 harness 플러그인 구조와 안 맞기 때문이다.

```
harness 플러그인 (여러 프로젝트에 각각 설치)          wiki-hub (별도 서버, 운영 계획 수립 중)
──────────────────────────────────                ─────────────────────────
generate-wiki                                      wiki-hub-serve  (열람·검색·버전관리, view 전용)
  → _workspace/wiki/ 폴더 생성 (zero-LLM)                ▲
                                                          │ (같은 DB를 읽기만 함)
publish-wiki 스킬                                        │
  → agents/lib/wikihub_db/publish.py 직접 실행 ─────────►│
    (harness 플러그인에 내장, wiki-hub 설치 불필요)        │
                                                          ▼
                                              MSSQL / PostgreSQL / Oracle / SQLite
```

`agents/lib/wikihub_db/`는 wiki-hub 프로젝트의 스키마·저장 로직을 그대로 옮긴 사본이라
**같은 테이블에 같은 방식으로 쓴다** — 그래서 wiki-hub-serve가 나중에 서버로 뜨면
harness가 이미 써 둔 데이터를 그대로 읽어 보여줄 수 있다. 스키마 정의(`models.py`)가
어긋나면 두 쪽이 갈라지므로, wiki-hub 프로젝트 쪽 스키마가 바뀌면 이 사본도 함께
갱신해야 한다(현재는 수동 동기화 — 자동 동기화 방안은 없음).

`_workspace/**/*.json`(call_graph·schema·sql_usage 등 harness index + writer_decisions.json
등)도 `_workspace/wiki/*.md`·`*.html`과 동일하게 발행·버전관리된다. 여러 인원이 한 프로젝트를 나눠
맡을 때, 한 사람이 harness-init을 돌려 만든 분석 인덱스 원본을 발행해두면 다른
팀원은 harness-init을 다시 돌리지 않고 `--pull`로 그 JSON을 자기 로컬
`_workspace/`의 원래 경로로 받아 impact-analyzer 등 에이전트에 바로 재사용할 수 있다 —
harness-init 재실행 비용(토큰)을 아끼기 위한 용도다.

---

## 위키를 보는 두 가지 방법

| | 폴더 wiki | DB(중앙 저장) wiki |
|---|---|---|
| 만드는 명령 | `generate-wiki` (harness) | `generate-wiki` 다음 `publish-wiki` (harness 내장, wiki-hub 설치 불필요) |
| 저장 위치 | 이 프로젝트의 `_workspace/wiki/` 폴더 | 조직 공용 DB(`wikihub_*` 테이블) |
| 보는 명령 | `_workspace/wiki/serve.bat` → `:3501` | `wiki-hub-serve`(별도 서버, 운영 계획 수립 중) → 서버 배포 시 URL 안내 예정 |
| 범위 | 이 프로젝트 하나 | 발행된 모든 시스템(시스템·컴포넌트로 구조화) |
| 버전 이력 | 없음 | 있음 (비교·되돌리기 — 서버 배포 후 조회 가능, 저장 자체는 지금도 됨) |

**기본은 폴더다.** `generate-wiki`는 질문 없이 항상 폴더에 wiki를 만든다. DB 발행은
완료 후 선택 질문으로만 나타난다 — 필요할 때만 켜는 상위 계층 기능이다. **DB 저장은
wiki-hub-serve가 아직 배포되지 않았어도 지금 바로 된다** — 저장과 조회가 분리돼 있기
때문이다.

---

## 스키마

시스템/컴포넌트/페이지/버전/구조화 인덱스 전부 `agents/lib/wikihub_db/models.py`
한 곳에서 SQLAlchemy Core 테이블로 정의된다(wiki-hub 프로젝트의 `wikihub/models.py`와
바이트 단위로 동일해야 한다). 엔진별 차이(NVARCHAR(MAX)/CLOB/TEXT, IDENTITY 방식,
TOP/LIMIT/FETCH FIRST)는 `.with_variant()`와 `select().limit()`으로 흡수되므로, 이
문서 바깥 어디에도 엔진별 SQL 분기가 없다.

| 테이블 | 담는 것 |
|--------|--------|
| `wikihub_systems` | 시스템 마스터 — 표시이름·설명·담당·태그·보관 여부 |
| `wikihub_components` | 시스템 안의 레이어 — backend/frontend/fullstack/batch/mobile/common |
| `wikihub_pages` | 현재 본문 (시스템·컴포넌트·경로 3키, 체크섬·현재버전). `_workspace/wiki/*.md`·`*.html`과 `_workspace/**/*.json`이 같은 테이블에 저장되며, 저장된 경로 문자열이 `_workspace/`로 시작하는 쪽(위키 문서는 접두사 없이 `Home.md`처럼 wiki_dir 기준 상대경로)이 JSON 원본이다 |
| `wikihub_page_versions` | 버전 이력 — 체크섬이 바뀔 때만 새 행 (JSON도 동일) |
| `wikihub_api_endpoints` / `wikihub_db_objects` / `wikihub_frontend_routes` / `wikihub_external_links` | 백엔드·프론트엔드 정보를 문서와 별도로 분리한 구조화 인덱스 |
| `wikihub_publish_log` | 발행 실행 기록 — 누가 실행했는지(`publisher_person_id`) 포함 |
| `wikihub_persons` | 담당자 마스터 — 회사명·소속·사번·성명·전화번호·이메일. (회사명 + 사번)이 유일 키 |
| `wikihub_system_owners` | 시스템·컴포넌트별 담당자 연결 — `owner`/`maintainer`/`publisher` |
| `wikihub_roles` / `wikihub_permissions` / `wikihub_role_permissions` | 역할과 역할별 권한 (기본값 4역할 7권한이 자동으로 채워진다) |
| `wikihub_access_grants` | 사람 × 범위(global/system/component) × 역할. 회수는 `is_active=0`으로 남긴다 |
| `wikihub_accounts` / `wikihub_access_log` | 로그인 계정(SSO 연동 자리)과 열람·차단 감사 로그 |
| `wikihub_schema_meta` | `schema_version`과 접근 통제 스위치 `access_control`(기본 `off`) |

### 담당자와 권한을 이 시점에 넣은 이유

권한을 "나중에 한꺼번에" 붙이면 그때 스키마를 다시 흔들어야 하고, 그 사이 쌓인 발행 기록에는
사람이 연결돼 있지 않아 소급이 안 된다. 그래서 **사람 마스터와 권한 표는 지금 만들고, 강제만
스위치로 미뤘다** — `access_control`이 `off`인 동안 열람 동작은 예전과 완전히 같다.

발행자를 예전처럼 `author` 문자열로만 남기면 같은 사람이 여러 표기로 흩어져 사람 단위로 묶을
수도, 권한을 걸 수도 없다. 사번만으로 키를 잡지 않은 것은 원청·협력사 인원이 섞이는 ITO 현장
때문이다 — 회사가 다른 동일 사번이 한 사람으로 합쳐지는 사고를 (회사명 + 사번) 유일 제약으로 막는다.

기존 표에 붙은 컬럼은 셋뿐이고 전부 NULL 허용이라 기존 행에 영향이 없다
(`systems.owner_person_id`, `page_versions.author_person_id`, `publish_log.publisher_person_id`).
접속 시 `store.ensure_schema()`가 빠진 컬럼만 골라 ALTER 로 채운다 — 이미 운영 중인 DB도
스크립트를 손으로 돌리지 않고 그대로 올라간다. DDL을 미리 검토받아야 하는 조직은
[`sql/`](../sql/README.md)의 엔진별 스크립트를 쓴다(자동 생성 결과와 대조 검증됨).

버전은 체크섬이 바뀔 때만 늘어난다. 삭제는 표시만 하고 본문·이력은 남긴다. 되돌리기는
과거 버전을 새 버전으로 추가하는 방식이라 이력이 줄지 않는다(되돌리기·비교 화면은
wiki-hub-serve 배포 후 사용 가능 — 데이터 자체는 지금 저장되는 버전 이력에 이미 쌓인다).

---

## 지원 DB와 전환 방법

| 엔진 | 드라이버 | 비고 |
|------|---------|------|
| MSSQL | `pymssql` | 1차 대상 |
| PostgreSQL | `psycopg2-binary` | |
| Oracle | `oracledb` (thin — Instant Client 불필요) | |
| SQLite | 표준 라이브러리 | 1인 사용·오프라인·시험 |

`.env`의 `WIKI_DB_ENGINE` 하나만 바꾸면 엔진이 바뀐다. 스키마는 최초 접속 시
자동 생성하므로 별도 마이그레이션 스크립트를 손으로 돌릴 필요가 없다.

```ini
WIKI_DB_ENGINE=mssql        # 지금 이렇게 시작해도
WIKI_DB_ENGINE=postgresql   # 나중에 이렇게 바꿀 수 있다 — harness 쪽 스킬은 그대로
```

---

## 저장에 필요한 것 (설치 아님 — pip 패키지만)

`agents/lib/wikihub_db/`는 harness 플러그인에 이미 포함돼 있다. 필요한 건 파이썬
패키지뿐이다.

```bash
pip install sqlalchemy pymssql        # MSSQL 기준. postgresql=psycopg2-binary, oracle=oracledb
```

wiki-hub-serve(조회 서버)는 별도 배포 대상이라 이 문서 범위 밖이다 — 배포되면 이
문서에 접속 방법을 추가한다.

---

## harness 쪽에서 쓰는 법

1. `generate-wiki` — 폴더 wiki 생성 (항상 실행, 기본값)
2. 완료 후 "중앙 DB에도 발행할까요?" 질문에 Y → `publish-wiki` 스킬 →
   `agents/lib/wikihub_db/publish.py` 직접 실행(내장, wiki-hub 설치 불필요)
3. 여러 시스템을 한 곳에서 보고 싶을 때 → wiki-hub-serve 배포 후 그 서버로 접속(운영 계획 수립 중)

백엔드·프론트엔드가 별도 저장소면 **양쪽에서 각각 발행**한다 — 같은 `--system-key`,
다른 `--component-type`을 쓰면 나중에 조회 화면에서 한 시스템 아래 두 레이어로 묶인다.

여러 인원이 한 프로젝트를 나눠 맡을 때: 한 사람이 harness-init을 돌려 발행해두면,
다른 팀원은 `python agents/lib/wikihub_db/publish.py --root [자기 로컬 경로] --pull --system-key ... --component-key ...`
로 위키 문서 + `_workspace/**/*.json`을 한 번에 받는다. JSON은 project_root 기준
원래 경로(`_workspace/index/...` 등)로 복원되므로 harness-init을 다시 돌릴 필요 없이
impact-analyzer 등 인덱스 의존 에이전트를 바로 쓸 수 있다.

과거 harness의 단일 테이블 DB 저장(v1, 지금은 제거됨) 데이터가 남아있는 프로젝트라면
`python agents/lib/wikihub_db/publish.py --migrate-v1`으로 새 스키마로 옮긴다.

---

## 검증 범위와 한계

`agents/lib/wikihub_db/`는 wiki-hub 프로젝트 코드를 그대로 옮긴 사본이라 검증도 같은
기준을 따른다. SQLite로 dry-run·발행·`--list` end-to-end 실행 검증 완료. 조직 공용
MSSQL DB(기존에 원본 wiki-hub CLI로 발행돼 있던 5개 시스템)에 대해서도 `--list`로
실제 접속해 전부 정상 조회됨을 확인했다 — 스키마가 바이트 단위로 같아 완전히 호환된다.
PostgreSQL/Oracle은 원본 wiki-hub 쪽의 SQLAlchemy 오프라인 방언 컴파일 검증(`wiki-hub/tests/`)에
의존한다.

스키마를 손으로 두 곳(harness의 `agents/lib/wikihub_db/models.py`, wiki-hub의
`wikihub/models.py`)에 유지하는 것 자체가 리스크다 — 한쪽만 고치면 어긋난다. 지금은
수동 동기화이며, 자동화(예: wiki-hub 쪽 스키마를 harness가 빌드 시점에 vendor-sync)는
아직 없다.
