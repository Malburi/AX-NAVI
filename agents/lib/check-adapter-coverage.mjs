#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { assessTargetCoverage } from "./adapters/registry.mjs";

const args = process.argv.slice(2);
const value = (name) => args[args.indexOf(name) + 1];
const root = resolve(value("--root") || process.cwd());
const target = value("--target");
if (!target) throw new Error("--target이 필요합니다");
const meta = JSON.parse(readFileSync(join(root, "_workspace", "index", "_meta.json"), "utf8"));
const result = { target, ...assessTargetCoverage(meta.adapter_coverage, target) };
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
process.exitCode = result.decision === "GO" ? 0 : 2;
