# 스킬 트리거 체계 상세 (2026-08-15 기준)

스킬이 자연어 요청에 어떻게 매칭되는지, 축약 호출·범용 문구·vibe(알아서) 모드가 어떻게 설계됐는지, 그리고 추후 트리거/정적 스킬을 추가할 때 건드려야 하는 파일 전체를 기록한다.

---

## 1. 개요

harness가 설치된 대상 프로젝트에서 개선/개발 요청은 배포된 스킬(analyze-impact, safe-modify, scaffold-feature 등)을 경유해 처리되는 것이 설계 의도다. 스킬을 경유해야 `_workspace/index/*.json`(인덱스)·`.claude/patterns/*.md`(컨벤션)·영향도/안전성 게이트가 적용된다.

2026-08-06 이전에는 트리거 문구가 한정 표현("컨벤션 준수", "안전하게 수정")만 등록돼 있어, **"개발해줘"/"고쳐줘" 같은 범용 요청은 어느 스킬에도 매칭되지 않고 게이트 없는 즉흥 수정(바이브코딩)으로 처리되는 커버리지 구멍**이 있었다. 이를 해소하기 위해 3가지를 추가했다.

| 추가 항목 | 내용 |
|-----------|------|
| 축약 호출 | "영향도 [대상]", "안전수정 [내용]" 등 짧은 단어로 스킬 호출 |
| 범용 문구 | "개발해줘"→scaffold-feature, "고쳐줘"→safe-modify 를 기본 경로로 등록 |
| vibe 스킬 (신규) | "알아서 해줘" 등 명시적 문구로 영향·독립 리뷰 에이전트만 생략하는 빠른 경로. 패턴·최소 실행 검증은 유지 |

---

## 2. 트리거 메커니즘 — 2겹, 둘 다 자연어 매칭

### 2-1. 스킬 frontmatter description

각 SKILL.md(플러그인 전역 — 정적 스킬 6종은 대상 프로젝트에 로컬 사본을 두지 않는다, 3절 참조)의 frontmatter `description`에 트리거 문구가 등록돼 있다. Claude가 사용자 요청을 읽고 description과 매칭되는 스킬을 선택한다.

### 2-2. 대상 프로젝트 CLAUDE.md "자동 워크플로우" 표

`agents/lib/claude_md.md.template`의 자동 워크플로우 표(상황 → 스킬 매핑)가 harness-init 시 대상 프로젝트 CLAUDE.md로 조립돼 매 세션 컨텍스트에 로드된다. description 매칭과 함께 Claude의 판단 근거가 된다.

### 2-3. 중요한 제약 — deterministic hook 아님

- 두 메커니즘 모두 **LLM 판단 기반 확률 매칭**이다. 등록 문구와 정확히 일치하지 않는 표현은 스킬을 안 탈 수 있다.
- `settings.json`의 PreToolUse/PostToolUse hooks로는 스킬 트리거를 강제할 수 없다 — `agents/writer.md`의 "금지: 의미 없는 hooks 생성" 절에 명시된 확립 원칙. hooks는 빌드 검증 결과 저장, 위험 파일 수정 차단(exit 1)에만 쓴다.
- **보장 경로는 슬래시 직접 호출뿐**: `/ax-navi:safe-modify` 등.

---

## 3. 단일 소스 구조 (2026-08-13부터)

위치는 플러그인 전역 `skills/<name>/SKILL.md` 하나뿐이다 — 플러그인 설치만 하면 어느 프로젝트에서든 활성.

정적 스킬 6종(analyze-impact / safe-modify / scaffold-feature / vibe / plan-migration / review-sql)은
프로젝트별로 달라지는 내용이 전혀 없어서, 대상 프로젝트에 로컬 사본을 배포하지 않고 플러그인
전역판 하나만 존재한다. harness-init이 하는 일은 CLAUDE.md 자동 워크플로우 표·`.claude/ito-guide.md`에
이 스킬들의 *이름*을 등록하는 것뿐 — 실제 트리거·실행은 항상 플러그인 전역판을 통해 이뤄진다.
`plan-migration`/`review-sql`은 writer가 프로젝트 적용 대상인지(마이그레이션 후보 스택/DB 사용 여부)만
판단해 그 표·문서에 반영할지 결정한다("파일을 배포할지"가 아니라 "이 프로젝트에 권장할지"의 문제).

