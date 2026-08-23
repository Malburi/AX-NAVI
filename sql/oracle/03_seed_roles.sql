-- =============================================================================
--  Total ITO · wiki-hub 중앙 DB 스키마 (ORACLE)
--  역할·권한 기본값 (03)
--
--  생성 기준 : agents/lib/wikihub_db/models.py (schema_version = 2)
--  생성 방식 : SQLAlchemy 방언 컴파일 — 손으로 고치지 말고 models.py 를 고친 뒤 다시 뽑는다.
--
--  주의. publish.py 는 접속 시 스키마를 자동 생성한다(create_all + 부족한 컬럼 ALTER).
--        이 스크립트는 DBA 검토·사전 생성·권한 분리 운영(발행 계정에 DDL 권한을 주지 않는
--        환경)을 위한 것이다. 둘 중 어느 쪽으로 만들어도 결과는 같다.
-- =============================================================================

-- 역할과 권한은 코드가 아니라 데이터다. 조직에 맞는 역할을 추가하려면
-- 여기에 INSERT 를 덧붙이면 된다(내장 역할은 is_builtin=1 로 구분).

-- ---- 역할 ----
INSERT INTO wikihub_roles (role_code, display_name, description, rank, is_builtin, created_at)
  SELECT 'admin', '관리자', '허브 전체를 관리한다.', 40, 1, SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_roles WHERE role_code = 'admin');
INSERT INTO wikihub_roles (role_code, display_name, description, rank, is_builtin, created_at)
  SELECT 'manager', '시스템 관리자', '맡은 시스템의 정보와 권한을 관리한다.', 30, 1, SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_roles WHERE role_code = 'manager');
INSERT INTO wikihub_roles (role_code, display_name, description, rank, is_builtin, created_at)
  SELECT 'editor', '발행자', '맡은 시스템에 위키를 발행한다.', 20, 1, SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_roles WHERE role_code = 'editor');
INSERT INTO wikihub_roles (role_code, display_name, description, rank, is_builtin, created_at)
  SELECT 'reader', '열람자', '허용된 시스템의 위키를 읽는다.', 10, 1, SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_roles WHERE role_code = 'reader');

-- ---- 권한 ----
INSERT INTO wikihub_permissions (perm_code, display_name, description)
  SELECT 'wiki.view', '위키 열람', '발행된 페이지 본문과 구조화 인덱스를 본다.' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_permissions WHERE perm_code = 'wiki.view');
INSERT INTO wikihub_permissions (perm_code, display_name, description)
  SELECT 'wiki.search', '위키 검색', '전 시스템 본문 검색을 쓴다.' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_permissions WHERE perm_code = 'wiki.search');
INSERT INTO wikihub_permissions (perm_code, display_name, description)
  SELECT 'wiki.history', '버전 이력 열람', '페이지 버전 목록과 비교 화면을 본다.' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_permissions WHERE perm_code = 'wiki.history');
INSERT INTO wikihub_permissions (perm_code, display_name, description)
  SELECT 'wiki.publish', '위키 발행', 'harness 산출물을 이 시스템으로 발행한다.' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_permissions WHERE perm_code = 'wiki.publish');
INSERT INTO wikihub_permissions (perm_code, display_name, description)
  SELECT 'wiki.revert', '버전 되돌리기', '과거 버전으로 되돌린다.' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_permissions WHERE perm_code = 'wiki.revert');
INSERT INTO wikihub_permissions (perm_code, display_name, description)
  SELECT 'system.manage', '시스템 정보 관리', '표시 이름·설명·담당자·보관 여부를 고친다.' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_permissions WHERE perm_code = 'system.manage');
INSERT INTO wikihub_permissions (perm_code, display_name, description)
  SELECT 'acl.manage', '권한 관리', '다른 사람에게 역할을 부여하거나 회수한다.' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_permissions WHERE perm_code = 'acl.manage');

-- ---- 역할별 권한 ----
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'admin', 'wiki.view' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'admin' AND perm_code = 'wiki.view');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'admin', 'wiki.search' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'admin' AND perm_code = 'wiki.search');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'admin', 'wiki.history' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'admin' AND perm_code = 'wiki.history');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'admin', 'wiki.publish' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'admin' AND perm_code = 'wiki.publish');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'admin', 'wiki.revert' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'admin' AND perm_code = 'wiki.revert');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'admin', 'system.manage' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'admin' AND perm_code = 'system.manage');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'admin', 'acl.manage' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'admin' AND perm_code = 'acl.manage');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'manager', 'wiki.view' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'manager' AND perm_code = 'wiki.view');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'manager', 'wiki.search' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'manager' AND perm_code = 'wiki.search');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'manager', 'wiki.history' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'manager' AND perm_code = 'wiki.history');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'manager', 'wiki.publish' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'manager' AND perm_code = 'wiki.publish');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'manager', 'wiki.revert' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'manager' AND perm_code = 'wiki.revert');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'manager', 'system.manage' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'manager' AND perm_code = 'system.manage');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'manager', 'acl.manage' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'manager' AND perm_code = 'acl.manage');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'editor', 'wiki.view' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'editor' AND perm_code = 'wiki.view');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'editor', 'wiki.search' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'editor' AND perm_code = 'wiki.search');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'editor', 'wiki.history' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'editor' AND perm_code = 'wiki.history');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'editor', 'wiki.publish' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'editor' AND perm_code = 'wiki.publish');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'editor', 'wiki.revert' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'editor' AND perm_code = 'wiki.revert');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'reader', 'wiki.view' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'reader' AND perm_code = 'wiki.view');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'reader', 'wiki.search' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'reader' AND perm_code = 'wiki.search');
INSERT INTO wikihub_role_permissions (role_code, perm_code)
  SELECT 'reader', 'wiki.history' FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_role_permissions WHERE role_code = 'reader' AND perm_code = 'wiki.history');

-- ---- 스키마 버전 · 접근 통제 스위치 ----
-- access_control 을 'on' 으로 바꾸면 wiki-hub 조회 서버가 권한을 강제한다.
-- 권한을 다 부여하기 전에 켜면 아무도 못 보게 되니, 부여를 마친 뒤 켠다.
INSERT INTO wikihub_schema_meta (meta_key, meta_value, updated_at)
  SELECT 'schema_version', '2', SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_schema_meta WHERE meta_key = 'schema_version');
INSERT INTO wikihub_schema_meta (meta_key, meta_value, updated_at)
  SELECT 'access_control', 'off', SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual
  WHERE NOT EXISTS (SELECT 1 FROM wikihub_schema_meta WHERE meta_key = 'access_control');
