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
    MetaData, Table, Column, Integer, String, Text, Boolean, DateTime,
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

COMPONENT_TYPES = ["backend", "frontend", "fullstack", "batch", "mobile", "common"]

systems = Table(
    T_SYSTEMS, metadata,
    Column("system_key", utext(100), primary_key=True),
    Column("display_name", utext(200), nullable=False),
    Column("description", utext(1000), server_default=""),
    Column("owner", utext(200), server_default=""),
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
    Column("content", big_text(), nullable=False),
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
    Column("content", big_text(), nullable=False),
    Column("content_type", utext(50), nullable=False),
    Column("checksum", utext(64), nullable=False),
    Column("change_type", utext(20), nullable=False),
    Column("change_summary", utext(500), server_default=""),
    Column("author", utext(100), server_default=""),
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
    Column("created_at", ts(), nullable=False),
)

INDEX_TABLES = {"api": api_endpoints, "db": db_objects, "route": frontend_routes, "external": external_links}
