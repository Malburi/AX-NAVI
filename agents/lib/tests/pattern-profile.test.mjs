import { execFileSync, spawnSync } from "node:child_process";
import { pythonBin } from "../python-bin.mjs";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, "..", "pattern_profile.py");
const libDir = join(here, "..");

function write(root, rel, content) {
  const path = join(root, rel);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content, "utf8");
}

function profile(root, profiles) {
  write(root, ".claude/patterns/pattern_profile.json", JSON.stringify({ version: 1, profiles }));
}

function preferred(id, module, layer, prefix, ref, confidence = "HIGH") {
  return {
    id,
    status: "preferred",
    confidence,
    samples_analyzed: 8,
    scope: { module, layer, stack: "Spring", path_prefixes: [prefix] },
    reference_files: [{ path: ref, reason: "동일 모듈의 대표 구현" }],
    rules: { class_suffix: "Service", transaction_location: "service" },
  };
}

export async function test(register, assert) {
  /*
   * 인터프리터 이름을 하드코딩하지 않는다 — Windows는 `python`, 다수 리눅스는 `python3`만 있다.
   * 아예 없으면 실패로 몰지 않고 사유를 밝히며 건너뛴다. "파이썬이 없다"와 "패턴 프로필이 틀렸다"는
   * 전혀 다른 결론인데, 예전에는 둘이 똑같이 빨간 FAIL로 보여 실제 회귀를 가렸다.
   */
  const PY_BIN = pythonBin();
  if (!PY_BIN) {
    register("패턴 프로필 검증 (건너뜀 — 실행 가능한 python3가 없음)", () => {
      assert.ok(true, "python3/python 미설치 환경");
    });
    return;
  }

  register("패턴 프로필은 실제 근거 파일과 필수 필드를 검증한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-pattern-profile-"));
    try {
      write(root, "src/education/OrderService.java", "class OrderService {}\n");
      profile(root, [preferred("education-service", "education", "service", "src/education", "src/education/OrderService.java")]);
      execFileSync(PY_BIN, [script, "validate", "--root", root], { encoding: "utf8" });
      const result = JSON.parse(readFileSync(join(root, "_workspace/pattern_profile_validation.json"), "utf8"));
      assert.equal(result.valid, true);
      assert.equal(result.profiles, 1);
      assert.equal(result.status_counts.preferred, 1);
      assert.equal(result.reference_files, 1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("존재하지 않는 근거 파일을 가진 패턴 프로필은 실패한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-pattern-profile-invalid-"));
    try {
      profile(root, [preferred("missing", "education", "service", "src/education", "src/education/Missing.java")]);
      const result = spawnSync(PY_BIN, [script, "validate", "--root", root], { encoding: "utf8" });
      assert.equal(result.status, 1);
      const report = JSON.parse(readFileSync(join(root, "_workspace/pattern_profile_validation.json"), "utf8"));
      assert.ok(report.errors.some((item) => item.includes("근거 파일 없음")));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("작업 경로·모듈·레이어가 같은 패턴을 우선 선택한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-pattern-profile-select-"));
    try {
      write(root, "src/common/CommonService.java", "class CommonService {}\n");
      write(root, "src/education/EducationService.java", "class EducationService {}\n");
      profile(root, [
        preferred("common-service", "common", "service", "src/common", "src/common/CommonService.java"),
        preferred("education-service", "education", "service", "src/education", "src/education/EducationService.java"),
      ]);
      execFileSync(PY_BIN, [script, "select", "--root", root, "--target", "src/education/new", "--module", "education", "--layer", "service"], { encoding: "utf8" });
      const result = JSON.parse(readFileSync(join(root, "_workspace/reports/pattern_selection.json"), "utf8"));
      assert.equal(result.selected[0].profile.id, "education-service");
      assert.ok(result.selected[0].reasons.some((item) => item.includes("경로 일치")));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("무관한 모듈 프로필을 기준 패턴으로 선택하지 않는다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-pattern-profile-unrelated-"));
    try {
      write(root, "src/order/OrderService.java", "class OrderService {}\n");
      profile(root, [preferred("order-service", "order", "service", "src/order", "src/order/OrderService.java")]);
      const result = spawnSync(PY_BIN, [script, "select", "--root", root, "--target", "src/education", "--module", "education", "--layer", "service"], { encoding: "utf8" });
      assert.equal(result.status, 2);
      const report = JSON.parse(readFileSync(join(root, "_workspace/reports/pattern_selection.json"), "utf8"));
      assert.equal(report.selected.length, 0);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  register("위키 패턴 페이지는 구조화 프로필과 실제 기준 파일을 표시한다", () => {
    const root = mkdtempSync(join(tmpdir(), "ax-pattern-wiki-"));
    try {
      write(root, "src/education/EducationService.java", "class EducationService {}\n");
      profile(root, [preferred("education-service", "education", "service", "src/education", "src/education/EducationService.java")]);
      write(root, ".claude/patterns/service.md", "# Service Pattern\n\n상세 규칙\n");
      const code = [
        "import sys",
        "sys.path.insert(0, sys.argv[2])",
        "import wiki_content",
        "print(wiki_content.build_patterns(sys.argv[1]))",
      ].join(";");
      /* Windows 콘솔 python은 stdout이 cp949라 utf8 비교가 모지바케로 깨진다 — 강제 지정. */
      const rendered = execFileSync(PY_BIN, ["-c", code, join(root, ".claude/patterns"), libDir], { encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } });
      assert.ok(rendered.includes("구조화 패턴 프로필"));
      assert.ok(rendered.includes("education-service"));
      assert.ok(rendered.includes("src/education/EducationService.java"));
      assert.ok(rendered.includes("Service Pattern"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}
