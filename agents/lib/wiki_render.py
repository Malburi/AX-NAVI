import html

# 정적 빌드(wiki_generator.py)가 쓰는 최소 HTML 렌더러.
# render_markdown_page()는 외부 CDN 의존 없이 markdown을 이스케이프 후 <pre>로 보여준다 —
# 폐쇄망 환경에서도, file:// 로 직접 열어도 동작해야 하기 때문. (_html/ 정적 렌더 사본에서 사용)
# render_index()는 [2026-07-15]부터 Docsify 기반이라 예외 — 외부 CDN 필요, file://는 미지원(serve.bat으로 로컬 서버 실행 필요).
# 별도 프로젝트 wiki-hub(중앙 허브)는 이 파일과 무관 — 자체 렌더러(CDN 미사용)를 갖는다.

PAGE_STYLE = """
body { font-family: -apple-system, Segoe UI, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }
pre { white-space: pre-wrap; word-break: break-word; background: #f6f8fa; padding: 16px; border-radius: 6px; }
a { color: #1a5fa8; }
.nav { margin-bottom: 16px; }
"""

INDEX_STYLE = """
body { font-family: -apple-system, Segoe UI, sans-serif; max-width: 700px; margin: 40px auto; }
li { margin: 6px 0; }
h3 { margin-top: 32px; color: #666; }
"""


def render_markdown_page(title, page_path, content, index_href="index.html"):
    """markdown 텍스트 1개를 안전하게 이스케이프해 <pre>로 보여주는 HTML 문서."""
    escaped = html.escape(content)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{html.escape(page_path)} - {html.escape(title)}</title>
<style>{PAGE_STYLE}</style></head>
<body>
<div class="nav"><a href="{html.escape(index_href)}">← 전체 페이지 목록</a></div>
<h2>{html.escape(page_path)}</h2>
<pre>{escaped}</pre>
</body></html>"""


def render_static_index(project_name, entries):
    """file://로 직접 열어도 동작하는 정적 홈 페이지. CDN/서버 불필요 —
    entries의 href는 wiki_dir 기준 상대경로(예: _html/Home.html, call-graph.html)여야 한다."""
    items = "\n".join(
        f'<li><a href="{html.escape(href)}">{html.escape(label)}</a></li>'
        for href, label, _source in entries
    )
    safe = html.escape(project_name)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{safe} Wiki (오프라인)</title>
<style>{INDEX_STYLE}</style></head>
<body>
<h2>{safe} Wiki</h2>
<p>file://로 직접 연 오프라인 보기. 서버 실행형(검색·사이드바 포함)은 <code>serve.bat</code> 실행 후 <a href="index.html">index.html</a> 참고.</p>
<ul>
{items}
</ul>
</body></html>"""


def render_index(title, heading="", entries=None, extra_html="", **kwargs):
    """Docsify 4 기반 index.html 생성.
    [2026-07-15] 토큰 절감 리팩토링으로 단순 정적 HTML로 교체됐던 것을 Docsify로 복원.
    향후 이 함수를 단순 정적 HTML로 되돌리지 말 것 — _sidebar.md/_navbar.md가 짝으로 필요.
    title 인자를 project_name으로 사용. heading/entries/extra_html 무시 (Docsify가 처리).
    """
    project_name = title
    safe = html.escape(project_name)
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
