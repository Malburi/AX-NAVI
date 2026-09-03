# harness 산출물을 wiki 폴더(Docsify·call-graph.html·정적 HTML)로 변환하는 zero-LLM 오케스트레이터
import os
import json
import re
import sys
import math      # 추가 — 사전 배치 레이아웃 계산용
import random    # 추가 — 결정론적(고정 시드) 레이아웃 배치용
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


def classify_trigger(nid):
    """raw type이 trigger인 노드를 id 프래그먼트 모양으로 세분한다.

    결정론적 인덱서는 "진입점 같은 것" 전부를 type="trigger" 하나로 낸다 — jsp의 onclick
    배선, struts <action> 매핑, forward 대상, main/스케줄러 진입점이 모두 섞여 있다.
    wiki_generator는 지금까지 이걸 통째로 visual "endpoint"(파란색 "⚡ API 엔드포인트")로
    칠해왔는데, 실측(xu43-server) 2,209개 trigger 중 실제 struts action은 346개뿐이고
    1,839개가 jsp의 onclick 핸들러였다 — 즉 화면에서 "API 엔드포인트"라고 표시되던 파란
    노드의 83%가 엔드포인트가 아니었다. 이것이 "apiendpoint가 없다"는 사용자 지적의 직접
    원인이다.

    HPS(WinForms)의 trigger 1,094개는 id에 '#' 프래그먼트가 없어 기본값 ui_event로
    떨어진다 — 디자이너의 컨트롤 이벤트 배선이므로 정확한 분류다.
    """
    if "#action." in nid:
        return "endpoint"       # struts <action> 매핑 = 진짜 HTTP 진입점
    if "#process-entry" in nid:
        return "entrypoint"     # main()/스케줄러/배치
    if "#forward." in nid:
        return "view"           # struts forward 대상 = 화면 전이
    return "ui_event"           # jsp onclick / WinForms 이벤트 배선


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


_ENDPOINT_PATH_MAX = 34


def _endpoint_label(endpoint):
    """엔드포인트 노드에 붙일 짧은 라벨.

    method가 ANY/빈값이면 붙이지 않는다 — struts·aspnet-webforms는 method를 전부 "ANY"로
    내므로(실측 server 421/421, HPS 3/3) "ANY /back/..."은 화면 폭만 먹고 정보가 0이다.

    긴 경로는 앞을 잘라낸다. aspnet-webforms/classic-asp는 path가 곧 파일 경로라
    "/Service Project/HPS.hpsportal.Service/DownloadFile.aspx"처럼 50자를 넘는 경우가 있고,
    이 라벨은 short_label()을 우회하므로(node["label"]이 이미 채워지면 그쪽이 호출되지
    않는다) 여기서 직접 줄여야 한다."""
    method = (endpoint.get("method") or "").upper()
    path = endpoint.get("path") or endpoint.get("path_pattern") or endpoint.get("id") or "?"
    if len(path) > _ENDPOINT_PATH_MAX:
        segs = [s for s in path.split("/") if s]
        if len(segs) > 2:
            path = ".../" + "/".join(segs[-2:])
    return path if method in ("", "ANY", "*") else f"{method} {path}"


def _endpoint_note(endpoint):
    """AI가 쓴 description(실측 421/421 채워짐) + 인증/권한/프레임워크를 한 덩어리로.

    call_graph.json의 노드 note는 결정론 인덱서가 채우지 않는다 — 실측 #action. 트리거
    346개 중 note 보유 0개라 덮어쓸 위험이 없다. 그래도 기존 note가 있으면 호출부에서
    뒤에 이어붙인다(방어적)."""
    parts = []
    desc = (endpoint.get("description") or "").strip()
    if desc:
        parts.append(desc)
    flags = []
    if endpoint.get("auth_required"):
        flags.append("인증 필요")
    roles = endpoint.get("roles") or []
    if roles:
        flags.append("권한: " + ", ".join(str(r) for r in roles))
    if endpoint.get("framework"):
        flags.append(str(endpoint["framework"]))
    if flags:
        parts.append("(" + " · ".join(flags) + ")")
    return " ".join(parts)


def resolve_endpoint_node(endpoint, ids, by_file, by_file_line, nodes):
    """엔드포인트 하나를 기존 call_graph 노드에 붙인다. 실측 히트율 순서대로 내려가는
    결정론적 사다리 — LLM 미개입. 반환: (node_id 또는 None, 사다리 단계 이름).

    L1이 87%를 먹는 이유: 결정론 인덱서는 struts <action> 매핑을
    "trigger:{xml경로}#action.{서비스빈}" id로 이미 노드화해두고 그 노드에서 서비스
    클래스로 가는 엣지까지 만들어놨다. api_contract.json의 file + dispatch_bean으로 그 id를
    문자열 조립하면 정확히 맞는다(실측 368/421). 즉 진짜 API 엔드포인트는 그래프에 이미
    있었고, 아무도 읽을 수 없는 id로 있었을 뿐이다.

    (file,line) 단계(L4)는 L1 뒤에 두면 실측 추가 히트가 0이다 — L1 집합에 완전히 포함된다.
    그래도 struts가 아닌 스택(데코레이터/애노테이션 기반)에서는 유일한 단서라 남긴다.
    """
    f = (endpoint.get("file") or "").replace("\\", "/")
    bean = endpoint.get("dispatch_bean")
    if f and bean:
        cand = f"trigger:{f}#action.{bean}"
        if cand in ids:
            return cand, "L1:trigger#action"
    if f and f"view:{f}" in ids:            # aspnet-webforms/jsp 계열 (실측 HPS 3/3, client 1/2)
        return f"view:{f}", "L2:view:file"
    handler = endpoint.get("handler")
    if handler and handler in ids:
        return handler, "L3:handler"
    same_line = by_file_line.get((f, endpoint.get("line"))) or []
    if len(same_line) == 1:
        return same_line[0], "L4:file+line"
    same_file = by_file.get(f) or []
    if len(same_file) == 1:
        return same_file[0], "L5:file-unique"
    if same_file:
        # 같은 파일에 노드가 여러 개 — 기존 헬퍼를 그대로 쓴다(데코레이터 바로 아래 함수 우선).
        picked = (_node_following(nodes, f, endpoint.get("line"))
                  or _node_enclosing(nodes, f, endpoint.get("line")))
        if picked:
            return picked, "L6:file-multi"
    return None, "L7:orphan"


