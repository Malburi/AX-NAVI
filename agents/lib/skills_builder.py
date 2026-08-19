# harness 산출물(도메인 에이전트·패턴·CLAUDE.md·ito-guide)을 프로그램식으로 배포하는 zero-LLM 빌더
import os
import re
import sys
import json
import argparse
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 정적 워크플로우 스킬(analyze-impact/safe-modify/scaffold-feature/vibe/plan-migration/review-sql)은
# 프로젝트별 변수가 없는 고정 텍스트라 플러그인 전역판(skills/<name>/SKILL.md)만 두고, 대상
# 프로젝트에는 로컬 사본을 배포하지 않는다 — 플러그인이 설치된 이상 전역판이 어느 프로젝트에서든
# 그대로 트리거되므로 로컬 사본은 내용 동기화 부담만 늘리는 중복이다(2026-08-13 제거).
# 이 스크립트는 대신 이 6개가 "이 프로젝트에 적용 가능한지"만 판단해 CLAUDE.md 자동 워크플로우
# 표·ito-guide.md·02_writer_files.md에 이름으로 반영한다 — 4개(analyze-impact/safe-modify/
# scaffold-feature/vibe)는 항상 적용, plan-migration/review-sql은 writer_decisions.json의
# 판단(decision_for())을 따른다.
# CLAUDE.md는 골격(고정 워크플로우 표·변경이력 헤더)만 템플릿화하고 writer가 채운 소수 필드를
# claude_md_fields.json으로 넘겨받아 조립한다. domain-expert.md는 analyzer_report 그대로 복사.
# patterns/ 스켈레톤 헤더(레이어명/프로젝트명 외 고정 문구)와 02_writer_files.md 완료 보고서
# 서식도 고정 구조라 이 스크립트가 조립한다 — writer는 _workspace/writer_decisions.json
# (조건부 스킬 적용 여부+사유, 패턴 파일명 목록, 탐지 스택, 적용 결정 사유)만 출력한다.
# trace.md / scaffolder.md / find-logic.md 및 각 패턴 파일의 실제 본문(pattern-extractor 소관)은
# 프로젝트별 내용이 실제로 달라지므로 계속 LLM이 직접 작성한다 (이 스크립트 대상 아님).

LIB_DIR = os.path.dirname(os.path.abspath(__file__))

# "배포 목록"이 아니라 "가용성 판단 목록" — 로컬 파일을 만들지 않고 이름만 CLAUDE.md/ito-guide에 반영한다.
ALWAYS_AVAILABLE_SKILLS = {"analyze-impact", "safe-modify", "scaffold-feature", "vibe"}
CONDITIONAL_SKILLS = {"plan-migration": "plan_migration", "review-sql": "review_sql"}

SKELETON_MARKER = "pattern-extractor 에이전트가 채울 예정입니다"

DEFAULT_PATTERN_TARGETS = (
    "- 샘플 파일: [analyzer가 샘플링한 파일 경로]\n"
    "- 추출할 요소: [네이밍·구조·예외 처리·로깅 등]\n"
)

CLIENT_PATTERN_TARGETS = (
    "- 샘플 파일: [analyzer가 샘플링한 파일 경로]\n"
    "- JS↔JSP 매핑 (다대일 관계)\n"
    "- onInit/onSaveData 함수 규약\n"
    "- transData()/eval AJAX 계약 + 응답 형식\n"
    "- _gate/_ajax/_popup 파일 명명 규약\n"
    "- jQuery 버전 환경 및 $() 혼재 안티패턴\n"
)

