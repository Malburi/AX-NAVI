-- =============================================================================
--  Total ITO · wiki-hub 중앙 DB 스키마 (MSSQL)
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
IF OBJECT_ID(N'wikihub_systems', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_systems (
        system_key NVARCHAR(100) NOT NULL,
        display_name NVARCHAR(200) NOT NULL,
        description NVARCHAR(1000) NULL DEFAULT '',
        owner NVARCHAR(200) NULL DEFAULT '',
        owner_person_id INTEGER NULL,
        repo_url NVARCHAR(500) NULL DEFAULT '',
        tags NVARCHAR(500) NULL DEFAULT '',
        is_archived BIT NOT NULL,
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        PRIMARY KEY (system_key)
    );
END;
GO

-- ---------- wikihub_components ----------
IF OBJECT_ID(N'wikihub_components', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_components (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        component_type NVARCHAR(30) NOT NULL,
        display_name NVARCHAR(200) NULL DEFAULT '',
        repo_root NVARCHAR(500) NULL DEFAULT '',
        stack NVARCHAR(300) NULL DEFAULT '',
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_components_key UNIQUE (system_key, component_key)
    );
END;
GO

-- ---------- wikihub_pages ----------
IF OBJECT_ID(N'wikihub_pages', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_pages (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        page_path NVARCHAR(300) NOT NULL,
        title NVARCHAR(300) NULL DEFAULT '',
        content NVARCHAR(max) NULL,
        content_type NVARCHAR(50) NOT NULL,
        checksum NVARCHAR(64) NOT NULL,
        current_version INTEGER NOT NULL,
        is_deleted BIT NOT NULL,
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_pages_key UNIQUE (system_key, component_key, page_path)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_pages_scope' AND object_id = OBJECT_ID(N'wikihub_pages'))
    CREATE INDEX ix_pages_scope ON wikihub_pages (system_key, component_key);
GO

-- ---------- wikihub_page_versions ----------
IF OBJECT_ID(N'wikihub_page_versions', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_page_versions (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        page_path NVARCHAR(300) NOT NULL,
        version_no INTEGER NOT NULL,
        content NVARCHAR(max) NULL,
        content_type NVARCHAR(50) NOT NULL,
        checksum NVARCHAR(64) NOT NULL,
        change_type NVARCHAR(20) NOT NULL,
        change_summary NVARCHAR(500) NULL DEFAULT '',
        author NVARCHAR(100) NULL DEFAULT '',
        author_person_id INTEGER NULL,
        created_at DATETIME2 NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_versions_key UNIQUE (system_key, component_key, page_path, version_no)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_versions_scope' AND object_id = OBJECT_ID(N'wikihub_page_versions'))
    CREATE INDEX ix_versions_scope ON wikihub_page_versions (system_key, component_key, page_path);
GO

-- ---------- wikihub_api_endpoints ----------
IF OBJECT_ID(N'wikihub_api_endpoints', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_api_endpoints (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        method NVARCHAR(10) NULL DEFAULT '',
        path NVARCHAR(500) NULL DEFAULT '',
        norm_path NVARCHAR(500) NULL DEFAULT '',
        handler NVARCHAR(300) NULL DEFAULT '',
        source_file NVARCHAR(500) NULL DEFAULT '',
        auth_required BIT NOT NULL,
        note NVARCHAR(500) NULL DEFAULT '',
        snapshot_at DATETIME2 NOT NULL,
        PRIMARY KEY (id)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_api_norm_path' AND object_id = OBJECT_ID(N'wikihub_api_endpoints'))
    CREATE INDEX ix_api_norm_path ON wikihub_api_endpoints (norm_path);
GO

-- ---------- wikihub_db_objects ----------
IF OBJECT_ID(N'wikihub_db_objects', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_db_objects (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        table_name NVARCHAR(300) NOT NULL,
        column_count INTEGER NOT NULL,
        primary_key NVARCHAR(500) NULL DEFAULT '',
        columns_json NVARCHAR(max) NULL DEFAULT '',
        used_by NVARCHAR(max) NULL DEFAULT '',
        snapshot_at DATETIME2 NOT NULL,
        PRIMARY KEY (id)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_db_table_name' AND object_id = OBJECT_ID(N'wikihub_db_objects'))
    CREATE INDEX ix_db_table_name ON wikihub_db_objects (table_name);
GO

-- ---------- wikihub_frontend_routes ----------
IF OBJECT_ID(N'wikihub_frontend_routes', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_frontend_routes (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        route_path NVARCHAR(500) NULL DEFAULT '',
        view_name NVARCHAR(300) NULL DEFAULT '',
        source_file NVARCHAR(500) NULL DEFAULT '',
        calls_api NVARCHAR(max) NULL DEFAULT '',
        snapshot_at DATETIME2 NOT NULL,
        PRIMARY KEY (id)
    );
END;
GO

-- ---------- wikihub_external_links ----------
IF OBJECT_ID(N'wikihub_external_links', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_external_links (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        link_type NVARCHAR(50) NULL DEFAULT '',
        target NVARCHAR(500) NULL DEFAULT '',
        source_file NVARCHAR(500) NULL DEFAULT '',
        line_no NVARCHAR(20) NULL DEFAULT '',
        snapshot_at DATETIME2 NOT NULL,
        PRIMARY KEY (id)
    );
END;
GO

-- ---------- wikihub_publish_log ----------
IF OBJECT_ID(N'wikihub_publish_log', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_publish_log (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL,
        action NVARCHAR(50) NOT NULL,
        pages_total INTEGER NOT NULL,
        pages_created INTEGER NOT NULL,
        pages_updated INTEGER NOT NULL,
        pages_deleted INTEGER NOT NULL,
        message NVARCHAR(1000) NULL DEFAULT '',
        publisher_person_id INTEGER NULL,
        created_at DATETIME2 NOT NULL,
        PRIMARY KEY (id)
    );
END;
GO

-- ---------- wikihub_content_blobs ----------
IF OBJECT_ID(N'wikihub_content_blobs', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_content_blobs (
        checksum NVARCHAR(64) NOT NULL,
        algo NVARCHAR(10) NOT NULL,
        byte_len INTEGER NOT NULL,
        data VARBINARY(max) NOT NULL,
        PRIMARY KEY (checksum)
    );
END;
GO

-- ---------- wikihub_persons ----------
IF OBJECT_ID(N'wikihub_persons', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_persons (
        person_id INTEGER NOT NULL IDENTITY(1,1),
        company NVARCHAR(100) NOT NULL,
        department NVARCHAR(100) NULL DEFAULT '',
        employee_no NVARCHAR(50) NOT NULL,
        person_name NVARCHAR(100) NOT NULL,
        phone NVARCHAR(50) NULL DEFAULT '',
        email NVARCHAR(200) NULL DEFAULT '',
        is_active BIT NOT NULL,
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        PRIMARY KEY (person_id),
        CONSTRAINT uq_persons_company_empno UNIQUE (company, employee_no)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_persons_email' AND object_id = OBJECT_ID(N'wikihub_persons'))
    CREATE INDEX ix_persons_email ON wikihub_persons (email);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_persons_name' AND object_id = OBJECT_ID(N'wikihub_persons'))
    CREATE INDEX ix_persons_name ON wikihub_persons (person_name);
GO

-- ---------- wikihub_system_owners ----------
IF OBJECT_ID(N'wikihub_system_owners', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_system_owners (
        id INTEGER NOT NULL IDENTITY(1,1),
        system_key NVARCHAR(100) NOT NULL,
        component_key NVARCHAR(100) NOT NULL DEFAULT '',
        person_id INTEGER NOT NULL,
        owner_role NVARCHAR(30) NOT NULL,
        note NVARCHAR(300) NULL DEFAULT '',
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_owner_key UNIQUE (system_key, component_key, person_id, owner_role)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_owner_person' AND object_id = OBJECT_ID(N'wikihub_system_owners'))
    CREATE INDEX ix_owner_person ON wikihub_system_owners (person_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_owner_scope' AND object_id = OBJECT_ID(N'wikihub_system_owners'))
    CREATE INDEX ix_owner_scope ON wikihub_system_owners (system_key, component_key);
GO

-- ---------- wikihub_roles ----------
IF OBJECT_ID(N'wikihub_roles', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_roles (
        role_code NVARCHAR(30) NOT NULL,
        display_name NVARCHAR(100) NOT NULL,
        description NVARCHAR(300) NULL DEFAULT '',
        rank INTEGER NOT NULL,
        is_builtin BIT NOT NULL,
        created_at DATETIME2 NOT NULL,
        PRIMARY KEY (role_code)
    );
END;
GO

-- ---------- wikihub_permissions ----------
IF OBJECT_ID(N'wikihub_permissions', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_permissions (
        perm_code NVARCHAR(40) NOT NULL,
        display_name NVARCHAR(100) NOT NULL,
        description NVARCHAR(300) NULL DEFAULT '',
        PRIMARY KEY (perm_code)
    );
END;
GO

-- ---------- wikihub_role_permissions ----------
IF OBJECT_ID(N'wikihub_role_permissions', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_role_permissions (
        role_code NVARCHAR(30) NOT NULL,
        perm_code NVARCHAR(40) NOT NULL,
        PRIMARY KEY (role_code, perm_code)
    );
END;
GO

-- ---------- wikihub_access_grants ----------
IF OBJECT_ID(N'wikihub_access_grants', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_access_grants (
        id INTEGER NOT NULL IDENTITY(1,1),
        person_id INTEGER NOT NULL,
        scope_type NVARCHAR(20) NOT NULL,
        system_key NVARCHAR(100) NOT NULL DEFAULT '',
        component_key NVARCHAR(100) NOT NULL DEFAULT '',
        role_code NVARCHAR(30) NOT NULL,
        granted_by_person_id INTEGER NULL,
        granted_at DATETIME2 NOT NULL,
        expires_at DATETIME2 NULL,
        is_active BIT NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_grant_key UNIQUE (person_id, scope_type, system_key, component_key, role_code)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_grants_person' AND object_id = OBJECT_ID(N'wikihub_access_grants'))
    CREATE INDEX ix_grants_person ON wikihub_access_grants (person_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_grants_scope' AND object_id = OBJECT_ID(N'wikihub_access_grants'))
    CREATE INDEX ix_grants_scope ON wikihub_access_grants (system_key, component_key);
GO

-- ---------- wikihub_accounts ----------
IF OBJECT_ID(N'wikihub_accounts', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_accounts (
        account_id INTEGER NOT NULL IDENTITY(1,1),
        person_id INTEGER NOT NULL,
        login_id NVARCHAR(100) NOT NULL,
        auth_type NVARCHAR(20) NOT NULL DEFAULT 'sso',
        password_hash NVARCHAR(200) NULL DEFAULT '',
        last_login_at DATETIME2 NULL,
        is_locked BIT NOT NULL,
        created_at DATETIME2 NOT NULL,
        updated_at DATETIME2 NOT NULL,
        PRIMARY KEY (account_id),
        CONSTRAINT uq_accounts_login UNIQUE (login_id)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_accounts_person' AND object_id = OBJECT_ID(N'wikihub_accounts'))
    CREATE INDEX ix_accounts_person ON wikihub_accounts (person_id);
GO

-- ---------- wikihub_access_log ----------
IF OBJECT_ID(N'wikihub_access_log', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_access_log (
        id INTEGER NOT NULL IDENTITY(1,1),
        person_id INTEGER NULL,
        login_id NVARCHAR(100) NULL DEFAULT '',
        action NVARCHAR(30) NOT NULL,
        system_key NVARCHAR(100) NULL DEFAULT '',
        component_key NVARCHAR(100) NULL DEFAULT '',
        page_path NVARCHAR(300) NULL DEFAULT '',
        result NVARCHAR(20) NOT NULL,
        client_ip NVARCHAR(50) NULL DEFAULT '',
        created_at DATETIME2 NOT NULL,
        PRIMARY KEY (id)
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_accesslog_created' AND object_id = OBJECT_ID(N'wikihub_access_log'))
    CREATE INDEX ix_accesslog_created ON wikihub_access_log (created_at);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_accesslog_person' AND object_id = OBJECT_ID(N'wikihub_access_log'))
    CREATE INDEX ix_accesslog_person ON wikihub_access_log (person_id);
GO

-- ---------- wikihub_schema_meta ----------
IF OBJECT_ID(N'wikihub_schema_meta', N'U') IS NULL
BEGIN
    CREATE TABLE wikihub_schema_meta (
        meta_key NVARCHAR(50) NOT NULL,
        meta_value NVARCHAR(200) NOT NULL,
        updated_at DATETIME2 NOT NULL,
        PRIMARY KEY (meta_key)
    );
END;
GO

