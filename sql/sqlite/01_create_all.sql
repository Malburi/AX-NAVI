-- =============================================================================
--  Total ITO · wiki-hub 중앙 DB 스키마 (SQLITE)
--  신규 설치 — 전체 테이블 (01)
--
--  생성 기준 : agents/lib/wikihub_db/models.py (schema_version = 2)
--  생성 방식 : SQLAlchemy 방언 컴파일 — 손으로 고치지 말고 models.py 를 고친 뒤 다시 뽑는다.
--
--  주의. publish.py 는 접속 시 스키마를 자동 생성한다(create_all + 부족한 컬럼 ALTER).
--        이 스크립트는 DBA 검토·사전 생성·권한 분리 운영(발행 계정에 DDL 권한을 주지 않는
--        환경)을 위한 것이다. 둘 중 어느 쪽으로 만들어도 결과는 같다.
-- =============================================================================

-- 빈 DB 에 처음 만들 때 쓴다. 이어서 03_seed_roles.sql 을 실행한다.

-- ---------- wikihub_systems ----------
CREATE TABLE IF NOT EXISTS wikihub_systems (
    system_key VARCHAR(100) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    description VARCHAR(1000) DEFAULT '',
    owner VARCHAR(200) DEFAULT '',
    owner_person_id INTEGER,
    repo_url VARCHAR(500) DEFAULT '',
    tags VARCHAR(500) DEFAULT '',
    is_archived BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (system_key)
);

-- ---------- wikihub_components ----------
CREATE TABLE IF NOT EXISTS wikihub_components (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    component_type VARCHAR(30) NOT NULL,
    display_name VARCHAR(200) DEFAULT '',
    repo_root VARCHAR(500) DEFAULT '',
    stack VARCHAR(300) DEFAULT '',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_components_key UNIQUE (system_key, component_key)
);

-- ---------- wikihub_pages ----------
CREATE TABLE IF NOT EXISTS wikihub_pages (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    page_path VARCHAR(300) NOT NULL,
    title VARCHAR(300) DEFAULT '',
    content TEXT,
    content_type VARCHAR(50) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    current_version INTEGER NOT NULL,
    is_deleted BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_pages_key UNIQUE (system_key, component_key, page_path)
);
CREATE INDEX IF NOT EXISTS ix_pages_scope ON wikihub_pages (system_key, component_key);

-- ---------- wikihub_page_versions ----------
CREATE TABLE IF NOT EXISTS wikihub_page_versions (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    page_path VARCHAR(300) NOT NULL,
    version_no INTEGER NOT NULL,
    content TEXT,
    content_type VARCHAR(50) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    change_type VARCHAR(20) NOT NULL,
    change_summary VARCHAR(500) DEFAULT '',
    author VARCHAR(100) DEFAULT '',
    author_person_id INTEGER,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_versions_key UNIQUE (system_key, component_key, page_path, version_no)
);
CREATE INDEX IF NOT EXISTS ix_versions_scope ON wikihub_page_versions (system_key, component_key, page_path);

