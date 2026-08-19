# Android/Kotlin 프로젝트의 symbols.json + call_graph.json을 정규식 기반으로
# 기계 추출한다 (LLM 미사용). Phase 1 범위: Kotlin 소스의 class/method/상속/import/
# Hilt `@Inject constructor` DI만 — Android nav_graph.xml(리소스 XML) 네비게이션
# 그래프·Activity/Fragment 생명주기 세부(단순 메서드로만 취급)는 범위 밖.
#
# Java/C#과 다른 점: Kotlin은 클래스 헤더 자체에 "1차 생성자"가 올 수 있다
# (`class Foo @Inject constructor(private val repo: OrderRepository) : ViewModel()`).
# 상속 목록의 각 항목도 `SuperClass(args)`처럼 생성자 호출 괄호를 가질 수 있어(Java의
# `extends X`는 괄호가 없음), 콤마 분리·본문 시작 중괄호 탐색 모두 괄호 깊이를 감안해야 한다.
# 필드 주입(`@Inject lateinit var x: Type`)도 지원. 알려진 한계: 본문 없는 한 줄짜리
# data class(`data class Foo(val x: Int)`)는 메서드 없이 클래스 노드만 등록.
import os
import re
import sys
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from extractor_common import (
    walk_files, strip_noise, line_of, annotations_before, matching_brace,
    simple_type, dedupe_edges, write_outputs, print_summary,
)

PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)(\.\*)?\s*$", re.MULTILINE)
CLASS_HEAD_RE = re.compile(r"(?:^|\n)([ \t]*)(?:(?:open|abstract|final|sealed|data|internal|private|public)\s+)*(class|interface|object)\s+(\w+)")
FUN_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:private|protected|public|internal)?\s*(?:open\s+|override\s+|abstract\s+|suspend\s+)*"
    r"fun\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*[\w<>\[\],.?]+)?\s*\{"
)
PROPERTY_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:private|protected|public|internal)?\s*(?:lateinit\s+)?(?:val|var)\s+(\w+)\s*:\s*([\w<>\[\],.?]+)"
)
ANNOTATION_LINE_RE = re.compile(r"@(\w+)(?:\([^)]*\))?")
# Spring-on-Kotlin은 Hilt처럼 생성자에 @Inject를 붙이지 않고, 클래스에 스프링 스테레오타입
# 애노테이션만 있으면 1차 생성자를 그대로 오토와이어링한다(2026-08-19 추가, C#의 "애노테이션
# 없이도 생성자 파라미터 = 주입 대상" 관례와 동일 논리).
SPRING_STEREOTYPE_ANNOTATIONS = ("@Service", "@Component", "@Repository", "@Controller", "@RestController", "@Configuration")


def _kt_annotations_before(text, pos):
    return annotations_before(text, pos, ANNOTATION_LINE_RE, format_fn=lambda m: f"@{m.group(1)}")


def _kt_simple_type(raw):
    return simple_type(raw.strip().rstrip("?").strip())


def _matching_paren(text, open_idx):
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def _split_depth_aware(raw):
    """콤마로 나누되 (), [], <> 어느 것이든 깊이를 존중한다 — Kotlin의 상속 목록·생성자
    파라미터에 둘 다 섞여 나올 수 있어서다."""
    if not raw:
        return []
    parts, buf, depth = [], "", 0
    for ch in raw:
        if ch in "([<":
            depth += 1
        elif ch in ")]>":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return [p for p in parts if p]