def merge_api_endpoints_into_graph(raw_graph, api_contract_json):
    """api_contract.json의 endpoints를 call_graph에 반영한다.

    **새 노드를 만드는 게 아니라 기존 노드를 제자리에서 보강하는 것이 기본**이다 —
    엔드포인트의 87%(struts)는 이미 trigger:...#action.* 노드로 그래프에 있고 서비스
    클래스로 가는 엣지까지 갖고 있어서, 별도 api: 노드를 만들면 "api → trigger → service"
    라는 의미 없는 중복 홉이 생긴다. 실측(xu43-server): 383개가 제자리 보강(352개 노드),
    38개만 신규 노드(전체 노드의 0.36%).

    보강 내용: label(짧은 경로), note(AI가 쓴 한글 description + 인증/권한),
    api(method+path), endpoint_ids(상세 패널이 data_flow 흐름을 조회할 키).
    call_graph.json 원본 파일은 건드리지 않는다(merge_db_tables_into_graph와 동일 원칙).

    반환: (병합된 그래프, api_merge_info dict — 07_wiki_build.md 보고용)
    """
    endpoints = (api_contract_json or {}).get("endpoints") or []
    info = {"endpoints": len(endpoints), "enriched": 0, "enriched_nodes": 0,
            "new_nodes": 0, "new_edges": 0, "ladder": {}}
    if not endpoints:
        return raw_graph, info

    nodes = list(raw_graph.get("nodes") or [])
    edges = list(raw_graph.get("edges") or [])
    node_by_id, by_file, by_file_line = {}, {}, {}
    for n in nodes:
        nid = n.get("id")
        if nid is not None and nid not in node_by_id:
            node_by_id[nid] = n
        f = (n.get("file") or "").replace("\\", "/")
        by_file.setdefault(f, []).append(nid)
        by_file_line.setdefault((f, n.get("line")), []).append(nid)
    ids = set(node_by_id)

    ladder = {}
    # endpoint id로 정렬 — 같은 노드에 여러 엔드포인트가 붙을 때(실측 17개 노드, 최대 7개)
    # 어느 것이 label이 되는지가 실행마다 달라지면 publish-wiki가 헛된 버전을 쌓는다.
    for ep in sorted(endpoints, key=lambda e: str(e.get("id") or "")):
        target, rung = resolve_endpoint_node(ep, ids, by_file, by_file_line, nodes)
        ladder[rung] = ladder.get(rung, 0) + 1

        if target is None or rung in ("L6:file-multi", "L7:orphan"):
            # 신규 노드. 접두사 "api:"는 기존 db_table:/view:/trigger:/partner_ 와 겹치지
            # 않는다(실측 3개 프로젝트 call_graph.json 어디에도 "api:"로 시작하는 id 없음).
            aid = f"api:{ep.get('id')}"
            if aid in ids:
                continue
            nodes.append({
                "id": aid, "label": _endpoint_label(ep), "type": "api_endpoint",
                "note": _endpoint_note(ep),
                "file": ep.get("file", ""), "line": ep.get("line", ""),
                "api": _endpoint_label(ep),
                "method": ep.get("method", ""), "path": ep.get("path", ""),
                "endpoint_ids": [ep.get("id")],
                "endpoint_promoted": True,
            })
            ids.add(aid)
            info["new_nodes"] += 1
            if target is not None:
                edges.append({"from": aid, "to": target, "label": "handles",
                              "type": "serves", "note": rung})
                info["new_edges"] += 1
            continue

        node = node_by_id[target]
        eids = node.setdefault("endpoint_ids", [])
        if ep.get("id") not in eids:
            eids.append(ep.get("id"))
        if len(eids) == 1:
            node["label"] = _endpoint_label(ep)
            node["api"] = _endpoint_label(ep)
            node["method"] = ep.get("method", "")
            node["path"] = ep.get("path", "")
            note = _endpoint_note(ep)
            existing = (node.get("note") or "").strip()
            node["note"] = f"{note}\n{existing}".strip() if existing else note
        else:
            # 하나의 struts action 노드에 여러 엔드포인트가 매핑되는 경우. 첫 라벨을 유지하고
            # 개수만 덧붙인다 — 라벨을 계속 갈아치우면 어느 게 남는지가 순회 순서에 의존한다.
            base = str(node.get("label") or "").split("  (+")[0]
            node["label"] = f"{base}  (+{len(eids) - 1})"
            node["note"] = (node.get("note") or "") + f"\n— {_endpoint_label(ep)}: {_endpoint_note(ep)}"
        node["endpoint_promoted"] = True
        info["enriched"] += 1

    info["enriched_nodes"] = sum(1 for n in nodes if n.get("endpoint_promoted") and not str(n.get("id", "")).startswith("api:"))
    info["ladder"] = dict(sorted(ladder.items()))
    print(f"API endpoint merge: endpoints {len(endpoints)}, 제자리 보강 {info['enriched']}건"
          f"({info['enriched_nodes']}개 노드), 신규 노드 {info['new_nodes']}, "
          f"신규 엣지 {info['new_edges']}, 사다리 {info['ladder']}")
    return {"nodes": nodes, "edges": edges}, info


def _short_method(fqn):
    """흐름 목록 표시용 축약 — 상세 패널이 좁아 FQN 전체는 어차피 잘린다. 페이로드 크기도
    이 축약으로 절반 이하가 된다(실측 906KB → 412KB)."""
    parts = str(fqn).split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else str(fqn)


FLOW_METHOD_CAP = 6
FLOW_TABLE_CAP = 10


def build_endpoint_flows(data_flow_json):
    """data_flow.json의 chains를 endpoint_id -> 상세 패널용 요약으로 만든다.

    이 파일은 지금까지 플러그인의 어떤 파이썬 파일도 열지 않았다(`data_flow` 문자열이
    lib/*.py 전체에 0건). 실측 330 chains 전부 note를 갖고 있고, endpoint_id 330/330이 실제
    api_contract 엔드포인트 id이며 method_chain 5,937/5,937이 실제 call_graph 노드 id다 —
    하네스가 쓴 설명 851개 중 330개가 여기 있는데 그래프에는 하나도 안 나왔다.

    **엣지나 노드를 만들지 않는다.** chains는 이미 그래프에 존재하는 경로의 투영이다 —
    method_chain의 각 홉은 call 엣지로, sql_ids→tables_*는 merge_db_tables_into_graph의
    query 엣지로 이미 그려져 있다. 그런데도 endpoint→method 흐름 엣지를 만들면 실측
    5,937개(전체 엣지 10,311개의 +58%)가 추가되면서 (a) 각 method의 in_degree가 올라가
    허브 임계값(in_degree 95퍼센타일)이 이동해 "어느 노드가 허브인가"가 조용히 바뀌고,
    (b) 엔드포인트마다 out-degree 18인 별 모양 뭉치가 330개 생긴다. chains가 실제로 더해주는
    것은 "순서"와 "요약 note"뿐이고, 그건 그래프 구조가 아니라 상세 패널의 관심사다.

    반환: {endpoint_id: {note, methods[], nm, sqls[], nq, tr[], tw[], conf}}
    """
    chains = (data_flow_json or {}).get("chains") or []
    flows = {}
    for c in sorted(chains, key=lambda x: str(x.get("endpoint_id") or "")):
        eid = c.get("endpoint_id")
        if not eid:
            continue
        mc = [m for m in (c.get("method_chain") or []) if m]
        sq = [s for s in (c.get("sql_ids") or []) if s]
        flows[eid] = {
            "note": c.get("note") or "",
            "methods": [_short_method(m) for m in mc[:FLOW_METHOD_CAP]],
            "nm": len(mc),
            "sqls": sq[:FLOW_METHOD_CAP],
            "nq": len(sq),
            "tr": sorted(set(c.get("tables_read") or []))[:FLOW_TABLE_CAP],
            "tw": sorted(set(c.get("tables_written") or []))[:FLOW_TABLE_CAP],
            "conf": c.get("confidence") or "",
        }
    if chains:
        print(f"Data flow: chains {len(chains)}, 엔드포인트 흐름 {len(flows)}건 (노드·엣지 추가 없음)")
    return flows


# 파일 경로 마지막(파일 바로 위) 세그먼트로 흔히 쓰이는 아키텍처 계층 이름 — 그대로 모듈로
# 쓰면 서로 무관한 기능들이 전부 이 이름 하나로 뭉쳐버린다(예: eduport/announce/service와
# eduport/board/service가 둘 다 "service"가 됨). derive_module()의 2순위 규칙에서 걷어낸다.
_MODULE_LAYER_NAMES = {
    "service", "services", "dao", "daos", "repository", "repositories",
    "mapper", "mappers", "action", "actions", "controller", "controllers",
    "handler", "handlers", "resource", "resources", "router", "routers",
    "view", "views", "serializer", "serializers", "schema", "schemas",
    "validator", "validators", "impl", "imp", "util", "utils", "helper",
    "helpers", "model", "models", "dto", "dtos", "entity", "entities",
    "vo", "bean", "beans", "form", "forms", "exception", "exceptions",
    "filter", "filters", "config", "configuration", "constant", "constants",
    "middleware", "middlewares",
}
# 빌드/소스루트 관례로 어느 프로젝트에나 반복되는, 그 자체로는 모듈 의미가 없는 폴더.
_MODULE_CONTAINER_PREFIXES = {
    "src", "main", "java", "kotlin", "test", "tests", "webapp", "web-inf",
    "classes", "webcontent", "bin", "obj", "target", "build", "app", "source",
    "node_modules",
}
# 코드 생성기가 만든 산출물임을 강하게 시사하는 토큰. 실측(xu43-server)에서 SOAP/WSDL
# 클라이언트 스텁(org/tempuri/*.java, 128개 파일)이 rollup_modules()로도 안 접히는
# 큰 덩어리로 남아 업무 모듈처럼 보이는 문제를 확인해 추가했다. 일부러 짧고 흔한 토큰
# ("gen" 등)은 뺐다 — "General"/"Generator" 같은 정상 업무 클래스명까지 걸리는 오탐을
# 막기 위해 반드시 "단어 전체" 매치만 인정한다(아래 토큰화 참고). 같은 이유로 HPS의
# ".Designer.cs"(WinForms 디자이너 partial class, 실제 UI 이벤트 배선 정보를 담고 있어
# 업무적으로 의미 있음)는 일부러 포함하지 않았다 — vscode의 "Designer"는 여기서 말하는
# "그 자체로 순수 보일러플레이트라 모듈로 묶일 가치가 없는 코드"와 다르다.
_GENERATED_CODE_TOKENS = {
    "tempuri", "wsimport", "generated", "autogenerated", "codegen", "stub",
    "stubs", "proxy", "proxies", "wsdl",
}


