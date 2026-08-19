# C#/.NET 프로젝트의 symbols.json + call_graph.json을 정규식 기반으로 기계 추출한다 (LLM 미사용).
# index_extractor_java_spring.py와 구조는 같으나 두 가지가 다르다:
# (1) 애노테이션이 @Name이 아니라 [Name] — extractor_common.annotations_before의 marker_re만 교체.
# (2) DI 관례가 다르다 — Spring은 @Autowired로 "주입 생성자"를 명시하지만, ASP.NET Core는
#     명시적 애노테이션 없이 생성자 파라미터 자체가 곧 DI 컨테이너가 주입하는 대상이다.
#     그래서 이 스크립트는 @Autowired 유무를 따지지 않고 모든 생성자의 파라미터를
#     주입 후보로 취급한다(프로젝트 내부 타입으로 해석될 때만 엣지 생성 — 과다 추정 방지).
# 범위(Phase 1 C#): extends/implements는 C#에서 콜론 뒤 한 목록으로 합쳐져 있어 문법상
# 구분 불가 — 첫 번째로 project-internal "class" kind로 해석되는 항목만 extends로,
# 나머지는 implements로 간주한다(베스트에포트).
# ASP.NET MVC Razor 뷰(.cshtml) 지원: .cshtml 파일을 "view" 노드로 추가하고, Controller
# Action의 return View(...) 호출을 "render" 엣지로, 뷰의 @model 선언을 "import" 엣지로
# 연결한다. 범위 밖(만들지 않음): 마크업 내 클릭 핸들러 등 "trigger" 노드, Areas 구조,
# Razor Pages PageModel(.cshtml.cs code-behind) — Controller 판별 조건에 안 걸려 자연히 스킵됨.
import os
import re
import sys
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from extractor_common import (
    walk_files, strip_noise, line_of, annotations_before, matching_brace,
    split_type_list, simple_type, dedupe_edges, write_outputs, print_summary,
)

NAMESPACE_BLOCK_RE = re.compile(r"^\s*namespace\s+([\w.]+)\s*\{", re.MULTILINE)
NAMESPACE_FILESCOPED_RE = re.compile(r"^\s*namespace\s+([\w.]+)\s*;", re.MULTILINE)
USING_RE = re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)

CLASS_DECL_RE = re.compile(
    r"(?:^|\n)[ \t]*(public|private|internal|protected)?\s*(?:static\s+)?(?:abstract\s+)?(?:sealed\s+)?(?:partial\s+)?"
    r"(class|interface|struct)\s+(\w+)"
    r"(?:\s*<[^{:]*?>)?"
    r"(?:\s*:\s*([\w.<>,\s]+?))?"
    r"\s*\{"
)

METHOD_DECL_RE = re.compile(
    r"(?:^|\n)[ \t]*(public|private|internal|protected)?\s*(static\s+)?(?:virtual\s+|override\s+|abstract\s+|sealed\s+)*"
    r"(?:async\s+)?"
    r"(?:<[\w,\s]+>\s*)?"
    r"([\w<>\[\],.\s]+?)\s+(\w+)\s*\(([^)]*)\)\s*(?:where\s+[\w.,:\s]+)?\s*[{;]"
)

FIELD_DECL_RE = re.compile(
    r"(?:^|\n)[ \t]*(public|private|internal|protected)?\s*(?:static\s+)?(?:readonly\s+)?"
    r"([\w<>\[\],.]+)\s+(\w+)\s*(?:=[^;]*)?;"
)

ATTR_LINE_RE = re.compile(r"\[(\w+)(?:\([^\]]*\))?\]")

# Razor .cshtml 지원용 — raw_text(strip_noise 미적용)에 직접 적용한다.
RETURN_VIEW_RE = re.compile(r"return\s+View\s*\(\s*(?:\"([^\"]*)\")?")
# [\s]는 개행을 포함해 다음 줄 마크업까지 캡처하므로(@model Foo\n<h1>...) 같은 줄로 제한한다.
MODEL_DIRECTIVE_RE = re.compile(r"^\s*@model[ \t]+([\w.<>,\[\] \t]+)", re.MULTILINE)


def _cs_annotations_before(text, pos):
    return annotations_before(text, pos, ATTR_LINE_RE, format_fn=lambda m: f"[{m.group(1)}]")