**이전(2026-08-06 ~ 2026-08-13)에는 두 번째 층**(`agents/lib/skills/<name>.md.template` → harness-init 시
`skills_builder.py`가 `.claude/skills/<name>.md`로 복사)이 있었다. 실제로 비교해보니 이 배포본은
전역판과 "같은 내용"이 아니라 훨씬 축약된 스텁이었고, "상세 로직은 `.claude/agents/<agent>.md` 참조"라는
문구가 가리키는 파일도 프로젝트에 배포된 적이 없어(도메인 에이전트 `domain-expert.md`만 실제로 복사됨)
죽은 참조였다 — 이 이중 구조와 그 결함을 함께 제거했다. 상세 이력은 문서 끝 "관련 이력" 참조.

---

## 4. 등록 트리거 전체 표

### 4-1. 축약 호출 (2026-08-06 신규)

| 축약 문구 | 스킬 | 사용 형식 |
|-----------|------|----------|
| 영향도, 임팩트 | analyze-impact | `영향도 UserService.updateUser` |
| 안전수정 | safe-modify | `안전수정 로그인 타임아웃 30초로` |
| 스캐폴드 | scaffold-feature | `스캐폴드 쿠폰 발급` |
| 마이그 | plan-migration | `마이그 iBatis → MyBatis` |
| SQL리뷰, 쿼리리뷰 | review-sql | `SQL리뷰 selectOrderList` |

### 4-2. 범용 문구 (2026-08-06 신규 — 게이트 경로가 기본값)

| 범용 문구 | 라우팅 | 실행 내용 |
|-----------|--------|----------|
| "수정해줘", "고쳐줘", "개선해줘", "버그 잡아줘", "이거 바꿔줘" | safe-modify | 사전 영향 분석 → 적용 → 사후 GO/HOLD/STOP |
| "개발해줘", "구현해줘", "코드 짜줘", "새 기능 만들어줘" | scaffold-feature | patterns 로드 → 컨벤션 보일러플레이트 + 테스트 골격 + 영향 체크 |

### 4-3. vibe (알아서 모드, 2026-08-06 신규)

| 문구 | 동작 |
|------|------|
| "알아서 해줘", "그냥 해줘", "바이브로", "바이브 코딩", "빠르게 그냥 고쳐", "vibe" | 영향·안전 에이전트 생략, 패턴 선택·최소 검증 유지 (상세는 6절) |

### 4-4. 기존 일반 문구 (변경 없음, 참고)

| 스킬 | 대표 문구 |
|------|----------|
| analyze-impact | "이거 수정하면 어디 영향?", "이 함수 수정해도 돼?", "어디서 쓰이고 있어?" |
| safe-modify | "안전하게 수정", "이 패치 적용해도 돼?", "긴급 핫픽스", "GO/NO-GO?" |
| scaffold-feature | "[기능명] 기능 추가", "패턴대로 만들어줘", "보일러플레이트 생성" |
| plan-migration | "Spring Boot로 마이그레이션", "전환 계획", "리프트앤시프트" |
| review-sql | "이 쿼리 성능", "N+1 확인", "DDL 영향 분석" |
| trace-logic | "이 API 어떻게 처리돼?", "처리 흐름", "어떻게 동작해?" |
| find-feature | "결제 관련 파일 어디 있어?", "찾아줘", "담당 클래스" |

writer가 프로젝트별로 직접 작성하는 스킬(trace / find-logic / scaffolder / cross-repo-*)의 트리거는 프로젝트마다 다르다 — 생성 규칙: 한국어 ≥3개 + 영어 ≥2개 + 스택 키워드 ≥1개 (`agents/writer.md` "2~4. trace / scaffolder / find-logic" 절).

---

## 5. 라우팅 설계 원칙

```
사용자 요청
 ├─ "개발해줘/구현해줘/새 기능"          → scaffold-feature  (컨벤션 기반 생성, 기본값)
 ├─ "수정해줘/고쳐줘/개선해줘"           → safe-modify       (게이트 포함, 기본값)
 ├─ "알아서 해줘/그냥 해줘/바이브로"      → vibe              (독립 에이전트 게이트 생략, 명시적 opt-out)
 └─ "/ax-navi:<스킬명>"               → 해당 스킬          (확정 경로)
```

