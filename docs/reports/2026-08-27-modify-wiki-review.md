# /modify(safe-modify) wiki 연계 점검 보고서

- 점검일: 2026-08-27
- 대상 버전: total-ito 0.30.3 (commit 8052c3d 기준)
- 점검 계기: 유지보수 시나리오에서 `/modify [요구사항]`이 harness가 생성한 wiki(generate-wiki 산출물)를 근거로 제대로 작동하는지 확인 요청.

---

## 1. 결론 요약

**`/modify`는 wiki를 직접 읽지 않는다. 판단 근거는 wiki의 원천인 `_workspace/index/*.json` 인덱스이며, wiki는 GO 판정 후 자동으로 최신화되는 출력물이다. 이 구조는 설계 의도상 정상이다.**

- wiki는 인덱스 + harness 산출물의 zero-LLM 뷰다 (`skills/generate-wiki/SKILL.md` "wiki는 산출물의 뷰, 소스는 harness" 절). wiki를 판단 입력으로 쓰면 원천(인덱스)을 한 번 가공한 사본을 읽는 셈이라 정보 손실만 생긴다. 인덱스를 직접 질의하는 현재 구조가 더 정확하다.
- 따라서 "wiki 기반으로 작동한다"는 표현은 *같은 원천을 공유하고, 수정 후 wiki가 자동 동기화된다*는 의미에서 간접적으로 참이다.
- 다만 자동 갱신 흐름에 상호작용 충돌 등 갭 4건이 있었고, 이번 점검에서 3건을 수정했다 (4절).

## 2. 데이터 흐름 점검

`/modify`는 얇은 별칭이다 — args 전체를 `safe-modify`에 그대로 위임하고 절차를 재정의하지 않는다 (`skills/modify/SKILL.md`).

safe-modify의 Phase별 입력 소스는 다음과 같다.

| Phase | 판단 내용 | 입력 소스 | wiki 입력 여부 |
|-------|----------|----------|:---:|
| 0 컨텍스트 | 인덱스 신선도, 어댑터 커버리지, 패턴 선택 | `build-index.mjs --check-stale`, `check-adapter-coverage.mjs`, `pattern_profile.py` | 아니오 |
| 1 사전 영향 | 호출자·SQL·트랜잭션·외부 계약 파급, 위험도 | `_workspace/index/*.json` (`query-index.mjs` 질의) | 아니오 |
| 2 적용 | 외과적 변경 | `pattern_selection.json` + 대상 소스 | 아니오 |
| 3 사후 안전성 | 패턴 적합성(CONFORM/HOLD/FAIL), 실행 검증, GO/HOLD/STOP | pattern-conformance·`verify-target.mjs`·change-safety | 아니오 |
| 4 최종 판정 | GO = 어댑터 FULL + 패턴 CONFORM + 검증 exit 0 + safety GO | Phase 0~3 산출물 | 아니오 |
| 5 후속 갱신 | 인덱스 증분 갱신 → wiki 재생성 → HEAD 정합 보고 | `build-index.mjs --mode incremental`, `generate-wiki` | **출력만** |

wiki 참조 검사 결과 — `agents/impact-analyzer.md`, `agents/change-safety.md`, `agents/pattern-conformance.md`, `skills/analyze-impact/SKILL.md`에 wiki 입력 참조 0건 (grep 확인). wiki가 등장하는 곳은 safe-modify Phase 5(재생성)와 vibe의 "wiki 최신성 유지"뿐이다.

## 3. 실행 검증 결과

| 항목 | 결과 |
|------|------|
| 회귀 테스트 (`node agents/lib/tests/run.js`) | 최초 86종 중 **3건 실패** → 원인 수정 후 **86/86 통과** |
| `query-index.mjs` 명령 계약 | 문서에 적힌 질의 전부 실제 지원 확인 (symbol/callers/callees/trace/sql/table/schema/endpoint/transaction/dead + summary) |
| `build-index.mjs` 플래그 | `--check-stale`, `--mode init\|incremental\|feature-scoped` 존재 확인 (build-index.mjs:179-184) |
| `wiki_generator.py` 인자 계약 | `--root`, `--wiki-dir` — generate-wiki SKILL.md의 호출 명령과 일치 |

