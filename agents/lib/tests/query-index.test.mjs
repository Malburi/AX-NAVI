import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { COMMANDS } from "../query-index.mjs";

function withIndex(fixture, fn) {
  const root = mkdtempSync(join(tmpdir(), "ax-query-"));
  try {
    const dir = join(root, "_workspace", "index");
    mkdirSync(dir, { recursive: true });
    for (const [name, value] of Object.entries(fixture)) {
      writeFileSync(join(dir, `${name}.json`), JSON.stringify(value), "utf8");
    }
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

const GRAPH = {
  _meta: { generated_at: "t" },
  nodes: [],
  edges: [
    { from: "kr.co.demo.web.OrderController.save", to: "kr.co.demo.service.OrderService.save", type: "call", file: "src/OrderController.java", line: 10 },
    { from: "kr.co.demo.service.OrderService.save", to: "kr.co.demo.dao.OrderDao.insert", type: "call", file: "src/OrderService.java", line: 20 },
    { from: "kr.co.demo.service.OrderService.save", to: "kr.co.demo.util.LogUtil.write", type: "call", file: "src/OrderService.java", line: 22 },
    { from: "kr.co.demo.batch.Night.run", to: "kr.co.demo.service.OrderService.save", type: "call", file: "src/Night.java", line: 5 },
  ],
};

export async function test(register, assert) {
  register("callers·callees는 짧은 이름으로도 조회된다", () => {
    withIndex({ call_graph: GRAPH }, (root) => {
      const callers = COMMANDS.callers({ root, id: "OrderService.save", limit: 50 });
      assert.equal(callers.total, 2, `호출자 2곳: ${JSON.stringify(callers.items)}`);
      assert.ok(callers.items.some((item) => item.from.endsWith("OrderController.save")));
      assert.ok(callers.items.some((item) => item.from.endsWith("Night.run")));
      const callees = COMMANDS.callees({ root, id: "kr.co.demo.service.OrderService.save", limit: 50 });
      assert.equal(callees.total, 2, "피호출 2곳");
    });
  });

  register("trace는 출발점을 포함한 경로를 깊이 제한 안에서 돌려준다", () => {
    withIndex({ call_graph: GRAPH }, (root) => {
      const traced = COMMANDS.trace({ root, id: "OrderController.save", depth: 3, limit: 50 });
      assert.equal(traced.resolved_start, "kr.co.demo.web.OrderController.save");
      const deepest = traced.items.map((item) => item.path.join(" > "));
      assert.ok(deepest.some((path) => path.startsWith("kr.co.demo.web.OrderController.save > kr.co.demo.service.OrderService.save")), `경로에 출발점 포함: ${JSON.stringify(deepest)}`);
      assert.ok(deepest.some((path) => path.endsWith("OrderDao.insert")), "2단계까지 도달");
      const shallow = COMMANDS.trace({ root, id: "OrderController.save", depth: 1, limit: 50 });
      assert.equal(shallow.total, 1, `depth 1이면 직접 호출만: ${JSON.stringify(shallow.items)}`);
    });
  });

  register("응답 상한은 total·truncated로 드러난다 (조용히 자르지 않는다)", () => {
    const many = { _meta: {}, nodes: [], edges: Array.from({ length: 120 }, (_, i) => ({ from: `pkg.A.m${i}`, to: "pkg.B.target", type: "call", file: "a.java", line: i })) };
    withIndex({ call_graph: many }, (root) => {
      const capped = COMMANDS.callers({ root, id: "pkg.B.target", limit: 10 });
      assert.equal(capped.returned, 10);
      assert.equal(capped.total, 120);
      assert.equal(capped.truncated, 110, "잘린 수를 명시해야 한다");
    });
  });

  register("table 질의는 SQL 문과 호출 지점을 함께 준다", () => {
    withIndex({
      sql_usage: {
        _meta: {},
        sqls: [
          { id: "order.selectList", type: "select", tables: ["TB_ORDER", "TB_MEMBER"], file: "m.xml", line: 5 },
          { id: "order.insert", type: "insert", tables: ["TB_ORDER"], file: "m.xml", line: 11 },
          { id: "member.selectList", type: "select", tables: ["TB_MEMBER"], file: "m2.xml", line: 5 },
        ],
        usages: [
          { sql_id: "order.insert", file: "OrderDao.java", line: 11, method: "kr.co.demo.dao.OrderDao.insert" },
          { sql_id: "member.selectList", file: "MemberDao.java", line: 10, method: "kr.co.demo.dao.MemberDao.selectList" },
        ],
      },
    }, (root) => {
      const result = COMMANDS.table({ root, table: "TB_ORDER", limit: 50 });
      assert.equal(result.statements.total, 2, "TB_ORDER를 쓰는 문장만");
      assert.equal(JSON.stringify(result.statement_count_by_type), JSON.stringify({ select: 1, insert: 1 }));
      assert.equal(result.call_sites.total, 1, "그 문장을 부르는 곳만");
      assert.equal(result.call_sites.items[0].method, "kr.co.demo.dao.OrderDao.insert");
    });
  });

  register("없는 인덱스는 빈 결과가 아니라 사유를 알린다", () => {
    withIndex({ call_graph: GRAPH }, (root) => {
      let threw = false;
      try {
        COMMANDS.sql({ root, table: "TB_ORDER", limit: 50 });
      } catch (error) {
        threw = true;
        /* "결과 0건"과 "인덱스가 없다"는 전혀 다른 결론이라 반드시 구분돼야 한다. */
        assert.equal(error.missingIndex, "sql_usage");
        assert.ok(/build-index/.test(error.message), `복구 방법 안내: ${error.message}`);
      }
      assert.ok(threw, "인덱스가 없으면 조용히 빈 결과를 주면 안 된다");
    });
  });

  register("symbol 질의는 짧은 이름·파일로 심볼을 찾고 누락 인덱스는 사유를 알린다", () => {
    const SYMBOLS = {
      _meta: {},
      symbols: [
        { id: "kr.co.demo.service.OrderService", type: "class", file: "src/OrderService.java", line: 1, package: "kr.co.demo.service" },
        { id: "kr.co.demo.service.OrderService.save", type: "method", file: "src/OrderService.java", line: 20, package: "kr.co.demo.service" },
        { id: "kr.co.demo.web.OrderController", type: "class", file: "src/OrderController.java", line: 1, package: "kr.co.demo.web" },
        { id: "kr.co.demo.service.MemberService", type: "class", file: "src/MemberService.java", line: 1, package: "kr.co.demo.service" },
      ],
    };
    withIndex({ symbols: SYMBOLS }, (root) => {
      /* 짧은 이름으로 물어도 마지막 segment·부분 문자열로 맞는다 — MemberService는 제외돼야 한다. */
      const byName = COMMANDS.symbol({ root, name: "OrderService", limit: 50 });
      assert.equal(byName.total, 2, `OrderService 관련만: ${JSON.stringify(byName.items)}`);
      assert.ok(byName.items.every((item) => item.id.includes("OrderService")));

      /* 파일로 좁히면 그 파일 심볼만. */
      const byFile = COMMANDS.symbol({ root, file: "OrderController.java", limit: 50 });
      assert.equal(byFile.total, 1);
      assert.equal(byFile.items[0].id, "kr.co.demo.web.OrderController");

      /* 상한 초과는 total·truncated로 드러난다. */
      const capped = COMMANDS.symbol({ root, name: "Service", limit: 1 });
      assert.equal(capped.returned, 1);
      assert.ok(capped.total >= 3, `Service 포함 심볼 다수: ${capped.total}`);
      assert.equal(capped.truncated, capped.total - 1, "잘린 수를 명시해야 한다");
    });

    /* symbols.json이 없으면 "결과 0건"이 아니라 인덱스 부재를 알려야 한다. */
    withIndex({ call_graph: GRAPH }, (root) => {
      let threw = false;
      try {
        COMMANDS.symbol({ root, name: "OrderService", limit: 50 });
      } catch (error) {
        threw = true;
        assert.equal(error.missingIndex, "symbols");
        assert.ok(/build-index/.test(error.message), `복구 방법 안내: ${error.message}`);
      }
      assert.ok(threw, "인덱스가 없으면 조용히 빈 결과를 주면 안 된다");
    });
  });

  register("schema 질의는 참조하는 쪽 FK까지 함께 준다", () => {
    withIndex({
      schema: {
        _meta: {},
        tables: [
          { name: "TB_MEMBER", columns: [{ name: "MEM_ID" }], primary_key: ["MEM_ID"], foreign_keys: [], indexes: [], source_file: "db/schema.sql" },
          { name: "TB_ORDER", columns: [{ name: "ID" }, { name: "MEM_ID" }], primary_key: ["ID"], indexes: [],
            foreign_keys: [{ name: "FK_ORDER_MEM", columns: ["MEM_ID"], references_table: "TB_MEMBER", references_columns: ["MEM_ID"] }], source_file: "db/schema.sql" },
        ],
      },
    }, (root) => {
      const member = COMMANDS.schema({ root, table: "TB_MEMBER", limit: 50 });
      assert.equal(member.returned, 1);
      /* 한쪽 방향만 보면 "이 테이블을 지우면 무엇이 깨지나"를 놓친다. */
      assert.equal(member.referenced_by.length, 1, `TB_MEMBER를 참조하는 테이블: ${JSON.stringify(member.referenced_by)}`);
      assert.equal(member.referenced_by[0].table, "TB_ORDER");

      /* 테이블 미지정이면 목록 요약만 — 수백 개짜리 스키마를 통째로 뱉지 않는다. */
      const all = COMMANDS.schema({ root, limit: 50 });
      assert.equal(all.total, 2);
      assert.equal(all.items[0].column_count, 1, "목록 조회는 컬럼 수만");
      assert.ok(!all.items[0].columns, "목록 조회에 컬럼 본문이 실리면 안 된다");
    });
  });
}
