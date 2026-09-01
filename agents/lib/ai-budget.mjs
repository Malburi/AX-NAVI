#!/usr/bin/env node
/*
 * AX-Harness AI 호출 예산 게이트
 *
 * 출처: upstream AX-Harness(Malburi/harness-sm) scripts/ai-budget.mjs, 2026-08-12 이식.
 * 로직은 무수정 — root/session/role/kind/reason만 다루는 완전 범용 스크립트라 이 저장소의
 * Tier·agent 이름을 가정하지 않는다. harness-init SKILL.md의 claim 호출 지점·예산 수치만
 * 이 저장소 컨벤션(Lite 폐지로 initial 3, Phase 4가 analyzer+writer 동시 재시도 가능해 retries 2)에
 * 맞춰 배선한다.
 *
 * initial claim은 역할당 평생 1회만 허용된다(호출 횟수가 아니라 "이미 한 번 썼는가" 규칙).
 * retry claim은 validator 실패 사유(--reason) 없이는 거부된다. 예산 소진 시 exit 1 — 조용히
 * 넘어가지 않는다.
 */
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

function parseArgs(argv) {
  const args = { command: argv[0] || "status", root: process.cwd(), kind: "initial", initial: 2, retries: 1 };
  for (let i = 1; i < argv.length; i += 1) {
    if (argv[i] === "--root") args.root = argv[++i];
    else if (argv[i] === "--session") args.session = argv[++i];
    else if (argv[i] === "--role") args.role = argv[++i];
    else if (argv[i] === "--kind") args.kind = argv[++i];
    else if (argv[i] === "--reason") args.reason = argv[++i];
    else if (argv[i] === "--initial") args.initial = Number(argv[++i]);
    else if (argv[i] === "--retries") args.retries = Number(argv[++i]);
    else if (argv[i] === "--minutes") args.minutes = Number(argv[++i]);
    else if (argv[i] === "--tokens") args.tokens = Number(argv[++i]);
    else if (argv[i] === "--spent-tokens") args.spentTokens = Number(argv[++i]);
    else if (argv[i] === "--now") args.now = Number(argv[++i]);
    else throw new Error(`알 수 없는 인자: ${argv[i]}`);
  }
  args.root = resolve(args.root);
  if (!new Set(["init", "claim", "record", "estimate", "status"]).has(args.command)) throw new Error(`지원하지 않는 명령: ${args.command}`);
  return args;
}

/*
 * 초기화 전 사전 견적.
 *
 * 이 하네스의 가장 큰 실패 모드는 "돌려봐야 얼마 드는지 안다"였다 — 사용자는 90분과 5시간 한도의
 * 40%를 쓰고 나서야 규모를 알았다. 인덱싱은 LLM 없이 끝나므로 그 결과만 있으면 이후 LLM 구간의
 * 규모를 미리 가늠할 수 있다. 정확한 예측이 목적이 아니라 **시작 전에 자릿수를 보여주는 것**이 목적이다.
 *
 * 계수는 2026-08 실측 세션(파일 2천~5천 규모 레거시)에서 역산한 값이고, 실행 후 `record`가 쌓는
 * 실제값으로 프로젝트마다 보정된다.
 */
export function estimateCost(meta, analysisInput) {
  const files = Number(meta?.source_file_count) || 0;
  const tier = meta?.tier || "Full";
  const counts = analysisInput?.counts || {};
  /*
   * 2026-09-01: build-index.mjs가 같은 (표현식/대상+candidates) 패턴을 그룹핑해
   * unresolved_decidable_group_count를 함께 내보내기 시작했다 — 레거시 코드베이스는 같은
   * 애매함이 수백 곳에서 반복되는 경우가 많아(실측: 발생 위치 2,380건이 실제로는 고유
   * 패턴 185개), 발생 위치 수(unresolved_decidable_count)로 예산을 잡으면 과대추정된다.
   * 그룹 수가 실제 analyzer 판정 횟수이므로 있으면 그걸 쓰고, 옛 인덱스(그룹 필드 없음)는
   * 기존 필드로 폴백한다.
   */
  const decidable = Number(
    analysisInput?.coverage?.unresolved_decidable_group_count ?? analysisInput?.coverage?.unresolved_decidable_count,
  ) || 0;

  /* 고정비: 에이전트 지침 + 산출물 왕복 (네임스페이스 호출 기준). */
  const fixed = tier === "Standard" ? 45_000 : 70_000;
  /* 규모비: 대표 파일 열람과 리포트 작성이 파일 수에 따라 는다. */
  const perFile = tier === "Standard" ? 12 : 22;
  /* 미해결 판정: 레코드당 소스 구간을 열어 확인한다 — 가장 변동이 큰 항목. */
  const perDecidable = 900;
  /* 패턴 추출은 레이어별 표본에 걸려 있어 상한이 뚜렷하다. */
  const patterns = 25_000;

  const tokens = fixed + files * perFile + Math.min(decidable, 2000) * perDecidable + patterns;
  /* 실측 기준 대략 분당 12K 토큰 전후로 진행됐다(모델·재시도 포함). */
  const minutes = Math.max(3, Math.round(tokens / 12_000));
  return {
    tier,
    files,
    decidable_unresolved: decidable,
    symbols: Number(counts.symbols) || 0,
    estimated_tokens: tokens,
    estimated_minutes: minutes,
    note: "인덱싱(LLM 없음) 이후 구간 추정치. 실제값은 record가 쌓이면 보정된다.",
  };
}

