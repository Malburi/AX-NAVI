# SQLAlchemy Core 엔진 위에서 시스템·컴포넌트·페이지·버전·구조화 인덱스를 다루는 계층
# 별도 프로젝트 wiki-hub(E:/AI/wiki-hub)의 wikihub/store.py를 그대로 옮긴 사본이다
# (import만 패키지 상대참조 → 같은 폴더 내 절대참조로 조정, 로직은 무변경).
"""store.py — harness가 wiki-hub 설치 없이 DB에 직접 쓰기 위한 유일한 DB 접근 통로.

버전 관리 정책.
- 페이지 저장은 체크섬이 바뀔 때만 새 버전을 만든다.
- 소스에서 사라진 페이지는 `is_deleted=1`로 표시만 하고 본문·이력은 남긴다.
- 되돌리기는 과거 버전 내용으로 새 버전을 하나 더 쌓는다 (이력이 줄어들지 않는다).
"""

import os
import sys
import re
import gzip
import hashlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, select, insert, update, delete, func, or_, inspect, text

import models as m


class StoreError(Exception):
    pass


def sha256_text(text_):
    return hashlib.sha256(text_.encode("utf-8")).hexdigest()


# 본문은 wikihub_content_blobs 에 checksum 당 1행(dedup)으로, 512바이트 이상이면 gzip 압축해 저장한다.
BLOB_COMPRESS_MIN = 512


def encode_content(content):
    """텍스트 → (algo, byte_len, data). 반환 data 는 DB blob 컬럼에 그대로 넣을 bytes."""
    raw = (content or "").encode("utf-8")
    if len(raw) < BLOB_COMPRESS_MIN:
        return "raw", len(raw), raw
    return "gzip", len(raw), gzip.compress(raw, 6)


def decode_blob(algo, data):
    """(algo, data) → 원본 텍스트. data 는 memoryview/bytes 모두 허용."""
    if data is None:
        return ""
    raw = bytes(data)
    if algo == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8")


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC — 엔진 전체에서 일관되게 비교하기 위함(저장은 그대로 UTC 유지)


KST = timezone(timedelta(hours=9))


