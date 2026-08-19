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
import hashlib
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, select, insert, update, delete, func, or_, inspect, text

import models as m


class StoreError(Exception):
    pass


def sha256_text(text_):
    return hashlib.sha256(text_.encode("utf-8")).hexdigest()


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
                      owner=None, repo_url=None, tags=None):
        now = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(m.systems.c.system_key).where(m.systems.c.system_key == system_key)
            ).first()
            if row:
                values = {"updated_at": now}
                for col, val in [("display_name", display_name), ("description", description),
                                 ("owner", owner), ("repo_url", repo_url), ("tags", tags)]:
                    if val is not None:
                        values[col] = val
                conn.execute(update(m.systems).where(m.systems.c.system_key == system_key).values(**values))
                return False
            conn.execute(insert(m.systems).values(
                system_key=system_key, display_name=display_name or system_key,
                description=description or "", owner=owner or "", repo_url=repo_url or "",
                tags=tags or "", is_archived=False, created_at=now, updated_at=now,
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
            return {"content": r["content"], "content_type": r["content_type"],
                    "current_version": r["current_version"], "updated_at": fmt_dt(r["updated_at"]),
                    "is_deleted": bool(r["is_deleted"]), "title": r["title"] or page_path}

    def page_exists(self, system_key, component_key, page_path):
        with self.engine.connect() as conn:
            row = conn.execute(select(m.pages.c.id).where(
                m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                m.pages.c.page_path == page_path, m.pages.c.is_deleted == False)  # noqa: E712
            ).first()
            return row is not None

    def save_page(self, system_key, component_key, page_path, content, content_type,
                  author="wiki-hub", change_summary=""):
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
                conn.execute(insert(m.pages).values(
                    system_key=system_key, component_key=component_key, page_path=page_path,
                    title=title, content=content, content_type=content_type, checksum=checksum,
                    current_version=1, is_deleted=False, created_at=now, updated_at=now,
                ))
                self._insert_version(conn, system_key, component_key, page_path, 1, content,
                                     content_type, checksum, "created", change_summary or "최초 등록",
                                     author, now)
                return "created"

            old_checksum, old_version, was_deleted = cur.checksum, cur.current_version, bool(cur.is_deleted)
            if old_checksum == checksum and not was_deleted:
                return "unchanged"

            new_version = old_version + 1
            conn.execute(update(m.pages).where(
                m.pages.c.system_key == system_key, m.pages.c.component_key == component_key,
                m.pages.c.page_path == page_path
            ).values(title=title, content=content, content_type=content_type, checksum=checksum,
                     current_version=new_version, is_deleted=False, updated_at=now))
            change_type = "restored" if was_deleted else "updated"
            self._insert_version(conn, system_key, component_key, page_path, new_version, content,
                                 content_type, checksum, change_type, change_summary or "내용 변경",
                                 author, now)
            return "created" if was_deleted else "updated"

    def mark_deleted(self, system_key, component_key, page_path, author="wiki-hub", reason=""):
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
                                 author, now)
            return True

    def _insert_version(self, conn, system_key, component_key, page_path, version_no, content,
                        content_type, checksum, change_type, change_summary, author, created_at):
        conn.execute(insert(m.page_versions).values(
            system_key=system_key, component_key=component_key, page_path=page_path,
            version_no=version_no, content=content, content_type=content_type, checksum=checksum,
            change_type=change_type, change_summary=(change_summary or "")[:490],
            author=author or "", created_at=created_at,
        ))

    def list_versions(self, system_key, component_key, page_path):
        with self.engine.connect() as conn:
            rows = conn.execute(select(
                m.page_versions.c.version_no, m.page_versions.c.change_type,
                m.page_versions.c.change_summary, m.page_versions.c.author,
                m.page_versions.c.created_at, m.page_versions.c.checksum, m.page_versions.c.content,
            ).where(
                m.page_versions.c.system_key == system_key, m.page_versions.c.component_key == component_key,
                m.page_versions.c.page_path == page_path
            ).order_by(m.page_versions.c.version_no.desc())).all()
            return [{
                "version_no": r.version_no, "change_type": r.change_type,
                "change_summary": r.change_summary or "", "author": r.author or "",
                "created_at": fmt_dt(r.created_at), "checksum": r.checksum, "size": len(r.content or ""),
            } for r in rows]

    def get_version(self, system_key, component_key, page_path, version_no):
        with self.engine.connect() as conn:
            r = conn.execute(select(m.page_versions).where(
                m.page_versions.c.system_key == system_key, m.page_versions.c.component_key == component_key,
                m.page_versions.c.page_path == page_path, m.page_versions.c.version_no == version_no
            )).mappings().first()
            if not r:
                return None
            return {"content": r["content"], "content_type": r["content_type"],
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
        like = f"%{kw}%"
        with self.engine.connect() as conn:
            j = m.pages.join(
                m.components,
                (m.components.c.system_key == m.pages.c.system_key)
                & (m.components.c.component_key == m.pages.c.component_key),
                isouter=True,
            )
            stmt = select(
                m.pages.c.system_key, m.pages.c.component_key, m.components.c.component_type,
                m.pages.c.page_path, m.pages.c.title, m.pages.c.content,
                m.pages.c.current_version, m.pages.c.updated_at,
            ).select_from(j).where(
                m.pages.c.is_deleted == False,  # noqa: E712
                or_(m.pages.c.content.like(like), m.pages.c.page_path.like(like), m.pages.c.title.like(like)),
            )
            if system_key:
                stmt = stmt.where(m.pages.c.system_key == system_key)
            if component_type:
                stmt = stmt.where(m.components.c.component_type == component_type)
            stmt = stmt.order_by(m.pages.c.system_key, m.pages.c.component_key, m.pages.c.page_path)

            results = []
            for r in conn.execute(stmt).mappings():
                content = r["content"] or ""
                results.append({
                    "system_key": r["system_key"], "component_key": r["component_key"],
                    "component_type": r["component_type"] or "common", "page_path": r["page_path"],
                    "title": r["title"] or r["page_path"], "current_version": r["current_version"],
                    "updated_at": fmt_dt(r["updated_at"]), "hit_count": content.lower().count(kw.lower()),
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

    def write_log(self, system_key, component_key, action, totals, message=""):
        with self.engine.begin() as conn:
            conn.execute(insert(m.publish_log).values(
                system_key=system_key, component_key=component_key, action=action,
                pages_total=totals.get("total", 0), pages_created=totals.get("created", 0),
                pages_updated=totals.get("updated", 0), pages_deleted=totals.get("deleted", 0),
                message=(message or "")[:990], created_at=utc_now(),
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


def open_store(root, engine_override=None):
    """<root>/.env 를 읽어 WikiStore 를 연다. 스키마는 자동 생성한다."""
    import config
    engine, url, _env = config.resolve_all(root, engine_override)
    store = WikiStore(url, engine_name=engine)
    store.ensure_schema()
    return store
