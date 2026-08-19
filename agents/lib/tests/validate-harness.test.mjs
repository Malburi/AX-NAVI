import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { validateHarness } from "../validate-harness.mjs";

// 이 파일 = agents/lib/tests/validate-harness.test.mjs -> dirname 4회(tests->lib->agents->루트)
const THIS_FILE = new URL(import.meta.url).pathname.replace(/^\/(\w:)/, "$1");
const PLUGIN_ROOT = dirname(dirname(dirname(dirname(THIS_FILE))));

function write(root, rel, content) {
  const path = join(root, rel);
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, content, "utf8");
}

function writeGoodFixture(root) {
  write(root, "src/OrderService.js", "class OrderService { cancel() { return true; } }\n");
  const meta = {
    generated_at: "2026-08-12T12:00:00+09:00", generator: "deterministic-indexer", version: "1.0",
    source_root: root, mode: "init", git_commit: null, sampled: false, files_scanned: 1, files_total: 1,
    source_file_count: 1, tier: "Standard", indexes: ["symbols", "call_graph"], unresolved_count: 0,
  };
  write(root, "_workspace/index/_meta.json", JSON.stringify(meta, null, 2));
  write(root, "_workspace/index/symbols.json", JSON.stringify({
    _meta: meta,
    symbols: [{ id: "src.OrderService", type: "class", file: "src/OrderService.js", line: 1, package: "src" }],
  }, null, 2));
  write(root, "_workspace/index/call_graph.json", JSON.stringify({
    _meta: { ...meta, node_count: 1, edge_count: 0 },
    nodes: [{ id: "src.OrderService.cancel", type: "method", file: "src/OrderService.js", line: 1 }],
    edges: [],
  }, null, 2));
  write(root, "_workspace/index/_unresolved.jsonl", "");
  return meta;
}