def _looks_generated(node):
    """annotations에 @Generated류 표시가 있거나, 파일 경로 토큰 중 하나가
    _GENERATED_CODE_TOKENS와 완전히 일치하면 생성 코드로 본다. 부분 문자열 매치가
    아니라 경로를 영숫자 기준으로 토큰화한 뒤 토큰 단위로 비교한다 — "GeneralService"가
    "gen"이나 "general"에 오탐되지 않게 하기 위함."""
    annotations = node.get("annotations") or []
    ann_text = " ".join(str(a) for a in annotations).lower()
    if "generated" in ann_text:
        return True
    path = (node.get("file") or "").lower()
    tokens = set(re.split(r"[^a-z0-9]+", path))
    return bool(tokens & _GENERATED_CODE_TOKENS)


# 프로젝트에 통째로 갖다 놓은 서드파티 JS/UI 라이브러리를 가리키는 토큰. 실측(xu43-client)에서
# amCharts(유료 차트 라이브러리)가 폴더 두 곳에 중복 벤더링되어 각각 1,048개 파일짜리 모듈로
# 잡혔다 — 코드 생성기 산출물은 아니라서(코드젠이 아니라 그냥 배포본을 복사해 넣은 것)
# _looks_generated로는 안 걸린다. 알려진 라이브러리 이름을 나열하는 방식이라 목록에 없는
# 라이브러리는 여전히 못 잡는다는 한계가 있다 — 그런 사례가 또 나오면 그때 추가한다.
_VENDOR_LIBRARY_TOKENS = {
    "vendor", "vendors", "thirdparty", "3rdparty",
    "ckeditor", "tinymce", "summernote", "wysiwyg",
    "amcharts", "highcharts", "chartjs", "echarts",
    "jquery", "bootstrap", "fontawesome", "swiper", "select2", "datatables",
    "moment", "lodash", "underscore",
    "sweetalert", "sweetalert2", "popper", "slick", "owlcarousel",
    "fancybox", "lightbox", "flatpickr", "daterangepicker",
}


def _looks_vendor_library(node):
    """경로 토큰 중 하나가 _VENDOR_LIBRARY_TOKENS와 완전히 일치하면 서드파티 라이브러리로
    본다. _looks_generated와 같은 토큰화 방식(부분 문자열 아님)을 쓴다."""
    path = (node.get("file") or "").lower()
    tokens = set(re.split(r"[^a-z0-9]+", path))
    return bool(tokens & _VENDOR_LIBRARY_TOKENS)


_LABEL_MAX = 40


def _clip(s):
    """라벨 한 줄을 _LABEL_MAX로 자른다. vis-network 노드 상자의 폭은 라벨의 "가장 긴 줄"이
    결정하므로, 여러 줄 라벨(trigger의 '파일명\\n#이벤트')은 총 길이가 아니라 줄마다 잘라야
    한다 — 실측 HPS에서 파일명 38자 + 이벤트명 44자로 한 줄이 44자까지 갔다."""
    s = str(s)
    return s if len(s) <= _LABEL_MAX else s[: _LABEL_MAX - 1] + "…"


def short_label(nid, vis_type, file_path="", method="", path=""):
    """그래프 캔버스에 그릴 짧은 라벨.

    지금까지 label = node.get("label", node.get("id")) 였고 결정론적 인덱서가 만드는 노드에는
    label 키가 아예 없어서(실측 3개 프로젝트 전부 0%) 60자짜리 FQN이 그대로 그려졌다 —
    "eduport.lms.back.main.code.service.TranKoocService.doSublist" 같은 문자열이 상자로
    렌더되니 fit 줌에서 서로 겹쳐 읽을 수 없었다.

    런타임(mkNode)이 아니라 생성 시점에 계산하는 이유:
      1) file/vis_type/method/path 컨텍스트가 파이썬 쪽에만 있다,
      2) 순수 함수라 실행마다 같은 바이트가 나온다(publish-wiki 체크섬 버저닝 제약 충족),
      3) 25,216개 노드의 라벨 문자열이 짧아져 생성 HTML이 오히려 작아진다.

    전체 id는 노드 id로 그대로 보존되므로 정보 손실이 없다 — 상세 패널과 검색이 id를 그대로
    쓴다. 한계: 서로 다른 패키지의 동명 클래스는 라벨이 같아진다. 패키지를 되붙여 유일화하는
    쪽은 일부러 택하지 않았다(다시 길어져 원래 문제로 회귀) — 구분이 필요한 순간엔 상세
    패널의 전체 id가 답을 준다.
    """
    if vis_type == "endpoint" and (method or path):
        p = path or ""
        if len(p) > 34:
            segs = [s for s in p.split("/") if s]
            if len(segs) > 2:
                p = ".../" + "/".join(segs[-2:])
        return p if (method or "").upper() in ("", "ANY", "*") else f"{method} {p}"

    core = (nid or "").split("#dup", 1)[0]
    if core.startswith("db_table:"):
        return _clip(core[len("db_table:"):])
    if core.startswith("trigger:"):
        head, _, frag = core[len("trigger:"):].partition("#")
        base = os.path.basename(head.replace("\\", "/")) or head
        return f"{_clip(base)}\n#{_clip(frag)}" if frag else _clip(base)
    if vis_type in ("view", "vue_view"):
        # view 노드는 file이 비어 있을 수 있어(실측 view: 노드는 file이 채워져 있지만
        # 방어적으로) id의 "view:" 뒤 경로도 후보로 쓴다.
        src = file_path
        if not src and core.startswith("view:"):
            src = core[len("view:"):]
        base = os.path.basename((src or "").replace("\\", "/"))
        if base:
            return _clip(base)
    parts = core.split(".")
    if len(parts) >= 2:
        core = ".".join(parts[-2:])            # Class.method 만 남긴다
    return _clip(core)


def compute_common_path_prefix(nodes):
    """
    전체 노드의 file 경로들이 공유하는 최상위 디렉터리 접두사(세그먼트 리스트)를 동적으로
    찾는다. 프로젝트마다 최상위 폴더 구조가 다르므로(WEB-INF/jsp/, WEB-INF/src/java/,
    src/main/java/ 등) 하드코딩하지 않고 실제 파일 경로들의 최장 공통 접두사를 계산해
    module_candidate()이 그 다음 단계 디렉터리부터 모듈 후보로 쓸 수 있게 한다.
    _MODULE_CONTAINER_PREFIXES(고정 단어 목록)와는 상호 보완 관계다 — 이건 "이
    프로젝트 전체가 실제로 공유하는" 접두사라 목록에 없는 낯선 빌드 레이아웃에도 적응하고,
    고정 목록은 공통 접두사 밑에서도 반복되는(예: 일부 트리에만 있는 src/java) 잔여 컨테이너
    폴더를 잡아낸다 — 어느 한쪽만으로는 부족하다(아래 module_candidate 참고).
    """
    seg_lists = []
    for n in nodes:
        p = (n.get("file") or "").replace("\\", "/")
        segs = [s for s in p.split("/") if s]
        if len(segs) >= 2:  # 마지막 세그먼트(파일명)는 접두사 계산에서 제외
            seg_lists.append(segs[:-1])
    if not seg_lists:
        return []
    prefix = seg_lists[0]
    for segs in seg_lists[1:]:
        common_len = 0
        for a, b in zip(prefix, segs):
            if a != b:
                break
            common_len += 1
        prefix = prefix[:common_len]
        if not prefix:
            break
    return prefix


