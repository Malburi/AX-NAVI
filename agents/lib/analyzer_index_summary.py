# analyzer 리포트 Section B/D를 인덱스 JSON에서 기계 생성하는 zero-LLM 빌더
import os
import sys
import json
import argparse
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# analyzer.md의 "01_analyzer_report.md" Section B(의존성 그래프/트랜잭션/외부통신/환경분기/데드코드/OWASP Top 10)
# + Section D(DB 스키마)는 _workspace/index/*.json에 이미 있는 카운트·표를 프로즈로 재진술한 것뿐이다.
# 이 스크립트가 그 재진술을 대신하고, analyzer(LLM)는 Section A(아키텍처 해석)와
# "비동기/스케줄/이벤트"·"인증/인가 경로"(대응하는 JSON 인덱스가 없어 기계화 불가)·
# "탐지 신뢰도"·"보완 권장"만 직접 작성한다.

TOP_HUB_LIMIT = 10
IO_TYPE_LABELS = {
    "http": "HTTP 호출",
    "kafka_producer": "메시지 큐",
    "kafka_consumer": "메시지 큐",
    "rabbit_producer": "메시지 큐",
    "rabbit_consumer": "메시지 큐",
    "sqs_producer": "메시지 큐",
    "sqs_consumer": "메시지 큐",
    "file_io": "파일 IO",
    "external_db": "외부 DB",
}


def _load_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"WARN: {path} 파싱 실패 — 해당 섹션 스킵", file=sys.stderr)
        return None


def _coverage_line(meta):
    """_meta의 files_scanned/files_total로 커버리지를 측정값으로 표기 (LLM 자기평가 보강)."""
    scanned, total = meta.get("files_scanned"), meta.get("files_total")
    if not (isinstance(scanned, int) and isinstance(total, int) and total > 0):
        return None
    pct = round(scanned * 100 / total)
    sampled = " · 샘플링 모드" if meta.get("sampled") else ""
    return f"- 분석 커버리지: {scanned}/{total} 파일 ({pct}%){sampled}"


def _section_call_graph(data):
    if not data:
        return None
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    in_degree = Counter(e.get("to") for e in edges if e.get("to"))
    top = in_degree.most_common(TOP_HUB_LIMIT)
    hub_lines = "\n".join(f"  - {node_id} (in-degree {count})" for node_id, count in top) or "  - (없음)"
    coverage = _coverage_line(data.get("_meta") or {})
    return (
        "## B. 의존성 그래프 요약\n"
        f"- 노드 수: {len(nodes)}, 엣지 수: {len(edges)}\n"
        + (coverage + "\n" if coverage else "")
        + f"- 핵심 허브 메서드 (in-degree 상위 {TOP_HUB_LIMIT}개):\n{hub_lines}\n"
        "- 인덱스: _workspace/index/call_graph.json\n"
    )


def _section_transactions(data):
    if not data:
        return None
    boundaries = data.get("boundaries") or []
    largest = max(boundaries, key=lambda b: len(b.get("methods_in_scope") or []), default=None)
    if largest:
        largest_desc = (
            f"{largest.get('entry_method', '미상')} "
            f"({largest.get('file', '?')}:{largest.get('line', '?')}, "
            f"메서드 {len(largest.get('methods_in_scope') or [])}개)"
        )
    else:
        largest_desc = "(없음)"
    return (
        "## B. 트랜잭션 경계\n"
        f"- 식별된 경계: {len(boundaries)}개\n"
        f"- 가장 큰 경계 (메서드 호출 수): {largest_desc}\n"
        "- 인덱스: _workspace/index/transactions.json\n"
    )


def _section_external_io(data):
    if not data:
        return None
    comms = data.get("communications") or []
    label_counts = Counter(IO_TYPE_LABELS.get(c.get("type"), c.get("type") or "기타") for c in comms)
    lines = "\n".join(f"- {label}: {count}건" for label, count in sorted(label_counts.items())) or "- (없음)"
    return (
        "## B. 외부 통신\n"
        f"{lines}\n"
        "- 인덱스: _workspace/index/external_io.json\n"
    )


def _section_env_branches(data):
    if not data:
        return None
    profiles = data.get("profiles") or []
    branches = data.get("branches") or []
    return (
        "## B. 환경 분기\n"
        f"- 활성 프로파일: {', '.join(profiles) if profiles else '(미상)'}\n"
        f"- 분기 위치: {len(branches)}곳\n"
        "- 인덱스: _workspace/index/env_branches.json\n"
    )


