# harness 산출물을 wiki 폴더(Docsify·call-graph.html·정적 HTML)로 변환하는 zero-LLM 오케스트레이터
import os
import json
import re
import sys
import wiki_render
import wiki_content
import docsify_convert

# 템플릿(call-graph)과 vis-network 라이브러리는 이 스크립트가 속한
# 플러그인 저장소(agents/lib/)에 있다. 대상 프로젝트(project_root) 안에는 없다 — 대상
# 프로젝트 경로 기준으로 찾으면 실사용(플러그인으로 설치되어 다른 프로젝트에 대해 실행되는 경우)
# 항상 못 찾아서 조용히 스킵되는 버그가 된다.
LIB_DIR = os.path.dirname(os.path.abspath(__file__))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
from datetime import datetime

def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def render_and_track(wiki_dir, page_entries, project_name, filename, content, label):
    """폴더 모드에서 서버 없이 브라우저로 바로 열리도록, .md 페이지를
    wiki/_html/<name>.html 정적 렌더 사본으로도 저장하고 index.html용 항목을 기록한다."""
    html_name = os.path.splitext(filename)[0] + ".html"
    rendered = wiki_render.render_markdown_page(project_name, filename, content, index_href="../offline.html")
    write_file(os.path.join(wiki_dir, "_html", html_name), rendered)
    page_entries.append((f"_html/{html_name}", label, filename))


def parse_pair_config(root):
    """_workspace/pair_config.md (단순 key: value 마크다운)를 파싱. 없으면 None.
    hub-roots(1:N) 파일은 '## Partner:' 블록 안에 partner_root 등 같은 키 이름이 반복되므로,
    그 앞부분(project_type/init_mode/linked_at 같은 공통 키)까지만 스캔 대상으로 자른다 —
    안 그러면 첫 번째 파트너 블록의 값이 마치 1:1 최상단 값인 것처럼 잘못 읽힌다."""
    text = read_file(os.path.join(root, "_workspace", "pair_config.md"))
    if not text:
        return None
    scan_text = text.split("## Partner:", 1)[0]
    cfg = {}
    for key in ["project_type", "partner_type", "partner_root", "partner_workspace",
                "partner_stack", "api_base_url", "api_contract_path",
                "partner_api_contract", "linked_at"]:
        m = re.search(rf"^{key}:\s*(.+)$", scan_text, re.MULTILINE)
        if m:
            cfg[key] = m.group(1).strip()
    return cfg or None


def parse_pair_config_partners(root):
    """_workspace/pair_config.md가 hub-roots(1:N, 예: 백엔드+웹+모바일+관리자) 형식이면
    '## Partner: <label>' 블록마다 파싱해 리스트로 반환. paired-roots(1:1, 기존 flat 형식)나
    파일 자체가 없으면 빈 리스트 — parse_pair_config()의 1:1 경로는 그대로 둔 채 순수 추가.
    라인 단위로 블록을 나눈다 (정규식 하나로 MULTILINE '$' + DOTALL '.'을 같이 쓰면 그리디
    매칭이 파일 끝까지 삼켜버리는 문제가 있어 일부러 피함)."""
    text = read_file(os.path.join(root, "_workspace", "pair_config.md"))
    if not text or "## Partner:" not in text:
        return []

    blocks = []  # (label, block_text)
    label, buf = None, []
    for line in text.splitlines():
        m = re.match(r"^## Partner:\s*(.+)$", line)
        if m:
            if label is not None:
                blocks.append((label, "\n".join(buf)))
            label, buf = m.group(1).strip(), []
        elif label is not None:
            buf.append(line)
    if label is not None:
        blocks.append((label, "\n".join(buf)))

    partners = []
    for label, block in blocks:
        cfg = {"label": label}
        for key in ["partner_role_label", "partner_type", "partner_root", "partner_workspace",
                    "partner_stack", "api_base_url", "api_contract_path", "partner_api_contract"]:
            km = re.search(rf"^{key}:\s*(.+)$", block, re.MULTILINE)
            if km:
                cfg[key] = km.group(1).strip()
        if cfg.get("partner_role_label"):
            cfg["label"] = cfg["partner_role_label"]
        partners.append(cfg)
    return partners


def normalize_api_path(p):
    """/api/order/:id, /api/orders/{id}, /api/orders/${id} 를 모두 /api/orders/{} 로 정규화."""
    if not p:
        return ""
    p = p.split("?")[0].rstrip("/")
    p = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", "{}", p)
    p = re.sub(r"\$\{[^}]*\}", "{}", p)
    p = re.sub(r"\{[^}]*\}", "{}", p)
    return p.lower()


def prefix_graph(graph, prefix):
    """파트너 그래프의 노드/엣지 id에 접두사를 붙여 자기 그래프와 충돌하지 않게 한다."""
    if not graph:
        return {"nodes": [], "edges": []}
    nodes = []
    for n in graph.get("nodes", []):
        n2 = dict(n)
        n2["id"] = f"{prefix}{n.get('id')}"
        nodes.append(n2)
    edges = []
    for e in graph.get("edges", []):
        e2 = dict(e)
        e2["from"] = f"{prefix}{e.get('from')}"
        e2["to"] = f"{prefix}{e.get('to')}"
        edges.append(e2)
    return {"nodes": nodes, "edges": edges}


def extract_path_and_method(text_fields):
    """노드의 id/label/note/file 텍스트에서 HTTP 메서드·경로 후보를 뽑는다. 못 찾으면 (None, None)."""
    combined = " ".join([t for t in text_fields if t])
    method = None
    m = re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\b", combined, re.IGNORECASE)
    if m:
        method = m.group(1).upper()
    path = None
    m2 = re.search(r"(/[A-Za-z0-9_\-{}:$./]+)", combined)
    if m2:
        path = m2.group(1)
    return method, path


def build_endpoint_index(contract):
    """api_contract.json의 endpoints -> {(method, normalized_path): endpoint_dict}."""
    idx = {}
    if not contract:
        return idx
    for ep in contract.get("endpoints", []):
        key = (ep.get("method", "").upper(), normalize_api_path(ep.get("path", "")))
        idx[key] = ep
    return idx