- **기본값 = 게이트 경로.** 범용 요청은 harness의 인덱스·패턴·안전성 평가를 태운다.
- **독립 에이전트 게이트 생략은 opt-out 명시로만.** 사용자가 "알아서/그냥/바이브"라고 말했을 때만 vibe가 탄다. 다만 코드 컨벤션 확인과 최소 실행 검증은 어느 경로에서도 생략하지 않는다.
- safe-modify vs scaffold-feature 분기: 기존 코드 변경이면 safe-modify, 새 파일/기능 생성이면 scaffold-feature.

---

## 6. vibe 스킬 상세

파일: `skills/vibe/SKILL.md` (전역, 유일한 소스 — 대상 프로젝트에 로컬 배포 없음).

### 핵심 규칙
1. **외과적 변경 원칙 유지** — 요청된 부분만 수정. 인접 코드·주석·포맷 "개선" 금지.
2. `pattern_profile.py`로 대상 프로필을 선택하고 실제 기준 파일을 읽는다. 신규 파일인데 근거가 없으면 scaffold-feature로 승격한다.
3. 가장 작은 관련 테스트·빌드·린트를 실행하며 미실행·실패를 성공으로 보고하지 않는다.
4. 소스·API·DB 구조 변경은 인덱스와 wiki를 갱신한다.
5. 변경 파일·기준 패턴·검증 명령과 exit code를 간단히 보고한다.

### 승격 조건 (기존 변경은 safe-modify, 신규 파일·기능은 scaffold-feature로 승격)
- DB 스키마 변경 (DDL, 컬럼 추가/삭제)
- 외부 API 계약 변경 (요청/응답 필드, 엔드포인트)
- 트랜잭션 경계 변경
- 3개 이상 파일에 걸친 수정
- 구조화 패턴 누락 또는 대상 모듈 preferred 프로필 부재

### 설계 근거
- 사소한 변경까지 매번 영향분석+독립 리뷰 에이전트를 태우면 토큰·시간 낭비이므로 빠른 경로가 필요하다.
- 빠른 경로도 프로젝트 컨벤션과 실행 가능성은 포기하지 않는다.
- 생략 범위가 암묵적으로 넓어지지 않도록 명시적 문구 전용 스킬로 분리한다.

---

## 7. 파이프라인 연결 지점 — 새 정적 스킬 추가 체크리스트

**새 정적 스킬을 추가할 때 이 목록을 순서대로 따라가면 된다.** (2026-08-13부터 로컬 배포 단계가
없어져 예전보다 단계가 줄었다 — 상세는 3절 참조.)

| # | 파일 | 수정 내용 |
|---|------|----------|
| 1 | `skills/<name>/SKILL.md` | 신규 생성 — frontmatter(name + description에 트리거 문구) + 본문 (플러그인 전역판, 유일한 소스) |
| 2 | `agents/lib/skills_builder.py` — `ALWAYS_AVAILABLE_SKILLS` 또는 `CONDITIONAL_SKILLS` | 항상 사용 가능한 스킬인지, 프로젝트별 적용 판단이 필요한 조건부 스킬인지 등록. 조건부면 `decision_for()` 로직과 writer_decisions.json 계약도 확인 |
| 3 | `agents/lib/skills_builder.py` — `render_writer_files_report()` | `02_writer_files.md`의 "[워크플로우 스킬]" 목록에 이름 추가 |
| 4 | `agents/lib/skills_builder.py` — `ITO_SKILL_ORDER` | ito-guide.md 섹션 나열 순서에 추가 |
| 5 | `agents/lib/ito_guide.md.template` | `<!-- SKILL:<name> -->` 블록 추가 (용도 + 트리거 예시 3개, 완전 정적 텍스트). **블록이 없으면 ITO_SKILL_ORDER에 있어도 조용히 스킵됨** (`_parse_ito_template()` → `if name not in blocks: continue`) |
| 6 | `agents/lib/claude_md.md.template` | 자동 워크플로우 표에 행 추가 (대상 프로젝트 CLAUDE.md에 반영됨) |
| 7 | `agents/validator.md` + `agents/lib/validator_checks.py`의 `check2_skill_registration()` | CLAUDE.md 표 등록 여부 검사 목록에 추가 |
| 8 | 루트 `CLAUDE.md` + `docs/changelog.md` | CLAUDE.md의 파일 구조 표 + 자동 워크플로우 표, `docs/changelog.md`의 변경 이력 |
| 9 | `.claude-plugin/plugin.json` | 버전 bump + description 스킬 수 갱신 |
| 10 | `agents/lib/tests/plugin-packaging.test.mjs` | 플러그인·마켓플레이스 매니페스트와 구성 요소 경로 계약 확인 |

