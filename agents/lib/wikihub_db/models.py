# 모든 지원 DB 엔진(MSSQL/PostgreSQL/Oracle/SQLite)이 공유하는 단일 스키마 정의
# 별도 프로젝트 wiki-hub(E:/AI/wiki-hub)의 wikihub/models.py를 그대로 옮긴 사본이다 —
# 발행(쓰기) 경로만 harness 플러그인에 내장해 wiki-hub 전체 설치 없이 DB 저장이 되게 하기 위함.
# 스키마는 wiki-hub와 완전히 동일해야 나중에 wiki-hub-serve(별도 서버)가 같은 DB를 그대로 읽을 수 있다.
"""models.py — 테이블 정의는 여기 한 곳뿐이다.

방언 차이(IDENTITY 방식, TEXT/CLOB, BOOLEAN, 유니코드 문자열 길이 기준)는 컬럼 타입에
`.with_variant()`로 박아 넣고, SQLAlchemy Core가 각 엔진에 맞는 SQL로 컴파일하게 맡긴다.
이 파일 밖에서는 CREATE TABLE 문이나 TOP/LIMIT/FETCH FIRST 같은 방언 분기를 두지 않는다.
"""

from sqlalchemy import (
    MetaData, Table, Column, Integer, String, Text, Boolean, DateTime, LargeBinary,
    Identity, UniqueConstraint, Index,
)
from sqlalchemy.dialects import mssql, postgresql, oracle


def big_text():
    """페이지 본문처럼 길이 제한이 없어야 하는 텍스트.
    mssql→NVARCHAR(MAX), oracle→CLOB, postgresql→TEXT, sqlite(기본)→TEXT."""
    return (
        Text()
        .with_variant(mssql.NVARCHAR("max"), "mssql")
        .with_variant(oracle.CLOB(), "oracle")
        .with_variant(postgresql.TEXT(), "postgresql")
    )


def big_blob():
    """압축된 페이지 본문처럼 길이 제한이 없어야 하는 이진 데이터.
    mssql→VARBINARY(MAX), oracle→BLOB, postgresql→BYTEA, sqlite(기본)→BLOB."""
    return (
        LargeBinary()
        .with_variant(mssql.VARBINARY("max"), "mssql")
        .with_variant(oracle.BLOB(), "oracle")
        .with_variant(postgresql.BYTEA(), "postgresql")
    )


def utext(n):
    """길이 제한이 있는 유니코드 문자열. MSSQL은 기본 String이 VARCHAR(바이트·코드페이지 기준)로
    컴파일되어 한글 등 멀티바이트 문자가 깨지므로 NVARCHAR로 바꾼다. Oracle VARCHAR2도 기본이
    바이트 길이 기준이라 NVARCHAR2(문자 길이 기준)로 바꿔 조기 절단을 막는다. PostgreSQL/SQLite는
    기본 String이 이미 유니코드 문자 기준이라 그대로 둔다."""
    return String(n).with_variant(mssql.NVARCHAR(n), "mssql").with_variant(oracle.NVARCHAR2(n), "oracle")


def ts():
    """타임스탬프. mssql만 DATETIME2로 승격(정밀도) — 나머지는 기본 DateTime으로 충분."""
    return DateTime().with_variant(mssql.DATETIME2(), "mssql")


metadata = MetaData()

T_SYSTEMS = "wikihub_systems"
T_COMPONENTS = "wikihub_components"
T_PAGES = "wikihub_pages"
T_VERSIONS = "wikihub_page_versions"
T_API = "wikihub_api_endpoints"
T_DB = "wikihub_db_objects"
T_ROUTE = "wikihub_frontend_routes"
T_EXT = "wikihub_external_links"
T_LOG = "wikihub_publish_log"
T_BLOBS = "wikihub_content_blobs"
T_META = "wikihub_schema_meta"
T_PERSONS = "wikihub_persons"
T_SYS_OWNERS = "wikihub_system_owners"
T_ROLES = "wikihub_roles"
T_PERMS = "wikihub_permissions"
T_ROLE_PERMS = "wikihub_role_permissions"
T_GRANTS = "wikihub_access_grants"
T_ACCOUNTS = "wikihub_accounts"
T_ACCESS_LOG = "wikihub_access_log"

