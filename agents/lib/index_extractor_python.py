# Python(FastAPI/Django/Flask) 프로젝트의 symbols.json + call_graph.json을 정규식 기반으로
# 기계 추출한다 (LLM 미사용). Java/C#과 달리 중괄호가 없어 블록 경계를 들여쓰기로 판정한다.
#
# Java/C#과의 구조적 차이:
# - 클래스뿐 아니라 모듈 최상위 함수도 노드로 만든다 — FastAPI/Flask 라우트 핸들러는
#   클래스 없이 함수로 정의되는 경우가 흔해, 클래스만 다루면 실사용 코드의 대부분을 놓친다.
# - DI 관례가 프레임워크 셋 안에서도 갈린다: FastAPI는 `Depends(x)`가 명시적 신호,
#   Django/Flask는 관례상 DI 컨테이너가 없어 타입힌트 기반 생성자 주입만 후보로 취급한다.
# - import 해석은 `from X.Y import Name` 형태만 다룬다(가장 흔한 패턴) — `import X.Y.Z` 전체
#   모듈 임포트는 이번 범위 밖(사용 시 `X.Y.Z.attr` 형태라 필드/호출 탐지가 더 필요해짐).
# - 알려진 한계: 데코레이터·타입힌트가 여러 줄에 걸치면 인식 못함, 중첩 함수/중첩 클래스도
#   Java의 inner class와 같은 이유로 바깥 스코프 스캔에 섞여 들어갈 수 있음.
import os
import re
import sys
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from extractor_common import walk_files, line_of, dedupe_edges, write_outputs, print_summary

TRIPLE_DQ_RE = re.compile(r'""".*?"""', re.DOTALL)
TRIPLE_SQ_RE = re.compile(r"'''.*?'''", re.DOTALL)
STRING_DQ_RE = re.compile(r'"(?:\\.|[^"\\\n])*"')
STRING_SQ_RE = re.compile(r"'(?:\\.|[^'\\\n])*'")
LINE_COMMENT_RE = re.compile(r"#[^\n]*")

# 시그니처 캡처는 정규식 한 줄짜리로는 안 됨 — Depends(x)처럼 파라미터 기본값에 괄호가
# 들어가거나(닫는 괄호가 함수 자신의 것보다 먼저 나옴) 여러 줄에 걸친 시그니처가 흔해서,
# 여는 지점만 정규식으로 찾고 실제 닫는 괄호는 _matching_paren()으로 깊이 계산한다.
CLASS_HEAD_RE = re.compile(r"(?:^|\n)([ \t]*)class\s+(\w+)")
DEF_HEAD_RE = re.compile(r"(?:^|\n)([ \t]*)(?:async\s+)?def\s+(\w+)")
DECORATOR_LINE_RE = re.compile(r"^(\s*)@([\w.]+)(?:\(([^)]*)\))?\s*$")
IMPORT_FROM_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+)$")
DEPENDS_RE = re.compile(r"Depends\(\s*(\w+)\s*\)")
INIT_ASSIGN_RE = re.compile(r"self\.(\w+)\s*=\s*(\w+)\s*\(")


def _strip_noise_py(text):
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = TRIPLE_DQ_RE.sub(blank, text)
    text = TRIPLE_SQ_RE.sub(blank, text)
    text = STRING_DQ_RE.sub(blank, text)
    text = STRING_SQ_RE.sub(blank, text)
    text = LINE_COMMENT_RE.sub(blank, text)
    return text


def _indent(line):
    return len(line) - len(line.lstrip())


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


def _block_end(lines, header_indent, scan_start_idx):
    """header_indent(원래 class/def 키워드 줄의 들여쓰기) 대비 더 깊게 들여쓴 줄들의
    끝(제외 경계, 0-based)을 scan_start_idx부터 찾는다. 빈 줄은 경계 판정에서 건너뛴다."""
    i = scan_start_idx
    while i < len(lines):
        if lines[i].strip() == "":
            i += 1
            continue
        if _indent(lines[i]) <= header_indent:
            return i
        i += 1
    return len(lines)


def _scan_signature(text, head_match):
    """head_match(CLASS_HEAD_RE 또는 DEF_HEAD_RE)의 끝 위치부터 괄호(있으면) 안쪽 내용과
    블록을 여는 콜론의 위치를 찾는다. class에 베이스가 없으면 content는 None."""
    pos = head_match.end()
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    if pos < len(text) and text[pos] == "(":
        close = _matching_paren(text, pos)
        content = text[pos + 1:close]
        pos = close + 1
    else:
        content = None
    colon_pos = text.index(":", pos)
    return content, colon_pos