-- ---------- wikihub_api_endpoints ----------
CREATE TABLE IF NOT EXISTS wikihub_api_endpoints (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    method VARCHAR(10) DEFAULT '',
    path VARCHAR(500) DEFAULT '',
    norm_path VARCHAR(500) DEFAULT '',
    handler VARCHAR(300) DEFAULT '',
    source_file VARCHAR(500) DEFAULT '',
    auth_required BOOLEAN NOT NULL,
    note VARCHAR(500) DEFAULT '',
    snapshot_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_api_norm_path ON wikihub_api_endpoints (norm_path);

-- ---------- wikihub_db_objects ----------
CREATE TABLE IF NOT EXISTS wikihub_db_objects (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    table_name VARCHAR(300) NOT NULL,
    column_count INTEGER NOT NULL,
    primary_key VARCHAR(500) DEFAULT '',
    columns_json TEXT DEFAULT '',
    used_by TEXT DEFAULT '',
    snapshot_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_db_table_name ON wikihub_db_objects (table_name);

-- ---------- wikihub_frontend_routes ----------
CREATE TABLE IF NOT EXISTS wikihub_frontend_routes (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    route_path VARCHAR(500) DEFAULT '',
    view_name VARCHAR(300) DEFAULT '',
    source_file VARCHAR(500) DEFAULT '',
    calls_api TEXT DEFAULT '',
    snapshot_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);

-- ---------- wikihub_external_links ----------
CREATE TABLE IF NOT EXISTS wikihub_external_links (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    link_type VARCHAR(50) DEFAULT '',
    target VARCHAR(500) DEFAULT '',
    source_file VARCHAR(500) DEFAULT '',
    line_no VARCHAR(20) DEFAULT '',
    snapshot_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);

-- ---------- wikihub_publish_log ----------
CREATE TABLE IF NOT EXISTS wikihub_publish_log (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    pages_total INTEGER NOT NULL,
    pages_created INTEGER NOT NULL,
    pages_updated INTEGER NOT NULL,
    pages_deleted INTEGER NOT NULL,
    message VARCHAR(1000) DEFAULT '',
    publisher_person_id INTEGER,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);

-- ---------- wikihub_content_blobs ----------
CREATE TABLE IF NOT EXISTS wikihub_content_blobs (
    checksum VARCHAR(64) NOT NULL,
    algo VARCHAR(10) NOT NULL,
    byte_len INTEGER NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (checksum)
);

-- ---------- wikihub_persons ----------
CREATE TABLE IF NOT EXISTS wikihub_persons (
    person_id INTEGER NOT NULL,
    company VARCHAR(100) NOT NULL,
    department VARCHAR(100) DEFAULT '',
    employee_no VARCHAR(50) NOT NULL,
    person_name VARCHAR(100) NOT NULL,
    phone VARCHAR(50) DEFAULT '',
    email VARCHAR(200) DEFAULT '',
    is_active BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (person_id),
    CONSTRAINT uq_persons_company_empno UNIQUE (company, employee_no)
);
CREATE INDEX IF NOT EXISTS ix_persons_email ON wikihub_persons (email);
CREATE INDEX IF NOT EXISTS ix_persons_name ON wikihub_persons (person_name);

-- ---------- wikihub_system_owners ----------
CREATE TABLE IF NOT EXISTS wikihub_system_owners (
    id INTEGER NOT NULL,
    system_key VARCHAR(100) NOT NULL,
    component_key VARCHAR(100) DEFAULT '' NOT NULL,
    person_id INTEGER NOT NULL,
    owner_role VARCHAR(30) NOT NULL,
    note VARCHAR(300) DEFAULT '',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_owner_key UNIQUE (system_key, component_key, person_id, owner_role)
);
CREATE INDEX IF NOT EXISTS ix_owner_person ON wikihub_system_owners (person_id);
CREATE INDEX IF NOT EXISTS ix_owner_scope ON wikihub_system_owners (system_key, component_key);

-- ---------- wikihub_roles ----------
CREATE TABLE IF NOT EXISTS wikihub_roles (
    role_code VARCHAR(30) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description VARCHAR(300) DEFAULT '',
    rank INTEGER NOT NULL,
    is_builtin BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (role_code)
);

-- ---------- wikihub_permissions ----------
CREATE TABLE IF NOT EXISTS wikihub_permissions (
    perm_code VARCHAR(40) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description VARCHAR(300) DEFAULT '',
    PRIMARY KEY (perm_code)
);

-- ---------- wikihub_role_permissions ----------
CREATE TABLE IF NOT EXISTS wikihub_role_permissions (
    role_code VARCHAR(30) NOT NULL,
    perm_code VARCHAR(40) NOT NULL,
    PRIMARY KEY (role_code, perm_code)
);

-- ---------- wikihub_access_grants ----------
CREATE TABLE IF NOT EXISTS wikihub_access_grants (
    id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    scope_type VARCHAR(20) NOT NULL,
    system_key VARCHAR(100) DEFAULT '' NOT NULL,
    component_key VARCHAR(100) DEFAULT '' NOT NULL,
    role_code VARCHAR(30) NOT NULL,
    granted_by_person_id INTEGER,
    granted_at DATETIME NOT NULL,
    expires_at DATETIME,
    is_active BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_grant_key UNIQUE (person_id, scope_type, system_key, component_key, role_code)
);
CREATE INDEX IF NOT EXISTS ix_grants_person ON wikihub_access_grants (person_id);
CREATE INDEX IF NOT EXISTS ix_grants_scope ON wikihub_access_grants (system_key, component_key);

-- ---------- wikihub_accounts ----------
CREATE TABLE IF NOT EXISTS wikihub_accounts (
    account_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL,
    login_id VARCHAR(100) NOT NULL,
    auth_type VARCHAR(20) DEFAULT 'sso' NOT NULL,
    password_hash VARCHAR(200) DEFAULT '',
    last_login_at DATETIME,
    is_locked BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (account_id),
    CONSTRAINT uq_accounts_login UNIQUE (login_id)
);
CREATE INDEX IF NOT EXISTS ix_accounts_person ON wikihub_accounts (person_id);

-- ---------- wikihub_access_log ----------
CREATE TABLE IF NOT EXISTS wikihub_access_log (
    id INTEGER NOT NULL,
    person_id INTEGER,
    login_id VARCHAR(100) DEFAULT '',
    action VARCHAR(30) NOT NULL,
    system_key VARCHAR(100) DEFAULT '',
    component_key VARCHAR(100) DEFAULT '',
    page_path VARCHAR(300) DEFAULT '',
    result VARCHAR(20) NOT NULL,
    client_ip VARCHAR(50) DEFAULT '',
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_accesslog_created ON wikihub_access_log (created_at);
CREATE INDEX IF NOT EXISTS ix_accesslog_person ON wikihub_access_log (person_id);

-- ---------- wikihub_schema_meta ----------
CREATE TABLE IF NOT EXISTS wikihub_schema_meta (
    meta_key VARCHAR(50) NOT NULL,
    meta_value VARCHAR(200) NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (meta_key)
);

