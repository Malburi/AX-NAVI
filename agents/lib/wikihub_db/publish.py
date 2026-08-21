# harness wiki/ 폴더 + _workspace/**/*.json 을 중앙 DB(시스템·컴포넌트·버전 구조)로 발행하는 CLI
# 별도 프로젝트 wiki-hub(E:/AI/wiki-hub)의 wikihub/publish.py를 그대로 옮긴 사본이다 —
# 이 스크립트는 harness 플러그인에 내장돼 있어 wiki-hub 자체를 pip install 하지 않아도 된다.
# wiki-hub(별도 서버)는 이 스크립트가 쓴 같은 DB를 나중에 읽어 열람·관리 화면을 제공한다(view 전용).
"""publish.py — `python wikihub_db/publish.py --root ...`로 직접 실행하는 발행 스크립트.

백엔드·프론트엔드가 별도 저장소면 **같은 --system-key, 다른 --component-type**으로
양쪽에서 각각 실행한다. 그래야 허브에서 한 시스템 아래 두 레이어로 묶인다.
"""

import os
import re
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import store as store_mod
import index_extract

EXCLUDED_DIRS = {"lib", "_html", "__pycache__"}
EXCLUDED_ROOT_FILES = {"index.html", "serve.bat", "_sidebar.md", "_navbar.md"}
CONTENT_TYPE_BY_EXT = {".md": "text/markdown", ".html": "text/html"}
WORKSPACE_JSON_CONTENT_TYPE = "application/json"

_SCRIPT_SRC_RE = re.compile(r'<script([^>]*)\ssrc="(lib/[^"]+)"([^>]*)></script>')
_LINK_HREF_RE = re.compile(r'<link([^>]*)\shref="(lib/[^"]+)"([^>]*)/?>')

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def inline_local_assets(content, wiki_dir):
    """call-graph.html 등이 `lib/*.js`·`*.css`를 상대경로로 참조하면 본문에 그대로 인라인한다."""

    def read_asset(rel_path):
        abspath = os.path.join(wiki_dir, rel_path.replace("/", os.sep))
        if not os.path.isfile(abspath):
            return None
        with open(abspath, "r", encoding="utf-8") as f:
            return f.read()

    def repl_script(m):
        body = read_asset(m.group(2))
        return f"<script{m.group(1)}{m.group(3)}>{body}</script>" if body is not None else m.group(0)

    def repl_link(m):
        body = read_asset(m.group(2))
        return f"<style{m.group(1)}{m.group(3)}>{body}</style>" if body is not None else m.group(0)

    content = _SCRIPT_SRC_RE.sub(repl_script, content)
    content = _LINK_HREF_RE.sub(repl_link, content)
    return content


def iter_wiki_files(wiki_dir):
    for dirpath, dirnames, filenames in os.walk(wiki_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        is_root = os.path.normpath(dirpath) == os.path.normpath(wiki_dir)
        for filename in sorted(filenames):
            if is_root and filename in EXCLUDED_ROOT_FILES:
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in CONTENT_TYPE_BY_EXT:
                continue
            abspath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abspath, wiki_dir).replace(os.sep, "/")
            yield rel_path, abspath, CONTENT_TYPE_BY_EXT[ext]


def iter_workspace_json_files(project_root):
    """`_workspace/` 아래 모든 `*.json`을 project_root 기준 상대경로로 발행 대상에 포함한다."""
    ws_dir = os.path.join(project_root, "_workspace")
    if not os.path.isdir(ws_dir):
        return
    for dirpath, dirnames, filenames in os.walk(ws_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for filename in sorted(filenames):
            if not filename.lower().endswith(".json"):
                continue
            abspath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abspath, project_root).replace(os.sep, "/")
            yield rel_path, abspath, WORKSPACE_JSON_CONTENT_TYPE


