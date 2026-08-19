# block: wiki — wiki 페이지 생성 (Phase 3.7, 3.6 메뉴에서 선택된 경우만)

`pipeline-runner` 에이전트의 `block: wiki` 절차 상세다. 공통 규칙(스크립트 경로·`--out`/`--summary` 생략·에러 원칙·반환 원칙)은 `agents/pipeline-runner.md` 헤더에 있으며 여기서 반복하지 않는다.

`generate-wiki` 스킬의 Phase 2(생성)와 Phase 3(결과 확인)에 해당하는 스크립트 실행만 담당한다. **`generate-wiki` Phase 3.5의 "중앙 허브 발행 여부" 질문은 이 에이전트가 하지 않는다** — 사용자 질문은 오케스트레이터의 몫이다. 이 블록은 사용자가 harness-init Phase 3.6 메뉴에서 wiki를 골랐을 때만 호출된다(2026-08-16 자동 실행 해제).

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/wiki_generator.py" --root "[root]" --wiki-dir "[root]/_workspace/wiki"
```

`_workspace/pair_config.md`가 있으면 `wiki_generator.py`가 파트너의 `call_graph.json`·`01_analyzer_report.md`·`api_contract.json`·`schema.json`·`external_io.json`을 함께 읽어 architecture/api-endpoints/database/external-systems 페이지에 자동 병합한다. 별도 인자는 없다.

기존 `_workspace/wiki/`가 있으면 `_workspace/wiki_prev/`로 백업한 뒤 재생성한다.

## 선택 — LLM 내러티브 페이지 (`narrative: true`로 호출된 경우만)

오케스트레이터가 블록 호출에 `narrative: true`를 명시했을 때만 수행한다. 기본은 수행하지 않음 — wiki 본문은 zero-LLM이 원칙이고, 이 페이지만 유일한 예외다.

1. `_workspace/01_analyzer_report.md`만 읽는다. **소스 코드·인덱스 재열람 금지** — 이 페이지의 비용 상한(5~10K 토큰)은 "이미 만든 리포트 요약"이라는 전제에서 나온다.
2. `_workspace/wiki/overview.md`를 작성한다. 구성: 시스템이 무엇을 하는지(비개발자도 읽는 2~3문단) → 핵심 도메인 흐름 상위 3개 → 아키텍처 선택의 이유(리포트에 근거 있는 것만) → 신규 투입자가 처음 읽어야 할 파일 5개. 리포트에 없는 내용은 추측 생성하지 않는다.
3. `wiki_generator.py` 실행 **이후에** 써야 한다 — 먼저 쓰면 재생성 백업 단계에서 `wiki_prev/`로 밀려난다. 그리고 `_sidebar.md`는 wiki_generator 시점에 이미 확정돼 있으므로, overview.md를 쓴 뒤 반드시 사이드바를 재조립한다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/docsify_convert.py" --wiki-dir "[root]/_workspace/wiki" --project-name "[프로젝트명]"
```

`docsify_convert.PAGE_META`의 `overview` 항목이 파일 존재 기준으로 사이드바에 올린다. `_html/` 정적 사본에는 포함되지 않는다(알려진 갭, Docsify·DB 발행 경로에서만 노출). 파트너 연동 wiki(`pair_config.md` 존재)에서는 이 재조립이 사이드바의 파트너 병합 앵커를 잃는다 — 그 경우 내러티브 옵션을 건너뛰고 WARN으로 사유를 반환한다.

실행 후 `_workspace/07_wiki_build.md`를 읽어 아래 요약을 만든다. **이 파일 본문을 그대로 반환하지 않는다.**

## 반환 형식

```
BLOCK: wiki | LANE: [lane] | RESULT: OK | PARTIAL | FAIL
pages: [N]개 ([주요 페이지명 목록])
call-graph.html: 생성 | 누락 (nodes=[N] edges=[M])
cross_repo_merge: 병합됨(파트너 노드 [N], 크로스 엣지 [M]) | 스킵([사유]) | 해당 없음
backup: _workspace/wiki_prev/ 로 백업 | 기존 wiki 없음
WARN: [없으면 "없음"]
```
