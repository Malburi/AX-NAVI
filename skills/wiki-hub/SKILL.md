---
name: wiki-hub
description: 별도 프로젝트 wiki-hub를 실행해 여러 시스템의 wiki를 한 사이트에서 통합 열람·검색·관리한다. 시스템 목록, 백엔드/프론트엔드 컴포넌트 구분, 전 시스템 문서 전문 검색, API·DB테이블·화면·외부연동 교차 인덱스, 페이지별 버전 이력·비교·복원을 제공한다. "위키 허브 띄워줘", "통합 위키 보여줘", "시스템 위키 목록", "wiki 검색", "위키 버전 비교", "이전 버전으로 되돌려줘", "wiki hub", "중앙 위키 관리", "DB 위키 보여줘" 요청 시 트리거.
---

# Wiki Hub (오케스트레이터)

`publish-wiki`(harness 플러그인에 내장된 `agents/lib/wikihub_db/publish.py`가 직접 DB에 씀)로
발행된 모든 시스템의 wiki를 한 사이트에서 다룬다. 읽기 전용 뷰어가 아니라 **관리 도구**다.
검색·버전 비교·복원·시스템 정보 편집을 포함한다.

이 스킬이 실행하는 `wiki-hub-serve`는 harness 플러그인이 아니라 **별도 프로젝트 wiki-hub**의
콘솔 명령이다(운영 계획 수립 중 — 서버로 배포되면 그 서버를 호출). harness는 폴더 wiki를
만들고 DB에도 직접 저장하지만, 여러 시스템을 한 사이트에서 통합 열람·관리하는 화면은
계속 이 별도 서버 쪽에 있다 — 같은 DB(스키마가 harness의 `agents/lib/wikihub_db/models.py`와
동일)를 읽기만 하므로 harness가 저장한 데이터를 그대로 보여줄 수 있다.

---

## 위키를 보는 방법 두 가지

harness가 만드는 wiki는 저장 위치에 따라 보는 방법이 다르다. 사용자가 "위키 보여줘"라고만
말하면 어느 쪽을 원하는지 확인한다.

| | 폴더 wiki | DB(중앙 허브) wiki |
|---|---|---|
| 저장 위치 | 이 프로젝트의 `_workspace/wiki/` 폴더 | wiki-hub의 중앙 DB (여러 프로젝트 공유) |
| 보는 방법 | `_workspace/wiki/serve.bat` 실행 → `http://localhost:3501` | `wiki-hub-serve` 실행 → `http://localhost:8800` |
| 범위 | 이 프로젝트 하나 | 발행된 모든 시스템 (시스템·컴포넌트로 구조화, API/DB/화면/외부연동까지 별도 인덱스 테이블로 세분 저장) |
| 버전 이력 | 없음 (매번 덮어씀) | 있음 (비교·되돌리기 가능) |
| 만드는 스킬 | `generate-wiki` | `generate-wiki` 다음 `publish-wiki` |

**"이 프로젝트 wiki만 보고 싶다"** → `generate-wiki`가 이미 만든 `_workspace/wiki/serve.bat` 안내로 끝. 이 스킬은
필요 없다.
**"여러 시스템을 한 곳에서 보고 싶다" / "버전 이력을 보고 싶다"** → 이 스킬(`wiki-hub-serve`)로 진행.

---

## Phase 0: wiki-hub 설치·데이터 확인

```powershell
wiki-hub-serve --help
```

명령이 없으면 wiki-hub-serve(별도 서버, 운영 계획 수립 중)가 아직 배포되지 않은 것이다 —
"서버 배포 전이라 통합 조회 화면은 아직 없습니다. 데이터는 이미 DB에 저장돼있으니(`publish-wiki`),
서버 배포 후 그대로 보입니다"라고 안내하고 중단. (`publish-wiki`의 DB 저장 자체는 이 명령과
무관하게 항상 가능 — Phase 0의 SQLAlchemy 확인만 필요.)

허브는 **발행된 데이터만** 보여준다. 아직 아무 시스템도 발행하지 않았다면 `publish-wiki`를 먼저 안내한다.

---

## Phase 1: 허브 실행

```powershell
wiki-hub-serve --root "[절대경로]" --port 8800
```

`--root`는 접속 정보(`.env`)가 있는 폴더다 — 보통 지금 발행한 harness 프로젝트 루트를 그대로 쓴다.
여러 프로젝트가 같은 DB를 공유하므로 어느 프로젝트 루트에서 실행해도 등록된 시스템은 전부 보인다.

| 옵션 | 설명 |
|------|------|
| `--engine` | `.env`의 `WIKI_DB_ENGINE`을 1회성으로 덮어씀 (mssql/postgresql/oracle/sqlite) |
| `--host 0.0.0.0` | 팀에 공유 (인증 없음 — 사내망 안에서만) |
| `--read-only` | 되돌리기·정보 수정 비활성화 (열람 전용 배포용) |
| `--port` | 기본 8800 |

실행 후 브라우저로 `http://127.0.0.1:8800` 접속을 안내한다. 종료는 Ctrl+C.

---

## Phase 2: 화면 안내

