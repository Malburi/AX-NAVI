# validator 10개 체크 중 8개를 기계 실행하는 zero-LLM 검사기 (LLM 담당은 체크 5·10만)
import os
import re
import sys
import json
import glob
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# validator.md의 10개 검증 항목 중 1,2,3,4,6,7,8,9는 file-exists/JSON-parse/regex-grep 뿐이라
# LLM 판단이 필요 없다. 이 스크립트가 그 8개를 대신 계산하고, validator(LLM)는 체크 5(레이어
# 커버리지)와 체크 10 중 이 스크립트가 "판정 불가"로 남긴 항목에만 집중한다.
# 점수 산식은 validator.md의 "신뢰도 점수 산식"과 동일: FAIL -10, WARN -3, 보안 위험 1건 -15
# (최대 -45), 인덱스 무결성 FAIL -15, 변경 이력 누락 -5.

SECURITY_PATTERNS = [
    ("PASSWORD", re.compile(r"password\s*[:=]\s*\S{4,}", re.IGNORECASE)),
    ("API_KEY", re.compile(r"(api[_-]?key|secret[_-]?key)\s*[:=]\s*\S{8,}", re.IGNORECASE)),
    ("DB_HOST", re.compile(r"jdbc:.*//[^/]*:[^/]*@")),
    ("INTERNAL_IP", re.compile(r"(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.\d+\.\d+")),
    ("INTERNAL_DOMAIN", re.compile(r"\.(corp|internal|local|lan)\b")),
]

# 어떤 프로젝트에서도 있어야 하는 인덱스. transactions/external_io 등은 해당 사실이 없으면
# 생성기가 아예 만들지 않는 것이 정상이라(예: @Transactional 없는 SPA) 필수에서 뺐다 —
# 대신 아래 OPTIONAL은 _meta.json의 indexes 선언과 대조해 "만들었다고 해놓고 없는" 경우만 잡는다.
CORE_INDEX_FILES = ["call_graph.json", "symbols.json"]
OPTIONAL_INDEX_FILES = [
    "transactions.json", "external_io.json", "sql_usage.json", "schema.json",
    "api_contract.json", "dead_code.json", "env_branches.json", "ui_flow.json",
]
# `_`로 시작하는 파일은 인덱스 페이로드가 아니라 제어 파일이다(_meta.json = 전역 매니페스트,
# _analysis_input.json = analyzer 입력 digest, _ai_patch.json = LLM 보강 patch).
# 이들은 _meta 블록을 갖지 않는 것이 정상이라 9필드 규칙 대상에서 제외한다.
SKELETON_MARKER = "pattern-extractor 에이전트가 채울 예정입니다"
SOURCE_EXT_HINTS = (
    ".java", ".kt", ".kts", ".cs", ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".vue", ".xjs", ".xfdl", ".go", ".php", ".rb", ".jsp", ".asp", ".aspx", ".html", ".htm", ".xml", ".sql",
)

# docs/index-spec.md 공통 규칙의 _meta 필수 필드 (node_count/edge_count는 call_graph.json
# 등 그래프형 파일에만 의미가 있어 별도로 검사한다 — 여기엔 모든 인덱스 파일 공통분만 둔다)
REQUIRED_META_FIELDS = (
    "generated_at", "generator", "version", "source_root",
    "mode", "git_commit", "sampled", "files_scanned", "files_total",
)
DI_STACK_MARKERS = ("spring", "nestjs", "fastapi", "angular", "guice", "micronaut")
PROJECT_PATH_PREFIXES = (
    "src/", "app/", "lib/", "pages/", "components/", "test/", "tests/",
    "WEB-INF/", "routes/", "controllers/", "services/", "models/",
)


def _read(path):
    if not os.path.isfile(path):
        return None
    # 레거시 한국어 소스는 CP949(EUC-KR)인 경우가 흔하다. 예전에는 UnicodeDecodeError가
    # 그대로 올라와 스팟체크가 프로젝트 하나 때문에 통째로 죽었다 — 읽기는 항상 성공시킨다.
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _frontmatter_fields(text):
    m = re.match(r"^---\n(.*?)\n---", text or "", re.DOTALL)
    if not m:
        return {}
    body = m.group(1)
    fields = {}
    for key in ("name", "description", "model"):
        km = re.search(rf"^{key}:\s*(.+)$", body, re.MULTILINE)
        if km:
            fields[key] = km.group(1).strip()
    return fields


# ---------------------------------------------------------------------------
# Check 1: 파일 존재 및 완성도
# ---------------------------------------------------------------------------

