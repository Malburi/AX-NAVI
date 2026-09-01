import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { initBudget, claimBudget, budgetStatus, recordSpend, estimateCost } from "../ai-budget.mjs";

function withTempRoot(fn) {
  const root = mkdtempSync(join(tmpdir(), "ax-budget-"));
  try {
    return fn(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

export async function test(register, assert) {
  register("ai-budget init은 동일 session 재호출 시 멱등하다", () => {
    withTempRoot((root) => {
      const first = initBudget({ root, session: "s1", initial: 3, retries: 2 });
      const second = initBudget({ root, session: "s1", initial: 99, retries: 99 });
      assert.equal(second.limits.initial, 3, "재init이 기존 한도를 덮어쓰면 안 됨");
      assert.equal(first.used.initial, 0);
    });
  });

  register("initial claim은 role마다 정확히 1회 허용된다", () => {
    withTempRoot((root) => {
      initBudget({ root, session: "s1", initial: 3, retries: 2 });
      const claim = claimBudget({ root, session: "s1", role: "analyzer", kind: "initial" });
      assert.equal(claim.allowed, true);
      assert.equal(budgetStatus(root).used.initial, 1);

      let threw = false;
      try {
        claimBudget({ root, session: "s1", role: "analyzer", kind: "initial" });
      } catch (e) {
        threw = true;
        assert.ok(/한 번만 허용/.test(e.message), `동일 role 재claim 오류 메시지: ${e.message}`);
      }
      assert.ok(threw, "동일 role의 두 번째 initial claim은 거부돼야 함");
    });
  });

  register("initial 예산은 role 3개(analyzer/writer/pattern-extractor)까지만 허용된다", () => {
    withTempRoot((root) => {
      initBudget({ root, session: "s1", initial: 3, retries: 2 });
      claimBudget({ root, session: "s1", role: "analyzer", kind: "initial" });
      claimBudget({ root, session: "s1", role: "writer", kind: "initial" });
      claimBudget({ root, session: "s1", role: "pattern-extractor", kind: "initial" });
      let threw = false;
      try {
        claimBudget({ root, session: "s1", role: "extra-role", kind: "initial" });
      } catch (e) {
        threw = true;
        assert.ok(/예산 초과/.test(e.message), `예산 초과 메시지: ${e.message}`);
      }
      assert.ok(threw, "initial 예산 소진 후 새 role claim은 거부돼야 함");
    });
  });

  register("retry claim은 --reason 없이 거부된다", () => {
    withTempRoot((root) => {
      initBudget({ root, session: "s1", initial: 3, retries: 2 });
      let threw = false;
      try {
        claimBudget({ root, session: "s1", role: "analyzer", kind: "retry", reason: "" });
      } catch (e) {
        threw = true;
        assert.ok(/reason이 필요/.test(e.message));
      }
      assert.ok(threw, "reason 없는 retry claim은 거부돼야 함");
    });
  });

  register("retry 예산은 2회까지 허용되고 초과 시 거부된다", () => {
    withTempRoot((root) => {
      initBudget({ root, session: "s1", initial: 3, retries: 2 });
      claimBudget({ root, session: "s1", role: "analyzer", kind: "retry", reason: "T-A-RETRY test" });
      claimBudget({ root, session: "s1", role: "writer", kind: "retry", reason: "T-W-RETRY test" });
      let threw = false;
      try {
        claimBudget({ root, session: "s1", role: "writer", kind: "retry", reason: "third retry" });
      } catch (e) {
        threw = true;
        assert.ok(/retries AI 호출 예산 초과: 2\/2/.test(e.message), `예산 초과 메시지: ${e.message}`);
      }
      assert.ok(threw, "retries 예산 소진 후 세 번째 claim은 거부돼야 함");
    });
  });

  register("시간 예산이 소진되면 호출 횟수가 남아도 거부한다", () => {
    withTempRoot((root) => {
      const t0 = 1_000_000;
      initBudget({ root, session: "s1", initial: 3, retries: 2, minutes: 30, now: t0 });
      assert.equal(claimBudget({ root, session: "s1", role: "analyzer", now: t0 }).allowed, true);
      let threw = false;
      try {
        claimBudget({ root, session: "s1", role: "writer", now: t0 + 31 * 60_000 });
      } catch (e) {
        threw = true;
        assert.ok(/시간 예산 초과/.test(e.message), `시간 예산 메시지: ${e.message}`);
      }
      assert.ok(threw, "시간 한도를 넘겼으면 횟수가 남아도 거부돼야 함");
    });
  });

  register("토큰 예산은 record로 쌓인 실제 소비를 기준으로 막는다", () => {
    withTempRoot((root) => {
      const t0 = 1_000_000;
      initBudget({ root, session: "s1", initial: 3, retries: 2, tokens: 500_000, now: t0 });
      claimBudget({ root, session: "s1", role: "analyzer", now: t0 });
      recordSpend({ root, role: "analyzer", spentTokens: 400_000 });
      assert.equal(claimBudget({ root, session: "s1", role: "writer", now: t0 }).allowed, true, "한도 내면 통과");
      recordSpend({ root, role: "writer", spentTokens: 150_000 });
      let threw = false;
      try {
        claimBudget({ root, session: "s1", role: "pattern-extractor", now: t0 });
      } catch (e) {
        threw = true;
        assert.ok(/토큰 예산 초과/.test(e.message), `토큰 예산 메시지: ${e.message}`);
      }
      assert.ok(threw, "누적 소비가 한도를 넘으면 거부돼야 함");
      assert.equal(budgetStatus(root).used.tokens, 550_000);
    });
  });

  register("한도를 주지 않으면 시간·토큰 게이트는 적용되지 않는다 (기존 동작 보존)", () => {
    withTempRoot((root) => {
      initBudget({ root, session: "s1", initial: 3, retries: 2, now: 0 });
      recordSpend({ root, role: "analyzer", spentTokens: 99_000_000 });
      const claim = claimBudget({ root, session: "s1", role: "analyzer", now: 999 * 60_000 });
      assert.equal(claim.allowed, true, "한도 0이면 무제한이어야 함");
      assert.equal(claim.remaining.tokens, null);
      assert.equal(claim.remaining.minutes, null);
    });
  });

  register("사전 견적은 파일 수·Tier·판정 대상 미해결 건수에 따라 커진다", () => {
    const small = estimateCost({ source_file_count: 300, tier: "Standard" }, { counts: {}, coverage: {} });
    const big = estimateCost({ source_file_count: 5000, tier: "Full" }, { counts: {}, coverage: { unresolved_decidable_count: 1500 } });
    assert.ok(big.estimated_tokens > small.estimated_tokens * 5, `대형이 훨씬 커야 함: ${small.estimated_tokens} vs ${big.estimated_tokens}`);
    assert.ok(small.estimated_minutes >= 3, "최소 추정 시간 하한");
    /* 판정 대상 미해결은 상한(2000)에서 포화한다 — 십수만 건이어도 견적이 발산하지 않아야 한다. */
    const huge = estimateCost({ source_file_count: 5000, tier: "Full" }, { counts: {}, coverage: { unresolved_decidable_count: 500_000 } });
    const capped = estimateCost({ source_file_count: 5000, tier: "Full" }, { counts: {}, coverage: { unresolved_decidable_count: 2000 } });
    assert.equal(huge.estimated_tokens, capped.estimated_tokens, "미해결 건수는 상한에서 포화해야 함");
  });

  register("그룹 카운트가 있으면 발생 위치 수 대신 그룹 수로 견적을 잡는다 (반복 패턴 압축)", () => {
    /* 실사용 세션 실측: 발생 위치 2,380건이 실제로는 고유 패턴 185개 — 그룹 필드가 있으면
     * 그 값을 써야 발생 위치 수를 그대로 쓸 때보다 견적이 훨씬 작아진다. */
    const withoutGroups = estimateCost({ source_file_count: 2575, tier: "Full" }, { counts: {}, coverage: { unresolved_decidable_count: 2380 } });
    const withGroups = estimateCost({ source_file_count: 2575, tier: "Full" }, { counts: {}, coverage: { unresolved_decidable_count: 2380, unresolved_decidable_group_count: 185 } });
    assert.ok(withGroups.estimated_tokens < withoutGroups.estimated_tokens, `그룹 카운트를 우선해야 함: ${withGroups.estimated_tokens} vs ${withoutGroups.estimated_tokens}`);
    assert.equal(withGroups.decidable_unresolved, 185, "반환값도 그룹 수를 반영해야 함");

    /* 옛 인덱스(그룹 필드 없음)는 기존 필드로 폴백해야 하위호환이 깨지지 않는다. */
    const legacyIndex = estimateCost({ source_file_count: 2575, tier: "Full" }, { counts: {}, coverage: { unresolved_decidable_count: 2380 } });
    assert.equal(legacyIndex.decidable_unresolved, 2380, "그룹 필드가 없는 옛 인덱스는 발생 위치 수로 폴백해야 함");
  });
}