COMPONENT_TYPES = ["backend", "frontend", "fullstack", "batch", "mobile", "common"]

# 스키마 버전 — 컬럼·테이블이 늘어나면 올린다. wikihub_schema_meta 에 기록되고,
# 나중에 wiki-hub(조회 서버)가 자기가 아는 버전보다 낮은 DB를 만났을 때 판단 근거로 쓴다.
SCHEMA_VERSION = 2

# 담당자가 시스템·컴포넌트에 대해 갖는 "책임" 구분 (권한과는 별개 — 권한은 wikihub_access_grants).
OWNER_ROLES = ["owner", "maintainer", "publisher"]

# 권한 부여 범위. global=전체 허브, system=시스템 하나, component=시스템 안의 한 레이어.
SCOPE_TYPES = ["global", "system", "component"]

# 기본 역할과 각 역할이 갖는 권한 — ensure_schema() 가 비어 있을 때만 채운다(seed).
# 지금은 아무도 강제하지 않는다. 접근 통제 스위치(access_control)가 'on' 이 되는 시점부터
# wiki-hub 조회 서버가 이 표를 근거로 열람을 허용/차단한다.
BUILTIN_PERMISSIONS = [
    ("wiki.view", "위키 열람", "발행된 페이지 본문과 구조화 인덱스를 본다."),
    ("wiki.search", "위키 검색", "전 시스템 본문 검색을 쓴다."),
    ("wiki.history", "버전 이력 열람", "페이지 버전 목록과 비교 화면을 본다."),
    ("wiki.publish", "위키 발행", "harness 산출물을 이 시스템으로 발행한다."),
    ("wiki.revert", "버전 되돌리기", "과거 버전으로 되돌린다."),
    ("system.manage", "시스템 정보 관리", "표시 이름·설명·담당자·보관 여부를 고친다."),
    ("acl.manage", "권한 관리", "다른 사람에게 역할을 부여하거나 회수한다."),
]

BUILTIN_ROLES = [
    ("admin", "관리자", "허브 전체를 관리한다.", 40),
    ("manager", "시스템 관리자", "맡은 시스템의 정보와 권한을 관리한다.", 30),
    ("editor", "발행자", "맡은 시스템에 위키를 발행한다.", 20),
    ("reader", "열람자", "허용된 시스템의 위키를 읽는다.", 10),
]

BUILTIN_ROLE_PERMISSIONS = {
    "admin": [p[0] for p in BUILTIN_PERMISSIONS],
    "manager": ["wiki.view", "wiki.search", "wiki.history", "wiki.publish", "wiki.revert",
                "system.manage", "acl.manage"],
    "editor": ["wiki.view", "wiki.search", "wiki.history", "wiki.publish", "wiki.revert"],
    "reader": ["wiki.view", "wiki.search", "wiki.history"],
}

systems = Table(
    T_SYSTEMS, metadata,
    Column("system_key", utext(100), primary_key=True),
    Column("display_name", utext(200), nullable=False),
    Column("description", utext(1000), server_default=""),
    Column("owner", utext(200), server_default=""),          # 자유 입력(구 방식) — 하위호환 위해 유지
    Column("owner_person_id", Integer, nullable=True),        # wikihub_persons.person_id — 대표 담당자
    Column("repo_url", utext(500), server_default=""),
    Column("tags", utext(500), server_default=""),
    Column("is_archived", Boolean, nullable=False, default=False),
    Column("created_at", ts(), nullable=False),
    Column("updated_at", ts(), nullable=False),
)

