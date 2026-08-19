---
name: spec-gate
description: 작업 시작 전 소크라테스식 인터뷰로 목적·범위·제약을 명확화한다. "명세 명확화", "요구사항 정리해줘", "spec gate", "작업 범위 정해줘", "어디서부터 시작해야 해", "ambiguity check", "뭐부터 해야 해", "범위 정의해줘", "작업 목표 정리해줘", "시작 전 정리", "scope clarify" 요청 시 사용. harness-init은 자동 호출하지 않는다 — harness-init 실행 전 목적·범위를 먼저 정리하고 싶으면 이 스킬을 독립적으로 먼저 호출한다.
---

# Spec Gate — 소크라테스식 명세 명확화

harness 초기화, 마이그레이션, 대형 기능 개발 등 **복잡한 작업을 시작하기 전에** 목적과 범위를 명확히 한다.

모호성이 남은 채 작업을 시작하면 결과물이 요구와 어긋날 가능성이 높다.  
5개 영역(범위·목표·제약·레거시·우선순위)에서 표적 질문으로 모호성 점수를 0.2 이하로 낮춘다.

Ouroboros Socratic Interview 엔진에서 영감.

---

## 실행 흐름

```
[사용자 요청]
     ↓
경량 스캔 + 맥락 파악
     ↓
질문 생성 (3~5개) → 사용자에게 제시
     ↓
사용자 응답 수신
     ↓
모호성 점수 계산
     ├── ≤ 0.2: GO → 명세 리포트 저장 → 다음 작업 안내
     └── > 0.2: 재질문 (1회 한도) → GO → 명세 리포트 저장
```

---

## Step 0: 작업 컨텍스트 확인

`pwd`로 현재 디렉토리 확인.

사용자가 독립 실행 시 간단히 확인:
- 어떤 작업을 앞두고 있는가? (harness-init / 마이그레이션 / 대형 기능 개발 / 기타)
- 알려진 것이 있으면 spec-clarifier에 전달

---

## Step 1: spec-clarifier 호출 — question 모드

네임스페이스를 지정한 호출은 에이전트 지침이 자동으로 로드되므로 프롬프트에 절차를 인라인하지 않고 인자만 전달한다. 플러그인 네임스페이스 지정을 지원하지 않는 호스트에서는 `general-purpose`로 폴백하되 프롬프트에 "`agents/spec-clarifier.md`의 지침을 읽고 그대로 따른다"를 명시한다.

```
Agent(
  subagent_type="total-ito:spec-clarifier",
  description="명세 명확화 질문 생성",
  prompt="<mode: question.
  프로젝트 루트: [절대경로].
  앞두고 있는 작업 종류: [확인된 작업 또는 '미정'].
  반환: 사용자에게 제시할 질문 목록 (텍스트)>",
  model="sonnet"
)
```

반환된 질문 세트를 **그대로** 사용자에게 제시한다.  
응답을 기다린다. 응답 전 다음 단계 진행 금지.

---

## Step 2: spec-clarifier 호출 — score 모드

사용자 응답을 점수화하고 명세 리포트 작성:

```
Agent(
  subagent_type="total-ito:spec-clarifier",
  description="응답 점수화 + 명세 리포트 작성",
  prompt="<mode: score.
  원본 질문: [Step 1에서 생성된 질문 목록].
  사용자 응답: [사용자 응답 전문].
  출력: _workspace/00_spec_report.md>",
  model="sonnet"
)
```

---

## Step 3: REFINE 처리 (조건부)

`_workspace/00_spec_report.md`에서 신호 확인:

| 신호 | 동작 |
|------|------|
| **GO** (점수 ≤ 0.2) | Step 4 진행 |
| **REFINE** (점수 0.21~0.4) | spec-clarifier가 작성한 재질문을 사용자에게 제시 → 응답 수신 → score 모드 재실행 (1회 한도) → Step 4 진행 |
| **GO (미답변 진행)** (점수 > 0.4) | Step 4 진행 |

2차 score 실행 후에는 점수와 무관하게 Step 4 진행.

---

## Step 4: 결과 보고

`_workspace/00_spec_report.md` 요약을 사용자에게 표시:

```
명세 명확화 완료 (모호성 점수: X.XX)

목표: [코드이해 / 버그수정 / 신규개발 / 마이그레이션 / 복합]
범위: [전체 / 특정 모듈명]
주요 제약: [있으면 나열, 없으면 "없음"]
우선순위: [있으면 나열, 없으면 "없음"]
권고 Tier: [Standard / Full / 없음]

다음 단계:
  harness 초기화를 진행하려면 → "하네스 초기화"
  (spec 컨텍스트가 _workspace/00_spec_report.md에 저장되어 analyzer에 자동 전달됩니다)
```

---

## 에러 핸들링

| 상황 | 대응 |
|------|------|
| spec-clarifier 실패 | "명세화 미실행 — analyzer가 자동 탐지합니다" 안내 후 진행 |
| `_workspace/` 없음 | `_workspace/` 생성 후 재시도 |
| 사용자가 응답 없이 다음 단계 요청 | "스킵"으로 처리, GO 신호 발행 |