def _find_class_open_brace(text, start):
    """start부터 괄호 깊이를 세며 깊이 0인 첫 '{'를 찾는다. 깊이 0에서 줄바꿈을 만나면
    본문 없는 한 줄 선언(data class 등)으로 보고 None을 반환한다."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "{" and depth <= 0:
            return i
        elif c == "\n" and depth <= 0:
            return None
        i += 1
    return None


def parse_file(path, rel):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()
    except OSError:
        return None

    text = strip_noise(raw_text)
    pkg_m = PACKAGE_RE.search(text)
    package = pkg_m.group(1) if pkg_m else ""
    imports = [m.group(1) for m in IMPORT_RE.finditer(text) if not m.group(2)]

    classes = []
    for cm in CLASS_HEAD_RE.finditer(text):
        kind, name = cm.group(2), cm.group(3)
        pos = cm.end()

        # 1차 생성자: 선택적 @Annotation + 선택적 constructor 키워드 + 선택적 (params)
        ctor_annotations = []
        m_at = re.match(r"\s*@(\w+)\s+", text[pos:])
        if m_at:
            ctor_annotations.append(f"@{m_at.group(1)}")
            pos += m_at.end()
        m_ctor_kw = re.match(r"\s*constructor\s*", text[pos:])
        if m_ctor_kw:
            pos += m_ctor_kw.end()
        skip_ws = re.match(r"\s*", text[pos:])
        pos += skip_ws.end()
        ctor_params_raw = None
        if pos < len(text) and text[pos] == "(":
            close = _matching_paren(text, pos)
            ctor_params_raw = text[pos + 1:close]
            pos = close + 1

        # 상속 목록: ` : Base(args), Interface`
        bases = []
        after_ctor = text[pos:]
        colon_m = re.match(r"\s*:\s*", after_ctor)
        if colon_m:
            colon_start = pos + colon_m.end()
            open_brace = _find_class_open_brace(text, colon_start)
            bases_text = text[colon_start:open_brace] if open_brace else text[colon_start:colon_start + 300]
            for b in _split_depth_aware(bases_text):
                b = re.sub(r"\(.*\)$", "", b).strip()
                if b:
                    bases.append(_kt_simple_type(b))
        else:
            open_brace = _find_class_open_brace(text, pos)

        class_id = f"{package}.{name}" if package else name
        annotations = _kt_annotations_before(text, cm.start())
        line = line_of(raw_text, cm.start(1))

        methods = []
        fields = {}
        if open_brace is not None:
            body_end = matching_brace(text, open_brace)
            body = text[open_brace + 1:body_end]
            body_offset = open_brace + 1

            for fm in FUN_RE.finditer(body):
                f_name, params = fm.groups()
                f_line = line_of(raw_text, body_offset + fm.start())
                f_anns = _kt_annotations_before(body, fm.start())
                f_open = fm.end() - 1
                f_close = matching_brace(body, f_open)
                f_body = body[f_open + 1:f_close]
                methods.append({
                    "name": f_name, "line": f_line, "annotations": f_anns,
                    "signature": f"fun {f_name}({params.strip()})", "body": f_body,
                })

            for pm in PROPERTY_RE.finditer(body):
                p_name, p_type = pm.groups()
                p_anns = _kt_annotations_before(body, pm.start())
                fields[p_name] = {"type": _kt_simple_type(p_type), "annotations": p_anns}

        # 1차 생성자의 val/var 파라미터는 Kotlin에서 자동으로 프로퍼티가 된다 — 본문의
        # PROPERTY_RE만으로는 못 잡으므로 여기서 fields에 합류시켜야 호출 탐지(x.method())가
        # 이 프로퍼티를 통한 호출도 잡을 수 있다. @Inject 주입 여부와는 별개로 항상 등록한다.
        constructor_injected_types = []
        if ctor_params_raw:
            for param in _split_depth_aware(ctor_params_raw):
                is_property = bool(re.match(r"\s*(?:private|protected|public|internal)?\s*(val|var)\s+", param))
                stripped = param
                for _ in range(2):
                    stripped = re.sub(r"^(private|protected|public|internal|val|var)\s+", "", stripped).strip()
                if ":" not in stripped:
                    continue
                p_name, _, type_part = stripped.partition(":")
                p_name = p_name.strip()
                type_part = type_part.split("=")[0].strip()
                resolved_type = _kt_simple_type(type_part)
                if is_property and p_name:
                    fields.setdefault(p_name, {"type": resolved_type, "annotations": []})
                if "@Inject" in ctor_annotations or any(a in annotations for a in SPRING_STEREOTYPE_ANNOTATIONS):
                    constructor_injected_types.append(resolved_type)

        classes.append({
            "id": class_id, "name": name, "kind": kind, "package": package, "file": rel, "line": line,
            "annotations": annotations, "bases_raw": bases, "methods": methods, "fields": fields,
            "constructor_injected_types": constructor_injected_types,
        })

    return {"package": package, "imports": imports, "classes": classes}


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
    files = walk_files(root, ".kt")
    parsed = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        result = parse_file(path, rel)
        if result:
            parsed.append(result)

    by_id, by_simple = {}, {}
    for p in parsed:
        for c in p["classes"]:
            by_id[c["id"]] = c
            by_simple.setdefault(c["name"], []).append(c["id"])

    symbols, nodes, edges = [], [], []
    for p in parsed:
        for c in p["classes"]:
            method_syms = [{"name": m["name"], "id": f"{c['id']}.{m['name']}", "line": m["line"], "visibility": "public"} for m in c["methods"]]
            symbols.append({
                "id": c["id"], "type": c["kind"], "file": c["file"], "line": c["line"], "package": c["package"],
                "extends": c["bases_raw"][0] if c["bases_raw"] else None, "implements": c["bases_raw"][1:],
                "annotations": c["annotations"], "methods": method_syms,
            })
            node_type = "class" if c["kind"] == "class" else c["kind"]
            nodes.append({
                "id": c["id"], "type": node_type, "file": c["file"], "line": c["line"],
                "visibility": "public", "static": False, "annotations": c["annotations"], "signature": "",
            })
            for m in c["methods"]:
                nodes.append({
                    "id": f"{c['id']}.{m['name']}", "type": "method", "file": c["file"], "line": m["line"],
                    "visibility": "public", "static": False, "annotations": m["annotations"], "signature": m["signature"],
                })

    for p in parsed:
        for c in p["classes"]:
            for base in c["bases_raw"]:
                target = _resolve(base, p["imports"], p["package"], by_id, by_simple)
                if target:
                    edges.append({"from": c["id"], "to": target, "type": "inherit", "file": c["file"], "line": c["line"]})

            injected_type_names = list(c["constructor_injected_types"])
            for f_name, f_info in c["fields"].items():
                if "@Inject" in f_info["annotations"] or "@Resource" in f_info["annotations"] or "@Autowired" in f_info["annotations"]:
                    injected_type_names.append(f_info["type"])
            for type_name in injected_type_names:
                target = _resolve(type_name, p["imports"], p["package"], by_id, by_simple)
                if target and target != c["id"]:
                    edges.append({"from": c["id"], "to": target, "type": "inject", "file": c["file"], "line": c["line"]})

            for imp in p["imports"]:
                if imp in by_id and imp != c["id"]:
                    edges.append({"from": c["id"], "to": imp, "type": "import", "file": c["file"], "line": None})

            field_types = {name: info["type"] for name, info in c["fields"].items()}
            resolved_field_targets = {}
            for f_name, f_type in field_types.items():
                target_cls = _resolve(f_type, p["imports"], p["package"], by_id, by_simple)
                if target_cls and target_cls in by_id:
                    resolved_field_targets[f_name] = target_cls

            own_methods = {m["name"] for m in c["methods"]}
            for m in c["methods"]:
                m_body = m["body"]
                for f_name, target_cls in resolved_field_targets.items():
                    target_methods = {tm["name"] for tm in by_id[target_cls]["methods"]}
                    for call_m in re.finditer(rf"\b{re.escape(f_name)}\s*\.\s*(\w+)\s*\(", m_body):
                        called = call_m.group(1)
                        if called in target_methods:
                            edges.append({"from": f"{c['id']}.{m['name']}", "to": f"{target_cls}.{called}", "type": "call", "file": c["file"], "line": None})
                for call_m in re.finditer(r"\bthis\s*\.\s*(\w+)\s*\(", m_body):
                    called = call_m.group(1)
                    if called in own_methods and called != m["name"]:
                        edges.append({"from": f"{c['id']}.{m['name']}", "to": f"{c['id']}.{called}", "type": "call", "file": c["file"], "line": None})

    return symbols, nodes, dedupe_edges(edges), len(parsed), len(files)


def main():
    parser = argparse.ArgumentParser(description="Android/Kotlin symbols.json + call_graph.json 기계 추출 (LLM 미사용)")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    symbols, nodes, edges, files_scanned, files_total = build_indexes(args.root)
    write_outputs(args.root, "index_extractor_kotlin", symbols, nodes, edges, files_scanned, files_total)
    print_summary(symbols, nodes, edges, files_scanned, files_total)


if __name__ == "__main__":
    main()
