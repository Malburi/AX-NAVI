// verify-target.mjs의 검증 명령 감지(detect)와 실행(run) 회귀 테스트.
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, "..", "verify-target.mjs");

function write(root, rel, content) {
  const path = join(root, rel);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content, "utf8");
}

/* detect/run은 exit code로도 신호를 주므로 execFileSync가 던지면 그 출력을 그대로 회수한다. */
function runCli(argv) {
  try {
    return { stdout: execFileSync("node", [script, ...argv], { encoding: "utf8" }), status: 0 };
  } catch (e) {
    return { stdout: String(e.stdout || ""), status: e.status };
  }
}

export async function test(register, assert) {
  register("detect는 package.json scripts에서 lint/test/typecheck만 뽑는다", () => {
    const root = mkdtempSync(join(tmpdir(), "vt-detect-"));
    try {
      write(root, "package.json", JSON.stringify({ scripts: { lint: "eslint .", test: "jest", build: "tsc", start: "node ." } }));
      const { stdout } = runCli(["detect", "--root", root]);
      const out = JSON.parse(stdout);
      const cmds = out.detected.map((c) => c.cmd);
      assert.ok(cmds.includes("npm run lint"), stdout);
      assert.ok(cmds.includes("npm run test"), stdout);
      assert.ok(!cmds.includes("npm run build"), "build는 대상 아님");
      assert.ok(!cmds.includes("npm run start"), "start는 대상 아님");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("detect는 tsconfig.json에서 tsc --noEmit 타입체크를 잡는다", () => {
    const root = mkdtempSync(join(tmpdir(), "vt-ts-"));
    try {
      write(root, "tsconfig.json", "{}");
      const out = JSON.parse(runCli(["detect", "--root", root]).stdout);
      assert.ok(out.detected.some((c) => c.cmd === "npx tsc --noEmit" && c.kind === "typecheck"), JSON.stringify(out));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("detect는 pyproject.toml의 ruff/mypy 설정을 잡는다", () => {
    const root = mkdtempSync(join(tmpdir(), "vt-py-"));
    try {
      write(root, "pyproject.toml", "[tool.ruff]\nline-length = 100\n\n[tool.mypy]\nstrict = true\n");
      const out = JSON.parse(runCli(["detect", "--root", root]).stdout);
      const cmds = out.detected.map((c) => c.cmd);
      assert.ok(cmds.includes("ruff check ."), JSON.stringify(out));
      assert.ok(cmds.includes("mypy ."), JSON.stringify(out));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("detect는 검증 명령이 없으면 count 0과 안내 note를 준다", () => {
    const root = mkdtempSync(join(tmpdir(), "vt-empty-"));
    try {
      const out = JSON.parse(runCli(["detect", "--root", root]).stdout);
      assert.equal(out.count, 0, JSON.stringify(out));
      assert.ok(out.note && out.note.includes("찾지 못"), JSON.stringify(out));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("run은 성공 명령에 exit 0·overall pass·fail_lines 없음", () => {
    const root = mkdtempSync(join(tmpdir(), "vt-pass-"));
    try {
      const res = runCli(["run", "--root", root, "--cmd", "node --version"]);
      const out = JSON.parse(res.stdout);
      assert.equal(out.overall, "pass", res.stdout);
      assert.equal(out.commands[0].exit, 0, res.stdout);
      assert.equal(out.commands[0].fail_lines, undefined, "성공은 실패 라인 없음");
      assert.equal(res.status, 0, "성공 exit 0");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("run은 실패 명령에 overall fail·exit 2·실패 라인만 반환", () => {
    const root = mkdtempSync(join(tmpdir(), "vt-fail-"));
    try {
      const cmd = 'node -e "console.error(String.fromCharCode(69,114,114,111,114)+\\": boom\\"); process.exit(5)"';
      const res = runCli(["run", "--root", root, "--cmd", cmd]);
      const out = JSON.parse(res.stdout);
      assert.equal(out.overall, "fail", res.stdout);
      assert.equal(out.commands[0].exit, 5, res.stdout);
      assert.ok(out.commands[0].fail_lines.some((l) => /Error: boom/.test(l)), res.stdout);
      assert.equal(res.status, 2, "실패 exit 2");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("run은 실패 라인을 --limit 상한으로 자른다", () => {
    const root = mkdtempSync(join(tmpdir(), "vt-limit-"));
    try {
      // 20줄의 error 라인을 뱉고 실패 종료
      const cmd = 'node -e "for(let i=0;i<20;i++)console.error(\\"error line \\"+i); process.exit(1)"';
      const res = runCli(["run", "--root", root, "--cmd", cmd, "--limit", "5"]);
      const out = JSON.parse(res.stdout);
      assert.ok(out.commands[0].fail_lines.length <= 5, res.stdout);
      assert.ok(out.commands[0].truncated >= 1, "잘린 수 명시 " + res.stdout);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}
