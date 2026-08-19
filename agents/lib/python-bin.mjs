/*
 * 파이썬 인터프리터 이름을 환경에서 찾는다.
 *
 * 이 저장소는 두 이름을 서로 다른 자리에 하드코딩하고 있었다 — 테스트는 `python3`,
 * 런타임 스크립트 21곳은 `python`. 둘 다 한쪽 OS에서만 맞는다:
 *   Windows(파이썬 공식 설치판·Store판): `python`은 있고 `python3`는 없다 → 테스트 5건 실패
 *   다수 Linux 배포판·Homebrew: `python3`만 있고 `python`은 없다 → 런타임 스크립트가 전부 실패
 * ITO 현장은 윈도우가 기본이고 CI는 리눅스라 양쪽 다 실제로 밟는 조합이다.
 *
 * 그래서 이름을 고정하지 않고 실제로 실행되는 것을 찾아 쓴다. 없으면 `null`을 돌려주고,
 * 부르는 쪽이 "파이썬 없음"을 조용한 실패가 아니라 명시적인 사유로 다루게 한다.
 */
import { spawnSync } from "node:child_process";

const CANDIDATES = ["python3", "python", "py"];

let resolved;
export function pythonBin() {
  if (resolved !== undefined) return resolved;
  for (const name of CANDIDATES) {
    /* `--version`이 실제로 성공해야 인정한다. Windows Store의 `python` stub은 존재하지만
     * 실행하면 스토어 앱을 띄우고 실패하므로 이름 존재 여부만으로는 판정할 수 없다. */
    const probe = spawnSync(name, ["--version"], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    if (probe.status === 0 && /Python\s+3/.test(`${probe.stdout}${probe.stderr}`)) {
      resolved = name;
      return resolved;
    }
  }
  resolved = null;
  return resolved;
}
