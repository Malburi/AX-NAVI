#!/usr/bin/env node
// 대상 프로젝트의 로컬 검증 명령(lint/typecheck/test)을 감지하고 실행해 실패 라인만 압축 반환한다.
/*
 * 존재 이유는 토큰이다. safe-modify/vibe/scaffold-feature는 "가장 작은 lint/build/test를 실제
 * 실행하라"는 지침만 있었고, 어떤 명령인지 정하는 건 매번 LLM 몫이었다. 그 결과 검증이
 * 임기응변으로 흐르거나("테스트 없어서 통과"), 명령 출력 전체가 컨텍스트로 흘러들었다.
 *
 * 이 스크립트는 그 둘을 끊는다:
 *  - detect: 프로젝트 매니페스트에서 검증 명령 후보를 읽기만 한다(부작용 0). 무엇을 돌릴지
 *            사용자에게 먼저 보여주기 위한 것 — 임의 명령을 실행하지 않는다.
 *  - run:    감지된 명령을 실행하되 성공이면 0토큰(요약만), 실패면 실패 라인만(명령당 상한)
 *            돌려준다. 코드 전체를 LLM에게 "검수해줘"로 되돌리지 않는다.
 *
 * 설계 원칙(query-index.mjs와 동일)
 * - 항상 JSON 한 덩어리로 답한다.
 * - 출력에 상한을 걸고 truncated로 잘린 수를 밝힌다. 조용히 자르지 않는다.
 * - exitCode는 pass=0 / fail·오류=2 (check-adapter-coverage.mjs 관례).
 */
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const FAIL_LINE_LIMIT = 15; // 명령당 반환할 실패 라인 상한

