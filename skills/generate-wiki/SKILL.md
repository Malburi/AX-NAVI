---
name: generate-wiki
description: harness 산출물(_workspace + .claude)을 기반으로 프로젝트 wiki 페이지 세트를 생성한다. call_graph.json을 vis-network 기반 인터랙티브 HTML(call-graph.html)로 변환하는 것을 포함. 생성 후 원하면 별도 프로젝트 wiki-hub(여러 시스템 통합·버전관리 중앙 허브)로 이어서 발행할 수 있다. "wiki 만들어줘", "wiki 생성", "문서 wiki", "프로젝트 wiki 생성", "위키 만들어줘", "generate wiki", "위키 업데이트", "call graph 시각화", "호출 그래프 wiki" 요청 시 트리거. harness-init 완료 후에는 자동 실행되지 않는다 — Phase 3.6 선택 작업 메뉴에서 사용자가 고를 때만 실행된다(2026-08-16 자동 실행 해제, 토큰 절감).
---

# Generate Wiki (오케스트레이터)

`wiki_generator.py`(zero-LLM)가 `_workspace/`·`.claude/` 산출물을 그대로 wiki 페이지로 복사/집계하고,
구조화 JSON(`api_contract.json`/`schema.json`/`external_io.json`/`pattern_profile.json` 등)은 표로 변환한다. `patterns.md`에는 preferred/legacy/anti-pattern 상태와 실제 기준 파일을 상세 패턴 문서보다 먼저 표시한다. LLM 호출 없음.
`_workspace/pair_config.md`(크로스 리포 연동)가 있으면 architecture/api-endpoints/database/external-systems
4개 페이지에 파트너 저장소 데이터가 자동 병합된다 (call-graph.html의 파트너 그래프 병합과 동일한 원리 — 어느 쪽에서 실행해도 통합됨).

---

## Phase 0: 사전 확인

### harness 존재 확인

| 확인 대상 | 없을 경우 |
|---------|---------|
| `_workspace/01_analyzer_report.md` | "harness-init을 먼저 실행해주세요" 안내 후 중단 |
| `CLAUDE.md` | 경고만 표시, 계속 진행 |

### 기존 wiki 감지

`_workspace/wiki/` 폴더가 이미 존재하면:

```
기존 wiki가 발견되었습니다 (_workspace/wiki/ 폴더).
덮어쓰시겠습니까? (Y/N)
  Y: 기존 _workspace/wiki/ → _workspace/wiki_prev/ 로 백업 후 재생성
  N: 중단
```

사용자 확인 후 진행.

---

## Phase 1: 페이지 범위 확인

기본적으로 발견된 데이터 기반으로 자동 결정하지만, 사용자가 범위를 지정할 수 있다.

---

## Phase 2: wiki_generator.py 실행

LLM 호출 없이, 다음 터미널 명령 한 번으로 wiki 페이지 + 인터랙티브 호출 그래프를 생성한다.
저장은 항상 `_workspace/wiki/`다(다른 harness 산출물과 같은 재생성 가능/`.gitignore` 권장
루트 아래로 통일 — 2026-08-14부터, 이전엔 프로젝트 루트의 별도 `wiki/` 폴더였다) — 질문 없이
바로 진행. 여러 시스템을 DB에 모아 보고 싶으면 완료 후 Phase 3.5에서 물어보는 wiki-hub 발행을
이용한다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/wiki_generator.py" --root "[절대경로]" --wiki-dir "[절대경로]/_workspace/wiki"
```

(스크립트는 플러그인 설치 루트에 있다 — PowerShell `$env:CLAUDE_PLUGIN_ROOT`, bash `$CLAUDE_PLUGIN_ROOT`. 비어 있으면 이 SKILL.md가 위치한 플러그인 디렉터리 절대경로로 대체. cwd 상대경로 `agents/lib/...` 금지.)

### 선택 — AI 해설 페이지 (사용자가 "해설 포함"·"내러티브 포함"을 요청한 경우만)

wiki 본문은 zero-LLM이 원칙이고 이 페이지만 유일한 예외다(약 5~10K 토큰). 절차·제약(소스 재열람 금지, 실행 순서, 사이드바 재조립, 파트너 wiki 제한)은 `agents/lib/pipeline-runner/block-wiki.md`의 "선택 — LLM 내러티브 페이지" 절을 그대로 따른다: `_workspace/01_analyzer_report.md`만 읽어 `_workspace/wiki/overview.md`를 쓰고 `docsify_convert.py`로 사이드바를 재조립한다.

---

## Phase 3: 결과 보고

`_workspace/07_wiki_build.md`를 읽어 요약 보고:

```
wiki 생성 완료