def parse_file(path, rel):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()
    except OSError:
        return None

    text = strip_noise(raw_text)

    ns_m = NAMESPACE_BLOCK_RE.search(text)
    namespace = ns_m.group(1) if ns_m else None
    if not namespace:
        ns_m2 = NAMESPACE_FILESCOPED_RE.search(text)
        namespace = ns_m2.group(1) if ns_m2 else ""

    usings = [m.group(1) for m in USING_RE.finditer(text)]

    classes = []
    for cm in CLASS_DECL_RE.finditer(text):
        visibility, kind, name, bases_raw = cm.groups()
        brace_pos = text.index("{", cm.end() - 1)
        body_end = matching_brace(text, brace_pos)
        body = text[brace_pos + 1:body_end]
        body_offset = brace_pos + 1

        class_id = f"{namespace}.{name}" if namespace else name
        annotations = _cs_annotations_before(text, cm.start())
        line = line_of(raw_text, cm.start())
        bases = [simple_type(t) for t in split_type_list(bases_raw)]

        methods = []
        for mm in METHOD_DECL_RE.finditer(body):
            m_vis, m_static, ret_type, m_name, params = mm.groups()
            if m_name == name:
                continue  # 생성자 — 별도 처리(주입 탐지용)
            if ret_type and ret_type.strip() in ("class", "interface", "struct", "new", "namespace"):
                continue
            m_line = line_of(raw_text, body_offset + mm.start())
            m_anns = _cs_annotations_before(body, mm.start())
            m_body = ""
            raw_body = ""
            if body[mm.end() - 1] == "{":
                m_body_end = matching_brace(body, mm.end() - 1)
                m_body = body[mm.end():m_body_end]
                # raw_body: strip_noise 미적용 원본 슬라이스 — return View("Name")의 문자열
                # 인자가 strip_noise에 공백 치환되기 전 상태로 필요할 때(뷰 이름 감지) 쓴다.
                raw_body = raw_text[body_offset + mm.end():body_offset + m_body_end]
            methods.append({
                "name": m_name,
                "line": m_line,
                "visibility": m_vis or "internal",
                "static": bool(m_static),
                "annotations": m_anns,
                "signature": f"{(ret_type or '').strip()} {m_name}({params.strip()})".strip(),
                "body": m_body,
                "raw_body": raw_body,
            })

        fields = {}
        for fm in FIELD_DECL_RE.finditer(body):
            f_vis, f_type, f_name = fm.groups()
            if f_type in ("class", "return", "new", "void"):
                continue
            f_anns = _cs_annotations_before(body, fm.start())
            fields[f_name] = {"type": simple_type(f_type), "annotations": f_anns}

        # 생성자 주입: ASP.NET Core 관례상 애노테이션 없이도 생성자 파라미터 = 주입 대상.
        # 명시적 [Inject] 필드도 함께 후보에 포함.
        constructor_injected_types = []
        ctor_re = re.compile(rf"(?:^|\n)[ \t]*(?:public|private|protected|internal)?\s*{re.escape(name)}\s*\(([^)]*)\)\s*\{{")
        for cm2 in ctor_re.finditer(body):
            for param in split_type_list(cm2.group(1)):
                param = param.strip()
                if not param:
                    continue
                tokens = param.split()
                if len(tokens) >= 2:
                    constructor_injected_types.append(simple_type(tokens[-2]))

        classes.append({
            "id": class_id,
            "name": name,
            "kind": kind,
            "package": namespace,
            "file": rel,
            "line": line,
            "visibility": visibility or "internal",
            "annotations": annotations,
            "bases_raw": bases,
            "methods": methods,
            "fields": fields,
            "constructor_injected_types": constructor_injected_types,
        })

    return {"package": namespace, "imports": usings, "classes": classes}


def parse_view_file(path, rel):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()
    except OSError:
        return None
    model_m = MODEL_DIRECTIVE_RE.search(raw_text)
    model_simple_name = simple_type(model_m.group(1)) if model_m else None
    return {"rel": rel, "model_simple_name": model_simple_name}


def _extract_views(root):
    files = walk_files(root, ".cshtml")
    views = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        v = parse_view_file(path, rel)
        if v:
            views.append(v)
    return views, len(files)