def publish(store, project_root, wiki_dir, system_key, component_key, component_type,
            system_name=None, author="wikihub-db-publish", summary="", with_index=True,
            with_workspace_json=True, dry_run=False):
    if not os.path.isdir(wiki_dir):
        raise store_mod.StoreError(
            f"wiki 폴더 없음: {wiki_dir} — 먼저 harness의 generate-wiki 로 wiki 를 생성하세요.")

    pages = list(iter_wiki_files(wiki_dir))
    json_pages = list(iter_workspace_json_files(project_root)) if with_workspace_json else []
    if not pages and not json_pages:
        raise store_mod.StoreError(f"wiki 폴더에 발행할 .md/.html 페이지가 없습니다: {wiki_dir}")

    stack = index_extract.detect_stack(project_root)
    counts = {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0,
              "total": len(pages) + len(json_pages), "workspace_json_total": len(json_pages)}

    if dry_run:
        print(f"[dry-run] 시스템={system_key} 컴포넌트={component_key}({component_type}) "
              f"위키 페이지 {len(pages)}개 + 워크스페이스 JSON {len(json_pages)}개")
        for rel_path, _abspath, ctype in pages:
            print(f"  - {rel_path} ({ctype})")
        for rel_path, _abspath, ctype in json_pages:
            print(f"  - {rel_path} ({ctype})")
        return counts

    store.upsert_system(system_key, display_name=system_name)
    store.upsert_component(system_key, component_key, component_type,
                           display_name=component_key, repo_root=os.path.abspath(project_root), stack=stack)

    seen = set()
    for rel_path, abspath, content_type in pages:
        with open(abspath, "r", encoding="utf-8") as f:
            content = f.read()
        if content_type == "text/html":
            content = inline_local_assets(content, wiki_dir)
        result = store.save_page(system_key, component_key, rel_path, content, content_type,
                                 author=author, change_summary=summary)
        counts[result] = counts.get(result, 0) + 1
        seen.add(rel_path)

    for rel_path, abspath, content_type in json_pages:
        with open(abspath, "r", encoding="utf-8") as f:
            content = f.read()
        result = store.save_page(system_key, component_key, rel_path, content, content_type,
                                 author=author, change_summary=summary)
        counts[result] = counts.get(result, 0) + 1
        seen.add(rel_path)

    for existing in store.list_pages(system_key, component_key):
        if existing["page_path"] not in seen:
            if store.mark_deleted(system_key, component_key, existing["page_path"], author=author,
                                  reason="발행 시점 wiki 폴더에 없음"):
                counts["deleted"] += 1

    index_counts = {}
    if with_index:
        extracted = index_extract.extract_all(project_root)
        for kind, rows in extracted.items():
            index_counts[kind] = store.replace_index_rows(kind, system_key, component_key, rows)

    store.write_log(system_key, component_key, "publish", counts, summary or (f"stack={stack}" if stack else ""))

    print(f"발행 완료: {store.describe()}")
    print(f"  시스템   : {system_key}")
    print(f"  컴포넌트 : {component_key} [{component_type}]" + (f"  stack={stack}" if stack else ""))
    print(f"  페이지   : 신규 {counts['created']} / 변경 {counts['updated']} / "
          f"동일 {counts['unchanged']} / 삭제표시 {counts['deleted']} (총 {counts['total']})")
    if json_pages:
        print(f"  워크스페이스 JSON : {counts['workspace_json_total']}개 (위 페이지 수에 포함, "
              "다른 팀원이 harness-init 재실행 없이 재사용 가능한 원본 index 데이터)")
    if index_counts:
        print("  인덱스   : " + ", ".join(f"{k} {v}건" for k, v in index_counts.items()))
    return counts