def module_candidate(node, vis_type, common_prefix=None):
    """
    노드 하나를 모듈/패키지 단위로 묶기 위한 후보를 만든다. (is_final, value) 튜플을
    반환한다 — is_final=True면 value는 바로 쓸 확정 모듈 키(str). is_final=False면
    value는 세분화된 경로(tuple) — 호출부가 전체 노드를 다 본 뒤 rollup_modules()로
    2차 병합해야 최종 모듈 키가 된다(밑에서 이유 설명).

    DB 테이블·외부 시스템은 소속 패키지가 무의미하므로(어차피 여러 모듈에서 공유 접근)
    타입 자체를 모듈로 쓴다 — 바로 확정. _looks_generated()가 참이면(주석·경로에 생성
    코드 마커) rollup 대상에서 완전히 빼고 "⚙️ 생성 코드" 하나로 즉시 확정한다 — 큰
    생성 코드 덩어리(예: WSDL 스텁 128개)는 파일 수가 작지 않아 rollup_modules()의
    "작은 것부터 접기" 로직으로는 안 걸러지기 때문에, 애초에 후보 단계에 들어가지도
    않게 한다.

    파일 경로 기준으로 판단한다(dotted id 기준이 아님) — analyzer가 만드는 `trigger:` id는
    "trigger:UI Project/HPS.QS/HPS.QS.QB/00 검사요청/HPSQB00030(...).Designer"처럼 파일
    경로 자체가 id라, dotted-id 분리 방식으로는 파일마다 별개 모듈이 되기 때문이다.

    1순위: 폴더 이름 자체가 네임스페이스형(점 2개 이상, 예: "HPS.QS.QA")인 .NET류 관례 —
    이 규칙이 매치되면 그대로 확정. (HPS 실사용 검증 완료, 아래 2순위는 이 매치가 하나도
    없을 때만 평가되므로 이 경로의 동작은 바뀌지 않는다.)

    2순위: Java/Kotlin류처럼 패키지 세그먼트마다 폴더가 하나씩인 관례 — 계층 이름
    (service/dao/action 등)과 빌드 컨테이너 폴더(src/main/java, WEB-INF/classes 등)를
    걷어낸 나머지 전체 경로를 "세분화 후보"로 반환한다(확정 아님). 실측(xu43-server,
    Struts+coperframe 구조, 706개 파일)에서 이 세분화 후보를 그대로 모듈로 쓰면 139개까지
    쪼개졌다 — education 밑에 apply/course/session/valuation 등 진짜 다른 기능이 많아서
    "마지막 2세그먼트"든 무엇이든 고정 규칙 하나로는 적당한 개수로 못 줄인다. 그래서 여기서는
    후보만 반환하고, 실제 병합은 전체 분포를 본 뒤 rollup_modules()가 예산(목표 모듈 수)에
    맞춰 형제 중 작은 것부터 부모 경로로 접어 올린다.
    """
    if vis_type in ("db_table", "mssql_table"):
        return True, "🗄 DB 테이블"
    if vis_type in ("external", "sap_interface"):
        return True, "🔶 외부 시스템"
    if vis_type == "endpoint":
        # 엔드포인트는 경로 기반 분류가 무의미하다 — struts는 414개가 전부
        # WEB-INF/config/actconf/struts-*.xml을 공유해서 "config.actconf"라는 뜻 없는 모듈로
        # 뭉쳤다. 가상 모듈로 승격하면 "이 시스템의 API 전체"가 찾을 수 있는 하나의 군집이
        # 되고, 템플릿의 PSEUDO_MODULE_KEYS 스코프 완화가 이미 적용돼 드릴다운 시 다른
        # 모듈에 있는 핸들러까지 함께 펼쳐진다.
        return True, "🌐 API 엔드포인트"
    if _looks_generated(node):
        return True, "⚙️ 생성 코드"
    if _looks_vendor_library(node):
        return True, "📦 외부 라이브러리"
    nid = node.get("id") or ""
    path = node.get("file") or ""
    if not path and nid.startswith("trigger:"):
        path = nid[len("trigger:"):]
    path = path.replace("\\", "/")
    segments = [s for s in path.split("/") if s]
    body = segments[:-1]  # 파일명 제외

    # 1순위 판정은 원본 경로 전체를 본다 — common_prefix로 먼저 잘라내면, 프로젝트
    # 전체가 우연히 dotted 폴더 하나를 공유 루트로 쓰는 드문 경우에 그 폴더까지
    # 함께 잘려나가 1순위가 발동을 못 할 수 있다.
    dotted = [s for s in body if s.count(".") >= 2]
    if dotted:
        return True, dotted[-1]

    # 2순위(Java류)에서만 공통 접두사를 먼저 제거한다 — 프로젝트마다 다른 최상위
    # 빌드 레이아웃(WEB-INF/src/java, src/main/java 등)에 적응한다.
    if common_prefix:
        cp_len = len(common_prefix)
        if body[:cp_len] == common_prefix:
            body = body[cp_len:]

    trimmed = list(body)
    while trimmed and trimmed[-1].lower() in _MODULE_LAYER_NAMES:
        trimmed.pop()
    while trimmed and (trimmed[0].lower() in _MODULE_CONTAINER_PREFIXES or trimmed[0].lower().endswith(" project")):
        trimmed.pop(0)
    if not trimmed:
        trimmed = body
    if trimmed:
        return False, tuple(trimmed)

    # 3순위: 파일/경로 정보 자체가 없는 극히 드문 경우 — id의 dotted prefix로 최후 폴백
    parts = nid.split(".")
    if len(parts) >= 3:
        return True, ".".join(parts[:-2])
    if len(parts) == 2:
        return True, parts[0]
    return True, nid or "(module 미상)"


def rollup_modules(leaf_counts, target_max):
    """
    module_candidate()가 반환한 세분화 경로(tuple)들이 목표 개수(target_max)를 넘으면,
    형제(같은 부모 경로를 가진) 중 파일 수가 가장 작은 것부터 부모 경로로 접어 올려서
    개수를 줄인다. "마지막 N세그먼트"처럼 고정 깊이를 쓰지 않는 이유: 실측 프로젝트가
    하위트리마다 깊이가 다 달라서(예: "front/community"는 2단계로 이미 충분한데
    "eduport/lms/back/education/apply"는 5단계) 고정 깊이 하나로는 얕은 쪽은 그대로 두고
    깊은 쪽만 적당히 접는 게 안 된다. 트리 구조를 그대로 따라 "가장 작은 것부터" 접으면
    자연히 진짜 세분화가 필요한 큰 하위트리는 오래 남고, 파일 몇 개짜리 잔가지만 먼저
    부모로 흡수된다.

    leaf_counts: {tuple(segments): 파일 수}. target_max개 이하가 될 때까지 반복.
    반환: {원본 leaf tuple: 최종(병합 후) tuple} 매핑 — 호출부가 각 노드의 원래 후보를
    이걸로 조회해 최종 모듈 문자열(".".join(...))을 만든다.
    """
    groups = dict(leaf_counts)
    membership = {t: {t} for t in leaf_counts}

    def parent_of(t):
        return t[:-1] if len(t) > 1 else t

    while len(groups) > target_max:
        mergeable = [t for t in groups if len(t) > 1]
        if not mergeable:
            break  # 전부 1단계 경로뿐이면 더 못 접음 — target_max 초과 상태로 종료
        smallest = min(mergeable, key=lambda t: groups[t])
        cnt = groups.pop(smallest)
        members = membership.pop(smallest)
        parent = parent_of(smallest)
        groups[parent] = groups.get(parent, 0) + cnt
        membership.setdefault(parent, set()).update(members)

    leaf_to_final = {}
    for final_t, members in membership.items():
        for leaf in members:
            leaf_to_final[leaf] = final_t
    return leaf_to_final


