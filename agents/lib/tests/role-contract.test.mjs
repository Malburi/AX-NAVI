import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..", "..");

function read(path) {
  return readFileSync(path, "utf8");
}

function field(text, name) {
  return text.match(new RegExp(`^${name}:\\s*(.+)$`, "m"))?.[1]?.trim() || "";
}

function agentFiles() {
  return readdirSync(join(root, "agents"))
    .filter((name) => name.endsWith(".md"))
    .map((name) => join(root, "agents", name));
}

function skillFiles() {
  return readdirSync(join(root, "skills"))
    .map((name) => join(root, "skills", name, "SKILL.md"))
    .filter((path) => {
      try {
        read(path);
        return true;
      } catch {
        return false;
      }
    });
}

export async function test(register, assert) {
  register("에이전트·스킬 frontmatter의 이름과 모델 계약이 유일하다", () => {
    const agents = agentFiles().map((path) => ({ path, text: read(path) }));
    const skills = skillFiles().map((path) => ({ path, text: read(path) }));
    const agentNames = agents.map(({ text }) => field(text, "name"));
    const skillNames = skills.map(({ text }) => field(text, "name"));

    assert.equal(agents.length, 19);
    assert.equal(skills.length, 24); // 워크플로우 17 + 별칭 7 (modify/impact/scaffold/find/flow/sql/wiki)
    assert.equal(new Set(agentNames).size, agents.length);
    assert.equal(new Set(skillNames).size, skills.length);
    assert.ok(agentNames.every(Boolean), "에이전트 name 누락");
    assert.ok(skillNames.every(Boolean), "스킬 name 누락");
    assert.ok(agents.every(({ text }) => ["sonnet", "opus"].includes(field(text, "model"))), "에이전트 model 누락·오류");
  });

  register("매니페스트의 에이전트·스킬 수가 실제 파일 수와 일치한다", () => {
    const plugin = JSON.parse(read(join(root, ".claude-plugin", "plugin.json")));
    const marketplace = JSON.parse(read(join(root, ".claude-plugin", "marketplace.json")));
    assert.ok(plugin.description.includes("19 agents + 17 workflow skills"));
    assert.ok(marketplace.plugins[0].description.includes("19개 에이전트 + 17개 워크플로우 스킬"));
  });

  register("역할 맵이 전체 스킬·에이전트를 포함하고 리포트 경로가 reports로 통일된다", () => {
    const roleMap = read(join(root, "docs", "role-map.md"));
    const sourceTexts = [...agentFiles(), ...skillFiles()].map(read);
    for (const path of [...agentFiles(), ...skillFiles()]) {
      const name = field(read(path), "name");
      assert.ok(roleMap.includes(`\`${name}\``), `역할 맵 누락: ${name}`);
    }
    assert.ok(sourceTexts.every((text) => !/_workspace\/(decoded_|tests_)/.test(text)), "옛 리포트 경로가 남아 있음");
  });

  register("QA/evaluator 계약이 전역 6종 스킬과 Boundary 1~7 운영 모델을 따른다", () => {
    const qa = read(join(root, "agents", "qa.md"));
    const evaluator = read(join(root, "agents", "harness-evaluator.md"));
    const writer = read(join(root, "agents", "writer.md"));
    const rootClaude = read(join(root, "CLAUDE.md"));
    assert.ok(!qa.includes("기존 절차 그대로") && !qa.includes("기존 절차."), "QA boundary에 실행 불가능한 stale 절차가 남음");
    assert.ok(!evaluator.includes("정적 배포 스킬 5종"), "evaluator가 폐기된 로컬 배포 5종 계약을 사용함");
    assert.ok(writer.includes("전역 워크플로우 6종") && writer.includes("프로젝트에 복사하지 않는다"), "writer 전역 스킬 계약");
    assert.ok(rootClaude.includes("Phase 3.7 온디맨드") && rootClaude.includes("Boundary 1~7"), "루트 운영 문서 QA 단계 drift");
  });
}
