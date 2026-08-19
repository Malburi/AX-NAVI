"""docsify_convert.py — 기존 wiki 폴더를 Docsify 형태로 일괄 변환.

LLM 호출 없이 Python만으로 처리. wiki_generator.py가 이미 생성한 *.md 파일을
그대로 두고, index.html / _sidebar.md / _navbar.md / serve.bat 만 교체/생성한다.

사용법:
    python docsify_convert.py --wiki-dir "E:\\AI\\M_frontend\\wiki" \\
        --project-name "MFS Wiki — 법인카드 비용처리 시스템"

[2026-07-15] harness-init 토큰 절감 리팩토링으로 wiki_generator.py가 단순 정적
HTML을 생성하게 됐을 때 기존 wiki를 Docsify로 변환하기 위해 작성.
향후 wiki_generator.py가 Docsify를 자동 생성하므로, 이 스크립트는 레거시 wiki
변환 또는 수동 재변환 용도로만 필요하다.
"""

import argparse
import html as html_mod
import os
import re
import sys

# 페이지 slug → (사이드바 레이블, 섹션)
# "workflows"는 업무 워크플로우(예: 예약 취소 처리 흐름)가 아니라 이 프로젝트에서 쓸 수 있는
# AI 개발 워크플로우 스킬(analyze-impact/safe-modify/scaffold-feature 등) 목록이다 — "시스템
# 개요"에 묶으면 실제 아키텍처와 혼동되므로 별도 "AI 도구" 섹션으로 분리한다.
PAGE_META = {
    "Home":             ("홈", None),
    # overview는 유일한 LLM 생성 페이지(선택) — 01_analyzer_report.md 재활용 내러티브.
    # 파일이 없으면 사이드바에서 자동 제외되므로 zero-LLM 실행에는 영향 없다.
    "overview":         ("시스템 해설 (AI)", "시스템 개요"),
    "domain":           ("도메인 개요", "시스템 개요"),
    "architecture":     ("아키텍처", "시스템 개요"),
    "workflows":        ("AI 워크플로우 스킬", "AI 도구"),
    "support-status":   ("유지보수 지원 현황", "AI 도구"),
    "database":         ("데이터베이스", "데이터"),
    "external-systems": ("외부 시스템", "데이터"),
    "api-endpoints":    ("전체 API 엔드포인트", "API 레퍼런스"),
    "patterns":         ("패턴 가이드", "코드 컨벤션"),
    "issues":           ("이슈 & 보안", "분석 리포트"),
}

SECTION_ORDER = ["시스템 개요", "AI 도구", "데이터", "API 레퍼런스", "코드 컨벤션", "분석 리포트"]


