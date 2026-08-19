# pattern-extractor 산출물(05_patterns_extracted.md) 집계 표를 패턴 파일에서 취합하는 zero-LLM 빌더
import os
import re
import sys
import argparse
import glob

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# pattern-extractor.md의 05_patterns_extracted.md 집계 표(샘플수/신뢰도/안티패턴 발견 수)는
# 각 .claude/patterns/*.md 파일에 pattern-extractor가 이미 써놓은 값을 그대로 취합한 것뿐이다.
# 이 스크립트가 취합을 대신하고, pattern-extractor(LLM)는 각 패턴 파일의 본문(권장 패턴·안티패턴·
# 가이드)과 05_patterns_extracted.md의 "## 권고" 문단만 직접 작성한다.

SKELETON_MARKER = "pattern-extractor 에이전트가 채울 예정입니다"
SAMPLE_COUNT_RE = re.compile(r"샘플\s*파일\s*수:\s*(\d+)")
CONFIDENCE_RE = re.compile(r"신뢰도:\s*(HIGH|MEDIUM|LOW)")
LOCATION_RE = re.compile(r"^-\s*위치:\s*`?([^`\n]+)`?", re.MULTILINE)
FREQ_ITEM_RE = re.compile(r"### \[?항목[^\]\n]*\]?[^\n]*\n빈도:\s*(\d+)%")


def _analyze_pattern_file(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    name = os.path.basename(path)

    if SKELETON_MARKER in text:
        return {"name": name, "status": "skeleton"}

    sample_m = SAMPLE_COUNT_RE.search(text)
    conf_m = CONFIDENCE_RE.search(text)
    locations = LOCATION_RE.findall(text)
    low_freq_items = [(pct) for pct in FREQ_ITEM_RE.findall(text) if int(pct) < 80]

    return {
        "name": name,
        "status": "filled",
        "samples": int(sample_m.group(1)) if sample_m else None,
        "confidence": conf_m.group(1) if conf_m else "미상",
        "antipattern_count": len(locations),
        "antipattern_locations": locations,
        "low_freq_count": len(low_freq_items),
    }


def build_summary(patterns_dir):
    paths = sorted(glob.glob(os.path.join(patterns_dir, "*.md")))
    if not paths:
        return None

    results = [_analyze_pattern_file(p) for p in paths]

    filled = [r for r in results if r["status"] == "filled"]
    skeletons = [r for r in results if r["status"] == "skeleton"]

    table_rows = []
    for r in filled:
        samples = r["samples"] if r["samples"] is not None else "?"
        loc_suffix = f" ({', '.join(r['antipattern_locations'])})" if r["antipattern_locations"] else ""
        table_rows.append(
            f"| {r['name']} | {samples} | {r['confidence']} | {r['antipattern_count']}{loc_suffix} |"
        )

    lines = [
        "| 패턴 파일 | 샘플 수 | 신뢰도 | 안티패턴 발견 |",
        "|----------|--------|--------|------------|",
    ]
    lines.extend(table_rows)

    total_samples = sum(r["samples"] for r in filled if r["samples"] is not None)

    low_freq_files = [r["name"] for r in filled if r["low_freq_count"] > 0]
    inconsistent_lines = (
        "\n".join(f"- {name}: 빈도 80% 미만 항목 존재 — 주요 패턴 + 부 패턴 병기 확인" for name in low_freq_files)
        or "- (없음)"
    )

    skipped_note = ""
    if skeletons:
        skipped_note = (
            "\n미처리 스켈레톤 (pattern-extractor 미실행): "
            + ", ".join(r["name"] for r in skeletons) + "\n"
        )

    return (
        f"처리한 스켈레톤: {len(filled)}개\n"
        f"샘플 수집: 총 {total_samples}개 파일\n"
        f"{skipped_note}\n"
        + "\n".join(lines)
        + "\n\n## 일관성 낮은 영역\n"
        + inconsistent_lines
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description="05_patterns_extracted.md 집계 표 기계 생성기 (LLM 미사용)")
    parser.add_argument("--root", required=True, help="프로젝트 루트 절대 경로")
    parser.add_argument("--patterns-dir", default=None, help="기본: [root]/.claude/patterns")
    parser.add_argument("--out", default=None, help="출력 경로 (기본: [root]/_workspace/05b_pattern_tally.md)")
    args = parser.parse_args()

    patterns_dir = args.patterns_dir or os.path.join(args.root, ".claude", "patterns")
    out_path = args.out or os.path.join(args.root, "_workspace", "05b_pattern_tally.md")

    summary = build_summary(patterns_dir)
    if not summary:
        print(f"WARN: {patterns_dir}에 패턴 파일 없음 — 집계 스킵", file=sys.stderr)
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"생성 완료: {out_path}")


if __name__ == "__main__":
    main()