components = Table(
    T_COMPONENTS, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("component_type", utext(30), nullable=False),
    Column("display_name", utext(200), server_default=""),
    Column("repo_root", utext(500), server_default=""),
    Column("stack", utext(300), server_default=""),
    Column("created_at", ts(), nullable=False),
    Column("updated_at", ts(), nullable=False),
    UniqueConstraint("system_key", "component_key", name="uq_components_key"),
)

pages = Table(
    T_PAGES, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("page_path", utext(300), nullable=False),
    Column("title", utext(300), server_default=""),
    Column("content", big_text(), nullable=True),  # 본문은 wikihub_content_blobs 로 이동, 하위호환 위해 컬럼 유지(신규 저장은 NULL)
    Column("content_type", utext(50), nullable=False),
    Column("checksum", utext(64), nullable=False),
    Column("current_version", Integer, nullable=False, default=1),
    Column("is_deleted", Boolean, nullable=False, default=False),
    Column("created_at", ts(), nullable=False),
    Column("updated_at", ts(), nullable=False),
    UniqueConstraint("system_key", "component_key", "page_path", name="uq_pages_key"),
    Index("ix_pages_scope", "system_key", "component_key"),
)

page_versions = Table(
    T_VERSIONS, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("page_path", utext(300), nullable=False),
    Column("version_no", Integer, nullable=False),
    Column("content", big_text(), nullable=True),  # 본문은 wikihub_content_blobs 로 이동, 하위호환 위해 컬럼 유지(신규 저장은 NULL)
    Column("content_type", utext(50), nullable=False),
    Column("checksum", utext(64), nullable=False),
    Column("change_type", utext(20), nullable=False),
    Column("change_summary", utext(500), server_default=""),
    Column("author", utext(100), server_default=""),          # 표시용 문자열 "성명(사번)" — 사람이 지워져도 남는다
    Column("author_person_id", Integer, nullable=True),        # wikihub_persons.person_id — 실제 발행자
    Column("created_at", ts(), nullable=False),
    UniqueConstraint("system_key", "component_key", "page_path", "version_no", name="uq_versions_key"),
    Index("ix_versions_scope", "system_key", "component_key", "page_path"),
)

api_endpoints = Table(
    T_API, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("method", utext(10), server_default=""),
    Column("path", utext(500), server_default=""),
    Column("norm_path", utext(500), server_default=""),
    Column("handler", utext(300), server_default=""),
    Column("source_file", utext(500), server_default=""),
    Column("auth_required", Boolean, nullable=False, default=False),
    Column("note", utext(500), server_default=""),
    Column("snapshot_at", ts(), nullable=False),
    Index("ix_api_norm_path", "norm_path"),
)

db_objects = Table(
    T_DB, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("table_name", utext(300), nullable=False),
    Column("column_count", Integer, nullable=False, default=0),
    Column("primary_key", utext(500), server_default=""),
    Column("columns_json", big_text(), server_default=""),
    Column("used_by", big_text(), server_default=""),
    Column("snapshot_at", ts(), nullable=False),
    Index("ix_db_table_name", "table_name"),
)

frontend_routes = Table(
    T_ROUTE, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("route_path", utext(500), server_default=""),
    Column("view_name", utext(300), server_default=""),
    Column("source_file", utext(500), server_default=""),
    Column("calls_api", big_text(), server_default=""),
    Column("snapshot_at", ts(), nullable=False),
)

external_links = Table(
    T_EXT, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("link_type", utext(50), server_default=""),
    Column("target", utext(500), server_default=""),
    Column("source_file", utext(500), server_default=""),
    Column("line_no", utext(20), server_default=""),
    Column("snapshot_at", ts(), nullable=False),
)

publish_log = Table(
    T_LOG, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False),
    Column("action", utext(50), nullable=False),
    Column("pages_total", Integer, nullable=False, default=0),
    Column("pages_created", Integer, nullable=False, default=0),
    Column("pages_updated", Integer, nullable=False, default=0),
    Column("pages_deleted", Integer, nullable=False, default=0),
    Column("message", utext(1000), server_default=""),
    Column("publisher_person_id", Integer, nullable=True),     # wikihub_persons.person_id — 이 발행을 실행한 담당자
    Column("created_at", ts(), nullable=False),
)

