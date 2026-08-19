# 스택별 index_extractor_*.py가 공유하는 보일러플레이트 (LLM 미사용).
# Java/Spring(index_extractor_java_spring.py)에서 검증 끝난 로직을 그대로 뽑아왔다 —
# 여기서 동작을 바꾸면 이미 검증된 java_spring 추출기까지 영향받으니 신중히 다룰 것.
import os
import re
import json
import subprocess

from now_kst import now_kst

SKIP_DIRS = {
    ".git", "node_modules", "target", "build", "dist", "out", ".idea", ".vscode",
    "__pycache__", "bin", "obj", "venv", ".venv", "env", "site-packages",
    ".mypy_cache", ".pytest_cache", "egg-info",
}

# C-계열 문법(//, /* */, "...") 공용 — Java/C#/Kotlin과 Vue <script> 블록(JS/TS)이 모두 해당.
# 백틱(`) 템플릿 리터럴은 다루지 않음(알려진 한계, JS/TS 흔한 패턴이라 향후 보강 여지).
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_RE = re.compile(r"//[^\n]*")
STRING_LITERAL_RE = re.compile(r'"(?:\\.|[^"\\])*"')


def strip_noise(text):
    """주석/문자열 리터럴을 같은 길이의 공백으로 치환 — 줄 번호(line)가 원본 텍스트와
    어긋나지 않게 하기 위해 삭제 대신 공백 치환을 쓴다."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = BLOCK_COMMENT_RE.sub(blank, text)
    text = LINE_COMMENT_RE.sub(blank, text)
    text = STRING_LITERAL_RE.sub(blank, text)
    return text


def walk_files(root, suffix, skip_dirs=SKIP_DIRS):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if fn.endswith(suffix):
                files.append(os.path.join(dirpath, fn))
    return files


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def annotations_before(text, pos, marker_re, format_fn=None):
    """선언 시작 위치(pos, 그 직전 개행 문자 지점) 바로 앞쪽 줄들을 거슬러 올라가며
    marker_re(예: @Foo 또는 [Foo])에 매치되는 줄을 모은다. format_fn(match)로 기록할
    문자열을 결정 — 기본은 매치 전체(group(0)), 언어별로 괄호 인자 포함 여부를 다르게
    하려면 커스텀 format_fn을 넘긴다."""
    if format_fn is None:
        format_fn = lambda m: m.group(0).strip()
    anns = []
    cursor = pos
    while True:
        line_start = text.rfind("\n", 0, cursor) + 1
        line = text[line_start:cursor].strip()
        if not line:
            if line_start == 0:
                break
            cursor = line_start - 1
            continue
        m = marker_re.match(line)
        if not m:
            break
        anns.insert(0, format_fn(m))
        if line_start == 0:
            break
        cursor = line_start - 1
    return anns


def matching_brace(text, open_pos):
    """open_pos가 가리키는 '{' 에 대응하는 '}' 의 인덱스를 찾는다."""
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def split_type_list(raw):
    """콤마로 구분된 타입 목록을 <>(제네릭) 중첩은 무시하고 분리한다."""
    if not raw:
        return []
    parts = []
    depth = 0
    buf = ""
    for ch in raw:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return [p for p in parts if p]


def simple_type(raw):
    """제네릭·배열 표기를 벗겨 단순 타입명만 남긴다 (예: List<OrderDto> -> List, string[] -> string)."""
    raw = raw.strip()
    raw = re.sub(r"<.*>", "", raw)
    raw = raw.replace("[]", "")
    return raw.strip().split(".")[-1]


def dedupe_edges(edges):
    seen = set()
    result = []
    for e in edges:
        key = (e["from"], e["to"], e["type"])
        if key in seen:
            continue
        seen.add(key)
        result.append(e)
    return result


def git_commit(root):
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def base_meta(root, generator, files_scanned, files_total):
    return {
        "generated_at": now_kst(),
        "generator": generator,
        "version": "1.0",
        "source_root": root,
        "mode": "init",
        "git_commit": git_commit(root),
        "sampled": False,
        "files_scanned": files_scanned,
        "files_total": files_total,
    }


def _load_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _dedupe_by_id(items):
    """id 기준 first-writer-wins. 반환: (병합 목록, 충돌 건수)."""
    seen, result, collisions = set(), [], 0
    for item in items:
        key = item.get("id")
        if key in seen:
            collisions += 1
            continue
        seen.add(key)
        result.append(item)
    return result, collisions


def _dump_atomic(path, payload):
    """같은 회차에 여러 추출기가 같은 파일을 이어 쓰므로, 중간에 죽어도 반쪽 JSON이 남지 않게 한다."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def write_outputs(root, generator, symbols, nodes, edges, files_scanned, files_total):
    """symbols.json + call_graph.json을 _workspace/index/에 표준 스키마로 저장한다.
    이미 파일이 있으면(모노레포에서 다른 스택 추출기가 먼저 실행됐거나, build-index.mjs가
    만든 인덱스 위에 Vue 결과를 얹는 경우) 덮어쓰지 않고 병합한다 — 병합하지 않으면 나중에
    실행된 쪽이 앞선 결과를 지워버린다. 노드·심볼은 id 기준으로 중복을 제거한다(두 생성기가
    같은 메서드를 각자 노드화하므로, 안 하면 in-degree·허브·데드코드 집계가 왜곡된다)."""
    index_dir = os.path.join(root, "_workspace", "index")
    os.makedirs(index_dir, exist_ok=True)
    symbols_path = os.path.join(index_dir, "symbols.json")
    cg_path = os.path.join(index_dir, "call_graph.json")

    existing_symbols = _load_json(symbols_path)
    prev_scanned, prev_total, prev_generator = 0, 0, ""
    symbol_collisions = node_collisions = 0
    if existing_symbols and isinstance(existing_symbols.get("symbols"), list):
        symbols, symbol_collisions = _dedupe_by_id(existing_symbols["symbols"] + symbols)
        prev_meta = existing_symbols.get("_meta") or {}
        prev_scanned = prev_meta.get("files_scanned") or 0
        prev_total = prev_meta.get("files_total") or 0
        prev_generator = prev_meta.get("generator") or ""

    existing_cg = _load_json(cg_path)
    if existing_cg and isinstance(existing_cg.get("nodes"), list):
        nodes, node_collisions = _dedupe_by_id(existing_cg["nodes"] + nodes)
        edges = dedupe_edges(existing_cg.get("edges", []) + edges)

    # 스택별 추출기끼리는 서로 다른 파일을 보므로 합계가 맞다. 반면 build-index.mjs는 이미
    # 프로젝트 전체를 세었으므로 그 위에 얹을 때 더하면 실제 파일 수를 넘는다 — 이때는 최댓값.
    if prev_generator == "deterministic-indexer":
        total_scanned = max(prev_scanned, files_scanned)
        total_files = max(prev_total, files_total)
    else:
        total_scanned = prev_scanned + files_scanned
        total_files = prev_total + files_total

    symbols_meta = base_meta(root, generator, total_scanned, total_files)
    symbols_meta["node_count"] = len(symbols)
    symbols_meta["edge_count"] = 0
    if symbol_collisions:
        symbols_meta["merge_collisions"] = symbol_collisions
    _dump_atomic(symbols_path, {"_meta": symbols_meta, "symbols": symbols})

    cg_meta = base_meta(root, generator, total_scanned, total_files)
    cg_meta["node_count"] = len(nodes)
    cg_meta["edge_count"] = len(edges)
    if node_collisions:
        cg_meta["merge_collisions"] = node_collisions
    _dump_atomic(cg_path, {"_meta": cg_meta, "nodes": nodes, "edges": edges})

    # node.js가 없어(rank-2) 이 스크립트가 유일한 인덱서인 경우, 여기서 최소한의 표준
    # _meta.json(top-level 파일)을 같이 써준다. analyzer.md Step 8의 "기계 인덱스가 있을 때"
    # 분기는 정확히 이 파일의 존재로 게이트되는데(build-index.mjs만 만들던 파일이라), 없으면
    # analyzer가 이 스크립트의 결과를 통째로 무시하고 처음부터 다시 LLM으로 만든다
    # (2026-08-19 추가 — "all-or-nothing 비용 배증"을 막는 안전망. 여러 스택 추출기가 순서대로
    # 실행돼도 매번 같은 내용으로 덮어써 결과가 안정적이다).
    # 단 build-index.mjs가 이미 만든 _meta.json은 건드리지 않는다 — fingerprint(--check-stale)·
    # unresolved 집계·indexes 목록이 실려 있어, 이 최소 메타로 덮어쓰면 팀 공유 신선도 판정과
    # analyzer 게이트 정보가 파괴된다(보강 실행 경로, Step D).
    meta_path = os.path.join(index_dir, "_meta.json")
    existing_meta = _load_json(meta_path)
    if existing_meta and existing_meta.get("generator") == "deterministic-indexer":
        return
    top_meta = base_meta(root, generator, total_scanned, total_files)
    top_meta["source_file_count"] = total_files
    top_meta["indexes"] = ["symbols", "call_graph"]
    top_meta["unresolved_count"] = 0
    top_meta["coverage"] = {"unresolved_count": 0, "unresolved_decidable_count": 0}
    _dump_atomic(meta_path, top_meta)


def print_summary(symbols, nodes, edges, files_scanned, files_total):
    print(f"symbols.json: {len(symbols)}개 심볼 ({files_scanned}/{files_total} 파일)")
    print(f"call_graph.json: 노드 {len(nodes)}개, 엣지 {len(edges)}개")
    edge_types = {}
    for e in edges:
        edge_types[e["type"]] = edge_types.get(e["type"], 0) + 1
    for t, c in sorted(edge_types.items()):
        print(f"  - {t}: {c}")
