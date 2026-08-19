"""wiki_content.py — _workspace/·.claude/ 산출물을 wiki 페이지 문자열로 변환하는 순수 함수 모음.

전부 LLM 미개입, 결정론적 Python. wiki_generator.py가 파일을 읽어(read_file/load_json)
이 모듈의 build_*() 함수에 텍스트/딕셔너리를 넘기면, 각 함수는 markdown 문자열을 반환한다.

크로스 리포(pair-init) 병합이 의미 있는 5개 함수(domain/architecture/api-endpoints/database/
external-systems)는 own_* 인자 옆에 partner_* 인자(1:1, paired-roots)를 받아, 있으면
"## 파트너 (label)" 섹션으로 이어붙인다. 파트너가 여러 개인 1:N(hub-roots, 예: 백엔드+웹+
모바일+관리자)은 partner_*와 별개로 `partners`(리스트) 인자를 추가로 받아 항목마다 "## 파트너
(label)" 섹션을 하나씩 더 이어붙인다 — 두 경로 다 동시에 값이 오면 partner_*가 먼저, partners
목록이 그 뒤에 이어진다. 파트너가 없으면(harness-init 전이거나 단일 저장소) own 것만 반환.
workflows/patterns/issues는 저장소별 실행 환경·품질 이슈라 병합 대상이 아니다
(CLAUDE.md 2026-07-15 wiki 통합 변경 이력 참조).
"""

import json
import os
import re
from collections import Counter


def _section(label, body):
    if not body or not body.strip():
        return ""
    return f"## {label}\n\n{body.strip()}\n"


def build_home(claude_md_text):
    if not claude_md_text:
        return "# Home\n\nCLAUDE.md가 없습니다.\n"
    return "> 이 페이지는 프로젝트 루트의 `CLAUDE.md`를 그대로 보여줍니다.\n\n" + claude_md_text


def build_support_status(meta_json):
    coverage = (meta_json or {}).get("adapter_coverage") or {}
    status = coverage.get("status", "UNKNOWN")
    decision = coverage.get("decision", "HOLD")
    parts = [
        "# 유지보수 지원 현황\n",
        f"> 전체 상태: **{status}** · 자동 변경 게이트: **{decision}**\n",
        "이 페이지의 지원은 제품명 선언이 아니라 실제 인덱싱 결과입니다. PARTIAL/UNSUPPORTED 대상은 빌드·UI·통합 시나리오의 명시적 검증 전까지 HOLD입니다.\n",
        "## 활성 어댑터\n",
        "| 어댑터 | 파일 수 |\n|---|---:|",
    ]
    active = coverage.get("active_adapters") or []
    parts.extend(f"| `{item.get('id', 'unknown')}` | {item.get('files', 0)} |" for item in active)
    if not active:
        parts.append("| (탐지 없음) | 0 |")
    parts.extend(["\n## 확장자 커버리지\n", "| 확장자 | 어댑터 | 수준 | 파일 수 |\n|---|---|---|---:|"])
    for item in coverage.get("extensions") or []:
        parts.append(f"| `{item.get('extension')}` | `{item.get('adapter', 'generic')}` | **{item.get('level', 'PARTIAL')}** | {item.get('files', 0)} |")
    unsupported = coverage.get("unsupported_files") or []
    partial_targets = coverage.get("partial_targets") or []
    if partial_targets:
        parts.extend(["\n## 파일 단위 PARTIAL 대상\n", *[f"- `{item.get('path')}` — {item.get('reason', '수동 검증 필요')}" for item in partial_targets]])
    if unsupported:
        parts.extend(["\n## Discovery-only / 미지원 파일\n", *[f"- `{path}`" for path in unsupported]])
    parts.extend(["\n## 판정 규칙\n", f"- {coverage.get('rule', 'PARTIAL 또는 미지원 대상은 HOLD')}\n", "- FULL도 동적 reflection, UI 시각 배치, 운영 환경 연동까지 자동 보증하지 않습니다.\n"])
    return "\n".join(parts)


