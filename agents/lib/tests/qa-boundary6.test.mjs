import { execFileSync } from "node:child_process";
import { pythonBin } from "../python-bin.mjs";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, "..", "qa_boundary6.py");

function write(root, rel, content) {
  const path = join(root, rel);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content, "utf8");
}

export async function test(register, assert) {
  /* 인터프리터 이름을 하드코딩하지 않는다 — Windows는 `python`, 다수 리눅스는 `python3`만 있다. */
  const PY_BIN = pythonBin();
  if (!PY_BIN) {
    register("QA Boundary 6 (건너뜀 — 실행 가능한 python3가 없음)", () => {
      assert.ok(true, "python3/python 미설치 환경");
    });
    return;
  }

  register("QA Boundary 6은 전역 스킬 파일이 아니라 writer 적용 결정과 필수 인덱스를 검사한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-qa6-"));
    try {
      write(root, "CLAUDE.md", "analyze-impact plan-migration review-sql\n");
      write(root, "_workspace/writer_decisions.json", JSON.stringify({
        plan_migration: { generate: false },
        review_sql: { generate: false },
      }));
      write(root, "_workspace/index/call_graph.json", "{}\n");
      const out = join(root, "_workspace", "qa_boundary6.md");
      execFileSync(PY_BIN, [script, "--root", root, "--out", out]);
      const report = readFileSync(out, "utf8");
      assert.ok(report.includes("analyze-impact 의존 인덱스: 존재"), report);
      assert.ok(report.includes("review-sql 의존 인덱스: 미적용"), report);
      assert.ok(report.includes("plan-migration 의존 인덱스: 미적용"), report);

      write(root, "_workspace/writer_decisions.json", JSON.stringify({
        plan_migration: { generate: false },
        review_sql: { generate: true },
      }));
      execFileSync(PY_BIN, [script, "--root", root, "--out", out]);
      assert.ok(readFileSync(out, "utf8").includes("review-sql 의존 인덱스: 누락 (sql_usage.json)"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}
