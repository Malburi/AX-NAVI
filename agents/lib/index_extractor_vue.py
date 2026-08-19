# Vue 2/3(+Nuxt/Pinia) 프로젝트의 symbols.json + call_graph.json을 정규식 기반으로
# 기계 추출한다 (LLM 미사용).
#
# Java/C#/Python과의 구조적 차이:
# - .vue 파일은 <template>/<script>/<style>로 나뉘고, 실제 로직은 <script> 블록 안에만
#   있다 — 그 블록만 잘라내 JS/TS로 취급한다.
# - Options API(`methods: {...}`)와 Composition API(`<script setup>`, 최상위 함수)가
#   공존한다 — 둘 다 지원하되 컴포넌트 하나 = 노드 하나(파일 단위)로 취급, 그 안의
#   methods/computed 또는 최상위 함수를 "메서드"로 붙인다.
# - Pinia 스토어(.js/.ts, `defineStore(...)` 포함)도 컴포넌트와 동일한 파서로 다뤄
#   컴포넌트→스토어 inject 엣지(`useXStore()` 호출)를 잡는다. Vuex/Vue Router는 범위 밖.
# - 알려진 한계: `methods:`/`computed:` 블록 안 메서드 파라미터에 중첩 괄호(기본값에
#   함수 호출 등)가 있으면 시그니처 캡처가 깨질 수 있음(Depends() 같은 패턴은 이 블록에서는
#   드물어 Python만큼 치명적이지 않다고 보고 Phase 1에서는 감수). 템플릿(<template>) 자체는
#   분석하지 않는다(자식 컴포넌트 사용은 렌더링 그래프라 별개 확장 과제).
import os
import re
import sys
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from extractor_common import (
    walk_files, strip_noise, line_of, matching_brace, dedupe_edges, write_outputs, print_summary,
    BLOCK_COMMENT_RE, LINE_COMMENT_RE,
)

SCRIPT_BLOCK_RE = re.compile(r"<script([^>]*)>(.*?)</script>", re.DOTALL)
SINGLE_QUOTE_STRING_RE = re.compile(r"'(?:\\.|[^'\\\n])*'")
IMPORT_JS_RE = re.compile(r"^\s*import\s+(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
# 동적 import(라우트 lazy-load 관례: `import('@/views/' + code)` 처럼 변수 결합형은 여전히
# 판단이 필요하지만, 리터럴 경로(`import('./Foo.vue')`)는 기계적으로 확정 가능하다.
# 2026-08-19 실측: 이 프로젝트의 라우팅 핵심 로직이 전부 이 패턴이라 하나도 안 잡히고 있었다.
DYNAMIC_IMPORT_RE = re.compile(r"\bimport\s*\(\s*(['\"])([^'\"]+)\1\s*\)")
DEFINE_STORE_RE = re.compile(r"defineStore\s*\(")
JS_METHOD_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:async\s+)?(\w+)\s*:\s*(?:async\s+)?function\s*\(([^)]*)\)\s*\{"
    r"|(?:^|\n)[ \t]*(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{"
)
TOP_LEVEL_FN_RE = re.compile(r"(?:^|\n)(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*\{")
TOP_LEVEL_ARROW_RE = re.compile(r"(?:^|\n)(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>\s*\{")
USE_STORE_CALL_RE = re.compile(r"\b(use\w*Store)\s*\(\s*\)")

OBJECT_METHOD_KEYS = ("methods", "computed", "actions", "getters")


def _extra_strip(text):
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return SINGLE_QUOTE_STRING_RE.sub(blank, text)