SPECIAL_PATTERN_TARGETS = {
    "form_pattern.md": "- 샘플 Form/XFDL 파일과 partial/Script 파일\n- 화면 생명주기·컴포넌트 명명·초기화 순서\n- 서비스 호출과 오류 표시 규약\n",
    "designer_pattern.md": "- 샘플 *.Designer.cs와 대응 partial class\n- control 생성·배치·리소스·Dispose 규약\n- generated 영역 수동 편집 금지 범위\n",
    "ui_event_pattern.md": "- 이벤트 선언/결선과 handler 샘플\n- handler 명명·검증·service 위임·예외 표시 규약\n",
    "dataset_pattern.md": "- Dataset/Grid/DTO 샘플\n- column 명명·타입·입출력 매핑·상태 규약\n",
    "component_pattern.md": "- 샘플 component 파일\n- props/state·hook/composable·event·API client 규약\n",
}


def decision_for(skill_name, decisions):
    """writer_decisions.json에서 생성 여부를 읽는다.
    키가 없거나 decisions가 None이면 안전하게 미생성으로 처리한다."""
    if not decisions:
        return False
    key = skill_name.replace("-", "_")
    entry = decisions.get(key) or {}
    return bool(entry.get("generate"))


def _layer_label(filename):
    base = filename[:-len("_pattern.md")] if filename.endswith("_pattern.md") else filename
    return base.replace("_", " ").title()


def deploy_pattern_skeletons(root, analyzer_report_text, pattern_files):
    """writer.md '12+. patterns/ 파일 스켈레톤'의 고정 헤더 포맷으로 스켈레톤을 생성한다.
    이미 pattern-extractor가 채운(스켈레톤 마커가 없는) 파일은 덮어쓰지 않는다."""
    patterns_dir = os.path.join(root, ".claude", "patterns")
    os.makedirs(patterns_dir, exist_ok=True)

    names = list(pattern_files or [])
    if "LegacyStaticJS" in (analyzer_report_text or "") and "client_pattern.md" not in names:
        names.append("client_pattern.md")

    project_name = os.path.basename(os.path.normpath(root)) or "프로젝트"
    deployed = []
    for name in names:
        dst = os.path.join(patterns_dir, name)
        if os.path.isfile(dst):
            with open(dst, "r", encoding="utf-8-sig") as f:
                existing = f.read()
            if SKELETON_MARKER not in existing:
                continue
        targets = CLIENT_PATTERN_TARGETS if name == "client_pattern.md" else SPECIAL_PATTERN_TARGETS.get(name, DEFAULT_PATTERN_TARGETS)
        content = (
            f"# {_layer_label(name)} Pattern — {project_name}\n\n"
            f"> 이 파일은 {SKELETON_MARKER}.\n"
            '> 채우려면: "패턴 추출해줘" 또는 `pattern-extractor` 호출.\n\n'
            "## 추출 대상\n"
            f"{targets}"
        )
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        deployed.append(name)
    return deployed, names


