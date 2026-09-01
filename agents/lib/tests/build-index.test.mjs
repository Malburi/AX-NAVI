import { mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { applyAiPatch, buildIndex } from "../build-index.mjs";
import { assessTargetCoverage } from "../adapters/registry.mjs";

function write(root, rel, content) {
  const path = join(root, rel);
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, content, "utf8");
}

function writeBytes(root, rel, buffer) {
  const path = join(root, rel);
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, buffer);
}

/* EUC-KR로 인코딩된 struts-config.xml 픽스처. 한글 주석과 속성 순서가 뒤섞인 action 3개 + 주석 처리된 action 1개. */
const EUCKR_STRUTS_HEX = "3c3f786d6c2076657273696f6e3d22312e302220656e636f64696e673d226575632d6b72223f3e0a3c7374727574732d636f6e6669673e0a20203c616374696f6e2d6d617070696e67733e0a202020203c212d2d20bcf6bfe4c1b6bbe720b8f1b7cf20c1b6c8b8202d2d3e0a202020203c616374696f6e20706174683d222f6261636b2f64656d616e642f6c6973742220747970653d22636f6d2e61636d652e44656d616e644c697374416374696f6e22206e616d653d2264656d616e64466f726d222073636f70653d2272657175657374222f3e0a202020203c212d2d20bcd3bcba20bcf8bcadb0a120b9ddb4ebc0ce20bdc7c1a620b7b9b0c5bdc320c7fcc5c2202d2d3e0a202020203c616374696f6e206e616d653d2264656d616e64466f726d2220747970653d22636f6d2e61636d652e44656d616e6453617665416374696f6e2220706174683d222f6261636b2f64656d616e642f73617665222076616c69646174653d2274727565222f3e0a202020203c212d2d207479706520bef8c0cc20666f7277617264b8b820c0d6b4c220c8adb8e920c0fcbfeb20b8c5c7ce202d2d3e0a202020203c616374696f6e20706174683d222f6261636b2f64656d616e642f68656c702220666f72776172643d222f6a73702f64656d616e642f68656c702e6a7370222f3e0a202020203c212d2d0a202020203c616374696f6e20706174683d222f6261636b2f64656d616e642f6c65676163792220747970653d22636f6d2e61636d652e44656164416374696f6e222f3e0a202020202d2d3e0a20203c2f616374696f6e2d6d617070696e67733e0a3c2f7374727574732d636f6e6669673e0a";

function json(root, name) {
  return JSON.parse(readFileSync(join(root, "_workspace", "index", name), "utf8"));
}