def check1_file_existence(root):
    results = []
    claude_md = _read(os.path.join(root, "CLAUDE.md"))
    if claude_md is None:
        results.append(("FAIL", "CLAUDE.md 없음"))
    else:
        required_headers = ["## 요청 흐름", "## 빌드 / 실행", "## 자동 워크플로우", "## 변경 이력"]
        missing = [h for h in required_headers if h not in claude_md]
        if missing:
            results.append(("FAIL", f"CLAUDE.md 필수 섹션 누락: {', '.join(missing)}"))
        else:
            results.append(("PASS", "CLAUDE.md 필수 섹션 확인"))
        if len(claude_md.splitlines()) > 500:
            results.append(("WARN", "CLAUDE.md 500줄 초과"))

    for name in ("trace.md", "scaffolder.md", "find-logic.md"):
        path = os.path.join(root, ".claude", "skills", name)
        text = _read(path)
        if text is None:
            results.append(("FAIL", f".claude/skills/{name} 없음"))
            continue
        fm = _frontmatter_fields(text)
        if not fm.get("name") or not fm.get("description"):
            results.append(("WARN", f".claude/skills/{name} frontmatter(name/description) 불완전"))
        elif len(text.splitlines()) < 5:
            results.append(("WARN", f".claude/skills/{name} 내용 부족 의심"))
        else:
            results.append(("PASS", f".claude/skills/{name} 존재·frontmatter 확인"))

    domain_expert = _read(os.path.join(root, ".claude", "agents", "domain-expert.md"))
    if domain_expert is None:
        results.append(("FAIL", ".claude/agents/domain-expert.md 없음"))
    else:
        fm = _frontmatter_fields(domain_expert)
        if not fm.get("name") or not fm.get("description"):
            results.append(("WARN", "domain-expert.md frontmatter 불완전"))
        else:
            results.append(("PASS", "domain-expert.md 존재·frontmatter 확인"))

    patterns_dir = os.path.join(root, ".claude", "patterns")
    pattern_files = glob.glob(os.path.join(patterns_dir, "*.md")) if os.path.isdir(patterns_dir) else []
    if not pattern_files:
        results.append(("WARN", ".claude/patterns/ 파일 없음"))
    else:
        results.append(("PASS", f".claude/patterns/ {len(pattern_files)}개 파일 존재"))
        for p in pattern_files:
            text = _read(p) or ""
            if len(text.splitlines()) > 300:
                results.append(("WARN", f"{os.path.basename(p)} 300줄 초과"))

    return results


# ---------------------------------------------------------------------------
# Check 2: 워크플로우 스킬 등록 확인
# ---------------------------------------------------------------------------

def check2_skill_registration(root, decisions, claude_md_text):
    """이 6개는 프로젝트에 로컬 파일로 배포되지 않는다(플러그인 전역 스킬, 2026-08-13부터) —
    가용성은 CLAUDE.md 자동 워크플로우 표에 이름이 등록됐는지로만 판정한다."""
    results = []
    text = claude_md_text or ""

    for name in ("analyze-impact", "safe-modify", "scaffold-feature", "vibe"):
        if name in text:
            results.append(("PASS", f"CLAUDE.md에 {name} 등록"))
        else:
            results.append(("FAIL", f"CLAUDE.md 자동 워크플로우 표에 {name} 미등록 (플러그인 전역 스킬, 항상 등록돼야 함)"))

    for name, key in (("plan-migration", "plan_migration"), ("review-sql", "review_sql")):
        should_apply = bool((decisions or {}).get(key, {}).get("generate"))
        if should_apply and name not in text:
            results.append(("WARN", f"{name} 적용 대상으로 판단되었으나 CLAUDE.md에 미등록"))
        elif name in text:
            results.append(("PASS", f"CLAUDE.md에 {name} 등록"))

    return results


# ---------------------------------------------------------------------------
# Check 3: 스킬 트리거 품질 검사
# ---------------------------------------------------------------------------

KOREAN_QUOTE_RE = re.compile(r'"([^"]*[가-힣][^"]*)"')
ASCII_QUOTE_RE = re.compile(r'"([a-zA-Z][a-zA-Z \-]*)"')

# 정적 스킬 6종(analyze-impact/safe-modify/scaffold-feature/vibe/plan-migration/review-sql)은
# 2026-08-13부터 대상 프로젝트에 로컬 배포되지 않는다(플러그인 전역판만 사용) — 새로 배포되는
# 프로젝트에서는 애초에 `.claude/skills/*.md` 글롭 스캔에 걸리지 않으므로 이 목록은 사실상
# no-op이다. 2026-08-13 이전에 배포됐던 레거시 프로젝트에 잔존 사본이 있을 경우를 위한
# 하위호환 목적으로만 남겨둔다 — check 3은 writer가 실제로 새로 작성한 per-project 스킬
# (trace/scaffolder/find-logic/cross-repo-*)에만 적용. harness-init.md는 2026-07-23부터
# 프로젝트에 배포하지 않으므로(메타/툴링 스킬 — 하네스 재초기화용이지 개발 워크플로우가 아님)
# 이 목록에서 제외했다. 혹시 과거 세션에서 수동 배포된 사본이 남아있어도 이 목록에 없으면
# check3이 일반 per-project 스킬과 동일하게 트리거 품질을 검사하게 되는데, 이는 의도된
# 부작용이다 — 남아있는 사본은 트리거 부실 WARN으로 존재가 드러나 정리 대상임을 알 수 있다.
STATIC_OR_PREEXISTING_SKILLS = {
    "analyze-impact.md", "safe-modify.md", "scaffold-feature.md",
    "plan-migration.md", "review-sql.md", "vibe.md",
}


