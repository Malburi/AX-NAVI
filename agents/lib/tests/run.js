// 최소 테스트 러너 (무의존). 실행: node agents/lib/tests/run.js
import { test as registerIndexerTests } from "./build-index.test.mjs";
import { test as registerBudgetTests } from "./ai-budget.test.mjs";
import { test as registerValidateHarnessTests } from "./validate-harness.test.mjs";
import { test as registerPatternProfileTests } from "./pattern-profile.test.mjs";
import { test as registerRoleContractTests } from "./role-contract.test.mjs";
import { test as registerQaBoundaryTests } from "./qa-boundary6.test.mjs";
import { test as registerPluginPackagingTests } from "./plugin-packaging.test.mjs";
import { test as registerQueryIndexTests } from "./query-index.test.mjs";
import { test as registerPortabilityTests } from "./portability.test.mjs";
import { test as registerVerifyTargetTests } from "./verify-target.test.mjs";

const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}

const assert = {
  equal(a, b, msg) {
    if (a !== b) throw new Error(`${msg || "equal"} — expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  },
  ok(v, msg) {
    if (!v) throw new Error(`${msg || "expected truthy"} — got ${JSON.stringify(v)}`);
  },
};

await registerIndexerTests(test, assert);
await registerBudgetTests(test, assert);
await registerValidateHarnessTests(test, assert);
await registerPatternProfileTests(test, assert);
await registerRoleContractTests(test, assert);
await registerQaBoundaryTests(test, assert);
await registerPluginPackagingTests(test, assert);
await registerQueryIndexTests(test, assert);
await registerPortabilityTests(test, assert);
await registerVerifyTargetTests(test, assert);

let passed = 0,
  failed = 0;
for (const t of tests) {
  try {
    await t.fn();
    passed++;
    console.log("  ✓ " + t.name);
  } catch (e) {
    failed++;
    console.error("  ✗ " + t.name + "\n    " + e.message);
  }
}
console.log(`\n${passed} passed, ${failed} failed (${tests.length} total)`);
process.exit(failed ? 1 : 0);