def build_architecture(own_report_text, partner_report_text=None,
                        own_label="이 저장소", partner_label=None, partners=None):
    own = own_report_text or "`_workspace/01_analyzer_report.md`가 없습니다. harness-init을 먼저 실행하세요.\n"
    parts = [f"# 아키텍처\n", _section(own_label, own)]
    if partner_report_text:
        parts.append(_section(f"파트너 ({partner_label or '연동 저장소'})", partner_report_text))
    for p in (partners or []):
        if p.get("text"):
            parts.append(_section(f"파트너 ({p.get('label') or '연동 저장소'})", p["text"]))
    return "\n".join(p for p in parts if p)


def _extract_domain_sections(report_text):
    """01_analyzer_report.md에서 "## A. ..." 섹션(프로젝트 기본 정보·아키텍처 레이어·요청 흐름·
    코드 컨벤션·데이터 접근 패턴·클라이언트 자원·빌드/실행 명령)만 순서대로 뽑는다.
    이 헤딩 집합은 agents/analyzer.md '출력: 분석 리포트' 템플릿에 고정돼 있어 정규식으로
    안전하게 분리할 수 있다 — "## B."·"탐지 신뢰도" 등 더 기술적인 나머지는 architecture.md에만
    남기고, 도메인/업무 흐름 이해에 필요한 부분만 빠르게 찾을 수 있는 별도 페이지로 분리한다."""
    if not report_text:
        return ""
    blocks = [p.strip() for p in re.split(r"\n(?=## )", report_text) if p.strip().startswith("## A.")]
    return "\n\n".join(blocks)


def build_domain_overview(own_report_text, partner_report_text=None,
                           own_label="이 저장소", partner_label=None, partners=None):
    own = _extract_domain_sections(own_report_text)
    if not own:
        own = ("도메인 개요 섹션(`## A.`)을 찾지 못했습니다 — `_workspace/01_analyzer_report.md`가 "
               "없거나 예상 형식이 아닙니다. 전체 분석 리포트는 architecture.md를 참고하세요.\n")
    parts = ["# 도메인 개요\n", _section(own_label, own)]
    partner_domain = _extract_domain_sections(partner_report_text)
    if partner_domain:
        parts.append(_section(f"파트너 ({partner_label or '연동 저장소'})", partner_domain))
    for p in (partners or []):
        block = _extract_domain_sections(p.get("text"))
        if block:
            parts.append(_section(f"파트너 ({p.get('label') or '연동 저장소'})", block))
    return "\n".join(p for p in parts if p)