def _resolve(simple_name, importer_imports, importer_package, by_id, by_simple):
    if not simple_name:
        return None
    for imp in importer_imports:
        if imp.endswith("." + simple_name) or imp == simple_name:
            if imp in by_id:
                return imp
    same_pkg = f"{importer_package}.{simple_name}" if importer_package else simple_name
    if same_pkg in by_id:
        return same_pkg
    candidates = by_simple.get(simple_name) or []
    if len(candidates) == 1:
        return candidates[0]
    return None


def build_indexes(root):
    files = walk_files(root, ".cs")
    parsed = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        result = parse_file(path, rel)
        if result:
            parsed.append(result)

    views, view_file_count = _extract_views(root)
    view_by_rel_lower = {v["rel"].lower(): v for v in views}

    by_id = {}
    by_simple = {}
    for p in parsed:
        for c in p["classes"]:
            by_id[c["id"]] = c
            by_simple.setdefault(c["name"], []).append(c["id"])

    symbols = []
    nodes = []
    edges = []

    for p in parsed:
        for c in p["classes"]:
            # extends/implements 구분: 콜론 목록 중 project-internal이고 kind=="class"인
            # 첫 항목만 extends, 나머지(인터페이스 포함 미해석 항목)는 implements로 취급.
            extends = None
            implements = []
            for base in c["bases_raw"]:
                target = _resolve(base, p["imports"], p["package"], by_id, by_simple)
                if extends is None and target and by_id.get(target, {}).get("kind") == "class":
                    extends = base
                else:
                    implements.append(base)

            method_syms = [
                {"name": m["name"], "id": f"{c['id']}.{m['name']}", "line": m["line"], "visibility": m["visibility"]}
                for m in c["methods"]
            ]
            symbols.append({
                "id": c["id"], "type": c["kind"], "file": c["file"], "line": c["line"],
                "package": c["package"], "extends": extends, "implements": implements,
                "annotations": c["annotations"], "methods": method_syms,
            })

            node_type = "class" if c["kind"] == "class" else c["kind"]
            nodes.append({
                "id": c["id"], "type": node_type, "file": c["file"], "line": c["line"],
                "visibility": c["visibility"], "static": False, "annotations": c["annotations"],
                "signature": "",
            })
            for m in c["methods"]:
                nodes.append({
                    "id": f"{c['id']}.{m['name']}", "type": "method", "file": c["file"], "line": m["line"],
                    "visibility": m["visibility"], "static": m["static"], "annotations": m["annotations"],
                    "signature": m["signature"],
                })

    for v in views:
        view_id = f"view:{v['rel']}"
        symbols.append({
            "id": view_id, "type": "view", "file": v["rel"], "line": 1,
            "package": None, "extends": None, "implements": [], "annotations": [], "methods": [],
        })
        nodes.append({
            "id": view_id, "type": "view", "file": v["rel"], "line": 1,
            "visibility": "", "static": False, "annotations": [], "signature": "",
        })

    for p in parsed:
        for c in p["classes"]:
            for base in c["bases_raw"]:
                target = _resolve(base, p["imports"], p["package"], by_id, by_simple)
                if target:
                    edges.append({"from": c["id"], "to": target, "type": "inherit", "file": c["file"], "line": c["line"]})

            injected_type_names = list(c["constructor_injected_types"])
            for f_name, f_info in c["fields"].items():
                if "[Inject]" in f_info["annotations"]:
                    injected_type_names.append(f_info["type"])
            for type_name in injected_type_names:
                target = _resolve(type_name, p["imports"], p["package"], by_id, by_simple)
                if target and target != c["id"]:
                    edges.append({"from": c["id"], "to": target, "type": "inject", "file": c["file"], "line": c["line"]})

            # import: C#의 using은 클래스 하나가 아니라 네임스페이스 전체를 가져온다
            # (Java의 import a.b.ClassName;과 다름) — 그래서 "using 목록에 있는 대상"이
            # 아니라 "실제로 참조가 해석됐는데 네임스페이스가 다른 대상"을 import로 취급한다.
            field_types = {name: info["type"] for name, info in c["fields"].items()}
            resolved_field_targets = {}
            for f_name, f_type in field_types.items():
                target_cls = _resolve(f_type, p["imports"], p["package"], by_id, by_simple)
                if target_cls and target_cls in by_id:
                    resolved_field_targets[f_name] = target_cls

            cross_ns_targets = set()
            for base in c["bases_raw"]:
                t = _resolve(base, p["imports"], p["package"], by_id, by_simple)
                if t:
                    cross_ns_targets.add(t)
            for type_name in injected_type_names:
                t = _resolve(type_name, p["imports"], p["package"], by_id, by_simple)
                if t:
                    cross_ns_targets.add(t)
            for t in resolved_field_targets.values():
                cross_ns_targets.add(t)
            for target in cross_ns_targets:
                if target != c["id"] and by_id.get(target, {}).get("package") != c["package"]:
                    edges.append({"from": c["id"], "to": target, "type": "import", "file": c["file"], "line": None})

            own_methods = {m["name"] for m in c["methods"]}
            for m in c["methods"]:
                m_body = m["body"]
                if not m_body:
                    continue
                for f_name, target_cls in resolved_field_targets.items():
                    target_methods = {tm["name"] for tm in by_id[target_cls]["methods"]}
                    for call_m in re.finditer(rf"\b{re.escape(f_name)}\s*\.\s*(\w+)\s*\(", m_body):
                        called = call_m.group(1)
                        if called in target_methods:
                            edges.append({
                                "from": f"{c['id']}.{m['name']}", "to": f"{target_cls}.{called}",
                                "type": "call", "file": c["file"], "line": None,
                            })
                for call_m in re.finditer(r"\bthis\s*\.\s*(\w+)\s*\(", m_body):
                    called = call_m.group(1)
                    if called in own_methods and called != m["name"]:
                        edges.append({
                            "from": f"{c['id']}.{m['name']}", "to": f"{c['id']}.{called}",
                            "type": "call", "file": c["file"], "line": None,
                        })

            # ASP.NET MVC Controller Action -> View render 엣지. Controller가 아니면 스킵
            # (오탐 방지 — 아래 두 조건 다 아니면 Action 탐지 자체를 안 함).
            is_controller = c["name"].endswith("Controller") or any(
                b in ("Controller", "ControllerBase") for b in c["bases_raw"]
            )
            if is_controller:
                controller_name = c["name"]
                if controller_name.endswith("Controller"):
                    controller_name = controller_name[: -len("Controller")]
                for m in c["methods"]:
                    view_m = RETURN_VIEW_RE.search(m.get("raw_body", ""))
                    if not view_m:
                        continue
                    view_name = view_m.group(1) or m["name"]
                    candidates = [
                        f"Views/{controller_name}/{view_name}.cshtml",
                        f"Views/Shared/{view_name}.cshtml",
                    ]
                    target_view = None
                    for cand in candidates:
                        target_view = view_by_rel_lower.get(cand.lower())
                        if target_view:
                            break
                    if target_view:
                        edges.append({
                            "from": f"{c['id']}.{m['name']}", "to": f"view:{target_view['rel']}",
                            "type": "render", "file": c["file"], "line": m["line"],
                        })
                    # 후보 경로에 실존 파일 없으면 엣지 생성 스킵 — 추측 노드 생성 금지.

    # View(@model) -> Model 클래스 import 엣지.
    for v in views:
        if not v.get("model_simple_name"):
            continue
        target = by_simple.get(v["model_simple_name"]) or []
        if len(target) == 1:
            edges.append({
                "from": f"view:{v['rel']}", "to": target[0], "type": "import", "file": v["rel"], "line": None,
            })
        # 후보 0개(미해석) 또는 2개 이상(모호)이면 스킵 — _resolve()와 동일한 원칙.

    return symbols, nodes, dedupe_edges(edges), len(parsed) + len(views), len(files) + view_file_count


def main():
    parser = argparse.ArgumentParser(description="C#/.NET symbols.json + call_graph.json 기계 추출 (LLM 미사용)")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    symbols, nodes, edges, files_scanned, files_total = build_indexes(args.root)
    write_outputs(args.root, "index_extractor_csharp", symbols, nodes, edges, files_scanned, files_total)
    print_summary(symbols, nodes, edges, files_scanned, files_total)


if __name__ == "__main__":
    main()
