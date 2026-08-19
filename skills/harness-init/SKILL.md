---
name: harness-init
description: 프로젝트를 심층 분석해 맞춤형 하네스(CLAUDE.md, 5+ 워크플로우 스킬, 도메인 에이전트, 패턴, 인덱스)를 자동 생성하는 오케스트레이터. "하네스 초기화", "하네스 만들어줘", "하네스 다시 초기화", "harness 다시 만들어줘", "프로젝트 분석해서 설정해줘", "이 프로젝트 Claude 설정해줘", "create harness", "initialize harness", "re-initialize harness", "generate project harness", "하네스 업데이트", "하네스 보완", "스킬만 다시 생성", "에이전트만 다시 생성", "validator만 다시 실행", "패턴 추출해줘", "pattern extract" 요청 시 사용. `.claude/skills/trace.md`가 없으면 자동 트리거.
---

# Harness Initializer (Enhanced) — 팀 모드 오케스트레이터

프로젝트 코드베이스를 심층 분석해 *수정·개발·마이그레이션 작업까지 지원하는* 맞춤형 harness를 자동 생성한다.

기존 harness-new가 만들던 5종 + harness-fin이 추가하는 5종 + 인덱스 + 패턴까지 한 번에 생성.

**실행 모드:** 에이전트 팀 (TaskCreate 의존성 + `_workspace/` 파일 기반 산출물 전달)

**팀 구성 (확장):**
- 필수 파이프라인: analyzer → writer → pattern-extractor + 프로필 검증 → validator
- 품질 루프: harness-evaluator (Phase 4)
- 온디맨드(자동 실행 안 함, Phase 3.6 메뉴에서 선택 시만 Phase 3.7에서 실행): generate-wiki, qa

---

> **사용자 질문 언어 규칙**: 이 스킬이 `AskUserQuestion`으로 사용자에게 묻는 모든 질문은 한국어로 작성한다. `question`·`header`·각 옵션의 `label`·`description` 필드를 전부 한국어로 채운다. 아래 표의 라벨·설명 문구를 그대로 필드에 쓰고, 임의로 영어로 번역하지 않는다. `AskUserQuestion` 툴이 없는 호스트의 평문 폴백도 한국어로 출력한다. (Phase -1 구성 확인, Phase 2-0.7 Tier 확인, Phase 3.6 선택 작업 메뉴 등 모든 질문에 적용.)

---

## Phase -1: 프로젝트 구성 확인

> **스킵 조건**: 아래 중 하나라도 해당하면 Phase 0으로 직행
> - `_workspace/00_init_scope.md` 이미 존재 (이전 구성 확인 완료)
> - 부분 재실행 ("스킬만"·"에이전트만"·"validator만" 등)
> - 재초기화 + "다시"만 있음 (추가 목표 변경 없음)
> - 사용자가 요청문에 구성과 경로를 이미 명시함 (`source: explicit-request`로 기록)

현재 작업 폴더 절대경로를 plain text로 먼저 출력한 뒤(`현재 작업 폴더: [절대경로]`), `AskUserQuestion`으로 2단계에 걸쳐 구성을 확인한다.

> **주의**: 전체 구성은 5가지인데 `AskUserQuestion` 툴은 한 질문에 옵션 최대 4개까지만 지원한다. 과거(2026-07-30) 5개를 한 질문에 담았다가 5번(허브형)이 조용히 잘려나간 실사고가 있었다 — 절대 5개를 한 질문에 넣지 않는다. 아래처럼 4개 이하씩 2단계로 나눈다. `AskUserQuestion` 툴 자체가 없는 호스트에서는 예전 방식(5지선다 평문 출력 + 자유 텍스트 응답 1~5)으로 폴백한다.

**1차 질문** (header: `초기화 구성`):

| 옵션 | 설명 |
|---|---|
| 단일 프로젝트로 초기화 (Recommended) | 지금 폴더 전체를 단일 프로젝트로 분석합니다 |
| 서버·클라이언트 함께 초기화 (모노레포) | 한 상위 폴더 안의 backend와 frontend/desktop/mobile을 워크스페이스로 통합 분석합니다 |
| 서버·클라이언트 각각 초기화 후 연결 (1:1) | 두 프로젝트를 독립적으로 초기화하고 양쪽 검증 후 pair-init으로 연결합니다 |
| 기타 (부분 범위 / 허브형 1:N) | 특정 폴더만 분석하거나, 백엔드 1개+클라이언트 여러 개 구조입니다 |

**2차 질문** (1차에서 "기타" 선택 시만, header: `세부 구성`):

| 옵션 | 설명 |
|---|---|
| 특정 폴더·모듈만 초기화 | 선택한 상대경로만 분석합니다 |
| 허브형 (1개 중심 + 클라이언트 여러 개, 1:N) | 예: 백엔드 1개 + 웹/모바일(iOS·Android)/관리자 등 클라이언트 2개 이상을 독립 초기화하고 연결합니다. 파트너가 정확히 1개면 1차 질문의 "1:1"을 쓴다 |

**응답별 분기:**

| 응답 | `init_layout` | 후속 확인 | 다음 단계 |
|------|------|---------|---------|
| 1차: 단일 | `single-root` | 없음 | Phase 0으로 진행 |
| 1차: 모노레포 | `monorepo` | root 내부 workspace 상대경로와 역할 | Phase 0으로 진행 |
| 1차: 1:1 | `paired-roots` | 파트너 정보 수집 (아래) | Phase 0으로 진행 |
| 1차: 기타 → 2차: 부분 범위 | `selected-paths` | root 내부 상대경로 | Phase 0으로 진행 |
| 1차: 기타 → 2차: 허브형 | `hub-roots` | 파트너 목록 수집 — N개 (아래) | Phase 0으로 진행 |
| 무응답·자유 텍스트로 판단 불가 | `single-root` (기본값) | 없음 | Phase 0으로 진행 |

휴리스틱으로 발견한 `server`/`backend`/`client`/`frontend`/`web`/`mobile` 후보는 경로 확인 표의 제안값으로만 쓰고 사용자의 구성 선택을 자동으로 바꾸지 않는다.

> **분리 저장소(`paired-roots`·`hub-roots`)를 선택했으면 여기서 `references/split-repo.md`를 읽고 그 절차를 따른다.**
> 파트너 정보·클라이언트 목록 수집, `pair_lane_state.md` 초기화, 대칭 2-레인 작업 그래프, 레인 실행 방식,
> P-BARRIER/P-PAIR/P-REFRESH가 전부 그 파일에 있고 이 SKILL.md에는 없다. 읽지 않으면 파트너 쪽이 통째로 누락된다.
> `single-root`·`monorepo`·`selected-paths`는 읽지 않는다 — 이 SKILL.md만으로 완결된다.
> 레인 상태 초기화는 Phase -1의 위 "스킵 조건"과 무관하게 항상 수행한다(`00_init_scope.md`가 이미 있어
> 구성을 다시 묻지 않는 재시도에도 `init_layout`은 그 파일에서 읽을 수 있으므로 레인 재개 판단이 필요하다).

### 출력

`_workspace/00_init_scope.md`를 일반 파일 쓰기로 기록한다.

```markdown
# 초기화 분석 범위

## 사용자 확인 내용
- 프로젝트 위치: `[절대경로]`
- 초기화 구성: 단일 | 모노레포 | 분리 저장소(1:1) | 부분 범위 | 허브형(1:N)
- 포함 경로: `[검증된 상대경로]`
- 대상 프로젝트: `[절대경로와 역할 목록, paired-roots만]`
- 클라이언트 목록: `[role_label·절대경로 목록, hub-roots만]`

## 기계 실행 값
- init_layout: single-root | monorepo | paired-roots | selected-paths | hub-roots
- paths: [검증된 상대경로]
- source: user-selection | explicit-request | reused
- tier: [Phase 0 Step 2.5에서 결정 후 추가 기록 — Phase -1 시점에는 비워 둠]
```

`monorepo`/`selected-paths`의 포함 경로는 root 내부 실제 디렉터리만 허용한다 (`..`, root 밖 절대경로 거부).

---

## Phase 0: 컨텍스트 확인

### Step 1: 작업 디렉토리 확인
`pwd`로 절대 경로 확보.

### Step 2: 기존 하네스 감지

| 확인 대상 | 의미 |
|----------|------|
| `CLAUDE.md` 존재 + "## 변경 이력" 섹션 | 기존 하네스 있음 |
| `.claude/skills/trace.md` 존재 | 기존 스킬 있음 |
| `.claude/ito-guide.md` 존재 | harness-fin (Enhanced) 버전 |
| `.claude/agents/domain-expert.md` | 도메인 에이전트 있음 |
| `_workspace/` 존재 | 이전 산출물 있음 |
| `_workspace/index/*.json` 존재 | 인덱스 있음 (incremental 가능) |
| `_workspace/pair_config.md` 존재 | 파트너 프로젝트 연동 상태 → partner_root 변수 설정 |
| `CLAUDE.md`가 이미 커밋돼 있고 `_workspace/`가 없음 | **팀원이 공유 하네스를 pull한 상태** → 아래 Step 2.2로 |

### Step 2.2: 공유 하네스 이어받기 (팀원 시나리오)