# -- 담당자 -----------------------------------------------------------------
# 발행할 때마다 "누가 올렸는지"를 문자열로만 남기면(구 author 컬럼) 나중에 사람 단위로
# 묶거나 권한을 걸 수 없다. 사람을 마스터로 분리하고, 발행 기록은 이 마스터를 가리킨다.
persons = Table(
    T_PERSONS, metadata,
    Column("person_id", Integer, Identity(start=1), primary_key=True),
    Column("company", utext(100), nullable=False),        # 회사명
    Column("department", utext(100), server_default=""),  # 소속
    Column("employee_no", utext(50), nullable=False),     # 사번 — 회사 안에서 유일
    Column("person_name", utext(100), nullable=False),    # 성명
    Column("phone", utext(50), server_default=""),        # 전화번호
    Column("email", utext(200), server_default=""),       # 이메일
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", ts(), nullable=False),
    Column("updated_at", ts(), nullable=False),
    # 사번은 회사 안에서만 유일하다 — 협력사가 섞이는 ITO 현장에서 사번만으로는 겹칠 수 있다.
    UniqueConstraint("company", "employee_no", name="uq_persons_company_empno"),
    Index("ix_persons_email", "email"),
    Index("ix_persons_name", "person_name"),
)

# 시스템·컴포넌트의 담당자. 한 사람이 여러 시스템을, 한 시스템이 여러 담당자를 가질 수 있다.
# component_key 가 빈 문자열이면 "시스템 전체 담당"을 뜻한다.
system_owners = Table(
    T_SYS_OWNERS, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("system_key", utext(100), nullable=False),
    Column("component_key", utext(100), nullable=False, server_default=""),
    Column("person_id", Integer, nullable=False),
    Column("owner_role", utext(30), nullable=False),      # owner | maintainer | publisher
    Column("note", utext(300), server_default=""),
    Column("created_at", ts(), nullable=False),
    Column("updated_at", ts(), nullable=False),
    UniqueConstraint("system_key", "component_key", "person_id", "owner_role", name="uq_owner_key"),
    Index("ix_owner_person", "person_id"),
    Index("ix_owner_scope", "system_key", "component_key"),
)

# -- 권한 (설계만 먼저, 강제는 나중) -------------------------------------------
# 지금은 표만 만들고 기본값을 채워둔다. wikihub_schema_meta 의 access_control 이
# 'on' 이 되는 시점부터 wiki-hub 조회 서버가 이 표를 근거로 열람을 허용/차단한다.
roles = Table(
    T_ROLES, metadata,
    Column("role_code", utext(30), primary_key=True),     # admin | manager | editor | reader
    Column("display_name", utext(100), nullable=False),
    Column("description", utext(300), server_default=""),
    Column("rank", Integer, nullable=False, default=0),   # 클수록 상위 역할
    Column("is_builtin", Boolean, nullable=False, default=True),
    Column("created_at", ts(), nullable=False),
)

permissions = Table(
    T_PERMS, metadata,
    Column("perm_code", utext(40), primary_key=True),     # wiki.view | wiki.publish | acl.manage ...
    Column("display_name", utext(100), nullable=False),
    Column("description", utext(300), server_default=""),
)

role_permissions = Table(
    T_ROLE_PERMS, metadata,
    Column("role_code", utext(30), primary_key=True),
    Column("perm_code", utext(40), primary_key=True),
)