def _read_dir_pages(dir_path):
    """폴더 안 *.md 파일을 이름순으로 (filename, text) 목록으로 읽는다."""
    if not dir_path or not os.path.isdir(dir_path):
        return []
    pages = []
    for name in sorted(os.listdir(dir_path)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(dir_path, name)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            pages.append((name, f.read()))
    return pages


def _frontmatter_field(text, field):
    m = re.search(rf"^{field}:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


# 하네스 재초기화/관리용 메타·툴링 스킬 — 프로젝트 개발(바이브 코딩) 워크플로우가 아니므로
# wiki의 "워크플로우 스킬" 목록(LLM이 기능 개발 중 참조하는 페이지)에서 제외한다. 2026-07-23
# 이후 harness-init.md는 애초에 프로젝트에 배포하지 않지만, 과거 세션에서 수동으로 남은
# 사본이 있어도 여기서는 걸러진다.
META_SKILL_FILES = {"harness-init.md"}


def build_workflows(skills_dir):
    pages = [(f, t) for f, t in _read_dir_pages(skills_dir) if f not in META_SKILL_FILES]
    if not pages:
        return "# AI 워크플로우 스킬\n\n등록된 스킬이 없습니다.\n"

    toc = ["# AI 워크플로우 스킬\n", "이 프로젝트에서 개발 작업 중 호출할 수 있는 AI 워크플로우 스킬 목록이다 (업무 워크플로우 아님).\n",
           "| 스킬 | 설명 |", "|------|------|"]
    body = []
    for filename, text in pages:
        name = _frontmatter_field(text, "name") or os.path.splitext(filename)[0]
        desc = _frontmatter_field(text, "description")
        toc.append(f"| [{name}](#{name.lower()}) | {desc} |")
        body.append(f"---\n\n{text.strip()}\n")

    return "\n".join(toc) + "\n\n" + "\n".join(body)


def build_patterns(patterns_dir):
    pages = _read_dir_pages(patterns_dir)
    profile_path = os.path.join(patterns_dir, "pattern_profile.json")
    profile = None
    if os.path.isfile(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8-sig") as f:
                profile = json.load(f)
        except (OSError, json.JSONDecodeError):
            profile = None

    if not pages and not profile:
        return "# 패턴 가이드\n\n추출된 패턴이 없습니다.\n"

    toc = ["# 패턴 가이드\n"]
    body = []
    profiles = (profile or {}).get("profiles") or []
    if profiles:
        counts = {status: sum(1 for item in profiles if item.get("status") == status)
                  for status in ("preferred", "legacy", "anti_pattern")}
        toc.extend([
            "## 구조화 패턴 프로필",
            "",
            (f"> preferred {counts['preferred']}개 · legacy {counts['legacy']}개 · "
             f"anti-pattern {counts['anti_pattern']}개"),
            "",
            "| ID | 상태 | 모듈 / 레이어 | 신뢰도 | 실제 기준 파일 |",
            "|------|------|------|------|------|",
        ])
        for item in profiles:
            scope = item.get("scope") or {}
            refs = item.get("reference_files") or []
            ref_text = "<br>".join(f"`{ref.get('path', '')}`" for ref in refs if isinstance(ref, dict)) or "-"
            module_layer = f"{scope.get('module') or 'common'} / {scope.get('layer') or '-'}"
            toc.append(
                f"| {item.get('id', '')} | {item.get('status', '')} | {module_layer} | "
                f"{item.get('confidence', '')} | {ref_text} |"
            )

    if pages:
        toc.extend(["", "## 상세 패턴 문서", "", "| 패턴 | 파일 |", "|------|------|"])
    for filename, text in pages:
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else filename
        toc.append(f"| {title} | `{filename}` |")
        body.append(f"---\n\n{text.strip()}\n")

    return "\n".join(toc) + "\n\n" + "\n".join(body)


_OWASP_STATUS_ICON = {"발견": "🔴", "확인필요": "🟡", "미탐지": "⚪"}


def _owasp_table(owasp_json):
    if not owasp_json:
        return ""
    categories = owasp_json.get("categories") or []
    if not categories:
        return ""
    rows = ["| 카테고리 | 상태 | 발견 건수 | 대표 사례 |", "|------|------|------|------|"]
    for c in categories:
        findings = c.get("findings") or []
        icon = _OWASP_STATUS_ICON.get(c.get("status"), "")
        sample = ""
        if findings:
            f0 = findings[0]
            line = f0.get("line")
            loc = f"{f0.get('file', '')}:{line}" if line is not None else f0.get("file", "")
            sample = f"{loc} — {f0.get('evidence', '')}".strip(" —")
        rows.append(f"| {c.get('id', '')} {c.get('name', '')} | {icon} {c.get('status', '')} | {len(findings)} | {sample} |")
    return (
        "\n".join(rows)
        + "\n\n> '미탐지'는 코드에서 해당 패턴을 못 찾았다는 뜻이며, 취약점이 없다는 보증이 아니다."
        " '확인필요'는 정적 분석 한계로 사람 검토가 필요한 카테고리다(예: 의존성 CVE 대조).\n"
    )


def build_issues(validator_report_text, qa_report_text, dead_code_json, owasp_json=None):
    parts = ["# 이슈 & 보안\n"]
    owasp_table = _owasp_table(owasp_json)
    if owasp_table:
        parts.append(_section("OWASP Top 10 매핑", owasp_table))
    if validator_report_text:
        parts.append(_section("검증 리포트 (validator)", validator_report_text))
    if qa_report_text:
        parts.append(_section("QA 리포트", qa_report_text))

    if dead_code_json:
        rows = ["## 데드 코드 후보", "", "| 종류 | ID/파일 | 사유 |", "|------|------|------|"]
        for kind, key in (("method", "unused_methods"), ("sql", "unused_sql_ids"), ("jsp", "unused_jsps")):
            for item in dead_code_json.get(key, []):
                if isinstance(item, dict):
                    label = item.get("id") or item.get("symbol") or item.get("file", "")
                    reason = item.get("reason") or item.get("confidence", "")
                else:
                    label, reason = str(item), ""
                rows.append(f"| {kind} | {label} | {reason} |")
        if len(rows) > 4:
            parts.append("\n".join(rows) + "\n")

    if len(parts) == 1:
        parts.append("검증/QA 리포트가 없습니다.\n")
    return "\n".join(parts)


def has_api_data(contract_json):
    """provider(endpoints) + consumer(dynamic_sql_calls/hiway_rest_endpoints) 계약 둘 다 인식."""
    if not contract_json:
        return False
    return bool(
        contract_json.get("endpoints")
        or contract_json.get("dynamic_sql_calls")
        or contract_json.get("hiway_rest_endpoints")
    )


def _dynamic_sql_calls_md(calls):
    if not calls:
        return ""
    rows = ["| Method | Namespace | SQL ID | Purpose | Callers |", "|--------|-----------|--------|---------|---------|"]
    for c in calls:
        callers = c.get("callers", [])
        callers = ", ".join(callers) if isinstance(callers, list) else callers
        rows.append(
            f"| {c.get('method', '')} | {c.get('namespace', '')} | {c.get('sqlid', '')} | "
            f"{c.get('purpose', '')} | {callers} |"
        )
    return "\n".join(rows)


def _hiway_rest_endpoints_md(eps):
    if not eps:
        return ""
    rows = ["| Method | Path | File | Purpose |", "|--------|------|------|---------|"]
    for e in eps:
        rows.append(f"| {e.get('method', '')} | {e.get('path', '')} | {e.get('file', '')} | {e.get('purpose', '')} |")
    return "\n".join(rows)


def _api_endpoints_table(contract_json):
    if not contract_json:
        return ""
    endpoints = contract_json.get("endpoints", [])
    if endpoints:
        rows = ["| Method | Path | Handler | Auth | 설명 |", "|--------|------|---------|------|------|"]
        for ep in endpoints:
            # 키 자체가 없으면 "인증 불필요"가 아니라 "확인 안 됨"이다 (결정론적 인덱서는 이 값을 판정하지 않는다)
            auth = "✅" if ep.get("auth_required") else ("" if "auth_required" in ep else "-")
            # description은 analyzer가 _ai_patch.json의 set_endpoint_description으로 보강하는 선택 필드 —
            # 인덱서 단계에서는 없는 게 정상이라 빈 칸으로 둔다(강제 아님).
            rows.append(
                f"| {ep.get('method', '')} | {ep.get('path', '')} | "
                f"{ep.get('handler', '')} | {auth} | {ep.get('description', '')} |"
            )
        return "\n".join(rows)
    # consumer(frontend) 계약 — provider 라우트가 아니라 호출하는 namespace/sqlid·REST 목록
    parts = []
    note = contract_json.get("note")
    if note:
        parts.append(f"> {note}\n")
    dsc = _dynamic_sql_calls_md(contract_json.get("dynamic_sql_calls"))
    if dsc:
        total = contract_json.get("total_dynamic_sql_calls", len(contract_json.get("dynamic_sql_calls", [])))
        parts.append(f"#### 동적 SQL 호출 ({total}건)\n\n{dsc}")
    hre = _hiway_rest_endpoints_md(contract_json.get("hiway_rest_endpoints"))
    if hre:
        parts.append(f"#### Hiway REST 호출\n\n{hre}")
    return "\n\n".join(parts)


def build_api_endpoints(own_contract_json, partner_contract_json=None,
                         own_label="이 저장소", partner_label=None, partners=None):
    own_table = _api_endpoints_table(own_contract_json)
    parts = ["# API Endpoints\n"]
    parts.append(_section(own_label, own_table) if own_table else "API 계약 정보가 없습니다.\n")
    partner_table = _api_endpoints_table(partner_contract_json)
    if partner_table:
        parts.append(_section(f"파트너 ({partner_label or '연동 저장소'})", partner_table))
    for p in (partners or []):
        table = _api_endpoints_table(p.get("contract_json"))
        if table:
            parts.append(_section(f"파트너 ({p.get('label') or '연동 저장소'})", table))
    return "\n".join(p for p in parts if p)


def has_schema_data(schema_json):
    """index-spec 표준(tables) + 프로시저 중심 프로젝트의 대체 스키마
    (tables_directly_referenced/stored_procedures) 둘 다 인식."""
    if not schema_json:
        return False
    if schema_json.get("tables"):
        return True
    if schema_json.get("tables_directly_referenced"):
        return True
    sp = schema_json.get("stored_procedures")
    if isinstance(sp, dict) and any(
        k != "note" and isinstance(v, list) and v for k, v in sp.items()
    ):
        return True
    return False


FRONTEND_EXTERNAL_IO_KEYS = (
    "http_client", "backend_gateways", "vite_dev_proxy",
    "module_federation_remote", "external_scripts", "anti_patterns",
)


def has_external_data(io_json):
    """index-spec 표준(communications) + outbound/datastores(backend) +
    http_client/backend_gateways/...(frontend consumer) 셋 다 인식."""
    if not io_json:
        return False
    if io_json.get("communications") or io_json.get("outbound") or io_json.get("datastores"):
        return True
    return any(io_json.get(k) for k in FRONTEND_EXTERNAL_IO_KEYS)


def _stored_procedures_md(sp):
    if not sp or not isinstance(sp, dict):
        return ""
    out = []
    note = sp.get("note")
    if note:
        out.append(f"> {note}\n")
    for category, items in sp.items():
        if category == "note":
            continue
        if isinstance(items, list) and items and isinstance(items[0], dict):
            out.append(f"#### {category}")
            out.append("| Proc | IN | OUT | Note |")
            out.append("|------|----|----|------|")
            for it in items:
                if not isinstance(it, dict):
                    continue
                in_val = it.get("in", "")
                out_val = it.get("out", "")
                in_val = ", ".join(in_val) if isinstance(in_val, list) else in_val
                out_val = ", ".join(out_val) if isinstance(out_val, list) else out_val
                out.append(f"| {it.get('proc', '')} | {in_val} | {out_val} | {it.get('note', '')} |")
            out.append("")
        elif isinstance(items, list) and items:
            # proc/in/out으로 구조화되지 않은, 이름·시그니처 문자열 나열 스키마
            out.append(f"#### {category}")
            for it in items:
                out.append(f"- {it}")
            out.append("")
        elif isinstance(items, dict) and items:
            out.append(f"#### {category}")
            for k, v in items.items():
                out.append(f"- **{k}**: {v}")
            out.append("")
    return "\n".join(out)


def _tables_directly_referenced_md(refs):
    if not refs:
        return ""
    rows = ["| Table | Source | Columns | Confidence |", "|-------|--------|---------|------------|"]
    for t in refs:
        cols = t.get("columns_seen", [])
        cols = ", ".join(cols) if isinstance(cols, list) else cols
        rows.append(f"| {t.get('name', '')} | {t.get('source', '')} | {cols} | {t.get('confidence', '')} |")
    return "\n".join(rows)


def _database_tables_md(schema_json):
    if not schema_json:
        return ""
    parts = []

    tables = schema_json.get("tables", [])
    if tables:
        out = []
        for t in tables:
            out.append(f"### {t.get('name', '')}")
            cols = t.get("columns") or t.get("columns_seen", [])
            if cols:
                out.append("| 컬럼 | 타입 | Null | 기본값 | PK |")
                out.append("|------|------|------|--------|----|")
                pk_cols = set(t.get("primary_key", []))
                for c in cols:
                    is_pk = "✅" if c.get("name") in pk_cols or c.get("primary_key") else ""
                    out.append(
                        f"| {c.get('name', '')} | {c.get('type', '')} | "
                        f"{'NULL' if c.get('nullable') else 'NOT NULL'} | "
                        f"{c.get('default', '')} | {is_pk} |"
                    )
            fks = t.get("foreign_keys", [])
            for fk in fks:
                out.append(
                    f"- FK `{fk.get('name', '')}`: {', '.join(fk.get('columns', []))} → "
                    f"{fk.get('references_table', '')}({', '.join(fk.get('references_columns', []))})"
                )
            idxs = t.get("indexes", [])
            for idx in idxs:
                out.append(f"- INDEX `{idx.get('name', '')}`: {', '.join(idx.get('columns', []))}")
            source = t.get("source")
            if source:
                out.append(f"- 출처: {source}")
            keys_note = t.get("keys")
            if keys_note:
                out.append(f"- 키: {keys_note}")
            out.append("")
        parts.append("\n".join(out))

    # index-spec 표준 스키마와 별개로 tables_directly_referenced/stored_procedures가
    # 함께 있을 수 있다(프로시저 중심 프로젝트) — tables 존재 여부와 무관하게 항상 확인한다.
    refs_md = _tables_directly_referenced_md(schema_json.get("tables_directly_referenced"))
    if refs_md:
        parts.append("### 직접 참조 테이블\n\n" + refs_md)
    sp_md = _stored_procedures_md(schema_json.get("stored_procedures"))
    if sp_md:
        parts.append("### 저장 프로시저\n\n" + sp_md)
    # index-spec 표준 스키마의 views/procedures/functions/triggers (DDL에서 유도)
    for key, title in (("views", "뷰"), ("procedures", "프로시저"), ("functions", "함수"), ("triggers", "트리거")):
        items = schema_json.get(key)
        if items:
            parts.append(f"### {title}\n\n" + _generic_value_md(items))
    domain = schema_json.get("domain_inference")
    if domain:
        parts.append(f"### 도메인 추정\n\n{domain}")

    stats_md = _schema_stats_md(schema_json)
    if stats_md:
        parts.insert(0, stats_md)
    return "\n\n".join(parts)


def _schema_stats_md(schema_json):
    tables = schema_json.get("tables") or []
    if not tables:
        return ""
    fk_target_count = Counter()
    for t in tables:
        for fk in (t.get("foreign_keys") or []):
            fk_target_count[fk.get("references_table")] += 1
    top = fk_target_count.most_common(5)
    top_lines = "\n".join(f"- {name} (참조 FK {cnt}건)" for name, cnt in top) or "- (없음)"
    no_pk = sum(1 for t in tables if not t.get("primary_key"))
    return (
        f"### 요약\n\n- 테이블 {len(tables)}개, PK 없는 테이블 {no_pk}개\n"
        f"- FK가 많이 들어오는(참조당하는) 핵심 테이블 top5:\n{top_lines}"
    )


def _sql_usage_table(sql_usage_json):
    if not sql_usage_json:
        return ""
    sqls = sql_usage_json.get("sqls", [])
    if sqls:
        rows = ["| SQL ID | 타입 | 대상 테이블 |", "|--------|------|------------|"]
        for s in sqls:
            rows.append(f"| {s.get('id', '')} | {s.get('type', '')} | {', '.join(s.get('tables', []))} |")
        return "\n".join(rows)

    # index-spec 표준(sqls 평면 리스트)이 아닌 mapper XML 중심 스키마
    mappers = sql_usage_json.get("mappers", [])
    if mappers:
        parts = []
        note = sql_usage_json.get("note")
        if note:
            parts.append(f"> {note}\n")
        rows = ["| Mapper XML | Namespace | Statement | Type | Proc/Table | Used By | Note |",
                "|------------|-----------|-----------|------|------------|---------|------|"]
        for m in mappers:
            xml = m.get("xml", "")
            ns = m.get("namespace", "")
            for st in m.get("statements", []):
                used_by = st.get("used_by", [])
                used_by = ", ".join(used_by) if isinstance(used_by, list) else used_by
                target = st.get("proc") or st.get("result") or ""
                rows.append(
                    f"| {xml} | {ns} | {st.get('id', '')} | {st.get('type', '')} | "
                    f"{target} | {used_by or '-'} | {st.get('note', '')} |"
                )
        parts.append("\n".join(rows))
        summary = sql_usage_json.get("summary")
        if isinstance(summary, dict):
            s_lines = ["#### 요약"]
            for k, v in summary.items():
                if isinstance(v, dict):
                    s_lines.append(f"- **{k}**:")
                    for k2, v2 in v.items():
                        s_lines.append(f"  - {k2}: {v2}")
                else:
                    s_lines.append(f"- **{k}**: {v}")
            parts.append("\n".join(s_lines))
        return "\n\n".join(parts)
    return ""


def build_database(own_schema_json, own_sql_usage_json,
                    partner_schema_json=None, partner_sql_usage_json=None,
                    own_label="이 저장소", partner_label=None, partners=None):
    own_body = "\n\n".join(
        p for p in [_database_tables_md(own_schema_json), _sql_usage_table(own_sql_usage_json)] if p
    )
    parts = ["# Database\n"]
    parts.append(_section(own_label, own_body) if own_body else "DB 스키마 정보가 없습니다.\n")

    partner_body = "\n\n".join(
        p for p in [_database_tables_md(partner_schema_json), _sql_usage_table(partner_sql_usage_json)] if p
    )
    if partner_body:
        parts.append(_section(f"파트너 ({partner_label or '연동 저장소'})", partner_body))
    for p in (partners or []):
        body = "\n\n".join(
            b for b in [_database_tables_md(p.get("schema_json")), _sql_usage_table(p.get("sql_usage_json"))] if b
        )
        if body:
            parts.append(_section(f"파트너 ({p.get('label') or '연동 저장소'})", body))
    return "\n".join(p for p in parts if p)


def _outbound_md(outbound):
    if not outbound:
        return ""
    rows = ["| Kind | Target | Caller | File |", "|------|--------|--------|------|"]
    for c in outbound:
        if not isinstance(c, dict):
            continue
        target = c.get("target") or c.get("endpoint") or c.get("interface") or c.get("class") or ""
        rows.append(f"| {c.get('kind', '')} | {target} | {c.get('caller', '')} | {c.get('file', '')} |")
    return "\n".join(rows)


def _datastores_md(datastores):
    if not datastores:
        return ""
    out = []
    for d in datastores:
        if not isinstance(d, dict):
            continue
        out.append(f"#### {d.get('kind', '')}")
        for k, v in d.items():
            if k == "kind":
                continue
            if isinstance(v, dict):
                v = ", ".join(f"{kk}={vv}" for kk, vv in v.items())
            out.append(f"- **{k}**: {v}")
        out.append("")
    return "\n".join(out)


def _generic_value_md(v, indent=0):
    """schema를 미리 알 수 없는 임의 dict/list를 중첩 bullet로 렌더링하는 범용 폴백."""
    pad = "  " * indent
    if isinstance(v, dict):
        lines = []
        for k, vv in v.items():
            if isinstance(vv, (dict, list)) and vv:
                lines.append(f"{pad}- **{k}**:")
                lines.append(_generic_value_md(vv, indent + 1))
            else:
                lines.append(f"{pad}- **{k}**: {vv}")
        return "\n".join(lines)
    if isinstance(v, list):
        lines = []
        for item in v:
            if isinstance(item, dict):
                # 리스트 안의 dict는 항목 경계가 보이도록 별도 bullet으로 묶고 한 단계 들여쓴다
                # (안 그러면 여러 항목의 키가 한 덩어리로 이어붙어 어디까지가 한 항목인지 안 보임).
                lines.append(f"{pad}-")
                lines.append(_generic_value_md(item, indent + 1))
            elif isinstance(item, list):
                lines.append(_generic_value_md(item, indent))
            else:
                lines.append(f"{pad}- {item}")
        return "\n".join(lines)
    return f"{pad}{v}"


def _frontend_external_md(io_json):
    """provider(outbound/datastores)가 아닌 consumer(frontend) external_io 스키마
    (http_client/backend_gateways/vite_dev_proxy/module_federation_remote/external_scripts/anti_patterns)."""
    parts = []
    hc = io_json.get("http_client")
    if hc:
        parts.append("### HTTP Client\n\n" + _generic_value_md(hc))
    bg = io_json.get("backend_gateways")
    if bg:
        parts.append("### Backend Gateways\n\n" + _generic_value_md(bg))
    vdp = io_json.get("vite_dev_proxy")
    if vdp:
        rows = ["| Path | Target |", "|------|--------|"]
        for k, v in vdp.items():
            rows.append(f"| {k} | {v} |")
        parts.append("### Vite Dev Proxy\n\n" + "\n".join(rows))
    mfr = io_json.get("module_federation_remote")
    if mfr:
        parts.append("### Module Federation Remote\n\n" + _generic_value_md(mfr))
    es = io_json.get("external_scripts")
    if es:
        rows = ["| File | Resource | Load |", "|------|----------|------|"]
        for e in es:
            rows.append(f"| {e.get('file', '')} | {e.get('resource', '')} | {e.get('load', '')} |")
        parts.append("### External Scripts\n\n" + "\n".join(rows))
    ap = io_json.get("anti_patterns")
    if ap:
        parts.append("### Anti-patterns\n\n" + "\n".join(f"- {a}" for a in ap))
    return "\n\n".join(parts)


def _external_io_table(io_json):
    if not io_json:
        return ""
    comms = io_json.get("communications", [])
    if comms:
        parts = []
        # description은 analyzer가 _ai_patch.json의 set_communication_description으로 보강하는
        # 선택 필드 — 인덱서 단계에서는 없는 게 정상이라 빈 칸으로 둔다(강제 아님).
        rows = ["| Type | Target | File:Line | 설명 |", "|------|--------|-----------|------|"]
        for c in comms:
            target = c.get("target") or c.get("topic") or c.get("path_pattern") or c.get("system") or ""
            loc = f"{c.get('file', '')}:{c.get('line', '')}" if (c.get("file") or c.get("line")) else "-"
            rows.append(f"| {c.get('type', '')} | {target} | {loc} | {c.get('description', '')} |")
        parts.append("\n".join(rows))

        # communications는 요약이고, external_io에 시스템별 세부 정보(URL/자격증명/호출 위치 등)가
        # 별도 배열로 딸려 오는 스키마 — 있으면 이어붙인다.
        details = io_json.get("external_io")
        if isinstance(details, list) and details:
            det_parts = ["### 상세"]
            for item in details:
                if not isinstance(item, dict):
                    det_parts.append(f"- {item}")
                    continue
                title = item.get("system") or item.get("kind") or ""
                det_parts.append(f"#### {title}")
                det_parts.append(_generic_value_md({k: v for k, v in item.items() if k != "system"}))
            parts.append("\n\n".join(det_parts))
        return "\n\n".join(parts)
    # index-spec 표준(communications)이 아닌 backend(outbound/datastores) 스키마
    ob_md = _outbound_md(io_json.get("outbound"))
    ds_md = _datastores_md(io_json.get("datastores"))
    note = io_json.get("note")
    if ob_md or ds_md:
        parts = []
        if note:
            parts.append(f"> {note}\n")
        if ob_md:
            parts.append("### Outbound 통신\n\n" + ob_md)
        if ds_md:
            parts.append("### Datastores\n\n" + ds_md)
        return "\n\n".join(parts)
    # consumer(frontend) 스키마
    fe_md = _frontend_external_md(io_json)
    if not fe_md:
        return ""
    if note:
        fe_md = f"> {note}\n\n" + fe_md
    return fe_md


def build_external_systems(own_io_json, partner_io_json=None,
                            own_label="이 저장소", partner_label=None, partners=None):
    own_table = _external_io_table(own_io_json)
    parts = ["# External Systems\n"]
    parts.append(_section(own_label, own_table) if own_table else "외부 시스템 연동 정보가 없습니다.\n")
    partner_table = _external_io_table(partner_io_json)
    if partner_table:
        parts.append(_section(f"파트너 ({partner_label or '연동 저장소'})", partner_table))
    for p in (partners or []):
        table = _external_io_table(p.get("io_json"))
        if table:
            parts.append(_section(f"파트너 ({p.get('label') or '연동 저장소'})", table))
    return "\n".join(p for p in parts if p)