def _section_dead_code(data):
    if not data:
        return None
    methods = data.get("unused_methods") or []
    sql_ids = data.get("unused_sql_ids") or []
    # 생성기마다 "low"/"LOW"로 갈린다 (스키마 enum은 대문자, analyzer는 소문자로 써 왔음)
    low_conf = sum(1 for m in methods if isinstance(m, dict) and str(m.get("confidence") or "").lower() == "low")
    low_note = f" (그중 confidence=low {low_conf}개 — 샘플링 그래프 파생)" if low_conf else ""
    suspect = sum(1 for m in methods if isinstance(m, dict) and m.get("entrypoint_suspect"))
    suspect_note = f"\n- 그중 진입점 의심 {suspect}개 (같은 파일에 API 핸들러 존재 — 데드 코드가 아닐 수 있음)" if suspect else ""
    return (
        "## B. 데드 코드 후보\n"
        f"- 미사용 public 메서드 후보: {len(methods)}개{low_note} (확정 아님, 리플렉션/동적 호출 확인 필요){suspect_note}\n"
        f"- 미사용 SQL ID 후보: {len(sql_ids)}개\n"
        "- 인덱스: _workspace/index/dead_code.json\n"
    )


def _section_owasp(data):
    if not data:
        return None
    categories = data.get("categories") or []
    if not categories:
        return None
    found = [c for c in categories if c.get("status") == "발견"]
    review = [c for c in categories if c.get("status") == "확인필요"]
    high_sev = sum(
        1 for c in found for f in (c.get("findings") or []) if f.get("severity") == "high"
    )
    lines = []
    for c in categories:
        cnt = len(c.get("findings") or [])
        suffix = f" ({cnt}건)" if cnt else ""
        lines.append(f"  - {c.get('id', '?')} {c.get('name', '')}: {c.get('status', '미상')}{suffix}")
    sampled = " · 샘플링 모드" if (data.get("_meta") or {}).get("sampled") else ""
    return (
        "## B. OWASP Top 10 매핑\n"
        f"- 발견: {len(found)}개 카테고리 (severity=high {high_sev}건), 확인필요: {len(review)}개{sampled}\n"
        + "\n".join(lines) + "\n"
        "- 인덱스: _workspace/index/owasp_top10.json\n"
        "- 주의: '미탐지'는 코드에서 해당 패턴을 못 찾았다는 뜻이지 취약점이 없다는 보증이 아니다.\n"
    )


def _section_schema(data):
    if not data:
        return None
    tables = data.get("tables") or []
    source = (data.get("_meta") or {}).get("source", "미상")
    source_label = {
        "live_db": "DB 직접 접속",
        "ddl_files": "DDL 파일",
        "orm_mapping": "ORM 역추출",
    }.get(source, source)
    return (
        "## D. DB 스키마 (가능한 경우)\n"
        f"- 테이블 수: {len(tables)}\n"
        "- 인덱스: _workspace/index/schema.json\n"
        f"- 출처: {source_label}\n"
    )


def build_summary(root):
    index_dir = os.path.join(root, "_workspace", "index")
    builders = [
        ("call_graph.json", _section_call_graph),
        ("transactions.json", _section_transactions),
        ("external_io.json", _section_external_io),
        ("env_branches.json", _section_env_branches),
        ("dead_code.json", _section_dead_code),
        ("owasp_top10.json", _section_owasp),
        ("schema.json", _section_schema),
    ]
    sections = []
    for filename, builder in builders:
        data = _load_json(os.path.join(index_dir, filename))
        section = builder(data)
        if section:
            sections.append(section)
    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="analyzer 리포트 Section B/D 기계 생성기 (인덱스 JSON 재진술, LLM 미사용)")
    parser.add_argument("--root", required=True, help="프로젝트 루트 절대 경로")
    parser.add_argument("--out", default=None, help="출력 경로 (기본: [root]/_workspace/01b_index_summary.md)")
    args = parser.parse_args()

    out_path = args.out or os.path.join(args.root, "_workspace", "01b_index_summary.md")
    summary = build_summary(args.root)

    if not summary:
        print("WARN: 인덱스 파일이 하나도 없어 Section B/D 생성 스킵 — analyzer가 직접 작성 필요", file=sys.stderr)
        return

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"생성 완료: {out_path}")


if __name__ == "__main__":
    main()