# 사람 × 범위 × 역할. 범위가 global 이면 system_key/component_key 는 빈 문자열이다.
access_grants = Table(
    T_GRANTS, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("person_id", Integer, nullable=False),
    Column("scope_type", utext(20), nullable=False),      # global | system | component
    Column("system_key", utext(100), nullable=False, server_default=""),
    Column("component_key", utext(100), nullable=False, server_default=""),
    Column("role_code", utext(30), nullable=False),
    Column("granted_by_person_id", Integer, nullable=True),
    Column("granted_at", ts(), nullable=False),
    Column("expires_at", ts(), nullable=True),            # NULL이면 무기한
    Column("is_active", Boolean, nullable=False, default=True),
    UniqueConstraint("person_id", "scope_type", "system_key", "component_key", "role_code",
                     name="uq_grant_key"),
    Index("ix_grants_person", "person_id"),
    Index("ix_grants_scope", "system_key", "component_key"),
)

# 로그인 계정. 사내 SSO/LDAP 를 붙일 때 person 과 로그인 아이디를 잇는 자리 —
# 지금은 발행 경로에서 쓰지 않으므로 비어 있다.
accounts = Table(
    T_ACCOUNTS, metadata,
    Column("account_id", Integer, Identity(start=1), primary_key=True),
    Column("person_id", Integer, nullable=False),
    Column("login_id", utext(100), nullable=False),
    Column("auth_type", utext(20), nullable=False, server_default="sso"),  # local | ldap | sso
    Column("password_hash", utext(200), server_default=""),                # local 일 때만 사용
    Column("last_login_at", ts(), nullable=True),
    Column("is_locked", Boolean, nullable=False, default=False),
    Column("created_at", ts(), nullable=False),
    Column("updated_at", ts(), nullable=False),
    UniqueConstraint("login_id", name="uq_accounts_login"),
    Index("ix_accounts_person", "person_id"),
)

# 감사 로그 — 누가 무엇을 보려 했고 허용됐는지. 차단된 시도도 남긴다.
access_log = Table(
    T_ACCESS_LOG, metadata,
    Column("id", Integer, Identity(start=1), primary_key=True),
    Column("person_id", Integer, nullable=True),
    Column("login_id", utext(100), server_default=""),    # 아직 사람으로 식별 안 된 접근 대비
    Column("action", utext(30), nullable=False),          # view | search | publish | revert | grant | login
    Column("system_key", utext(100), server_default=""),
    Column("component_key", utext(100), server_default=""),
    Column("page_path", utext(300), server_default=""),
    Column("result", utext(20), nullable=False),          # allowed | denied
    Column("client_ip", utext(50), server_default=""),
    Column("created_at", ts(), nullable=False),
    Index("ix_accesslog_created", "created_at"),
    Index("ix_accesslog_person", "person_id"),
)

# 스키마 버전·운영 스위치를 담는 1행짜리 키-값 표.
schema_meta = Table(
    T_META, metadata,
    Column("meta_key", utext(50), primary_key=True),      # schema_version | access_control
    Column("meta_value", utext(200), nullable=False),
    Column("updated_at", ts(), nullable=False),
)

content_blobs = Table(
    T_BLOBS, metadata,
    Column("checksum", utext(64), primary_key=True),  # sha256(원본 텍스트) — pages/page_versions.checksum 과 동일 키
    Column("algo", utext(10), nullable=False),         # "gzip" | "raw"
    Column("byte_len", Integer, nullable=False),       # 원본(압축 전) UTF-8 바이트 길이
    Column("data", big_blob(), nullable=False),        # algo 로 인코딩된 바이트
)

INDEX_TABLES = {"api": api_endpoints, "db": db_objects, "route": frontend_routes, "external": external_links}

# v1 시절 이미 만들어진 표에 v2 에서 새로 붙는 컬럼.
# create_all() 은 없는 "테이블"만 만들지 기존 테이블에 "컬럼"을 붙여주지 않으므로,
# store.ensure_schema() 가 이 목록을 보고 빠진 것만 ALTER 로 채운다(전부 nullable — 기존 행 영향 없음).
ADDED_COLUMNS_V2 = [
    (T_SYSTEMS, "owner_person_id"),
    (T_VERSIONS, "author_person_id"),
    (T_LOG, "publisher_person_id"),
]