def pull(store, project_root, wiki_dir, system_key, component_key):
    """DB → 폴더. `_workspace/`로 시작하는 페이지는 project_root 기준 원래 경로로,
    나머지(위키 문서)는 wiki_dir 로 복원한다."""
    pages = store.list_pages(system_key, component_key)
    if not pages:
        raise store_mod.StoreError(f"DB 에 페이지 없음: {system_key}/{component_key}")

    os.makedirs(wiki_dir, exist_ok=True)
    wiki_count, workspace_count = 0, 0
    for meta in pages:
        page = store.get_page(system_key, component_key, meta["page_path"])
        rel = meta["page_path"]
        if rel.startswith("_workspace/"):
            dest = os.path.join(project_root, rel.replace("/", os.sep))
            workspace_count += 1
        else:
            dest = os.path.join(wiki_dir, rel.replace("/", os.sep))
            wiki_count += 1
        os.makedirs(os.path.dirname(dest) or wiki_dir, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(page["content"])

    store.write_log(system_key, component_key, "pull", {"total": len(pages)},
                    f"→ {wiki_dir}" + (f" + {project_root}/_workspace" if workspace_count else ""))
    print(f"폴더 복원 완료: {wiki_dir} — 위키 {wiki_count}개 + 워크스페이스 JSON {workspace_count}개 "
          f"({system_key}/{component_key})")
    if workspace_count:
        print(f"  워크스페이스 JSON은 {project_root}/_workspace/ 원래 위치로 복원했습니다.")
    return len(pages)


def guess_v1_split(project_name):
    suffix_map = {
        "BACKEND": "backend", "BE": "backend", "API": "backend", "SERVER": "backend",
        "FRONTEND": "frontend", "FE": "frontend", "WEB": "frontend", "UI": "frontend",
        "BATCH": "batch", "MOBILE": "mobile", "APP": "mobile",
    }
    for sep in ["-", "_"]:
        if sep in project_name:
            head, _, tail = project_name.rpartition(sep)
            ctype = suffix_map.get(tail.upper())
            if ctype and head:
                return head, ctype
    return project_name, config.DEFAULT_COMPONENT_TYPE


def migrate_v1(store, mappings=None, dry_run=False):
    projects = store.v1_projects()
    if not projects:
        print("구 단일 테이블(harness_wiki_pages, project_name 컬럼)에 이관할 데이터가 없습니다.")
        return

    explicit = {}
    for mapping in mappings or []:
        left, _, right = mapping.partition("=")
        parts = right.split(":")
        if not left or len(parts) < 2:
            print(f"WARN: 매핑 형식 오류 무시 — {mapping} (형식: v1키=시스템키:컴포넌트키[:타입])")
            continue
        ckey = parts[1]
        ctype = parts[2] if len(parts) > 2 else (
            ckey if ckey in config.COMPONENT_TYPES else config.DEFAULT_COMPONENT_TYPE)
        explicit[left] = (parts[0], ckey, ctype)

    print(f"{'v1 project_name':28} {'페이지':>5}  →  시스템 / 컴포넌트 [타입]")
    plan = []
    for name, count in projects:
        if name in explicit:
            skey, ckey, ctype = explicit[name]
        else:
            skey, ctype = guess_v1_split(name)
            ckey = ctype
        plan.append((name, count, skey, ckey, ctype))
        print(f"{name:28} {count:>5}  →  {skey} / {ckey} [{ctype}]")

    if dry_run:
        print("\n[dry-run] 실제 이관은 --migrate-v1 을 --dry-run 없이 다시 실행하세요.")
        return

    print()
    for name, _count, skey, ckey, ctype in plan:
        counts = store.migrate_v1_project(name, skey, ckey, ctype)
        print(f"이관 완료: {name} → {skey}/{ckey} (신규 {counts['created']}, 변경 {counts['updated']}, "
              f"동일 {counts['unchanged']})")
    print("\n원본 v1 테이블은 지우지 않았습니다. 확인 후 직접 정리하세요.")


def migrate_blobs(store, dry_run=False):
    """기존 pages/page_versions.content 본문을 압축·dedup 해 wikihub_content_blobs 로 이관한다."""
    stats = store.migrate_content_to_blobs(dry_run=dry_run)
    print(f"이관 대상 행 : pages {stats['pages_rows']} + versions {stats['versions_rows']}개 "
          f"(고유 checksum {stats['unique_checksums']}개)")
    print(f"기존 blob    : {stats['blobs_existing']}개")
    if dry_run:
        print("[dry-run] 실제 이관은 --migrate-blobs 를 --dry-run 없이 다시 실행하세요. "
              "(dedup + gzip 으로 대폭 축소됩니다)")
        return
    mb = stats["content_bytes"] / (1024 * 1024)
    print(f"이관 완료    : 본문 약 {mb:.1f}MB → blob 신규 {stats['blobs_created']}개 생성, content 컬럼 비움")
    if stats["vacuumed"]:
        print("SQLite VACUUM 실행 완료 — 파일 크기가 실제로 줄었습니다.")
    else:
        print("주의: 이 엔진은 자동 축소하지 않습니다. 운영 DB 는 담당자가 직접 공간을 회수하세요 "
              "(MSSQL: DBCC SHRINKFILE / 인덱스 재구성, PostgreSQL: VACUUM FULL, Oracle: 테이블스페이스 정리).")


def print_list(store):
    systems = store.list_systems(include_archived=True)
    if not systems:
        print("등록된 시스템이 없습니다.")
        return
    components = store.list_components()
    for s in systems:
        flag = " [보관됨]" if s["is_archived"] else ""
        print(f"■ {s['system_key']} — {s['display_name']}{flag}  ({s['page_count']}페이지, 최근 {s['updated_at'] or '-'})")
        for c in [c for c in components if c["system_key"] == s["system_key"]]:
            print(f"    └ {c['component_key']:16} [{c['component_type']:9}] {c['page_count']:>3}페이지  {c['stack'] or '-'}")


def main():
    parser = argparse.ArgumentParser(
        description="harness wiki 폴더를 중앙 DB로 발행 (다중 시스템 · 레이어 분리 · 버전 관리, wiki-hub 설치 불필요)")
    parser.add_argument("--root", required=True, help="harness 프로젝트 루트 절대 경로 (.env 위치)")
    parser.add_argument("--wiki-dir", help="wiki 폴더 경로 (기본: <root>/wiki)")
    parser.add_argument("--engine", choices=config.SUPPORTED_ENGINES, help="미지정 시 .env WIKI_DB_ENGINE (기본 sqlite)")
    parser.add_argument("--system-key", help="시스템 키 (예: ORDER). 미지정 시 .env WIKI_SYSTEM_KEY")
    parser.add_argument("--system-name", help="시스템 표시 이름 (예: 주문관리시스템)")
    parser.add_argument("--component-key", help="컴포넌트 키. 미지정 시 타입과 동일")
    parser.add_argument("--component-type", choices=config.COMPONENT_TYPES,
                        help="컴포넌트 타입. 미지정 시 .env → pair_config.md → 폴더명 추정 순")
    parser.add_argument("--author", default="wikihub-db-publish")
    parser.add_argument("--summary", default="", help="이번 발행의 변경 요약 (버전 이력에 기록)")
    parser.add_argument("--no-index", action="store_true", help="구조화 인덱스 추출 생략")
    parser.add_argument("--no-workspace-json", action="store_true",
                        help="_workspace/**/*.json(call_graph 등 harness index + writer_decisions 등) 발행 생략")
    parser.add_argument("--save-env", action="store_true", help="결정된 키를 .env 에 저장 (기존 값은 덮어쓰지 않음)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pull", action="store_true", help="발행 대신 DB → wiki 폴더로 복원")
    parser.add_argument("--list", action="store_true", help="등록된 시스템·컴포넌트 목록 출력")
    parser.add_argument("--migrate-v1", action="store_true", help="구 단일 테이블 데이터를 새 스키마로 이관")
    parser.add_argument("--migrate-blobs", action="store_true",
                        help="기존 content 본문을 압축·dedup 해 wikihub_content_blobs 로 이관(용량 축소)")
    parser.add_argument("--map", action="append", default=[], help="v1 이관 매핑 (반복 가능)")
    args = parser.parse_args()

    project_root = os.path.abspath(args.root)

    try:
        engine, url, env = config.resolve_all(project_root, args.engine)
        store = store_mod.WikiStore(url, engine_name=engine)
        store.ensure_schema()
    except config.ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        with store:
            if args.list:
                print_list(store)
                return
            if args.migrate_v1:
                migrate_v1(store, args.map, args.dry_run)
                return
            if args.migrate_blobs:
                migrate_blobs(store, args.dry_run)
                return

            system_key = config.resolve_system_key(project_root, env, args.system_key)
            component_key, component_type = config.detect_component(
                project_root, env, args.component_key, args.component_type)
            wiki_dir = os.path.abspath(args.wiki_dir or os.path.join(project_root, "_workspace", "wiki"))

            if args.save_env and not args.dry_run:
                config.upsert_env_value(project_root, "WIKI_SYSTEM_KEY", system_key)
                config.upsert_env_value(project_root, "WIKI_COMPONENT_KEY", component_key)
                config.upsert_env_value(project_root, "WIKI_COMPONENT_TYPE", component_type)

            if args.pull:
                pull(store, project_root, wiki_dir, system_key, component_key)
                return

            publish(store, project_root, wiki_dir, system_key, component_key, component_type,
                    system_name=args.system_name or env.get("WIKI_SYSTEM_NAME"),
                    author=args.author, summary=args.summary,
                    with_index=not args.no_index, with_workspace_json=not args.no_workspace_json,
                    dry_run=args.dry_run)
    except store_mod.StoreError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
