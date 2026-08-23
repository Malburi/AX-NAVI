-- =============================================================================
--  Total ITO · wiki-hub 중앙 DB 스키마 (SQLITE)
--  기존 DB 업그레이드 v1 → v2 (02)
--
--  생성 기준 : agents/lib/wikihub_db/models.py (schema_version = 2)
--  생성 방식 : SQLAlchemy 방언 컴파일 — 손으로 고치지 말고 models.py 를 고친 뒤 다시 뽑는다.
--
--  주의. publish.py 는 접속 시 스키마를 자동 생성한다(create_all + 부족한 컬럼 ALTER).
--        이 스크립트는 DBA 검토·사전 생성·권한 분리 운영(발행 계정에 DDL 권한을 주지 않는
--        환경)을 위한 것이다. 둘 중 어느 쪽으로 만들어도 결과는 같다.
-- =============================================================================

-- 이미 운영 중인 wikihub_* DB 에 담당자·권한 표를 더한다.
-- 기존 표의 데이터는 건드리지 않는다. 아래 ALTER 는 전부 NULL 허용 컬럼이라
-- 기존 행에 영향이 없고, 여러 번 실행해도 안전하다.

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

-- ---------- 기존 표에 담당자 연결 컬럼 추가 ----------
-- 이미 있으면 "duplicate column name" 오류가 난다(무시해도 됨).
ALTER TABLE wikihub_systems ADD COLUMN owner_person_id INTEGER;
-- 이미 있으면 "duplicate column name" 오류가 난다(무시해도 됨).
ALTER TABLE wikihub_page_versions ADD COLUMN author_person_id INTEGER;
-- 이미 있으면 "duplicate column name" 오류가 난다(무시해도 됨).
ALTER TABLE wikihub_publish_log ADD COLUMN publisher_person_id INTEGER;

-- 이어서 03_seed_roles.sql 을 실행해 역할·권한 기본값을 채운다.
