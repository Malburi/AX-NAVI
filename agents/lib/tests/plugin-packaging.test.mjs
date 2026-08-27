import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..", "..");

function read(path) {
  return readFileSync(path, "utf8");
}

function json(relativePath) {
  return JSON.parse(read(join(root, relativePath)));
}

function frontmatterField(text, name) {
  const frontmatter = text.match(/^---\s*\n([\s\S]*?)\n---/m)?.[1] || "";
  return frontmatter.match(new RegExp(`^${name}:\\s*(.+)$`, "m"))?.[1]?.trim() || "";
}

export async function test(register, assert) {
  register("플러그인 매니페스트가 기본 디렉터리 자동 탐색 계약을 따른다", () => {
    const plugin = json(".claude-plugin/plugin.json");
    const supportedFields = new Set([
      "$schema", "name", "displayName", "version", "description", "author", "homepage",
      "repository", "license", "keywords", "metadata", "defaultEnabled", "skills", "commands",
      "agents", "hooks", "mcpServers", "outputStyles", "lspServers", "experimental", "dependencies",
    ]);

    assert.equal(plugin.name, "total-ito");
    assert.ok(/^\d+\.\d+\.\d+$/.test(plugin.version), "플러그인 버전은 semver여야 함");
    assert.ok(!Object.hasOwn(plugin, "skills"), "기본 skills 경로는 자동 탐색하므로 중복 선언하지 않음");
    assert.ok(!Object.hasOwn(plugin, "agents"), "기본 agents 경로는 자동 탐색하므로 중복 선언하지 않음");
    assert.ok(existsSync(join(root, "skills")), "기본 skills 경로가 없음");
    assert.ok(existsSync(join(root, "agents")), "기본 agents 경로가 없음");
    assert.ok(Object.keys(plugin).every((key) => supportedFields.has(key)), "비표준 plugin.json 필드가 있음");
  });

  register("마켓플레이스가 저장소 루트 플러그인을 설치 대상으로 가리킨다", () => {
    const marketplace = json(".claude-plugin/marketplace.json");
    assert.ok(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(marketplace.name), "마켓플레이스 이름은 kebab-case여야 함");
    assert.equal(marketplace.plugins.length, 1);
    assert.equal(marketplace.name, "total-ito");
    assert.equal(marketplace.renames["ax-std-harness"], "total-ito");
    assert.equal(marketplace.plugins[0].name, "total-ito");
    assert.equal(marketplace.plugins[0].source, ".");
    assert.ok(existsSync(join(root, marketplace.plugins[0].source, ".claude-plugin", "plugin.json")));
  });

  register("설치되는 모든 스킬과 에이전트의 이름이 경로와 일치한다", () => {
    const skillDirs = readdirSync(join(root, "skills"), { withFileTypes: true }).filter((entry) => entry.isDirectory());
    const agentFiles = readdirSync(join(root, "agents")).filter((name) => name.endsWith(".md"));

    assert.equal(skillDirs.length, 24); // 워크플로우 17 + 별칭 7 (modify/impact/scaffold/find/flow/sql/wiki)
    assert.equal(agentFiles.length, 19);
    for (const entry of skillDirs) {
      const path = join(root, "skills", entry.name, "SKILL.md");
      assert.ok(existsSync(path), `SKILL.md 누락: ${entry.name}`);
      assert.equal(frontmatterField(read(path), "name"), entry.name, `스킬 이름 불일치: ${entry.name}`);
      assert.ok(frontmatterField(read(path), "description"), `스킬 description 누락: ${entry.name}`);
    }
    for (const file of agentFiles) {
      const expected = file.slice(0, -3);
      const text = read(join(root, "agents", file));
      assert.equal(frontmatterField(text, "name"), expected, `에이전트 이름 불일치: ${file}`);
      assert.ok(frontmatterField(text, "description"), `에이전트 description 누락: ${file}`);
    }
  });
}
