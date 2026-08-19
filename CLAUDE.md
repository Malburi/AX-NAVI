# CLAUDE.md

> 💡 **토큰 비용 절감 꿀팁 (바이브 코딩 시 필수)**
> - **코드 수정 후 전체 재분석 금지**: 전체 재초기화 대신 `"인덱스만 갱신해줘"`라고 요청하면 변경된 파일만 부분 증분(Incremental) 분석합니다.
> - **부분 단계 실행**: 특정 요소만 갱신할 때는 `"스킬만 다시 생성"`, `"패턴만 다시"`, `"validator만 실행"` 등으로 필요한 단계만 핀포인트 요청하세요.
> - **경량 분석 모드 (Standard)**: 토큰 소비를 줄이려면 하네스 초기화 시 `"빠르게 하네스 구축해줘"` 문구를 포함하면 Standard Tier로 실행합니다 (기본은 Full, Lite Tier는 폐지됨).

## 보편 에이전트 행동 원칙

> Andrej Karpathy 가이드라인 기반. 모든 에이전트·스킬에 공통 적용.

### 1. 코딩 전 사고

구현 전 반드시.

- **가정 명시**: 불확실한 사항은 숨기지 않고 사용자에게 알린다.
- **해석 충돌**: 복수 해석이 가능하면 모두 제시하고 선택을 구한다.
- **단순 대안**: 더 간단한 방법이 있으면 먼저 제안한다. 무조건 실행하지 않는다.
- **모호함 정지**: 요청이 불명확하면 멈추고 이름을 붙여 질문한다.

### 2. 단순성 우선

요청된 것만 만든다.

- 요청받지 않은 기능·추상화·유연성은 추가하지 않는다.
- 새 에이전트·스킬 추가 전 자문: "기존 에이전트로 해결되는가?"
- 200줄로 해결 가능한데 50줄로 되면 50줄로 쓴다.

### 3. 외과적 변경

요청된 부분만 건드린다.

- 인접 코드·주석·포맷을 "개선"하지 않는다.
- 내 변경이 만든 미사용 import/변수/함수만 제거한다.
- 기존 dead code는 언급하되 삭제하지 않는다.
- 변경된 모든 줄은 사용자 요청에 직접 연결되어야 한다.

### 4. 목표 기반 실행

→ `_workspace/` 파이프라인(Phase 2-1~2-5 + Phase 4 harness-evaluator)으로 구현됨.

### 5. 한국어 출력 규칙

한국어 문장은 마침표(`.`), 물음표(`?`), 느낌표(`!`)로 끝낸다.  
목록이나 예시가 이어져도 문장 종결에 콜론(`:`)을 쓰지 않는다.  
코드·키-값 쌍·레이블 내부의 콜론은 허용.

### 6. 새 파일 헤더 주석

새 `.py` 파일 첫 줄: `# 이 파일의 역할을 한 줄 한국어로`  
`agents/*.md` 에이전트: frontmatter `description` 필드가 헤더 역할을 대신함.  
config / template / requirements 파일은 헤더 생략.

### 7. 계획 + 체크리스트 + 컨텍스트

→ `_workspace/` 파일 체계(writer_decisions.json · CLAUDE.md 변경이력)로 구현됨.

### 8. 완료 전 테스트 실행

→ `validator_checks.py` + `qa_boundary6.py` + `harness-evaluator` 루프로 구현됨.

### 9. 의미 단위 커밋

- 하나의 논리적 변경이 완료되면 즉시 커밋한다. 사용자 요청 전에.
- 커밋 메시지는 한 문장으로 설명 가능한 단위만.
- 좋은 예: `"change-safety: opus→sonnet 모델 수정"`
- 나쁜 예: `"에이전트 4개 수정 + 버그 수정 + 문서 업데이트"` (3개로 분리)
- 파트너 저장소 커밋은 자동 실행하지 않는다. 반드시 확인 후.

### 10. 에러 읽기, 추측 금지

- 전체 에러 메시지와 스택 트레이스를 읽는다. 키워드만 보지 않는다.
- 기억 기반의 "흔한 수정"을 확인 없이 적용하지 않는다.
- 원인 불명 시: print/log를 추가해 상태를 확인한 후 수정한다.
- WARN 후 폴백한 경우 폴백 사유를 `_workspace/`에 기록한다.

---

**harness-fin** — ITO/SI 조직을 위한 확장 메타 하네스 템플릿.

## 이 저장소의 역할

