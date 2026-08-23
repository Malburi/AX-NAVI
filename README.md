# Total ITO

> **ITO/SI 조직을 위한 Claude Code 확장 하네스**
>
> 처음 투입된 프로젝트에서 _"이 코드 뭐야?"_ 부터 _"이 변경 안전해?"_ 까지,
> Claude가 프로젝트를 이해하고 작업을 함께 수행할 수 있도록 돕는 에이전트 팀 + 워크플로우 도구 모음입니다.

---

## 🧬 설계 철학

검증된 오픈소스 방법론 3종을 SM 현장에 맞게 접목했습니다.

```
분석 전              분석 중              분석 후
─────────────────    ─────────────────    ─────────────────
목적이 명확한가?  →  파이프라인 실행   →  결과가 맞는가?
(Ouroboros)          (Superpowers)         (Karpathy)
```

| 출처 | 핵심 아이디어 | Total ITO 적용 |
|------|-------------|----------------|
| [Q00/ouroboros](https://github.com/Q00/ouroboros) | 코드 생성 전 모호성을 수치화해 80% 명확해질 때까지 질문 | **`spec-gate` 스킬** — 대형 작업 전 별도 호출로 목적·범위·제약 확인 (harness-init과는 독립) |
| [Andrej Karpathy](https://karpathy.bearblog.dev) | 출력을 스스로 평가 → 실패 원인 분석 → 재생성 (AutoResearch) | **Phase 4 Eval Loop** — 4차원 품질 채점 → 80점 미만 시 타겟 재생성 |
| [obra/superpowers](https://github.com/obra/superpowers) | 에이전트마다 프롬프트를 주지 말고 파이프라인에 방법론을 심어라 | **단계별 검증 파이프라인** — analyzer → writer → validator → eval (qa·wiki는 온디맨드) |

---

## 🤔 이게 왜 필요한가요?

Claude Code를 아무 설정 없이 사용하면 매번 _"이 프로젝트가 뭔지"_ 처음부터 설명해야 합니다.
Total ITO는 프로젝트를 **한 번 분석해 Claude가 기억할 수 있는 형태로 저장**합니다.

그 결과, 이후 작업에서 Claude는 다음을 알고 시작합니다:

- 🏗️ 이 프로젝트의 아키텍처와 레이어 구조
- 🔌 어떤 DB·외부 시스템과 연결되어 있는지
- 📐 코드 작성 컨벤션 (네이밍, 계층 패턴, 예외 처리 방식)
- 🕸️ 어떤 함수가 어떤 함수를 호출하는지 (호출 그래프)
- 🔒 트랜잭션 경계, 인증/인가 경로

### 범용 ITO 지원 원칙

Java/Spring, JavaScript/TypeScript(Vue·React), Python, Go, C#/.NET의 결정적 소스 분석을 공통 워크플로우에서 사용합니다. ASP.NET Core route·생성자 DI, WinForms event, Nexacro Form·Dataset·transaction은 전용 어댑터로 보강됩니다.

다만 “파일을 발견했다”를 “안전하게 자동 수정할 수 있다”로 과장하지 않습니다. 인덱서는 확장자와 파일별로 `FULL/PARTIAL/UNSUPPORTED`를 기록하며, WinForms Designer·DevExpress·XFDL·JSP/Struts XML 같은 PARTIAL 대상은 실제 빌드·UI·통합 검증 전까지 자동 변경 판정이 `HOLD`입니다. 생성된 wiki의 **유지보수 지원 현황**에서 프로젝트별 상태를 확인할 수 있습니다.

이 정보를 바탕으로 영향도 분석, 안전 변경, 신규 기능 생성, 마이그레이션 계획 같은 작업을 **자연어로** 요청할 수 있게 됩니다.

---

## 📦 설치 방법

최신 Claude Code에서 아래 두 명령을 실행하면 GitHub 저장소를 마켓플레이스로 등록하고 플러그인을 사용자 범위에 설치할 수 있습니다.

### 1단계 — 마켓플레이스 등록 (최초 1회)

Claude Code 어느 프로젝트에서나 실행:

```
/plugin marketplace add neoruler001/total_ito
```

### 2단계 — 플러그인 설치

```
/plugin install total-ito@total-ito
```

설치 확인:

```
/plugin list
```

`total-ito@total-ito — enabled`가 보이면 됩니다. ✅

### 3단계 — 구성 요소 로딩 확인

설치 결과가 재로딩을 요구할 때만 아래 명령을 실행합니다.

```
/reload-plugins
```

플러그인 상세 화면에서 17개 스킬과 18개 에이전트를 확인할 수 있습니다.

```
/plugin details total-ito@total-ito
```

첫 실행은 이름이 겹치지 않도록 네임스페이스를 포함해 호출할 수 있습니다.

```
/total-ito:harness-init
```

터미널에서 비대화형으로 설치하려면 다음 명령도 사용할 수 있습니다.

```bash
claude plugin marketplace add neoruler001/total_ito
claude plugin install total-ito@total-ito --scope user
claude plugin details total-ito@total-ito
```

> 💡 **설치가 안 될 때** — 저장소 루트에서 `claude plugin validate . --strict`를 실행하고 Claude Code를 최신 버전으로 갱신하세요.

---

## 🚀 처음 시작하기 (하네스 초기화)

분석하고 싶은 **프로젝트 루트**에서 Claude Code를 열고 아래 중 하나를 입력하세요:

```
"하네스 초기화해줘"
"이 프로젝트 Claude 설정해줘"
"harness init"
```

`harness-init` 스킬이 자동으로 실행되어 아래 순서로 진행됩니다:

```mermaid
flowchart LR
    S([-1️⃣ 프로젝트 구성 확인\n단일/모노레포/분리저장소1대1/부분범위/허브형1대N]) --> A
    A([⚖️ Tier 확인\n기본 Full, 다운그레이드 1회 확인]) --> C([🔬 코드베이스 분석])
    C --> D([✍️ 하네스 파일 생성])
    D --> P([📐 패턴 추출·근거 검증])
    P --> E([✅ 구조 검증])
    E --> G([🎯 품질 평가\n4차원 Eval])
    G -->|PASS 80+| F([📋 결과 보고])
    G -->|PARTIAL/RETRY| H([🔁 타겟 재생성])
    H --> F
```

시작 전에 질문 두 개가 나올 수 있습니다 — ① 프로젝트 구성(단일/모노레포/분리저장소 1:1/부분범위/허브형 1:N — 백엔드 1개+클라이언트 2개 이상, 예: 웹+모바일+관리자), ② Tier 확인(기본 Full 유지할지). 요청문에 구성·경로를 이미 적었으면 ①은 생략되고, `"빠르게"`(Standard)·`"심층"`(Full) 같은 키워드를 붙이면 ②도 질문 없이 바로 확정됩니다.

완료되면 프로젝트 루트에 `CLAUDE.md`와 `.claude/` 폴더가 생깁니다.
이 파일들을 git에 커밋해 팀원과 공유하세요.

```bash
git add CLAUDE.md .claude/
git commit -m "docs: add project harness"
```

> ⏱️ **소요 시간:** Standard 3~5분 · Full 10분 내외

---

## ⚡ 분석 깊이 (2-Tier)

harness-init의 기본 Tier는 **Full**입니다 — 레거시 유지보수는 얕은 분석이 놓치는 위험(미해결 관계·인증 우회·트랜잭션 경계)이 재작업 비용보다 크다는 전제입니다.

```mermaid
flowchart TD
    Start([프로젝트 분석 시작]) --> KW{요청에\n키워드 있음?}

    KW -->|"빠르게 / 간단히"| Standard
    KW -->|"심층 / 마이그레이션 / 레거시"| Full
    KW -->|없음| Ask{"Full 유지 vs\nStandard로 낮출까요?\n(1회 확인, 기본값: Full)"}

    Ask -->|"Standard 확인"| Standard
    Ask -->|무응답/그 외| Full

    Standard["🟡 Standard\n스택·구조 + 의존성 그래프\n트랜잭션·외부통신\n+ 패턴 추출"]
    Full["🔴 Full\nStandard + 데드코드\n환경분기·인증경로"]
```

경계면 QA와 wiki 생성은 Tier와 무관하게 항상 온디맨드입니다 — 초기화 완료 후 선택 작업 메뉴에서 고를 때만 실행됩니다(토큰 절감).

| Tier | 선택 방법 | 적합한 프로젝트 | 소요 시간 |
|------|---------|--------------|---------|
| 🟡 **Standard** | `"빠르게"`/`"간단히"` 키워드 또는 다운그레이드 확인 질문에서 선택 | 일반적인 웹 서비스, 소규모 모듈 | 3~5분 |
| 🔴 **Full** (기본값) | 아무것도 안 하거나 `"심층"`/`"마이그레이션"` 키워드 | 대형 레거시, 마이그레이션 대상 | ~10분 |

---

## 💬 하네스 초기화 이후 — 일상 작업에서 쓰는 법

하네스가 설치된 프로젝트에서는 자연어로 아래 작업을 요청할 수 있습니다.

### 🔍 코드 이해

```
"주문 취소 로직 어떻게 돼?"
```
→ `trace-logic` → 진입점 · Controller · Service · Repository · DB 쿼리까지 전체 흐름 리포트

```
"결제 관련 코드 어디 있어?"
```
→ `find-feature` → 관련 파일 · 클래스 · 메서드 · SQL ID 목록

```
"이 PL/SQL 뭐하는 코드야?"
```
→ `legacy-decoder` → 비즈니스 의도 역공학 리포트

---

### 🛡️ 변경 전 확인

```
"OrderService.cancel 수정하면 어디 영향가?"
```
→ `analyze-impact` → 직접 호출자, 트랜잭션 경계, 관련 테스트, 화면 영향 정리

```
"이 변경 안전하게 적용해줘"
```
→ `safe-modify` → 영향 분석 → 실제 기준 패턴 선택 → 적용 → 패턴 적합성·테스트/빌드 검증 → 안전성 판정

```mermaid
flowchart LR
    M[변경 요청] --> I[영향도 분석]
    I --> A[변경 적용]
    A --> S{안전성 평가}
    S -->|문제 없음| GO["✅ GO\n진행 가능"]
    S -->|주의 필요| HOLD["⚠️ HOLD\n확인 후 결정"]
    S -->|위험| STOP["🛑 STOP\n대안 논의"]
```

> HOLD / STOP 이 나오면 Claude가 이유와 권고 조치를 함께 알려줍니다. **자동 수정은 하지 않습니다.**

---

### 🏗️ 신규 기능 개발

```
"환불 기능을 프로젝트 컨벤션에 맞게 만들어줘"
```
→ `scaffold-feature` → 기존 패턴 분석 → Controller · Service · Repository · DTO · 테스트 골격 일괄 생성

---

### 🗄️ SQL 리뷰

```
"이 쿼리 문제없어? SELECT * FROM orders WHERE ..."
```
→ `review-sql` → 사용처 · 인덱스 활용 · N+1 위험 · SQL 인젝션 · DDL 영향 종합 리포트

---

### 🚚 마이그레이션

```
"Spring Boot 3으로 마이그레이션 계획 짜줘"
"Oracle에서 PostgreSQL로 전환 계획 짜줘"
```
→ `plan-migration` → 인벤토리 → 매핑 테이블 → 단계별 계획 → 리스크 레지스터 → 롤백 플랜

---

### 📝 문서 동기화

```
"코드 바꿨는데 문서 동기화해줘"
```
→ `doc-syncer` → CLAUDE.md · README · API 문서 업데이트 권고 목록

---

## 🏭 운영 환경 키워드

변경 작업 요청 시 상황을 알려주면 Claude가 안전성 판단 기준을 맞춰줍니다:

| 상황 | 키워드 예시 |
|------|-----------|
| 🏢 운영 서버 반영 | "운영 패치야", "프로덕션 배포 전이야" |
| 🚨 긴급 수정 | "긴급 핫픽스야" — 변경 범위를 작게 제한 |
| 🏚️ 레거시 코드 | "레거시 손보는 거야" — 컨벤션 기준 완화 |
| 🎯 고객 데모 직전 | "고객 데모 직전이야" — 외부 영향 가중치 높임 |
| 🌙 야간 배치 | "야간 배치 관련이야" |

---

## 📁 하네스가 만드는 파일들

초기화 후 프로젝트에 생기는 파일 구조입니다:

```
프로젝트/
├── CLAUDE.md                          ← 🧠 이 프로젝트의 핵심 가이드 (git 커밋 권장)
└── .claude/
    ├── ito-guide.md                   ← 📖 하네스 사용 설명서 (초기화 시 자동 생성)
    ├── skills/                        ← ⚙️ 프로젝트 전용 스킬 (git 커밋 권장)
    │   ├── trace.md
    │   ├── scaffolder.md
    │   └── find-logic.md
    ├── agents/
    │   └── domain-expert.md           ← 🎓 이 프로젝트의 도메인 지식
    └── patterns/                      ← 📐 코드 컨벤션 패턴
        ├── controller_pattern.md
        ├── service_pattern.md
        ├── dao_pattern.md
        ├── client_pattern.md          ← Legacy Static JS 탐지 시에만 생성
        └── ...
```

> `analyze-impact`/`safe-modify`/`scaffold-feature`/`vibe`/`plan-migration`/`review-sql`은 프로젝트별로
> 내용이 달라지지 않는 스킬이라 로컬 파일을 만들지 않는다 — 플러그인이 설치된 이상 바로 사용 가능하며,
> CLAUDE.md의 자동 워크플로우 표에 이름이 등록된다.

```
_workspace/                            ← 🔧 분석 산출물 (.gitignore 권장)
├── 00_init_scope.md                   ← 구성 확인 리포트 (Phase -1)
├── 01_analyzer_report.md              ← 분석 리포트
├── 06_eval_report.md                  ← 품질 Eval 결과 (Phase 4)
├── index/                             ← ⚡ JSON 인덱스 (후속 작업 고속화)
│   ├── call_graph.json                ← 함수 호출 그래프
│   ├── symbols.json                   ← 클래스·메서드 위치 인덱스
│   ├── sql_usage.json                 ← SQL ID ↔ 호출 위치
│   ├── transactions.json              ← 트랜잭션 경계
│   ├── external_io.json               ← 외부 시스템 연결
│   ├── client_index.json              ← JS↔JSP 매핑 (Legacy Static JS 탐지 시)
│   └── ...
├── reports/                            ← 📋 온디맨드 작업 리포트(스킬별 1회성 산출물)
│   ├── impact_<slug>.md               ← 영향도 분석 결과
│   ├── safety_<slug>.md               ← 안전성 평가 결과
│   └── ...                            ← trace_/found_/sql_review_/docs_sync_/api_drift_report 등
└── wiki/                               ← 🌐 generate-wiki 산출물 (2026-08-14부터 프로젝트 루트 대신 여기)
```

> 💡 `CLAUDE.md`와 `.claude/`는 팀원과 공유하기 위해 git에 커밋하세요.
> `_workspace/`는 런타임 산출물이므로 `.gitignore`에 추가를 권장합니다.

---

## 🌐 지원 스택

ITO/SI 현장에서 자주 만나는 레거시를 포함해 자동으로 탐지합니다.

| 카테고리 | 지원 스택 |
|---------|----------|
| ☕ Java EE 레거시 | Struts 1.x/2.x, Spring 3~4, iBatis, EJB 2, JSP/JSTL |
| 🍃 Spring | Spring Boot 2/3, Spring MVC, MyBatis, Spring Data JPA, Spring Security |
| 🏛️ 전자정부 | egovframework |
| 🟩 Node.js | Express, NestJS, Next.js, Fastify, Koa |
| 🖥️ 프런트엔드 | Vue 2/3, Nuxt 2/3, Pinia/Vuex, React, Angular 15+, AngularJS 1.x, Svelte |
| 📜 Legacy Static JS | jQuery 1.x~3.x, 빌드 도구 없는 JSP+JS 혼합 (JS↔JSP 매핑, onInit/onSaveData 규약, eval AJAX 자동 추출) |
| 🐍 Python | FastAPI, Django, Flask |
| 🔷 .NET | .NET Framework 2~4, .NET Core, .NET 5~8, ASP.NET Core |
| 🗄️ DB | Oracle, PostgreSQL, MySQL/MariaDB, Tibero, Altibase, SQL Server |
| 🔄 마이그레이션 경로 | Struts→Spring, iBatis→MyBatis/JPA, Vue 2→3, Vuex→Pinia, Oracle→PostgreSQL 등 |

---

## ❓ 자주 묻는 질문

**Q. 초기화할 때 질문이 너무 많아요. 바로 시작하고 싶어요.**

"빠르게 하네스 초기화해줘" 처럼 **"빠르게"** 를 붙이거나 "skip spec"을 포함하면 질문 없이 바로 분석으로 넘어갑니다.

**Q. 품질 점수(Eval)가 낮으면 어떻게 되나요?**

80점 미만이면 낮은 차원(커버리지·정확도·실행가능성·컨텍스트 품질)만 골라 자동으로 재생성합니다. 전체 재실행이 아닌 **타겟 재생성**이라 시간이 크게 늘지 않습니다. 재생성 후 점수가 오히려 낮아지면 초기 결과를 유지합니다.

**Q. harness를 완전히 제거하고 싶어요.**

```
"하네스 삭제해줘"
"harness clean"
```

→ `harness-clean` 스킬이 삭제 대상 목록을 먼저 보여주고 확인을 받습니다. 자동 삭제 없음.  
플러그인 자체를 제거하려면 확인 후 안내해 드립니다:

```
/plugin uninstall total-ito@total-ito
```

**Q. 하네스를 한 번 만들면 코드가 바뀌었을 때는?**

인덱스를 증분 갱신할 수 있습니다:
```
"인덱스 갱신해줘"
```
큰 변경이 있었다면 `"하네스 다시 초기화해줘"` 로 전체 재실행도 가능합니다.

**Q. 초기화 후 어떻게 쓰는지 모르겠어요.**

초기화가 끝나면 `.claude/ito-guide.md` 파일이 자동으로 생성됩니다.
이 파일에는 이 프로젝트에 맞는 스킬 트리거 예시, 실전 시나리오, 주의사항이 담겨 있습니다.

```
"ito-guide 보여줘"
```

**Q. 특정 부분만 다시 만들고 싶어요.**

```
"스킬만 다시 생성해줘"
"패턴만 다시 추출해줘"
"validator만 다시 실행해줘"
```

**Q. _workspace/ 폴더가 너무 커요.**

분석이 끝난 후 `_workspace/`는 지워도 됩니다. 단, `_workspace/index/`는 영향도 분석·안전 변경 등에서 참조하므로 남겨두는 편이 좋습니다.

**Q. ✅ GO / ⚠️ HOLD / 🛑 STOP 이 나왔는데 어떻게 해야 하나요?**

- ✅ **GO** — 진행해도 안전합니다.
- ⚠️ **HOLD** — 주의가 필요한 부분이 있습니다. Claude가 상세 내용을 알려줍니다. 확인 후 결정하세요.
- 🛑 **STOP** — 현재 방식으로는 진행하지 않는 것을 권고합니다. 대안을 논의하세요.

Claude는 HOLD/STOP 상황에서도 자동 수정을 하지 않습니다. **판단은 항상 사람이 합니다.**

---

## 📚 에이전트 & 스킬 전체 목록

<details>
<summary>펼쳐보기</summary>

### ⚙️ 워크플로우 스킬 (17종)

| 스킬 | 트리거 예시 | 역할 |
|------|-----------|------|
| `spec-gate` | "작업 전 범위 정해줘" | 소크라테스식 명세 명확화 (단독 실행 가능) |
| `harness-init` | "하네스 초기화해줘" | 명세 확인 → 분석 → 생성 → 검증 → eval 오케스트레이터 |
| `harness-clean` | "하네스 삭제해줘" | 생성된 harness 파일 전체 안전 제거 |
| `analyze-impact` | "영향도 분석해줘" | 변경 영향 범위 분석 |
| `safe-modify` | "안전하게 적용해줘" | 영향 분석 + 적용 + 안전성 판정 |
| `scaffold-feature` | "컨벤션 따라 만들어줘" | 전 레이어 신규 기능 생성 |
| `plan-migration` | "마이그레이션 계획 짜줘" | 스택 전환 계획 수립 |
| `review-sql` | "SQL 점검해줘" | SQL 종합 리뷰 |
| `trace-logic` | "로직 어떻게 돼?" | 처리 흐름 추적 |
| `find-feature` | "어디 있어?" | 기능·키워드로 코드 위치 탐색 |
| `vibe` | "알아서 해줘" | 사소한 작업은 빠르게 처리하고 위험 변경은 안전 워크플로우로 승격 |
| `generate-wiki` | "위키 만들어줘" | 도메인·아키텍처·패턴·API·DB wiki 생성 |
| `publish-wiki` | "위키 발행해줘" | 생성된 wiki를 중앙 wiki-hub DB에 발행 |
| `wiki-hub` | "위키 허브 실행해줘" | 여러 시스템 wiki 통합 열람·검색 |
| `pair-init` | "백엔드 프론트 연결해줘" | 분리 저장소 API 계약 연결 |
| `cross-repo-scaffold` | "전체 스택 기능 만들어줘" | 백엔드와 선택한 클라이언트에 신규 기능 동시 생성 |
| `cross-repo-modify` | "양쪽 다 수정해줘" | API 영향이 있는 기존 기능을 관련 저장소에 안전 반영 |

### 🤖 에이전트 (18종)

| 에이전트 | 역할 | 모델 |
|---------|------|------|
| `spec-clarifier` | 소크라테스 인터뷰 + 모호성 점수 + 명세 리포트 (spec-gate 스킬 전용) | sonnet |
| `analyzer` | 코드베이스 분석 + 인덱스 생성 | opus (Full) / sonnet (Standard) |
| `writer` | 하네스 파일 생성 | sonnet (모든 Tier) |
| `pattern-extractor` | 코드 컨벤션 패턴 추출 (Legacy Static JS 포함) | sonnet |
| `pattern-conformance` | 변경 코드와 선택된 실제 기준 파일의 패턴 적합성 판정 | sonnet |
| `validator` | 하네스 구조 검증 | sonnet |
| `qa` | 경계면 교차 비교 (온디맨드, Phase 3.6 메뉴 선택 시) | sonnet |
| `harness-evaluator` | 4차원 품질 평가 + 타겟 재생성 지시 (Phase 4) | sonnet |
| `impact-analyzer` | 변경 영향도 분석 | opus |
| `change-safety` | 안전성 평가 (GO/HOLD/STOP) | sonnet |
| `migration-planner` | 마이그레이션 계획 수립 | opus |
| `test-generator` | 회귀 테스트 골격 생성 | sonnet |
| `sql-reviewer` | SQL 다각도 리뷰 | sonnet |
| `legacy-decoder` | 레거시 코드 역공학 | opus |
| `doc-syncer` | 코드 ↔ 문서 동기화 점검 | sonnet |
| `logic-tracer` | 처리 흐름 추적 | sonnet |
| `feature-finder` | 기능·키워드 코드 위치 탐색 | sonnet |
| `api-bridge` | 저장소 간 API 계약 추출·검증·스텁 생성·영향 확인 | sonnet |

</details>

---

## 🖥️ 발표·보고 자료

설치부터 분석·활용·중앙 위키 발행까지 전 과정을 한 파일로 정리한 슬라이드가 있습니다.
브라우저로 열면 바로 발표할 수 있고(← →로 넘김, `O` 목차, `F` 전체화면), `P`로 인쇄하면
그대로 PDF가 됩니다. 외부 CDN·폰트를 쓰지 않아 폐쇄망에서도 열립니다.

```
total-ito-guide.html      ← 세미나·보고용 슬라이드 20장 (PPT 대체)
skill-triggers.html       ← 스킬 트리거 체계 상세
```

---

## 🔗 참고

- [neoruler001/harness-new](https://github.com/neoruler001/harness-new) — 기반 4-에이전트 파이프라인
- [Malburi/harness-ito](https://github.com/Malburi/harness-ito) — 메타 하네스 설계 원칙
- [Claude Code 공식 문서](https://docs.anthropic.com/en/docs/claude-code/overview)
- [`docs/user-guide.md`](docs/user-guide.md) — 사용자 설명서 (스킬별 사용법 + SM 실무 시나리오)
- [`docs/workflows.md`](docs/workflows.md) — 스킬별 상세 시나리오
- [`docs/stack-matrix.md`](docs/stack-matrix.md) — 지원 스택 상세 매트릭스
- [`docs/pattern-profile.md`](docs/pattern-profile.md) — 구조화 패턴 프로필·선택·적합성 게이트
- [`docs/role-map.md`](docs/role-map.md) — 17개 스킬·18개 에이전트의 책임과 중복 방지 경계
- [`docs/harness-description.md`](docs/harness-description.md) — 규모별 비교 분석 (정확도 & 토큰 소비)
- [`sql/README.md`](sql/README.md) — 중앙 DB 스키마·담당자/권한 설계와 엔진별 DDL 스크립트