def render_index(project_name: str) -> str:
    safe = html_mod.escape(project_name)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{safe}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/docsify-themeable@0/dist/css/theme-simple.css">
  <style>
    :root {{
      --theme-color: #2563eb;
      --base-font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --base-font-size: 15px;
      --sidebar-width: 280px;
      --content-max-width: 960px;
      --heading-font-weight: 700;
      --sidebar-background: #0f172a;
      --sidebar-name-color: #ffffff;
      --sidebar-nav-link-color: #cbd5e1;
      --sidebar-nav-link-color--active: #38bdf8;
      --sidebar-nav-link-color--hover: #ffffff;
      --base-line-height: 1.7;
      --heading-h1-color: #0f172a;
      --heading-h2-color: #1e293b;
      --heading-h3-color: #334155;
      --blockquote-border-color: #3b82f6;
      --blockquote-background: #eff6ff;
    }}
    .sidebar-nav > ul > li > p {{
      font-size: 11px; text-transform: uppercase;
      letter-spacing: 0.6px; color: #64748b;
      margin: 16px 0 4px 12px;
    }}
    table {{ border-collapse: separate; border-spacing: 0; border-radius: 8px; overflow: hidden; }}
    th {{ background: #f8fafc; }}
    td, th {{ padding: 10px 14px; }}
    blockquote {{ border-radius: 0 8px 8px 0; }}
  </style>
</head>
<body>
  <div id="app">로딩 중...</div>
  <script>
    window.$docsify = {{
      name: '📋 {safe}',
      repo: '',
      homepage: 'Home.md',
      loadSidebar: true,
      loadNavbar: true,
      subMaxLevel: 3,
      auto2top: true,
      executeScript: false,
      search: {{
        maxAge: 86400000,
        paths: 'auto',
        placeholder: '문서 검색...',
        noData: '검색 결과가 없습니다.',
        depth: 6,
        hideOtherSidebarContent: false
      }},
      pagination: {{
        previousText: '← 이전',
        nextText: '다음 →',
        crossChapter: true,
      }},
      copyCode: {{
        buttonText: '복사',
        errorText: '오류',
        successText: '복사됨 ✓'
      }},
      themeColor: '#2563eb',
    }}
  </script>
  <script src="https://cdn.jsdelivr.net/npm/docsify@4/lib/docsify.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/docsify@4/lib/plugins/search.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/docsify-copy-code@2/dist/docsify-copy-code.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/docsify-pagination/dist/docsify-pagination.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-python.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-javascript.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-bash.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-sql.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/prismjs@1/components/prism-json.min.js"></script>
</body>
</html>"""


_SLUGIFY_PUNCT_RE = re.compile(r"[()\[\]{}'\"!#$%&*+,./:;<=>?@\^`|~]")


def slugify(text: str) -> str:
    """Docsify가 heading에서 만드는 앵커 id 규칙(구두점 제거 + 공백->대시)의 근사치."""
    text = _SLUGIFY_PUNCT_RE.sub("", text.strip().lower())
    return re.sub(r"\s+", "-", text)


def build_sidebar(project_name: str, present_slugs: set, has_call_graph: bool,
                   frontend_merged_slugs=None, partner_label=None) -> str:
    lines = [f"- [{project_name} 홈](/)\n"]
    sections: dict[str, list[str]] = {s: [] for s in SECTION_ORDER}
    frontend_merged_slugs = frontend_merged_slugs or []
    anchor_id = slugify(f"파트너 ({partner_label or '연동 저장소'})")

    for slug, (label, section) in PAGE_META.items():
        if slug == "Home" or section is None:
            continue
        if slug not in present_slugs:
            continue
        sections[section].append(f"  - [{label}](/{slug})\n")
        if slug in frontend_merged_slugs:
            sections[section].append(f"    - [↳ 파트너 ({partner_label or '연동 저장소'})](/{slug}?id={anchor_id})\n")

    if has_call_graph:
        sections["분석 리포트"].append("  - [호출 그래프 ↗](/call-graph.html ':ignore')\n")

    for section in SECTION_ORDER:
        items = sections[section]
        if items:
            lines.append(f"- **{section}**\n")
            lines.extend(items)

    return "".join(lines)


def build_navbar(present_slugs: set, has_call_graph: bool) -> str:
    lines = ["- [홈](/)\n"]
    if "api-endpoints" in present_slugs:
        lines += ["- API\n", "  - [전체 엔드포인트](/api-endpoints)\n"]
    analysis = []
    if "issues" in present_slugs:
        analysis.append("  - [이슈 & 보안](/issues)\n")
    if has_call_graph:
        analysis.append("  - [호출 그래프](/call-graph.html ':ignore')\n")
    if analysis:
        lines.append("- 분석\n")
        lines.extend(analysis)
    return "".join(lines)


def serve_bat_content(port: int = 3501) -> str:
    return f"@echo off\npython -m http.server {port}\n"


def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="기존 wiki 폴더를 Docsify 형태로 변환")
    parser.add_argument("--wiki-dir", required=True, help="변환할 wiki 폴더 절대경로")
    parser.add_argument("--project-name", default="", help="Docsify name: 제목 (기본: 폴더명)")
    parser.add_argument("--port", type=int, default=3501, help="serve.bat 포트 (기본: 3501)")
    args = parser.parse_args()

    wiki_dir = os.path.abspath(args.wiki_dir)
    if not os.path.isdir(wiki_dir):
        print(f"오류: 폴더 없음 — {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    project_name = args.project_name or os.path.basename(os.path.dirname(wiki_dir))

    # 존재하는 .md 파일 slug 수집
    md_files = [f for f in os.listdir(wiki_dir) if f.endswith(".md") and not f.startswith("_")]
    present_slugs = {os.path.splitext(f)[0] for f in md_files}
    has_call_graph = os.path.exists(os.path.join(wiki_dir, "call-graph.html"))

    # index.html (Docsify)
    write(os.path.join(wiki_dir, "index.html"), render_index(project_name))
    print("[OK] index.html (Docsify)")

    # _sidebar.md
    write(os.path.join(wiki_dir, "_sidebar.md"), build_sidebar(project_name, present_slugs, has_call_graph))
    print("[OK] _sidebar.md")

    # _navbar.md
    write(os.path.join(wiki_dir, "_navbar.md"), build_navbar(present_slugs, has_call_graph))
    print("[OK] _navbar.md")

    # serve.bat
    write(os.path.join(wiki_dir, "serve.bat"), serve_bat_content(args.port))
    print(f"[OK] serve.bat  (port {args.port})")

    print(f"\nDone -> {wiki_dir}")
    print(f"Run serve.bat then open http://localhost:{args.port}")


if __name__ == "__main__":
    main()
