# block: assemble — 하네스 파일 조립 (Phase 2-2.3 / 2-2.5)

`pipeline-runner` 에이전트의 `block: assemble` 절차 상세다. 공통 규칙(스크립트 경로·`--out`/`--summary` 생략·에러 원칙·반환 원칙)은 `agents/pipeline-runner.md` 헤더에 있으며 여기서 반복하지 않는다.

writer 완료 후 실행한다. 전부 결정론적 파일 조립·복사이며 LLM 호출이 없다.

```powershell
python "$env:CLAUDE_PLUGIN_ROOT/agents/lib/skills_builder.py" --root "[root]"
```

이 한 번의 실행이 다음을 전부 처리한다.

- `_workspace/claude_md_fields.json` + `claude_md.md.template` → `CLAUDE.md` 조립. `pair_config.md`가 있으면 "파트너 프로젝트" 섹션도 자동으로 채운다.
- `_workspace/writer_decisions.json`의 적용 판단을 읽어 전역 워크플로우 스킬 이름을 CLAUDE.md 자동 워크플로우 표·ito-guide.md에 반영한다. 로컬 파일은 만들지 않는다.
- `_workspace/01_analyzer_report.md`를 그대로 복사해 `.claude/agents/domain-expert.md` 생성.
- `writer_decisions.json`의 `pattern_files` 목록(+ "LegacyStaticJS" 탐지 시 `client_pattern.md` 자동 추가)으로 `.claude/patterns/*.md` 스켈레톤 생성. 이미 pattern-extractor가 채운 파일은 덮어쓰지 않는다.
- `ito_guide.md.template` + 배포 스킬 frontmatter + 위 JSON 값으로 `.claude/ito-guide.md` 조립.
- 위 결과 전부를 조합해 `_workspace/02_writer_files.md` 조립.

실패 시(python 미설치, `claude_md_fields.json`/`writer_decisions.json` 누락 등) 1회만 재시도한다. 스크립트가 항목별로 독립 처리하므로 부분 성공이 가능하다 — 재실패해도 중단하지 않고, 아래 항목별 존재 확인 결과를 그대로 반환한다.

조립 후 각 산출물의 **존재만** 확인한다. 내용 검증은 verify 블록과 validator의 일이다.

## 반환 형식

```
BLOCK: assemble | LANE: [lane] | RESULT: OK | PARTIAL | FAIL
CLAUDE.md: 생성 | 누락
.claude/agents/domain-expert.md: 생성 | 누락
.claude/patterns/: [생성된 파일 수]개 ([파일명 목록])
.claude/ito-guide.md: 생성 | 누락
_workspace/02_writer_files.md: 생성 | 누락
retry: 0 | 1
WARN: [없으면 "없음", 있으면 사유 한 줄씩]
```