def render_writer_files_report(root, decisions):
    """writer.md '완료 보고' 섹션(167-215줄)의 고정 포맷으로 02_writer_files.md를 조립한다."""
    pattern_files = decisions.get("pattern_files") or []
    pattern_list_md = "\n".join(f"- .claude/patterns/{name}" for name in pattern_files) or "- (없음)"

    def _decision_line(skill_name, key):
        entry = decisions.get(key) or {}
        verdict = "적용" if entry.get("generate") else "미적용"
        reason = (entry.get("reason") or "").strip() or "(사유 없음)"
        return f"- {skill_name}: {verdict} — {reason}"

    cross_scaffold_exists = os.path.isfile(os.path.join(root, ".claude", "skills", "cross-repo-scaffold.md"))
    cross_modify_exists = os.path.isfile(os.path.join(root, ".claude", "skills", "cross-repo-modify.md"))

    applied = decisions.get("applied_decisions") or []
    applied_md = "\n".join(f"- {item}" for item in applied) or "- (해당 없음)"

    content = (
        "=== WRITER COMPLETE (Enhanced) ===\n\n"
        "생성된 파일:\n\n"
        "[Core — writer 직접 작성]\n"
        "- _workspace/claude_md_fields.json           (CLAUDE.md 필드 — 아래 skills_builder.py가 조립)\n"
        "- .claude/skills/trace.md\n"
        "- .claude/skills/scaffolder.md\n"
        "- .claude/skills/find-logic.md\n\n"
        "[skills_builder.py가 뒤이어 배포 — 여기 안 씀]\n"
        "- CLAUDE.md                                 (claude_md_fields.json + 템플릿 조립)\n"
        "- .claude/agents/domain-expert.md           (analyzer_report 복사)\n"
        "- .claude/patterns/[목록]                    (스켈레톤 — skills_builder.py가 조립, 아래 목록 참조)\n"
        "- .claude/ito-guide.md                      (사용 설명서 조립)\n\n"
        "[워크플로우 스킬 — 플러그인 전역판만 사용, 로컬 배포 없음]\n"
        "- analyze-impact / safe-modify / scaffold-feature / vibe (항상 사용 가능)\n"
        f"{_decision_line('plan-migration', 'plan_migration')}\n"
        f"{_decision_line('review-sql', 'review_sql')}\n\n"
        "[Workflow Skills — writer 직접 작성]\n"
        f"- .claude/skills/cross-repo-scaffold.md     ({'생성됨' if cross_scaffold_exists else '미생성 — pair_config.md 없음'})\n"
        f"- .claude/skills/cross-repo-modify.md       ({'생성됨' if cross_modify_exists else '미생성 — pair_config.md 없음'})\n\n"
        "[Pattern Skeletons — pattern-extractor가 채울 예정]\n"
        f"{pattern_list_md}\n\n"
        f"탐지 스택: {decisions.get('detected_stack', '미상')}\n"
        f"분석 신뢰도: {decisions.get('confidence', '미상')}\n\n"
        "선택적 스킬 적용 결정:\n"
        f"- cross-repo-scaffold.md: {'생성' if cross_scaffold_exists else '미생성'} — pair_config.md 존재 여부\n"
        f"- cross-repo-modify.md: {'생성' if cross_modify_exists else '미생성'} — pair_config.md 존재 여부\n"
        "(plan-migration/review-sql 적용 여부는 위 \"워크플로우 스킬\" 블록 참조)\n\n"
        "적용 결정 사유:\n"
        f"{applied_md}\n\n"
        "다음 권장 단계:\n"
        "- pattern-extractor 호출하여 패턴 스켈레톤 채우기\n\n"
        "=== END ===\n"
    )

    out_path = os.path.join(root, "_workspace", "02_writer_files.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path


DOMAIN_EXPERT_DESC = (
    "{project_name} 프로젝트의 코드베이스 분석 결과(스택·아키텍처·의존성·데이터 흐름·"
    "트랜잭션·외부 통신)를 전부 갖고 있는 도메인 지식 에이전트. 비즈니스 로직·아키텍처 "
    "관련 질문이나 다른 에이전트가 프로젝트 맥락이 필요할 때 참조한다."
)


def deploy_domain_expert(root):
    """domain-expert.md = _workspace/01_analyzer_report.md를 시스템 프롬프트에 주입한 파일.
    writer가 같은 내용을 다시 타이핑해 출력하는 건 100% 중복 낭비이므로, 여기서 파일 복사로 만든다."""
    report_path = os.path.join(root, "_workspace", "01_analyzer_report.md")
    if not os.path.isfile(report_path):
        print(f"WARN: {report_path} 없음 — domain-expert.md 스킵 (analyzer가 01_analyzer_report.md를 먼저 생성해야 함)", file=sys.stderr)
        return False

    with open(report_path, "r", encoding="utf-8-sig") as f:
        report = f.read()

    project_name = os.path.basename(os.path.normpath(root)) or "프로젝트"
    frontmatter = (
        "---\n"
        "name: domain-expert\n"
        f"description: {DOMAIN_EXPERT_DESC.format(project_name=project_name)}\n"
        "---\n\n"
        f"# Domain Expert — {project_name}\n\n"
        "> 이 파일은 `_workspace/01_analyzer_report.md`를 그대로 주입한 것입니다. "
        "코드 변경 후 `\"인덱스만 갱신해줘\"`로 analyzer를 재실행하면 이 파일도 함께 갱신하세요.\n\n"
        "---\n\n"
    )

    agents_dir = os.path.join(root, ".claude", "agents")
    os.makedirs(agents_dir, exist_ok=True)
    with open(os.path.join(agents_dir, "domain-expert.md"), "w", encoding="utf-8") as f:
        f.write(frontmatter + report)
    return True


def parse_pair_config(root):
    """_workspace/pair_config.md (단순 key: value 마크다운) 파싱. 없으면 None.
    hub-roots(1:N) 형식 파일도 최상단 공통 키(project_type/init_mode/linked_at)는 읽히지만
    partner_root 등은 '## Partner:' 블록 안에만 있어 여기엔 안 잡힌다 — 그건 parse_pair_config_partners() 몫."""
    path = os.path.join(root, "_workspace", "pair_config.md")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
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
    """hub-roots(1:N, 예: 백엔드+웹+모바일+관리자) pair_config.md의 '## Partner: label' 블록들을
    각각 파싱해 리스트로 반환. paired-roots(1:1, flat 형식)나 파일 자체가 없으면 빈 리스트.
    라인 단위로 블록을 나눈다 (정규식 하나로 MULTILINE '$' + DOTALL '.'을 같이 쓰면 그리디
    매칭이 파일 끝까지 삼켜버리는 문제가 있어 일부러 피함)."""
    path = os.path.join(root, "_workspace", "pair_config.md")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    if "## Partner:" not in text:
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


def build_partner_section(root):
    """pair_config.md가 있으면 '## 파트너 프로젝트' 섹션을 그 필드값만으로 조립한다 (LLM 불필요 — 전부 pair_config.md에 이미 있는 값).
    1:1(paired-roots)과 1:N(hub-roots, 클라이언트 여러 개)을 서식만 다르게 조립한다."""
    partners = parse_pair_config_partners(root)
    if partners:
        rows = "\n".join(
            f"| {p.get('label', '미상')} | {p.get('partner_root', '미상')} | {p.get('partner_stack', '미상')} |"
            for p in partners
        )
        return (
            f"\n## 파트너 프로젝트들 (클라이언트 {len(partners)}개)\n\n"
            "| 역할 라벨 | 경로 | 스택 |\n"
            "|---|---|---|\n"
            f"{rows}\n\n"
            "- API 계약: `_workspace/index/api_contract.json` (클라이언트 전체가 공유)\n\n"
            "### 크로스 리포 워크플로우\n"
            "| 상황 | 명령 |\n"
            "|------|------|\n"
            '| 전체 스택 기능 동시 생성 (클라이언트 선택) | "전체 스택 기능 만들어줘" → cross-repo-scaffold |\n'
            '| 기존 기능 개선/수정 (클라이언트 선택) | "이 기능 개선해줘" → cross-repo-modify |\n'
            '| API 변경 전 클라이언트 영향 확인 | "영향도 분석해줘" → analyze-impact |\n'
            '| API 드리프트 재확인 (전체) | "API 드리프트 확인해줘" → pair-init 재실행 |\n'
            '| 클라이언트 추가 | "[새 역할] 클라이언트 추가해줘" → pair-init 재실행 |\n\n'
        )

    cfg = parse_pair_config(root)
    if not cfg:
        return ""
    return (
        f"\n## 파트너 프로젝트 ({cfg.get('partner_type', '미상')})\n\n"
        f"- 파트너 경로: {cfg.get('partner_root', '미상')}\n"
        f"- 스택: {cfg.get('partner_stack', '미상')}\n"
        f"- API 계약: `{cfg.get('api_contract_path', '_workspace/index/api_contract.json')}`\n"
        f"- 연동일: {cfg.get('linked_at', '미상')}\n\n"
        "### 크로스 리포 워크플로우\n"
        "| 상황 | 명령 |\n"
        "|------|------|\n"
        '| 전체 스택 기능 동시 생성 | "전체 스택 기능 만들어줘" → cross-repo-scaffold |\n'
        '| 기존 기능 개선/수정 양쪽 반영 | "이 기능 개선해줘 (프론트도 같이)" → cross-repo-modify |\n'
        '| API 변경 전 파트너 영향 확인 | "영향도 분석해줘" → analyze-impact |\n'
        '| API 드리프트 재확인 | "API 드리프트 확인해줘" → pair-init 재실행 |\n'
        '| 프론트 서비스 스텁만 생성 | "프론트 스텁 만들어줘" → api-bridge |\n\n'
    )


def deploy_claude_md(root):
    """writer가 낸 _workspace/claude_md_fields.json(소수 필드) + claude_md.md.template(고정 골격)를
    조립해 CLAUDE.md를 만든다. 워크플로우 표·변경이력 헤더처럼 프로젝트 무관 고정 텍스트를
    writer가 매번 재작성하던 부분을 없앤 것 — 서술형 필드 값 자체는 여전히 writer(LLM)가 채운다."""
    fields_path = os.path.join(root, "_workspace", "claude_md_fields.json")
    if not os.path.isfile(fields_path):
        print(f"WARN: {fields_path} 없음 — CLAUDE.md 스킵 (writer가 claude_md_fields.json을 먼저 생성해야 함)", file=sys.stderr)
        return False

    template_path = os.path.join(LIB_DIR, "claude_md.md.template")
    if not os.path.isfile(template_path):
        print(f"WARN: 템플릿 없음 — {template_path}", file=sys.stderr)
        return False

    with open(fields_path, "r", encoding="utf-8-sig") as f:
        fields = json.load(f)
    with open(template_path, "r", encoding="utf-8-sig") as f:
        template = f.read()

    project_name = fields.get("project_name") or os.path.basename(os.path.normpath(root)) or "프로젝트"

    content = (
        template
        .replace("{{PROJECT_NAME}}", project_name)
        .replace("{{ONE_LINE_DESC}}", fields.get("one_line_desc", ""))
        .replace("{{TECH_STACK_SUMMARY}}", fields.get("tech_stack_summary", ""))
        .replace("{{REQUEST_FLOW}}", fields.get("request_flow", ""))
        .replace("{{FILE_LOCATIONS_ROWS}}", fields.get("file_locations_rows", ""))
        .replace("{{BUILD_RUN}}", fields.get("build_run", ""))
        .replace("{{CAUTIONS}}", fields.get("cautions", ""))
        .replace("{{PARTNER_SECTION}}", build_partner_section(root))
        .replace("{{GENERATION_DATE}}", datetime.now().strftime("%Y-%m-%d"))
    )

    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write(content)
    return True


def deploy_agents_md(root):
    """agents.md.template(프로젝트 무관 정적 진입점)를 대상 루트에 AGENTS.md로 복사한다.
    필드 치환 없이 그대로 쓴다 — 세션 진입 시 먼저 읽는 초경량 규약(인덱스 조회·로컬 검증 우선)이라
    프로젝트별로 달라질 내용이 없다. 캐싱 접두사로서 모든 프로젝트에서 동일해야 한다."""
    template_path = os.path.join(LIB_DIR, "agents.md.template")
    if not os.path.isfile(template_path):
        print(f"WARN: 템플릿 없음 — {template_path}", file=sys.stderr)
        return False
    with open(template_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8") as f:
        f.write(content)
    return True


ITO_TEMPLATE = os.path.join(LIB_DIR, "ito_guide.md.template")

# ito-guide 스킬 섹션 나열 순서 (존재하는 스킬만 포함)
ITO_SKILL_ORDER = [
    "trace", "find-logic", "scaffolder",
    "analyze-impact", "safe-modify", "scaffold-feature", "vibe",
    "plan-migration", "review-sql",
    "cross-repo-scaffold", "cross-repo-modify",
]
# writer가 프로젝트별로 작성하는 스킬 — description에서 용도/트리거를 추출해 블록 플레이스홀더를 채운다
ITO_DYNAMIC_PREFIX = {"trace": "TRACE", "find-logic": "FINDLOGIC", "scaffolder": "SCAFFOLDER"}


def _skill_description(root, skill_name):
    path = os.path.join(root, ".claude", "skills", f"{skill_name}.md")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _usage_and_triggers(desc):
    """스킬 frontmatter description에서 용도 한 줄과 따옴표 트리거 예시(최대 3개)를 뽑는다."""
    if not desc:
        return "(설명 없음 — 스킬 파일 참조)", '- (트리거 예시는 스킬 파일 참조)'
    quoted = re.findall(r'"([^"]+)"', desc)
    usage = desc.split('"')[0].strip().rstrip('.,;— ') or desc[:80]
    triggers = "\n".join(f'- `"{q}"`' for q in quoted[:3]) or '- (트리거 예시는 스킬 파일 참조)'
    return usage, triggers


def _parse_ito_template(template_text):
    """본문과 <!-- SKILL:name --> 블록들을 분리한다."""
    body, _, blocks_part = template_text.partition("<!-- ===================== SKILL BLOCKS")
    blocks = {}
    for m in re.finditer(r"<!-- SKILL:([\w-]+) -->\n(.*?)(?=\n<!-- SKILL:|\Z)", blocks_part, re.DOTALL):
        blocks[m.group(1)] = m.group(2).strip("\n")
    return body.rstrip() + "\n", blocks


def _build_scenarios(root, decisions, pair_cfg):
    """규칙 기반 실전 시나리오 — 배포된 스킬 조합으로 결정 (LLM 판단 불필요)."""
    scenarios = [
        ("신규 기능 추가", "추출된 컨벤션(패턴 파일)을 따라 보일러플레이트와 테스트 골격까지 생성합니다.",
         "scaffold-feature", '"[기능명] 패턴대로 만들어줘"'),
        ("기존 코드 수정 전 영향 확인", "수정 대상의 호출처·트랜잭션·외부 통신 영향을 인덱스로 먼저 확인한 뒤 안전하게 적용합니다.",
         "analyze-impact → safe-modify", '"이 함수 수정하면 어디 영향 있어?" → "이 변경 안전하게 적용해줘"'),
    ]
    if decision_for("review-sql", decisions):
        scenarios.append(("SQL 수정·리뷰", "SQL 사용처 역추적, N+1, 인젝션, 트랜잭션 적정성을 한 번에 점검합니다.",
                          "review-sql", '"이 쿼리 리뷰해줘"'))
    pattern_files = (decisions or {}).get("pattern_files") or []
    if "client_pattern.md" in pattern_files:
        scenarios.append(("화면 오류 추적", "화면 이벤트에서 시작해 Controller → Service → DB까지 처리 흐름을 따라가며 원인 지점을 좁힙니다.",
                          "trace / find-logic", '"이 화면 저장 버튼 누르면 뭐가 실행돼?"'))
    if pair_cfg or parse_pair_config_partners(root):
        scenarios.append(("파트너 저장소 동시 수정", "API 계약을 건드리는 변경을 파트너(들) 저장소까지 함께 반영해 드리프트를 막습니다.",
                          "cross-repo-modify", '"이 API 바꾸는데 프론트 영향 있으면 같이 처리해줘"'))
    md = []
    for i, (title, desc, skills, trigger) in enumerate(scenarios, 1):
        md.append(f"### 시나리오 {i} — {title}\n\n{desc}\n\n- 사용 스킬: `{skills}`\n- 예시: {trigger}\n")
    return "\n".join(md)


def deploy_ito_guide(root, decisions):
    """ito_guide.md.template + 이미 배포된 스킬/필드 값만으로 .claude/ito-guide.md를 조립한다 (zero-LLM).
    기존에는 sonnet Agent가 매 초기화마다 처음부터 작성하던 문서 — 전 항목이 이미 있는 산출물의 재진술이라 기계화."""
    if not os.path.isfile(ITO_TEMPLATE):
        print(f"WARN: 템플릿 없음 — {ITO_TEMPLATE} — ito-guide.md 스킵", file=sys.stderr)
        return False
    with open(ITO_TEMPLATE, "r", encoding="utf-8-sig") as f:
        template = f.read()
    body, blocks = _parse_ito_template(template)

    fields = {}
    fields_path = os.path.join(root, "_workspace", "claude_md_fields.json")
    if os.path.isfile(fields_path):
        try:
            with open(fields_path, "r", encoding="utf-8-sig") as f:
                fields = json.load(f)
        except json.JSONDecodeError:
            pass

    pair_cfg = parse_pair_config(root)
    hub_partners = parse_pair_config_partners(root)
    project_name = fields.get("project_name") or os.path.basename(os.path.normpath(root)) or "프로젝트"

    sections, n = [], 0
    for name in ITO_SKILL_ORDER:
        if name not in blocks:
            continue
        if name in ALWAYS_AVAILABLE_SKILLS:
            available = True
        elif name in CONDITIONAL_SKILLS:
            available = decision_for(name, decisions)
        else:
            available = os.path.isfile(os.path.join(root, ".claude", "skills", f"{name}.md"))
        if not available:
            continue
        n += 1
        block = blocks[name].replace("{{N}}", str(n))
        prefix = ITO_DYNAMIC_PREFIX.get(name)
        if prefix:
            usage, triggers = _usage_and_triggers(_skill_description(root, name))
            block = block.replace(f"{{{{{prefix}_USAGE}}}}", usage).replace(f"{{{{{prefix}_TRIGGERS}}}}", triggers)
        if hub_partners:
            labels = ", ".join(p.get("label", "미상") for p in hub_partners)
            block = (block.replace("{{PARTNER_ROOT}}", f"클라이언트 {len(hub_partners)}개 — CLAUDE.md 파트너 섹션 참조")
                          .replace("{{PARTNER_TYPE}}", labels))
        elif pair_cfg:
            block = (block.replace("{{PARTNER_ROOT}}", pair_cfg.get("partner_root", "미상"))
                          .replace("{{PARTNER_TYPE}}", pair_cfg.get("partner_type", "미상")))
        sections.append(block)

    pattern_files = (decisions or {}).get("pattern_files") or []
    patterns_rows = "\n".join(
        f"| `{name}` | {_layer_label(name)} 레이어 컨벤션 (올바른 패턴 + 안티패턴 + 코드 예시) | `scaffold-feature`, `safe-modify` |"
        for name in pattern_files
    ) or "| (없음) | — | — |"

    api_row = ""
    if os.path.isfile(os.path.join(root, "_workspace", "index", "api_contract.json")):
        api_row = "| `api_contract.json` | REST API 계약 (경로·메서드·요청/응답 스키마) | `api-bridge`, `cross-repo-*` |"

    cautions = (fields.get("cautions") or "").strip() or "(CLAUDE.md의 \"작업 시 주의사항\" 섹션을 참조하세요.)"

    content = (
        body
        .replace("{{PROJECT_NAME}}", project_name)
        .replace("{{HEADER_DESC}}", "harness-init이 생성한 하네스(스킬·에이전트·패턴·인덱스)의 사용 설명서입니다.")
        .replace("{{STACK_LINE}}", (decisions or {}).get("detected_stack", "미상"))
        .replace("{{PROJECT_ROOT}}", root.replace("\\", "/"))
        .replace("{{SKILL_SECTIONS}}", "\n\n".join(sections) or "(생성된 스킬 없음)")
        .replace("{{PATTERNS_TABLE_ROWS}}", patterns_rows)
        .replace("{{API_CONTRACT_ROW}}", api_row)
        .replace("{{SCENARIOS_MD}}", _build_scenarios(root, decisions, pair_cfg))
        .replace("{{CAUTIONS_MD}}", cautions)
    )

    claude_dir = os.path.join(root, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    with open(os.path.join(claude_dir, "ito-guide.md"), "w", encoding="utf-8") as f:
        f.write(content)
    return True


def main():
    parser = argparse.ArgumentParser(description="Harness domain-expert.md + CLAUDE.md + 패턴 스켈레톤 + ito-guide.md + 02_writer_files.md 배포기")
    parser.add_argument("--root", required=True, help="프로젝트 루트 절대 경로")
    parser.add_argument("--summary", default=None,
                        help="writer_decisions.json 경로 (기본: [root]/_workspace/writer_decisions.json)")
    args = parser.parse_args()
    if not args.summary:
        args.summary = os.path.join(args.root, "_workspace", "writer_decisions.json")

    decisions = None
    if os.path.isfile(args.summary):
        with open(args.summary, "r", encoding="utf-8-sig") as f:
            try:
                decisions = json.load(f)
            except json.JSONDecodeError:
                print(f"WARN: {args.summary} JSON 파싱 실패 — 조건부 스킬 적용 판단/패턴 스켈레톤/02_writer_files.md 스킵", file=sys.stderr)
    else:
        print(f"WARN: 요약 파일 없음 ({args.summary}) — 조건부 스킬(plan-migration/review-sql) 적용 판단·패턴 스켈레톤·02_writer_files.md는 스킵", file=sys.stderr)

    print(f"사용 가능(플러그인 전역, 로컬 배포 없음): {', '.join(sorted(ALWAYS_AVAILABLE_SKILLS))}")
    applicable = [n for n in CONDITIONAL_SKILLS if decision_for(n, decisions)]
    skipped = [n for n in CONDITIONAL_SKILLS if n not in applicable]
    if applicable:
        print(f"적용 대상(플러그인 전역, 로컬 배포 없음): {', '.join(applicable)}")
    if skipped:
        print(f"조건 미충족: {', '.join(skipped)}")

    if deploy_domain_expert(args.root):
        print("배포 완료: domain-expert.md (analyzer_report 복사)")

    if deploy_claude_md(args.root):
        print("배포 완료: CLAUDE.md (claude_md_fields.json + 템플릿 조립)")

    if deploy_agents_md(args.root):
        print("배포 완료: AGENTS.md (정적 경량 진입점)")

    ito_decisions = decisions

    if decisions:
        report_path = os.path.join(args.root, "_workspace", "01_analyzer_report.md")
        analyzer_report_text = ""
        if os.path.isfile(report_path):
            with open(report_path, "r", encoding="utf-8-sig") as f:
                analyzer_report_text = f.read()

        deployed_patterns, final_pattern_list = deploy_pattern_skeletons(
            args.root, analyzer_report_text, decisions.get("pattern_files") or []
        )
        if deployed_patterns:
            print(f"배포 완료: 패턴 스켈레톤 {len(deployed_patterns)}개 ({', '.join(deployed_patterns)})")

        decisions_for_report = dict(decisions)
        decisions_for_report["pattern_files"] = final_pattern_list
        ito_decisions = decisions_for_report
        out_path = render_writer_files_report(args.root, decisions_for_report)
        print(f"배포 완료: 02_writer_files.md ({out_path})")

    try:
        if deploy_ito_guide(args.root, ito_decisions):
            print("배포 완료: .claude/ito-guide.md (템플릿 조립, zero-LLM)")
    except Exception as e:
        print(f"WARN: ito-guide.md 조립 실패 — {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
