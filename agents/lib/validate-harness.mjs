#!/usr/bin/env node
/*
 * AX-Harness 인덱스 스키마 검증기 (축소판)
 *
 * 출처: upstream AX-Harness(Malburi/harness-sm) scripts/validate-harness.mjs, 2026-08-12 이식.
 * upstream 원본은 analyzer/writer/pattern-extractor 산출물의 마크다운 프로즈 구조(21개 필수
 * H2 섹션·한국어 분량 하한·Pattern Evidence 코드 예시 등)까지 검사하지만, 이 저장소의
 * agents/analyzer.md·writer.md·pattern-extractor.md는 완전히 다른 섹션 체계(Phase A~D,
 * `## A./B.` prefix)를 써서 매핑 근거가 없다 — 그대로 가져오면 정상 산출물이 전부 FAIL 처리된다.
 * 그래서 이 이식판은 JSON 쪽만 남긴다:
 *   - _workspace/index/*.json을 docs/index-schema/*.json 대조 스키마 검증(타입·enum·필수필드)
 *   - call_graph.json 엣지 참조 무결성 + AI 보강 엣지의 file:line 근거 확인
 *   - 인덱스가 가리키는 소스 파일이 실제로 존재하는지(evidence path) 확인
 *   - _meta.json의 generator·선언된 indexes·unresolved_count 정합성
 * 파일 존재(check1)·트리거 품질·보안 regex·패턴 스켈레톤 등은 이미 agents/lib/validator_checks.py가
 * 이 저장소 컨텍스트에 맞춰 담당하므로 중복 이식하지 않는다. 이 스크립트는 그것을 대체하지 않고
 * 병행한다 — 스키마 "형태" 검증과 validator_checks.py의 내용 "정확성" 검증(check7b, 실제 소스 대조)은
 * 서로 대체 불가능한 다른 층이다.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";

const INDEX_SCHEMAS = [
  "symbols", "call_graph", "sql_usage", "transactions", "external_io",
  "env_branches", "schema", "api_contract", "dead_code", "client_index", "data_flow",
];

function readJson(path, fallback = null) {
  try { return JSON.parse(readFileSync(path, "utf8")); } catch { return fallback; }
}

function parseArgs(argv) {
  const args = {
    root: process.cwd(),
    pluginRoot: resolve(dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, "$1")), ".."),
    out: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--root") args.root = argv[++i];
    else if (argv[i] === "--plugin-root") args.pluginRoot = argv[++i];
    else if (argv[i] === "--tier") args.tier = argv[++i];
    else if (argv[i] === "--out") args.out = argv[++i];
    else if (argv[i] === "--quiet") args.quiet = true;
    else throw new Error(`알 수 없는 인자: ${argv[i]}`);
  }
  args.root = resolve(args.root);
  args.pluginRoot = resolve(args.pluginRoot);
  return args;
}

function matchesType(value, type) {
  if (type === "null") return value === null;
  if (type === "array") return Array.isArray(value);
  if (type === "integer") return Number.isInteger(value);
  if (type === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
  return typeof value === type;
}

function validateSchema(value, schema, location, loadRef, errors) {
  if (schema.$ref) return validateSchema(value, loadRef(schema.$ref), location, loadRef, errors);
  const types = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  if (types.length && !types.some((type) => matchesType(value, type))) {
    errors.push(`${location}: 타입 불일치(expected ${types.join("|")})`);
    return;
  }
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${location}: 허용되지 않은 값 ${JSON.stringify(value)}`);
  if (typeof value === "number" && typeof schema.minimum === "number" && value < schema.minimum) {
    errors.push(`${location}: 최솟값 ${schema.minimum} 미만`);
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const key of schema.required || []) if (!(key in value)) errors.push(`${location}.${key}: 필수 필드 누락`);
    for (const [key, child] of Object.entries(schema.properties || {})) if (key in value) {
      validateSchema(value[key], child, `${location}.${key}`, loadRef, errors);
    }
  }
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, index) => validateSchema(item, schema.items, `${location}[${index}]`, loadRef, errors));
  }
}

function collectEvidenceFiles(value, output = []) {
  if (Array.isArray(value)) {
    for (const item of value) collectEvidenceFiles(item, output);
  } else if (value && typeof value === "object") {
    const path = value.file || value.source_file;
    if (typeof path === "string" && value.source !== "external") output.push(path);
    for (const child of Object.values(value)) collectEvidenceFiles(child, output);
  }
  return output;
}

function relativeSourceExists(root, path) {
  if (!path || isAbsolute(path) || path.includes("..")) return false;
  return existsSync(join(root, path.split(/[\\/]/).join(sep)));
}

function add(checks, level, code, message) {
  checks.push({ level, code, message });
}

function schemaFailureCode(document) {
  return document?._meta?.generator === "deterministic-indexer" ? "PLUGIN_INDEX_CONTRACT" : "INDEX_SCHEMA";
}

export function validateHarness({ root, pluginRoot, tier: requestedTier }) {
  const checks = [];
  const indexDir = join(root, "_workspace", "index");
  const meta = readJson(join(indexDir, "_meta.json"));
  if (!meta) add(checks, "FAIL", "META_MISSING", "_workspace/index/_meta.json이 없거나 JSON 파싱에 실패했습니다.");
  const tier = requestedTier || meta?.tier || "Standard";

  const schemaDir = join(pluginRoot, "docs", "index-schema");
  const schemaCache = new Map();
  const loadSchema = (name) => {
    const normalized = name.replace(/^\.\//, "");
    if (!schemaCache.has(normalized)) schemaCache.set(normalized, readJson(join(schemaDir, normalized), {}));
    return schemaCache.get(normalized);
  };
  if (meta) {
    const errors = [];
    validateSchema(meta, loadSchema("_meta.schema.json"), "_meta", loadSchema, errors);
    for (const error of errors) add(checks, "FAIL", schemaFailureCode(meta), error);
  }
  for (const name of INDEX_SCHEMAS) {
    const path = join(indexDir, `${name}.json`);
    if (!existsSync(path)) continue;
    const value = readJson(path);
    if (!value) { add(checks, "FAIL", "INDEX_PARSE", `${name}.json 파싱 실패`); continue; }
    const errors = [];
    validateSchema(value, loadSchema(`${name}.schema.json`), name, loadSchema, errors);
    for (const error of errors) add(checks, "FAIL", schemaFailureCode(value), error);
    for (const file of new Set(collectEvidenceFiles(value))) {
      if (!relativeSourceExists(root, file)) add(checks, "FAIL", "EVIDENCE_PATH", `${name}.json 근거 파일 없음: ${file}`);
    }
  }

  const graph = readJson(join(indexDir, "call_graph.json"));
  if (graph) {
    const ids = new Set((graph.nodes || []).map((node) => node.id));
    for (const edge of graph.edges || []) {
      if (!ids.has(edge.from) || !ids.has(edge.to)) add(checks, "FAIL", "GRAPH_REFERENCE", `존재하지 않는 노드 참조: ${edge.from} -> ${edge.to}`);
      if (edge.origin === "ai-enrichment" && (!edge.evidence || !edge.file || !Number.isInteger(edge.line))) {
        add(checks, "FAIL", "AI_EVIDENCE", `AI 보강 edge에 file:line/evidence 누락: ${edge.from} -> ${edge.to}`);
      }
    }
  }

  if (meta) {
    if (meta.generator !== "deterministic-indexer") add(checks, "WARN", "GENERATOR", `_meta.generator=${meta.generator}`);
    for (const name of meta.indexes || []) if (!existsSync(join(indexDir, `${name}.json`))) add(checks, "FAIL", "DECLARED_INDEX", `_meta에 선언됐지만 파일이 없음: ${name}.json`);
    const unresolvedPath = join(indexDir, "_unresolved.jsonl");
    const unresolved = existsSync(unresolvedPath) ? readFileSync(unresolvedPath, "utf8").split(/\r?\n/).filter(Boolean).length : 0;
    if (unresolved !== meta.unresolved_count) add(checks, "FAIL", "UNRESOLVED_COUNT", `_meta=${meta.unresolved_count}, 실제=${unresolved}`);
  }

  const failures = checks.filter((item) => item.level === "FAIL").length;
  const warnings = checks.filter((item) => item.level === "WARN").length;
  const pluginContractFailures = checks.filter((item) => item.level === "FAIL" && item.code === "PLUGIN_INDEX_CONTRACT").length;
  const score = Math.max(0, 100 - failures * 12 - warnings * 3);
  const status = failures ? "FAIL" : warnings ? "WARN" : "PASS";
  const result = {
    generated_at: new Date().toISOString(), root, tier, status, score,
    failures, warnings, plugin_contract_failures: pluginContractFailures, checks,
    coverage: {
      source_files: meta?.source_file_count || 0,
      indexes: meta?.indexes || [],
      unresolved: meta?.unresolved_count || 0,
    },
  };
  return result;
}

function main() {
  try {
    const args = parseArgs(process.argv.slice(2));
    const result = validateHarness(args);
    const outPath = resolve(args.root, args.out || join("_workspace", "validator_schema.json"));
    mkdirSync(dirname(outPath), { recursive: true });
    writeFileSync(outPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
    if (!args.quiet) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (result.failures) process.exitCode = 1;
  } catch (error) {
    process.stderr.write(`하네스 검증 실패: ${error.stack || error.message}\n`);
    process.exitCode = 1;
  }
}

const isMain = process.argv[1] && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, "$1"));
if (isMain) main();