function withTempRoot(fn) {
  const root = mkdtempSync(join(tmpdir(), "ax-validate-harness-"));
  try {
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

export async function test(register, assert) {
  register("정상 픽스처는 실패 없이 PASS한다", () => {
    withTempRoot((root) => {
      writeGoodFixture(root);
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.equal(result.failures, 0, `실패 없어야 함: ${JSON.stringify(result.checks)}`);
      assert.equal(result.status, "PASS");
    });
  });

  register("_meta.json 필수 필드 결손은 스키마 FAIL이다", () => {
    withTempRoot((root) => {
      writeGoodFixture(root);
      // generator를 지워 스키마 required 위반을 만든다 (analyzer가 쓴 것으로 위장 -> INDEX_SCHEMA)
      write(root, "_workspace/index/_meta.json", JSON.stringify({
        generated_at: "2026-08-12T12:00:00+09:00", version: "1.0", source_root: root, mode: "init",
        tier: "Standard", indexes: [], unresolved_count: 0,
      }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.ok(result.failures > 0, "generator 없는 _meta는 FAIL이어야 함");
      assert.ok(result.checks.some((c) => c.code === "INDEX_SCHEMA"), `INDEX_SCHEMA 코드 있어야 함: ${JSON.stringify(result.checks)}`);
    });
  });

  register("generator=deterministic-indexer인 인덱스 파일의 스키마 결함은 PLUGIN_INDEX_CONTRACT다", () => {
    // schemaFailureCode는 각 인덱스 파일 내부의 _meta.generator를 보고 판단한다(파일 자체인
    // _meta.json의 자체 검증에는 적용되지 않음 — upstream 원본 그대로의 동작).
    withTempRoot((root) => {
      const meta = writeGoodFixture(root);
      write(root, "_workspace/index/symbols.json", JSON.stringify({
        _meta: { ...meta, mode: 123 },
        symbols: [{ id: "src.OrderService", type: "class", file: "src/OrderService.js", line: 1, package: "src" }],
      }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.ok(result.checks.some((c) => c.code === "PLUGIN_INDEX_CONTRACT"), `PLUGIN_INDEX_CONTRACT 있어야 함: ${JSON.stringify(result.checks)}`);
    });
  });

  register("client_index/data_flow도 스키마 검증 대상이다 (기존 픽스처에 허위 FAIL을 내지 않는다)", () => {
    withTempRoot((root) => {
      const meta = writeGoodFixture(root);
      write(root, "_workspace/index/client_index.json", JSON.stringify({
        _meta: meta, type: "LegacyStaticJS", build_tool: null, js_count: 120,
        domain_structure: { back: ["education/course"] },
        sample_mappings: [{ js: "back/education/course/a.js", jsps: ["a.jsp"], functions: ["onInit"] }],
        jquery_versions: [],
      }, null, 2));
      write(root, "_workspace/index/data_flow.json", JSON.stringify({
        _meta: meta,
        chains: [{ id: "dataflow:x", endpoint_id: "x", method_chain: ["a.b"], sql_ids: ["Mapper.q"], tables_read: ["T"], tables_written: [], confidence: "MEDIUM" }],
      }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.equal(result.failures, 0, `정상 구조인데 FAIL이 남: ${JSON.stringify(result.checks)}`);
    });
  });

  register("client_index의 구조 필드가 빠지면 PLUGIN_INDEX_CONTRACT로 잡힌다", () => {
    withTempRoot((root) => {
      const meta = writeGoodFixture(root);
      write(root, "_workspace/index/client_index.json", JSON.stringify({
        _meta: meta, type: "LegacyStaticJS", build_tool: null,
        /* js_count 누락 — 인덱서 소유 구조 필드 결손 */
        domain_structure: {}, sample_mappings: [], jquery_versions: [],
      }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.ok(result.checks.some((c) => c.code === "PLUGIN_INDEX_CONTRACT" && c.message.includes("js_count")), `js_count 누락이 PLUGIN_INDEX_CONTRACT여야 함: ${JSON.stringify(result.checks)}`);
    });
  });

  register("call_graph의 dangling edge는 GRAPH_REFERENCE FAIL이다", () => {
    withTempRoot((root) => {
      const meta = writeGoodFixture(root);
      write(root, "_workspace/index/call_graph.json", JSON.stringify({
        _meta: { ...meta, node_count: 1, edge_count: 1 },
        nodes: [{ id: "src.OrderService.cancel", type: "method", file: "src/OrderService.js", line: 1 }],
        edges: [{ from: "no-such-node", to: "src.OrderService.cancel", type: "call" }],
      }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.ok(result.checks.some((c) => c.code === "GRAPH_REFERENCE"), `GRAPH_REFERENCE 있어야 함: ${JSON.stringify(result.checks)}`);
    });
  });

  register("존재하지 않는 파일을 가리키는 심볼은 EVIDENCE_PATH FAIL이다", () => {
    withTempRoot((root) => {
      const meta = writeGoodFixture(root);
      write(root, "_workspace/index/symbols.json", JSON.stringify({
        _meta: meta,
        symbols: [{ id: "src.Ghost", type: "class", file: "does/not/exist.js", line: 1, package: "src" }],
      }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.ok(result.checks.some((c) => c.code === "EVIDENCE_PATH"), `EVIDENCE_PATH 있어야 함: ${JSON.stringify(result.checks)}`);
    });
  });

  register("AI 보강 edge에 file:line/evidence가 없으면 AI_EVIDENCE FAIL이다", () => {
    withTempRoot((root) => {
      const meta = writeGoodFixture(root);
      write(root, "_workspace/index/call_graph.json", JSON.stringify({
        _meta: { ...meta, node_count: 1, edge_count: 1 },
        nodes: [{ id: "src.OrderService.cancel", type: "method", file: "src/OrderService.js", line: 1 }],
        edges: [{ from: "src.OrderService.cancel", to: "src.OrderService.cancel", type: "call", origin: "ai-enrichment" }],
      }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.ok(result.checks.some((c) => c.code === "AI_EVIDENCE"), `AI_EVIDENCE 있어야 함: ${JSON.stringify(result.checks)}`);
    });
  });

  register("_meta에 선언된 인덱스가 실제로 없으면 DECLARED_INDEX FAIL이다", () => {
    withTempRoot((root) => {
      const meta = writeGoodFixture(root);
      write(root, "_workspace/index/_meta.json", JSON.stringify({ ...meta, indexes: ["symbols", "call_graph", "sql_usage"] }, null, 2));
      const result = validateHarness({ root, pluginRoot: PLUGIN_ROOT, tier: "Standard" });
      assert.ok(result.checks.some((c) => c.code === "DECLARED_INDEX"), `DECLARED_INDEX 있어야 함: ${JSON.stringify(result.checks)}`);
    });
  });
}
