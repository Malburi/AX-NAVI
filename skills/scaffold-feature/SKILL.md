---
name: scaffold-feature
description: 추출된 프로젝트 컨벤션에 따라 신규 기능을 스캐폴딩한다(Controller/Service/DAO/DTO/테스트까지). "[기능명] 기능 추가", "주문 취소 기능 만들어줘", "신규 모듈 생성 컨벤션", "scaffold feature", "패턴대로 만들어줘", "프로젝트 스타일로 새 기능", "보일러플레이트 생성", "새 API 만들어줘 컨벤션 따라" 요청 시 트리거. 범용 개발 요청("개발해줘", "구현해줘", "코드 짜줘", "새 기능 만들어줘")도 기본적으로 이 스킬을 탄다 — 게이트 없이 바로 하려면 vibe 스킬("알아서 해줘"). 축약 호출: "스캐폴드 [기능명]".
---

# Scaffold Feature (오케스트레이터)

`.claude/patterns/`에 추출된 컨벤션을 따라 *전체 레이어*의 신규 파일을 생성한다.

기본 `scaffolder` 스킬과 차이: `scaffolder`는 *체크리스트만* 제공, `scaffold-feature`는 *실제 파일 생성*까지 수행하며 *컨벤션 100% 준수*.

---

## Phase 0: 사전 조건 확인

### 어댑터 커버리지 게이트

생성 예정 경로의 확장자마다 `agents/lib/check-adapter-coverage.mjs`를 실행한다. 기존 파일이 아직 없더라도 같은 확장자의 `_meta.json.adapter_coverage` 항목으로 판정한다.

- `FULL`만 자동 생성 가능.
- `PARTIAL`(예: XFDL 혼합 XML/Script, 프로젝트 메타데이터)은 실제 유사 화면/Designer/설정 파일과 실행 검증 절차를 사용자가 확인할 때까지 HOLD.
- `UNSUPPORTED`는 추측 스캐폴딩 금지. 먼저 어댑터와 회귀 픽스처를 추가한다.

### pair_config 확인 (Type B 지원)

`_workspace/pair_config.md` 존재 확인:
- **있고** `partner_root` 경로가 유효하면 → `pair_linked = true`
  - Phase 1에서 "프론트엔드도 함께 생성할까요?" 질문 추가
- **없으면** → `pair_linked = false` (단일 레포 스캐폴딩 진행)

### 패턴 로드

`.claude/patterns/*.md` 확인:
- 스켈레톤 상태 (pattern-extractor 미실행) → "패턴 추출 먼저 필요" 안내 후 pattern-extractor 호출
- 본문 채워짐 → 계속 진행

`.claude/patterns/pattern_profile.json`을 기계 검증한다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/pattern_profile.py" validate --root "[프로젝트 루트 절대 경로]"
```

- 검증 PASS → 모듈·레이어별 기준 코드 선택 가능.
- 파일 없음·검증 FAIL → pattern-extractor를 먼저 실행하고 다시 검증. 재실패하면 추측 생성 금지 후 중단.

### 분석 리포트 로드

`_workspace/01_analyzer_report.md`에서:
- 아키텍처 레이어 목록
- 빌드/실행 명령
- 모듈 분류 방식 (기능별/레이어별/혼합)

---

## Phase 1: 기능 명세 수집

사용자에게 다음 확인 (1~2회):

| 질문 | 예시 답 |
|------|--------|
| 기능명 | "주문 취소" |
| 영향 레이어 | "Controller, Service, DAO, DTO, 테스트" (기본 전체) |
| 기존 유사 모듈 | "OrderRefund 비슷하게" (있으면 참조) |
| API 엔드포인트 | "POST /api/orders/{id}/cancel" |
| DB 테이블 영향 | "TBL_ORDER.STATUS 업데이트" |
| (pair_linked=true) 프론트엔드도 함께? | Y → cross-repo-scaffold로 위임 / N → 백엔드만 진행 |

추가 정보:
- 기존 유사 모듈을 명시하면 → 그 모듈 코드를 더 적극 참조
- DB 영향이 있으면 → review-sql 사전 호출 권고
- pair_linked=true에서 "Y (프론트도 함께)" → 즉시 `cross-repo-scaffold`로 위임하고 scaffold-feature 종료
  (cross-repo-scaffold가 백엔드+프론트엔드 양쪽 모두 처리)

### 유사 기능과 기준 패턴 선정

사용자가 기존 유사 모듈을 지정하지 않았으면 `feature-finder`와 인덱스를 이용해 **같은 모듈·같은 레이어·같은 작업 유형**의 후보를 찾는다. 이름만 비슷한 다른 세대 코드는 기준으로 고르지 않는다.

생성 예정 경로와 모듈이 정해지면 다음을 실행한다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/pattern_profile.py" select --root "[프로젝트 루트 절대 경로]" --target "[생성 예정 상위 경로]" --module "[모듈명]" --limit 20
```