`.claude/` 폴더에 *코드베이스 분석 + 수정/개발/마이그레이션 작업까지* 지원하는 에이전트 팀과 워크플로우 스킬이 포함되어 있다.

대상 프로젝트의 코드베이스를 분석해 맞춤형 CLAUDE.md / 워크플로우 스킬 / 도메인 에이전트 / 패턴 / 인덱스를 한 번에 생성하고, 이후 *수정·개발·마이그레이션 작업*까지 끊김 없이 지원한다.

[neoruler001/harness-new](https://github.com/neoruler001/harness-new)의 4-에이전트 파이프라인을 기반으로 [Malburi/harness-ito](https://github.com/Malburi/harness-ito)의 메타 방법론을 확장 적용했다.

## 실행 모드

**에이전트 팀** — `TaskCreate` 의존성 + `_workspace/` 파일 기반 산출물 전달

**팀 구성:**
- 분석/생성 파이프라인: `analyzer` → `writer` → `pattern-extractor` + 구조화 프로필 검증 → `validator` → `qa`
- 스크립트 실행 위임: `pipeline-runner` (harness-init의 결정론적 블록 index/assemble/verify/wiki — 오케스트레이터는 `agents/lib/*` 스크립트를 직접 실행하지 않는다)
- 품질 루프: `spec-clarifier` (Phase -1, 사전 명세화) + `harness-evaluator` (Phase 4, 사후 eval)
- 작업용 에이전트: `impact-analyzer`, `pattern-conformance`, `change-safety`, `migration-planner`, `test-generator`, `sql-reviewer`, `legacy-decoder`, `doc-syncer`, `logic-tracer`, `feature-finder`, `api-bridge`
- 크로스 리포 에이전트: `api-bridge` (백엔드↔프론트엔드 API 계약 추출·검증·스텁 생성)

## 파일 구조

플러그인 표준 레이아웃 — `agents/`는 flat, `skills/`는 폴더/`SKILL.md`.

| 경로 | 역할 |
|------|------|
| `.claude-plugin/marketplace.json` | 마켓플레이스 카탈로그 (단일 저장소 = 단일 플러그인) |
| `.claude-plugin/plugin.json` | 플러그인 매니페스트 |
| `skills/harness-init/SKILL.md` | 메인 오케스트레이터 (분석 → 생성 → 검증 → QA → 패턴) |
| `skills/harness-init/references/split-repo.md` | 분리 저장소(paired-roots·hub-roots) 전용 절차 — 파트너 정보 수집·레인 상태·2-레인 작업 그래프·P-BARRIER/P-PAIR/P-REFRESH. `init_layout`이 분리 저장소일 때만 읽는다(단일·모노레포 초기화의 상주 컨텍스트에서 제외하기 위한 분리) |
| `skills/analyze-impact/SKILL.md` | 영향도 분석 워크플로우 |
| `skills/safe-modify/SKILL.md` | 안전 변경 워크플로우 (사전 영향 + 사후 안전성) |
| `skills/scaffold-feature/SKILL.md` | 컨벤션 기반 신규 기능 스캐폴딩 |
| `skills/vibe/SKILL.md` | 빠른 알아서 모드 (영향·안전 에이전트는 생략하되 패턴·최소 실행 검증 유지, 위험 시 safe-modify 승격) |
| `skills/plan-migration/SKILL.md` | 마이그레이션 계획 워크플로우 |
| `skills/review-sql/SKILL.md` | SQL 종합 리뷰 워크플로우 |
| `skills/spec-gate/SKILL.md` | 작업 전 소크라테스식 명세 명확화 워크플로우 (Ouroboros 영감) |
| `skills/harness-clean/SKILL.md` | harness 전체 제거 워크플로우 (확인 후 안전 삭제) |
| `skills/trace-logic/SKILL.md` | 기능·API·화면 처리 흐름 추적 워크플로우 |
| `skills/find-feature/SKILL.md` | 기능명·키워드로 관련 코드 위치 탐색 워크플로우 |
| `skills/generate-wiki/SKILL.md` | harness 산출물 → wiki 페이지 세트 생성 (call_graph.json → vis-network 인터랙티브 HTML) |
| `skills/pair-init/SKILL.md` | 별도 저장소 백엔드·프론트엔드 연동 (pair_config.md 생성 + API 계약 추출 + 드리프트 검증) |
| `skills/cross-repo-scaffold/SKILL.md` | 전체 스택 기능 동시 스캐폴딩 (백엔드 레이어 + 프론트엔드 서비스·컴포넌트·라우트) |
| `skills/cross-repo-modify/SKILL.md` | 페어 연동된 양쪽 저장소에 기존 기능 개선/수정 동시 반영 (safe-modify + 파트너 영향 확인·반영 게이트) |
| `skills/publish-wiki/SKILL.md` | 폴더 wiki를 별도 프로젝트 wiki-hub(중앙 DB, 시스템·컴포넌트·버전관리)에 발행 — `wiki-hub-publish` 콘솔 명령 호출 |
| `skills/wiki-hub/SKILL.md` | 별도 프로젝트 wiki-hub 실행 — 여러 시스템 wiki 통합 열람·검색·버전 이력·되돌리기 (`wiki-hub-serve` 콘솔 명령 호출) |
| `agents/spec-clarifier.md` | Phase -1: 소크라테스 인터뷰 + 모호성 점수화 + 명세 리포트 생성 |
| `agents/harness-evaluator.md` | Phase 4: 4차원 품질 평가 (커버리지·정확도·실행가능성·컨텍스트) + fix_targets 반환 |
| `agents/analyzer.md` | Phase 2-1: 심층 분석 (스택 + 의존성 그래프 + 데이터 흐름 + 트랜잭션 + 외부 통신 + 인덱스 생성) |
| `agents/writer.md` | Phase 2-2: 하네스 파일 + 워크플로우 스킬 생성 |
| `agents/pattern-extractor.md` | Phase 2-2.5: 컨벤션 추출 (writer 직후) |
| `agents/pattern-conformance.md` | 선택된 프로필·실제 기준 파일과 변경 코드의 적합성 판정 (CONFORM/HOLD/FAIL) |
| `agents/validator.md` | Phase 2-3: 구조 검증 + 인덱스 무결성 |
| `agents/qa.md` | Phase 3.7 온디맨드: 경계면 교차 비교 (Boundary 1~7) |
| `agents/impact-analyzer.md` | 변경 영향도 분석 |
| `agents/change-safety.md` | 변경 안전성 평가 (GO/HOLD/STOP) |
| `agents/migration-planner.md` | 스택 마이그레이션 계획 |
| `agents/test-generator.md` | 회귀 테스트 골격 생성 |
| `agents/sql-reviewer.md` | SQL 다각도 리뷰 |
| `agents/legacy-decoder.md` | 레거시 코드 역공학 |
| `agents/doc-syncer.md` | 코드 ↔ 문서 동기화 점검 |
| `agents/logic-tracer.md` | 기능·API·화면 처리 흐름을 진입점 → Controller → Service → DB까지 추적 |
| `agents/feature-finder.md` | 기능명·키워드로 관련 파일·클래스·메서드·SQL 위치 탐색 |
| `agents/api-bridge.md` | REST API 계약 추출(extract)·드리프트 검증(validate)·프론트 스텁 생성(generate-stub)·파트너 영향 확인(check-impact) |
| `agents/pipeline-runner.md` | harness-init의 결정론적 스크립트 블록(index·assemble·verify·wiki)을 대신 실행하고 요약만 반환 — 메인 컨텍스트에서 스크립트 왕복을 걷어내기 위한 토큰 절감 계층 |
| `agents/lib/wiki_generator.py` + `agents/lib/wiki_content.py` | harness 산출물을 그대로 wiki 페이지로 변환(zero-LLM) + call_graph.json → vis-network 인터랙티브 HTML |
| `agents/lib/wikihub_db/` (models/store/config/index_extract/publish.py) | wiki DB 발행(쓰기) — 별도 프로젝트 wiki-hub의 스키마·저장 로직을 그대로 옮긴 사본(view 전용 server/ui/render는 제외). wiki-hub 설치 없이 harness가 직접 DB에 씀 |
| `agents/lib/build-index.mjs` | 결정론적 전수 인덱서(Node 18+, npm 의존성 0, 소스 인코딩 자동 판정, 벤더·미니파이 제외, DDL 없을 때 SQL에서 스키마 유도) — `_workspace/index/`의 symbols·call_graph·sql_usage·transactions·external_io·env_branches·schema·api_contract·dead_code + `_meta`·`_analysis_input`·`_unresolved`를 LLM 없이 생성. upstream AX-Harness에서 이식 후 이 저장소 계약에 맞게 패치 |
| `agents/lib/ai-budget.mjs` | harness-init Phase 2(analyzer/writer/pattern-extractor)의 AI 호출을 role당 initial 1회로 스크립트가 강제하는 예산 게이트. upstream 이식, 거의 무수정 |
| `agents/lib/validate-harness.mjs` | `_workspace/index/*.json`을 `docs/index-schema/*.json` 대조 JSON 스키마로 검증(형태 검증) — `validator_checks.py`의 check7/7b(내용 정확성)와 병행. upstream 이식 후 analyzer.md 섹션 체계와 안 맞는 마크다운 프로즈 검사는 제거 |
| `agents/lib/tests/` | 결정론적 인덱스·AI 예산·하네스 검증·패턴 프로필·역할 계약 회귀 테스트 38종 + 무의존 러너 (`node agents/lib/tests/run.js`) |
| `agents/lib/pattern_profile.py` | 구조화 패턴 프로필의 실제 근거 파일·scope·상태를 검증하고 작업 경로·모듈·레이어별 preferred 프로필 선택 |
| `agents/lib/analyzer_index_summary.py` | analyzer 리포트 Section B/D(의존성그래프·트랜잭션·외부통신·환경분기·데드코드·DB스키마)를 인덱스 JSON에서 기계 생성(zero-LLM) |
| `agents/lib/pattern_tally.py` | pattern-extractor의 `05_patterns_extracted.md` 집계 표(샘플수·신뢰도·안티패턴 수)를 개별 패턴 파일에서 기계 취합(zero-LLM) |
| `agents/lib/validator_checks.py` | validator 체크 1,2,3,4,6,7,8,9(파일존재·트리거품질·경로교차·보안·인덱스무결성·이력)를 기계 실행(zero-LLM), 체크 5·10만 validator(LLM)에 남김 |
| `agents/lib/qa_boundary6.py` | qa Boundary 6(워크플로우 스킬 ↔ 인덱스 의존성)을 기계 실행(zero-LLM) |

> 본 저장소 내의 `agents/`·`skills/` 경로는 *플러그인 소스*이며, 설치된 대상 프로젝트에서 출력되는 결과물은 여전히 대상 프로젝트의 `.claude/skills/...`·`.claude/agents/...`에 기록된다. 에이전트/스킬 본문 내부의 `.claude/...` 경로는 *대상 프로젝트* 경로를 의미한다.

## 자동 워크플로우

| 상황 | 트리거 스킬 |
|------|---------|
| 하네스 초기화 전 명세 명확화 | `spec-gate` |
| 하네스 초기화 / 재초기화 | `harness-init` |
| 하네스 전체 제거 | `harness-clean` |
| 변경 영향도 분석 | `analyze-impact` |
| 안전한 변경 진행 | `safe-modify` |
| 컨벤션 따라 신규 기능 생성 | `scaffold-feature` |
| 영향·안전 에이전트 생략 빠른 작업 (패턴·최소 검증 유지) | `vibe` |
| 스택 마이그레이션 계획 | `plan-migration` |
| SQL 리뷰 | `review-sql` |
| 레거시 코드 해석 | `legacy-decoder` 직접 호출 |
| 문서 동기화 | `doc-syncer` 직접 호출 |
| 기능·API 처리 흐름 추적 | `trace-logic` |
| 기능·키워드로 코드 위치 탐색 | `find-feature` |
| harness 산출물 → wiki 생성 | `generate-wiki` |
| 백엔드·프론트엔드 별도 저장소 연동 | `pair-init` |
| 전체 스택 기능 동시 생성 | `cross-repo-scaffold` |
| 기존 기능 개선/수정 양쪽 저장소 동시 반영 | `cross-repo-modify` |
| API 드리프트 감지 | `pair-init` 재실행 |
| 프론트엔드 서비스 스텁만 생성 | `api-bridge` 직접 호출 |
| 생성된 wiki를 중앙 허브(wiki-hub)에 발행 | `publish-wiki` |
| 여러 시스템 wiki 통합 열람·검색·버전관리 | `wiki-hub` |

## 에이전트 수정

에이전트 개선은 `agents/[name].md` 파일을 직접 수정한다.  
변경사항은 `docs/changelog.md`의 변경 이력 테이블에 기록한다 (Malburi/harness-ito Phase 5-4 템플릿).

새 에이전트 추가:
1. `agents/[name].md` 작성 (frontmatter + 본문)
2. 호출하는 오케스트레이터 스킬(`skills/<name>/SKILL.md`)에 등록
3. `docs/changelog.md`의 변경 이력 테이블에 기록

새 스킬 추가:
1. `skills/[name]/SKILL.md` 폴더 + 파일 생성 (frontmatter 필수)
2. `docs/changelog.md`의 변경 이력 테이블에 기록

## 변경 이력

상세 변경 이력은 `docs/changelog.md`를 참조한다.