def _decorators_before(lines, header_idx):
    decos = []
    i = header_idx - 1
    while i >= 0:
        if lines[i].strip() == "":
            i -= 1
            continue
        m = DECORATOR_LINE_RE.match(lines[i])
        if not m:
            break
        decos.insert(0, "@" + m.group(2))
        i -= 1
    return decos


def _module_id(rel):
    rel = rel.replace("\\", "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    parts = rel.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else rel


def _split_type_hints(params_str):
    """파라미터 문자열에서 'name: Type' 힌트가 있는 것만 {name: Type} 로 반환.
    self/cls, 기본값(=...) 유무는 무시하고 타입힌트만 뽑는다."""
    result = {}
    depth = 0
    buf = ""
    parts = []
    for ch in params_str:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    for part in parts:
        part = part.split("=")[0].strip()
        if ":" not in part:
            continue
        name, _, type_hint = part.partition(":")
        name = name.strip()
        if name in ("self", "cls") or not name:
            continue
        type_hint = type_hint.strip()
        type_hint = re.sub(r"\[.*\]", "", type_hint).strip()
        if type_hint:
            result[name] = type_hint.split(".")[-1]
    return result


def parse_file(path, rel):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw_text = f.read()
    except OSError:
        return None

    text = _strip_noise_py(raw_text)
    lines = text.split("\n")
    module = _module_id(rel)

    def _header_line_idx(m):
        # group(1)은 (?:^|\n) 다음 위치라 항상 해당 줄 내부를 가리킨다 — line_of에 안전하게 쓸 수 있다.
        return line_of(raw_text, m.start(1)) - 1

    imports = {}  # 지역명 -> "module.Name" 후보
    for line in lines:
        m = IMPORT_FROM_RE.match(line)
        if not m:
            continue
        src_module, names_part = m.groups()
        for item in names_part.split(","):
            item = item.strip()
            if not item:
                continue
            name = item.split(" as ")[0].strip()
            if name and name != "*":
                imports[name] = f"{src_module}.{name}"

    classes = []
    class_body_ranges = []  # (header_line_idx, body_end_idx) — 최상위 함수 스캔에서 클래스 내부 제외용
    for cm in CLASS_HEAD_RE.finditer(text):
        name = cm.group(2)
        header_idx = _header_line_idx(cm)
        header_indent = _indent(lines[header_idx])
        bases_str, colon_pos = _scan_signature(text, cm)
        colon_line_idx = line_of(raw_text, colon_pos) - 1
        body_end = _block_end(lines, header_indent, colon_line_idx + 1)

        # 중첩 클래스(예: pydantic의 nested `class Config:`)는 module.name만 쓰면 같은 파일 안
        # 다른 클래스에 붙은 동명 nested class와 id가 충돌한다(mfs-test3에서 실제 발생 —
        # backend.app.schemas.schemas.Config가 3개 클래스에 걸쳐 동일 id로 뭉쳐짐, vis.DataSet이
        # id 중복에 예외를 던져 call-graph.html 전체가 렌더링 안 됨, 2026-08-05 확인). 이미 기록된
        # class_body_ranges 중 이 헤더를 감싸는 것 중 가장 안쪽(가장 늦게 시작한) 것을 부모로 삼는다.
        enclosing = [i for i, (s, e) in enumerate(class_body_ranges) if s <= header_idx < e]
        parent_name = classes[max(enclosing, key=lambda i: class_body_ranges[i][0])]["name"] if enclosing else None

        class_body_ranges.append((header_idx, body_end))

        class_id = f"{module}.{parent_name}.{name}" if parent_name else f"{module}.{name}"
        decorators = _decorators_before(lines, header_idx)
        bases = []
        if bases_str:
            for b in bases_str.split(","):
                b = b.strip()
                if b and "=" not in b:  # metaclass=X 등 kwarg 제외
                    bases.append(b.split(".")[-1])

        # 클래스 본문 내 def 헤더들 중 "직접 메서드" 판정: 가장 얕은 들여쓰기 레벨만 채택
        # (더 깊은 건 중첩 함수로 간주해 제외 — Java의 inner class 처리와 같은 원칙)
        def_headers_in_body = [
            dm for dm in DEF_HEAD_RE.finditer(text)
            if header_idx < _header_line_idx(dm) < body_end
        ]
        methods = []
        init_injected = {}
        if def_headers_in_body:
            min_indent = min(_indent(lines[_header_line_idx(dm)]) for dm in def_headers_in_body)
            for dm in def_headers_in_body:
                m_header_idx = _header_line_idx(dm)
                if _indent(lines[m_header_idx]) != min_indent:
                    continue
                m_name = dm.group(2)
                params, m_colon_pos = _scan_signature(text, dm)
                params = params or ""
                m_colon_line_idx = line_of(raw_text, m_colon_pos) - 1
                m_body_end = _block_end(lines, _indent(lines[m_header_idx]), m_colon_line_idx + 1)
                m_body = "\n".join(lines[m_colon_line_idx + 1:m_body_end])
                m_decos = _decorators_before(lines, m_header_idx)
                depends_targets = DEPENDS_RE.findall(params)
                type_hints = _split_type_hints(params)
                if m_name == "__init__":
                    init_injected.update(type_hints)
                    for am in INIT_ASSIGN_RE.finditer(m_body):
                        attr, ctor_type = am.groups()
                        init_injected.setdefault(attr, ctor_type)
                    continue  # __init__ 자체는 메서드 노드로 만들지 않음(Java 생성자와 동일 취급)
                methods.append({
                    "name": m_name, "line": m_header_idx + 1, "visibility": "public",
                    "static": "@staticmethod" in m_decos, "annotations": m_decos,
                    "signature": f"def {m_name}({params.strip()})",
                    "body": m_body, "depends_targets": depends_targets,
                    "param_type_hints": type_hints,
                })

        classes.append({
            "id": class_id, "name": name, "file": rel, "line": header_idx + 1,
            "annotations": decorators, "bases_raw": bases, "methods": methods,
            "fields": init_injected,
        })

    def _inside_any_class(idx):
        return any(start <= idx < end for start, end in class_body_ranges)

    # 모듈 최상위 함수 (클래스 밖, indent==0인 def만)
    functions = []
    for dm in DEF_HEAD_RE.finditer(text):
        header_idx = _header_line_idx(dm)
        if _indent(lines[header_idx]) != 0 or _inside_any_class(header_idx):
            continue
        f_name = dm.group(2)
        params, colon_pos = _scan_signature(text, dm)
        params = params or ""
        colon_line_idx = line_of(raw_text, colon_pos) - 1
        body_end = _block_end(lines, 0, colon_line_idx + 1)
        f_body = "\n".join(lines[colon_line_idx + 1:body_end])
        f_decos = _decorators_before(lines, header_idx)
        functions.append({
            "id": f"{module}.{f_name}", "name": f_name, "file": rel, "line": header_idx + 1,
            "annotations": f_decos, "signature": f"def {f_name}({params.strip()})",
            "body": f_body, "depends_targets": DEPENDS_RE.findall(params),
            "param_type_hints": _split_type_hints(params),
        })

    return {"module": module, "imports": imports, "classes": classes, "functions": functions}


def _resolve(name, imports, by_id, by_simple):
    if not name:
        return None
    if name in imports and imports[name] in by_id:
        return imports[name]
    candidates = by_simple.get(name) or []
    if len(candidates) == 1:
        return candidates[0]
    return None


def build_indexes(root):
    files = walk_files(root, ".py")
    parsed = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        result = parse_file(path, rel)
        if result:
            parsed.append(result)

    by_id = {}
    by_simple = {}
    for p in parsed:
        for c in p["classes"]:
            by_id[c["id"]] = {"kind": "class", "methods": c["methods"]}
            by_simple.setdefault(c["name"], []).append(c["id"])
        for fn in p["functions"]:
            by_id[fn["id"]] = {"kind": "function", "methods": []}
            by_simple.setdefault(fn["name"], []).append(fn["id"])

    symbols = []
    nodes = []
    edges = []

    for p in parsed:
        for c in p["classes"]:
            method_syms = [{"name": m["name"], "id": f"{c['id']}.{m['name']}", "line": m["line"], "visibility": "public"} for m in c["methods"]]
            symbols.append({
                "id": c["id"], "type": "class", "file": c["file"], "line": c["line"],
                "package": p["module"], "extends": c["bases_raw"][0] if c["bases_raw"] else None,
                "implements": c["bases_raw"][1:], "annotations": c["annotations"], "methods": method_syms,
            })
            nodes.append({
                "id": c["id"], "type": "class", "file": c["file"], "line": c["line"],
                "visibility": "public", "static": False, "annotations": c["annotations"], "signature": "",
            })
            for m in c["methods"]:
                nodes.append({
                    "id": f"{c['id']}.{m['name']}", "type": "method", "file": c["file"], "line": m["line"],
                    "visibility": "public", "static": m["static"], "annotations": m["annotations"],
                    "signature": m["signature"],
                })
        for fn in p["functions"]:
            symbols.append({
                "id": fn["id"], "type": "function", "file": fn["file"], "line": fn["line"],
                "package": p["module"], "extends": None, "implements": [],
                "annotations": fn["annotations"], "methods": [],
            })
            nodes.append({
                "id": fn["id"], "type": "function", "file": fn["file"], "line": fn["line"],
                "visibility": "public", "static": False, "annotations": fn["annotations"],
                "signature": fn["signature"],
            })

    for p in parsed:
        for c in p["classes"]:
            for base in c["bases_raw"]:
                target = _resolve(base, p["imports"], by_id, by_simple)
                if target:
                    edges.append({"from": c["id"], "to": target, "type": "inherit", "file": c["file"], "line": c["line"]})

            resolved_attr_targets = {}
            for attr, type_name in c["fields"].items():
                target = _resolve(type_name, p["imports"], by_id, by_simple)
                if target and by_id[target]["kind"] == "class":
                    edges.append({"from": c["id"], "to": target, "type": "inject", "file": c["file"], "line": c["line"]})
                    resolved_attr_targets[attr] = target

            for imp_name, imp_id in p["imports"].items():
                if imp_id in by_id and imp_id != c["id"]:
                    edges.append({"from": c["id"], "to": imp_id, "type": "import", "file": c["file"], "line": None})

            own_methods = {m["name"] for m in c["methods"]}
            for m in c["methods"]:
                for dep in m["depends_targets"]:
                    target = _resolve(dep, p["imports"], by_id, by_simple)
                    if target:
                        edges.append({"from": f"{c['id']}.{m['name']}", "to": target, "type": "inject", "file": c["file"], "line": None})
                for call_m in re.finditer(r"\bself\s*\.\s*(\w+)\s*\(", m["body"]):
                    called = call_m.group(1)
                    if called in own_methods:
                        edges.append({"from": f"{c['id']}.{m['name']}", "to": f"{c['id']}.{called}", "type": "call", "file": c["file"], "line": None})
                for attr, target_cls in resolved_attr_targets.items():
                    target_methods = {tm["name"] for tm in by_id[target_cls]["methods"]}
                    for call_m in re.finditer(rf"\bself\s*\.\s*{re.escape(attr)}\s*\.\s*(\w+)\s*\(", m["body"]):
                        called = call_m.group(1)
                        if called in target_methods:
                            edges.append({"from": f"{c['id']}.{m['name']}", "to": f"{target_cls}.{called}", "type": "call", "file": c["file"], "line": None})

        for fn in p["functions"]:
            for imp_name, imp_id in p["imports"].items():
                if imp_id in by_id and imp_id != fn["id"]:
                    edges.append({"from": fn["id"], "to": imp_id, "type": "import", "file": fn["file"], "line": None})
            for dep in fn["depends_targets"]:
                target = _resolve(dep, p["imports"], by_id, by_simple)
                if target:
                    edges.append({"from": fn["id"], "to": target, "type": "inject", "file": fn["file"], "line": None})
            for call_m in re.finditer(r"\b(\w+)\s*\(", fn["body"]):
                called = call_m.group(1)
                target = _resolve(called, p["imports"], by_id, by_simple)
                if target and by_id[target]["kind"] == "function" and target != fn["id"]:
                    edges.append({"from": fn["id"], "to": target, "type": "call", "file": fn["file"], "line": None})

            # 파라미터 타입힌트로 해석 가능한 변수(예: FastAPI Depends 주입 파라미터)가
            # method(...)를 호출하는 패턴도 잡는다 — self.attr 없이 그냥 지역 변수라 클래스
            # 메서드 스캔과 별도 처리 필요.
            for var_name, type_hint in fn["param_type_hints"].items():
                target_cls = _resolve(type_hint, p["imports"], by_id, by_simple)
                if not target_cls or by_id[target_cls]["kind"] != "class":
                    continue
                target_methods = {tm["name"] for tm in by_id[target_cls]["methods"]}
                for call_m in re.finditer(rf"\b{re.escape(var_name)}\s*\.\s*(\w+)\s*\(", fn["body"]):
                    called = call_m.group(1)
                    if called in target_methods:
                        edges.append({"from": fn["id"], "to": f"{target_cls}.{called}", "type": "call", "file": fn["file"], "line": None})

    return symbols, nodes, dedupe_edges(edges), len(parsed), len(files)


def main():
    parser = argparse.ArgumentParser(description="Python(FastAPI/Django/Flask) symbols.json + call_graph.json 기계 추출 (LLM 미사용)")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    symbols, nodes, edges, files_scanned, files_total = build_indexes(args.root)
    write_outputs(args.root, "index_extractor_python", symbols, nodes, edges, files_scanned, files_total)
    print_summary(symbols, nodes, edges, files_scanned, files_total)


if __name__ == "__main__":
    main()