def find_backend_node_for_endpoint(endpoint, backend_nodes):
    """controller_file/handler로 call_graph 노드를 찾는다 (같은 저장소라 file 경로가 그대로 일치한다).
    결정론적 인덱서는 같은 값을 `file` 키에 넣으므로 양쪽을 다 본다 — 안 그러면 크로스 엣지가 조용히 0건이 된다."""
    cfile = endpoint.get("controller_file") or endpoint.get("file") or ""
    handler = (endpoint.get("handler") or "").lower()
    if not cfile:
        return None
    # 핸들러 이름을 못 뽑으면 파일명이 대신 들어온다(결정론적 인덱서). 그걸로 노드 id를 찾으면
    # 절대 안 맞으므로 파일 매칭만 쓴다 — 안 그러면 크로스 엣지가 통째로 0건이 된다.
    if handler == os.path.basename(cfile).lower():
        handler = ""
    if handler:
        for n in backend_nodes:
            nfile = n.get("file", "")
            if nfile and (nfile in cfile or cfile in nfile):
                if handler in str(n.get("id", "")).lower() or handler in str(n.get("label", "")).lower():
                    return n.get("id")
    # 핸들러 이름이 없으면 위치로 찾는다. 엔드포인트 줄은 보통 데코레이터·애노테이션 줄이고
    # 실제 함수 선언은 그 몇 줄 아래이므로, 바로 뒤에 오는 노드를 먼저 본다. 그 다음이 감싸는 노드.
    # (파일의 첫 노드를 집으면 라우트 함수가 아니라 그 위의 DTO 클래스로 연결돼 그래프가 엉뚱해진다.)
    following = _node_following(backend_nodes, cfile, endpoint.get("line"))
    if following:
        return following
    enclosing = _node_enclosing(backend_nodes, cfile, endpoint.get("line"))
    if enclosing:
        return enclosing
    for n in backend_nodes:
        nfile = n.get("file", "")
        if nfile and (nfile in cfile or cfile in nfile):
            return n.get("id")
    return None


def infer_cross_edges(frontend_nodes, endpoint_index, backend_nodes):
    """프론트 external/client 노드 <-> 백엔드 엔드포인트 노드를 메서드+경로 매칭으로 연결한다.
    노드에 경로 정보가 없으면(analyzer가 안 채운 경우) 매칭 0건 — 조용히 실패하지 않고 호출부에서 로그로 알린다."""
    edges = []
    unmatched = 0
    for n in frontend_nodes:
        if n.get("type", "") not in ("external", "client", "api"):
            continue
        method, path = extract_path_and_method([
            str(n.get("id", "")), str(n.get("label", "")),
            str(n.get("note", "")), str(n.get("file", "")),
        ])
        if not path:
            unmatched += 1
            continue
        npath = normalize_api_path(path)
        ep = endpoint_index.get((method, npath)) if method else None
        if not ep:
            candidates = [v for (m, p), v in endpoint_index.items() if p == npath]
            if len(candidates) == 1:
                ep = candidates[0]
        if not ep:
            unmatched += 1
            continue
        backend_id = find_backend_node_for_endpoint(ep, backend_nodes)
        if backend_id:
            edges.append({
                "from": n.get("id"), "to": backend_id,
                "label": f"{ep.get('method')} {ep.get('path')}", "type": "call",
            })
        else:
            unmatched += 1
    return edges, unmatched


def _node_enclosing(nodes, file_rel, line):
    """같은 파일에서 해당 줄을 감싸는 노드(그 줄 이전에 시작한 것 중 가장 가까운 것)를 찾는다."""
    target = (file_rel or "").replace("\\", "/")
    if not target:
        return None
    best = None
    for n in nodes:
        if (n.get("file") or "").replace("\\", "/") != target:
            continue
        nline = n.get("line") or 0
        if line and nline and nline > line:
            continue
        if best is None or (nline or 0) > (best.get("line") or 0):
            best = n
    return best.get("id") if best else None


def _node_following(nodes, file_rel, line, window=6):
    """같은 파일에서 해당 줄 직후(window줄 이내)에 시작하는 노드. 데코레이터·애노테이션 아래의
    실제 핸들러 함수를 집기 위한 것이다."""
    target = (file_rel or "").replace("\\", "/")
    if not target or not line:
        return None
    best = None
    for n in nodes:
        if (n.get("file") or "").replace("\\", "/") != target:
            continue
        nline = n.get("line") or 0
        if nline < line or nline > line + window:
            continue
        if best is None or nline < (best.get("line") or 0):
            best = n
    return best.get("id") if best else None


def infer_cross_edges_from_consumers(consumer_contract, frontend_nodes, endpoint_index, backend_nodes):
    """api_contract.json의 consumers(axios/fetch/HttpClient 호출 지점)로 크로스 엣지를 만든다.
    노드 텍스트에서 경로를 긁는 방식(infer_cross_edges)은 결정론적 인덱서 산출물처럼 노드에 경로가
    안 담기는 그래프에서 항상 0건이었다 — 계약에 이미 method·path_pattern·file·line이 있으므로 그걸 쓴다."""
    edges, unmatched = [], 0
    for consumer in (consumer_contract or {}).get("consumers", []):
        npath = normalize_api_path(consumer.get("path_pattern") or consumer.get("path") or "")
        if not npath:
            unmatched += 1
            continue
        method = (consumer.get("method") or "").upper()
        endpoint = endpoint_index.get((method, npath))
        if not endpoint:
            same_path = [v for (_m, p), v in endpoint_index.items() if p == npath]
            endpoint = same_path[0] if len(same_path) == 1 else None
        if not endpoint:
            unmatched += 1
            continue
        src = _node_enclosing(frontend_nodes, consumer.get("file"), consumer.get("line"))
        dst = find_backend_node_for_endpoint(endpoint, backend_nodes)
        if src and dst:
            edges.append({"from": src, "to": dst, "label": f"{endpoint.get('method')} {endpoint.get('path')}", "type": "call"})
        else:
            unmatched += 1
    return edges, unmatched