(`agents/lib/validator_checks.py`의 `STATIC_OR_PREEXISTING_SKILLS`는 더 이상 새 정적 스킬을 추가할 때
건드릴 필요가 없다 — 로컬 배포가 없으니 check3의 `.claude/skills/*.md` 글롭 스캔에 애초에 걸리지 않는다.
이 집합은 2026-08-13 이전에 이미 로컬 배포됐던 레거시 프로젝트의 잔존 사본을 위한 하위호환 용도로만 남아있다.)

### 트리거 문구만 추가/수정할 때 (스킬 신설 아님)
- `skills/<name>/SKILL.md`(유일한 소스) description만 수정.
- 라우팅 표현이 바뀌면 `claude_md.md.template` 자동 워크플로우 표도 확인.
- 버전 bump + `node agents/lib/tests/run.js` + `claude plugin validate . --strict` 후 push + `claude plugin update ax-navi@ax-navi`.

---

## 8. 사용 예시

```
# 축약 호출
영향도 UserService.updateUser
안전수정 로그인 타임아웃 30초로 변경
스캐폴드 쿠폰 발급
마이그 iBatis → MyBatis
SQL리뷰 selectOrderList

# 범용 문구 (게이트 경로)
주문 취소 기능 개발해줘          → scaffold-feature
세션 만료 버그 고쳐줘            → safe-modify

# 알아서 모드 (게이트 생략)
알아서 해줘 — 버튼 라벨만 바꿔
그냥 해줘, 로그 한 줄 추가

# 슬래시 (확정 경로, 플러그인 전역)
/ax-navi:safe-modify
/ax-navi:scaffold-feature
/ax-navi:vibe
```

정적 스킬 6종은 플러그인 전역판만 쓰므로 플러그인 업데이트 즉시 모든 프로젝트에 새 트리거가 반영된다(별도 프로젝트별 재생성 불필요). CLAUDE.md 표·ito-guide.md에 새 이름을 반영하려면: 해당 프로젝트에서 `"스킬만 다시 생성"` 요청 (부분 증분 — `skills_builder.py` 재실행으로 조립본 갱신).

---

## 9. 검증 방법

새 스킬/트리거 반영 후 아래 두 가지를 실행한다 (vibe 추가 시 실제 수행한 검증).

1. **더미 프로젝트 조립 확인**
   ```powershell
   # 더미 루트에 _workspace/writer_decisions.json (detected_stack 등 최소 필드) 준비 후
   python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/skills_builder.py" --root <더미루트>
   ```
   확인: CLAUDE.md 자동 워크플로우 표에 스킬명이 등록됨, `_workspace/02_writer_files.md`의 "워크플로우 스킬" 목록에 포함, `.claude/ito-guide.md`에 해당 섹션이 생성됨. **`.claude/skills/<name>.md` 파일 자체는 생성되지 않는 것이 정상이다**(정적 스킬 6종은 플러그인 전역판만 사용, 3절 참조).

2. **validator 오탐 확인**
   ```powershell
   python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/validator_checks.py" --root <더미루트>
   ```
   확인: `_workspace/validator_mechanical.json`에 새 스킬 관련 FAIL/WARN 없음 (check2가 CLAUDE.md 표 미등록을 놓치지 않는지 확인).

---

## 관련 이력

- 2026-08-13 — 정적 스킬 6종의 대상 프로젝트 로컬 배포(`agents/lib/skills/<name>.md.template` → `.claude/skills/<name>.md`) 완전 제거, 플러그인 전역판 단일 소스로 전환. 배포본이 전역판과 다른 축약 스텁이었고 참조하는 에이전트 파일도 배포되지 않는 죽은 참조를 갖고 있었던 것이 발견 계기. 상세는 `docs/changelog.md` 참조.
- 2026-08-06 — 본 문서가 다루는 트리거 확장 3종 구현 (커밋 bf82dfb vibe 신설, 43713c2 축약+범용 문구, 4a008a4 문서·버전 0.9.1). 상세는 `docs/changelog.md` 참조.
- 2026-07-23 — check3에 STATIC_OR_PREEXISTING_SKILLS 제외 도입 (정적 스킬 오탐 FAIL 해소).
- 2026-07-14 — 정적 스킬 5종을 writer LLM 재작성에서 템플릿 무-LLM 복사(skills_builder.py)로 전환.
