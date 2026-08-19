# _workspace/index/*.json 을 API·DB·라우트·외부연동 인덱스 행으로 바꾸는 zero-LLM 추출기
# 별도 프로젝트 wiki-hub(E:/AI/wiki-hub)의 wikihub/index_extract.py를 그대로 옮긴 사본이다.
"""index_extract.py — harness 산출물 파일 규약만 아는 순수 함수 모음."""

import os
import re
import json


def _load(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"WARN: {path} 읽기 실패 — {e}")
        return None


def normalize_api_path(p):
    """/api/order/:id, /api/orders/{id}, /api/orders/${id} 를 모두 /api/orders/{} 로 정규화."""
    if not p:
        return ""
    p = str(p).split("?")[0].rstrip("/")
    p = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", "{}", p)
    p = re.sub(r"\$\{[^}]*\}", "{}", p)
    p = re.sub(r"\{[^}]*\}", "{}", p)
    return p.lower()


def extract_api_endpoints(workspace_dir):
    # 생성기에 따라 파일명이 api_contract.json / api_contracts.json 로 갈린다 (스키마는 동일).
    data = (_load(os.path.join(workspace_dir, "index", "api_contract.json"))
            or _load(os.path.join(workspace_dir, "index", "api_contracts.json")))
    rows = []
    for ep in (data or {}).get("endpoints", []):
        path = ep.get("path", "")
        rows.append({
            "method": (ep.get("method") or "").upper()[:10],
            "path": path[:490],
            "norm_path": normalize_api_path(path)[:490],
            "handler": (ep.get("handler") or "")[:290],
            "source_file": (ep.get("controller_file") or ep.get("file") or "")[:490],
            "auth_required": bool(ep.get("auth_required")),
            "note": (ep.get("description") or ep.get("note") or "")[:490],
        })
    return rows


def extract_db_objects(workspace_dir):
    schema = _load(os.path.join(workspace_dir, "index", "schema.json")) or {}
    usage = _load(os.path.join(workspace_dir, "index", "sql_usage.json")) or {}

    used_by = {}
    for s in usage.get("sqls", []):
        for t in s.get("tables", []):
            used_by.setdefault(str(t).upper(), []).append(f"{s.get('id', '')}({s.get('type', '')})")

    rows, seen = [], set()
    for t in schema.get("tables", []):
        name = t.get("name", "")
        if not name:
            continue
        seen.add(name.upper())
        cols = t.get("columns", [])
        pk = t.get("primary_key", []) or [c.get("name") for c in cols if c.get("primary_key")]
        rows.append({
            "table_name": name[:290],
            "column_count": len(cols),
            "primary_key": ", ".join(str(x) for x in pk)[:490],
            "columns_json": json.dumps(
                [{"name": c.get("name"), "type": c.get("type")} for c in cols], ensure_ascii=False),
            "used_by": ", ".join(used_by.get(name.upper(), []))[:2000],
        })

    for tname, refs in used_by.items():
        if tname in seen:
            continue
        rows.append({"table_name": tname[:290], "column_count": 0, "primary_key": "",
                     "columns_json": "", "used_by": ", ".join(refs)[:2000]})
    return rows


def extract_frontend_routes(workspace_dir):
    graph = _load(os.path.join(workspace_dir, "index", "call_graph.json")) or {}
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    view_types = {"view", "vue_view", "component", "page", "screen", "jsp", "route"}
    endpoint_types = {"endpoint", "api", "controller", "route", "external", "client"}
    by_id = {n.get("id"): n for n in nodes}

    calls = {}
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        tgt = by_id.get(dst) or {}
        if tgt.get("type") in endpoint_types:
            label = tgt.get("api") or e.get("label") or tgt.get("label") or dst
            calls.setdefault(src, []).append(str(label))

    rows = []
    for n in nodes:
        if n.get("type") not in view_types:
            continue
        nid = n.get("id")
        rows.append({
            "route_path": str(n.get("route") or n.get("api") or n.get("label") or nid)[:490],
            "view_name": str(n.get("label") or nid)[:290],
            "source_file": str(n.get("file") or "")[:490],
            "calls_api": ", ".join(sorted(set(calls.get(nid, []))))[:2000],
        })
    return rows


def extract_external_links(workspace_dir):
    data = _load(os.path.join(workspace_dir, "index", "external_io.json"))
    rows = []
    for c in (data or {}).get("communications", []):
        target = c.get("target") or c.get("topic") or c.get("path_pattern") or ""
        rows.append({
            "link_type": str(c.get("type") or "")[:40],
            "target": str(target)[:490],
            "source_file": str(c.get("file") or "")[:490],
            "line_no": str(c.get("line") or "")[:20],
        })
    return rows


def extract_all(project_root):
    ws = os.path.join(project_root, "_workspace")
    return {
        "api": extract_api_endpoints(ws),
        "db": extract_db_objects(ws),
        "route": extract_frontend_routes(ws),
        "external": extract_external_links(ws),
    }


def detect_stack(project_root):
    path = os.path.join(project_root, "_workspace", "01_analyzer_report.md")
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        head = f.read(4000)
    for pattern in [r"^\s*[-*]?\s*(?:주요\s*)?스택\s*[:：]\s*(.+)$",
                    r"^\s*[-*]?\s*Stack\s*[:：]\s*(.+)$",
                    r"^\|\s*스택\s*\|\s*(.+?)\s*\|"]:
        m = re.search(pattern, head, re.MULTILINE | re.IGNORECASE)
        if m:
            return m.group(1).strip()[:290]
    return ""