function budgetPath(root) { return join(root, "_workspace", "ai-budget.json"); }
function readBudget(root) {
  const path = budgetPath(root);
  if (!existsSync(path)) throw new Error(`AI 예산이 초기화되지 않았습니다: ${path}`);
  return JSON.parse(readFileSync(path, "utf8"));
}

function atomicJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.tmp-${process.pid}`;
  writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  renameSync(temp, path);
}

export function initBudget({ root, session, initial = 2, retries = 1, minutes = 0, tokens = 0, now = Date.now() }) {
  if (!session) throw new Error("init에는 --session이 필요합니다.");
  if (!Number.isInteger(initial) || initial < 0 || !Number.isInteger(retries) || retries < 0) throw new Error("예산은 0 이상의 정수여야 합니다.");
  const path = budgetPath(root);
  if (existsSync(path)) {
    const current = JSON.parse(readFileSync(path, "utf8"));
    if (current.session === session) return current;
  }
  /*
   * 한도를 호출 **횟수**로만 걸면 정작 큰 소비를 못 막는다 — 미해결 판정 한 번의 "호출"이
   * 파일 2000개 열람일 수 있었다. 그래서 시간·토큰 한도를 함께 건다(0이면 해당 한도 미적용).
   */
  const value = {
    version: 2, session,
    limits: { initial, retries, minutes: minutes || 0, tokens: tokens || 0 },
    used: { initial: 0, retries: 0, tokens: 0 },
    started_at: now,
    claims: [],
  };
  atomicJson(path, value);
  return value;
}

/* 실제 소비를 사후 기록한다 — 다음 claim의 한도 판정과 프로젝트별 견적 보정에 쓰인다. */
export function recordSpend({ root, role, spentTokens = 0 }) {
  const value = readBudget(root);
  value.used.tokens = (value.used.tokens || 0) + (Number(spentTokens) || 0);
  const last = [...value.claims].reverse().find((item) => item.role === role);
  if (last) last.spent_tokens = (last.spent_tokens || 0) + (Number(spentTokens) || 0);
  atomicJson(budgetPath(root), value);
  return { role, used: value.used, limits: value.limits };
}

export function claimBudget({ root, session, role, kind = "initial", reason = "", now = Date.now() }) {
  if (!role) throw new Error("claim에는 --role이 필요합니다.");
  if (!new Set(["initial", "retry"]).has(kind)) throw new Error("kind는 initial 또는 retry여야 합니다.");
  const value = readBudget(root);
  if (session && value.session !== session) throw new Error(`AI 예산 session 불일치: expected ${value.session}, got ${session}`);
  /* 시간·토큰 한도를 먼저 본다 — 횟수가 남아 있어도 이쪽이 소진되면 진행하지 않는다. */
  const limits = value.limits || {};
  if (limits.minutes > 0 && value.started_at) {
    const elapsed = (now - value.started_at) / 60000;
    if (elapsed >= limits.minutes) throw new Error(`시간 예산 초과: ${elapsed.toFixed(1)}분 / ${limits.minutes}분`);
  }
  if (limits.tokens > 0 && (value.used.tokens || 0) >= limits.tokens) {
    throw new Error(`토큰 예산 초과: ${value.used.tokens}/${limits.tokens}`);
  }
  const bucket = kind === "retry" ? "retries" : "initial";
  if (kind === "initial" && value.claims.some((item) => item.kind === "initial" && item.role === role)) {
    throw new Error(`동일 role의 initial 호출은 한 번만 허용됩니다: ${role}`);
  }
  if (value.used[bucket] >= value.limits[bucket]) throw new Error(`${bucket} AI 호출 예산 초과: ${value.used[bucket]}/${value.limits[bucket]}`);
  if (kind === "retry" && !reason.trim()) throw new Error("retry claim에는 validator 실패 --reason이 필요합니다.");
  const claim = { sequence: value.claims.length + 1, role, kind, reason: reason || undefined, claimed_at: now };
  value.claims.push(claim);
  value.used[bucket] += 1;
  atomicJson(budgetPath(root), value);
  return {
    allowed: true, claim,
    remaining: {
      initial: value.limits.initial - value.used.initial,
      retries: value.limits.retries - value.used.retries,
      tokens: limits.tokens > 0 ? limits.tokens - (value.used.tokens || 0) : null,
      minutes: limits.minutes > 0 && value.started_at ? Math.max(0, limits.minutes - (now - value.started_at) / 60000) : null,
    },
  };
}

export function budgetStatus(root) { return readBudget(root); }

function main() {
  try {
    const args = parseArgs(process.argv.slice(2));
    let result;
    if (args.command === "init") result = initBudget(args);
    else if (args.command === "claim") result = claimBudget(args);
    else if (args.command === "record") result = recordSpend(args);
    else if (args.command === "estimate") {
      const read = (name) => {
        const path = join(args.root, "_workspace", "index", name);
        return existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : null;
      };
      const meta = read("_meta.json");
      if (!meta) throw new Error("estimate에는 인덱스가 먼저 필요합니다 (_workspace/index/_meta.json 없음).");
      result = estimateCost(meta, read("_analysis_input.json"));
    } else result = budgetStatus(args.root);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } catch (error) {
    process.stderr.write(`AI 예산 거부: ${error.message}\n`);
    process.exitCode = 1;
  }
}

const isMain = process.argv[1] && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, "$1"));
if (isMain) main();
