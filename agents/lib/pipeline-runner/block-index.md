# block: index — 결정론적 전수 인덱싱 (Phase 2-0.5)

`pipeline-runner` 에이전트의 `block: index` 절차 상세다. 공통 규칙(스크립트 경로·`--out`/`--summary` 생략·에러 원칙·반환 원칙)은 `agents/pipeline-runner.md` 헤더에 있으며 여기서 반복하지 않는다.

## Step A — 실행 환경 확인

```powershell
node --version
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/stack_precheck.py" --root "[root]"
```

`node`가 exit 0이고 major 버전 18 이상이면 결정론적 인덱서를 쓴다. `stack_precheck.py`는 node 가용 여부와 무관하게 항상 실행한다 — 감지된 `detected_stack`이 validator의 DI 휴리스틱과 아래 폴백 선택에 쓰이고 비용이 거의 없다.

## Step B — `_workspace/indexer-config.json` 작성

`_workspace/00_init_scope.md`의 값을 그대로 옮긴다. 판단 없는 기계 변환이다.

```json
{"init_layout": "single-root", "include_paths": ["."], "workspace_mode": false,
 "workspaces": [{"id": "root", "path": "", "kind": "unknown", "stack": "unknown"}]}
```

- `selected-paths`면 선택한 상대경로들을 `include_paths`에 넣는다. 인덱서가 그 밖의 소스는 읽지 않는다.
- 모노레포면 모듈마다 `workspaces[]` 항목을 하나씩 두고 `stack`은 `00_stack_precheck.json`의 값을 쓴다.

## Step C — 인덱싱

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/build-index.mjs" --root "[root]" --mode [mode] --tier "[tier]" --config "_workspace/indexer-config.json"
```

`_workspace/index/`에 `symbols`·`call_graph`·`sql_usage`·`transactions`·`external_io`·`env_branches`·`schema`·`api_contract`·`dead_code`(해당 사실이 있는 것만) + `_meta.json`·`_analysis_input.json`·`_unresolved.jsonl`이 생성된다.

기존 인덱스의 `_meta.generator`가 `deterministic-indexer`가 아니면 `--mode incremental` 대신 **`--mode init`을 강제**한다. 생성기마다 노드 id 체계가 달라 섞이면 한 파일에 두 개의 id 네임스페이스가 생긴다.

## Step D — 스택 보강 (해당 시)

`00_stack_precheck.json`의 `extractors`를 보고 해당하는 것만 이어서 실행한다.

**D-1. Vue** — `extractors`에 `vue`가 있으면.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/index_extractor_vue.py" --root "[root]"
```

인덱서는 `.vue`를 JS로만 읽어 컴포넌트·Pinia 스토어 노드와 `import`·`inject` 엣지를 만들지 않는다. 이 스크립트가 그 부분만 얹는다 — 노드는 id 기준 중복 제거되므로 인덱서 결과를 덮어쓰지 않는다.

