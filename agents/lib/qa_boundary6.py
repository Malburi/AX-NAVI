# qa Boundary 6(워크플로우 스킬 ↔ 인덱스 의존성)을 기계 실행하는 zero-LLM 검사기
import os
import sys
import argparse
import json

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# qa.md의 Boundary 6(신규 워크플로우 스킬 ↔ 인덱스 의존성)은 파일 존재 확인뿐이라 LLM이
# 필요 없다. 나머지 Boundary 1~5, 7은 실제 소스코드를 읽고 의미 비교가 필요해 그대로 qa(LLM)가 담당.

DEPS = {
    "analyze-impact": {"always": True, "required": ["call_graph.json"], "optional": []},
    "review-sql": {"decision": "review_sql", "required": ["sql_usage.json"], "optional": ["schema.json"]},
    "plan-migration": {"decision": "plan_migration", "required": ["call_graph.json"], "optional": ["external_io.json", "transactions.json"]},
}


def _json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def build_report(root):
    index_dir = os.path.join(root, "_workspace", "index")
    decisions = _json(os.path.join(root, "_workspace", "writer_decisions.json"))
    claude_path = os.path.join(root, "CLAUDE.md")
    try:
        with open(claude_path, "r", encoding="utf-8-sig") as handle:
            claude_text = handle.read()
    except OSError:
        claude_text = ""

    lines = []
    for skill, contract in DEPS.items():
        decision_key = contract.get("decision")
        decision = decisions.get(decision_key, {}) if decision_key else {}
        # writer_decisions가 있으면 조건부 스킬의 명시 결정을 우선한다. 구버전 프로젝트처럼
        # 결정 키 자체가 없을 때만 CLAUDE.md 등록을 하위호환 신호로 사용한다.
        conditional_applicable = bool(decision.get("generate")) if decision_key in decisions else skill in claude_text
        applicable = contract.get("always", False) or conditional_applicable
        if not applicable:
            lines.append(f"- {skill} 의존 인덱스: 미적용 (writer_decisions/CLAUDE.md 기준)")
            continue
        missing = [name for name in contract["required"] if not os.path.isfile(os.path.join(index_dir, name))]
        optional_missing = [name for name in contract["optional"] if not os.path.isfile(os.path.join(index_dir, name))]
        if missing:
            lines.append(f"- {skill} 의존 인덱스: 누락 ({', '.join(missing)})")
        else:
            required = ", ".join(contract["required"])
            suffix = f"; 선택 인덱스 없음 ({', '.join(optional_missing)})" if optional_missing else ""
            lines.append(f"- {skill} 의존 인덱스: 존재 ({required}){suffix}")

    any_missing = any("누락" in l for l in lines)
    recommendation = (
        "analyzer를 init/incremental 모드로 재실행하여 필수 인덱스 생성"
        if any_missing
        else "누락 없음"
    )

    return (
        "## Boundary 6: Workflow Skills ↔ Index Deps (NEW)\n"
        + "\n".join(lines)
        + f"\n권고: {recommendation}\n"
    )


def main():
    parser = argparse.ArgumentParser(description="qa Boundary 6 기계 실행기 (LLM 미사용)")
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    out_path = args.out or os.path.join(args.root, "_workspace", "qa_boundary6.md")
    report = build_report(args.root)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"생성 완료: {out_path}")


if __name__ == "__main__":
    main()
