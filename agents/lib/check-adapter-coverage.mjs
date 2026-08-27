#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { assessTargetCoverage } from "./adapters/registry.mjs";

const args = process.argv.slice(2);
const value = (name) => args[args.indexOf(name) + 1];
const root = resolve(value("--root") || process.cwd());
const target = value("--target");
if (!target) throw new Error("--target이 필요합니다");

const metaPath = join(root, "_workspace", "index", "_meta.json");

// _meta.json이 없거나(구버전 인덱스·미인덱싱) 손상돼 있으면 크래시 대신 HOLD로 우아하게 강등한다.
// 호출부(safe-modify 등)가 이 JSON을 그대로 파싱해 다음 단계 여부를 판단할 수 있게 형태를 유지.
function holdResult(reason, guidance) {
  return { target, decision: "HOLD", reason, guidance };
}

let raw;
try {
  raw = readFileSync(metaPath, "utf8");
} catch (err) {
  const reason = err.code === "ENOENT" ? "index_meta_missing" : `index_meta_unreadable:${err.code}`;
  const result = holdResult(
    reason,
    "build-index.mjs로 재인덱싱 필요(구버전 인덱스이거나 아직 인덱싱되지 않은 프로젝트로 추정)."
  );
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  process.exitCode = 2;
  process.exit();
}

let meta;
try {
  meta = JSON.parse(raw);
} catch (err) {
  const result = holdResult(
    "index_meta_corrupted",
    `_meta.json이 유효한 JSON이 아님(${err.message}). build-index.mjs로 재인덱싱 필요.`
  );
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  process.exitCode = 2;
  process.exit();
}

const result = { target, ...assessTargetCoverage(meta.adapter_coverage, target) };
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
process.exitCode = result.decision === "GO" ? 0 : 2;