출력 `_workspace/reports/pattern_selection.json`에서 영향 레이어별 `preferred` 프로필과 실제 `reference_files`를 선택한다.

- 동일 모듈·레이어 프로필 우선.
- `legacy`와 `anti_pattern`은 신규 코드 기준으로 선택 금지.
- 후보 간 규칙 충돌·LOW 신뢰도·근거 파일 부재 → 사용자에게 선택받기 전 생성 중단.
- 생성 전에 선택한 기준 파일을 실제로 읽는다. Markdown 패턴만 읽고 일반적인 프레임워크 예제를 작성하지 않는다.

---

## Phase 2: 사전 영향 체크 (선택)

기능명·테이블 영향이 있으면 → `analyze-impact`로 *충돌 가능성* 사전 점검:
- 같은 엔드포인트가 이미 있는지
- 같은 SQL ID가 이미 있는지
- 같은 클래스/메서드명 충돌

충돌 발견 시 → 사용자에게 알리고 명명 조정 권고.

---

## Phase 3: 파일 생성

각 레이어별로 컨벤션 적용한다. 웹 Controller/Service/DAO 구조를 모든 시스템에 강제하지 않고, 분석된 `workspace.kind`와 선택 프로필에 따라 다음 중 해당 구조만 사용한다.

- 서버/API: Controller·Action·Router / Service / Repository·Mapper / DTO / Test
- WinForms·DevExpress: Form·UserControl / Designer partial / UI event / application service / Test
- Nexacro: XFDL Form / XJS 공통 모듈 / Dataset / transaction·callback / 서버 Action·Controller / Test 또는 수동 시나리오
- Vue·React: Component / composable·hook / store / API client / route / Test

### 3-1. Controller / Action / Router 레이어

선택된 Controller 프로필의 `rules`·`reference_files`와 `.claude/patterns/controller_pattern.md`(또는 `action_pattern.md`)를 함께 로드한다:
- 클래스 명명 패턴
- 매핑 어노테이션 패턴
- 매개변수 처리
- 응답 형식
- 예외 처리

생성 위치와 코드 골격은 일반 Spring 예제가 아니라 선택된 실제 기준 파일의 구조를 따른다.

### 3-2. Service 레이어

`.claude/patterns/service_pattern.md` 본문 기반.

### 3-3. DAO / Repository / Mapper 레이어

`.claude/patterns/dao_pattern.md` 본문 기반.  
SQL ID는 분석 리포트의 명명 규칙 (`MODULE_FEATURE_S01` 등) 따름.

### 3-4. DTO / Entity 레이어

`.claude/patterns/dto_pattern.md` (있으면) 또는 entity 패턴 기반.

### 3-5. Test 레이어

`test-generator` 에이전트 호출. 네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 해당 `agents/<이름>.md`의 지침을 읽고 그대로 따르라고 명시한다.

```
Agent(
  subagent_type="ax-navi:test-generator",
  description="신규 기능 테스트 생성",
  prompt="<대상: [생성된 파일 목록]. 컨벤션: .claude/patterns/test_pattern.md.>",
  model="sonnet"
)
```

테스트는 *작성 대상 코드의 골격*만 생성하고 *비즈니스 검증은 TODO*로 남긴다 (test-generator 원칙).

### 3-6. 설정 / 라우팅 등록

스택별로 필요한 설정 파일에 등록 항목 추가:
- Struts: `struts-*.xml`에 `<action>` 추가
- Spring XML: `applicationContext-*.xml`에 Bean 등록
- web.xml의 servlet/filter 패턴 (필요 시)
- frontend route 등록 (Next.js, Vue Router 등)

---

## Phase 4: 패턴 적합성·실행 증거·안전성 평가