| 하려는 일 | 화면 |
|---------|------|
| 어떤 시스템이 등록돼 있나 | `/` — 시스템 카드, 색 배지가 레이어 |
| 한 시스템의 구성과 페이지 | `/s/[시스템키]` — 컴포넌트 표 + 페이지 목록 + 정보 편집 |
| 문서 내용에서 찾기 | `/search` — 전 시스템 본문 검색, 시스템·레이어로 좁힐 수 있음 |
| 이 API를 누가 쓰나 | `/index/api` |
| 이 테이블을 누가 쓰나 | `/index/db` |
| 어떤 화면이 어떤 API를 부르나 | `/index/route` |
| 외부 시스템 연동 지점 | `/index/external` |
| 최근에 뭐가 바뀌었나 | `/changes` — 누가(성명·사번) 올렸는지 함께 보인다 |
| 이 시스템 담당자가 누구인가 | `/s/[시스템키]` 담당자 표 — 회사·소속·사번·성명·전화·이메일 |
| 페이지 내용 보기 | `/page/[시스템]/[컴포넌트]/[경로]` (`?v=N`으로 특정 버전) |

허브 화면은 외부 CDN을 쓰지 않는다(서버가 직접 렌더링) — 폐쇄망에서도 그대로 뜬다.

---

## Phase 3: 버전 관리 작업

### 이력·되돌리기

`/history/[시스템]/[컴포넌트]/[페이지]`에서 버전을 최신순으로 본다. "v(이전)과 비교"로 diff를 보고,
"이 버전으로 되돌리기"를 누르면 **새 버전이 하나 더 쌓인다** (이력이 줄지 않는다).

### 되돌린 내용을 실제 프로젝트로 가져오기

허브에서 되돌린 것은 DB 안의 내용이다. harness 프로젝트 폴더에도 반영하려면 회수한다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/wikihub_db/publish.py" --root "[절대경로]" `
  --system-key "[시스템키]" --component-key "[컴포넌트키]" --pull --wiki-dir "[절대경로]/_workspace/wiki"
```

> 다음 `generate-wiki`를 실행하면 harness 산출물 기준으로 다시 덮어써진다. 되돌리기는 문서 이력
  추적용이지 소스 코드 롤백이 아니다.

---

## Phase 3.5: 담당자와 열람 권한

발행할 때 받은 담당자 정보(회사·소속·사번·성명·전화·이메일)는 `wikihub_persons`에 사람 단위로
쌓인다. 버전 이력의 "누가"와 시스템 담당자 표가 같은 사람을 가리키므로, 장애 시 문서를
뒤지지 않고 담당자와 연락처를 바로 얻을 수 있다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/wikihub_db/publish.py" --root "[절대경로]" --list-owners
```

열람 권한은 **표와 기본 역할까지 준비돼 있고 강제만 꺼져 있다**(`access_control=off`).
지금은 발행된 모든 시스템을 누구나 볼 수 있고, 이는 예전과 같은 동작이다.

| 역할 | 할 수 있는 일 |
|------|-------------|
| `reader` | 열람 · 검색 · 버전 이력 |
| `editor` | reader + 발행 · 되돌리기 |
| `manager` | editor + 시스템 정보 수정 · 권한 부여 |
| `admin` | 전부 (`--grant-scope global`이면 모든 시스템) |

사용자가 "특정 사람만 보게 하고 싶다"고 하면 순서를 지킨다 — **부여를 모두 끝낸 뒤 켠다.**
먼저 켜면 권한을 못 받은 사람이 즉시 전부 차단된다.

```powershell
# 1) 부여
publish.py --root "[절대경로]" --grant "20231234=reader" --system-key ORDER
# 2) 확인
publish.py --root "[절대경로]" --list-grants
# 3) 사용자 확인을 받고 마지막에 켠다
publish.py --root "[절대경로]" --access-control on
```

실제 차단은 이 조회 서버가 수행한다 — 서버 배포 전에는 스위치를 켜도 화면 동작이 달라지지
않는다(데이터·판정 근거만 준비된 상태).

---

## Phase 4: 시스템 목록 관리

`/s/[시스템키]` 상단 폼에서 표시 이름·설명·담당·태그를 고친다. 여기서 고친 표시 이름은 다음 발행 때
`--system-name`을 다시 주지 않는 한 되돌아가지 않는다.

운영이 끝난 시스템은 같은 폼의 "보관"으로 목록에서 내린다. 데이터는 지워지지 않는다.

---

## 원칙

### 허브는 발행된 것만 보여준다
코드를 다시 읽지 않는다. 화면이 옛날 내용이면 그 시스템에서 `generate-wiki` → `publish-wiki`를
다시 돌려야 한다.

### 인덱스 표는 스냅샷이다
`/index/*`의 API·테이블 목록은 발행 시점 값이다. 실제 영향도 판단은 `impact-analyzer`와
`api-bridge`의 라이브 재분석으로 한다.

### DB 엔진을 바꿔도 이 스킬은 그대로다
MSSQL에서 PostgreSQL이나 Oracle로 옮기더라도 `wiki-hub-serve --root ...` 실행법은 같다.
`.env`의 `WIKI_DB_ENGINE`만 바뀐다 — wiki-hub가 SQLAlchemy로 방언 차이를 흡수하기 때문이다.