def check3_trigger_quality(root, decisions):
    results = []
    skills_dir = os.path.join(root, ".claude", "skills")
    stack_tokens = [
        t for t in re.split(r"[^0-9A-Za-z가-힣]+", (decisions or {}).get("detected_stack", "") or "")
        if len(t) >= 3
    ]

    for path in sorted(glob.glob(os.path.join(skills_dir, "*.md"))):
        name = os.path.basename(path)
        if name in STATIC_OR_PREEXISTING_SKILLS:
            continue
        text = _read(path) or ""
        fm = _frontmatter_fields(text)
        desc = fm.get("description", "")

        if len(desc) < 100:
            results.append(("WARN", f"{name} description 100자 미만 ({len(desc)}자)"))
        ko_triggers = len(KOREAN_QUOTE_RE.findall(desc))
        if ko_triggers < 3:
            results.append(("WARN", f"{name} 한국어 트리거 {ko_triggers}개 (3개 미만)"))
        en_triggers = len([m for m in ASCII_QUOTE_RE.findall(desc) if not re.search(r"[가-힣]", m)])
        if en_triggers < 2:
            results.append(("WARN", f"{name} 영어 트리거 {en_triggers}개 (2개 미만)"))
        if stack_tokens and not any(tok.lower() in desc.lower() for tok in stack_tokens):
            results.append(("WARN", f"{name} 스택 특화 키워드 미확인 (수동 확인 권장)"))
        if not fm.get("model"):
            results.append(("FAIL", f"{name} model 필드 없음"))

    return results


# ---------------------------------------------------------------------------
# Check 4: 프로젝트 파일과 교차 검증
# ---------------------------------------------------------------------------

PATH_RE = re.compile(r"`([\w./\-]+/[\w./\-]+)`")