def merge_partner_call_graph(project_root, raw_graph):
    """pair_config.md가 있으면 파트너 call_graph.json을 병합하고, api_contract.json 기반으로
    프론트<->백엔드 크로스 엣지를 추론한다. 전부 결정론적 문자열 매칭 — LLM 미개입.
    반환: (병합된 그래프, merge_info dict — 07_wiki_build.md 보고용)"""
    no_merge_info = {"merged": False}
    pair_cfg = parse_pair_config(project_root)
    if not pair_cfg or not pair_cfg.get("partner_workspace"):
        return raw_graph, no_merge_info

    partner_graph = load_json(os.path.join(pair_cfg["partner_workspace"], "index", "call_graph.json"))
    if not partner_graph:
        print("WARN: pair_config.md 있으나 파트너 call_graph.json 없음/비어있음 — 크로스 리포 병합 스킵")
        return raw_graph, {"merged": False, "reason": "파트너 call_graph.json 없음/비어있음"}

    prefixed_partner = prefix_graph(partner_graph, "partner_")
    own_type = pair_cfg.get("project_type", "")

    endpoint_index, backend_nodes, frontend_nodes = {}, [], []
    consumer_contract = None
    if own_type == "backend":
        backend_nodes = raw_graph.get("nodes", [])
        frontend_nodes = prefixed_partner.get("nodes", [])
        own_contract = load_json(os.path.join(project_root, "_workspace", "index", "api_contract.json"))
        endpoint_index = build_endpoint_index(own_contract)
        consumer_contract = load_json(os.path.join(pair_cfg["partner_workspace"], "index", "api_contract.json"))
    elif own_type == "frontend":
        backend_nodes = prefixed_partner.get("nodes", [])
        frontend_nodes = raw_graph.get("nodes", [])
        partner_contract_path = pair_cfg.get("partner_api_contract")
        partner_contract = load_json(partner_contract_path) if partner_contract_path else None
        endpoint_index = build_endpoint_index(partner_contract)
        consumer_contract = load_json(os.path.join(project_root, "_workspace", "index", "api_contract.json"))

    cross_edges = []
    unmatched = 0
    if endpoint_index and (backend_nodes or frontend_nodes):
        cross_edges, unmatched = infer_cross_edges(frontend_nodes, endpoint_index, backend_nodes)
        consumer_edges, consumer_unmatched = infer_cross_edges_from_consumers(
            consumer_contract, frontend_nodes, endpoint_index, backend_nodes)
        seen = {(e["from"], e["to"]) for e in cross_edges}
        cross_edges += [e for e in consumer_edges if (e["from"], e["to"]) not in seen]
        unmatched += consumer_unmatched
        print(f"Cross-repo merge: partner nodes {len(prefixed_partner.get('nodes', []))}, "
              f"inferred cross edges {len(cross_edges)} (unmatched candidates: {unmatched})")
    else:
        print(f"Cross-repo merge: partner nodes {len(prefixed_partner.get('nodes', []))} merged, "
              f"cross edges 0 (api_contract.json 없음 또는 project_type 미상 — 경로 매칭 스킵)")

    merge_info = {
        "merged": True,
        "partner_type": pair_cfg.get("partner_type", "미상"),
        "partner_nodes": len(prefixed_partner.get("nodes", [])),
        "cross_edges": len(cross_edges),
        "unmatched": unmatched,
    }
    merged_graph = {
        "nodes": raw_graph.get("nodes", []) + prefixed_partner.get("nodes", []),
        "edges": raw_graph.get("edges", []) + prefixed_partner.get("edges", []) + cross_edges,
    }
    return merged_graph, merge_info


def merge_hub_partner_call_graphs(project_root, raw_graph, partner_cfgs):
    """hub-roots(1:N) 버전의 merge_partner_call_graph — 등록된 파트너 전부(웹/모바일/관리자 등)를
    각각 고유 접두사(partner0_, partner1_, ...)로 병합한다. own_type은 항상 backend로 취급한다
    (hub-roots는 1개 중심(backend) + N개 소비자(frontend류) 구조라는 전제 — pair-init 참조).
    반환: (병합된 그래프, {"merged": bool, "partners": [{label, nodes, cross_edges, unmatched}, ...]})"""
    if not partner_cfgs:
        return raw_graph, {"merged": False}

    own_contract = load_json(os.path.join(project_root, "_workspace", "index", "api_contract.json"))
    endpoint_index = build_endpoint_index(own_contract)
    backend_nodes = raw_graph.get("nodes", [])

    merged_nodes = list(raw_graph.get("nodes", []))
    merged_edges = list(raw_graph.get("edges", []))
    partner_reports = []

    for i, cfg in enumerate(partner_cfgs):
        ws = cfg.get("partner_workspace")
        label = cfg.get("label") or cfg.get("partner_type") or f"파트너{i+1}"
        if not ws:
            partner_reports.append({"label": label, "nodes": 0, "cross_edges": 0, "unmatched": 0, "skipped": "partner_workspace 없음"})
            continue
        partner_graph = load_json(os.path.join(ws, "index", "call_graph.json"))
        if not partner_graph:
            partner_reports.append({"label": label, "nodes": 0, "cross_edges": 0, "unmatched": 0, "skipped": "call_graph.json 없음/비어있음"})
            continue

        prefixed = prefix_graph(partner_graph, f"partner{i}_")
        cross_edges, unmatched = [], 0
        if endpoint_index:
            cross_edges, unmatched = infer_cross_edges(prefixed.get("nodes", []), endpoint_index, backend_nodes)
            # 1:1과 동일하게 클라이언트의 api_contract.json consumers로도 연결한다 (노드에 경로가 없는 그래프 대응)
            consumer_edges, consumer_unmatched = infer_cross_edges_from_consumers(
                load_json(os.path.join(ws, "index", "api_contract.json")),
                prefixed.get("nodes", []), endpoint_index, backend_nodes)
            seen = {(e["from"], e["to"]) for e in cross_edges}
            cross_edges += [e for e in consumer_edges if (e["from"], e["to"]) not in seen]
            unmatched += consumer_unmatched

        merged_nodes += prefixed.get("nodes", [])
        merged_edges += prefixed.get("edges", []) + cross_edges
        partner_reports.append({
            "label": label, "nodes": len(prefixed.get("nodes", [])),
            "cross_edges": len(cross_edges), "unmatched": unmatched,
        })
        print(f"Cross-repo merge [{label}]: nodes {len(prefixed.get('nodes', []))}, "
              f"inferred cross edges {len(cross_edges)} (unmatched: {unmatched})")

    return {"nodes": merged_nodes, "edges": merged_edges}, {"merged": True, "partners": partner_reports}


def _partner_paths(pair_cfg):
    """pair_cfg에서 파트너 _workspace 하위 산출물 절대경로들을 계산. pair_cfg 없으면 전부 None."""
    if not pair_cfg or not pair_cfg.get("partner_workspace"):
        return None
    ws = pair_cfg["partner_workspace"]
    return {
        "label": pair_cfg.get("label") or pair_cfg.get("partner_type", "연동 저장소"),
        "analyzer_report": os.path.join(ws, "01_analyzer_report.md"),
        "api_contract": pair_cfg.get("partner_api_contract") or os.path.join(ws, "index", "api_contract.json"),
        "schema": os.path.join(ws, "index", "schema.json"),
        "sql_usage": os.path.join(ws, "index", "sql_usage.json"),
        "external_io": os.path.join(ws, "index", "external_io.json"),
    }


