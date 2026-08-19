import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { pythonBin } from "../python-bin.mjs";

const ROOT = join(import.meta.dirname, "..", "..", "..");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === ".git" || entry === "node_modules") continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (entry.endsWith(".mjs") || entry.endsWith(".js")) out.push(path);
  }
  return out;
}

export async function test(register, assert) {
  register("파이썬 인터프리터 이름을 코드에 하드코딩하지 않는다", () => {
    /*
     * 예전에는 테스트가 "python3", 런타임 문서가 "python"을 각각 하드코딩해
     * 윈도우에서는 테스트 5건이, 리눅스에서는 런타임 스크립트가 실패했다.
     * 이름은 반드시 pythonBin()으로 결정한다.
     */
    const offenders = [];
    for (const file of walk(join(ROOT, "agents", "lib"))) {
      if (file.endsWith("python-bin.mjs")) continue;
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(/execFileSync\(\s*"(python3?)"|spawnSync\(\s*"(python3?)"/g)) {
        offenders.push(`${file.slice(ROOT.length + 1)}: ${match[1] || match[2]}`);
      }
    }
    assert.equal(offenders.length, 0, `하드코딩된 인터프리터: ${JSON.stringify(offenders)}`);
  });

  register("pythonBin은 실제로 실행되는 인터프리터만 인정한다", () => {
    const bin = pythonBin();
    /* 이 환경에는 파이썬이 있으므로 이름이 나와야 한다. 없는 환경이면 null이 정상이다. */
    assert.ok(bin === null || ["python3", "python", "py"].includes(bin), `예상 밖 값: ${bin}`);
    if (bin) {
      /* 두 번째 호출은 캐시에서 같은 값이 나와야 한다(매 호출마다 프로세스를 띄우지 않는다). */
      assert.equal(pythonBin(), bin, "결과가 캐시돼야 함");
    }
  });
}