def _strip_comments_only(text):
    """import 문의 따옴표 안 경로는 살려야 하므로, 문자열 리터럴은 안 지우고 주석만 지운다."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = BLOCK_COMMENT_RE.sub(blank, text)
    text = LINE_COMMENT_RE.sub(blank, text)
    return text


def _extract_object_block(text, key_name):
    m = re.search(rf"\b{key_name}\s*:\s*\{{", text)
    if not m:
        return None, None
    open_pos = m.end() - 1
    close_pos = matching_brace(text, open_pos)
    return text[open_pos + 1:close_pos], open_pos + 1


def _module_id(rel):
    rel = rel.replace("\\", "/")
    for ext in (".vue", ".js", ".ts", ".jsx", ".tsx"):
        if rel.endswith(ext):
            rel = rel[: -len(ext)]
            break
    return rel.replace("/", ".")


def _extract_methods_from_block(block_text, block_offset, raw_text, script_offset):
    methods = []
    for mm in JS_METHOD_RE.finditer(block_text):
        name = mm.group(1) or mm.group(3)
        params = mm.group(2) or mm.group(4) or ""
        rel_open = mm.end() - 1
        rel_close = matching_brace(block_text, rel_open)
        body = block_text[rel_open + 1:rel_close]
        abs_pos = script_offset + block_offset + mm.start()
        line = line_of(raw_text, abs_pos)
        methods.append({"name": name, "line": line, "signature": f"{name}({params.strip()})", "body": body})
    return methods


def _extract_top_level_functions(script_text, raw_text, script_offset):
    functions = []
    for rx in (TOP_LEVEL_FN_RE, TOP_LEVEL_ARROW_RE):
        for mm in rx.finditer(script_text):
            name, params = mm.group(1), mm.group(2)
            open_pos = mm.end() - 1
            close_pos = matching_brace(script_text, open_pos)
            body = script_text[open_pos + 1:close_pos]
            abs_pos = script_offset + mm.start()
            line = line_of(raw_text, abs_pos)
            functions.append({"name": name, "line": line, "signature": f"{name}({(params or '').strip()})", "body": body})
    return functions


def parse_file(path, rel):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()
    except OSError:
        return None

    is_vue = rel.endswith(".vue")
    if is_vue:
        sm = SCRIPT_BLOCK_RE.search(raw_text)
        if not sm:
            return None
        attrs, script_raw = sm.groups()
        script_offset = sm.start(2)
        is_setup = "setup" in (attrs or "")
    else:
        script_raw, script_offset, is_setup = raw_text, 0, True  # 순수 .js/.ts 스토어는 top-level 함수 취급

    script = _extra_strip(strip_noise(script_raw))
    script_for_imports = _strip_comments_only(script_raw)
    module = _module_id(rel)
    is_store = bool(DEFINE_STORE_RE.search(script))

    if is_store:
        node_kind = "store"
    elif is_vue:
        node_kind = "vue_view"
    else:
        node_kind = "module"

    imports = {}  # local_name -> src_path(원본, 아직 미해석)
    for m in IMPORT_JS_RE.finditer(script_for_imports):
        default_name, named_block, src_path = m.groups()
        if default_name:
            imports[default_name] = src_path
        for item in (named_block or "").split(","):
            item = item.strip()
            if not item:
                continue
            local = item.split(" as ")[-1].strip() if " as " in item else item
            imports[local] = src_path

    methods = []
    if is_setup or is_store:
        methods.extend(_extract_top_level_functions(script, raw_text, script_offset))
    for key in OBJECT_METHOD_KEYS:
        block, block_offset = _extract_object_block(script, key)
        if block:
            methods.extend(_extract_methods_from_block(block, block_offset, raw_text, script_offset))

    components_block, _ = _extract_object_block(script, "components")
    registered_components = []
    if components_block:
        for name in re.finditer(r"(\w+)\s*(?::\s*\w+)?\s*,?", components_block):
            n = name.group(1)
            if n:
                registered_components.append(n)

    store_uses = list(dict.fromkeys(USE_STORE_CALL_RE.findall(script)))
    dynamic_imports = [m.group(2) for m in DYNAMIC_IMPORT_RE.finditer(script_for_imports)]

    return {
        "id": module, "kind": node_kind, "file": rel, "line": 1,
        "imports": imports, "methods": methods,
        "registered_components": registered_components, "store_uses": store_uses,
        "dynamic_imports": dynamic_imports,
    }


def _resolve_path(current_rel, src_path):
    if src_path.startswith("."):
        current_dir = os.path.dirname(current_rel)
        joined = os.path.normpath(os.path.join(current_dir, src_path)).replace("\\", "/")
        return _module_id(joined)
    if src_path.startswith("@/"):
        rest = src_path[2:]
        return _module_id(rest), _module_id("src/" + rest)
    return None


def build_indexes(root):
    files = walk_files(root, ".vue") + [f for f in walk_files(root, ".js") if "defineStore" in open(f, encoding="utf-8", errors="ignore").read()] + \
        [f for f in walk_files(root, ".ts") if "defineStore" in open(f, encoding="utf-8", errors="ignore").read()]
    parsed = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        result = parse_file(path, rel)
        if result:
            parsed.append(result)

    by_id = {p["id"]: p for p in parsed}

    def resolve_import(current_rel, name, imports):
        src_path = imports.get(name)
        if not src_path:
            return None
        candidates = _resolve_path(current_rel, src_path)
        if candidates is None:
            return None
        if isinstance(candidates, tuple):
            for c in candidates:
                if c in by_id:
                    return c
            return None
        return candidates if candidates in by_id else None

    symbols, nodes, edges = [], [], []
    for p in parsed:
        method_syms = [{"name": m["name"], "id": f"{p['id']}.{m['name']}", "line": m["line"], "visibility": "public"} for m in p["methods"]]
        symbols.append({
            "id": p["id"], "type": p["kind"], "file": p["file"], "line": p["line"],
            "package": os.path.dirname(p["file"]).replace("/", "."), "extends": None, "implements": [],
            "annotations": [], "methods": method_syms,
        })
        nodes.append({
            "id": p["id"], "type": p["kind"], "file": p["file"], "line": p["line"],
            "visibility": "public", "static": False, "annotations": [], "signature": "",
        })
        for m in p["methods"]:
            nodes.append({
                "id": f"{p['id']}.{m['name']}", "type": "method", "file": p["file"], "line": m["line"],
                "visibility": "public", "static": False, "annotations": [], "signature": m["signature"],
            })

    for p in parsed:
        own_methods = {m["name"] for m in p["methods"]}

        for comp_name in p["registered_components"]:
            target = resolve_import(p["file"], comp_name, p["imports"])
            if target and target != p["id"]:
                edges.append({"from": p["id"], "to": target, "type": "import", "file": p["file"], "line": None})

        for store_fn in p["store_uses"]:
            target = resolve_import(p["file"], store_fn, p["imports"])
            if target and target != p["id"] and by_id.get(target, {}).get("kind") == "store":
                edges.append({"from": p["id"], "to": target, "type": "inject", "file": p["file"], "line": None})

        for imp_name, src_path in p["imports"].items():
            target = resolve_import(p["file"], imp_name, p["imports"])
            if target and target != p["id"]:
                edges.append({"from": p["id"], "to": target, "type": "import", "file": p["file"], "line": None})

        for src_path in p.get("dynamic_imports", []):
            candidates = _resolve_path(p["file"], src_path)
            if candidates is None:
                continue
            target = None
            if isinstance(candidates, tuple):
                for c in candidates:
                    if c in by_id:
                        target = c
                        break
            elif candidates in by_id:
                target = candidates
            if target and target != p["id"]:
                edges.append({"from": p["id"], "to": target, "type": "import", "file": p["file"], "line": None})

        for m in p["methods"]:
            for call_m in re.finditer(r"\bthis\s*\.\s*(\w+)\s*\(", m["body"]):
                called = call_m.group(1)
                if called in own_methods and called != m["name"]:
                    edges.append({"from": f"{p['id']}.{m['name']}", "to": f"{p['id']}.{called}", "type": "call", "file": p["file"], "line": None})
            for call_m in re.finditer(r"(?<![.\w])(\w+)\s*\(", m["body"]):
                called = call_m.group(1)
                if called in own_methods and called != m["name"]:
                    edges.append({"from": f"{p['id']}.{m['name']}", "to": f"{p['id']}.{called}", "type": "call", "file": p["file"], "line": None})
            for store_fn in p["store_uses"]:
                target = resolve_import(p["file"], store_fn, p["imports"])
                if target and by_id.get(target, {}).get("kind") == "store":
                    target_methods = {tm["name"] for tm in by_id[target]["methods"]}
                    for call_m in re.finditer(r"\.(\w+)\s*\(", m["body"]):
                        called = call_m.group(1)
                        if called in target_methods:
                            edges.append({"from": f"{p['id']}.{m['name']}", "to": f"{target}.{called}", "type": "call", "file": p["file"], "line": None})

    return symbols, nodes, dedupe_edges(edges), len(parsed), len(files)


def main():
    parser = argparse.ArgumentParser(description="Vue 2/3(+Pinia) symbols.json + call_graph.json 기계 추출 (LLM 미사용)")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    symbols, nodes, edges, files_scanned, files_total = build_indexes(args.root)
    write_outputs(args.root, "index_extractor_vue", symbols, nodes, edges, files_scanned, files_total)
    print_summary(symbols, nodes, edges, files_scanned, files_total)


if __name__ == "__main__":
    main()