출력 위치: _workspace/wiki/
열기 방법: _workspace/wiki/serve.bat 실행 후 브라우저로 http://localhost:3501 접속 (Docsify 기반 — 인터넷 CDN 필요, file:// 직접 열기는 미지원)
  - _workspace/wiki/_sidebar.md, _workspace/wiki/_navbar.md: Docsify 네비게이션
  - _workspace/wiki/_html/*.html: Home·architecture·workflows 등 페이지의 서버 없는 열람용 렌더 사본 (원본은 _workspace/wiki/*.md 그대로 유지)
  - _workspace/wiki/call-graph.html: 데이터가 파일 안에 인라인으로 포함된 완전 독립 페이지 (file://로 직접 열람 가능)
  - _workspace/wiki/patterns.md: 모듈·레이어별 패턴 상태, 신뢰도, 실제 기준 파일 + 상세 컨벤션
```

`pair_config.md`가 있으면 `07_wiki_build.md`의 "크로스 리포 병합" 줄 2개(call-graph.html 노드/엣지 병합 + architecture/api-endpoints/database/external-systems markdown 페이지 병합)를 그대로 포함해 보고 (병합 성공 시 파트너 노드/추론된 크로스 엣지 수 또는 병합된 페이지 목록, 스킵 시 사유).

---

## Phase 3.5: 중앙 허브(wiki-hub) 발행 여부 확인 (선택)

폴더 wiki 생성이 끝난 뒤 이 질문을 한다 — 여러 시스템을 버전 관리와 함께 한 곳에서 보고
싶을 때만 켜는 별도 프로젝트 `wiki-hub` 발행이기 때문이다.

```
생성된 wiki를 중앙 허브(wiki-hub)에도 발행할까요? (Y/N)

발행하면
  - 다른 시스템들과 함께 한 사이트에서 조회되고
  - 백엔드/프론트엔드가 레이어(컴포넌트)로 구분되고
  - 페이지 버전 이력(내용이 바뀐 페이지만 새 버전)이 쌓입니다
```

| 응답 | 동작 |
|------|------|
| Y / 예 / yes / 발행 | `publish-wiki` 스킬 실행 (harness 플러그인에 내장된 `agents/lib/wikihub_db/`가 DB에 직접 저장 — 별도 wiki-hub 설치 불필요) |
| N / 아니오 / no / 나중에 | "나중에 필요하면 `wiki 발행해줘`라고 하세요" 안내 후 종료 |

DB 저장에 필요한 건 `SQLAlchemy` + 엔진별 드라이버(pymssql 등)뿐이다 — 없으면 `publish-wiki` 스킬이 pip install 안내부터 한다.

---

## 원칙

### wiki는 산출물의 뷰, 소스는 harness
wiki 파일은 `_workspace/`·`.claude/`에서 *생성*된다.  
wiki 파일을 직접 편집해도 다음 `generate-wiki` 실행 시 덮어씌워진다.

### 폴더 / wiki-hub는 선택이 아니라 용도가 다르다
폴더는 이 프로젝트 하나를 혼자 보는 용도, wiki-hub는 여러 시스템을 조직 차원에서 버전
관리와 함께 한 곳에 모아 보는 용도다. 대부분은 폴더만으로 충분하고, 조직에 시스템이
여러 개 쌓이기 시작하면 wiki-hub 발행을 추가하면 된다.