def compute_layout(node_ids, edges, iterations=100, seed=42, target_spacing=120.0):
    """
    stdlib-only Fruchterman-Reingold 스타일 force-directed 레이아웃.
    node_ids: 배치할 노드 id의 iterable (전체 그래프의 부분집합 가능).
    edges: (from_id, to_id) 튜플의 iterable. node_ids 밖의 endpoint를 가진 엣지는 무시.
    반환: id -> (x, y) dict, (0,0) 부근 중심, vis-network 캔버스 단위.

    엣지가 하나도 없는(고립) 노드는 FR 시뮬레이션에서 아예 뺀다 — 반발력만 받아 경계까지
    밀려나는 문제(vis-network forceAtlas2Based의 centralGravity 같은 인력을 추가해봤지만,
    담금질(temperature) 스케줄이 후반부에는 이동 폭을 거의 0으로 줄여버려서 초반에 이미
    경계에 붙은 노드는 그 뒤로 인력을 세게 줘도 되돌아오지 못했다 — 실측: xu43-server
    48개 모듈 중 28개가 경계(±1247)에 그대로 붙어 있었음). 대신 연결된 노드끼리만 FR을
    돌려 중앙 군집을 만들고, 고립 노드는 그 군집 바로 바깥에 원형으로 가지런히 배치한다 —
    물리 시뮬레이션의 우연에 기대지 않는 결정론적 방식이라 항상 화면 안에 들어온다.

    결정론 보장:
      - node_ids를 정렬 후 사용한다. 문자열 set/dict의 순회 순서는 프로세스마다 달라질 수
        있어(PYTHONHASHSEED) 정렬 없이는 같은 입력 그래프에도 실행마다 다른 바이트 출력이
        나올 수 있고, 이는 wiki-hub 발행 시 불필요한 새 버전을 만든다(위쪽의 기존
        `sorted(..., key=lambda item: (-item[1], item[0]))`과 같은 이유).
      - random.Random(seed)로 지역 인스턴스를 써서 다른 코드의 random 사용과 격리한다.
    """
    ids_all = sorted(set(node_ids))
    n_all = len(ids_all)
    if n_all == 0:
        return {}
    if n_all == 1:
        return {ids_all[0]: (0.0, 0.0)}

    id_set = set(ids_all)
    adj_all = [(f, t) for f, t in edges if f in id_set and t in id_set and f != t]
    degree = {nid: 0 for nid in ids_all}
    for f, t in adj_all:
        degree[f] += 1
        degree[t] += 1
    ids = [nid for nid in ids_all if degree[nid] > 0]
    isolated_ids = [nid for nid in ids_all if degree[nid] == 0]
    n = len(ids)

    if n == 0:
        # 전부 고립 — 군집 자체가 없으므로 원점 중심 원형 배치만으로 끝낸다.
        return _place_in_ring(ids_all, (0.0, 0.0), target_spacing * 2, seed)
    if n == 1:
        pos = {ids[0]: (0.0, 0.0)}
    else:
        rng = random.Random(seed)
        k = target_spacing  # call-graph.template.html의 forceAtlas2Based springLength(120)와 맞춤
        side = k * math.sqrt(n)
        id_set = set(ids)
        adj = [(f, t) for f, t in adj_all if f in id_set and t in id_set]

        pos = {nid: (rng.uniform(-side / 2, side / 2), rng.uniform(-side / 2, side / 2)) for nid in ids}
        index = {nid: i for i, nid in enumerate(ids)}
        disp = [[0.0, 0.0] for _ in ids]
        temperature = side / 10.0

        for _ in range(iterations):
            for i in range(n):
                disp[i][0] = 0.0
                disp[i][1] = 0.0

            for i in range(n):
                xi, yi = pos[ids[i]]
                for j in range(i + 1, n):
                    xj, yj = pos[ids[j]]
                    dx, dy = xi - xj, yi - yj
                    dist2 = dx * dx + dy * dy
                    if dist2 < 1e-4:
                        dx, dy = rng.uniform(-1, 1), rng.uniform(-1, 1)
                        dist2 = 1e-4
                    dist = math.sqrt(dist2)
                    force = (k * k) / dist
                    fx, fy = dx / dist * force, dy / dist * force
                    disp[i][0] += fx; disp[i][1] += fy
                    disp[j][0] -= fx; disp[j][1] -= fy

            for f, t in adj:
                xf, yf = pos[f]; xt, yt = pos[t]
                dx, dy = xf - xt, yf - yt
                dist = math.sqrt(dx * dx + dy * dy) or 0.01
                force = (dist * dist) / k
                fx, fy = dx / dist * force, dy / dist * force
                i, j = index[f], index[t]
                disp[i][0] -= fx; disp[i][1] -= fy
                disp[j][0] += fx; disp[j][1] += fy

            for i, nid in enumerate(ids):
                dx, dy = disp[i]
                dlen = math.sqrt(dx * dx + dy * dy) or 0.01
                capped = min(dlen, temperature)
                x, y = pos[nid]
                x = max(-side, min(side, x + dx / dlen * capped))
                y = max(-side, min(side, y + dy / dlen * capped))
                pos[nid] = (x, y)
            temperature *= 0.95

    if isolated_ids:
        cx = sum(p[0] for p in pos.values()) / len(pos)
        cy = sum(p[1] for p in pos.values()) / len(pos)
        max_r = max((math.hypot(x - cx, y - cy) for x, y in pos.values()), default=0.0)
        ring_pos = _place_in_ring(isolated_ids, (cx, cy), max_r + target_spacing * 2, seed)
        pos.update(ring_pos)

    return {nid: (round(x, 1), round(y, 1)) for nid, (x, y) in pos.items()}


def _place_in_ring(ids, center, radius, seed):
    """ids를 center를 중심으로 반지름 radius인 원 위에 균등 간격으로 배치한다(결정론적).
    compute_layout()이 고립 노드(연결된 엣지가 하나도 없는 노드)를 물리 시뮬레이션 없이
    항상 화면 안쪽에, 겹치지 않게 배치하는 데 쓴다."""
    ids_sorted = sorted(ids)
    n = len(ids_sorted)
    cx, cy = center
    if n == 1:
        return {ids_sorted[0]: (cx + radius, cy)}
    return {
        nid: (round(cx + radius * math.cos(2 * math.pi * i / n), 1),
              round(cy + radius * math.sin(2 * math.pi * i / n), 1))
        for i, nid in enumerate(ids_sorted)
    }