function parseArgs(argv) {
  const args = { command: argv[0] || "help", root: process.cwd() };
  for (let i = 1; i < argv.length; i += 1) {
    if (argv[i] === "--root") args.root = argv[++i];
    else if (argv[i] === "--target") args.target = argv[++i];
    else if (argv[i] === "--cmd") args.cmd = argv[++i];
    else if (argv[i] === "--limit") args.limit = Math.max(1, Number(argv[++i]) || FAIL_LINE_LIMIT);
    else throw new Error(`알 수 없는 인자: ${argv[i]}`);
  }
  args.root = resolve(args.root);
  args.limit = args.limit || FAIL_LINE_LIMIT;
  return args;
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

/*
 * 매니페스트별 검증 명령 후보를 모은다. 실행하지 않고 목록만 만든다.
 * 각 항목: { kind, cmd, source } — kind는 lint|typecheck|test|build.
 */
function detectCommands(root) {
  const commands = [];
  const add = (kind, cmd, source) => commands.push({ kind, cmd, source });

  // Node/JS/TS — package.json scripts
  const pkgPath = join(root, "package.json");
  if (existsSync(pkgPath)) {
    const pkg = readJson(pkgPath) || {};
    const scripts = pkg.scripts || {};
    for (const name of Object.keys(scripts)) {
      const lower = name.toLowerCase();
      if (lower === "lint" || lower === "typecheck" || lower === "type-check" || lower === "test") {
        const kind = lower === "test" ? "test" : lower === "lint" ? "lint" : "typecheck";
        add(kind, `npm run ${name}`, "package.json:scripts");
      }
    }
  }
  // TypeScript — tsconfig 존재 시 타입체크
  if (existsSync(join(root, "tsconfig.json"))) {
    add("typecheck", "npx tsc --noEmit", "tsconfig.json");
  }
  // Biome — 설정 있으면 lint
  if (existsSync(join(root, "biome.json")) || existsSync(join(root, "biome.jsonc"))) {
    add("lint", "npx biome check .", "biome.json");
  }

  // Python — pyproject/setup.cfg/.flake8
  const hasPyproject = existsSync(join(root, "pyproject.toml"));
  if (hasPyproject) {
    const text = readFileSync(join(root, "pyproject.toml"), "utf8");
    if (/\[tool\.ruff/.test(text)) add("lint", "ruff check .", "pyproject.toml:tool.ruff");
    if (/\[tool\.mypy/.test(text)) add("typecheck", "mypy .", "pyproject.toml:tool.mypy");
  }
  if (existsSync(join(root, ".flake8")) || existsSync(join(root, "setup.cfg"))) {
    add("lint", "flake8", ".flake8/setup.cfg");
  }

  // Java — 빌드 도구 (테스트/컴파일)
  if (existsSync(join(root, "pom.xml"))) add("build", "mvn -q -DskipTests=false test", "pom.xml");
  else if (existsSync(join(root, "build.gradle")) || existsSync(join(root, "build.gradle.kts")))
    add("build", "gradle test", "build.gradle");

  // Makefile — 관례적 타깃
  if (existsSync(join(root, "Makefile"))) {
    const mk = readFileSync(join(root, "Makefile"), "utf8");
    for (const t of ["lint", "test", "check"]) {
      if (new RegExp(`^${t}:`, "m").test(mk)) add(t === "test" ? "test" : "lint", `make ${t}`, "Makefile");
    }
  }

  // 중복 cmd 제거 (같은 명령이 여러 소스로 잡히는 경우)
  const seen = new Set();
  const unique = commands.filter((c) => (seen.has(c.cmd) ? false : (seen.add(c.cmd), true)));
  return unique;
}

/* 명령 출력에서 실패 신호가 있는 라인만 추린다. 없으면 마지막 라인들로 폴백. */
function extractFailLines(output, limit) {
  const lines = output.split(/\r?\n/).filter((l) => l.trim() !== "");
  const signal = /error|fail|failed|assert|exception|warn(ing)?|✕|✗|✖|traceback/i;
  const hits = lines.filter((l) => signal.test(l));
  const picked = hits.length > 0 ? hits : lines.slice(-limit);
  const truncated = Math.max(0, picked.length - limit);
  return { fail_lines: picked.slice(0, limit), truncated };
}

/* 명령 하나를 실행하고 exit code와 실패 라인만 캡처한다. */
function runCommand(root, cmd, limit) {
  const result = spawnSync(cmd, { cwd: root, shell: true, encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  const exit = result.status == null ? (result.error ? 127 : 1) : result.status;
  const combined = `${result.stdout || ""}\n${result.stderr || ""}`;
  const entry = { cmd, exit };
  if (exit !== 0) {
    const { fail_lines, truncated } = extractFailLines(combined, limit);
    entry.fail_lines = fail_lines;
    if (truncated > 0) entry.truncated = truncated;
    if (result.error) entry.spawn_error = String(result.error.message || result.error);
  }
  return entry;
}

function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.command === "detect") {
    const commands = detectCommands(args.root);
    const payload = {
      command: "detect",
      root: args.root,
      target: args.target || null,
      detected: commands,
      count: commands.length,
      note: commands.length === 0 ? "검증 명령을 찾지 못했습니다 — 수동 검증 시나리오가 필요합니다." : null,
    };
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
    process.exitCode = 0;
    return;
  }

  if (args.command === "run") {
    if (!args.cmd) throw new Error("run에는 --cmd가 필요합니다 (detect 결과의 cmd를 그대로 전달)");
    // detect가 내는 명령은 단일 명령이다. 여러 명령이 필요하면 run을 여러 번 호출한다
    // (여기서 &&·; 로 쪼개면 따옴표 안 인자까지 잘려 명령이 깨진다).
    const commands = [runCommand(args.root, args.cmd, args.limit)];
    const overall = commands.every((c) => c.exit === 0) ? "pass" : "fail";
    const payload = {
      command: "run",
      root: args.root,
      commands,
      overall,
    };
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
    process.exitCode = overall === "pass" ? 0 : 2;
    return;
  }

  process.stdout.write(
    [
      "verify-target.mjs — 대상 프로젝트 로컬 검증 감지·실행",
      "",
      "사용법:",
      "  node verify-target.mjs detect --root <경로> [--target <상대경로>]",
      "  node verify-target.mjs run --root <경로> --cmd \"<명령>\" [--limit 15]",
    ].join("\n") + "\n",
  );
  process.exitCode = 0;
}

main();