export async function test(register, assert) {
  register("deterministic indexer가 심볼·호출·API·SQL 인덱스를 생성한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-"));
    try {
      write(root, "_workspace/indexer-config.json", JSON.stringify({
        init_layout: "monorepo",
        workspace_mode: true,
        workspaces: [
          { id: "backend", path: "backend", kind: "backend", stack: "Spring Boot" },
          { id: "frontend", path: "frontend", kind: "frontend", stack: "TypeScript", calls_backend_api: true },
        ],
      }));
      write(root, "backend/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @Autowired private OrderService service;
  @PostMapping("/{id}/cancel")
  public void cancel() { service.cancel(); }
}
class OrderService {
  @Transactional
  public void cancel() { repository.remove(); }
}
class Repository { public void remove() {} }
`);
      write(root, "backend/OrderMapper.xml", `<mapper namespace="OrderMapper">
  <update id="cancel">UPDATE ORDERS SET STATUS='CANCEL' WHERE ID=#{id}</update>
</mapper>`);
      write(root, "frontend/api.ts", `export async function cancelOrder(id: string) {
  return fetch(\`/orders/\${id}/cancel\`, { method: "POST" });
}`);

      const first = buildIndex({ root, mode: "init", tier: "Standard", config: null });
      assert.ok(first.indexes.includes("symbols"), "symbols index");
      assert.ok(first.indexes.includes("api_contract"), "api contracts index");
      assert.ok(first.indexes.includes("sql_usage"), "sql usage index");
      assert.ok(json(root, "symbols.json").symbols.some((item) => item.id === "com.acme.OrderController"), "OrderController symbol");
      const callGraph = json(root, "call_graph.json");
      assert.ok(callGraph.edges.some((item) => item.type === "call" && item.to.endsWith("OrderService.cancel")), `service.cancel call edge: ${JSON.stringify(callGraph)}`);
      assert.equal(json(root, "api_contract.json").matches.length, 1);
      assert.equal(json(root, "sql_usage.json").sqls[0].id, "OrderMapper.cancel");
      assert.equal(json(root, "_meta.json").init_layout, "monorepo");

      /*
       * 파일별 facts 캐시는 두지 않는다(2026-08-14 폐지 유지, 2026-08-16 재실측으로 확인).
       * facts가 원본 소스보다 훨씬 커서 캐시 직렬화·파싱이 재추출보다 비쌌다 — build-index.mjs의
       * "파일 분석 워커 병렬화" 주석 참조. 계약으로 고정해 둔다: 재실행은 항상 전량 재분석한다.
       */
      const second = buildIndex({ root, mode: "incremental", tier: "Standard", config: null });
      assert.equal(second.analyzed, second.files);
      assert.equal(second.reused, 0);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("Lite도 AI 없이 기본 기계 인덱스를 생성한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-lite-"));
    try {
      write(root, "src/simple.ts", "export function hello() { return 'hello'; }\n");
      const result = buildIndex({ root, mode: "init", tier: "Lite", config: null });
      assert.ok(result.indexes.includes("symbols"));
      assert.ok(result.indexes.includes("call_graph"));
      assert.equal(json(root, "_meta.json").tier, "Lite");
      assert.equal(json(root, "_meta.json").init_layout, "single-root");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("Init Scope Gate의 include_paths 밖 소스는 읽지 않는다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-scope-"));
    try {
      write(root, "_workspace/indexer-config.json", JSON.stringify({
        init_layout: "selected-paths",
        include_paths: ["selected"],
        workspace_mode: false,
        workspaces: [{ id: "root", path: "", kind: "backend", stack: "unknown" }],
      }));
      write(root, "selected/Included.ts", "export function included() { return 1; }\n");
      write(root, "outside/Excluded.ts", "export function excluded() { return 2; }\n");
      const result = buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const symbols = json(root, "symbols.json").symbols;
      assert.equal(result.files, 1);
      assert.equal(json(root, "_meta.json").init_layout, "selected-paths");
      assert.ok(symbols.some((item) => item.file === "selected/Included.ts"));
      assert.ok(!symbols.some((item) => item.file === "outside/Excluded.ts"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("raw SQL은 완결된 SQL 문장만 추출하고 UI·HTTP·번역 문자열을 제외한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-raw-sql-"));
    try {
      write(root, "src/WebConfig.java", `registry.allowedMethods("GET", "POST", "DELETE");\n`);
      write(root, "src/ui.js", `
const css = "select-router-transition";
const action = "delete-node";
const query = "SELECT ID, STATUS FROM ORDERS WHERE ID = ?";
const mutation = 'UPDATE ORDERS SET STATUS = ? WHERE ID = ?';
`);
      write(root, "src/mock.json", JSON.stringify({ select: "select-one", delete: "Delete", update: "update:" }));
      write(root, "src/data.sql", "INSERT INTO LABELS VALUES ('Delete', 'Select');\n");
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const sqls = json(root, "sql_usage.json").sqls;
      assert.equal(sqls.map((item) => item.type).sort().join(","), "select,update");
      assert.ok(sqls.some((item) => item.tables.includes("ORDERS")));
      assert.ok(sqls.every((item) => ["select", "insert", "update", "delete", "ddl"].includes(item.type)));
      assert.ok(!sqls.some((item) => /WebConfig|mock\.json|data\.sql/.test(item.file)));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("AI 보강은 전체 JSON 재작성 없이 작은 edge patch만 병합한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-patch-"));
    try {
      write(root, "src/simple.ts", "export function first() { return 1; }\nexport function second() { return 2; }\n");
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [{ op: "add_edge", edge: { from: "src.simple.first", to: "src.simple.second", type: "call", confidence: "MEDIUM", evidence: "dynamic dispatch resolved from cited snippet" } }],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 1);
      assert.ok(json(root, "call_graph.json").edges.some((item) => item.origin === "ai-enrichment"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("AI 보강 patch는 analyzer 문서형(flat)과 중첩형을 모두 적용한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-patch-flat-"));
    try {
      write(root, "src/simple.ts", "export function first() { return 1; }\nexport function second() { return 2; }\n");
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      // agents/analyzer.md가 지시하는 평면 형태. 이전 구현은 이걸 전부 조용히 거부했다.
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [{
          op: "add_edge", from: "src.simple.first", to: "src.simple.second", type: "call",
          file: "src/simple.ts", line: 1, confidence: "HIGH", reason: "호출 인자 타입이 단일 후보를 가리킴",
        }],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 1, `flat patch 적용: ${JSON.stringify(result)}`);
      assert.equal(result.rejected, 0);
      const edge = json(root, "call_graph.json").edges.find((item) => item.origin === "ai-enrichment");
      assert.ok(edge, "ai-enrichment edge");
      assert.equal(edge.evidence, "호출 인자 타입이 단일 후보를 가리킴", "flat form의 reason이 근거로 보존된다");
      assert.equal(json(root, "_meta.json").ai_enrichment.applied, 1);
      // digest는 그래프에서 파생되므로 보강 후 값이 갱신돼야 한다.
      const digest = json(root, "_analysis_input.json").digest;
      assert.ok(digest.hubs.some((item) => item.id === "src.simple.second"), `보강된 허브 반영: ${JSON.stringify(digest.hubs)}`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("AI 보강 patch가 전부 거부되면 조용히 성공하지 않고 사유를 남긴다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-patch-reject-"));
    try {
      write(root, "src/simple.ts", "export function first() { return 1; }\n");
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "add_edge", from: "does.not.Exist", to: "src.simple.first", type: "call" },
          { op: "add_node", id: "src.simple.invented" },
          { op: "add_edge", from: "src.simple.first", to: "src.simple.first", type: "teleport" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 0);
      assert.equal(result.rejected, 3, JSON.stringify(result));
      assert.equal(result.rejected_reasons.unknown_from_node, 1);
      assert.equal(result.rejected_reasons.unsupported_op, 1);
      assert.equal(result.rejected_reasons.invalid_edge_type, 1);
      assert.ok(result.rejected_samples.length >= 3, "거부 표본 기록");
      assert.equal(json(root, "_meta.json").ai_enrichment.rejected, 3);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("AI 보강으로 API 엔드포인트·외부 통신에 설명을 추가할 수 있다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-desc-"));
    try {
      write(root, "src/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @PostMapping("/{id}/cancel")
  public void cancel() { }
}
class PaymentGatewayClient {
  RestTemplate restTemplate;
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const endpointId = json(root, "api_contract.json").endpoints[0].id;
      const commId = json(root, "external_io.json").communications[0].id;
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "set_endpoint_description", id: endpointId, description: "주문을 취소 처리한다" },
          { op: "set_communication_description", id: commId, description: "결제 게이트웨이에 취소 요청을 전달한다" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 2, JSON.stringify(result));
      assert.equal(result.rejected, 0);
      assert.equal(json(root, "api_contract.json").endpoints[0].description, "주문을 취소 처리한다");
      assert.equal(json(root, "external_io.json").communications[0].description, "결제 게이트웨이에 취소 요청을 전달한다");
      assert.equal(json(root, "_meta.json").ai_enrichment.applied, 2);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("설명 보강 오퍼레이션이 존재하지 않는 id를 가리키면 unknown_id로 거부된다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-desc-reject-"));
    try {
      write(root, "src/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @PostMapping("/{id}/cancel")
  public void cancel() { }
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [{ op: "set_endpoint_description", id: "does.not.exist", description: "존재하지 않는 엔드포인트" }],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 0);
      assert.equal(result.rejected, 1);
      assert.equal(result.rejected_reasons.unknown_id, 1, JSON.stringify(result));
      assert.equal(json(root, "api_contract.json").endpoints[0].description, undefined, "거부된 항목은 description이 안 생김");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("add_edge와 설명 보강이 섞인 패치도 서로 오염 없이 각자 적용된다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-desc-mixed-"));
    try {
      write(root, "src/simple.ts", "export function first() { return 1; }\nexport function second() { return 2; }\n");
      write(root, "src/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @PostMapping("/{id}/cancel")
  public void cancel() { }
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const endpointId = json(root, "api_contract.json").endpoints[0].id;
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "add_edge", from: "src.simple.first", to: "src.simple.second", type: "call", confidence: "MEDIUM", evidence: "동적 디스패치" },
          { op: "set_endpoint_description", id: endpointId, description: "주문을 취소 처리한다" },
          { op: "add_node", id: "src.simple.invented" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 2, JSON.stringify(result));
      assert.equal(result.rejected, 1);
      assert.equal(result.rejected_reasons.unsupported_op, 1, "add_node는 여전히 unsupported_op로 집계된다");
      assert.ok(json(root, "call_graph.json").edges.some((item) => item.origin === "ai-enrichment"), "call_graph edge 보강은 그대로 동작");
      assert.equal(json(root, "api_contract.json").endpoints[0].description, "주문을 취소 처리한다");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("set_node_note/set_edge_note로 콜 그래프 노드·엣지에 설명을 추가할 수 있다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-note-"));
    try {
      write(root, "src/simple.ts", "export function first() { return 1; }\nexport function second() { return 2; }\n");
      write(root, "src/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @Autowired private OrderService service;
  @PostMapping("/{id}/cancel")
  public void cancel() { service.cancel(); }
}
class OrderService {
  public void cancel() { }
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const graph = json(root, "call_graph.json");
      const serviceNode = graph.nodes.find((n) => n.id.endsWith("OrderService.cancel"));
      const callEdge = graph.edges.find((e) => e.type === "call" && e.to.endsWith("OrderService.cancel"));
      assert.ok(serviceNode, `OrderService.cancel 노드: ${JSON.stringify(graph.nodes)}`);
      assert.ok(callEdge, `호출 엣지: ${JSON.stringify(graph.edges)}`);
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "set_node_note", id: serviceNode.id, note: "주문 취소 업무 로직을 처리한다" },
          { op: "set_edge_note", from: callEdge.from, to: callEdge.to, type: callEdge.type, note: "취소 요청을 서비스 계층으로 위임한다" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 2, JSON.stringify(result));
      assert.equal(result.rejected, 0);
      const updated = json(root, "call_graph.json");
      assert.equal(updated.nodes.find((n) => n.id === serviceNode.id).note, "주문 취소 업무 로직을 처리한다");
      const updatedEdge = updated.edges.find((e) => e.from === callEdge.from && e.to === callEdge.to && e.type === callEdge.type);
      assert.equal(updatedEdge.note, "취소 요청을 서비스 계층으로 위임한다");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("set_node_note/set_edge_note가 존재하지 않는 대상을 가리키면 거부된다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-note-reject-"));
    try {
      write(root, "src/simple.ts", "export function first() { return 1; }\n");
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "set_node_note", id: "does.not.exist", note: "존재하지 않음" },
          { op: "set_edge_note", from: "does.not.exist", to: "src.simple.first", type: "call", note: "존재하지 않는 엣지" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 0);
      assert.equal(result.rejected, 2, JSON.stringify(result));
      assert.equal(result.rejected_reasons.unknown_id, 1);
      assert.equal(result.rejected_reasons.unknown_edge, 1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("add_edge로 새로 추가한 엣지에 같은 패치의 set_edge_note로 바로 설명을 붙일 수 있다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-note-combo-"));
    try {
      write(root, "src/simple.ts", "export function first() { return 1; }\nexport function second() { return 2; }\n");
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "add_edge", from: "src.simple.first", to: "src.simple.second", type: "call", confidence: "MEDIUM", evidence: "동적 디스패치" },
          { op: "set_edge_note", from: "src.simple.first", to: "src.simple.second", type: "call", note: "두 번째 값 계산을 위임한다" },
          { op: "set_node_note", id: "src.simple.first", note: "첫 번째 값을 계산한다" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 3, JSON.stringify(result));
      assert.equal(result.rejected, 0);
      const graph = json(root, "call_graph.json");
      const edge = graph.edges.find((e) => e.from === "src.simple.first" && e.to === "src.simple.second" && e.type === "call");
      assert.ok(edge, "add_edge로 추가된 엣지");
      assert.equal(edge.note, "두 번째 값 계산을 위임한다", "같은 패치 내에서 방금 추가한 엣지에도 note 적용됨");
      assert.equal(graph.nodes.find((n) => n.id === "src.simple.first").note, "첫 번째 값을 계산한다");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("분석 입력 팩이 허브·모듈·위험 digest를 상한과 함께 제공한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-digest-"));
    try {
      write(root, "src/main/java/com/acme/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @Autowired private OrderService service;
  @PostMapping("/{id}/cancel")
  public void cancel() { service.cancel(); }
}
class OrderService {
  @Transactional
  public void cancel() { repository.remove(); }
  public void neverCalled() {}
}
class Repository { public void remove() {} }
`);
      write(root, "src/main/resources/mapper/OrderMapper.xml", `<mapper namespace="com.acme.OrderMapper">
  <update id="cancel">UPDATE TBL_ORDER SET STATUS='CANCEL' WHERE ID=#{id}</update>
</mapper>`);
      write(root, "legacy/list.jsp", "<%@ page contentType=\"text/html\" %><script src=\"/js/list.js\"></script>");

      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const input = json(root, "_analysis_input.json");
      const digest = input.digest;
      assert.ok(digest, "digest 블록 존재");
      // 허브: 호출을 받는 심볼이 in-degree 순으로 노출된다.
      assert.ok(digest.hubs.some((item) => item.id.endsWith("OrderService.cancel")), `허브 목록: ${JSON.stringify(digest.hubs)}`);
      assert.ok(digest.hubs.every((item) => typeof item.in_degree === "number" && typeof item.out_degree === "number"));
      assert.ok(digest.entry_points.length > 0, "진입점 목록");
      assert.ok(digest.modules.some((item) => item.path.startsWith("src/main")), `모듈 목록: ${JSON.stringify(digest.modules)}`);
      assert.ok(digest.transactions.some((item) => item.marker), "트랜잭션 경계 요약");
      assert.ok(digest.sql_top_tables.some((item) => item.name === "tbl_order"), `SQL 상위 테이블: ${JSON.stringify(digest.sql_top_tables)}`);
      assert.ok(digest.endpoints.some((item) => item.method === "POST"), `엔드포인트 요약: ${JSON.stringify(digest.endpoints)}`);
      // PARTIAL 확장자를 노출해야 analyzer가 전체 재순회 없이 커버리지 구멍을 메울 수 있다.
      assert.ok(digest.partial_coverage_extensions.some((item) => item.extension === ".jsp"), `PARTIAL 노출: ${JSON.stringify(digest.partial_coverage_extensions)}`);
      // 상한과 잘린 개수를 항상 함께 기록한다.
      assert.ok(Number.isInteger(digest.hubs_truncated) && Number.isInteger(digest.modules_truncated));
      assert.ok(Number.isInteger(input.evidence.representative_files_truncated));
      assert.equal(input.analyzer_contract.digest_guided_selective_read, true);
      // Standard에서도 데드 코드 후보와 API 인덱스를 갖는다 (이전에는 Full/pair 전용이었다).
      assert.ok(digest.dead_code_candidates.some((item) => item.id.endsWith("OrderService.neverCalled")), `데드 코드 후보: ${JSON.stringify(digest.dead_code_candidates)}`);
      assert.ok(json(root, "_meta.json").indexes.includes("api_contract"), "단일 저장소도 api_contract 생성");
      assert.equal(json(root, "api_contract.json").matches.length, 0, "consumer가 없으면 매칭은 빈 배열");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("ESM/CJS 확장자(.mjs/.cjs/.mts/.cts)도 FULL로 인덱싱한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-esm-"));
    try {
      write(root, "src/service.mjs", "export function loadOrder() { return 1; }\nexport function cancelOrder() { return loadOrder(); }\n");
      write(root, "src/legacy.cjs", "function helper() { return 2; }\nmodule.exports = { helper };\n");
      write(root, "src/typed.mts", "export function typedHandler(): number { return 3; }\n");
      // TypeScript 반환 타입 주석이 있으면 예전 정규식이 함수를 통째로 놓쳤다.
      write(root, "src/typed.ts", `export async function fetchOrders(id: string): Promise<Order[]> { return []; }
export const buildLabel = (value: number): string => { return String(value); };
class OrderStore {
  save(order: Order): void { }
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const symbols = json(root, "symbols.json").symbols.map((item) => item.id);
      const graphNodes = json(root, "call_graph.json").nodes.map((item) => item.id);
      assert.ok(symbols.some((id) => id.endsWith("fetchOrders")), `async Promise 반환 타입 함수: ${JSON.stringify(symbols)}`);
      assert.ok(symbols.some((id) => id.endsWith("buildLabel")), `타입 주석 화살표 함수: ${JSON.stringify(symbols)}`);
      assert.ok(graphNodes.some((id) => id.endsWith("OrderStore.save")), `타입 주석 클래스 메서드: ${JSON.stringify(graphNodes)}`);
      // 확장자 목록이 네 곳에 중복돼 .mjs가 누락되면 ESM 프로젝트 심볼이 0건이 된다.
      assert.ok(symbols.some((id) => id.endsWith("loadOrder")), `.mjs 심볼: ${JSON.stringify(symbols)}`);
      assert.ok(symbols.some((id) => id.endsWith("helper")), `.cjs 심볼: ${JSON.stringify(symbols)}`);
      assert.ok(symbols.some((id) => id.endsWith("typedHandler")), `.mts 심볼: ${JSON.stringify(symbols)}`);
      assert.ok(json(root, "call_graph.json").edges.some((edge) => edge.to.endsWith("loadOrder")), "ESM 내부 호출 엣지");
      const coverage = json(root, "_meta.json").adapter_coverage;
      for (const ext of [".mjs", ".cjs", ".mts"]) {
        const entry = coverage.extensions.find((item) => item.extension === ext);
        assert.equal(entry?.level, "FULL", `${ext}는 FULL 커버리지여야 함: ${JSON.stringify(coverage.extensions)}`);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("대표 파일 목록 상한이 Tier에 비례한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-repfiles-"));
    try {
      for (let i = 0; i < 80; i += 1) {
        write(root, `src/mod${i}.ts`, `export function handler${i}() { return ${i}; }\n`);
      }
      buildIndex({ root, mode: "init", tier: "Lite", config: null });
      const lite = json(root, "_analysis_input.json").evidence;
      assert.ok(lite.representative_files.length <= 50, `Lite 상한 50: ${lite.representative_files.length}`);
      buildIndex({ root, mode: "init", tier: "Full", config: null });
      const full = json(root, "_analysis_input.json").evidence;
      assert.ok(full.representative_files.length > lite.representative_files.length, `Full이 더 많은 대표 파일을 준다: ${full.representative_files.length}`);
      assert.equal(full.representative_files_truncated, 0);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("미해결 관계가 200건을 넘어도 잘라내지 않고 전부 기록한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-unresolved-"));
    try {
      /* 후보 클래스 이름에 한정자(target)가 포함되게 한다 — 선언 타입을 모르는 한정자는
       * id 부분 문자열 근사 매칭으로 좁히는데(2026-08-19), 매칭 0건이면 "전부 아님"으로
       * 판정해 미해결로도 남기지 않는다. 이 테스트의 목적은 그 휴리스틱이 아니라
       * "200건 초과 시 잘라내지 않음"이므로 필터에서 살아남는 진짜 모호 케이스로 만든다. */
      const calls = Array.from({ length: 250 }, (_, i) => `  target.run(${i});`).join("\n");
      write(root, "src/ambiguous.ts", `class FirstTarget {\n  run(value: number) {}\n}\nclass SecondTarget {\n  run(value: number) {}\n}\nexport function caller(target: unknown) {\n${calls}\n}\n`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const lines = readFileSync(join(root, "_workspace", "index", "_unresolved.jsonl"), "utf8").trim().split(/\r?\n/);
      assert.equal(lines.length, 250);
      assert.equal(json(root, "_meta.json").unresolved_count, 250);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("같은 애매함이 반복되는 미해결 관계는 발생 위치가 아니라 고유 패턴으로 그룹핑된다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-unresolved-group-"));
    try {
      /* 위 "200건을 넘어도 잘라내지 않는다" 테스트와 동일한 진짜 모호 케이스를 재사용한다 —
       * target.run(...)이 250곳에서 호출되지만 전부 같은 (표현식, candidates) 조합이므로
       * 그룹은 정확히 1개여야 한다(실사용 세션에서 확인한 패턴: 발생 위치 수백~수천 건이
       * 고유 패턴 몇 개로 수렴). */
      const calls = Array.from({ length: 250 }, (_, i) => `  target.run(${i});`).join("\n");
      write(root, "src/ambiguous.ts", `class FirstTarget {\n  run(value: number) {}\n}\nclass SecondTarget {\n  run(value: number) {}\n}\nexport function caller(target: unknown) {\n${calls}\n}\n`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const groupsDoc = json(root, "_unresolved_groups.json");
      assert.equal(groupsDoc.groups.length, 1, `동일 패턴 250건이 그룹 1개로 묶여야 함: ${JSON.stringify(groupsDoc._meta)}`);
      const [group] = groupsDoc.groups;
      assert.equal(group.kind, "ambiguous_call");
      assert.equal(group.occurrence_count, 250);
      assert.equal(group.occurrences.length, 250, "그룹 상한(2000) 안이므로 occurrences를 생략하면 안 됨");
      assert.equal(groupsDoc._meta.decidable_raw_count, 250);
      assert.equal(groupsDoc._meta.total_occurrences, 250);

      const analysisInput = json(root, "_analysis_input.json");
      assert.equal(analysisInput.coverage.unresolved_decidable_count, 250, "발생 위치 기준 카운트는 그대로 유지");
      assert.equal(analysisInput.coverage.unresolved_decidable_group_count, 1, "그룹 기준 카운트가 실제 판정 횟수를 반영해야 함");
      assert.equal(analysisInput.analyzer_contract.process_all_unresolved, true);
      assert.equal(analysisInput.evidence.unresolved_groups, "_workspace/index/_unresolved_groups.json");

      const unresolvedLines = readFileSync(join(root, "_workspace", "index", "_unresolved.jsonl"), "utf8").trim().split(/\r?\n/).map((line) => JSON.parse(line));
      assert.equal(unresolvedLines.length, 250, "_unresolved.jsonl 감사 원본은 발생 위치 수만큼 그대로 유지");
      assert.ok(unresolvedLines.every((item) => item.group_id === group.group_id), "모든 발생 위치가 같은 group_id를 가리켜야 함");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("서로 다른 애매함 패턴은 별개 그룹으로 나뉜다 (회귀 가드)", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-unresolved-group-distinct-"));
    try {
      write(root, "src/ambiguous.ts", `
class FirstTarget { run(value: number) {} read(value: number) {} }
class SecondTarget { run(value: number) {} read(value: number) {} }
export function caller(target: unknown) {
  target.run(1);
  target.run(2);
  target.read(1);
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const groupsDoc = json(root, "_unresolved_groups.json");
      assert.equal(groupsDoc.groups.length, 2, `run(...)/read(...)는 서로 다른 패턴이라 그룹도 2개여야 함: ${JSON.stringify(groupsDoc.groups.map((g) => g.key_field))}`);
      const runGroup = groupsDoc.groups.find((g) => g.key_field.startsWith("run"));
      const readGroup = groupsDoc.groups.find((g) => g.key_field.startsWith("read"));
      assert.equal(runGroup?.occurrence_count, 2);
      assert.equal(readGroup?.occurrence_count, 1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("DDL FK·인덱스와 MyBatis JOIN 관계·mapper 사용처를 결정적으로 전수 추출한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-db-relations-"));
    try {
      write(root, "src/main/java/com/acme/OrderMapper.java", `package com.acme;
public interface OrderMapper {
  void findOrders();
  void findTenantOrders();
}
`);
      write(root, "src/main/resources/mapper/OrderMapper.xml", `<mapper namespace="com.acme.OrderMapper">
  <select id="findOrders">
    SELECT O.ORDER_ID, U.USER_NAME
      FROM TBL_ORDER O
      JOIN TBL_USER U ON O.USER_ID = U.USER_ID
  </select>
  <select id="findTenantOrders">
    SELECT O.ORDER_ID
      FROM TBL_ORDER O, TBL_TENANT T
     WHERE O.TENANT_ID = T.TENANT_ID
  </select>
</mapper>`);
      write(root, "src/main/resources/schema.sql", `CREATE TABLE TBL_USER (
  USER_ID VARCHAR(20) PRIMARY KEY,
  USER_NAME VARCHAR(100)
);
CREATE TABLE TBL_TENANT (
  TENANT_ID VARCHAR(20) PRIMARY KEY
);
CREATE TABLE TBL_ORDER (
  ORDER_ID VARCHAR(20) PRIMARY KEY,
  USER_ID VARCHAR(20),
  TENANT_ID VARCHAR(20),
  CONSTRAINT FK_ORDER_USER FOREIGN KEY (USER_ID) REFERENCES TBL_USER (USER_ID)
);
CREATE UNIQUE INDEX IF NOT EXISTS IDX_ORDER_USER ON TBL_ORDER (USER_ID);
`);

      buildIndex({ root, mode: "init", tier: "Full", config: null });
      const schema = json(root, "schema.json");
      const sqlUsage = json(root, "sql_usage.json");
      const order = schema.tables.find((table) => table.name === "TBL_ORDER");
      assert.ok(order.foreign_keys.some((fk) => fk.name === "FK_ORDER_USER" && fk.references_table === "TBL_USER"), JSON.stringify(order));
      assert.ok(order.indexes.some((index) => index.name === "IDX_ORDER_USER" && index.unique === true), JSON.stringify(order));
      assert.ok(schema.relations.some((relation) => relation.type === "foreign_key" && relation.from_table === "TBL_ORDER" && relation.to_table === "TBL_USER"), JSON.stringify(schema.relations));
      assert.ok(schema.relations.some((relation) => relation.type === "query_join" && relation.from_table === "TBL_ORDER" && relation.to_table === "TBL_USER"), JSON.stringify(schema.relations));
      assert.ok(schema.relations.some((relation) => relation.type === "query_join" && [relation.from_table, relation.to_table].includes("TBL_TENANT")), JSON.stringify(schema.relations));
      assert.ok(sqlUsage.usages.some((usage) => usage.method === "com.acme.OrderMapper.findOrders" && usage.confidence === "HIGH"), JSON.stringify(sqlUsage.usages));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("ASP.NET Core의 controller route·생성자 DI·트랜잭션 경계를 추출한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-dotnet-"));
    try {
      write(root, "Controllers/OrdersController.cs", `using Microsoft.AspNetCore.Mvc;
[Route("api/[controller]")]
public class OrdersController : ControllerBase {
  private readonly OrderService service;
  public OrdersController(OrderService service) { this.service = service; }
  [HttpPost("{id}/cancel")]
  public void Cancel(int id) { using var tx = new TransactionScope(); service.Cancel(id); }
}
public class OrderService { public void Cancel(int id) {} }
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const api = json(root, "api_contract.json");
      const graph = json(root, "call_graph.json");
      assert.ok(api.endpoints.some((item) => item.path_pattern === "/api/Orders/{param}/cancel"), JSON.stringify(api.endpoints));
      assert.ok(graph.edges.some((item) => item.type === "inject" && item.to.endsWith("OrderService")), JSON.stringify(graph.edges));
      assert.ok(json(root, "transactions.json").boundaries.some((item) => item.entry_method.endsWith("OrdersController.Cancel")));
      assert.ok(json(root, "_meta.json").adapter_coverage.active_adapters.some((item) => item.id === "aspnet-core"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("WinForms designer의 정규화된 delegate와 React JSX 이벤트를 handler에 연결한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-ui-events-"));
    try {
      write(root, "Desktop/MainForm.Designer.cs", `using System.Windows.Forms;
public partial class MainForm : Form {
  public void InitializeComponent() { this.btnSave.Click += new System.EventHandler(this.btnSave_Click); }
  private void btnSave_Click(object sender, System.EventArgs e) { Save(); }
  private void Save() {}
}`);
      write(root, "Web/Order.tsx", `export function saveOrder() { return 1; }
export function Order() { return <button onClick={saveOrder}>Save</button>; }
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const edges = json(root, "call_graph.json").edges;
      assert.ok(edges.some((item) => item.type === "ui_event" && item.to.endsWith("MainForm.btnSave_Click")), JSON.stringify(edges));
      assert.ok(edges.some((item) => item.type === "ui_event" && item.to.endsWith("saveOrder")), JSON.stringify(edges));
      const coverage = json(root, "_meta.json").adapter_coverage;
      assert.equal(assessTargetCoverage(coverage, "Desktop/MainForm.Designer.cs").decision, "HOLD", "generated Designer는 수동 UI 검증 전 HOLD");
      assert.equal(coverage.full_files + coverage.partial_files, 2, "파일별 coverage 합계가 중복되지 않음");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("Nexacro XFDL의 화면·Dataset·이벤트·transaction과 API 소비처를 인덱싱한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-nexacro-"));
    try {
      write(root, "forms/Order.xfdl", `<FDL><Form id="OrderForm" titletext="Order" onload="form_onload">
<Dataset id="dsOrder"><ColumnInfo><Column id="ORDER_ID" type="STRING"/></ColumnInfo></Dataset>
<Button id="btnSave" onclick="btnSave_onclick"/>
<Script><![CDATA[
this.form_onload = function(obj,e) {};
this.btnSave_onclick = function(obj,e) { this.transaction("saveOrder", "svc::/orders/save.do", "in=dsOrder:U", "out=dsResult", "", "fnCallback"); };
this.fnCallback = function(svcId,errCode,errMsg) {};
]]></Script></Form></FDL>`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const flow = json(root, "ui_flow.json");
      assert.equal(flow.screens[0].id, "OrderForm");
      assert.ok(flow.datasets.some((item) => item.id === "dsOrder" && item.columns.some((column) => column.name === "ORDER_ID")), JSON.stringify(flow.datasets));
      assert.ok(flow.events.some((item) => item.handler === "btnSave_onclick"));
      assert.ok(flow.transactions.some((item) => item.service_id === "saveOrder" && item.callback === "fnCallback"));
      assert.ok(json(root, "api_contract.json").consumers.some((item) => item.call_type === "nexacro-transaction" && item.path_pattern === "/orders/save.do"));
      assert.ok(json(root, "call_graph.json").edges.some((item) => item.type === "ui_event" && item.to.endsWith("btnSave_onclick")), "XFDL event→Script handler 연결");
      const target = assessTargetCoverage(json(root, "_meta.json").adapter_coverage, "forms/Order.xfdl");
      assert.equal(target.decision, "HOLD", "XFDL 부분 해석은 수동 검증 전 HOLD");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  /*
   * 2026-08-15 실사고 회귀 — EUC-KR로 저장된 레거시 Struts 설정.
   * 전부 UTF-8로 읽던 시절에는 한글 주석이 U+FFFD로 깨졌고, path 뒤에 type이 오는 한 줄짜리
   * action만 잡혀 나머지 매핑이 통째로 누락됐다.
   */
  register("EUC-KR 레거시 설정을 선언 인코딩으로 읽고 순서 무관하게 action을 추출한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-euckr-"));
    try {
      writeBytes(root, "WEB-INF/config/struts-config.xml", Buffer.from(EUCKR_STRUTS_HEX, "hex"));
      /* 같은 트리의 UTF-8 파일은 그대로 UTF-8로 읽혀야 한다 — 레거시 폴백이 번지면 안 된다. */
      write(root, "src/DemandService.java", `package com.acme;
class DemandService { public void save() { /* 수요조사 저장 */ } }
`);
      /* euc-kr이라 선언했지만 실제로는 UTF-8로 저장된 파일 — 선언보다 바이트가 우선이다. */
      write(root, "WEB-INF/config/mislabeled.xml", `<?xml version="1.0" encoding="euc-kr"?>
<root><note>실제로는 UTF-8로 저장된 설정</note></root>
`);

      buildIndex({ root, mode: "init", tier: "Standard", config: null });

      const meta = json(root, "_meta.json");
      assert.equal(meta.encoding.by_encoding["euc-kr"], 1, JSON.stringify(meta.encoding));
      assert.ok(meta.encoding.declared_non_utf8.includes("WEB-INF/config/struts-config.xml"), "EUC-KR 파일이 기록되지 않음");
      assert.equal(meta.encoding.guessed_count, 0, "선언이 있는데 추측으로 읽음");

      const paths = json(root, "api_contract.json").endpoints.map((item) => item.path);
      assert.ok(paths.includes("/back/demand/list"), `path 우선 순서: ${paths}`);
      assert.ok(paths.includes("/back/demand/save"), `type 우선 순서: ${paths}`);
      assert.ok(paths.includes("/back/demand/help"), `forward 전용: ${paths}`);
      assert.ok(!paths.includes("/back/demand/legacy"), "주석 처리된 action을 살아 있는 매핑으로 셈");

      /* 인덱스 어디에도 U+FFFD가 남으면 안 된다 — 이게 이 회귀의 본체다. */
      for (const name of readdirSync(join(root, "_workspace", "index"))) {
        const raw = readFileSync(join(root, "_workspace", "index", name), "utf8");
        assert.ok(!raw.includes("�"), `${name}에 깨진 문자가 남음`);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  /*
   * 2026-08-16 실사고 회귀 — 벤더/미니파이 JS를 업무 코드로 세던 문제.
   * xu25-client에서 ckeditor·fck_editor·jquery-ui가 전부 인덱싱돼 노드 34,674개 중 80%가
   * 고아가 되고 dead_code 31,572건이 거짓양성으로 나왔다.
   */
  register("벤더 경로·미니파이 파일을 인덱스에서 제외하고 사유를 기록한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-vendor-"));
    try {
      // 1) 경로로 잡히는 벤더 (node_modules 관행을 안 쓰는 레거시 배치)
      write(root, "html/ckeditor/ckeditor.js", "function editorInit(){ return 1; } ".repeat(80));
      // 2) 파일명으로 잡히는 벤더
      write(root, "html/script/app.min.js", "function bundled(){ return 2; } ".repeat(80));
      // 3) 이름·경로로는 못 잡고 내용으로만 잡히는 미니파이 번들 (한 줄 48KB)
      write(root, "html/script/custom.js", "var a=1;".repeat(6000));
      // 4) 버전이 박힌 배포본
      write(root, "html/script/jquery-1.5.2.js", "function legacyLib(){ return 3; } ".repeat(80));
      // 5) 라이브러리 이름을 접두사로 쓴 *업무* 파일 — 잘리면 안 된다.
      //    실측(2026-08-16)에서 jquery.add.js가 실제로는 배너 슬라이더 업무 코드였다.
      write(root, "html/script/js/jquery.add.js", `function startBanner(){ return rotateBanner(); }
function rotateBanner(){ return true; }
`);
      // 6) 진짜 업무 코드 — 절대 빠지면 안 된다
      write(root, "html/script/order.js", `function submitOrder(){ return validateOrder(); }
function validateOrder(){ return true; }
`);

      buildIndex({ root, mode: "init", tier: "Standard", config: null });

      const excluded = json(root, "_meta.json").excluded_sources;
      assert.equal(excluded.count, 4, JSON.stringify(excluded));
      assert.equal(excluded.by_reason["vendor-versioned"], 1, JSON.stringify(excluded.by_reason));
      assert.ok(!excluded.files.some((f) => f.includes("jquery.add.js")), `업무 파일이 벤더로 오탐: ${excluded.files}`);
      assert.equal(excluded.by_reason["vendor-path"], 1, JSON.stringify(excluded.by_reason));
      assert.equal(excluded.by_reason["vendor-filename"], 1, JSON.stringify(excluded.by_reason));
      assert.equal(excluded.by_reason["minified"], 1, JSON.stringify(excluded.by_reason));
      assert.ok(excluded.files.some((f) => f.startsWith("html/ckeditor/ckeditor.js")), JSON.stringify(excluded.files));

      const ids = json(root, "symbols.json").symbols.map((item) => item.id);
      assert.ok(ids.some((id) => id.includes("submitOrder")), "업무 코드가 인덱싱되지 않음");
      assert.ok(!ids.some((id) => id.includes("editorInit")), "벤더 경로가 인덱싱됨");
      assert.ok(!ids.some((id) => id.includes("bundled")), "min.js가 인덱싱됨");
      assert.ok(!ids.some((id) => id.includes("legacyLib")), "버전 박힌 배포본이 인덱싱됨");
      assert.ok(ids.some((id) => id.includes("startBanner")), "라이브러리 이름을 쓴 업무 파일이 제외됨");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  /*
   * 테스트 파일이 업무 코드와 동일하게 전량 인덱싱돼 call_graph.json을 부풀리던 문제(2026 조사).
   * 벤더 필터와 같은 원칙 — 디렉터리는 세그먼트 완전 일치, 파일명은 빌드 도구 강제 규약만.
   */
  register("테스트 파일·디렉터리를 인덱스에서 제외하고 사유를 기록한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-test-"));
    try {
      // 1) Maven/Gradle 표준 레이아웃 — 디렉터리 세그먼트로 잡힘
      write(root, "src/test/java/com/foo/OrderServiceTest.java", `class OrderServiceTest { void checkOrder(){ verifyOrder(); } void verifyOrder(){} }`);
      // 2) JS/TS 파일명 규약
      write(root, "src/order/OrderService.test.ts", `function testOrder(){ return assertOrder(); }
function assertOrder(){ return true; }`);
      // 3) Go 툴체인 강제 규약
      write(root, "pkg/order/order_test.go", `func TestOrder(t *testing.T) { checkOrder() }
func checkOrder() {}`);
      // 4) pytest 관행 (test_ 접두사) — 디렉터리로도 잡히는 경우
      write(root, "app/tests/test_order.py", `def test_order():
    return validate_test_order()
def validate_test_order():
    return True`);
      // 5) 세그먼트 이름이 다른 업무 폴더 — 잘리면 안 된다 (벤더의 jquery.add.js와 같은 자리)
      write(root, "src/main/java/com/foo/abtest/AbTestService.java", `class AbTestService { void runVariant(){ pickBucket(); } void pickBucket(){} }`);
      // 6) 파일명이 "Test"로 시작하지 않고 우연히 포함만 하는 업무 파일 — 잘리면 안 된다
      write(root, "src/main/java/com/foo/Testimony.java", `class Testimony { void record(){ persist(); } void persist(){} }`);
      // 7) 진짜 업무 코드 — 절대 빠지면 안 된다
      write(root, "src/main/java/com/foo/OrderService.java", `class OrderService { void submitOrder(){ validateOrder(); } void validateOrder(){} }`);

      buildIndex({ root, mode: "init", tier: "Standard", config: null });

      const excluded = json(root, "_meta.json").excluded_sources;
      assert.equal(excluded.by_reason["test-path"], 2, JSON.stringify(excluded.by_reason)); // src/test/java, app/tests
      assert.equal(excluded.by_reason["test-filename"], 2, JSON.stringify(excluded.by_reason)); // .test.ts, _test.go
      assert.ok(!excluded.files.some((f) => f.includes("AbTestService")), `업무 파일이 테스트로 오탐: ${excluded.files}`);
      assert.ok(!excluded.files.some((f) => f.includes("Testimony")), `업무 파일이 테스트로 오탐: ${excluded.files}`);

      // 클래스 메서드는 symbols.json 최상위가 아니라 class.methods[]에 중첩되므로(owner 있는 메서드),
      // 노드 유무는 call_graph.json(클래스+메서드를 owner 무관 전부 평탄화)으로 확인한다.
      const ids = json(root, "call_graph.json").nodes.map((item) => item.id);
      assert.ok(ids.some((id) => id.includes("submitOrder")), "업무 코드가 인덱싱되지 않음");
      assert.ok(ids.some((id) => id.includes("pickBucket")), "abtest 업무 폴더가 테스트로 오탐돼 제외됨");
      assert.ok(ids.some((id) => id.includes("persist")), "Testimony 업무 파일이 테스트로 오탐돼 제외됨");
      assert.ok(!ids.some((id) => id.includes("checkOrder")), "Maven 표준 테스트 경로가 인덱싱됨");
      assert.ok(!ids.some((id) => id.includes("testOrder")), "*.test.ts가 인덱싱됨");
      assert.ok(!ids.some((id) => id.includes("TestOrder")), "Go _test.go가 인덱싱됨");
      assert.ok(!ids.some((id) => id.includes("test_order") || id.includes("validate_test_order")), "pytest tests/ 디렉터리가 인덱싱됨");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("test_exclude: false면 테스트 파일 제외를 끌 수 있다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-test-optout-"));
    try {
      write(root, "src/test/java/com/foo/OrderServiceTest.java", `class OrderServiceTest { void checkOrder(){} }`);
      // loadConfig()는 config를 파일 경로로만 받는다(_workspace/indexer-config.json 기본값) — 객체 직접 전달 불가.
      write(root, "_workspace/indexer-config.json", JSON.stringify({ test_exclude: false }));

      buildIndex({ root, mode: "init", tier: "Standard", config: null });

      const excluded = json(root, "_meta.json").excluded_sources;
      assert.equal(excluded.by_reason["test-path"] || 0, 0, JSON.stringify(excluded.by_reason));

      const ids = json(root, "call_graph.json").nodes.map((item) => item.id);
      assert.ok(ids.some((id) => id.includes("checkOrder")), "test_exclude: false인데도 제외됨");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  /*
   * 2026-08-16 실사고 회귀 — DDL이 없는 레거시(.sql 0개, 쿼리는 전부 XML)에서 schema.json이
   * tables=0으로 비던 문제. sql_usage에는 이미 테이블명이 들어 있으므로 그것을 집계한다.
   */
  register("DDL이 없으면 sql_usage에서 스키마를 유도하고 의사테이블을 걸러낸다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-derived-"));
    try {
      write(root, "WEB-INF/config/query/query-course.xml", `<mapper namespace="Course">
  <select id="list">SELECT Z.* FROM( SELECT ROWNUM RO, A.* FROM( SELECT CRS_NO FROM TB_LS_CRS A, TB_LS_CRS_SESS B ) A ) Z</select>
  <select id="count">SELECT COUNT(*) FROM TB_LS_CRS</select>
  <select id="now">SELECT SYSDATE FROM DUAL</select>
</mapper>`);

      buildIndex({ root, mode: "init", tier: "Standard", config: null });

      const sqlUsage = json(root, "sql_usage.json");
      const allTables = sqlUsage.sqls.flatMap((item) => item.tables);
      assert.ok(!allTables.some((n) => /^(rownum|dual|sysdate)$/i.test(n)), `의사테이블이 남음: ${allTables}`);

      const schema = json(root, "schema.json");
      assert.equal(schema._meta.source, "derived-from-sql", JSON.stringify(schema._meta));
      const names = schema.tables.map((item) => item.name.toUpperCase());
      assert.ok(names.includes("TB_LS_CRS"), JSON.stringify(names));
      assert.ok(names.includes("TB_LS_CRS_SESS"), JSON.stringify(names));
      const crs = schema.tables.find((item) => item.name.toUpperCase() === "TB_LS_CRS");
      assert.equal(crs.origin, "derived-from-sql");
      assert.equal(crs.confidence, "MEDIUM");
      assert.ok(crs.usage_count >= 2, `usage_count=${crs.usage_count}`);
      assert.ok(Array.isArray(crs.columns) && crs.columns.length === 0, "DDL 없이 컬럼을 지어냄");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("등록되지 않은 확장자는 변경 안전 게이트가 HOLD한다", () => {
    const result = assessTargetCoverage({ extensions: [], unsupported_files: [] }, "legacy/Screen.unknown");
    assert.equal(result.decision, "HOLD");
    assert.equal(result.level, "UNSUPPORTED");
  });

  register("애너테이션이 아니라 실제 메서드를 심볼로 잡는다 (Spring MVC 컨트롤러)", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-anno-"));
    try {
      write(root, "src/OrderController.java", `package kr.co.demo;
@Controller
@RequestMapping("/order")
public class OrderController {
  @Autowired private OrderService orderService;

  @GetMapping("/list")
  public String list(SearchVO vo, Model model) {
    return "order/list";
  }

  @PostMapping("/save")
  public String save(@RequestParam("id") String id, OrderVO vo) {
    orderService.save(vo);
    return "redirect:/order/list";
  }
}
class OrderService { public void save(OrderVO vo) {} }
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const ids = json(root, "call_graph.json").nodes.map((item) => item.id);
      /*
       * `[^;{}]*`가 개행과 괄호를 가리지 않아 `@GetMapping("/list")⏎ public String list(...)` 전체를
       * 하나의 인자 목록으로 삼켰고, 애너테이션 이름이 메서드가 되고 진짜 메서드는 사라졌다.
       * Spring MVC 컨트롤러가 전부 이 형태라 요청 진입점이 통째로 인덱스에서 빠졌다.
       */
      assert.ok(ids.some((id) => id.endsWith("OrderController.list")), `list 메서드: ${JSON.stringify(ids)}`);
      assert.ok(ids.some((id) => id.endsWith("OrderController.save")), `save 메서드: ${JSON.stringify(ids)}`);
      assert.ok(!ids.some((id) => /\.(GetMapping|PostMapping|Controller|RequestMapping|Autowired)$/.test(id)), `애너테이션이 메서드로 잡힘: ${JSON.stringify(ids)}`);
      /* 파라미터 애너테이션(@RequestParam("id"))이 있어도 정상 인식돼야 한다. */
      const endpoints = json(root, "api_contract.json").endpoints.map((item) => `${item.method} ${item.path_pattern}`);
      assert.ok(endpoints.includes("POST /order/save"), `엔드포인트: ${JSON.stringify(endpoints)}`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("try-with-resources를 메서드로 잡지 않는다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-try-"));
    try {
      write(root, "src/LogUtil.java", `package kr.co.demo;
public class LogUtil {
  public void write(String job) {
    try (FileOutputStream fos = new FileOutputStream("/logs/app.log", true)) {
      fos.write(job.getBytes());
    } catch (Exception e) { }
  }
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const ids = json(root, "call_graph.json").nodes.map((item) => item.id);
      assert.ok(ids.some((id) => id.endsWith("LogUtil.write")), `write 메서드: ${JSON.stringify(ids)}`);
      assert.ok(!ids.some((id) => id.endsWith(".try")), `try가 메서드로 잡힘: ${JSON.stringify(ids)}`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("이름 붙은 제약과 ALTER TABLE로 건 PK·FK를 읽는다 (오라클 레거시 DDL)", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-ddl-"));
    try {
      write(root, "db/schema.sql", `CREATE TABLE TB_ORDER (
  ID     VARCHAR2(20) NOT NULL,
  MEM_ID VARCHAR2(20),
  CONSTRAINT PK_TB_ORDER PRIMARY KEY (ID)
);
CREATE TABLE TB_MEMBER (
  MEM_ID VARCHAR2(20) NOT NULL,
  NM     VARCHAR2(200)
);
ALTER TABLE TB_MEMBER ADD CONSTRAINT PK_TB_MEMBER PRIMARY KEY (MEM_ID);
ALTER TABLE TB_ORDER ADD CONSTRAINT FK_ORDER_MEM FOREIGN KEY (MEM_ID) REFERENCES TB_MEMBER (MEM_ID);
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const tables = json(root, "schema.json").tables;
      const order = tables.find((item) => item.name === "TB_ORDER");
      const member = tables.find((item) => item.name === "TB_MEMBER");
      /* `CONSTRAINT ... PRIMARY KEY (...)`가 스킵 규칙에 걸려 PK가 통째로 버려지고 있었다. */
      assert.equal(JSON.stringify(order.primary_key), JSON.stringify(["ID"]), "이름 붙은 PK 제약");
      /* ALTER TABLE로 뒤에 거는 형태는 아예 읽지 않았다 — 레거시 DDL에서 매우 흔하다. */
      assert.equal(JSON.stringify(member.primary_key), JSON.stringify(["MEM_ID"]), "ALTER TABLE PK");
      assert.equal(order.foreign_keys.length, 1, `ALTER TABLE FK: ${JSON.stringify(order.foreign_keys)}`);
      assert.equal(order.foreign_keys[0].references_table, "TB_MEMBER");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("엔드포인트 핸들러는 데드 코드 후보에서 제외한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-dead-"));
    try {
      write(root, "src/OrderController.java", `package kr.co.demo;
@Controller
@RequestMapping("/order")
public class OrderController {
  @GetMapping("/list")
  public String list(SearchVO vo) { return "list"; }
}
`);
      write(root, "src/Unused.java", `package kr.co.demo;
public class Unused {
  public void neverCalled() { }
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const dead = json(root, "dead_code.json").unused_methods.map((item) => item.id);
      /*
       * endpoint.handler는 전체 id인데 조회는 마지막 segment로 해서 제외가 한 번도 동작하지 않았다.
       * HTTP 진입점은 정의상 in-degree 0이라 컨트롤러 메서드가 전부 데드 코드로 올라왔다.
       */
      assert.ok(!dead.some((id) => id.endsWith("OrderController.list")), `엔드포인트 핸들러가 데드로 분류됨: ${JSON.stringify(dead)}`);
      assert.ok(dead.some((id) => id.endsWith("Unused.neverCalled")), `진짜 미사용은 남아야 함: ${JSON.stringify(dead)}`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("한정자를 선언 타입으로 해석해 프레임워크 호출을 LLM 판정에 넘기지 않는다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-qual-"));
    try {
      /* 같은 이름의 메서드를 가진 Dao가 여럿 = 이름만으로는 모호한 상황 */
      for (const mod of ["order", "member", "settle"]) {
        const Mod = mod[0].toUpperCase() + mod.slice(1);
        write(root, `src/${Mod}Dao.java`, `package kr.co.demo;
import org.mybatis.spring.SqlSessionTemplate;
public class ${Mod}Dao {
  @Autowired private SqlSessionTemplate sqlSession;
  public void insert(Object vo) { sqlSession.insert("${mod}.insert", vo); }
}
`);
      }
      write(root, "src/OrderService.java", `package kr.co.demo;
public class OrderService {
  @Autowired private OrderDao repo;
  public void save(Object vo) { repo.insert(vo); }
}
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const unresolvedRaw = readFileSync(join(root, "_workspace", "index", "_unresolved.jsonl"), "utf8").trim();
      const unresolved = unresolvedRaw ? unresolvedRaw.split("\n").map((line) => JSON.parse(line)) : [];
      const decidable = unresolved.filter((item) => !item.no_candidates && !item.candidates_omitted);
      /*
       * `sqlSession`은 SqlSessionTemplate(인덱스에 없는 프레임워크 타입)이므로 외부 호출이다.
       * 예전에는 한정자가 어느 후보와도 겹치지 않아 후보 전체(전부 오답)를 판정 대기열에 넣었고,
       * analyzer가 파일을 열어봐도 목록에 정답이 없어 판정 자체가 성립하지 않았다.
       */
      assert.equal(decidable.length, 0, `프레임워크 호출이 판정 대기열에 남음: ${JSON.stringify(decidable.map((item) => item.expression))}`);

      /* 반면 필드 타입이 인덱스에 있으면 이름이 안 겹쳐도(repo ≠ OrderDao) 정확히 해석돼야 한다. */
      const edges = json(root, "call_graph.json").edges;
      assert.ok(
        edges.some((item) => item.from.endsWith("OrderService.save") && item.to.endsWith("OrderDao.insert")),
        `필드 타입 기반 해석 실패: ${JSON.stringify(edges.filter((e) => e.type === "call").map((e) => `${e.from}->${e.to}`))}`,
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("상속 관계 해석 시 implements는 interface만, extends는 interface를 제외한 후보만 대상으로 삼는다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-inherit-type-"));
    try {
      /* 이름이 겹치는 interface와 class를 각각 다른 패키지에 둔다 — 이름만으로는 모호하지만
       * implements/extends의 문법상 대상 종류가 다르므로 타입으로 결정론적으로 갈라야 한다. */
      write(root, "src/pkg/a/Repository.java", `package pkg.a;
public interface Repository { void save(); }
`);
      write(root, "src/pkg/b/Repository.java", `package pkg.b;
public class Repository { public void save() {} }
`);
      write(root, "src/pkg/c/OrderRepository.java", `package pkg.c;
public class OrderRepository implements Repository { public void save() {} }
`);
      write(root, "src/pkg/d/ExtendedRepo.java", `package pkg.d;
public class ExtendedRepo extends Repository { }
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const edges = json(root, "call_graph.json").edges.filter((item) => item.type === "inherit");
      assert.ok(
        edges.some((item) => item.from === "pkg.c.OrderRepository" && item.to === "pkg.a.Repository"),
        `implements가 interface 후보로 해석되지 않음: ${JSON.stringify(edges)}`,
      );
      assert.ok(
        edges.some((item) => item.from === "pkg.d.ExtendedRepo" && item.to === "pkg.b.Repository"),
        `extends가 class 후보로 해석되지 않음: ${JSON.stringify(edges)}`,
      );
      const unresolvedRaw = readFileSync(join(root, "_workspace", "index", "_unresolved.jsonl"), "utf8").trim();
      const unresolved = unresolvedRaw ? unresolvedRaw.split("\n").map((line) => JSON.parse(line)) : [];
      const ambiguousInherit = unresolved.filter((item) => item.kind === "ambiguous_inherit");
      assert.equal(ambiguousInherit.length, 0, `타입으로 갈릴 수 있는데도 미해결로 남음: ${JSON.stringify(ambiguousInherit)}`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("같은 타입끼리 진짜로 이름이 겹치는 상속은 여전히 ambiguous_inherit로 남는다 (회귀 가드)", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-inherit-collide-"));
    try {
      write(root, "src/pkg/e/Base.java", `package pkg.e;
public class Base { }
`);
      write(root, "src/pkg/f/Base.java", `package pkg.f;
public class Base { }
`);
      write(root, "src/pkg/g/Derived.java", `package pkg.g;
public class Derived extends Base { }
`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const unresolvedRaw = readFileSync(join(root, "_workspace", "index", "_unresolved.jsonl"), "utf8").trim();
      const unresolved = unresolvedRaw ? unresolvedRaw.split("\n").map((line) => JSON.parse(line)) : [];
      const ambiguousInherit = unresolved.filter((item) => item.kind === "ambiguous_inherit" && item.from === "pkg.g.Derived");
      assert.equal(ambiguousInherit.length, 1, `진짜 동종 충돌인데 타입 필터가 과하게 해소해버림: ${JSON.stringify(unresolved)}`);
      assert.equal(ambiguousInherit[0].candidates.length, 2);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("대표 파일 목록은 개수가 아니라 바이트 예산으로 제한한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-repbudget-"));
    try {
      /* 컨벤션을 담은 평범한 파일 여러 개 + 생성물처럼 거대한 파일 하나 */
      for (let i = 0; i < 12; i += 1) {
        write(root, `src/Svc${i}.java`, `package kr.co.demo;\npublic class Svc${i} { public void run${i}() { helper${i}(); } }\n`);
      }
      const huge = `package kr.co.demo;\npublic class Generated {\n${"  public void m() { x(); }\n".repeat(20000)}}\n`;
      write(root, "src/Generated.java", huge);
      buildIndex({ root, mode: "init", tier: "Full", config: null });
      const evidence = json(root, "_analysis_input.json").evidence;
      /*
       * 개수 상한(Full=300)만 있던 시절에는 거대 파일이 "1개"로 세어져 그대로 목록에 들어갔고,
       * 실측 픽스처에서 대표 파일 300개가 24.5MB(약 21M 토큰)까지 갔다.
       */
      assert.ok(!evidence.representative_files.includes("src/Generated.java"), "개별 상한을 넘는 파일은 대표에서 제외돼야 함");
      assert.ok(evidence.representative_files.length >= 5, `평범한 파일은 남아야 함: ${evidence.representative_files.length}`);
      assert.ok(evidence.representative_files_bytes > 0, "열람 비용을 알려줘야 함");
      assert.ok(evidence.representative_files_bytes < 1536 * 1024, `Full 바이트 예산 초과: ${evidence.representative_files_bytes}`);
      assert.equal(evidence.representative_files_skipped.oversized, 1, "제외 사유가 집계돼야 함");
      assert.equal(json(root, "_analysis_input.json").analyzer_contract.representative_read_budget_bytes, 1536 * 1024);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("Legacy Static JS 탐지 시 client_index.json을 JS↔JSP 매핑과 함께 결정론적으로 생성한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-clientindex-"));
    try {
      /* JS 100개 이상이 back/education 아래 집중, 번들러 매니페스트 없음 = analyzer.md Step 5의 탐지 조건. */
      for (let i = 0; i < 105; i += 1) {
        write(root, `back/education/course/module${i}.js`, `function onInit${i}() {}\nfunction onSaveData${i}() { $.ajax({url: "/save"}); }\n`);
      }
      write(root, "front/course/crsInfoHandle.jsp", `<html><script src="/back/education/course/module0.js"></script>
<script src="/lib/jquery-1.11.1.min.js"></script></html>`);
      const first = buildIndex({ root, mode: "init", tier: "Standard", config: null });
      assert.ok(first.indexes.includes("client_index"), `client_index가 생성돼야 함: ${JSON.stringify(first.indexes)}`);
      const clientIndex = json(root, "client_index.json");
      assert.equal(clientIndex.type, "LegacyStaticJS");
      assert.equal(clientIndex.build_tool, null);
      assert.equal(clientIndex.js_count, 105);
      assert.ok(clientIndex.domain_structure.back?.includes("education/course"), JSON.stringify(clientIndex.domain_structure));
      const mapping = clientIndex.sample_mappings.find((item) => item.js === "back/education/course/module0.js");
      assert.ok(mapping, `module0.js 매핑이 있어야 함: ${JSON.stringify(clientIndex.sample_mappings.slice(0, 3))}`);
      assert.equal(JSON.stringify(mapping.jsps), JSON.stringify(["front/course/crsInfoHandle.jsp"]));
      assert.equal(JSON.stringify(mapping.functions), JSON.stringify(["onInit0", "onSaveData0"]));
      assert.equal(JSON.stringify(clientIndex.jquery_versions), JSON.stringify(["jquery@1.11.1"]));
      /* 판단이 필요한 서술 필드는 인덱서가 채우지 않는다 — analyzer의 _ai_patch.json 몫이다. */
      assert.equal(clientIndex.ajax_contract, undefined);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("package.json에 번들러가 있으면 Legacy Static JS로 오판하지 않는다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-clientindex-bundled-"));
    try {
      write(root, "package.json", JSON.stringify({ scripts: { build: "vite build" }, devDependencies: { vite: "^5.0.0" } }));
      for (let i = 0; i < 105; i += 1) write(root, `src/module${i}.js`, `function onInit${i}() {}\n`);
      const first = buildIndex({ root, mode: "init", tier: "Standard", config: null });
      assert.ok(!first.indexes.includes("client_index"), `번들러가 있는데도 client_index가 생성됨: ${JSON.stringify(first.indexes)}`);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("call_graph와 sql_usage를 조인해 data_flow.json 체인을 결정론적으로 생성한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-dataflow-"));
    try {
      write(root, "src/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @Autowired private OrderService service;
  @PostMapping("/{id}/cancel")
  public void cancel() { service.cancel(); }
}
class OrderService {
  @Autowired private OrderDao repository;
  public void cancel() { repository.remove(); }
}
class OrderDao {
  @Autowired private SqlSessionTemplate sqlSession;
  public void remove() { sqlSession.update("OrderMapper.cancel", null); }
}
`);
      write(root, "src/OrderMapper.xml", `<mapper namespace="OrderMapper">
  <update id="cancel">UPDATE ORDERS SET STATUS='CANCEL' WHERE ID=#{id}</update>
</mapper>`);
      const first = buildIndex({ root, mode: "init", tier: "Standard", config: null });
      assert.ok(first.indexes.includes("data_flow"), `data_flow가 생성돼야 함: ${JSON.stringify(first.indexes)}`);
      const dataFlow = json(root, "data_flow.json");
      assert.equal(dataFlow.chains.length, 1, JSON.stringify(dataFlow.chains));
      const chain = dataFlow.chains[0];
      assert.ok(chain.method_chain.some((id) => id.endsWith("OrderController.cancel")));
      assert.ok(chain.method_chain.some((id) => id.endsWith("OrderService.cancel")), `체인이 그래프를 순회해야 함: ${JSON.stringify(chain.method_chain)}`);
      assert.equal(JSON.stringify(chain.sql_ids), JSON.stringify(["OrderMapper.cancel"]));
      assert.equal(JSON.stringify(chain.tables_written), JSON.stringify(["ORDERS"]));
      assert.equal(JSON.stringify(chain.tables_read), JSON.stringify([]));
      assert.equal(chain.note, undefined, "의미 판단(note)은 인덱서가 채우지 않는다");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("Struts command(Spring bean)로 디스패치되는 액션도 실제 서비스 클래스까지 역추적해 체인을 만든다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-dataflow-bean-"));
    try {
      /*
       * WorkerAction류 공용 디스패처 패턴 — type은 전부 같은 프레임워크 클래스라 handler로는
       * 실제 로직에 못 닿는다(2026-08-17 xu25-server 실측). command(Spring bean id)를 <bean>으로
       * 역추적해야 한다.
       */
      write(root, "src/struts-demand.xml", `<action path="/back/demand/DemandInfoAction" type="coperframe.common.struts.WorkerAction" command="DemandInfoService" name="beanForm" parameter="method">
  <forward name="list" path="/jsp/list.jsp"/>
</action>`);
      write(root, "src/application-demand.xml", `<beans>
  <bean id="DemandInfoService" class="com.acme.demand.service.DemandInfoService"/>
</beans>`);
      write(root, "src/DemandInfoService.java", `package com.acme.demand.service;
public class DemandInfoService {
  @Autowired private SqlSessionTemplate sqlSession;
  public void list() { sqlSession.selectList("DemandMapper.list", null); }
}
`);
      write(root, "src/DemandMapper.xml", `<mapper namespace="DemandMapper">
  <select id="list">SELECT * FROM DEMAND</select>
</mapper>`);
      const first = buildIndex({ root, mode: "init", tier: "Standard", config: null });
      assert.ok(first.indexes.includes("data_flow"), `data_flow가 생성돼야 함: ${JSON.stringify(first.indexes)}`);
      const chain = json(root, "data_flow.json").chains[0];
      assert.ok(chain.method_chain.some((id) => id.endsWith("DemandInfoService.list")), `bean으로 역추적된 서비스 메서드가 시드여야 함: ${JSON.stringify(chain.method_chain)}`);
      assert.equal(JSON.stringify(chain.sql_ids), JSON.stringify(["DemandMapper.list"]));
      assert.equal(JSON.stringify(chain.tables_read), JSON.stringify(["DEMAND"]));
      assert.equal(chain.confidence, "LOW", "런타임 파라미터로 메서드가 갈리는 시드는 과대추정이라 LOW여야 함");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("AI 보강으로 client_index의 서술 필드와 data_flow 체인의 note를 채울 수 있다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-narrative-"));
    try {
      for (let i = 0; i < 105; i += 1) write(root, `src/module${i}.js`, `function onInit${i}() {}\n`);
      write(root, "src/OrderController.java", `package com.acme;
@RequestMapping("/orders")
public class OrderController {
  @Autowired private OrderDao repository;
  @PostMapping("/{id}/cancel")
  public void cancel() { repository.remove(); }
}
class OrderDao {
  @Autowired private SqlSessionTemplate sqlSession;
  public void remove() { sqlSession.update("OrderMapper.cancel", null); }
}
`);
      write(root, "src/OrderMapper.xml", `<mapper namespace="OrderMapper">
  <update id="cancel">UPDATE ORDERS SET STATUS='CANCEL' WHERE ID=#{id}</update>
</mapper>`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      const chainId = json(root, "data_flow.json").chains[0].id;
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "set_client_index_narrative", ajax_contract: "fetch 기반 REST 호출", naming_convention: { gate: "*_gate.js" }, anti_patterns: ["eval 사용"] },
          { op: "set_flow_note", id: chainId, note: "ORDERS.STATUS 갱신만 하고 감사 로그를 남기지 않음" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 2, JSON.stringify(result));
      assert.equal(result.rejected, 0);
      const clientIndex = json(root, "client_index.json");
      assert.equal(clientIndex.ajax_contract, "fetch 기반 REST 호출");
      assert.equal(JSON.stringify(clientIndex.naming_convention), JSON.stringify({ gate: "*_gate.js" }));
      assert.equal(JSON.stringify(clientIndex.anti_patterns), JSON.stringify(["eval 사용"]));
      /* 구조 필드는 이 오퍼레이션으로 건드릴 수 없다 — 여전히 인덱서 값 그대로. */
      assert.equal(clientIndex.js_count, 105);
      assert.equal(json(root, "data_flow.json").chains[0].note, "ORDERS.STATUS 갱신만 하고 감사 로그를 남기지 않음");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("이번 회차에 조건을 못 채워도 기존 analyzer-작성 client_index/data_flow는 지우지 않는다 (하위호환)", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-preserve-legacy-"));
    try {
      /* JS가 100개 미만 = 이번 인덱서 실행은 client_index/data_flow를 만들지 않는 조건. */
      write(root, "src/Empty.java", `package com.acme;\npublic class Empty {}\n`);
      const legacyMeta = { generated_at: "2026-01-01T00:00:00+09:00", generator: "analyzer", version: "legacy" };
      write(root, "_workspace/index/client_index.json", JSON.stringify({ _meta: legacyMeta, type: "LegacyStaticJS", js_count: 3 }));
      write(root, "_workspace/index/data_flow.json", JSON.stringify({ _meta: legacyMeta, chains: [] }));
      const result = buildIndex({ root, mode: "incremental", tier: "Standard", config: null });
      assert.ok(!result.indexes.includes("client_index"), "이번 회차엔 조건 미충족이라 만들지 않아야 함");
      assert.equal(json(root, "client_index.json")._meta.generator, "analyzer", "analyzer가 쓴 기존 파일이 보존돼야 함");
      assert.equal(json(root, "data_flow.json")._meta.generator, "analyzer", "analyzer가 쓴 기존 파일이 보존돼야 함");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("존재하지 않는 client_index/data_flow에 서술 보강을 시도하면 거부된다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-indexer-narrative-reject-"));
    try {
      write(root, "src/Empty.java", `package com.acme;\npublic class Empty {}\n`);
      buildIndex({ root, mode: "init", tier: "Standard", config: null });
      write(root, "_workspace/index/_ai_patch.json", JSON.stringify({
        version: 1,
        operations: [
          { op: "set_client_index_narrative", ajax_contract: "설명" },
          { op: "set_flow_note", id: "dataflow:nothing", note: "설명" },
        ],
      }));
      const result = applyAiPatch(root, "_workspace/index/_ai_patch.json");
      assert.equal(result.applied, 0);
      assert.equal(result.rejected, 2);
      assert.equal(result.rejected_reasons.no_client_index, 1, JSON.stringify(result));
      assert.equal(result.rejected_reasons.no_data_flow, 1, JSON.stringify(result));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}