def _place_remaining_near_neighbors(remaining_ids, edges, known_positions, seed=42):
    """LARGE_VISIBLE_SET_CAP 초과로 compute_layout을 허브에만 돌렸을 때, 나머지 노드를
    이미 배치된 이웃들의 평균 좌표 + 지터로 배치한다(고아 노드는 원점 부근 폴백)."""
    rng = random.Random(seed)
    adjacency = {}
    for f, t in edges:
        adjacency.setdefault(f, []).append(t)
        adjacency.setdefault(t, []).append(f)
    positions = dict(known_positions)
    for nid in sorted(remaining_ids):
        neigh = [n for n in adjacency.get(nid, []) if n in positions]
        if neigh:
            cx = sum(positions[n][0] for n in neigh) / len(neigh)
            cy = sum(positions[n][1] for n in neigh) / len(neigh)
        else:
            cx, cy = 0.0, 0.0
        positions[nid] = (round(cx + rng.uniform(-60, 60), 1), round(cy + rng.uniform(-60, 60), 1))
    return positions


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
    api_merge_info = {"endpoints": 0, "enriched": 0, "enriched_nodes": 0,
                      "new_nodes": 0, "new_edges": 0, "ladder": {}}
    endpoint_flows = {}
    call_graph_path = os.path.join(project_root, "_workspace", "index", "call_graph.json")
    cg_template = read_file(os.path.join(LIB_DIR, "call-graph.template.html"))
    nodes_data, edges_data = [], []
    if cg_template:
        raw_graph = load_json(call_graph_path) or {"nodes": [], "edges": []}
        # 노드 상세 패널의 extends/implements/메서드 목록은 call_graph가 아니라 symbols.json에만 있다.
        # 파트너 그래프 노드는 prefix_graph()가 "partner_"/"partner{i}_" 접두사를 붙여놓기
        # 때문에(위 prefix_graph 참조) 자기 symbols.json만 인덱싱하면 파트너 노드는 100%
        # 미스가 된다 — 실측 xu43-server 병합 그래프에서 파트너 노드 13,966개 전부
        # extends/implements/methods가 빈 값이었다(병합 그래프 전체 노드의 55%).
        #
        # 조회 시점에 접두사를 벗기는 대신 인덱스 시점에 붙이는 이유: 벗기려면 조회 지점이
        # partner_/partner0_/.../partner9_ 중 무엇인지 알아야 하고, 우연히 "partner_"로
        # 시작하는 정상 id를 망칠 위험이 있다. 붙이는 쪽이 정확하고 조회 코드는 무수정이다.
        def _index_symbols(symbols_json, prefix=""):
            out = {}
            for s in ((symbols_json or {}).get("symbols") or []):
                if isinstance(s, dict) and s.get("id"):
                    out[f"{prefix}{s['id']}"] = s
            return out

        own_symbols_json = load_json(os.path.join(project_root, "_workspace", "index", "symbols.json"))
        symbol_by_id = _index_symbols(own_symbols_json)
        if hub_partner_cfgs:
            for _i, _cfg in enumerate(hub_partner_cfgs):
                _ws = _cfg.get("partner_workspace")
                if _ws:
                    symbol_by_id.update(_index_symbols(
                        load_json(os.path.join(_ws, "index", "symbols.json")), f"partner{_i}_"))
        else:
            _pair_cfg = parse_pair_config(project_root)
            if _pair_cfg and _pair_cfg.get("partner_workspace"):
                symbol_by_id.update(_index_symbols(
                    load_json(os.path.join(_pair_cfg["partner_workspace"], "index", "symbols.json")),
                    "partner_"))

        if hub_partner_cfgs:
            raw_graph, merge_info = merge_hub_partner_call_graphs(project_root, raw_graph, hub_partner_cfgs)
        else:
            raw_graph, merge_info = merge_partner_call_graph(project_root, raw_graph)

        raw_graph, db_merge_info = merge_db_tables_into_graph(raw_graph, own_schema_json, own_sql_usage_json)

        # 엔드포인트 병합은 파트너·DB 병합 뒤, degree/허브/레이아웃/모듈 집계보다 앞이어야 한다.
        # (a) 파트너 병합 뒤라야 partner_ 접두사와 api: 접두사가 충돌할 수 없고,
        # (b) degree 계산 앞이라야 신규 serves 엣지가 허브 랭킹·초기 표시 집합에 반영되고,
        # (c) compute_layout·module_candidate가 신규 노드를 함께 배치·분류한다.
        raw_graph, api_merge_info = merge_api_endpoints_into_graph(raw_graph, own_api_contract_json)

        # 아래는 그래프 위상을 바꾸지 않는 메타데이터 전용이므로 순서 자유 —
        # degree/레이아웃/모듈 집계에 일절 영향이 없다.
        endpoint_flows = build_endpoint_flows(
            load_json(os.path.join(project_root, "_workspace", "index", "data_flow.json")))

        detected_types = set()
        nodes_data = []
        edges_data = []
        meta_data = {}

        COLORS = {
            "view":          {"bg": '#7B1A1A', "border": '#E74C3C', "font": '#fff'},
            "vue_view":      {"bg": '#7B1A1A', "border": '#E74C3C', "font": '#fff'},
            "endpoint":      {"bg": '#1a5fa8', "border": '#4A90D9', "font": '#fff'},
            # classify_trigger()가 trigger에서 분리한 두 타입.
            # entrypoint는 호박색 — 개수가 적고(실측 server 24개) 중요하다.
            # ui_event는 탈채도 회청 — 실측 server 1,839개/HPS 1,094개로 압도적으로 많지만
            # 아키텍처가 아니라 배선이라 시각적으로 물러나야 한다(예전엔 이게 전부 파란
            # "API 엔드포인트"로 칠해져 화면을 지배했다).
            "entrypoint":    {"bg": '#5b3a00', "border": '#D98E04', "font": '#fff'},
            "ui_event":      {"bg": '#3a3f4b', "border": '#8792a8', "font": '#e8ecf3'},
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

        # 배지/범례/통계용 "허브" 임계값. 기존 total_nodes*0.15는 노드 수만 보는 고정 비율이라
        # 호출 그래프처럼 간선이 노드 수에 비례할 뿐 밀도가 안 오르는 그래프(간선 ≈ 노드)에서는
        # 그래프가 커질수록 실제 in-degree와 무관하게 값이 폭주해 대형 그래프는 항상 허브 0개로
        # 표시됐다(3857개 → 578 요구, 실측 최대 in-degree 168). 실제 in-degree 분포의 상위
        # 5%(95th percentile) 지점을 쓰고, 그래프가 아주 작거나 균일해 값이 무의미하게 낮아질
        # 때를 대비해 최솟값 3을 둔다.
        in_degree_sorted_desc = sorted(in_degree.values(), reverse=True)
        if in_degree_sorted_desc:
            top5_pct_rank = max(1, int(len(in_degree_sorted_desc) * 0.05))
            hub_threshold = max(3, in_degree_sorted_desc[top5_pct_rank - 1])
            # 간선이 노드 수에 비례할 뿐 밀도가 안 오르는 희소 그래프(트리형 정적 호출그래프
            # 등)는 5%ile 값보다 최솟값 3이 항상 더 커서 위 max()가 실제 최대 in-degree보다도
            # 높은 임계값을 만든다 — 그러면 어떤 노드도 조건을 못 채워 허브가 다시 0개로
            # 표시된다(실측: xu43-client, 노드 24671/엣지 21814, 최대 in-degree 3 미만).
            # 실제 데이터가 낼 수 있는 최댓값을 넘지 않도록 clamp해 최소 1개는 허브로 잡히게 한다.
            hub_threshold = min(hub_threshold, in_degree_sorted_desc[0])
        else:
            hub_threshold = 3

        # 대형 그래프는 초기 렌더링에 노드 전량을 vis-network에 올려 브라우저가 버벅였다(상한 없음, 실측
        # call_graph.json 36MB). 물리엔진 OFF 기준(300)과 같은 경계에서, in-degree 상위 허브 + 그 직접
        # 이웃만 초기에 표시하고 나머지는 클릭·검색으로 확장한다(전체 데이터는 그대로 보존, 손실 없음).
        # hub_threshold(위, 배지 크기용)와는 별개 — 대형 그래프에서 hub_threshold는 너무 높아져
        # 사실상 0개가 되므로 순위 기반으로 별도 계산한다.
        SMALL_GRAPH_THRESHOLD = 300
        if total_nodes <= SMALL_GRAPH_THRESHOLD or not raw_graph.get("edges"):
            initial_ids = None  # 축소 없음 — 현재와 동일하게 전부 표시 (엣지 0개면 랭킹 근거가 없음)
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

        # ---- 정적 레이아웃 프리컴퓨트 (물리엔진 OFF 상태에서도 원형 뭉침 방지) ----
        # vis-network는 물리엔진이 꺼져 있고 노드에 x/y가 없으면 construction 시점에
        # positionInitially()로 반지름 ~(전체 노드수+50)인 원 위에 무작위 배치한다. 대형
        # 그래프는 물리엔진이 기본 OFF라 이 원형 배치가 그대로 남는다. "초기 표시(initial)"
        # 노드 집합만 생성 시점에 파이썬에서 좌표를 구워, 물리엔진 상태와 무관하게 항상
        # 읽을 수 있는 배치가 나오게 한다.
        LARGE_VISIBLE_SET_CAP = 1500
        visible_ids = set(initial_ids) if initial_ids is not None else {
            n.get("id") for n in raw_graph.get("nodes", [])
        }
        visible_edges = [
            (e.get("from"), e.get("to"))
            for e in raw_graph.get("edges", [])
            if e.get("from") in visible_ids and e.get("to") in visible_ids
        ]
        if len(visible_ids) <= LARGE_VISIBLE_SET_CAP:
            n_for_iter = len(visible_ids)
            pair_count = max(1, n_for_iter * (n_for_iter - 1) // 2)
            iterations = max(30, min(100, int(50_000_000 / pair_count)))
            layout_positions = compute_layout(visible_ids, visible_edges, iterations=iterations)
        else:
            # 밀집 그래프에서 허브+이웃 확장이 예외적으로 캡을 넘으면, 허브만 정식으로
            # 배치하고 나머지는 이웃 평균 좌표로 붙인다(전량 O(n^2) 계산을 피함).
            layout_positions = compute_layout(hub_ids, visible_edges, iterations=100)
            layout_positions = _place_remaining_near_neighbors(
                visible_ids - set(layout_positions), visible_edges, layout_positions, seed=42
            )

        # 모든 노드의 file 경로가 공유하는 최상위 디렉터리를 동적으로 찾아 module_candidate()에
        # 넘긴다 — 프로젝트마다 최상위 폴더 구조(WEB-INF/jsp/, WEB-INF/src/java/, src/main/java/
        # 등)가 달라 하드코딩할 수 없다.
        common_path_prefix = compute_common_path_prefix(raw_graph.get("nodes", []))

        dead_code = {}
        if dead_code_json:
            # dead_code.json 스키마 키는 unused_methods (docs/index-spec.md) — "dead_code"가 아님.
            for item in dead_code_json.get("unused_methods", []):
                dead_code[item.get("id")] = item.get("reason", "")

        seen_node_ids = {}
        node_module = {}  # 원본 id(#dup 접미사 없음) -> 확정 모듈 키, 아래 엣지 집계에서 재사용
        # module_candidate()가 세분화 후보(tuple)를 반환한 노드는 여기 모아뒀다가, 전체
        # 분포를 본 뒤(rollup_modules) 한꺼번에 최종 모듈 키를 정해서 extra["module"]을
        # 채운다 — 노드 하나씩 볼 때는 전체 몇 개 모듈이 나올지 알 수 없기 때문이다.
        pending_module_nodes = []  # [(원본 id, 후보 tuple, extra dict)]
        module_leaf_counts = {}
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
            raw_type = node.get("type", "function")

            vis_type = "function"
            type_mapping = {
                "view": ["view", "component", "page", "screen", "jsp", "thymeleaf", "vue", "react"],
                # endpoint = api_contract.json에서 온 실제 HTTP 엔드포인트 + 컨트롤러 진입 메서드.
                # raw type "trigger"는 여기서 빼고 아래 classify_trigger()로 세분한다 — 예전엔
                # trigger가 이 목록에 있어서 jsp onclick 핸들러까지 전부 "API 엔드포인트"로
                # 칠해졌다(실측 server 2,209개 중 1,839개가 onclick).
                "endpoint": ["controller", "endpoint", "route", "api", "rest", "api_endpoint"],
                "dao": ["dao", "repository", "mapper", "store", "jpa"],
                "external": ["external", "client", "feign", "soap", "sap", "mq", "kafka", "redis"],
                "db_table": ["db", "table", "mssql", "oracle", "mysql", "postgres", "sqlite"],
                "util": ["util", "helper", "common", "config", "constant"]
            }

            if raw_type == "trigger":
                vis_type = classify_trigger(nid or "")
            elif raw_type in ["vue_view", "sap_interface", "mssql_table"]:
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

            # 엔드포인트로 보강된 노드는 원래 raw type이 무엇이었든 파란 endpoint로 통일한다.
            # aspnet-webforms/classic-asp 계열은 view: 노드에 붙기 때문에(실측 HPS 3/3,
            # client 1/2) 이 줄이 없으면 진짜 엔드포인트가 빨간 뷰로 남는다.
            if node.get("endpoint_promoted"):
                vis_type = "endpoint"

            detected_types.add(vis_type)

            # 라벨은 vis_type이 확정된 뒤에 만든다(엔드포인트/뷰 여부에 따라 규칙이 다름).
            # 결정론 인덱서 노드에는 label 키가 아예 없으므로(실측 3개 프로젝트 0%) 사실상
            # 항상 short_label()이 계산한다 — 엔드포인트 병합이 label을 넣어준 노드만 예외.
            label = node.get("label") or short_label(
                nid, vis_type, node.get("file", ""), node.get("method", ""), node.get("path", "")
            )

            node_degree = in_degree.get(nid, 0)
            extra = {}
            if node_degree >= hub_threshold:
                extra["size"] = 28
                extra["borderWidth"] = 3

            if nid in dead_code:
                extra["opacity"] = 0.4

            extra["initial"] = initial_ids is None or nid in initial_ids

            is_final, candidate = module_candidate(node, vis_type, common_path_prefix)
            if is_final:
                node_module[node.get("id")] = candidate
                extra["module"] = candidate
            else:
                module_leaf_counts[candidate] = module_leaf_counts.get(candidate, 0) + 1
                pending_module_nodes.append((node.get("id"), candidate, extra))

            # 주의: nid는 위의 중복 id 방어 로직 때문에 원본 id와 다를 수 있다(#dup 접미사).
            # layout_positions는 원본 id(node.get("id")) 기준으로 계산했으므로 조회도 원본
            # id로 해야 한다 — nid로 조회하면 중복 노드에서 조용히 miss 난다(그 노드만 좌표
            # 없이 폴백되는 드문 방어적 케이스로 허용).
            pos_xy = layout_positions.get(node.get("id"))
            if pos_xy is not None:
                extra["x"], extra["y"] = pos_xy
                # fixed는 설정하지 않는다 — 구운 좌표는 "초기 배치 힌트"일 뿐, 사용자가
                # 물리엔진 토글을 켜면 계속 움직여야 한다(fixed:true면 영구 고정돼버림).

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
                # 상세 패널이 FLOWS(data_flow.json)를 조회할 키. 하나의 struts action 노드에
                # 여러 엔드포인트가 매핑될 수 있어(실측 최대 7개) 리스트다.
                "endpointIds": node.get("endpoint_ids", []),
                "inDegree": node_degree,
                "outDegree": out_degree.get(nid, 0),
                "hub": node_degree >= hub_threshold,
                "dead": nid in dead_code,
                "deadReason": dead_code.get(nid, ""),
                "extends": sym.get("extends", ""),
                "implements": sym.get("implements", []),
                "methods": [m.get("name") for m in (sym.get("methods") or []) if isinstance(m, dict)]
            }

        # 세분화 후보로 남겨뒀던 노드(module_candidate 2순위)들의 최종 모듈 키를 이제 확정한다
        # — 전체 분포를 다 모은 지금이라야 목표 개수 안으로 접을 수 있다.
        TARGET_MAX_MODULES = 40
        leaf_to_final = rollup_modules(module_leaf_counts, TARGET_MAX_MODULES)
        for original_id, candidate, extra in pending_module_nodes:
            final_key = ".".join(leaf_to_final.get(candidate, candidate))
            node_module[original_id] = final_key
            extra["module"] = final_key

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

        # ---- 모듈/패키지 단위 개요 그래프 ----
        # 3,857개 함수를 한 캔버스에 뿌리는 것 자체가 "전체 구조를 훑어본다"는 목적과 안 맞는다는
        # 피드백에 따라, 기본 화면을 모듈(패키지) 단위 요약 그래프로 바꾼다. 실제 함수 단위
        # 그래프(nodesData/edgesData)는 그대로 유지되고, 사용자가 모듈을 클릭하면 그 모듈
        # 내부만 보여주는 드릴다운 화면으로 전환된다(call-graph.template.html에서 처리).
        #
        # SMALL_GRAPH_THRESHOLD(위에서 정의, 초기 허브+이웃 축소와 동일 경계) 이하인 작은
        # 그래프는 모듈 개요를 만들 필요가 없다 — 어차피 전체를 한 화면에 그려도 읽을 수
        # 있는 크기라, 괜히 2단계 클릭을 강제하면 UX만 나빠진다. 이 경우 MODULE_NODES를
        # 빈 배열로 둬서 템플릿이 자동으로 기존 단일 레벨 그래프로 폴백하게 한다
        # (call-graph.template.html의 `if (MODULE_NODES.length >= 2)` 분기).
        if total_nodes > SMALL_GRAPH_THRESHOLD:
            module_node_count = {}
            for m in node_module.values():
                module_node_count[m] = module_node_count.get(m, 0) + 1

            module_edge_agg = {}
            for e in raw_graph.get("edges", []):
                fm = node_module.get(e.get("from"))
                tm = node_module.get(e.get("to"))
                if fm and tm and fm != tm:
                    key = (fm, tm)
                    module_edge_agg[key] = module_edge_agg.get(key, 0) + 1

            module_ids_sorted = sorted(module_node_count.keys())
            module_layout_edges = list(module_edge_agg.keys())
            module_with_cross_edge = {m for pair in module_edge_agg for m in pair}
            # 모듈 그래프는 보통 수십 개 수준이라 전량 FR로 계산해도 충분히 빠르다. 모듈 간
            # 실제 호출(cross-module edge) 없이 고립된 모듈은 compute_layout()이 자동으로
            # 중앙 군집 바깥 원형으로 배치한다(대부분의 호출은 모듈 "내부"에서 끝나 모듈
            # 개요 엣지에는 안 잡히는 경우가 많아, 실측 xu43-server 48개 모듈 중 상당수가
            # 이 경우였다).
            module_positions = compute_layout(module_ids_sorted, module_layout_edges, iterations=150, seed=7, target_spacing=180.0)

            module_nodes_js = []
            for m in module_ids_sorted:
                x, y = module_positions.get(m, (0.0, 0.0))
                module_nodes_js.append(json.dumps({
                    "id": m, "label": m, "count": module_node_count[m], "x": x, "y": y,
                    "connected": m in module_with_cross_edge
                }))
            module_edges_js = [
                json.dumps({"from": fm, "to": tm, "count": cnt})
                for (fm, tm), cnt in sorted(module_edge_agg.items())
            ]
            module_nodes_array_str = "[\n      " + ",\n      ".join(module_nodes_js) + "\n    ]" if module_nodes_js else "[]"
            module_edges_array_str = "[\n      " + ",\n      ".join(module_edges_js) + "\n    ]" if module_edges_js else "[]"
        else:
            module_nodes_array_str = "[]"
            module_edges_array_str = "[]"

        btn_labels = {
            # endpoint는 이제 api_contract.json에서 온 실제 HTTP 엔드포인트만 가리킨다
            # (classify_trigger가 onclick 핸들러를 ui_event로 분리했다).
            "view": "🖥 뷰", "vue_view": "🖥 Vue 뷰", "endpoint": "⚡ API 엔드포인트",
            "ui_event": "🖱 UI 이벤트", "entrypoint": "🚀 진입점(main/배치)",
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
        # 두 타입이 실제로 나타날 때만 설명을 붙인다 — 범례가 없는 타입을 설명하면 그것도 거짓이다.
        if "ui_event" in detected_types or "entrypoint" in detected_types:
            legend_html += (
                '<div class="legend-note">🖱 UI 이벤트 = 화면 컨트롤·마크업 핸들러 · '
                '⚡ API 엔드포인트 = api_contract.json의 실제 HTTP 엔드포인트</div>\n        '
            )
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
        # 물리엔진/동적 엣지 스무딩 on-off는 "전체 데이터셋 크기"가 아니라 "초기에 실제로
        # 화면에 보이는(hidden=false) 노드/엣지 수" 기준이어야 한다 — vis-network는 hidden
        # 노드를 물리 시뮬레이션에서 제외한다. 위에서 이미 계산한 visible_ids/visible_edges를
        # 재사용한다(중복 계산 방지).
        #
        # 주의: 물리엔진 기본 ON 임계값은 LARGE_VISIBLE_SET_CAP(1500, 파이썬 사전 배치의
        # O(n^2) 계산 상한 — 생성 시점 1회 비용)과 절대 같은 값을 쓰면 안 된다. 실측 결과
        # 955개 노드에서도 forceAtlas2Based stabilization(250 iteration)이 브라우저 메인
        # 스레드를 오래 막아 화면이 안 그려질 정도로 느렸다(2026-09 사용자 리포트). 노드는
        # 이미 위에서 좌표가 구워져 있어 물리엔진 없이도 읽을 수 있는 배치가 보장되므로,
        # 대형 그래프는 SMALL_GRAPH_THRESHOLD와 동일한 훨씬 보수적인 기준으로 기본 OFF를
        # 유지하고, 필요하면 사용자가 토글로 직접 켜게 한다(이미 좋은 좌표에서 시작하므로
        # 수동으로 켜도 예전의 "나쁜 원형 배치에서 시작" 문제는 없다).
        PHYSICS_NODE_THRESHOLD = SMALL_GRAPH_THRESHOLD
        visible_node_count = len(visible_ids)
        visible_edge_count = len(visible_edges) if initial_ids is not None else len(edges_data)
        physics_default = visible_node_count <= PHYSICS_NODE_THRESHOLD
        edge_smooth_dynamic = visible_edge_count <= 500

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
            .replace("{{MODULE_NODES}}", module_nodes_array_str)\
            .replace("{{MODULE_EDGES}}", module_edges_array_str)\
            .replace("{{META}}", json.dumps(meta_data, indent=2))\
            .replace("{{FLOWS}}", json.dumps(
                endpoint_flows, ensure_ascii=False, sort_keys=True, separators=(",", ":")))\
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

    # 조인 사다리 census를 남기는 이유: 향후 analyzer가 dispatch_bean 같은 필드 이름을 바꾸면
    # L1이 급감하고 L7(조인 실패)이 튀어오른다 — 조용히 망가지는 대신 이 표에서 드러난다.
    if api_merge_info.get("endpoints"):
        report_content += (
            f"\nAPI 엔드포인트 병합 (call-graph.html): ✅ api_contract.json 엔드포인트 "
            f"{api_merge_info['endpoints']}개 → 기존 노드 제자리 보강 {api_merge_info['enriched']}건"
            f"({api_merge_info['enriched_nodes']}개 노드), 신규 노드 {api_merge_info['new_nodes']}개, "
            f"신규 serves 엣지 {api_merge_info['new_edges']}개\n"
            f"  조인 사다리: {api_merge_info['ladder']}\n"
        )
    else:
        report_content += "\nAPI 엔드포인트 병합 (call-graph.html): ⏭ 스킵 — api_contract.json에 엔드포인트 없음/파일 없음\n"

    if endpoint_flows:
        report_content += (
            f"\n데이터 흐름 (call-graph.html 상세 패널): ✅ data_flow.json 기반 엔드포인트별 흐름 "
            f"{len(endpoint_flows)}건 (메서드 체인·SQL·읽기/쓰기 테이블 + 서술). 노드·엣지 추가 없음 — "
            f"흐름은 이미 존재하는 call/query 엣지의 투영이라 엣지로 만들면 허브 임계값이 이동한다\n"
        )
    else:
        report_content += "\n데이터 흐름 (call-graph.html 상세 패널): ⏭ 스킵 — data_flow.json 없음/chains 없음\n"

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