ITO는 한 시스템에 여러 명이 붙는다. 이 단계가 없으면 **초기화가 팀당 1회가 아니라 사람당 1회**가 되어, 90분과 세션 한도를 인원수만큼 곱해서 쓰게 된다.

앞 표에서 "팀원이 공유 하네스를 pull한 상태"로 판정됐으면(또는 인덱스가 이미 있으면) **전체 초기화를 하지 않는다.** 대신:

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/build-index.mjs" --root "[절대경로]" --check-stale
```

| exit | 의미 | 동작 |
|------|------|------|
| 0 | 소스 지문이 인덱스와 일치 | **아무것도 하지 않는다.** 하네스가 이미 쓸 수 있는 상태다 — 그대로 종료하고 사용 가능한 스킬만 안내 |
| 1 | 인덱스가 없거나 소스가 변경됨 | `block: index`만 1회 실행(LLM 없음, 수십 초). 그 뒤 `_workspace/index/_ai_patch.json`이 저장소에 있으면 `--mode incremental`이 자동 병합한다 |

두 경우 모두 **LLM 파이프라인(2-1~2-5)을 실행하지 않는다.** analyzer·writer·pattern-extractor의 산출물은 이미 `CLAUDE.md`·`.claude/`에 커밋돼 있고, 인덱스는 결정론적이라 각자 로컬에서 다시 만드는 편이 싸다(수십 초, LLM 0). 사용자가 명시적으로 "하네스 다시 초기화"를 요청한 경우에만 전체 파이프라인으로 간다.

> 인덱스 자체를 커밋할지는 팀이 정한다. 커밋하면 팀원은 위 `--check-stale`이 exit 0을 내는 동안 인덱싱조차 하지 않는다. 인덱스는 이제 이식 가능하다 — `source_root`가 `.`이고, 경로는 전부 루트 기준 상대경로에 슬래시 정규화이며, 줄바꿈(CRLF/LF)과 OS 로케일에 따라 내용이 달라지지 않는다(2026-08-16 수정). 크기가 부담되면 커밋하지 않아도 되고, 그때는 팀원이 수십 초짜리 인덱싱 한 번을 더 할 뿐이다.
>
> **반드시 커밋해야 하는 것은 인덱스가 아니라 LLM 산출물이다** — `_workspace/index/_ai_patch.json`(analyzer가 미해결 관계를 판정한 결과)은 다시 만들려면 opus를 다시 돌려야 한다. 이 파일이 `.gitignore`의 `_workspace/`에 걸려 버려지고 있지 않은지 Phase 3 보고에서 확인시킨다.
>
> **git에 인덱스·`_ai_patch.json`이 없는데 시스템이 wiki-hub DB에 발행돼 있으면** DB가 대체 경로다 — `publish-wiki`의 `--pull`이 `_workspace/**/*.json` 전부(인덱스 + `_ai_patch.json` 포함)를 원래 경로로 복원한다. 복원 후 위 `--check-stale`로 신선도를 확인하고, exit 1이면 `block: index`를 `--mode incremental`로 1회만 돌리면 된다(LLM 0). 순서는 반드시 pull → check-stale — 반대로 하면 방금 만든 로컬 인덱스를 오래된 DB 사본이 덮어쓴다.

### Step 2.5: Tier 결정

**① 사용자 요청 override 먼저 확인:**

| 키워드 | Tier 강제 |
|--------|---------|
| "빠르게"·"간단히"·"빠른"·"quick"·"fast" | **Standard** |
| "깊게"·"심층"·"마이그레이션"·"레거시"·"전체"·"migration"·"legacy"·"deep" | **Full** |

> Lite Tier는 2026-07-23 폐지됨 — 인덱스 없는 하네스는 후속 스킬(analyze-impact 등)이 동작하지 않아 실효가 없었다. Tier는 Standard/Full 2단계만 존재하며 기본은 Full이다.

**② override 없으면 기본 Full — 단, 확인은 인덱싱 뒤에 한다(2-0.7):**

기본 Tier는 **Full**이다. 레거시 유지보수는 얕은 분석이 놓치는 위험(미해결 관계·인증 우회·트랜잭션 경계)이 재작업 비용보다 크다는 전제.

과거에는 여기서 곧바로 "Standard로 낮출까요?"를 물었는데, **이 시점에는 물어볼 근거가 없었다** — 프로젝트 규모를 아직 모르므로 사용자도 판단할 수 없고, 결국 "돌려봐야 얼마 드는지 아는" 상태로 90분·한도 40%를 쓰게 됐다. 인덱싱(2-0.5)은 LLM을 쓰지 않고 수십 초면 끝나면서 규모를 정확히 알려주므로, **확인은 인덱싱 직후 2-0.7에서 실제 견적과 함께** 한다.

override가 있으면 그 값을 그대로 확정하고 2-0.7의 질문을 건너뛴다. 결정된 Tier는 `_workspace/00_init_scope.md`의 "기계 실행 값" 섹션에 `- tier: Standard | Full` 행으로 기록한다. 이 질문은 초기 실행/재초기화당 1회만 하며, 부분 재실행·인덱스 리프레시는 `00_init_scope.md`의 `tier:` 값을 재사용해 다시 묻지 않는다(값이 없으면 그때만 다시 묻는다).

**③ Tier별 실행 구성:**

| Tier | 실행 구성 | 스킵 항목 |
|------|---------|---------|
| **Standard** | analyzer(init/sonnet, 스택 해당 Phase B만) → writer(sonnet) → pattern(병렬) → validator | — |
| **Full** | 전체 파이프라인 (analyzer만 opus, writer 포함 나머지는 sonnet) | — |

wiki·QA는 Tier와 무관하게 두 Tier 모두 자동 실행에서 스킵되며, Phase 3.6 선택 작업 메뉴에서 사용자가 고를 때만 Phase 3.7에서 실행된다(위 표에는 포함하지 않음).

### Step 3: 실행 모드 분기

| 상황 | 모드 | 처리 |
|------|------|------|
| 기존 하네스 없음 | **초기 실행** | 전체 파이프라인 (analyzer init + writer + validator + pattern-extractor; wiki·qa는 Phase 3.6 선택 시만) |
| 기존 + "다시"·"새로" | **재초기화** | `.claude/backup/[YYYYMMDD-HHMMSS]/`로 백업 후 전체 실행 (analyzer init 모드) |
| 기존 + "스킬만"·"에이전트만"·"validator만"·"qa만"·"패턴만" | **부분 재실행** | 해당 단계만, 이전 `_workspace/` 산출물 재사용 |
| 기존 + 일반 보완 | **업데이트** | 백업 후 analyzer incremental + 재실행 |
| 기존 + "인덱스만 갱신해줘"·"인덱스만 다시"·"인덱스 리프레시" (코드 변경 후) | **인덱스 리프레시** | analyzer incremental만 (writer/validator/eval 스킵) |

백업 절차:
- PowerShell: `Get-Date -Format "yyyyMMdd-HHmmss"`
- 백업 대상: `CLAUDE.md`, `.claude/skills/*.md`, `.claude/agents/*.md` (공통 에이전트는 제외, 프로젝트 전용만), `.claude/patterns/`
- 백업 위치: `.claude/backup/[YYYYMMDD-HHMMSS]/`

### Step 4: 작업공간 준비

`_workspace/` 디렉토리:
- 초기 실행/재초기화: `_workspace/`를 `_workspace_prev/`로 이동 후 새로 생성
- 부분 재실행: 기존 유지

산출물 파일명:
```
_workspace/00_init_scope.md           ← 구성 확인 (Phase -1)
_workspace/01_analyzer_report.md      ← analyzer
_workspace/02_writer_files.md         ← writer
_workspace/03_validator_report.md     ← validator
_workspace/04_qa_report.md            ← qa
_workspace/05_patterns_extracted.md   ← pattern-extractor
_workspace/pattern_profile_validation.json ← 구조화 패턴 기계 검증
_workspace/06_eval_report.md          ← harness-evaluator (Phase 4)
_workspace/index/*.json               ← analyzer (인덱스)
_workspace/ai-budget.json             ← ai-budget.mjs (2-0.5 Step F)
_workspace/validator_schema.json      ← validate-harness.mjs (2-4)
```

`ai_budget_session` 값을 이 단계에서 한 번 생성한다 — `now_kst.py` 결과에 `init-` 접두사를 붙인 문자열(예: `init-2026-08-12-143000`). `00_init_scope.md`의 "기계 실행 값"에 `tier:`와 나란히 `- ai_budget_session: [값]` 행으로 추가 기록하고, 부분 재실행·인덱스 리프레시는 이미 기록된 값을 재사용한다(재초기화 시 예산이 조용히 리셋되는 것을 막기 위함 — `ai-budget.mjs init`은 같은 session이면 멱등).

---

## Phase 1: 공유 작업 계획

`TaskCreate`로 팀원별 작업 + 의존성 설정 (Tier에 따라 생성 작업 다름):

**단일/모노레포 (Standard/Full 공통):**
```
T-I (pipeline-runner):   → _workspace/index/*.json (결정론적, LLM 판단 없음 — 2-0.5)
T-A (analyzer):          → _workspace/01_analyzer_report.md       (blockedBy: T-I)
T-W (writer):            → _workspace/02_writer_files.md           (blockedBy: T-A)
T-P (pattern-extractor): → _workspace/05_patterns_extracted.md     (blockedBy: T-W)
T-V (MJS validator):     → _workspace/03_validator_report.md       (blockedBy: T-P)
T-E (harness-eval):      → _workspace/06_eval_report.md            (blockedBy: T-V)
```
T-I는 LLM 판단이 없는 스크립트 단계지만(2-0.5, `pipeline-runner`에 위임), 레거시 대형 저장소는 실행 시간이 체감될 수 있어 별도 작업으로 눈에 보이게 둔다(예: `T-I · pipeline-runner · 소스 구조와 호출 관계 인덱싱`). T-V의 표시 이름을 "MJS validator"로 쓰는 이유도 같다 — 체크 대부분(1,2,3,4,6,7,8,9,11)이 `validator_checks.py`/`validate-harness.mjs`의 기계 결과를 그대로 옮겨 적는 것이고, LLM은 체크 5·일부 10만 판단한다(agents/validator.md 참조). T-P가 만든 구조화 프로필까지 T-V가 검증해야 하므로 T-V는 T-P 완료 뒤 실행한다.

**분리 저장소 (paired-roots/hub-roots):** 아래 "분리 저장소 작업 그래프" 절 참조 — 단일/모노레포 그래프 대신 이 그래프를 쓴다.

QA(`T-Q`)와 wiki(`T-WIKI`)는 Tier와 무관하게 이 초기 작업 그래프에 포함하지 않는다 — Phase 3.6의 선택 작업 메뉴에서 사용자가 고를 때만 온디맨드로 실행한다(토큰 절감).

`TaskCreate`가 있으면 위 작업 ID와 한글 설명을 **함께 포함한 제목 그대로** 작업을 생성한다(예: `T-A · analyzer · 프로젝트 구조·의존성·레거시 로직 분석`).

**모든 `Agent()` 호출은 `subagent_type="total-ito:[에이전트 이름]"`으로 발행한다.** 2026-08-16 이전에는 분석·생성·판정 역할을 전부 `general-purpose`로 불렀는데, 그러면 서브에이전트가 자기 지침 파일을 **직접 `Read`로 읽어야** 했다 — `agents/analyzer.md` 하나가 22K 토큰이고, 파일 위치를 찾느라 Glob·Grep이 덧붙는 경우도 많았다. 네임스페이스로 부르면 같은 지침이 서브에이전트의 시스템 프롬프트로 자동 로드되므로 그 읽기가 통째로 사라지고, 프롬프트에는 인자(루트 경로·mode·tier·입출력 파일)만 남긴다. 초기화 1회 기준 이 변경만으로 지침 재적재가 약 70K 토큰 줄어든다.

`description` 필드에는 계속 `[task-id] · [실제 에이전트 이름] · 한글 목적`을 그대로 넣는다 — 어떤 단계가 실행 중인지 사용자에게 드러내기 위한 것이라 네임스페이스 호출이어도 규칙은 같다.

플러그인 네임스페이스 지정을 지원하지 않는 호스트에서만 `general-purpose`로 폴백하되, 그때는 프롬프트에 "`agents/[에이전트 이름].md`의 지침을 읽고 그대로 따른다"를 반드시 명시한다(pipeline-runner는 디스패치 표가 가리키는 `block-*.md` **하나만** 이어서 읽게 한다). `TaskCreate`가 없는 호스트에서는 `_workspace/00_pipeline_status.md` 체크리스트로 폴백하며 같은 제목을 사용한다.

보완·재검증 작업 제목은 원래 단계 ID를 보존한다.

- `T-A-PATCH · analyzer · 인덱스 무결성 지적 항목 보강` (Phase 4 게이트, targeted/sonnet)
- `T-A-RETRY · analyzer · 누락된 분석 근거 보완` (점수 기반 재실행)
- `T-W-RETRY · writer · 누락된 하네스 파일·패턴 보완`
- `T-V-RECHECK · MJS validator · 보완된 초기화 결과 재검증`

### 분리 저장소 작업 그래프 (paired-roots/hub-roots)

단일/모노레포의 `T-*` 그래프 대신 대칭 2-레인(`B-*` / `C1..CM-*`)을 쓴다. 그래프 형태·표시 제목 규칙·레인 실패 처리는 `references/split-repo.md`의 "작업 그래프" 절에 있다.

---

## Phase 2: 팀원 실행

### 오케스트레이터는 스크립트를 직접 실행하지 않는다

`agents/lib/*` 스크립트 블록은 전부 `pipeline-runner`에 위임한다 (2-0.5 `index`, 2-2.3 `assemble`, 2-3.5 `verify`, 3.7 `wiki`). 이 블록들은 정상 경로에서도 실행 확인·설정 작성·폴백·재시도·산출물 확인으로 수 회씩 왕복하는데, 오케스트레이터가 직접 하면 그 왕복마다 200~350K 컨텍스트를 다시 읽는다. 위임하면 왕복은 버려지는 서브에이전트 컨텍스트에서 일어나고 메인은 요약 한 덩어리만 받는다.

메인 스레드에 남는 스크립트 호출은 **단발 명령 2종뿐**이다. 위임해도 에이전트 스폰 비용이 절감분보다 커서 그대로 둔다.

| 남는 호출 | 위치 | 남기는 이유 |
|---|---|---|
| `build-index.mjs --apply-ai-patch` | 2-1.5 | 1회 호출, analyzer와 writer 사이에 끼어 있어 다른 블록과 묶이지 않음 |
| `ai-budget.mjs claim` | 2-1 / 2-2 / 2-3 / Phase 4 | 결과(exit 0/1)로 그 다음 `Agent()` 호출 여부를 결정하는 제어 게이트라 위임 불가 |

> **스크립트 경로 규칙 (위 잔여 호출과 `pipeline-runner`에 넘기는 `plugin_root` 공통)**: 스크립트는 대상 프로젝트가 아니라 *플러그인 설치 루트*에 있다. PowerShell은 `$env:CLAUDE_PLUGIN_ROOT`, bash는 `$CLAUDE_PLUGIN_ROOT`로 참조한다. 환경변수가 비어 있으면 이 SKILL.md가 위치한 플러그인 디렉터리(예: `~/.claude/plugins/cache/total-ito/...`)의 절대경로로 대체한다. cwd 기준 상대경로 `agents/lib/...`는 개발 저장소에서만 동작하므로 금지.
> **파이썬 인터프리터 규칙**: `.py` 스크립트를 부를 때 `python` 또는 `python3` **어느 쪽도 하드코딩하지 않는다.** 윈도우(공식 설치판·Store판)에는 `python`만 있고, 다수 리눅스 배포판·Homebrew에는 `python3`만 있다 — ITO 현장은 윈도우가 기본이고 CI는 리눅스라 양쪽을 다 밟는다. 먼저 `python3 --version`을 시도해 성공하면 `python3`, 실패하면 `python`을 쓴다(둘 다 실패하면 "파이썬 없음"을 WARN으로 보고하고 그 블록만 건너뛴다 — 조용히 넘어가지 않는다). 아래 예시는 `python`으로 적혀 있으나 실제 호출 시 이 규칙으로 결정한 이름을 쓴다.

### 분리 저장소 레인 실행 (paired-roots/hub-roots만 해당)

아래 2-0.5~2-5는 **레인 한 개를 대상으로 한 절차**다. 분리 저장소는 이 절차를 바꾸지 않고 레인 수만큼(B 1개 + C 1~M개) 같은 단계를 같은 메시지에서 병렬 실행한다. 단계별 실행 방식과 레인 상태 갱신 규칙은 `references/split-repo.md`의 "레인 실행" 절에 있다. 단일/모노레포는 이 절을 건너뛰고 2-0.5부터 그대로 따른다.

### 2-0.5. 결정론적 전수 인덱싱 (LLM 미사용) — `T-I`(또는 분리 저장소의 `B-I`/`C-I`)

analyzer 호출 전에 실행. `_workspace/01_analyzer_report.md`가 이미 있어 2-1을 스킵하는 경우 이 단계도 함께 스킵. `TaskCreate`가 있으면 이 절 시작 시 해당 작업(`T-I` 등)을 in_progress로, 반환 확인 후 completed로 갱신한다.

실행 환경 확인·설정 파일 작성·인덱싱·Vue 보강·폴백 사다리·AI 예산 초기화(Step A~F)는 전부 `pipeline-runner`에 위임한다. 절차 상세는 `agents/lib/pipeline-runner/block-index.md`에 있다(`agents/pipeline-runner.md`의 디스패치 표가 가리킨다).

```
Agent(
  subagent_type="total-ito:pipeline-runner",
  description="T-I · pipeline-runner · 소스 구조와 호출 관계 인덱싱",
  prompt="<pipeline-runner 에이전트 지침의 block: index를 실행한다.
  block: index. root: [절대경로]. tier: [Standard/Full]. mode: [init/incremental].
  plugin_root: [$env:CLAUDE_PLUGIN_ROOT 값]. ai_budget_session: [ai_budget_session].
  lane: [T-I 또는 B-I/C1-I 등].
  반환은 지침의 'block: index 반환 형식' 그대로만.>",
  model="sonnet"
)
```

반환의 `indexer_rank`가 3이면 인덱스가 만들어지지 않았다는 뜻이다 — 2-1의 analyzer가 인덱스를 처음부터 전부 작성한다(기존 동작, 회귀 없음). `ai_budget`이 `skipped(node 없음)`이면 2-1/2-2/2-3/Phase 4의 `claim` 호출을 전부 생략하고 무제한 진행한다. 반환의 `indexer_rank`·WARN은 Phase 3 보고에 포함한다.

### 2-0.7. 사전 견적 및 진행 확인 (LLM 미사용)

**여기가 사용자가 비용을 알고 결정하는 유일한 지점이다.** 이 뒤로는 LLM 구간이라 되돌릴 수 없다.

인덱싱이 끝났으므로 규모가 확정됐다. 견적을 뽑는다(스크립트 1회, 메인에서 직접 실행 — 결과로 다음 분기를 정하는 제어 게이트라 위임하지 않는다):

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" estimate --root "[절대경로]"
```

반환값(`files`·`tier`·`decidable_unresolved`·`estimated_tokens`·`estimated_minutes`)을 그대로 사용자에게 보인다.

```
인덱싱 완료 — 소스 [files]개 파일, 심볼 [symbols]개. (여기까지 LLM 사용 없음)

이제 LLM 분석 구간입니다. 예상 규모:
  Tier [tier] 기준 · 약 [estimated_minutes]분 · 약 [estimated_tokens] 토큰
  판정이 필요한 미해결 관계: [decidable_unresolved]건

  1. Full 로 진행      — 심층 분석 (마이그레이션·대규모 수정 계획이 있으면 권장)
  2. Standard 로 진행  — 위 견적의 약 60% (일상 유지보수에는 대개 충분)
  3. 여기서 중단        — 인덱스만 두고 나중에 이어서 (인덱스는 그대로 남습니다)
```

| 응답 | 동작 |
|------|------|
| `1` · 무응답 | Full로 진행 |
| `2` | Standard로 진행 — `00_init_scope.md`의 `tier:`를 Standard로 갱신 |
| `3` | 파이프라인 중단. 인덱스는 남아 있으므로 `analyze-impact`·`trace-logic`은 이미 동작한다고 안내하고 종료 |

Step 2.5에서 override 키워드로 Tier가 이미 확정됐으면 견적만 보이고 질문 없이 진행한다.

시간·토큰 한도는 이미 걸려 있다 — `block: index`의 Step E.5/F가 인덱싱 직후(2-0.5 시점)에 같은 견적을 내서 최초 `init` 호출에 `--minutes`/`--tokens`(견적의 2배)로 실어 보냈다. `initBudget`은 같은 session으로 재호출하면 새 인자를 무시하는 멱등성 가드가 있어서, 여기(2-0.7)에서 다시 `init`을 불러 한도를 거는 건 불가능하다 — 이 절은 사용자에게 견적을 보여주고 Tier를 확정하는 것만 한다.

토큰 한도가 실제로 의미 있으려면 `used.tokens`가 쌓여야 하는데, 이 하네스는 `Agent()`가 부분 실행 결과(텍스트)만 돌려줄 뿐 실사용 토큰 카운터를 주지 않고 hooks도 없어 진짜 계측은 불가능하다. 대신 **사전 배분 장부**로 근사한다 — 2-1/2-2/2-3에서 각 역할의 `claim --kind initial`이 성공한 직후, 그 역할의 대략적 몫을 기록한다:

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" record --root "[절대경로]" --role [역할] --spent-tokens [estimated_tokens × 비율]
```

비율은 `docs/harness-description.md`의 역할별 비용 구간 중앙값에서 근사한 것이다: analyzer 60%, writer 25%, pattern-extractor 15%(validator·harness-evaluator는 `claim` 대상이 아니므로 기록하지 않는다). **정확한 실사용량이 아니라 "프로젝트가 견적보다 훨씬 크게 나온 경우"를 잡기 위한 근사치라는 걸 감안한다** — 한 역할 내부에서 폭주하는 경우까지는 못 잡는다. 값을 알 수 없는 호스트에서는 생략 — 한도는 시간 쪽으로만 걸린다.

### 2-1. analyzer 호출

부분 재실행 + `_workspace/01_analyzer_report.md` 존재 시 스킵.

Tier별 mode/model 결정:
| Tier / 상황 | mode | model |
|------|------|-------|
| Standard | `init` (A + 스택 해당 Phase B만) | sonnet |
| Full | `init` (A + B 전체) | opus |
| 업데이트·인덱스 리프레시 (Step 3 표) | `incremental` (변경 파일만 재분석 + stale 엣지 무효화) | sonnet (Tier 무관) |

AI 예산이 초기화됐으면(Step F) claim 먼저:
```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" claim --root "[절대경로]" --session "[ai_budget_session]" --role analyzer --kind initial
```
(exit 1이면 이 Agent 호출을 하지 않고 레인 중단 — Step F 참조)

```
Agent(
  subagent_type="total-ito:analyzer",
  description="T-A · analyzer · 프로젝트 구조·의존성·레거시 로직 분석",
  prompt="<프로젝트 루트: [절대경로]. mode: init. tier: [Standard/Full].
  init_layout/paths: _workspace/00_init_scope.md 참조 (selected-paths면 해당 상대경로만 분석).
  2-0.5가 인덱스를 기계 생성했으면(_workspace/index/_meta.json 존재) 그 파일들 재작성 금지 —
  _analysis_input.json을 읽고 _unresolved.jsonl을 계약대로 처리해 _ai_patch.json만 출력한다
  (analyzer.md Step 8 '기계 인덱스가 있을 때' 분기). _meta.json이 없으면 기존대로 직접 작성.
  결과: _workspace/01_analyzer_report.md + (기계 인덱스 없을 때만) _workspace/index/*.json>",
  model="[sonnet/opus]"
)
```

`.claude/agents/analyzer.md`의 지침 따름. 완료 후 결과 파일 존재 확인.

AI 예산이 초기화됐으면 완료 직후 이 역할의 사전 배분 몫을 기록한다(2-0.7 설명 참조, analyzer는 견적의 60%): `node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" record --root "[절대경로]" --role analyzer --spent-tokens [estimated_tokens*0.6]`.

### 2-1.5. AI 보강 patch 병합 (기계 인덱스가 있을 때만)

`_workspace/index/_ai_patch.json`이 있으면 실행한다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/build-index.mjs" --root "[절대경로]" --apply-ai-patch "_workspace/index/_ai_patch.json"
```

기존 노드 사이의 엣지만 추가되고, 없는 노드를 참조하는 operation은 사유와 함께 거부된다. 전부 거부되면 비정상 종료하므로 **WARN으로 보고하고 계속 진행**한다(인덱스 자체는 유효하고 보강만 안 된 상태다). 병합 결과는 `_meta.json`의 `ai_enrichment`에 남는다.

analyzer가 `call_graph.json`을 직접 고치지 않고 patch로 내는 이유는 재인덱싱 때문이다. `--mode incremental`은 캐시에서 그래프를 다시 만들므로, 손으로 덧붙인 엣지는 다음 "인덱스만 갱신" 실행에서 **에러 없이 사라진다**. patch는 파일을 쓰기 전에 다시 병합되고 데드 코드도 그에 맞춰 재계산된다.

### 2-2. writer 호출

`_workspace/01_analyzer_report.md` 존재 확인 후.

model: 모든 Tier에서 sonnet (2026-07-14 하이브리드 빌더 도입으로 writer 작업이 스킬 3종 + JSON 2개로 줄어 opus 불필요 — 2026-07-23 변경).

AI 예산이 초기화됐으면 claim 먼저: `node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" claim --root "[절대경로]" --session "[ai_budget_session]" --role writer --kind initial` (exit 1이면 중단).

```
Agent(
  subagent_type="total-ito:writer",
  description="T-W · writer · 하네스 파일과 프로젝트 가이드 생성",
  prompt="<프로젝트 루트: [절대경로]. tier: [Standard/Full]. 입력: _workspace/01_analyzer_report.md + _workspace/index/*.json (필요 시). 출력: 하네스 파일들(trace/scaffolder/find-logic, cross-repo-* 있는 경우) + _workspace/claude_md_fields.json + _workspace/writer_decisions.json>",
  model="sonnet"
)
```

AI 예산이 초기화됐으면 완료 직후 기록한다(writer는 견적의 25%): `node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" record --root "[절대경로]" --role writer --spent-tokens [estimated_tokens*0.25]`.

> writer는 trace.md·scaffolder.md·find-logic.md만 markdown으로 직접 작성한다 (pair_config.md 있으면 cross-repo-scaffold.md·cross-repo-modify.md도). CLAUDE.md는 `_workspace/claude_md_fields.json`에 필드(프로젝트명·한줄설명·스택요약·요청흐름·파일위치표 행·빌드명령·주의사항)만, patterns 스켈레톤·02_writer_files.md는 `_workspace/writer_decisions.json`에 결정 값(조건부 스킬 적용 여부+사유, 패턴 파일명 목록, 탐지 스택, 적용 결정 사유)만 채워서 낸다. domain-expert.md(analyzer_report 그대로 주입)·patterns 스켈레톤·02_writer_files.md는 writer가 쓰지 않고 다음 단계(2-2.3)에서 조립한다. analyze-impact/safe-modify/scaffold-feature/vibe/plan-migration/review-sql은 플러그인 전역판을 그대로 쓰므로 writer도 skills_builder.py도 로컬 파일을 만들지 않는다 — writer는 plan-migration/review-sql의 *적용 여부*만 판단해 writer_decisions.json에 남긴다.

### 2-2.3. 하네스 파일 조립 (CLAUDE.md + domain-expert.md + 패턴 스켈레톤 + ito-guide.md + 02_writer_files.md)

writer 완료 후 실행. LLM 호출 없이 전부 결정론적 파일 조립·복사이므로 `pipeline-runner`에 위임한다. 조립 항목과 재시도 규칙 상세는 `agents/lib/pipeline-runner/block-assemble.md`에 있다(`agents/pipeline-runner.md`의 디스패치 표가 가리킨다).

```
Agent(
  subagent_type="total-ito:pipeline-runner",
  description="T-W-BUILD · pipeline-runner · 하네스 파일 조립",
  prompt="<pipeline-runner 에이전트 지침의 block: assemble을 실행한다.
  block: assemble. root: [절대경로]. tier: [Standard/Full].
  plugin_root: [$env:CLAUDE_PLUGIN_ROOT 값]. lane: [T-W 또는 B-W/C1-W 등].
  반환은 지침의 'block: assemble 반환 형식' 그대로만.>",
  model="sonnet"
)
```

> writer는 trace.md·scaffolder.md·find-logic.md만 markdown으로 직접 작성한다 (pair_config.md 있으면 cross-repo-scaffold.md·cross-repo-modify.md도). CLAUDE.md는 `_workspace/claude_md_fields.json`에 필드만, patterns 스켈레톤·02_writer_files.md는 `_workspace/writer_decisions.json`에 결정 값만 채워서 낸다. domain-expert.md·patterns 스켈레톤·02_writer_files.md는 이 단계에서 조립된다. analyze-impact/safe-modify/scaffold-feature/vibe/plan-migration/review-sql은 플러그인 전역판을 그대로 쓰므로 로컬 파일을 만들지 않는다 — writer는 plan-migration/review-sql의 *적용 여부*만 판단해 writer_decisions.json에 남긴다.

반환의 `RESULT`가 `PARTIAL`/`FAIL`이면 누락 항목을 그대로 Phase 3 보고에 옮기고 계속 진행한다. 스크립트가 항목별로 독립 처리하므로 일부만 실패할 수 있다 — 파이프라인을 중단하지 않는다.

### 2-2.5. ito-guide.md (2-2.3에 통합 — 별도 Agent 호출 없음)

`.claude/ito-guide.md`는 2-2.3의 `skills_builder.py`가 `agents/lib/ito_guide.md.template`로 기계 조립한다(zero-LLM) — 전 항목이 이미 있는 산출물(스킬 frontmatter·claude_md_fields·writer_decisions·pair_config)의 재진술이라 LLM 작성이 불필요했다 (2026-07-23 전환, 이전에는 매 초기화마다 sonnet ~5K 토큰 소비). 존재 확인도 2-2.3의 `pipeline-runner` 반환(`.claude/ito-guide.md: 생성 | 누락`)으로 끝나므로 오케스트레이터가 따로 확인하지 않는다. `누락`이면 "ito-guide 미생성" WARN 후 계속 진행.

### 2-3. pattern-extractor 호출 (레인 간 병렬 가능)

2-2.3(assemble 블록)이 patterns/ 스켈레톤을 생성한 뒤에만 호출한다 — 스켈레톤은 writer(2-2)가 아니라 `skills_builder.py`(2-2.3)의 산출물이므로, T-P를 TaskCreate 의존성만으로 착수시키지 말고 2-2.3 반환을 받고 시작한다.

AI 예산이 초기화됐으면 claim 먼저: `node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" claim --root "[절대경로]" --session "[ai_budget_session]" --role pattern-extractor --kind initial` (exit 1이면 중단).

```
Agent(
  subagent_type="total-ito:pattern-extractor",
  description="T-P · pattern-extractor · 레이어별 컨벤션 패턴 추출",
  prompt="<프로젝트 루트: [절대경로]. 입력: .claude/patterns/*.md 스켈레톤 + _workspace/01_analyzer_report.md + _workspace/index/*.json. 출력: 패턴 파일 본문 + .claude/patterns/pattern_profile.json + _workspace/05_patterns_extracted.md>",
  model="sonnet"
)
```

AI 예산이 초기화됐으면 완료 직후 기록한다(pattern-extractor는 견적의 15%): `node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" record --root "[절대경로]" --role pattern-extractor --spent-tokens [estimated_tokens*0.15]`.

### 2-3.5. 패턴 프로필 + 기계 검증 (LLM 미사용) — `pipeline-runner`

pattern-extractor 완료 직후, validator Agent 호출 전에 실행한다. `pattern_profile.py validate` → `validator_checks.py` → `validate-harness.mjs` 세 스크립트와 그 결과 확인을 한 번의 위임으로 처리한다. 절차 상세는 `agents/lib/pipeline-runner/block-verify.md`에 있다(`agents/pipeline-runner.md`의 디스패치 표가 가리킨다).

```
Agent(
  subagent_type="total-ito:pipeline-runner",
  description="T-V-CHECK · pipeline-runner · 패턴 프로필과 인덱스 기계 검증",
  prompt="<pipeline-runner 에이전트 지침의 block: verify를 실행한다.
  block: verify. root: [절대경로]. tier: [Standard/Full].
  plugin_root: [$env:CLAUDE_PLUGIN_ROOT 값]. lane: [T-V 또는 B-V/C1-V 등].
  반환은 지침의 'block: verify 반환 형식' 그대로만.>",
  model="sonnet"
)
```

반환의 `RESULT`별 분기.

| RESULT | 동작 |
|--------|------|
| `OK` / `PARTIAL` | 2-4로 진행. `mechanical`·`schema` 필드값은 Phase 4 인덱스 무결성 게이트가 그대로 쓰므로 버리지 않는다 |
| `PROFILE_FAIL` (1회차) | `profile_missing` 항목을 그대로 pattern-extractor에 넘겨 1회 보완시킨 뒤 이 블록을 다시 호출 |
| `PROFILE_FAIL` (2회차) | 추가 재시도 없음. T-V를 진단 리포트 생성 목적으로만 실행하되 프로필을 사용 가능하다고 표시하지 않으며, 파이프라인·validator·최종 보고를 **FAIL**로 다룬다. 분리 저장소 레인은 `status: failed, last_stage: W`로 남겨 barrier를 통과시키지 않는다 |

`validate-harness.mjs`의 exit 1은 스키마 FAIL이 있다는 뜻이지 스크립트 실패가 아니다 — 결과 파일은 정상적으로 쓰이고 Phase 4의 무결성 게이트가 그 값을 읽는다.

### 2-4. validator 호출

모든 Tier에서 실행. 2-3.5가 이미 `validator_mechanical.json`·`validator_schema.json`·`pattern_profile_validation.json`을 남겼으므로 여기서는 validator Agent만 호출한다.

```
Agent(
  subagent_type="total-ito:validator",
  description="T-V · MJS validator · 하네스 구조와 근거 검증",
  prompt="<프로젝트 루트: [절대경로]. tier: [Standard/Full]. 입력: _workspace/01_analyzer_report.md, _workspace/02_writer_files.md, _workspace/validator_mechanical.json(있으면), _workspace/validator_schema.json(있으면), _workspace/pattern_profile_validation.json(있으면), (있으면) _workspace/index/. 출력: _workspace/03_validator_report.md>",
  model="sonnet"
)
```

> QA(경계면 교차 비교)는 더 이상 Phase 2에서 자동 실행하지 않는다. Agent 호출 방법은 Phase 3.6 "선택 작업 안내"에서 사용자가 선택했을 때만 참조한다 — 토큰 절감을 위해 Tier와 무관하게 항상 온디맨드다.

### 2-5. harness-evaluator 호출 (모든 Tier)

validator 완료 후 실행:

```
Agent(
  subagent_type="total-ito:harness-evaluator",
  description="T-E · harness-evaluator · harness 품질 평가",
  prompt="<프로젝트 루트: [절대경로]. tier: [Standard/Full].
  입력: _workspace/01_analyzer_report.md, _workspace/03_validator_report.md,
        _workspace/pattern_profile_validation.json,
        생성된 harness 파일들 (CLAUDE.md, .claude/skills/, .claude/agents/, .claude/patterns/).
  출력: _workspace/06_eval_report.md>",
  model="sonnet"
)
```

---

## Phase 3: 결과 종합 및 보고

`_workspace/03_validator_report.md`, `_workspace/05_patterns_extracted.md`(있으면), `_workspace/04_qa_report.md`(있으면, 선택 작업에서 이미 실행한 경우만)를 읽어 사용자에게 다음 형식으로 보고:

```
하네스 초기화 완료 (harness-fin v1) [Tier: Standard/Full]

생성된 파일:

[Core]
- CLAUDE.md
- .claude/ito-guide.md               (사용 설명서)
- .claude/skills/trace.md, scaffolder.md, find-logic.md
- .claude/agents/domain-expert.md
- .claude/patterns/[목록]

[사용 가능한 워크플로우 스킬 — 플러그인 전역, 로컬 파일 없음]
- analyze-impact / safe-modify / scaffold-feature / vibe (항상)
- plan-migration                            (적용 조건 충족 시)
- review-sql                                (DB 사용 시)

[Indexes (NEW)]
- _workspace/index/call_graph.json (노드: N, 엣지: M)
- _workspace/index/symbols.json
- _workspace/index/transactions.json
- _workspace/index/external_io.json
- _workspace/index/sql_usage.json           (DB 사용 시)
- _workspace/index/schema.json              (DB 접속 가능 시)
- _workspace/index/dead_code.json
- _workspace/index/env_branches.json
- _workspace/index/owasp_top10.json         (Security 설정 탐지 시)

구조 검증 (validator):
[신뢰도 점수 + 보완 권장 항목]
[validator_schema.json 있으면: 인덱스 스키마 검증 PASS/WARN/FAIL, plugin_contract_failures 있으면 "플러그인 인덱스 계약 결함" 별도 표기]

AI 예산 증적 (ai-budget.json 있으면): [session] · initial [used]/[limit] · retries [used]/[limit]

패턴 추출 (pattern-extractor):
- 처리한 패턴 파일: N개
- 구조화 프로필 검증: [PASS / FAIL] (preferred N개, 실제 기준 파일 N개)
- 신뢰도: [HIGH: A, MEDIUM: B, LOW: C]
- 안티패턴 발견: K건

Eval 품질 점수 (harness-evaluator):
[점수: N/100 — PASS / PARTIAL / RETRY]
- 커버리지: /25 | 정확도: /25 | 실행가능성: /25 | 컨텍스트 품질: /25
(PARTIAL/RETRY이면 → Phase 4 재생성 실행 후 최종 점수 업데이트)
(인덱스 무결성 기계 게이트가 걸렸으면 → PASS여도 analyzer 재실행 1회 진행, 결과·잔존 이슈 여부 여기 표시)

이제 다음 작업이 가능합니다:
  "이 함수 영향도 분석해줘"          → analyze-impact
  "이 변경 안전하게 적용"            → safe-modify
  "[기능] 패턴 따라 만들어줘"        → scaffold-feature
  "Spring Boot로 마이그레이션"       → plan-migration
  "이 SQL 리뷰해줘"                  → review-sql
  "이 코드 뭐하는 거야"              → legacy-decoder (직접 호출)
  "문서 동기화"                      → doc-syncer (직접 호출)

다음 단계 — 팀에 공유 (이걸 해야 다음 사람이 초기화를 반복하지 않습니다):

  1) _ai_patch.json이 .gitignore에 걸려 있는지 먼저 확인
     git check-ignore -v _workspace/index/_ai_patch.json
     걸려 있으면 .gitignore에 예외를 추가:  !_workspace/index/_ai_patch.json

  2) git add CLAUDE.md .claude/ _workspace/index/_ai_patch.json
     git commit -m "docs: add project harness (harness-fin v1)"

  팀원은 pull 후 아무것도 하지 않아도 됩니다 — 필요하면 인덱싱 한 번(수십 초, LLM 사용 없음)이
  자동으로 돌고, 그 뒤 바로 analyze-impact·trace-logic 등을 쓸 수 있습니다.
  (인덱스까지 커밋하면 그 인덱싱조차 생략됩니다 — 팀 정책에 맞게 선택하세요.)

피드백 요청:
결과에서 개선할 부분이 있나요? 워크플로우 스킬 트리거 조정이 필요한가요?
```

HIGH 우선순위 항목이 있으면 사용자에게 명시적 안내. 자동 수정 X.

---

## Phase 3.5: 파트너 연동 (P-BARRIER → P-PAIR → P-REFRESH)

**Phase -1 결과 및 기존 설정 기반 분기:**

| 조건 | 동작 |
|------|------|
| `init_layout = "single-root"`, `"monorepo"`, `"selected-paths"` | 이 Phase 전체 스킵 → Phase 3.6으로 |
| `_workspace/pair_config.md` 이미 있고 `pair_lane_state.md`도 `pair_state: complete` | 이 Phase 전체 스킵 → Phase 3.6으로 |
| `init_layout = "paired-roots"`/`"hub-roots"` + Phase 2의 분리 저장소 레인이 방금 `pair_state: barrier_done`으로 끝남 | 아래 P-BARRIER부터 진행 |
| Phase -1 스킵 + `pair_config.md` 없음 (레인 그래프 자체를 안 거친 경우) | 연동 여부 질문 후 진행(기존 방식 — pair-init 단독 실행) |

위 표에서 스킵이 아닌 행으로 판정됐으면 `references/split-repo.md`의 "Phase 3.5" 절을 읽고 그대로 수행한다 — P-BARRIER/P-PAIR/P-REFRESH 절차와 마지막 행(연동 여부 질문 방식)이 모두 그 절에 있다. 완료 후 Phase 3.6으로 진행한다.

---

## Phase 3.6: 선택 작업 안내 (wiki · QA)

초기화 파이프라인이 끝난 뒤, 기본 파이프라인에 포함되지 않는 후속 작업을 **한 번의 질문으로** 제시하고 선택받는다. 선택하지 않은 항목은 실행하지 않는다.

> wiki는 2026-08-16부터 자동 실행이 아니다 — 이 단계는 초기화 컨텍스트가 최대일 때 도달하므로, 초기화와 분리해 새 세션에서 돌리는 편이 같은 결과를 더 싸게 얻는다. 경위는 `docs/changelog.md` 2026-08-16 항목.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
초기화가 끝났습니다. 아래는 아직 실행하지 않은 선택 작업입니다.

  1. wiki 생성   — 산출물을 탐색 가능한 정적 wiki 페이지로 변환합니다
     (+n: AI 해설 페이지 추가 — 분석 리포트를 재활용한 시스템 개요 내러티브, 약 5~10K 토큰)
  2. 경계 QA     — writer 주장(패턴·컨벤션)이 실제 코드·인덱스와 일치하는지 교차검증합니다
  3. 지금 안 함  — 초기화만 마칩니다 (권장)

지금 컨텍스트가 이미 커져 있어, 새 세션에서 "위키 만들어줘"(generate-wiki) ·
"경계 QA 실행해줘"로 따로 돌리는 편이 같은 결과를 더 싸게 얻습니다.

실행할까요? (번호 복수 선택 가능, 예: 1 2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

| 응답 | 동작 |
|------|------|
| `1` 포함 | Phase 3.7의 "wiki 실행" 수행 |
| `1 +n` (또는 "해설 포함") | wiki 실행에 `narrative: true`를 함께 넘긴다 |
| `2` 포함 | Phase 3.7의 "QA 실행" 수행 |
| `3` · 무응답 · 다른 주제로 전환 | 둘 다 실행하지 않고 Phase 4로 진행 (기본값) |

`_workspace/03_validator_report.md` 신뢰도 < 50이면 "2. 경계 QA" 항목에 "— 구조 검증 실패로 결과 없이 종료됨" 주석을 붙여 표시한다(선택해도 미실행 사유만 기록).

> Phase 3.5(파트너 연동 — P-BARRIER/P-PAIR/P-REFRESH, 대부분 질문 없이 자동 진행) → Phase 3.6(이 메뉴) → Phase 3.7(선택된 것만 실행) 순서다. 파트너 연동이 실패해 단독 상태로 왔으면 1번 설명에 "파트너 병합 없이 단독 wiki로 생성됨"을 덧붙인다.

---

## Phase 3.7: 선택 작업 실행

Phase 3.6에서 고른 항목만 실행한다. 둘 다 골랐으면 두 `Agent()` 호출을 **같은 메시지에서** 발행한다 — 서로 의존하지 않는다.

### wiki 실행 (1번 선택 시)

생성 자체는 `wiki_generator.py` 한 번이지만 실제로는 기존 wiki 백업·산출물 확인·`07_wiki_build.md` 확인이 뒤따르므로 `pipeline-runner`에 위임한다. 절차 상세는 `agents/lib/pipeline-runner/block-wiki.md`에 있다(`agents/pipeline-runner.md`의 디스패치 표가 가리킨다).

```
Agent(
  subagent_type="total-ito:pipeline-runner",
  description="T-WIKI · pipeline-runner · wiki 페이지 생성",
  prompt="<pipeline-runner 에이전트 지침의 block: wiki를 실행한다.
  block: wiki. root: [절대경로]. plugin_root: [$env:CLAUDE_PLUGIN_ROOT 값].
  lane: [단일이면 T-WIKI, 분리 저장소면 레인별로 각각].
  narrative: [사용자가 '+n'/'해설 포함'을 골랐으면 true, 아니면 생략].
  반환은 지침의 'block: wiki 반환 형식' 그대로만.>",
  model="sonnet"
)
```

`pair_config.md`가 있으면 `wiki_generator.py`가 파트너의 call_graph.json·01_analyzer_report.md·api_contract.json·schema.json·external_io.json을 함께 읽어 architecture/api-endpoints/database/external-systems 페이지에 자동 병합한다. 별도 인자 없이 동작하므로 프롬프트에 추가할 것이 없다.

반환이 `RESULT: FAIL`이어도 harness-init 자체를 막지 않는다 — WARN 후 Phase 4로 계속 진행.

**중앙 허브 발행 여부**는 wiki가 실제로 생성된 경우에만 이어서 묻는다. `generate-wiki` Phase 3.5와 같은 질문이며, 서브에이전트는 사용자에게 질문할 수 없으므로 오케스트레이터가 한다. Y면 `publish-wiki` 스킬을 실행한다. DB 저장은 harness에 내장된 `agents/lib/wikihub_db/`가 처리하므로 별도 프로젝트 wiki-hub 설치 여부와 무관하게 항상 가능하다.

### QA 실행 (2번 선택 시)

Boundary 6 기계 체크(`qa_boundary6.py`)는 오케스트레이터가 미리 돌리지 않는다 — qa 에이전트가 자기 컨텍스트에서 첫 순서로 직접 실행한다(`agents/qa.md` "Boundary 6" 절). 스크립트 1회 실행을 위해 메인 스레드가 왕복할 이유가 없고, qa는 어차피 그 결과를 읽어야 하는 유일한 소비자다.

```
Agent(
  subagent_type="total-ito:qa",
  description="T-Q · qa · 경계면 교차 비교 검증",
  prompt="<프로젝트 루트: [절대경로]. plugin_root: [$env:CLAUDE_PLUGIN_ROOT 값]. Boundary 6은 qa_boundary6.py를 직접 실행해 처리한다. 입력: _workspace/01~03 + _workspace/index/. 출력: _workspace/04_qa_report.md>",
  model="sonnet"
)
```

신뢰도 < 50이면 이 Agent 호출 대신 "구조 검증 실패로 미실행" 한 줄만 `_workspace/04_qa_report.md`에 작성.

### 실행 후

선택한 항목의 결과를 Phase 3와 같은 형식으로 사용자에게 보고한 뒤 Phase 4로 진행한다. 실행하지 않은 항목은 "미실행 — 나중에 `위키 만들어줘` / `경계 QA 실행해줘`로 개별 호출 가능"으로 한 줄 남긴다.

---

## Phase 4: Eval Loop — Karpathy AutoResearch 영감

1차 평가(harness-evaluator)는 Phase 2-5에서 모든 Tier가 항상 실행한다(분리 저장소는 레인마다 독립 실행) — 이 Phase는 그 결과(`_workspace/06_eval_report.md`)의 총점을 읽어 **점수 기반 재생성 루프만** 담당한다(evaluator 실패로 파일이 없으면 에러 핸들링 표에 따라 eval 없이 Phase 3 보고로 종료). 분리 저장소는 자기 레인의 eval 결과만 이 Phase의 대상이다 — 파트너 레인의 재생성은 그쪽 레인 실행(Phase 2) 안에서 이미 자체적으로 처리된다.

### 인덱스 무결성 기계 게이트 (점수와 무관하게 우선 적용)

harness-evaluator는 harness 파일이 인덱스를 참조하는지만 보고 인덱스 *내용*(dangling edge, `_meta` 누락, edge 종류 누락)은 채점하지 않는다 — PASS여도 인덱스가 구조적으로 깨진 채 통과할 수 있다. 점수 해석보다 먼저 다음을 결정론적으로 확인한다.

2-3.5 `block: verify` 반환의 `mechanical`·`mechanical_gate_warns` 값을 쓴다(값을 잃었으면 `_workspace/validator_mechanical.json`을 직접 읽는다 — 스크립트 재실행은 불필요). 아래 중 하나라도 해당하면:

- `index_integrity_fail == true`
- `index_spotcheck_fail == true`
- `warns` 배열에 "analyzer.md Step 8 참고" 문구가 포함된 항목 1개 이상 (call_graph 추출 누락 의심 휴리스틱 — import/inherit/inject 편중 감지)
- `warns` 배열에 "generated_at" 문구가 포함된 항목 1개 이상 (실제 시각 미조회 의심)

같은 반환의 `schema`·`schema_fail_messages`(원본은 `_workspace/validator_schema.json`)에서 `failures > 0`인 경우도 게이트 대상이다. `plugin_contract_failures`(`checks`의 `code === "PLUGIN_INDEX_CONTRACT"`)는 `build-index.mjs`/`docs/index-schema/*.json` 자체의 계약 결함이라 analyzer나 프로젝트 소스 문제가 아니며, 아래 표에서 별도로 처리한다.

위 중 하나라도 해당하면 **원인을 소유한 쪽에 맞는 조치**를 취한다. 예전에는 신호 종류와 무관하게 `analyzer`를 통째로(Full이면 opus) 재실행했는데, 게이트가 요구하는 것은 대부분 analyzer가 고칠 수 없거나(인덱서 소유 파일) 패치 오퍼레이션 몇 개면 끝나는 일이라 값을 못 하는 비용이었다. 아래 표로 라우팅한다.

| 게이트 신호 | 원인 소유자 | 조치 | LLM 비용 |
|---|---|---|---|
| `index_integrity_fail` · `index_spotcheck_fail` + `_meta.generator == "deterministic-indexer"` | 인덱서 | 2-0.5의 `block: index`를 `mode: init`으로 1회 재실행 | 없음 |
| 같은 신호 + 기계 인덱스 없음(analyzer가 직접 작성) | analyzer | 아래 **targeted 재실행** | sonnet 1회 |
| `warns`에 "analyzer.md Step 8 참고" (inherit·inject edge 0개) | analyzer | 아래 **targeted 재실행** — `_ai_patch.json`의 `add_edge`로 해소되는 신호다 | sonnet 1회 |
| `warns`에 "generated_at" | 그 파일을 쓴 쪽 | 기계 인덱스면 `block: index` 재실행, analyzer 산출물이면 targeted 재실행 | 없음 또는 sonnet 1회 |
| `schema.failures > 0` + `plugin_contract_failures == 0`, 대상이 인덱서 소유 파일(`data_flow`·`client_index` 포함 — 둘 다 구조 필드만 필수라 스키마 실패는 항상 구조 쪽 결함이다) | 인덱서 | `block: index` 재실행 | 없음 |
| 같은 조건, 대상이 `owasp_top10`(analyzer 전량 작성) | analyzer | targeted 재실행 | sonnet 1회 |
| 같은 조건, 대상이 `api_contract` | api-bridge | `api-bridge` extract 재실행(자체 스키마 검증 포함 — `agents/api-bridge.md` Step 4 규칙 3) | sonnet 1회 |
| `plugin_contract_failures > 0` | 플러그인 | **AI로 재시도하지 않는다.** Phase 3 보고에 "플러그인 인덱스 계약 결함 — build-index.mjs/docs/index-schema 확인 필요"로 명시 | 없음 |

`analyzer`가 인덱서 소유 파일(`_meta.json`의 `indexes` 목록)을 고칠 수 없다는 것이 라우팅의 근거다 — `agents/analyzer.md` Step 8 "기계 인덱스가 있을 때" 계약상 그 파일들은 한 줄도 건드리지 못하고 `_ai_patch.json`만 낼 수 있다. 그런 파일의 구조 결함에 analyzer를 부르는 것은 정의상 해결될 수 없는 호출이었다.

### targeted 재실행 (게이트가 analyzer로 라우팅한 경우)

전체 재분석이 아니라 **지목된 항목만 고치는 좁은 패스**다. task-id는 `T-A-PATCH`.

```
Agent(
  subagent_type="total-ito:analyzer",
  description="T-A-PATCH · analyzer · 인덱스 무결성 지적 항목 보강",
  prompt="<mode: targeted. 프로젝트 루트: [절대경로].
  고칠 항목(이것만 본다): [해당 warn·FAIL 메시지 원문].
  Phase A/B 재분석 금지, _workspace/01_analyzer_report.md 재작성 금지.
  기계 인덱스가 있으면 _workspace/index/_ai_patch.json만, 없으면 지목된 인덱스 파일만 고친다.>",
  model="sonnet"
)
```

`mode: targeted`의 계약은 `agents/analyzer.md` "실행 모드" 표에 있다. sonnet을 쓰는 이유는 이 패스가 아키텍처 판단이 아니라 지목된 관계를 소스에서 확인해 패치 오퍼레이션으로 옮기는 작업이기 때문이다 — Full Tier의 최초 분석(2-1)은 그대로 opus다.

기계 인덱스가 있으면 targeted 재실행 뒤 2-1.5의 `--apply-ai-patch`를 다시 실행해야 패치가 반영된다. 빠뜨리면 `_ai_patch.json`만 남고 인덱스는 그대로라 게이트가 그대로 재현된다.

harness-evaluator가 이미 `analyzer` fix_target을 반환했으면 이 게이트의 항목을 그 행에 병합한다(같은 회차에 analyzer를 두 번 부르지 않는다). 단 그 fix_target이 점수 기반(PARTIAL/RETRY)이면 병합된 행은 아래 "점수별 동작"의 모델 규칙을 따른다 — 게이트 단독일 때만 sonnet 고정이다.

### 게이트 해소 확인

조치 완료 후 2-3.5의 `pipeline-runner` `block: verify`를 1회 다시 호출해 게이트가 해소됐는지 확인한다(여기서도 스크립트를 메인에서 직접 돌리지 않는다). 해소 안 되면 추가 재시도 없이 Phase 3 보고에 "인덱스 무결성 잔존 이슈"로 남은 FAIL/WARN을 그대로 명시하고 진행한다. 점수가 PASS인데 게이트만 걸린 경우, 조치가 LLM 없는 `block: index` 재실행뿐이었다면 **harness-evaluator 재평가는 생략한다** — 인덱스를 다시 만들었을 뿐 harness 파일이 바뀌지 않아 점수가 달라질 수 없다.

### 점수별 동작

| 총점 | 결정 | 동작 |
|------|------|------|
| 80~100 (PASS) | 완료 | Phase 3 보고 그대로 사용자에게 전달 |
| 60~79 (PARTIAL) | 타겟 재생성 | fix_targets 기반 특정 에이전트 재실행 → 재평가 (1회) |
| 0~59 (RETRY) | 주요 재생성 | fix_targets 상위 2개 에이전트 재실행 → 재평가 (1회) |

### 타겟 재생성 실행 (PARTIAL/RETRY)

`_workspace/06_eval_report.md`의 fix_targets를 읽어 각 에이전트 재실행. fix_target.agent는 `analyzer` 또는 `writer`만 반환된다 — task-id는 `analyzer→T-A`, `writer→T-W` 매핑을 따른다. 점수가 PASS인데 게이트만 걸린 경우는 여기로 오지 않고 위 "게이트 라우팅" 표대로 처리한다. 게이트와 점수 기반 fix_target이 겹치면 위 병합 규칙에 따라 한 행으로 합쳐 여기서 한 번만 실행한다:

AI 예산이 초기화됐으면 각 fix_target마다 재실행 전 claim(exit 1이면 그 fix_target은 건너뛰고 Phase 3 보고에 "예산 소진으로 미실행" 명시, 다른 fix_target은 계속 진행). 게이트가 부르는 `T-A-PATCH`도 `--role analyzer --kind retry`로 같은 claim을 거친다 — LLM을 쓰지 않는 `block: index` 재실행은 claim 대상이 아니다:
```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" claim --root "[절대경로]" --session "[ai_budget_session]" --role "[fix_target.agent]" --kind retry --reason "[fix_target.instruction, 100자로 트림]"
```

```
for each fix_target in eval_report.fix_targets (우선순위 순):
  Agent(
    subagent_type="total-ito:[fix_target.agent]",
    description="[fix_target.agent에 대응하는 task-id]-RETRY · [fix_target.agent] · 개선 재실행",
    prompt="<재실행.
    (analyzer이고 PARTIAL 구간이면) mode: targeted — Phase A/B 재분석과 01_analyzer_report.md 재작성 금지.
    (analyzer이고 RETRY 구간이면) mode: init — 분석 자체를 다시 한다.
    개선 지시: [fix_target.instruction].
    범위: [fix_target.scope].
    프로젝트 루트: [절대경로].
    기존 산출물: _workspace/01_analyzer_report.md, _workspace/02_writer_files.md>",
    model="[아래 규칙]"
  )
```

재실행 model 규칙 — **부분 보완은 sonnet, 분석 자체가 부실할 때만 opus**다. "tier별 모델"로 뭉뚱그리지 않는다.

| 재실행 종류 | model |
|---|---|
| 게이트 단독(점수 PASS) → `T-A-PATCH` | sonnet (Tier 무관, 위 targeted 절 참조) |
| PARTIAL(60~79)의 `analyzer` fix_target | sonnet (Tier 무관) — 지목된 항목 보완이지 재분석이 아니다 |
| RETRY(0~59)의 `analyzer` fix_target | Full이면 opus, Standard면 sonnet — 점수가 이 구간이면 분석 자체를 다시 봐야 한다 |
| `writer` 재실행 | 모든 Tier에서 sonnet (2026-07-23 결정) |

PARTIAL 구간을 sonnet으로 내리는 근거는 fix_target이 `instruction`+`scope`로 범위가 이미 좁혀져 있다는 점이다. 2026-08-15 세션에서 opus analyzer가 5회 돌았는데 그중 3회(`B-A-RETRY`·`C-A-RETRY`·`B-A-RETRY2`)가 이런 좁은 보완이었다.

writer 재실행 후에는 2-2.3의 `pipeline-runner` `block: assemble`을 다시 호출해 CLAUDE.md·02_writer_files.md 등을 재조립한다.

재생성 완료 후 harness-evaluator 1회 재실행 (평가 회차 = 2):

```
Agent(
  subagent_type="total-ito:harness-evaluator",
  description="T-E-RECHECK · harness-evaluator · harness 품질 재평가 (2차)",
  prompt="<평가 회차: 2.
  프로젝트 루트: [절대경로]. tier: [Standard/Full].
  출력: _workspace/06_eval_report.md (덮어쓰기)>",
  model="sonnet"
)
```

2차 평가 후에는 점수와 무관하게 Phase 3 보고로 넘어간다. **무한 루프 없음.**

### 개선 델타 표시

Phase 3 보고 중 "Eval 품질 점수" 섹션에 1차→2차 점수 변화 표시:

```
Eval 품질 점수: 63/100 → 84/100 (+21, PARTIAL→PASS)
```

---

## 에러 핸들링

원칙: **1회 재시도 후 재실패 시 결과 없이 진행하고 보고서에 누락 명시. 상충 데이터는 출처 병기.**

| 상황 | 대응 |
|------|------|
| analyzer가 산출물 미생성 | 1회 재실행. 재실패 시 "분석 실패 — 수동 분석 필요" 보고 후 중단 |
| analyzer가 인덱스 일부만 생성 | writer/validator/qa는 진행, 누락 인덱스에 의존하는 워크플로우 스킬은 "인덱스 누락" WARN |
| writer 일부 파일만 생성 | 누락 목록 보고. validator는 생성된 파일에만 검증. 누락 워크플로우 스킬 명시 |
| writer가 claude_md_fields.json 미생성 | skills_builder.py가 CLAUDE.md 조립 스킵. "CLAUDE.md 미생성 — writer 재실행 필요" WARN. 다른 항목(스킬·domain-expert.md)은 계속 배포 |
| writer가 writer_decisions.json 미생성 | skills_builder.py가 조건부 스킬·패턴 스켈레톤·02_writer_files.md 조립 전부 스킵. "writer 재실행 필요" WARN. CLAUDE.md·domain-expert.md·항상배포 스킬 3종은 계속 배포 |
| pattern-extractor 또는 프로필 검증 실패 | patterns/ 는 스켈레톤·미검증 상태로 남기고 validator에 FAIL 전달. "pattern-extractor 재실행 권고" 안내 |
| validator 보안 위험 발견 | 자동 수정 금지. 위치 명시, 사용자 직접 처리 |
| qa DEAD/ORPHAN 발견 | 자동 수정 금지. 우선순위 표시, 사용자 직접 처리 |
| validator 신뢰도 < 50 | Phase 3.6 메뉴에서 QA를 골라도 실행 대신 "구조 검증 실패로 미실행" 한 줄만 작성. "validator 권고 우선 처리 후 재실행" 안내 |
| 작업 디렉토리 권한 오류 | 즉시 중단, 권한 확인 요청 |
| `_workspace/` 생성 실패 | 1회 재시도. 실패 시 중단 |
| harness-evaluator 실패 | eval 없이 Phase 3 결과만 보고. "eval 미실행" 안내 |
| eval 재생성 후 점수 하락 | 재생성 결과 무시, 초기 harness 유지. 1차·2차 점수 모두 사용자에게 보고 |
| 인덱스 무결성 기계 게이트가 조치 후에도 미해소 | 추가 재시도 없음. Phase 3 보고에 "인덱스 무결성 잔존 이슈"로 남은 FAIL/WARN 그대로 명시 |
| targeted 재실행이 근거를 못 찾아 "미해소"로 반환 | 없는 엣지를 만들지 않은 정상 동작이다. 게이트를 강제로 통과시키지 말고 그대로 잔존 이슈로 보고 |
| AI 예산 claim 실패(exit 1) | 해당 Agent 호출을 하지 않고 레인 중단(2-1/2-2/2-3) 또는 그 fix_target만 건너뜀(Phase 4) — 다른 예외처럼 WARN 후 계속하지 않는다, 하드 스톱이 의도 |
| `validate-harness.mjs` 실행 자체 실패(node 없음/python 미설치급 환경 문제) | WARN 후 계속 진행 — 스키마 검증 없이 validator_checks.py/validator Agent만으로 진행(기존 방식) |
| `validator_schema.json`의 `plugin_contract_failures > 0` | AI 재시도하지 않음. Phase 3 보고에 "플러그인 인덱스 계약 결함"으로 명시 |

상충 데이터: writer가 두 패턴 발견 시 출처 병기, validator/qa가 우선순위 권고 (자동 결정 X).

---

## 팀 통신 프로토콜

이 하네스는 `TeamCreate`/`SendMessage` 도구 없음. 대신:

| 채널 | 도구 | 용도 |
|------|------|------|
| 작업 조율 | `TaskCreate`/`TaskUpdate` | 진행 추적, 의존성 |
| 산출물 전달 | `_workspace/` 파일 | 분석 리포트·생성 파일·검증·인덱스 |

각 에이전트는 자기 `.md`에 명시된 입력 파일을 읽고 출력 파일을 작성. 오케스트레이터는 의존성 순서로 호출하고 산출물 존재 확인.