실패 3건의 원인은 모두 동일했다 — 당일 커밋 a9ef917에서 별칭 스킬 7종(modify/impact/scaffold/find/flow/sql/wiki)을 추가하며 스킬 수가 17 → 24가 됐는데, 테스트 기대값(`role-contract.test.mjs`, `plugin-packaging.test.mjs`)과 `docs/role-map.md`가 미갱신 상태였다. 세 파일을 갱신해 해소했다 (기능 결함 아님, 테스트·문서 정합성 문제).

## 4. 발견된 갭과 조치

| # | 갭 | 조치 |
|---|-----|------|
| 1 | **Phase 5 ↔ generate-wiki 상호작용 충돌.** generate-wiki Phase 0은 기존 `_workspace/wiki/`가 있으면 "덮어쓰시겠습니까? (Y/N)"를 묻는다. safe-modify Phase 5가 이를 기본 자동 후속으로 호출하므로 매 GO마다 불필요한 질문이 흐름을 끊는다. | **수정.** generate-wiki Phase 0에 "예외 — 자동 후속 갱신 호출" 규정 추가(질문 생략, 바로 백업 후 재생성), safe-modify Phase 5 3번 항목에 갱신 모드 명시. |
| 2 | **wiki_prev 백업 중첩 미정의.** 반복 갱신 시 백업 폴더 처리 방식이 문서에 없었다. | **수정.** generate-wiki Phase 0에 "백업은 1세대만 유지(기존 wiki_prev 삭제 후 교체)" 명시. |
| 3 | **wiki-hub 발행본 미동기화.** Phase 5는 폴더 wiki만 갱신하므로, publish-wiki로 중앙 허브에 발행한 시스템은 허브 버전이 stale로 남는데 안내가 없었다. | **수정.** safe-modify Phase 5에 5번 항목 신설 — `.env`의 `WIKI_DB_ENGINE` 등 wiki DB 설정이 있으면 "허브 발행본도 갱신할까요?" 1회 제안(기본 OFF, publish-wiki 위임). 함께, Phase 0 재인덱싱 발생 시 기존 wiki도 stale임을 인지하고 HOLD/STOP 종료 시 재생성 안내를 포함하도록 1줄 보강. |
| 4 | **테스트·역할 맵 미갱신** (3절 참조). | **수정.** 기대값 17 → 24, role-map.md에 "별칭 스킬 (단축 호출)" 절 추가. |

## 5. 보류 권고 (이번에 적용하지 않음)

**impact/safety 리포트의 wiki 변경 이력 페이지 집계.** `_workspace/reports/impact_*.md`·`safety_*.md`에는 "무엇을 왜 바꿨고 GO 근거가 무엇이었는지"가 남는데, 현재 wiki에는 반영되지 않는다. 인수인계 관점에서 wiki에 "최근 변경" 페이지가 있으면 유용하나, `wiki_content.py` 확장(리포트 파싱·시간순 집계·페이지 템플릿)이 필요해 효용 대비 범위가 크다. 단순성 원칙에 따라 권고로만 남긴다. 필요해지면 zero-LLM 원칙을 유지한 채 reports 폴더의 파일명·frontmatter만 표로 집계하는 최소 구현부터 시작할 것을 권한다.

## 6. 사용 안내 (유지보수 시나리오)

대상 시스템 프로젝트에서 `/modify [요구사항]`을 쓰면 다음이 보장된다.

1. 인덱스가 stale이면 자동 재인덱싱 후 판단한다 — wiki가 아니라 인덱스가 근거이므로, wiki가 오래됐어도 판단 정확도에는 영향이 없다.
2. GO 판정 후 인덱스와 wiki가 함께 자동 갱신된다 — wiki는 항상 "마지막 GO 시점"과 동기화된다.
3. wiki를 열람 용도로 신뢰해도 된다 — 단, /modify 밖에서 코드를 직접 고친 경우에는 다음 /modify 실행 또는 `wiki 만들어줘`로 재생성될 때까지 stale일 수 있다.