### 4-1. 패턴 적합성 독립 검증

`pattern-conformance`를 호출해 생성 코드와 선택된 실제 기준 파일을 교차 검증한다.

```
Agent(
  subagent_type="ax-navi:pattern-conformance",
  description="신규 기능 패턴 적합성 검증",
  prompt="<변경 파일: [생성·수정 파일 목록]. 선택 결과: _workspace/reports/pattern_selection.json. 출력: _workspace/reports/pattern_conformance_<slug>.md>",
  model="sonnet"
)
```

- CONFORM → 다음 단계.
- HOLD → 충돌·의도적 차이를 사용자 확인 후 필요한 수정과 재검증.
- FAIL → 생성 코드 수정 후 재검증. FAIL 상태에서는 GO 보고 금지.

### 4-2. 프로젝트 검증 명령 실행

`verify-target.mjs detect`로 프로젝트 검증 명령을 확보한 뒤(분석 리포트의 빌드·실행 명령과 교차 확인), 생성 범위에 필요한 항목을 `run`으로 실제 실행하고 `cmd`·`exit`·`fail_lines`를 기록한다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/verify-target.mjs" detect --root "[프로젝트 루트]" --target "[생성 대상 경로]"
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/verify-target.mjs" run --root "[프로젝트 루트]" --cmd "[고른 명령]"
```

테스트 골격만 생성되고 assertion이 비어 있으면 통과 증거가 아니므로 HOLD로 표시한다. 감지 `count: 0`이면 자동 검증이 없다는 뜻이므로 수동 검증을 확보하기 전 GO로 보고하지 않는다.

### 4-3. 변경 안전성 평가

`change-safety` 호출 (자동) — 생성 파일, 패턴 적합성 리포트, 실제 검증 명령 결과를 함께 전달해 보안·회귀 위험을 점검한다.

결과:
- GO → 패턴 CONFORM + 필수 검증 명령 exit 0 + change-safety GO가 모두 충족된 경우만 진행
- HOLD → 보완 필요 항목 표시
- STOP → 거의 발생 안 함 (보안 위험 자동 도입 시만)

### 4-4. 인덱스와 위키 갱신

GO일 때 변경된 프로젝트에서 인덱스를 incremental 모드로 갱신하고 `generate-wiki`를 재실행한다. 인덱스 또는 위키 갱신이 실패하면 코드 생성 성공과 구분해 WARN으로 보고하며 실패 사유와 stale 상태를 남긴다.

---

## Phase 5: 결과 보고

```
신규 기능 스캐폴딩 완료: [기능명]

생성된 파일:
- [Controller] [경로]
- [Service] [경로]
- [DAO/Mapper] [경로]
- [DTO/Entity] [경로]
- [Test] [경로]
- (설정 변경) [파일]: [추가 항목]

패턴 적합성: [CONFORM/HOLD/FAIL] (기준 프로필·파일 표시)
검증 증거: [실행 명령과 exit code]
인덱스·위키: [갱신 완료/WARN]

⚠️ TODO 항목 (수동 완성 필요):
- [위치]: [완성할 부분]

영향도 사전 체크: [충돌 없음 / 충돌 발견 — 보완]

다음 단계:
- 비즈니스 로직 구현 (TODO 채우기)
- 테스트 assertion 보완
- 빌드/실행: [명령어]
- 통과 후 commit
```

---

## 원칙

### 근거 있는 컨벤션 준수

선택된 모듈·레이어의 `preferred` 프로필과 실제 기준 파일을 따른다. 서로 다른 모듈의 다수 패턴을 평균내지 않는다. 패턴이 모호하거나 충돌하면 *생성 중단* 후 사용자에게 결정 요청.

### TODO 정직 표기

자동 생성된 *비즈니스 로직*은 비어 있다. TODO로 명시. 가짜 구현(예: 무조건 success 반환)으로 채우지 않는다.

### 충돌 자동 회피

기존 파일/메서드/SQL ID와 충돌하면 *덮어쓰지 않고* 사용자에게 조정 요청.

### 패턴 부재 시 거부

`.claude/patterns/`가 비어 있거나 스켈레톤이면 → pattern-extractor 먼저 실행 권고. 컨벤션 없이 스캐폴딩하면 *추측에 기반한 잘못된 표준*을 도입할 위험.