**D-2. C# Razor 뷰** — `extractors`에 `csharp_dotnet`이 있고 `.cshtml` 파일이 하나라도 있으면.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/index_extractor_csharp.py" --root "[root]"
```

인덱서는 `.cshtml`을 view 노드로만 올리고 Controller Action → 뷰 연결은 만들지 않는다. 이 스크립트가 `return View(...)` → `render` 엣지, 뷰의 `@model` → `import` 엣지를 얹는다. 노드 id 체계가 인덱서와 동일(`namespace.Class.method`, `view:상대경로`)해서 중복 노드는 id 기준 제거되고, 엣지는 (from, to, type) 기준 중복 제거된다. `.cshtml`이 없으면 render 엣지가 나올 수 없으므로 실행하지 않는다(전체 `.cs` 재파싱 낭비 방지).

## Step E — 폴백 사다리

| 순위 | 조건 | 실행 |
|---|---|---|
| 1 | node ≥ 18 | `build-index.mjs` (비정상 종료 시 1회 재시도 — 모든 출력이 원자적 쓰기라 반쪽 파일이 남지 않는다) |
| 2 | node 없음 또는 2회 실패 | `00_stack_precheck.json`의 `extractors`를 순회하며 스택별 Python 추출기를 차례로 실행 (`java_spring`→`index_extractor_java_spring.py`, `csharp_dotnet`→`_csharp.py`, `python_web`→`_python.py`, `vue`→`_vue.py`, `kotlin_android`→`_kotlin.py`). 이 경로는 `symbols.json`·`call_graph.json`만 만든다 |
| 3 | 감지 스택 없음 또는 2도 실패 | 인덱스를 만들지 않고 반환한다. analyzer가 처음부터 전부 작성한다 |

어느 순위로 실행됐는지 `_workspace/00_stack_precheck.json`에 `indexer` 키로 기록한다 — 성능이 떨어진 채 넘어간 실행이 조용히 묻히지 않게 한다.

> analyzer가 처음부터 직접 작성하는 인덱스는 `owasp_top10.json` 하나뿐이다(판단이 필요해 기계화 대상 아님, 2026-08-04 검토로 유지 확정). `data_flow.json`·`client_index.json`은 인덱서가 구조(체인 골격/JS↔JSP 매핑)까지 만들고, analyzer는 `_ai_patch.json`의 `set_flow_note`/`set_client_index_narrative`로 판단이 필요한 서술 필드만 보탠다(2026-08 이관). 인덱서가 만들지 못한 경우(대상 조건 미충족 등)의 `owasp_top10.json`은 인덱서가 만들지도 지우지도 않는다.

## Step E.5 — 사전 견적 계산

node ≥ 18일 때만 (Step A 프로브 결과 재사용). Step C가 이미 `_workspace/index/_meta.json`·`_analysis_input.json`을 만들어 뒀으므로 추가 인덱싱 없이 바로 견적을 낼 수 있다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" estimate --root "[root]"
```

결과의 `estimated_tokens`/`estimated_minutes`를 Step F에 그대로 넘긴다. (Phase 2-0.7이 사용자에게 보여주는 견적과 같은 계산이지만, Step F의 `init` 호출은 2-0.7보다 먼저 실행되므로 별도로 한 번 더 구한다 — 뒤에서 다시 구해 재전달하는 것보다 이 자리에서 직접 얻는 편이 라운드트립이 없다.)

## Step F — AI 호출 예산 초기화

node ≥ 18일 때만 (Step A 프로브 결과 재사용). Step E.5의 견적값을 시간·토큰 한도로 함께 건다 — 호출 **횟수** 한도만으로는 미해결 판정 "1회"가 파일 수천 개 열람으로 이어지는 사고를 못 막는다(`ai-budget.mjs` 자체 주석 참조). 한도는 견적의 2배로 준다 — 견적은 "시작 전 자릿수를 보여주는" 목적이라 부정확할 수 있고, 목적은 계획대로 진행되는 프로젝트를 막는 게 아니라 견적을 몇 배씩 벗어나는 이상 상황만 잡는 것이다.

```powershell
node "$env:CLAUDE_PLUGIN_ROOT/agents/lib/ai-budget.mjs" init --root "[root]" --session "[ai_budget_session]" --initial 3 --retries 2 --minutes [estimated_minutes*2] --tokens [estimated_tokens*2]
```

`init`은 세션당 이 한 번만 호출한다 — `initBudget`은 같은 session으로 다시 호출하면 새 인자를 무시하고 기존 값을 그대로 돌려주는 멱등성 가드가 있다(`ai-budget.test.mjs`로 고정된 계약). 그래서 시간·토큰 한도는 반드시 이 최초 호출에 실려 있어야 하며, 이후 어딘가에서 "이제 한도를 걸자"며 `init`을 다시 부르는 시도는 아무 효과가 없다.

node가 없으면 Step E.5와 이 Step을 스킵하고 `00_stack_precheck.json`에 "AI 예산 강제 미적용(node 없음)"으로 기록한다. 반환의 `ai_budget`에 그대로 드러낸다 — 오케스트레이터가 이후 `claim` 호출 여부를 이 값으로 판단한다.

## 반환 형식

```
BLOCK: index | LANE: [lane] | RESULT: OK | PARTIAL | FAIL
indexer_rank: 1 | 2 | 3
node: [버전 또는 none] / python: [ok 또는 none]
detected_stack: [값] / extractors: [목록]
index_files: [생성된 파일명 목록]
call_graph: nodes=[N] edges=[M] / symbols=[N]
ai_budget: initialized | skipped(node 없음)
WARN: [없으면 "없음", 있으면 한 줄씩]
```