def fmt_dt(value):
    """저장은 UTC(naive)로 하되, 화면 표시는 KST로 변환한다."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    s = str(value)[:19]
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return s


def extract_title(content, page_path):
    m1 = re.search(r"^#\s+(.+)$", content or "", re.MULTILINE)
    if m1:
        return m1.group(1).strip()[:290]
    m2 = re.search(r"<title>(.*?)</title>", content or "", re.IGNORECASE | re.DOTALL)
    if m2:
        return m2.group(1).strip()[:290]
    return page_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def snippets(content, keyword, max_hits=3, width=90):
    out = []
    low, kw = content.lower(), keyword.lower()
    start = 0
    while len(out) < max_hits:
        idx = low.find(kw, start)
        if idx < 0:
            break
        a = max(0, idx - width // 2)
        b = min(len(content), idx + len(kw) + width // 2)
        text_ = content[a:b].replace("\n", " ").strip()
        out.append(("…" if a > 0 else "") + text_ + ("…" if b < len(content) else ""))
        start = idx + len(kw)
    return out


class WikiStore:
    """`with WikiStore(url) as store:` 로 쓴다. 커밋은 각 메서드 내부에서 즉시 이뤄진다."""

    def __init__(self, url, engine_name=""):
        self.url = url
        self.engine_name = engine_name
        self.engine = create_engine(url, future=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.engine.dispose()
        return False

    def describe(self):
        import config
        return config.describe_url(self.engine_name or self.engine.dialect.name, self.url)

    # -- 스키마 -------------------------------------------------------------

    def ensure_schema(self):
        m.metadata.create_all(self.engine)
        self._ensure_added_columns()
        self.seed_access_control()
        self._set_meta("schema_version", str(m.SCHEMA_VERSION))

    def _ensure_added_columns(self):
        """v1 시절 만들어진 표에 v2 컬럼이 빠져 있으면 ALTER 로 붙인다(있으면 건너뜀).
        전부 nullable Integer 라 기존 행에 영향이 없고, 여러 번 실행해도 안전하다."""
        insp = inspect(self.engine)
        dialect = self.engine.dialect
        for table_name, column_name in m.ADDED_COLUMNS_V2:
            if not insp.has_table(table_name):
                continue
            existing = {c["name"] for c in insp.get_columns(table_name)}
            if column_name in existing:
                continue
            col_type = m.metadata.tables[table_name].c[column_name].type.compile(dialect=dialect)
            if dialect.name == "oracle":
                sql = f"ALTER TABLE {table_name} ADD ({column_name} {col_type} NULL)"
            elif dialect.name == "mssql":
                sql = f"ALTER TABLE {table_name} ADD {column_name} {col_type} NULL"
            else:  # postgresql / sqlite
                sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {col_type}"
            with self.engine.begin() as conn:
                conn.exec_driver_sql(sql)

    def seed_access_control(self):
        """역할·권한 기본값을 채운다. 이미 있으면 건드리지 않는다(운영 중 수정한 값 보존)."""
        now = utc_now()
        with self.engine.begin() as conn:
            have_roles = {r[0] for r in conn.execute(select(m.roles.c.role_code))}
            for code, name, desc, rank in m.BUILTIN_ROLES:
                if code not in have_roles:
                    conn.execute(insert(m.roles).values(
                        role_code=code, display_name=name, description=desc,
                        rank=rank, is_builtin=True, created_at=now))
            have_perms = {r[0] for r in conn.execute(select(m.permissions.c.perm_code))}
            for code, name, desc in m.BUILTIN_PERMISSIONS:
                if code not in have_perms:
                    conn.execute(insert(m.permissions).values(
                        perm_code=code, display_name=name, description=desc))
            have_pairs = {(r[0], r[1]) for r in conn.execute(
                select(m.role_permissions.c.role_code, m.role_permissions.c.perm_code))}
            for role_code, perm_codes in m.BUILTIN_ROLE_PERMISSIONS.items():
                for perm_code in perm_codes:
                    if (role_code, perm_code) not in have_pairs:
                        conn.execute(insert(m.role_permissions).values(
                            role_code=role_code, perm_code=perm_code))

    def _set_meta(self, key, value):
        now = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(select(m.schema_meta.c.meta_key)
                               .where(m.schema_meta.c.meta_key == key)).first()
            if row:
                conn.execute(update(m.schema_meta).where(m.schema_meta.c.meta_key == key)
                             .values(meta_value=value, updated_at=now))
            else:
                conn.execute(insert(m.schema_meta).values(
                    meta_key=key, meta_value=value, updated_at=now))

    def get_meta(self, key, default=None):
        with self.engine.connect() as conn:
            row = conn.execute(select(m.schema_meta.c.meta_value)
                               .where(m.schema_meta.c.meta_key == key)).first()
            return row[0] if row else default

    def access_control_enabled(self):
        """접근 통제 스위치. 기본은 'off' — 켜기 전까지 열람 동작은 예전과 완전히 같다."""
        return (self.get_meta("access_control", "off") or "off").lower() == "on"

    def set_access_control(self, enabled):
        self._set_meta("access_control", "on" if enabled else "off")

    def v1_table_exists(self):
        """구 단일 테이블(harness_wiki_pages, project_name 컬럼 보유) 존재 여부.
        wiki-hub 자체 테이블은 wikihub_* 로 네임스페이스를 분리했으므로 이름이 겹치지 않는다 —
        project_name 컬럼 유무로 v1 테이블인지 확인한다."""
        insp = inspect(self.engine)
        if not insp.has_table("harness_wiki_pages"):
            return False
        cols = {c["name"] for c in insp.get_columns("harness_wiki_pages")}
        return "project_name" in cols

    # -- 시스템 / 컴포넌트 ----------------------------------------------------

    def upsert_system(self, system_key, display_name=None, description=None,
                      owner=None, repo_url=None, tags=None, owner_person_id=None):
        now = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(m.systems.c.system_key).where(m.systems.c.system_key == system_key)
            ).first()
            if row:
                values = {"updated_at": now}
                for col, val in [("display_name", display_name), ("description", description),
                                 ("owner", owner), ("repo_url", repo_url), ("tags", tags),
                                 ("owner_person_id", owner_person_id)]:
                    if val is not None:
                        values[col] = val
                conn.execute(update(m.systems).where(m.systems.c.system_key == system_key).values(**values))
                return False
            conn.execute(insert(m.systems).values(
                system_key=system_key, display_name=display_name or system_key,
                description=description or "", owner=owner or "", owner_person_id=owner_person_id,
                repo_url=repo_url or "", tags=tags or "", is_archived=False,
                created_at=now, updated_at=now,
            ))
            return True

    def upsert_component(self, system_key, component_key, component_type,
                         display_name=None, repo_root=None, stack=None):
        now = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(m.components.c.id).where(
                    m.components.c.system_key == system_key,
                    m.components.c.component_key == component_key)
            ).first()
            if row:
                conn.execute(update(m.components).where(m.components.c.id == row.id).values(
                    component_type=component_type, display_name=display_name or component_key,
                    repo_root=repo_root or "", stack=stack or "", updated_at=now))
                return False
            conn.execute(insert(m.components).values(
                system_key=system_key, component_key=component_key, component_type=component_type,
                display_name=display_name or component_key, repo_root=repo_root or "",
                stack=stack or "", created_at=now, updated_at=now,
            ))
            return True

    def list_systems(self, include_archived=False):
        with self.engine.connect() as conn:
            stmt = select(m.systems).order_by(m.systems.c.system_key)
            if not include_archived:
                stmt = stmt.where(m.systems.c.is_archived == False)  # noqa: E712 (MSSQL: .is_(False) compiles to invalid "IS 0")
            rows = conn.execute(stmt).mappings().all()
            out = []
            for r in rows:
                comp_n = conn.execute(
                    select(func.count()).select_from(m.components)
                    .where(m.components.c.system_key == r["system_key"])
                ).scalar_one()
                page_n = conn.execute(
                    select(func.count()).select_from(m.pages)
                    .where(m.pages.c.system_key == r["system_key"], m.pages.c.is_deleted == False)  # noqa: E712
                ).scalar_one()
                updated = conn.execute(
                    select(func.max(m.pages.c.updated_at)).where(m.pages.c.system_key == r["system_key"])
                ).scalar_one()
                out.append({
                    "system_key": r["system_key"], "display_name": r["display_name"],
                    "description": r["description"] or "", "owner": r["owner"] or "",
                    "tags": r["tags"] or "", "is_archived": bool(r["is_archived"]),
                    "component_count": comp_n, "page_count": page_n, "updated_at": fmt_dt(updated),
                })
            return out

    def get_system(self, system_key):
        for s in self.list_systems(include_archived=True):
            if s["system_key"] == system_key:
                return s
        return None

    def set_archived(self, system_key, archived):
        with self.engine.begin() as conn:
            conn.execute(update(m.systems).where(m.systems.c.system_key == system_key)
                         .values(is_archived=archived, updated_at=utc_now()))

    def list_components(self, system_key=None):
        with self.engine.connect() as conn:
            stmt = select(m.components).order_by(
                m.components.c.system_key, m.components.c.component_type, m.components.c.component_key)
            if system_key:
                stmt = stmt.where(m.components.c.system_key == system_key)
            rows = conn.execute(stmt).mappings().all()
            out = []
            for r in rows:
                page_n = conn.execute(
                    select(func.count()).select_from(m.pages).where(
                        m.pages.c.system_key == r["system_key"],
                        m.pages.c.component_key == r["component_key"],
                        m.pages.c.is_deleted == False)  # noqa: E712
                ).scalar_one()
                updated = conn.execute(
                    select(func.max(m.pages.c.updated_at)).where(
                        m.pages.c.system_key == r["system_key"],
                        m.pages.c.component_key == r["component_key"])
                ).scalar_one()
                out.append({
                    "system_key": r["system_key"], "component_key": r["component_key"],
                    "component_type": r["component_type"], "display_name": r["display_name"] or r["component_key"],
                    "repo_root": r["repo_root"] or "", "stack": r["stack"] or "",
                    "page_count": page_n, "updated_at": fmt_dt(updated),
                })
            return out

    # -- 담당자 --------------------------------------------------------------

    def upsert_person(self, company, employee_no, person_name,
                      department=None, phone=None, email=None):
        """(회사명, 사번)으로 사람을 찾아 없으면 만들고, 있으면 바뀐 정보만 갱신한다.
        반환: (person_id, created)."""
        company = (company or "").strip()
        employee_no = (employee_no or "").strip()
        person_name = (person_name or "").strip()
        if not (company and employee_no and person_name):
            raise StoreError("담당자 정보가 부족합니다 — 회사명·사번·성명은 반드시 있어야 합니다.")

        now = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(select(m.persons.c.person_id).where(
                m.persons.c.company == company,
                m.persons.c.employee_no == employee_no)).first()
            if row:
                values = {"person_name": person_name, "is_active": True, "updated_at": now}
                for col, val in [("department", department), ("phone", phone), ("email", email)]:
                    if val is not None and str(val).strip() != "":
                        values[col] = str(val).strip()
                conn.execute(update(m.persons)
                             .where(m.persons.c.person_id == row.person_id).values(**values))
                return row.person_id, False
            result = conn.execute(insert(m.persons).values(
                company=company, department=(department or "").strip(), employee_no=employee_no,
                person_name=person_name, phone=(phone or "").strip(), email=(email or "").strip(),
                is_active=True, created_at=now, updated_at=now))
            new_id = result.inserted_primary_key[0]
            return new_id, True

    def get_person(self, person_id):
        with self.engine.connect() as conn:
            r = conn.execute(select(m.persons)
                             .where(m.persons.c.person_id == person_id)).mappings().first()
            return dict(r) if r else None

    def find_person(self, company, employee_no):
        with self.engine.connect() as conn:
            r = conn.execute(select(m.persons).where(
                m.persons.c.company == company,
                m.persons.c.employee_no == employee_no)).mappings().first()
            return dict(r) if r else None

    def list_persons(self, keyword=None, limit=200):
        with self.engine.connect() as conn:
            stmt = select(m.persons).order_by(m.persons.c.company, m.persons.c.person_name)
            if keyword:
                like = f"%{keyword}%"
                stmt = stmt.where(or_(m.persons.c.person_name.like(like),
                                      m.persons.c.employee_no.like(like),
                                      m.persons.c.company.like(like),
                                      m.persons.c.department.like(like),
                                      m.persons.c.email.like(like)))
            rows = conn.execute(stmt.limit(limit)).mappings().all()
            return [{**dict(r), "created_at": fmt_dt(r["created_at"]),
                     "updated_at": fmt_dt(r["updated_at"])} for r in rows]

    def set_system_owner(self, system_key, person_id, component_key="", owner_role="owner", note=""):
        """시스템(또는 시스템 안 한 컴포넌트)의 담당자를 등록한다. 같은 조합이면 갱신만 한다."""
        if owner_role not in m.OWNER_ROLES:
            raise StoreError(f"알 수 없는 담당 구분: {owner_role} — {', '.join(m.OWNER_ROLES)} 중 하나")
        now = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(select(m.system_owners.c.id).where(
                m.system_owners.c.system_key == system_key,
                m.system_owners.c.component_key == (component_key or ""),
                m.system_owners.c.person_id == person_id,
                m.system_owners.c.owner_role == owner_role)).first()
            if row:
                conn.execute(update(m.system_owners).where(m.system_owners.c.id == row.id)
                             .values(note=note or "", updated_at=now))
                return False
            conn.execute(insert(m.system_owners).values(
                system_key=system_key, component_key=component_key or "", person_id=person_id,
                owner_role=owner_role, note=note or "", created_at=now, updated_at=now))
            return True

    def list_system_owners(self, system_key=None, component_key=None):
        """담당자 목록을 사람 정보와 함께 돌려준다."""
        with self.engine.connect() as conn:
            j = m.system_owners.join(
                m.persons, m.persons.c.person_id == m.system_owners.c.person_id, isouter=True)
            stmt = select(
                m.system_owners.c.system_key, m.system_owners.c.component_key,
                m.system_owners.c.owner_role, m.system_owners.c.note,
                m.system_owners.c.created_at, m.persons,
            ).select_from(j)
            if system_key:
                stmt = stmt.where(m.system_owners.c.system_key == system_key)
            if component_key is not None and component_key != "":
                stmt = stmt.where(m.system_owners.c.component_key == component_key)
            stmt = stmt.order_by(m.system_owners.c.system_key, m.system_owners.c.owner_role)
            rows = conn.execute(stmt).mappings().all()
            return [{
                "system_key": r["system_key"], "component_key": r["component_key"],
                "owner_role": r["owner_role"], "note": r["note"] or "",
                "company": r["company"] or "", "department": r["department"] or "",
                "employee_no": r["employee_no"] or "", "person_name": r["person_name"] or "",
                "phone": r["phone"] or "", "email": r["email"] or "",
                "person_id": r["person_id"], "created_at": fmt_dt(r["created_at"]),
            } for r in rows]

    def set_system_owner_person(self, system_key, person_id):
        """시스템 마스터의 대표 담당자를 지정한다(목록 화면에 한 명만 보이는 자리)."""
        with self.engine.begin() as conn:
            conn.execute(update(m.systems).where(m.systems.c.system_key == system_key)
                         .values(owner_person_id=person_id, updated_at=utc_now()))

    # -- 권한 ----------------------------------------------------------------

    def grant_access(self, person_id, role_code, scope_type="system", system_key="",
                     component_key="", granted_by_person_id=None, expires_at=None):
        """사람에게 범위별 역할을 준다. 같은 조합을 다시 주면 되살리기(is_active=1)만 한다."""
        if scope_type not in m.SCOPE_TYPES:
            raise StoreError(f"알 수 없는 범위: {scope_type} — {', '.join(m.SCOPE_TYPES)} 중 하나")
        if scope_type == "global":
            system_key, component_key = "", ""
        elif scope_type == "system":
            component_key = ""
            if not system_key:
                raise StoreError("scope_type=system 이면 system_key 가 있어야 합니다.")
        elif not (system_key and component_key):
            raise StoreError("scope_type=component 이면 system_key 와 component_key 가 모두 있어야 합니다.")

        now = utc_now()
        with self.engine.begin() as conn:
            if not conn.execute(select(m.roles.c.role_code)
                                .where(m.roles.c.role_code == role_code)).first():
                raise StoreError(f"등록되지 않은 역할: {role_code}")
            row = conn.execute(select(m.access_grants.c.id).where(
                m.access_grants.c.person_id == person_id,
                m.access_grants.c.scope_type == scope_type,
                m.access_grants.c.system_key == system_key,
                m.access_grants.c.component_key == component_key,
                m.access_grants.c.role_code == role_code)).first()
            if row:
                conn.execute(update(m.access_grants).where(m.access_grants.c.id == row.id)
                             .values(is_active=True, expires_at=expires_at, granted_at=now,
                                     granted_by_person_id=granted_by_person_id))
                return False
            conn.execute(insert(m.access_grants).values(
                person_id=person_id, scope_type=scope_type, system_key=system_key,
                component_key=component_key, role_code=role_code,
                granted_by_person_id=granted_by_person_id, granted_at=now,
                expires_at=expires_at, is_active=True))
            return True

    def revoke_access(self, person_id, role_code, scope_type="system", system_key="", component_key=""):
        """권한을 회수한다. 행을 지우지 않고 is_active=0 으로 둔다(회수 이력 보존)."""
        with self.engine.begin() as conn:
            result = conn.execute(update(m.access_grants).where(
                m.access_grants.c.person_id == person_id,
                m.access_grants.c.role_code == role_code,
                m.access_grants.c.scope_type == scope_type,
                m.access_grants.c.system_key == (system_key or ""),
                m.access_grants.c.component_key == (component_key or "")
            ).values(is_active=False))
            return result.rowcount

    def list_grants(self, person_id=None, system_key=None, include_inactive=False):
        with self.engine.connect() as conn:
            j = m.access_grants.join(
                m.persons, m.persons.c.person_id == m.access_grants.c.person_id, isouter=True)
            stmt = select(
                m.access_grants.c.id, m.access_grants.c.scope_type, m.access_grants.c.system_key,
                m.access_grants.c.component_key, m.access_grants.c.role_code,
                m.access_grants.c.is_active, m.access_grants.c.granted_at,
                m.access_grants.c.expires_at, m.persons.c.person_id, m.persons.c.company,
                m.persons.c.department, m.persons.c.employee_no, m.persons.c.person_name,
                m.persons.c.email,
            ).select_from(j)
            if person_id:
                stmt = stmt.where(m.access_grants.c.person_id == person_id)
            if system_key:
                stmt = stmt.where(m.access_grants.c.system_key == system_key)
            if not include_inactive:
                stmt = stmt.where(m.access_grants.c.is_active == True)  # noqa: E712
            stmt = stmt.order_by(m.access_grants.c.system_key, m.access_grants.c.role_code)
            return [dict(r) | {"granted_at": fmt_dt(r["granted_at"]),
                               "expires_at": fmt_dt(r["expires_at"])}
                    for r in conn.execute(stmt).mappings().all()]

    def person_permissions(self, person_id, system_key="", component_key=""):
        """이 사람이 이 범위에서 가진 권한 코드 집합. 상위 범위(global→system→component)는 아래로 상속된다."""
        with self.engine.connect() as conn:
            now = utc_now()
            j = m.access_grants.join(
                m.role_permissions, m.role_permissions.c.role_code == m.access_grants.c.role_code)
            rows = conn.execute(select(
                m.role_permissions.c.perm_code, m.access_grants.c.scope_type,
                m.access_grants.c.system_key, m.access_grants.c.component_key,
                m.access_grants.c.expires_at,
            ).select_from(j).where(
                m.access_grants.c.person_id == person_id,
                m.access_grants.c.is_active == True,  # noqa: E712
            )).mappings().all()

        out = set()
        for r in rows:
            if r["expires_at"] is not None and r["expires_at"] < now:
                continue
            if r["scope_type"] == "global":
                out.add(r["perm_code"])
            elif r["scope_type"] == "system" and r["system_key"] == system_key:
                out.add(r["perm_code"])
            elif (r["scope_type"] == "component" and r["system_key"] == system_key
                  and r["component_key"] == component_key):
                out.add(r["perm_code"])
        return out

    def can(self, person_id, perm_code, system_key="", component_key=""):
        """권한 판정 한 곳. 접근 통제가 꺼져 있으면 항상 허용한다(지금 상태 = 예전과 동일)."""
        if not self.access_control_enabled():
            return True
        if not person_id:
            return False
        return perm_code in self.person_permissions(person_id, system_key, component_key)

    def write_access_log(self, action, result, person_id=None, login_id="", system_key="",
                         component_key="", page_path="", client_ip=""):
        with self.engine.begin() as conn:
            conn.execute(insert(m.access_log).values(
                person_id=person_id, login_id=(login_id or "")[:100], action=action[:30],
                system_key=(system_key or "")[:100], component_key=(component_key or "")[:100],
                page_path=(page_path or "")[:300], result=result[:20],
                client_ip=(client_ip or "")[:50], created_at=utc_now()))

    # -- 페이지 + 버전 --------------------------------------------------------

    def list_pages(self, system_key, component_key=None, include_deleted=False):
        with self.engine.connect() as conn:
            stmt = select(m.pages).where(m.pages.c.system_key == system_key)
            if component_key:
                stmt = stmt.where(m.pages.c.component_key == component_key)
            if not include_deleted:
                stmt = stmt.where(m.pages.c.is_deleted == False)  # noqa: E712
            stmt = stmt.order_by(m.pages.c.page_path)
            rows = conn.execute(stmt).mappings().all()
            return [{
                "page_path": r["page_path"], "title": r["title"] or r["page_path"],
                "content_type": r["content_type"], "current_version": r["current_version"],
                "is_deleted": bool(r["is_deleted"]), "updated_at": fmt_dt(r["updated_at"]),
            } for r in rows]

    def get_page(self, system_key, component_key, page_path):
        with self.engine.connect() as conn:
            r = conn.execute(select(m.pages).where(
                m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                m.pages.c.page_path == page_path)).mappings().first()
            if not r:
                return None
            content = self._load_blob(conn, r["checksum"])
            if content is None:  # 마이그레이션 전 구 데이터 폴백
                content = r["content"] or ""
            return {"content": content, "content_type": r["content_type"],
                    "current_version": r["current_version"], "updated_at": fmt_dt(r["updated_at"]),
                    "is_deleted": bool(r["is_deleted"]), "title": r["title"] or page_path}

    def page_exists(self, system_key, component_key, page_path):
        with self.engine.connect() as conn:
            row = conn.execute(select(m.pages.c.id).where(
                m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                m.pages.c.page_path == page_path, m.pages.c.is_deleted == False)  # noqa: E712
            ).first()
            return row is not None

    def _ensure_blob(self, conn, checksum, content):
        """checksum 본문이 wikihub_content_blobs 에 없으면 압축해 넣는다(dedup 지점). 있으면 skip.
        반환: 새로 넣었으면 True, 이미 있었으면 False."""
        exists = conn.execute(
            select(m.content_blobs.c.checksum).where(m.content_blobs.c.checksum == checksum)
        ).first()
        if exists:
            return False
        algo, byte_len, data = encode_content(content)
        conn.execute(insert(m.content_blobs).values(
            checksum=checksum, algo=algo, byte_len=byte_len, data=data))
        return True

    def _load_blob(self, conn, checksum):
        """checksum → 원본 텍스트. blob 이 없으면 None(마이그레이션 전 구 데이터는 호출부에서 content 컬럼 폴백)."""
        r = conn.execute(select(m.content_blobs.c.algo, m.content_blobs.c.data)
                         .where(m.content_blobs.c.checksum == checksum)).first()
        if r is None:
            return None
        return decode_blob(r.algo, r.data)

    def save_page(self, system_key, component_key, page_path, content, content_type,
                  author="wiki-hub", change_summary="", author_person_id=None):
        """반환: "created" | "updated" | "unchanged"."""
        now = utc_now()
        checksum = sha256_text(content)
        title = extract_title(content, page_path)

        with self.engine.begin() as conn:
            cur = conn.execute(select(
                m.pages.c.checksum, m.pages.c.current_version, m.pages.c.is_deleted
            ).where(m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                    m.pages.c.page_path == page_path)).first()

            if cur is None:
                self._ensure_blob(conn, checksum, content)
                conn.execute(insert(m.pages).values(
                    system_key=system_key, component_key=component_key, page_path=page_path,
                    title=title, content="", content_type=content_type, checksum=checksum,
                    current_version=1, is_deleted=False, created_at=now, updated_at=now,
                ))
                self._insert_version(conn, system_key, component_key, page_path, 1, content,
                                     content_type, checksum, "created", change_summary or "최초 등록",
                                     author, now, author_person_id)
                return "created"

            old_checksum, old_version, was_deleted = cur.checksum, cur.current_version, bool(cur.is_deleted)
            if old_checksum == checksum and not was_deleted:
                return "unchanged"

            new_version = old_version + 1
            self._ensure_blob(conn, checksum, content)
            conn.execute(update(m.pages).where(
                m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                m.pages.c.page_path == page_path
            ).values(title=title, content="", content_type=content_type, checksum=checksum,
                     current_version=new_version, is_deleted=False, updated_at=now))
            change_type = "restored" if was_deleted else "updated"
            self._insert_version(conn, system_key, component_key, page_path, new_version, content,
                                 content_type, checksum, change_type, change_summary or "내용 변경",
                                 author, now, author_person_id)
            return "created" if was_deleted else "updated"

    def mark_deleted(self, system_key, component_key, page_path, author="wiki-hub", reason="",
                     author_person_id=None):
        with self.engine.begin() as conn:
            cur = conn.execute(select(
                m.pages.c.current_version, m.pages.c.content, m.pages.c.content_type,
                m.pages.c.checksum, m.pages.c.is_deleted
            ).where(m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                    m.pages.c.page_path == page_path)).first()
            if not cur or bool(cur.is_deleted):
                return False
            now = utc_now()
            new_version = cur.current_version + 1
            conn.execute(update(m.pages).where(
                m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                m.pages.c.page_path == page_path
            ).values(is_deleted=True, current_version=new_version, updated_at=now))
            self._insert_version(conn, system_key, component_key, page_path, new_version, cur.content,
                                 cur.content_type, cur.checksum, "deleted", reason or "소스에서 사라짐",
                                 author, now, author_person_id)
            return True

    def _insert_version(self, conn, system_key, component_key, page_path, version_no, content,
                        content_type, checksum, change_type, change_summary, author, created_at,
                        author_person_id=None):
        self._ensure_blob(conn, checksum, content)
        conn.execute(insert(m.page_versions).values(
            system_key=system_key, component_key=component_key, page_path=page_path,
            version_no=version_no, content="", content_type=content_type, checksum=checksum,
            change_type=change_type, change_summary=(change_summary or "")[:490],
            author=author or "", author_person_id=author_person_id, created_at=created_at,
        ))

    def list_versions(self, system_key, component_key, page_path):
        with self.engine.connect() as conn:
            j = m.page_versions.join(
                m.content_blobs, m.content_blobs.c.checksum == m.page_versions.c.checksum, isouter=True)
            rows = conn.execute(select(
                m.page_versions.c.version_no, m.page_versions.c.change_type,
                m.page_versions.c.change_summary, m.page_versions.c.author,
                m.page_versions.c.created_at, m.page_versions.c.checksum,
                m.content_blobs.c.byte_len, m.page_versions.c.content,
            ).select_from(j).where(
                m.page_versions.c.system_key == system_key, m.page_versions.c.component_key == component_key,
                m.page_versions.c.page_path == page_path
            ).order_by(m.page_versions.c.version_no.desc())).all()
            return [{
                "version_no": r.version_no, "change_type": r.change_type,
                "change_summary": r.change_summary or "", "author": r.author or "",
                "created_at": fmt_dt(r.created_at), "checksum": r.checksum,
                "size": r.byte_len if r.byte_len is not None else len(r.content or ""),
            } for r in rows]

    def get_version(self, system_key, component_key, page_path, version_no):
        with self.engine.connect() as conn:
            r = conn.execute(select(m.page_versions).where(
                m.page_versions.c.system_key == system_key, m.page_versions.c.component_key == component_key,
                m.page_versions.c.page_path == page_path, m.page_versions.c.version_no == version_no
            )).mappings().first()
            if not r:
                return None
            content = self._load_blob(conn, r["checksum"])
            if content is None:  # 마이그레이션 전 구 데이터 폴백
                content = r["content"] or ""
            return {"content": content, "content_type": r["content_type"],
                    "change_type": r["change_type"], "change_summary": r["change_summary"] or "",
                    "author": r["author"] or "", "created_at": fmt_dt(r["created_at"])}

    def revert_page(self, system_key, component_key, page_path, version_no, author="hub"):
        target = self.get_version(system_key, component_key, page_path, version_no)
        if not target:
            raise StoreError(f"버전 없음: {page_path} v{version_no}")
        result = self.save_page(system_key, component_key, page_path, target["content"],
                                target["content_type"], author=author,
                                change_summary=f"v{version_no} 내용으로 되돌림")
        if result == "unchanged":
            return None
        page = self.get_page(system_key, component_key, page_path)
        with self.engine.begin() as conn:
            conn.execute(update(m.page_versions).where(
                m.page_versions.c.system_key == system_key, m.page_versions.c.component_key == component_key,
                m.page_versions.c.page_path == page_path, m.page_versions.c.version_no == page["current_version"]
            ).values(change_type="reverted"))
        return page["current_version"]

    def recent_changes(self, limit=30, system_key=None):
        with self.engine.connect() as conn:
            stmt = select(m.page_versions).order_by(
                m.page_versions.c.created_at.desc(), m.page_versions.c.id.desc()).limit(limit)
            if system_key:
                stmt = stmt.where(m.page_versions.c.system_key == system_key)
            rows = conn.execute(stmt).mappings().all()
            return [{
                "system_key": r["system_key"], "component_key": r["component_key"],
                "page_path": r["page_path"], "version_no": r["version_no"],
                "change_type": r["change_type"], "change_summary": r["change_summary"] or "",
                "author": r["author"] or "", "created_at": fmt_dt(r["created_at"]),
            } for r in rows]

    # -- 검색 ------------------------------------------------------------

    def search(self, keyword, system_key=None, component_type=None, limit=100):
        if not keyword or not keyword.strip():
            return []
        kw = keyword.strip()
        kwl = kw.lower()
        with self.engine.connect() as conn:
            # 본문이 wikihub_content_blobs(압축)로 옮겨져 content 컬럼 LIKE 프리필터가 불가하다.
            # 범위 내 페이지를 모아 Python 에서 본문을 복원해 매칭한다.
            j = m.pages.join(
                m.components,
                (m.components.c.system_key == m.pages.c.system_key)
                & (m.components.c.component_key == m.pages.c.component_key),
                isouter=True,
            ).join(
                m.content_blobs, m.content_blobs.c.checksum == m.pages.c.checksum, isouter=True,
            )
            stmt = select(
                m.pages.c.system_key, m.pages.c.component_key, m.components.c.component_type,
                m.pages.c.page_path, m.pages.c.title, m.pages.c.content, m.pages.c.content_type,
                m.pages.c.current_version, m.pages.c.updated_at,
                m.content_blobs.c.algo, m.content_blobs.c.data,
            ).select_from(j).where(
                m.pages.c.is_deleted == False,  # noqa: E712
            )
            if system_key:
                stmt = stmt.where(m.pages.c.system_key == system_key)
            if component_type:
                stmt = stmt.where(m.components.c.component_type == component_type)
            stmt = stmt.order_by(m.pages.c.system_key, m.pages.c.component_key, m.pages.c.page_path)

            results = []
            for r in conn.execute(stmt).mappings():
                # HTML/JSON 대용량 산출물은 본문 스캔을 건너뛰고 경로·제목만 매칭한다(전문검색 대상 아님).
                if r["content_type"] in ("text/html", "application/json"):
                    content = ""
                elif r["algo"] is not None:
                    content = decode_blob(r["algo"], r["data"])
                else:  # 마이그레이션 전 구 데이터 폴백
                    content = r["content"] or ""
                path_title = f'{r["page_path"]}\n{r["title"] or ""}'.lower()
                if kwl not in content.lower() and kwl not in path_title:
                    continue
                results.append({
                    "system_key": r["system_key"], "component_key": r["component_key"],
                    "component_type": r["component_type"] or "common", "page_path": r["page_path"],
                    "title": r["title"] or r["page_path"], "current_version": r["current_version"],
                    "updated_at": fmt_dt(r["updated_at"]), "hit_count": content.lower().count(kwl),
                    "snippets": snippets(content, kw),
                })
                if len(results) >= limit * 3:  # 정렬 전 여유 있게 모았다가 상위 limit만 자른다
                    break
            results.sort(key=lambda x: x["hit_count"], reverse=True)
            return results[:limit]

    # -- 구조화 인덱스 ------------------------------------------------------

    def replace_index_rows(self, kind, system_key, component_key, rows):
        """한 컴포넌트의 인덱스 행을 통째로 교체한다 (스냅샷 의미라 부분 갱신하지 않는다)."""
        table = m.INDEX_TABLES[kind]
        now = utc_now()
        with self.engine.begin() as conn:
            conn.execute(delete(table).where(
                table.c.system_key == system_key, table.c.component_key == component_key))
            if rows:
                payload = [{**row, "system_key": system_key, "component_key": component_key,
                           "snapshot_at": now} for row in rows]
                conn.execute(insert(table), payload)
        return len(rows)

    def query_index(self, kind, keyword=None, system_key=None, component_key=None, limit=500):
        table = m.INDEX_TABLES[kind]
        if kind == "api":
            search_cols = [table.c.path, table.c.handler, table.c.source_file]
            order_col = table.c.path
        elif kind == "db":
            search_cols = [table.c.table_name, table.c.used_by]
            order_col = table.c.table_name
        elif kind == "route":
            search_cols = [table.c.route_path, table.c.view_name, table.c.calls_api]
            order_col = table.c.route_path
        elif kind == "external":
            search_cols = [table.c.target, table.c.source_file]
            order_col = table.c.target
        else:
            raise StoreError(f"알 수 없는 인덱스 종류: {kind}")

        with self.engine.connect() as conn:
            stmt = select(table)
            if keyword:
                like = f"%{keyword}%"
                stmt = stmt.where(or_(*[c.like(like) for c in search_cols]))
            if system_key:
                stmt = stmt.where(table.c.system_key == system_key)
            if component_key:
                stmt = stmt.where(table.c.component_key == component_key)
            stmt = stmt.order_by(order_col, table.c.system_key).limit(limit)
            return conn.execute(stmt).mappings().all()

    # -- 로그 --------------------------------------------------------------

    def write_log(self, system_key, component_key, action, totals, message="",
                  publisher_person_id=None):
        with self.engine.begin() as conn:
            conn.execute(insert(m.publish_log).values(
                system_key=system_key, component_key=component_key, action=action,
                pages_total=totals.get("total", 0), pages_created=totals.get("created", 0),
                pages_updated=totals.get("updated", 0), pages_deleted=totals.get("deleted", 0),
                message=(message or "")[:990], publisher_person_id=publisher_person_id,
                created_at=utc_now(),
            ))

    def recent_logs(self, limit=20):
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(m.publish_log).order_by(m.publish_log.c.created_at.desc(), m.publish_log.c.id.desc())
                .limit(limit)
            ).mappings().all()
            return [{
                "system_key": r["system_key"], "component_key": r["component_key"], "action": r["action"],
                "total": r["pages_total"], "created": r["pages_created"], "updated": r["pages_updated"],
                "deleted": r["pages_deleted"], "message": r["message"] or "", "created_at": fmt_dt(r["created_at"]),
            } for r in rows]

    # -- v1(구 단일 테이블) 이관 ---------------------------------------------

    def v1_projects(self):
        if not self.v1_table_exists():
            return []
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT project_name, COUNT(*) AS n FROM harness_wiki_pages GROUP BY project_name "
                "ORDER BY project_name"
            )).all()
            return [(r.project_name, r.n) for r in rows]

    def migrate_v1_project(self, project_name, system_key, component_key, component_type):
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT page_path, content, content_type FROM harness_wiki_pages WHERE project_name = :p"
            ), {"p": project_name}).all()
        self.upsert_system(system_key, display_name=system_key)
        self.upsert_component(system_key, component_key, component_type)
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for r in rows:
            res = self.save_page(system_key, component_key, r.page_path, r.content, r.content_type,
                                 author="migrate-v1", change_summary=f"v1 '{project_name}' 에서 이관")
            counts[res] = counts.get(res, 0) + 1
        counts["total"] = len(rows)
        self.write_log(system_key, component_key, "migrate-v1", counts, f"v1 project_name='{project_name}'")
        return counts

    # -- 본문 → blob 이관(일회성 용량 축소) ------------------------------------

    def migrate_content_to_blobs(self, dry_run=False, vacuum=True):
        """기존 pages/page_versions.content 를 wikihub_content_blobs 로 이관하고 content 컬럼을 빈 값('')으로 비운다.
        행은 삭제하지 않는다(이력 보존). 대용량 본문 메모리 폭주를 막기 위해 행 단위로 처리한다.
        반환: 통계 dict."""
        stats = {"pages_rows": 0, "versions_rows": 0, "unique_checksums": 0,
                 "blobs_existing": 0, "blobs_created": 0, "content_bytes": 0, "vacuumed": False}
        # 이관 대상: content 에 실제 본문이 남아 있는 행. 이미 이관된 행은 content=""(빈 값)이라 제외 → 재실행 안전.
        def _pending(tbl):
            return (tbl.c.content.isnot(None)) & (tbl.c.content != "")

        with self.engine.connect() as conn:
            # 행 수·고유 checksum 만 SQL 로 센다 — 본문 길이(LENGTH/LEN/DATALENGTH)는 엔진마다 함수가 갈려 쓰지 않는다.
            # 실제 본문 바이트(content_bytes)는 아래 실제 이관 패스에서 읽은 값으로 집계한다(dry-run 에서는 0).
            checksums = set()
            for tbl, key in ((m.pages, "pages_rows"), (m.page_versions, "versions_rows")):
                stats[key] = conn.execute(
                    select(func.count()).select_from(tbl).where(_pending(tbl))).scalar_one()
                for (cs,) in conn.execute(select(tbl.c.checksum).where(_pending(tbl)).distinct()):
                    checksums.add(cs)
            stats["unique_checksums"] = len(checksums)
            stats["blobs_existing"] = conn.execute(
                select(func.count()).select_from(m.content_blobs)).scalar_one()

        if dry_run:
            return stats

        for tbl in (m.pages, m.page_versions):
            with self.engine.connect() as conn:
                id_rows = conn.execute(
                    select(tbl.c.id).where(_pending(tbl)).order_by(tbl.c.id)).all()
            for (rid,) in id_rows:
                with self.engine.begin() as tx:
                    r = tx.execute(select(tbl.c.checksum, tbl.c.content)
                                   .where(tbl.c.id == rid)).first()
                    if r is None or not r.content:
                        continue
                    stats["content_bytes"] += len(r.content.encode("utf-8"))
                    if self._ensure_blob(tx, r.checksum, r.content):
                        stats["blobs_created"] += 1
                    tx.execute(update(tbl).where(tbl.c.id == rid).values(content=""))

        if vacuum and self.engine.dialect.name == "sqlite":
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql("VACUUM")
            stats["vacuumed"] = True
        return stats


def open_store(root, engine_override=None):
    """<root>/.env 를 읽어 WikiStore 를 연다. 스키마는 자동 생성한다."""
    import config
    engine, url, _env = config.resolve_all(root, engine_override)
    store = WikiStore(url, engine_name=engine)
    store.ensure_schema()
    return store