def _partner_root(root):
    """pair_config.md의 partner_root: 값을 읽는다 — cross-repo 스킬이 파트너 저장소
    경로를 예시로 인용할 때 이를 '없는 경로'로 오탐하지 않기 위해 필요."""
    text = _read(os.path.join(root, "_workspace", "pair_config.md"))
    if not text:
        return None
    m = re.search(r"^partner_root:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def check4_path_crosscheck(root):
    results = []
    candidates = set()
    for pattern in (".claude/skills/*.md", ".claude/patterns/*.md"):
        for path in glob.glob(os.path.join(root, pattern)):
            text = _read(path) or ""
            for m in PATH_RE.findall(text):
                if m.startswith(PROJECT_PATH_PREFIXES):
                    candidates.add(m)

    partner_root = _partner_root(root)

    def _exists(rel_path):
        stripped = rel_path.rstrip("/\\")
        full = os.path.join(root, stripped)
        if os.path.isfile(full) or os.path.isdir(full):
            return True
        if partner_root:
            partner_full = os.path.join(partner_root, stripped)
            if os.path.isfile(partner_full) or os.path.isdir(partner_full):
                return True
        return False

    missing = [p for p in sorted(candidates) if not _exists(p)]
    if missing:
        for p in missing:
            results.append(("FAIL", f"참조 경로 없음: {p}"))
    elif candidates:
        results.append(("PASS", f"참조 경로 {len(candidates)}개 확인"))
    return results


# ---------------------------------------------------------------------------
# Check 6: 보안 위험 확인
# ---------------------------------------------------------------------------

def check6_security_scan(root):
    findings = []
    targets = []
    targets.append(os.path.join(root, "CLAUDE.md"))
    targets.extend(glob.glob(os.path.join(root, ".claude", "skills", "*.md")))
    targets.extend(glob.glob(os.path.join(root, ".claude", "patterns", "*.md")))
    targets.extend(glob.glob(os.path.join(root, ".claude", "agents", "*.md")))
    targets.extend(glob.glob(os.path.join(root, "_workspace", "index", "*.json")))

    for path in targets:
        text = _read(path)
        if not text:
            continue
        for label, pattern in SECURITY_PATTERNS:
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append(f"[{label}] {os.path.relpath(path, root)}:{line}")

    return findings


# ---------------------------------------------------------------------------
# Check 7: 인덱스 무결성
# ---------------------------------------------------------------------------

def _meta_field_issues(data, name):
    """반환: (fail_lines, warn_notes). generated_at이 실제 명령 실행(now_kst.py) 결과가
    아니라 추측으로 채워진 값(예: 과거 사례의 T00:00:00Z)인 것으로 의심되면 WARN만 남긴다
    — 형식만으로 100% 단정할 수 없어 FAIL이 아니라 WARN으로 완화."""
    meta = data.get("_meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        return [f"- {name}: FAIL (_meta 블록 없음)"], []
    missing = [k for k in REQUIRED_META_FIELDS if k not in meta]
    if missing:
        return [f"- {name}: FAIL (_meta 필수 필드 누락: {', '.join(missing)})"], []

    warns = []
    generated_at = str(meta.get("generated_at") or "")
    if generated_at.endswith("T00:00:00Z") or generated_at.endswith("T00:00:00+09:00"):
        warns.append(
            f"{name}: generated_at이 자정(00:00:00) — 실제 시각 조회 없이 채워졌을 가능성 (agents/lib/now_kst.py 실행 결과 사용 권장)"
        )
    elif generated_at.endswith("Z") and not generated_at.endswith("+09:00"):
        warns.append(f"{name}: generated_at이 KST(+09:00)가 아닌 UTC(Z) 표기 — agents/lib/now_kst.py 실행 결과 사용 권장")
    return [], warns


def _call_graph_integrity_issues(data, decisions):
    """dangling edge·node/edge count 불일치·edge 종류 누락(import/inherit/inject)
    검사. mfs-test3 사례(호출그래프만 추출되고 임포트/DI/상속 그래프가 누락된 채
    _meta도 없이 통과되던 문제)를 재발 방지하기 위한 게이트."""
    fail_lines, warn_notes = [], []
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
    ids = {n.get("id") for n in nodes}

    dangling = [e for e in edges if e.get("from") not in ids or e.get("to") not in ids]
    if dangling:
        sample = "; ".join(f"{e.get('from')} -> {e.get('to')}" for e in dangling[:5])
        fail_lines.append(
            f"- call_graph.json: FAIL (dangling edge {len(dangling)}건 — nodes에 없는 from/to 참조, 예: {sample})"
        )

    # 노드 중복. 여러 생성기의 결과를 병합할 때(예: 결정론적 인덱서 위에 Vue 추출기를 얹을 때)
    # id 기준 dedupe를 빠뜨리면 in-degree·허브 랭킹·데드코드 집계가 조용히 왜곡된다.
    if len(ids) != len(nodes):
        dup = len(nodes) - len(ids)
        seen, dup_ids = set(), []
        for n in nodes:
            nid = n.get("id")
            if nid in seen and nid not in dup_ids:
                dup_ids.append(str(nid))
            seen.add(nid)
        fail_lines.append(f"- call_graph.json: FAIL (중복 node id {dup}건, 예: {', '.join(dup_ids[:5])})")

    meta = data.get("_meta") or {}
    if "node_count" in meta and meta.get("node_count") != len(nodes):
        fail_lines.append(f"- call_graph.json: FAIL (_meta.node_count={meta.get('node_count')} ≠ 실제 노드 {len(nodes)})")
    if "edge_count" in meta and meta.get("edge_count") != len(edges):
        fail_lines.append(f"- call_graph.json: FAIL (_meta.edge_count={meta.get('edge_count')} ≠ 실제 엣지 {len(edges)})")

    edge_types = {}
    for e in edges:
        t = e.get("type")
        edge_types[t] = edge_types.get(t, 0) + 1

    # import edge 부재는 결함이 아니다. 결정론적 인덱서(build-index.mjs)는 파일 노드가 없는
    # 순수 심볼 그래프라 import 엣지를 만들지 않는다 — 만들면 to가 노드가 아니라서 전부
    # dangling이 된다. 파일 단위 관계를 내는 생성기(index_extractor_vue.py 등)만 이 엣지를 쓴다.

    class_count = len([n for n in nodes if n.get("type") == "class"])
    if class_count == 0:
        # nodes에 class 타입이 없으면 symbols.json에서 대신 센다 (call_graph는 class를 아예
        # 노드화하지 않는 스타일도 있어 이것만으로 inherit 누락을 단정하지 않기 위함)
        pass
    if class_count > 0 and edge_types.get("inherit", 0) == 0:
        warn_notes.append(
            f"call_graph.json: class 노드 {class_count}개 존재하나 inherit edge 0개 — 상속 관계 추출 누락 의심 (analyzer.md Step 8 참고)"
        )

    detected_stack = ((decisions or {}).get("detected_stack") or "").lower()
    if any(marker in detected_stack for marker in DI_STACK_MARKERS) and edge_types.get("inject", 0) == 0:
        warn_notes.append(
            f"call_graph.json: 스택({(decisions or {}).get('detected_stack')})에 DI 프레임워크가 감지되나 inject edge 0개 — DI 그래프 추출 누락 의심 (analyzer.md Step 8 참고)"
        )

    return fail_lines, warn_notes


def check7_index_integrity(root, analyzer_report_text, decisions=None):
    index_dir = os.path.join(root, "_workspace", "index")
    lines = []
    warn_notes = []
    missing_core = 0
    parse_failures = 0
    call_graph_empty = False
    meta_fail = False
    cg_issue_fail = False

    for name in CORE_INDEX_FILES:
        path = os.path.join(index_dir, name)
        if not os.path.isfile(path):
            lines.append(f"- {name}: WARN (없음)")
            missing_core += 1
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            lines.append(f"- {name}: FAIL (JSON 파싱 실패)")
            parse_failures += 1
            continue

        if name == "call_graph.json":
            nodes = len(data.get("nodes") or [])
            edges = len(data.get("edges") or [])
            call_graph_empty = (nodes == 0 and edges == 0)
            status = "FAIL (노드/엣지 0)" if call_graph_empty else "PASS"
            lines.append(f"- {name}: {status} (노드 {nodes}, 엣지 {edges})")
            if not call_graph_empty:
                cg_fail_lines, cg_warns = _call_graph_integrity_issues(data, decisions)
                if cg_fail_lines:
                    cg_issue_fail = True
                    lines.extend(cg_fail_lines)
                warn_notes.extend(cg_warns)
        else:
            lines.append(f"- {name}: PASS")

    # 선택 인덱스는 없어도 정상이지만, _meta.json이 "생성했다"고 선언한 것이 실제로 없으면 FAIL이다.
    declared_missing = []
    manifest = _read_json(os.path.join(index_dir, "_meta.json"))
    declared = manifest.get("indexes") if isinstance(manifest, dict) else None
    if isinstance(declared, list):
        for key in declared:
            path = os.path.join(index_dir, f"{key}.json")
            if not os.path.isfile(path):
                declared_missing.append(f"{key}.json")
        if declared_missing:
            lines.append(f"- _meta.json: FAIL (indexes에 선언됐으나 파일 없음: {', '.join(declared_missing)})")
    present_optional = [n for n in OPTIONAL_INDEX_FILES if os.path.isfile(os.path.join(index_dir, n))]
    if present_optional:
        lines.append(f"- 선택 인덱스 존재: {', '.join(present_optional)}")

    # _meta 필수 필드 확인 — 존재하는 인덱스 파일 전부 (core에 한정하지 않음, 제어 파일은 제외)
    all_index_files = sorted(glob.glob(os.path.join(index_dir, "*.json"))) if os.path.isdir(index_dir) else []
    for path in all_index_files:
        name = os.path.basename(path)
        if name.startswith("_"):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # 파싱 실패는 core 파일이면 위에서 이미 기록됨
        meta_fail_lines, meta_warns = _meta_field_issues(data, name)
        if meta_fail_lines:
            meta_fail = True
            lines.extend(meta_fail_lines)
        warn_notes.extend(meta_warns)

    confidence_m = re.search(r"의존성 그래프 완전성:\s*(HIGH|MEDIUM|LOW)", analyzer_report_text or "")
    stale_mismatch = False
    if confidence_m and confidence_m.group(1) in ("HIGH", "MEDIUM") and call_graph_empty:
        stale_mismatch = True
        lines.append("- 신뢰도 불일치: 분석 신뢰도 MEDIUM 이상인데 call_graph가 비어있음")

    fail = (
        missing_core >= 1 or parse_failures > 0 or call_graph_empty
        or stale_mismatch or meta_fail or cg_issue_fail or bool(declared_missing)
    )
    return fail, "\n".join(lines), warn_notes


# ---------------------------------------------------------------------------
# Check 7b: 인덱스 내용 스팟체크 (엣지·SQL 실측 대조 — LLM이 만든 인덱스의 내용 정확성 게이트)
# ---------------------------------------------------------------------------

SPOTCHECK_EDGE_SAMPLES = 20
SPOTCHECK_SQL_SAMPLES = 10
SPOTCHECK_MIN_CHECKABLE = 5
SPOTCHECK_PASS_RATE = 0.8


def _evenly_spaced(items, n):
    """결정론적 샘플링 — random 대신 정렬 후 균등 간격 추출 (재실행 시 같은 결과)."""
    if len(items) <= n:
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


NODE_TYPE_PREFIX_RE = re.compile(r"^[a-z][a-z_-]*:(?!//)")


SYNTHETIC_SQL_ID_RE = re.compile(r".+:\d+:(raw|literal|inline)$", re.IGNORECASE)


def _sql_probe(entry):
    """SQL 항목을 소스와 대조할 때 실제로 찾아볼 문자열을 고른다.
    MyBatis 매퍼처럼 이름 있는 id는 그 id가 파일에 그대로 있지만, 문자열 리터럴에서 뽑은
    SQL은 id가 'app/api/x.py:62:raw'처럼 위치 기반이라 소스에 있을 리가 없다 — 이때는
    id 대신 대상 테이블명이나 SQL 본문 앞부분을 찾는다."""
    sql_id = str(entry.get("id") or "")
    if sql_id and not SYNTHETIC_SQL_ID_RE.match(sql_id):
        return sql_id, "id"
    tables = [t for t in (entry.get("tables") or []) if isinstance(t, str) and t.strip()]
    if tables:
        return tables[0].split(".")[-1].strip(), "테이블명"
    preview = str(entry.get("text_preview") or entry.get("text") or "").strip()
    if preview:
        return " ".join(preview.split()[:3]), "SQL 본문"
    return "", "대조 기준"


def _looks_like_path(target):
    """'src/stores/theme.js' → True, 'src.stores.theme' / 'com.example.Foo' → False.
    import edge의 to는 생성기마다 파일 경로형과 심볼 id형으로 갈린다."""
    if "/" in target or "\\" in target:
        return True
    return target.lower().endswith(SOURCE_EXT_HINTS)


def _simple_name(symbol_id):
    """'com.example.OrderService.cancel' / 'src/x.ts::cancelOrder' → 'cancel' / 'cancelOrder'.
    일부 analyzer는 노드 id를 'sql:PKG_X' / 'page:Menu.vue' / 'route:/lo'처럼 type: 접두사로
    낸다 — 이 접두사를 벗기지 않으면 실제 소스에 없는 문자열을 찾아 스팟체크가 오탐(FAIL)한다."""
    symbol_id = NODE_TYPE_PREFIX_RE.sub("", symbol_id, count=1)
    tail = symbol_id.rsplit("::", 1)[-1]
    tail = tail.rsplit(".", 1)[-1]
    return tail.split("(", 1)[0].strip()


def check7b_spotcheck(root):
    """call_graph 엣지·sql_usage 항목을 실제 소스와 대조한다.
    qa Boundary 5(온디맨드)와 달리 기본 파이프라인에서 항상 도는 기계 게이트."""
    index_dir = os.path.join(root, "_workspace", "index")
    lines = []
    fail = False

    # --- call_graph 엣지: from 쪽 파일에 callee 단순명이 실제로 등장하는가 ---
    cg_path = os.path.join(index_dir, "call_graph.json")
    if os.path.isfile(cg_path):
        try:
            with open(cg_path, "r", encoding="utf-8-sig") as f:
                cg = json.load(f)
        except (json.JSONDecodeError, OSError):
            cg = None
        if cg:
            node_file = {n.get("id"): n.get("file") for n in (cg.get("nodes") or []) if isinstance(n, dict)}
            all_edges = [e for e in (cg.get("edges") or []) if isinstance(e, dict) and e.get("from") and e.get("to")]
            # import 타입 edge(파일 단위 관계)는 to가 파일 경로라 _simple_name()이 확장자("js" 등)만
            # 남겨 심볼명 매칭이 의미 없다 — 별도로 "대상 파일이 실존하는가"만 확인한다.
            symbol_edges = sorted((e for e in all_edges if e.get("type") != "import"), key=lambda e: (str(e.get("from")), str(e.get("to"))))
            import_edges = sorted((e for e in all_edges if e.get("type") == "import"), key=lambda e: (str(e.get("from")), str(e.get("to"))))

            hits = checked = missing_files = 0
            misses = []
            for e in _evenly_spaced(symbol_edges, SPOTCHECK_EDGE_SAMPLES):
                src_rel = e.get("file") or node_file.get(e.get("from"))
                if not src_rel:
                    continue
                src_text = _read(os.path.join(root, src_rel))
                if src_text is None:
                    missing_files += 1
                    continue
                checked += 1
                callee = _simple_name(str(e.get("to")))
                if callee and re.search(rf"\b{re.escape(callee)}\b", src_text):
                    hits += 1
                else:
                    misses.append(f"{e.get('from')} → {e.get('to')} ({src_rel})")
            if checked >= SPOTCHECK_MIN_CHECKABLE:
                rate = hits / checked
                status = "PASS" if rate >= SPOTCHECK_PASS_RATE else "FAIL"
                if status == "FAIL":
                    fail = True
                lines.append(f"- call_graph 엣지 스팟체크: {status} ({hits}/{checked} 일치, 기준 {int(SPOTCHECK_PASS_RATE*100)}%)")
                for m in misses[:5]:
                    lines.append(f"  - 불일치: {m}")
            else:
                lines.append(f"- call_graph 엣지 스팟체크: 판정 불가 (대조 가능 엣지 {checked}개 < {SPOTCHECK_MIN_CHECKABLE})")

            if import_edges:
                ihits = ichecked = 0
                imisses = []
                node_ids = set(node_file)
                for e in _evenly_spaced(import_edges, SPOTCHECK_EDGE_SAMPLES):
                    target = str(e.get("to"))
                    to_rel = NODE_TYPE_PREFIX_RE.sub("", target, count=1)
                    ichecked += 1
                    if _looks_like_path(to_rel):
                        # 파일 경로형 to — 실제 파일이 있어야 한다
                        ok = os.path.isfile(os.path.join(root, to_rel))
                        reason = "대상 파일 없음"
                    else:
                        # 심볼 id형 to (예: com.example.OrderService, src.stores.theme) — 노드로 존재해야 한다.
                        # 예전엔 이것도 파일로 찾아서 Java·Kotlin·C# 인덱스가 상시 오탐 FAIL이었다.
                        ok = target in node_ids
                        reason = "대상 노드 없음"
                    if ok:
                        ihits += 1
                    else:
                        imisses.append(f"{e.get('from')} → {e.get('to')} ({reason})")
                if ichecked >= SPOTCHECK_MIN_CHECKABLE:
                    irate = ihits / ichecked
                    istatus = "PASS" if irate >= SPOTCHECK_PASS_RATE else "FAIL"
                    if istatus == "FAIL":
                        fail = True
                    lines.append(f"- call_graph import 엣지 대상 존재 확인: {istatus} ({ihits}/{ichecked}, 기준 {int(SPOTCHECK_PASS_RATE*100)}%)")
                    for m in imisses[:5]:
                        lines.append(f"  - 불일치: {m}")
                else:
                    lines.append(f"- call_graph import 엣지 대상 존재 확인: 판정 불가 (대조 가능 {ichecked}개 < {SPOTCHECK_MIN_CHECKABLE})")
            if missing_files:
                lines.append(f"  - 소스 파일 자체가 없는 엣지 {missing_files}개 (경로 오류 또는 stale 인덱스 의심)")

    # --- sql_usage: 매퍼 파일에 SQL ID가, 사용처 파일에 참조가 실제로 있는가 ---
    su_path = os.path.join(index_dir, "sql_usage.json")
    if os.path.isfile(su_path):
        try:
            with open(su_path, "r", encoding="utf-8-sig") as f:
                su = json.load(f)
        except (json.JSONDecodeError, OSError):
            su = None
        if su:
            hits = checked = 0
            misses = []
            entries = sorted(
                [s for s in (su.get("sqls") or []) if isinstance(s, dict) and s.get("id") and s.get("file")],
                key=lambda s: str(s.get("id")),
            )
            for s in _evenly_spaced(entries, SPOTCHECK_SQL_SAMPLES):
                text = _read(os.path.join(root, s["file"]))
                if text is None:
                    misses.append(f"{s['id']} (파일 없음: {s['file']})")
                    checked += 1
                    continue
                checked += 1
                probe, label = _sql_probe(s)
                if probe and re.search(re.escape(probe), text, re.IGNORECASE):
                    hits += 1
                else:
                    misses.append(f"{s['id']} ({s['file']}에 {label} 미존재)")
            if checked >= SPOTCHECK_MIN_CHECKABLE:
                rate = hits / checked
                status = "PASS" if rate >= SPOTCHECK_PASS_RATE else "FAIL"
                if status == "FAIL":
                    fail = True
                lines.append(f"- sql_usage 스팟체크: {status} ({hits}/{checked} 일치)")
                for m in misses[:5]:
                    lines.append(f"  - 불일치: {m}")
            elif checked:
                lines.append(f"- sql_usage 스팟체크: 판정 불가 (대조 가능 항목 {checked}개 < {SPOTCHECK_MIN_CHECKABLE})")

    return fail, lines


def _index_meta_freshness(root):
    """_meta.git_commit이 있으면 현재 HEAD와 대조해 드리프트를 알린다 (감점 없음, 정보성)."""
    import subprocess
    cg_path = os.path.join(root, "_workspace", "index", "call_graph.json")
    if not os.path.isfile(cg_path):
        return []
    try:
        with open(cg_path, "r", encoding="utf-8-sig") as f:
            meta = (json.load(f) or {}).get("_meta") or {}
    except (json.JSONDecodeError, OSError):
        return []
    lines = []
    if meta.get("sampled"):
        scanned, total = meta.get("files_scanned"), meta.get("files_total")
        cov = f" (커버리지 {scanned}/{total})" if scanned and total else ""
        lines.append(f"- 인덱스가 샘플링 모드로 생성됨{cov} — dead_code 등 파생 결과 신뢰도 낮음")
    # 신선도는 source_fingerprint(내용 지문)로 판정한다. git_commit 대조는 헛경보만 냈다 —
    # 인덱스를 만든 뒤 하네스를 커밋하면 HEAD가 앞서가므로 항상 "리프레시 권장"이 떴고,
    # 팀원이 clone한 저장소에서는 소스가 한 글자도 다르지 않아도 커밋 해시가 달랐다
    # (2026-08-16 가상 프로젝트 실행에서 두 경우 모두 재현).
    # 지문은 clone·OS·커밋 이력과 무관하게 "인덱싱한 소스와 지금 소스가 같은가"만 본다.
    # 지문은 인덱스 묶음 전체에 대한 값이라 call_graph._meta가 아니라 글로벌 _meta.json에 있다.
    global_meta = {}
    try:
        with open(os.path.join(root, "_workspace", "index", "_meta.json"), "r", encoding="utf-8-sig") as f:
            global_meta = json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        pass
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    indexer = os.path.join(plugin_root, "agents", "lib", "build-index.mjs")
    if global_meta.get("source_fingerprint") and os.path.isfile(indexer):
        try:
            probe = subprocess.run(
                ["node", indexer, "--root", root, "--check-stale"],
                capture_output=True, text=True, timeout=180,
            )
            if probe.returncode == 1:
                reason = ""
                try:
                    reason = (json.loads(probe.stdout or "{}") or {}).get("reason") or ""
                except json.JSONDecodeError:
                    pass
                lines.append(f"- 인덱스가 현재 소스와 불일치{f' ({reason})' if reason else ''} — 인덱스 리프레시 권장")
        except Exception:
            pass
    elif meta.get("git_commit"):
        # 지문이 없는 구버전 인덱스만 예전 방식으로 확인한다.
        commit = meta["git_commit"]
        try:
            head = subprocess.run(
                ["git", "-C", root, "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if head and head != commit:
                lines.append(f"- 인덱스 생성 시점 커밋({commit[:8]}) ≠ 현재 HEAD({head[:8]}) — 인덱스 리프레시 권장 (구버전 인덱스)")
        except Exception:
            pass
    return lines


# ---------------------------------------------------------------------------
# Check 8: harness-init 스킬 보존 확인 (2026-07-23 완화)
# ---------------------------------------------------------------------------
# harness-init.md는 더 이상 프로젝트 .claude/skills/에 배포하지 않는다 — 그건 하네스
# 재초기화용 메타/툴링 스킬이지 프로젝트 개발(바이브 코딩) 워크플로우 스킬이 아니라서,
# 배포해두면 wiki workflows.md·domain 참조 등 LLM이 실제 참조하는 목록에 함께 노출돼
# "기능 개발 중 하네스를 재초기화하라"는 엉뚱한 참조를 유발한다. 플러그인이 설치된
# 세션에서는 harness-init이 이미 전역적으로 호출 가능하므로 프로젝트 로컬 사본이
# 애초에 불필요하다. 이 체크는 과거 호환을 위해 남기되 항상 정보성 PASS만 반환한다
# (감점 없음) — 프로젝트에 사본이 남아있어도 무방하나 강제하지 않는다.

def check8_harness_init_preserved(root):
    path = os.path.join(root, ".claude", "skills", "harness-init.md")
    text = _read(path)
    if text is None:
        return "PASS", "harness-init.md 미배포 (정상 — 플러그인이 전역 제공, 프로젝트 로컬 사본 불필요)"
    fm = _frontmatter_fields(text)
    if fm.get("name") != "harness-init":
        return "PASS", "harness-init.md frontmatter name 불일치(정보성, 감점 없음)"
    return "PASS", "harness-init.md 존재 확인(선택 사항, 감점 대상 아님)"


# ---------------------------------------------------------------------------
# Check 9: 변경 이력 기록 확인
# ---------------------------------------------------------------------------

def check9_changelog(claude_md_text):
    if not claude_md_text or "## 변경 이력" not in claude_md_text:
        return "WARN", "변경 이력 섹션 없음"
    after = claude_md_text.split("## 변경 이력", 1)[1]
    rows = [l for l in after.splitlines() if l.strip().startswith("|") and "----" not in l and "날짜" not in l]
    if not rows:
        return "WARN", "변경 이력 테이블에 항목 없음"
    return "PASS", f"변경 이력 {len(rows)}건 확인"


# ---------------------------------------------------------------------------
# Check 10: patterns/ 스켈레톤 vs 본문 구분 (마커 기반, 애매하면 validator LLM에 위임)
# ---------------------------------------------------------------------------

def check10_pattern_status(root):
    patterns_dir = os.path.join(root, ".claude", "patterns")
    lines = []
    undecided = []
    for path in sorted(glob.glob(os.path.join(patterns_dir, "*.md"))):
        name = os.path.basename(path)
        text = _read(path) or ""
        has_skeleton_marker = SKELETON_MARKER in text
        has_filled_marker = bool(re.search(r"신뢰도:\s*(HIGH|MEDIUM|LOW)", text))
        if has_skeleton_marker and not has_filled_marker:
            lines.append(f"- {name}: SKELETON (pattern-extractor 호출 권장)")
        elif has_filled_marker and not has_skeleton_marker:
            lines.append(f"- {name}: FILLED")
        else:
            lines.append(f"- {name}: 판정 불가 — validator 직접 확인 필요")
            undecided.append(name)
    return lines, undecided


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="validator 체크 1,2,3,4,6,7,8,9 (+10 시도) 기계 실행기 (LLM 미사용)")
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    root = args.root
    out_path = args.out or os.path.join(root, "_workspace", "validator_mechanical.json")

    claude_md_text = _read(os.path.join(root, "CLAUDE.md")) or ""
    analyzer_report_text = _read(os.path.join(root, "_workspace", "01_analyzer_report.md")) or ""

    decisions = None
    decisions_path = os.path.join(root, "_workspace", "writer_decisions.json")
    if os.path.isfile(decisions_path):
        try:
            with open(decisions_path, "r", encoding="utf-8-sig") as f:
                decisions = json.load(f)
        except json.JSONDecodeError:
            pass

    r1 = check1_file_existence(root)
    r2 = check2_skill_registration(root, decisions, claude_md_text)
    r3 = check3_trigger_quality(root, decisions)
    r4 = check4_path_crosscheck(root)
    combined_1to6 = r1 + r2 + r3 + r4

    security_findings = check6_security_scan(root)

    index_fail, index_lines, index_warns = check7_index_integrity(root, analyzer_report_text, decisions)
    spotcheck_fail, spotcheck_lines = check7b_spotcheck(root)
    freshness_lines = _index_meta_freshness(root)
    if spotcheck_fail:
        index_fail = True
    check8_status, check8_note = check8_harness_init_preserved(root)
    check9_status, check9_note = check9_changelog(claude_md_text)
    check10_lines, check10_undecided = check10_pattern_status(root)

    fails = [n for s, n in combined_1to6 if s == "FAIL"]
    warns = [n for s, n in combined_1to6 if s == "WARN"] + index_warns
    passes = [n for s, n in combined_1to6 if s == "PASS"]
    if check8_status == "FAIL":
        fails.append(check8_note)
    else:
        passes.append(check8_note)

    deduction = 10 * len(fails) + 3 * len(warns)
    deduction += 15 * min(len(security_findings), 3)
    if index_fail:
        deduction += 15
    if check9_status == "WARN":
        deduction += 5

    md_1to6 = (
        "## 1~6. 기본 검증\n"
        + "\n".join(f"✅ PASS: {n}" for n in passes)
        + ("\n" if passes else "")
        + "\n".join(f"⚠️  WARN: {n} (각 -3점)" for n in warns)
        + ("\n" if warns else "")
        + "\n".join(f"❌ FAIL: {n} (각 -10점)" for n in fails)
    )

    md_security = (
        "## 🔒 보안 확인 필요\n" + ("\n".join(security_findings) if security_findings else "(발견 없음)")
    )

    md_7 = "## 7. 인덱스 무결성\n" + (index_lines or "(인덱스 없음)")
    extra_7 = spotcheck_lines + freshness_lines
    if extra_7:
        md_7 += "\n\n### 7b. 내용 스팟체크 (실측 대조)\n" + "\n".join(extra_7)
    md_8 = f"## 8. harness-init 보존\n{check8_status}"
    md_9 = f"## 9. 변경 이력 기록\n{check9_status}"
    md_10 = "## 10. patterns/ 상태\n" + ("\n".join(check10_lines) if check10_lines else "(패턴 파일 없음)")

    result = {
        "mechanical_deduction": deduction,
        "fails": fails,
        "warns": warns,
        "passes": passes,
        "security_findings": security_findings,
        "index_integrity_fail": index_fail,
        "index_spotcheck_fail": spotcheck_fail,
        "check8_status": check8_status,
        "check9_status": check9_status,
        "check10_undecided": check10_undecided,
        "report_fragments": {
            "1to6": md_1to6,
            "security": md_security,
            "7": md_7,
            "8": md_8,
            "9": md_9,
            "10": md_10,
        },
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"생성 완료: {out_path} (기계 체크 차감 {deduction}점)")


if __name__ == "__main__":
    main()