def merge_db_tables_into_graph(raw_graph, schema_json, sql_usage_json):
    """schema.json의 테이블 + sql_usage.json의 DAO 호출 관계를 call_graph에 병합해
    db_table 노드와 DAO→테이블 엣지를 합성한다. call_graph.json 자체에는 이 정보가 없다 —
    결정론적 인덱서(build-index.mjs)가 테이블 정보를 schema.json에만 쓰고 call_graph 노드로는
    만들지 않기 때문(설계상 분리). wiki 렌더링용 메모리 그래프에만 반영하고 call_graph.json
    원본 파일은 건드리지 않는다. 전부 결정론적 매칭 — LLM 미개입.
    반환: (병합된 그래프, db_merge_info dict — 07_wiki_build.md 보고용)"""
    tables = (schema_json or {}).get("tables") or []
    if not tables:
        return raw_graph, {"table_nodes": 0, "query_edges": 0}

    nodes = list(raw_graph.get("nodes") or [])
    edges = list(raw_graph.get("edges") or [])
    existing_ids = {n.get("id") for n in nodes}

    table_node_ids = {}
    for t in tables:
        name = t.get("name")
        if not name or name in table_node_ids:
            continue
        tid = f"db_table:{name}"
        table_node_ids[name] = tid
        if tid in existing_ids:
            continue
        col_count = len(t.get("columns") or [])
        pk = t.get("primary_key") or []
        note = f"컬럼 {col_count}개" + (f" · PK {', '.join(pk)}" if pk else "")
        nodes.append({"id": tid, "label": name, "type": "table", "note": note})
        existing_ids.add(tid)

    sqls = (sql_usage_json or {}).get("sqls") or []
    usages = (sql_usage_json or {}).get("usages") or []
    sql_tables = {s.get("id"): (s.get("tables") or []) for s in sqls if s.get("id")}
    sql_type = {s.get("id"): s.get("type", "") for s in sqls if s.get("id")}

    seen_edges = set()
    for u in usages:
        method = u.get("method")
        sql_id = u.get("sql_id")
        if not method or method == "unknown" or method not in existing_ids:
            continue
        for table_name in sql_tables.get(sql_id, []):
            tid = table_node_ids.get(table_name)
            if not tid or (method, tid) in seen_edges:
                continue
            seen_edges.add((method, tid))
            edges.append({"from": method, "to": tid, "label": sql_type.get(sql_id, ""), "type": "query"})

    return {"nodes": nodes, "edges": edges}, {"table_nodes": len(table_node_ids), "query_edges": len(seen_edges)}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Zero-LLM Wiki Generator — _workspace/.claude 산출물을 그대로 wiki 페이지로")
    parser.add_argument("--root", required=True, help="Project root directory")
    parser.add_argument("--wiki-dir", required=True, help="Output wiki directory")
    args = parser.parse_args()

    project_root = args.root
    wiki_dir = args.wiki_dir

    print(f"Starting wiki generation (zero-LLM). Root: {project_root}, Wiki: {wiki_dir}")

    project_name = os.path.basename(os.path.normpath(project_root))
    page_entries = []  # (href, label, source_filename) — 정적 index.html 링크 목록

    pair_cfg = parse_pair_config(project_root)
    own_label = (pair_cfg or {}).get("project_type") or "이 저장소"
    partner = _partner_paths(pair_cfg)

    # hub-roots(1:N, 예: 백엔드+웹+모바일+관리자) — paired-roots(1:1)와 별개 경로.
    # pair_config.md가 1:1 flat 형식이면 아래는 빈 리스트라 이후 로직은 기존과 동일하게 동작한다.
    hub_partner_cfgs = parse_pair_config_partners(project_root)
    partners_data = []
    for cfg in hub_partner_cfgs:
        paths = _partner_paths(cfg)
        if not paths:
            continue
        partners_data.append({
            "label": paths["label"],
            "text": read_file(paths["analyzer_report"]),
            "contract_json": load_json(paths["api_contract"]),
            "schema_json": load_json(paths["schema"]),
            "sql_usage_json": load_json(paths["sql_usage"]),
            "io_json": load_json(paths["external_io"]),
        })

    # ---- own-side 원본 로드 ----
    claude_md_text = read_file(os.path.join(project_root, "CLAUDE.md"))
    analyzer_report_text = read_file(os.path.join(project_root, "_workspace", "01_analyzer_report.md"))
    validator_report_text = read_file(os.path.join(project_root, "_workspace", "03_validator_report.md"))
    qa_report_text = read_file(os.path.join(project_root, "_workspace", "04_qa_report.md"))
    dead_code_json = load_json(os.path.join(project_root, "_workspace", "index", "dead_code.json"))
    owasp_json = load_json(os.path.join(project_root, "_workspace", "index", "owasp_top10.json"))
    own_api_contract_json = load_json(os.path.join(project_root, "_workspace", "index", "api_contract.json"))
    own_schema_json = load_json(os.path.join(project_root, "_workspace", "index", "schema.json"))
    own_sql_usage_json = load_json(os.path.join(project_root, "_workspace", "index", "sql_usage.json"))
    own_external_io_json = load_json(os.path.join(project_root, "_workspace", "index", "external_io.json"))
    own_index_meta_json = load_json(os.path.join(project_root, "_workspace", "index", "_meta.json"))
    skills_dir = os.path.join(project_root, ".claude", "skills")
    patterns_dir = os.path.join(project_root, ".claude", "patterns")

    # ---- partner-side 원본 로드 (pair_config.md 있을 때만) ----
    partner_report_text = read_file(partner["analyzer_report"]) if partner else None
    partner_api_contract_json = load_json(partner["api_contract"]) if partner else None
    partner_schema_json = load_json(partner["schema"]) if partner else None
    partner_sql_usage_json = load_json(partner["sql_usage"]) if partner else None
    partner_external_io_json = load_json(partner["external_io"]) if partner else None
    partner_label = partner["label"] if partner else None

    # ---- 페이지 존재 판정 (hub-roots 파트너들도 포함) ----
    api_exists = (wiki_content.has_api_data(own_api_contract_json) or wiki_content.has_api_data(partner_api_contract_json)
                  or any(wiki_content.has_api_data(p["contract_json"]) for p in partners_data))
    db_exists = (wiki_content.has_schema_data(own_schema_json) or wiki_content.has_schema_data(partner_schema_json)
                 or any(wiki_content.has_schema_data(p["schema_json"]) for p in partners_data))
    patterns_exists = os.path.isdir(patterns_dir) and any(
        f.endswith(".md") or f == "pattern_profile.json" for f in os.listdir(patterns_dir)
    )
    external_exists = (wiki_content.has_external_data(own_external_io_json) or wiki_content.has_external_data(partner_external_io_json)
                       or any(wiki_content.has_external_data(p["io_json"]) for p in partners_data))
    issues_exists = bool(validator_report_text or qa_report_text or dead_code_json or owasp_json)

    # 1. Home.md ← CLAUDE.md 그대로
    home_content = wiki_content.build_home(claude_md_text)
    write_file(os.path.join(wiki_dir, "Home.md"), home_content)
    render_and_track(wiki_dir, page_entries, project_name, "Home.md", home_content, "Home (프로젝트 개요)")
    print("Generated Home.md")

    # 2. domain.md ← 01_analyzer_report.md의 "## A." 섹션만 (+ 파트너 병합)
    # architecture.md(전체 리포트)에 도메인/업무 흐름이 묻혀서 wiki로는 찾을 방법이 없다는
    # 지적으로 추가 — 같은 원본에서 도메인 개요만 뽑아 먼저 보이는 별도 페이지로 분리한다.
    domain_content = wiki_content.build_domain_overview(
        analyzer_report_text, partner_report_text, own_label=own_label, partner_label=partner_label,
        partners=partners_data)
    write_file(os.path.join(wiki_dir, "domain.md"), domain_content)
    render_and_track(wiki_dir, page_entries, project_name, "domain.md", domain_content, "Domain (도메인 개요)")
    print("Generated domain.md")

    # 3. architecture.md ← 01_analyzer_report.md (+ 파트너 병합)
    arch_content = wiki_content.build_architecture(
        analyzer_report_text, partner_report_text, own_label=own_label, partner_label=partner_label,
        partners=partners_data)
    write_file(os.path.join(wiki_dir, "architecture.md"), arch_content)
    render_and_track(wiki_dir, page_entries, project_name, "architecture.md", arch_content, "Architecture (아키텍처)")
    print("Generated architecture.md")

    # 4. workflows.md ← .claude/skills/*.md 그대로 연결 (병합 대상 아님)
    workflows_content = wiki_content.build_workflows(skills_dir)
    write_file(os.path.join(wiki_dir, "workflows.md"), workflows_content)
    render_and_track(wiki_dir, page_entries, project_name, "workflows.md", workflows_content, "Workflows (AI 워크플로우 스킬)")
    print("Generated workflows.md")

    # 실제 파일별 어댑터 수준과 자동 변경 가능 여부를 ITO 담당자가 바로 확인한다.
    support_content = wiki_content.build_support_status(own_index_meta_json)
    write_file(os.path.join(wiki_dir, "support-status.md"), support_content)
    render_and_track(wiki_dir, page_entries, project_name, "support-status.md", support_content, "Maintenance Support Status")
    print("Generated support-status.md")

    # 5. patterns.md ← pattern_profile.json 요약 + .claude/patterns/*.md 상세 (병합 대상 아님)
    if patterns_exists:
        patterns_content = wiki_content.build_patterns(patterns_dir)
        write_file(os.path.join(wiki_dir, "patterns.md"), patterns_content)
        render_and_track(wiki_dir, page_entries, project_name, "patterns.md", patterns_content, "Patterns")
        print("Generated patterns.md")

    # 6. api-endpoints.md ← api_contract.json (+ 파트너 병합)
    if api_exists:
        api_content = wiki_content.build_api_endpoints(
            own_api_contract_json, partner_api_contract_json, own_label=own_label, partner_label=partner_label,
            partners=partners_data)
        write_file(os.path.join(wiki_dir, "api-endpoints.md"), api_content)
        render_and_track(wiki_dir, page_entries, project_name, "api-endpoints.md", api_content, "API Endpoints")
        print("Generated api-endpoints.md")

    # 7. database.md ← schema.json + sql_usage.json (+ 파트너 병합)
    if db_exists:
        db_content = wiki_content.build_database(
            own_schema_json, own_sql_usage_json, partner_schema_json, partner_sql_usage_json,
            own_label=own_label, partner_label=partner_label, partners=partners_data)
        write_file(os.path.join(wiki_dir, "database.md"), db_content)
        render_and_track(wiki_dir, page_entries, project_name, "database.md", db_content, "Database")
        print("Generated database.md")

    # 8. external-systems.md ← external_io.json (+ 파트너 병합)
    if external_exists:
        ext_content = wiki_content.build_external_systems(
            own_external_io_json, partner_external_io_json, own_label=own_label, partner_label=partner_label,
            partners=partners_data)
        write_file(os.path.join(wiki_dir, "external-systems.md"), ext_content)
        render_and_track(wiki_dir, page_entries, project_name, "external-systems.md", ext_content, "External Systems")
        print("Generated external-systems.md")

    # 9. issues.md ← 03_validator_report.md + 04_qa_report.md + dead_code.json + owasp_top10.json (병합 대상 아님)
    if issues_exists:
        issues_content = wiki_content.build_issues(validator_report_text, qa_report_text, dead_code_json, owasp_json)
        write_file(os.path.join(wiki_dir, "issues.md"), issues_content)
        render_and_track(wiki_dir, page_entries, project_name, "issues.md", issues_content, "Issues (이슈 & 보안)")
        print("Generated issues.md")

    # 10. vis-network 라이브러리는 call-graph.html에 직접 인라인한다(아래 11번) — 파일로
    # 복사해 상대경로(lib/...)로 참조하면 DB 발행 시(wikihub_db) 이 페이지만 올라가고
    # lib/ 폴더는 안 올라가서 그래프가 빈 화면으로 뜨는 문제가 있었다(2026-08-05 확인).
    # 완전 독립 페이지(file://·DB 열람 모두 동작)로 만들려면 인라인이 유일한 방법이다.
    vis_network_js = read_file(os.path.join(LIB_DIR, "vis-network.min.js")) or ""
    vis_network_css = read_file(os.path.join(LIB_DIR, "vis-network.min.css")) or ""

    # 11. Generate call-graph.html (100% Python program-side binding, 파트너 그래프 병합 포함)
    merge_info = {"merged": False}
    db_merge_info = {"table_nodes": 0, "query_edges": 0}
    call_graph_path = os.path.join(project_root, "_workspace", "index", "call_graph.json")
    cg_template = read_file(os.path.join(LIB_DIR, "call-graph.template.html"))
    nodes_data, edges_data = [], []
    if cg_template:
        raw_graph = load_json(call_graph_path) or {"nodes": [], "edges": []}
        # 노드 상세 패널의 extends/implements/메서드 목록은 call_graph가 아니라 symbols.json에만 있다.
        own_symbols_json = load_json(os.path.join(project_root, "_workspace", "index", "symbols.json"))
        symbol_by_id = {
            s.get("id"): s for s in ((own_symbols_json or {}).get("symbols") or []) if isinstance(s, dict)
        }

        if hub_partner_cfgs:
            raw_graph, merge_info = merge_hub_partner_call_graphs(project_root, raw_graph, hub_partner_cfgs)
        else:
            raw_graph, merge_info = merge_partner_call_graph(project_root, raw_graph)

        raw_graph, db_merge_info = merge_db_tables_into_graph(raw_graph, own_schema_json, own_sql_usage_json)

        detected_types = set()
        nodes_data = []
        edges_data = []
        meta_data = {}

        COLORS = {
            "view":          {"bg": '#7B1A1A', "border": '#E74C3C', "font": '#fff'},
            "vue_view":      {"bg": '#7B1A1A', "border": '#E74C3C', "font": '#fff'},
            "endpoint":      {"bg": '#1a5fa8', "border": '#4A90D9', "font": '#fff'},
            "function":      {"bg": '#6C3483', "border": '#9B59B6', "font": '#fff'},
            "dao":           {"bg": '#154360', "border": '#2E86C1', "font": '#fff'},
            "external":      {"bg": '#8a5900', "border": '#F5A623', "font": '#fff'},
            "sap_interface": {"bg": '#8a5900', "border": '#F5A623', "font": '#fff'},
            "db_table":      {"bg": '#2d6a00', "border": '#7ED321', "font": '#fff'},
            "mssql_table":   {"bg": '#2d6a00', "border": '#7ED321', "font": '#fff'},
            "util":          {"bg": '#0e3030', "border": '#48C9B0', "font": '#fff'},
        }

        in_degree = {}
        out_degree = {}
        for edge_item in raw_graph.get("edges", []):
            to_node = edge_item.get("to")
            from_node = edge_item.get("from")
            in_degree[to_node] = in_degree.get(to_node, 0) + 1
            out_degree[from_node] = out_degree.get(from_node, 0) + 1

        total_nodes = len(raw_graph.get("nodes", []))
        hub_threshold = max(5, int(total_nodes * 0.15))

        # 대형 그래프는 초기 렌더링에 노드 전량을 vis-network에 올려 브라우저가 버벅였다(상한 없음, 실측
        # call_graph.json 36MB). 물리엔진 OFF 기준(300)과 같은 경계에서, in-degree 상위 허브 + 그 직접
        # 이웃만 초기에 표시하고 나머지는 클릭·검색으로 확장한다(전체 데이터는 그대로 보존, 손실 없음).
        # hub_threshold(위, 배지 크기용)와는 별개 — 대형 그래프에서 hub_threshold는 너무 높아져
        # 사실상 0개가 되므로 순위 기반으로 별도 계산한다.
        SMALL_GRAPH_THRESHOLD = 300
        if total_nodes <= SMALL_GRAPH_THRESHOLD:
            initial_ids = None  # 축소 없음 — 현재와 동일하게 전부 표시
        else:
            initial_hub_count = min(60, max(20, total_nodes // 50))
            ranked = sorted(in_degree.items(), key=lambda item: (-item[1], item[0]))  # 동률은 id로 결정론 확보
            hub_ids = {nid for nid, _ in ranked[:initial_hub_count]}
            neighbor_ids = set()
            for edge_item in raw_graph.get("edges", []):
                f, t = edge_item.get("from"), edge_item.get("to")
                if f in hub_ids:
                    neighbor_ids.add(t)
                if t in hub_ids:
                    neighbor_ids.add(f)
            initial_ids = hub_ids | neighbor_ids

        dead_code = {}
        if dead_code_json:
            # dead_code.json 스키마 키는 unused_methods (docs/index-spec.md) — "dead_code"가 아님.
            for item in dead_code_json.get("unused_methods", []):
                dead_code[item.get("id")] = item.get("reason", "")

        seen_node_ids = {}
        for node in raw_graph.get("nodes", []):
            nid = node.get("id")
            # vis.DataSet()이 id 중복을 던지므로(런타임에 전체 그래프가 깨짐), 분석기가
            # 중첩 클래스 등을 같은 id로 잘못 뭉친 경우를 여기서 방어적으로 풀어준다
            # (예: 같은 파일에 동일 이름의 nested class가 여러 번 나오는 경우 —
            # mfs-test3의 backend.app.schemas.schemas.Config 사례, 2026-08-05 확인).
            # 첫 등장은 원래 id 그대로 둬서 기존 엣지 참조가 깨지지 않게 하고, 2번째부터만
            # file:line을 붙여 구분한다.
            if nid in seen_node_ids:
                seen_node_ids[nid] += 1
                nid = f"{nid}#dup{seen_node_ids[nid]}:{node.get('file', '')}:{node.get('line', '')}"
            else:
                seen_node_ids[nid] = 0
            label = node.get("label", node.get("id"))
            raw_type = node.get("type", "function")

            vis_type = "function"
            type_mapping = {
                "view": ["view", "component", "page", "screen", "jsp", "thymeleaf", "vue", "react"],
                # trigger = UI 이벤트·스케줄러·main 같은 진입점 노드 (결정론적 인덱서 산출)
                "endpoint": ["controller", "endpoint", "route", "api", "rest", "trigger"],
                "dao": ["dao", "repository", "mapper", "store", "jpa"],
                "external": ["external", "client", "feign", "soap", "sap", "mq", "kafka", "redis"],
                "db_table": ["db", "table", "mssql", "oracle", "mysql", "postgres", "sqlite"],
                "util": ["util", "helper", "common", "config", "constant"]
            }

            if raw_type in ["vue_view", "sap_interface", "mssql_table"]:
                vis_type = raw_type
            else:
                for k, v in type_mapping.items():
                    if raw_type in v:
                        vis_type = k
                        break
                else:
                    # raw_type이 "method"/"external-method"처럼 레이어 정보 없는 범용값이면
                    # 패키지·클래스명(id/file)에서 레이어를 추론한다 (Controller/Service/Dao 관행 기반).
                    haystack = f"{nid or ''} {node.get('file', '')}".lower()
                    if raw_type == "external-method" or "external" in haystack:
                        vis_type = "external"
                    elif ".web." in haystack or "controller" in haystack:
                        vis_type = "endpoint"
                    elif ".dao." in haystack or "dao" in haystack or "mapper" in haystack:
                        vis_type = "dao"
                    elif ".service." in haystack or "service" in haystack:
                        vis_type = "function"

            detected_types.add(vis_type)

            node_degree = in_degree.get(nid, 0)
            extra = {}
            if node_degree >= hub_threshold:
                extra["size"] = 28
                extra["borderWidth"] = 3

            if nid in dead_code:
                extra["opacity"] = 0.4

            extra["initial"] = initial_ids is None or nid in initial_ids

            nodes_data.append({
                "id": nid,
                "label": label,
                "type": vis_type,
                "extra": extra
            })

            sym = symbol_by_id.get(node.get("id")) or {}
            meta_data[nid] = {
                "type": vis_type,
                "rawType": raw_type,
                "file": node.get("file", ""),
                "line": node.get("line", ""),
                "signature": node.get("signature", ""),
                "visibility": node.get("visibility", ""),
                "static": bool(node.get("static", False)),
                "annotations": node.get("annotations", []),
                "api": node.get("api", ""),
                "note": node.get("note", ""),
                "inDegree": node_degree,
                "outDegree": out_degree.get(nid, 0),
                "hub": node_degree >= hub_threshold,
                "dead": nid in dead_code,
                "deadReason": dead_code.get(nid, ""),
                "extends": sym.get("extends", ""),
                "implements": sym.get("implements", []),
                "methods": [m.get("name") for m in (sym.get("methods") or []) if isinstance(m, dict)]
            }

        for edge_item in raw_graph.get("edges", []):
            edges_data.append({
                "from": edge_item.get("from"),
                "to": edge_item.get("to"),
                "label": edge_item.get("label", ""),
                "type": edge_item.get("type", "call"),
                # reflect는 AI 보강 추정 엣지라 확정 호출과 구분해 점선(+주황, 템플릿)으로 그린다.
                "dashed": edge_item.get("type") in ("depends", "reflect"),
                "note": edge_item.get("note", "")
            })

        btn_labels = {
            "view": "🖥 뷰", "vue_view": "🖥 Vue 뷰", "endpoint": "⚡ API 엔드포인트",
            "function": "🔧 서비스/함수", "dao": "🗃 DAO/저장소", "external": "🔶 외부 시스템",
            "sap_interface": "🔶 SAP SOAP", "db_table": "🗄 DB 테이블", "mssql_table": "🗄 MSSQL 테이블",
            "util": "⚙ 유틸"
        }
        # set 순회 순서는 실행마다 달라진다 — 정렬하지 않으면 내용이 같아도 파일이 매번
        # 달라져서 DB 발행(publish-wiki) 때마다 헛된 버전이 쌓인다.
        filter_buttons_html = ""
        for t in sorted(detected_types):
            if t in btn_labels:
                filter_buttons_html += f'<button class="filter-btn active" data-type="{t}">{btn_labels[t]}</button>\n    '

        legend_html = ""
        for t in sorted(detected_types):
            if t in COLORS:
                c = COLORS[t]
                legend_html += f'<div class="legend-item"><div class="legend-dot" style="background:{c["border"]}"></div>{btn_labels.get(t, t)}</div>\n        '
        legend_html += f'<div class="legend-note">◎ 허브(in-degree ≥ {hub_threshold})</div>\n        '
        legend_html += '<div class="legend-note" style="opacity:.55">☠ 데드 코드 후보</div>\n        '
        if any(e["type"] == "reflect" for e in edges_data):
            legend_html += '<div class="legend-note" style="color:#F5A623">┄┄ 리플렉션 엣지(신뢰도 낮음, 검증 권장)</div>\n        '
        if initial_ids is not None:
            initial_count = sum(1 for n in nodes_data if n["extra"].get("initial"))
            legend_html += (
                f'<div class="legend-note">🔍 대형 그래프 — 허브+이웃 {initial_count}개만 기본 표시, '
                f'나머지 {total_nodes - initial_count}개는 검색·클릭으로 확장</div>\n        '
            )

        hub_count = sum(1 for n in nodes_data if n["extra"].get("size") == 28)
        dead_count = sum(1 for n in nodes_data if n["id"] in dead_code)
        stat_summary_html = (
            f'<div class="stat-hero"><div class="stat-num">{len(nodes_data)}</div>'
            f'<div class="stat-caption">노드 · {len(edges_data)} 엣지</div>'
            f'<div class="stat-sub">허브 {hub_count} · 데드코드 후보 {dead_count}</div></div>'
        )

        # id/label/note는 analyzer가 자유 서술한 텍스트라 따옴표를 포함할 수 있다 —
        # json.dumps로 이스케이핑해야 생성된 JS가 깨지지 않는다.
        js_nodes = []
        for n in nodes_data:
            js_nodes.append(
                f"mkNode({json.dumps(n['id'])}, {json.dumps(n['label'])}, {json.dumps(n['type'])}, {json.dumps(n['extra'])})"
            )

        js_edges = []
        for e in edges_data:
            js_edges.append(
                f"edge({json.dumps(e['from'])}, {json.dumps(e['to'])}, {json.dumps(e['label'])}, "
                f"{str(e['dashed']).lower()}, {json.dumps(e['type'])}, {json.dumps(e.get('note', ''))})"
            )

        js_nodes_array_str = "[\n      " + ",\n      ".join(js_nodes) + "\n    ]"
        js_edges_array_str = "[\n      " + ",\n      ".join(js_edges) + "\n    ]"

        # 노드/엣지 수가 많으면 기본 물리 시뮬레이션·동적 엣지 스무딩을 꺼서 초기 로딩을 가볍게 한다
        # (사용자가 필요하면 화면의 "물리엔진 ON" 토글로 직접 켤 수 있음 — 상세 근거는
        # call-graph.template.html 헤더 주석 참조).
        physics_default = len(nodes_data) <= 300
        edge_smooth_dynamic = len(edges_data) <= 500

        cg_html = cg_template\
            .replace("{{VIS_NETWORK_JS}}", vis_network_js)\
            .replace("{{VIS_NETWORK_CSS}}", vis_network_css)\
            .replace("{{PROJECT_NAME}}", project_name)\
            .replace("{{STACK_DESCRIPTION}}", "정적 분석 결과")\
            .replace("{{FILTER_BUTTONS}}", filter_buttons_html)\
            .replace("{{STAT_SUMMARY}}", stat_summary_html)\
            .replace("{{LEGEND_ITEMS}}", legend_html)\
            .replace("{{COLORS}}", json.dumps(COLORS, indent=2))\
            .replace("{{NODES_DATA}}", js_nodes_array_str)\
            .replace("{{EDGES_DATA}}", js_edges_array_str)\
            .replace("{{META}}", json.dumps(meta_data, indent=2))\
            .replace("{{PHYSICS_DEFAULT}}", "true" if physics_default else "false")\
            .replace("{{EDGE_SMOOTH_DYNAMIC}}", "true" if edge_smooth_dynamic else "false")

        write_file(os.path.join(wiki_dir, "call-graph.html"), cg_html)
        print("Generated call-graph.html successfully.")
        page_entries.append(("call-graph.html", "Call Graph (호출 그래프)", "call-graph.html"))

    # 12. index.html (Docsify) + _sidebar.md + _navbar.md + serve.bat
    # Docsify는 file:// 미지원 — serve.bat으로 로컬 서버 실행 필요.
    has_call_graph_file = os.path.exists(os.path.join(wiki_dir, "call-graph.html"))
    present_slugs = {
        os.path.splitext(f)[0]
        for f in os.listdir(wiki_dir)
        if f.endswith(".md") and not f.startswith("_")
    }

    write_file(os.path.join(wiki_dir, "index.html"), wiki_render.render_index(title=f"{project_name} Wiki"))
    print("Generated index.html")

    write_file(os.path.join(wiki_dir, "offline.html"), wiki_render.render_static_index(project_name, page_entries))
    print("Generated offline.html (file:// 진입점)")

    # 파트너(frontend류) 데이터가 실제로 병합된 페이지만 사이드바에 앵커 서브항목으로 노출
    frontend_merged_slugs = []
    if partner:
        if partner_report_text:
            frontend_merged_slugs.append("architecture")
            frontend_merged_slugs.append("domain")
        if wiki_content.has_api_data(partner_api_contract_json):
            frontend_merged_slugs.append("api-endpoints")
        if wiki_content.has_external_data(partner_external_io_json):
            frontend_merged_slugs.append("external-systems")
    if any(p.get("text") for p in partners_data):
        frontend_merged_slugs.append("architecture")
        frontend_merged_slugs.append("domain")
    if any(wiki_content.has_api_data(p.get("contract_json")) for p in partners_data):
        frontend_merged_slugs.append("api-endpoints")
    if any(wiki_content.has_external_data(p.get("io_json")) for p in partners_data):
        frontend_merged_slugs.append("external-systems")
    frontend_merged_slugs = sorted(set(frontend_merged_slugs))

    hub_partner_label = ", ".join(p["label"] for p in partners_data) if partners_data else None

    write_file(os.path.join(wiki_dir, "_sidebar.md"),
               docsify_convert.build_sidebar(project_name, present_slugs, has_call_graph_file,
                                              frontend_merged_slugs=frontend_merged_slugs,
                                              partner_label=partner_label or hub_partner_label))
    print("Generated _sidebar.md")

    write_file(os.path.join(wiki_dir, "_navbar.md"),
               docsify_convert.build_navbar(present_slugs, has_call_graph_file))
    print("Generated _navbar.md")

    write_file(os.path.join(wiki_dir, "serve.bat"), docsify_convert.serve_bat_content())
    print("Generated serve.bat")

    # 13. Write WIKI BUILD REPORT
    build_report_path = os.path.join(project_root, "_workspace", "07_wiki_build.md")
    report_content = f"""=== WIKI BUILD REPORT (zero-LLM) ===

생성 시각: {datetime.now().strftime("%Y-%m-%d %H:%M")}
출력 경로: wiki/

생성된 파일:
- wiki/Home.md              ✅ (원본: CLAUDE.md)
- wiki/domain.md             ✅ (원본: _workspace/01_analyzer_report.md의 "## A." 섹션만)
- wiki/architecture.md      ✅ (원본: _workspace/01_analyzer_report.md 전체)
- wiki/workflows.md         ✅ (원본: .claude/skills/*.md)
- wiki/call-graph.html      {"✅" if nodes_data else "⏭"} (노드: {len(nodes_data)}, 엣지: {len(edges_data)})
- wiki/index.html           ✅ (Docsify 4 — serve.bat 실행 후 http://localhost:3501)
- wiki/_sidebar.md          ✅ (Docsify 사이드바 네비게이션)
- wiki/_navbar.md           ✅ (Docsify 상단 네비바)
- wiki/serve.bat            ✅ (python -m http.server 3501)
- wiki/_html/*.html         ✅ ({sum(1 for href, _, _ in page_entries if href.startswith("_html/"))}개 페이지의 브라우저 열람용 렌더 사본)
- wiki/offline.html         ✅ (서버 없이 file://로 바로 여는 진입점 — call-graph.html과 동일한 방식)
- wiki/patterns.md          {"✅ (원본: .claude/patterns/*.md)" if patterns_exists else "⏭ (미대상)"}
- wiki/api-endpoints.md     {"✅ (원본: _workspace/index/api_contract.json)" if api_exists else "⏭ (미대상)"}
- wiki/database.md          {"✅ (원본: _workspace/index/schema.json + sql_usage.json)" if db_exists else "⏭ (미대상)"}
- wiki/external-systems.md  {"✅ (원본: _workspace/index/external_io.json)" if external_exists else "⏭ (미대상)"}
- wiki/issues.md            {"✅ (원본: 03_validator_report.md + 04_qa_report.md + dead_code.json + owasp_top10.json)" if issues_exists else "⏭ (미대상)"}
"""
    if merge_info.get("merged") and "partners" in merge_info:
        report_content += "\n크로스 리포 병합 (call-graph.html, hub-roots 1:N):\n"
        for pr in merge_info["partners"]:
            if pr.get("skipped"):
                report_content += f"  ⏭ {pr['label']}: 스킵 — {pr['skipped']}\n"
            else:
                report_content += (
                    f"  ✅ {pr['label']}: 노드 {pr['nodes']}개 병합, 추론된 크로스 엣지 {pr['cross_edges']}개 "
                    f"(미매칭 후보 {pr['unmatched']}개)\n"
                )
    elif merge_info.get("merged"):
        report_content += (
            f"\n크로스 리포 병합 (call-graph.html): ✅ 파트너({merge_info['partner_type']}) 노드 {merge_info['partner_nodes']}개 병합, "
            f"추론된 크로스 엣지 {merge_info['cross_edges']}개 (미매칭 후보 {merge_info['unmatched']}개)\n"
        )
    elif "reason" in merge_info:
        report_content += f"\n크로스 리포 병합 (call-graph.html): ⏭ 스킵 — {merge_info['reason']}\n"

    if db_merge_info.get("table_nodes"):
        report_content += (
            f"\nDB 테이블 병합 (call-graph.html): ✅ schema.json 기반 db_table 노드 {db_merge_info['table_nodes']}개, "
            f"sql_usage.json 기반 DAO→테이블 쿼리 엣지 {db_merge_info['query_edges']}개 합성\n"
        )
    else:
        report_content += "\nDB 테이블 병합 (call-graph.html): ⏭ 스킵 — schema.json에 테이블 없음/파일 없음\n"

    if partner:
        merged_pages = []
        if partner_report_text:
            merged_pages.append("architecture.md")
        if wiki_content.has_api_data(partner_api_contract_json):
            merged_pages.append("api-endpoints.md")
        if wiki_content.has_schema_data(partner_schema_json):
            merged_pages.append("database.md")
        if wiki_content.has_external_data(partner_external_io_json):
            merged_pages.append("external-systems.md")
        if merged_pages:
            report_content += f"크로스 리포 병합 (markdown 페이지): ✅ 파트너({partner_label}) 데이터가 {', '.join(merged_pages)}에 병합됨\n"
        else:
            report_content += f"크로스 리포 병합 (markdown 페이지): ⏭ pair_config.md는 있으나 파트너 산출물({partner['analyzer_report']} 등)을 찾지 못함\n"

    for p in partners_data:
        merged_pages = []
        if p.get("text"):
            merged_pages.append("architecture.md")
        if wiki_content.has_api_data(p.get("contract_json")):
            merged_pages.append("api-endpoints.md")
        if wiki_content.has_schema_data(p.get("schema_json")):
            merged_pages.append("database.md")
        if wiki_content.has_external_data(p.get("io_json")):
            merged_pages.append("external-systems.md")
        if merged_pages:
            report_content += f"크로스 리포 병합 (markdown 페이지, hub-roots): ✅ 파트너({p['label']}) 데이터가 {', '.join(merged_pages)}에 병합됨\n"
        else:
            report_content += f"크로스 리포 병합 (markdown 페이지, hub-roots): ⏭ 파트너({p['label']}) 산출물을 찾지 못함\n"

    storage_line = (
        "저장 위치: 폴더 (wiki/)\n"
        "중앙 허브(여러 시스템 통합, 버전 관리)에도 두려면 별도 프로젝트 wiki-hub로 발행 → publish-wiki 스킬 참고\n"
    )
    report_content += f"\n{storage_line}"

    report_content += "\n=== END ===\n"
    write_file(build_report_path, report_content)
    print("Generated 07_wiki_build.md report.")

if __name__ == "__main__":
    main()
