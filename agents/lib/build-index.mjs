#!/usr/bin/env node
/*
 * AX-Harness deterministic indexer
 *
 * 출처: upstream AX-Harness(Malburi/harness-sm) scripts/build-index.mjs, INDEXER_VERSION 1.7.0, 2026-08-12 이식.
 * 1.8.0부터 범용 adapter registry와 .NET/Nexacro/UI flow 보강은 total_ito에서 독자 관리한다.
 * 이 저장소 계약(_meta 9필드 · KST 타임스탬프 · api_contract 단수)에 맞춘 패치가 들어가 있으므로
 * upstream과 자동 동기화되지 않는다. 갱신 시 diff로 확인할 것.
 *
 * AI에게 전체 소스와 대형 JSON 생성을 맡기지 않기 위한 zero-dependency 1차 인덱서다.
 * 언어별 구문/프레임워크에서 확실하게 추출 가능한 사실은 이 스크립트가 기록하고,
 * 하나로 결정할 수 없는 호출 관계만 _unresolved.jsonl로 넘겨 analyzer가 보강한다.
 */
import {
  existsSync,
  mkdirSync,
  readFileSync,
  openSync,
  readSync,
  closeSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { basename, dirname, extname, isAbsolute, join, relative, resolve, sep } from "node:path";
import {
  ADAPTER_DISCOVERY_ONLY_EXTENSIONS,
  ADAPTER_SOURCE_EXTENSIONS,
  buildAdapterCoverage,
  detectAdapters,
} from "./adapters/registry.mjs";
import { extractNexacro } from "./adapters/nexacro.mjs";

export const INDEXER_VERSION = "1.10.0"; // 1.10.0: _unresolved_groups.json 신설(판정 대상을 패턴 단위로 그룹핑) + _unresolved.jsonl에 group_id 부여 — 기존 인덱스가 --check-stale에서 stale 판정되어 재인덱싱되도록 상향

/* AI edge patch에서 허용하는 관계 종류. analyzer는 노드를 새로 만들 수 없고 기존 노드 사이의 관계만 보강한다. */
const AI_PATCH_EDGE_TYPES = new Set(["call", "inject", "inherit", "reflect"]);
/*
 * `_analysis_input.json`의 digest 상한.
 * analyzer는 대형 index를 직접 읽지 못하므로, 인덱서가 이미 메모리에 갖고 있는 사실을
 * 결정적으로 정렬·집계해 "해석할 재료"만 넘긴다. 전체 덤프가 아니라 상한 있는 요약이다.
 */
const DIGEST_LIMITS = {
  hubs: 30,
  entry_points: 30,
  modules: 40,
  transactions: 25,
  external_io: 25,
  env_branches: 25,
  tables: 40,
  endpoints: 40,
  sql_tables: 25,
  dead_code: 30,
  partial_coverage: 20,
};
/* 대표 파일 경로 목록 상한 — 경로 문자열뿐이라 Tier가 커질수록 넉넉하게 준다. */
const REPRESENTATIVE_FILE_LIMITS = { Lite: 50, Standard: 150, Full: 300 };
/*
 * 대표 파일 목록에 **바이트 예산**을 함께 건다.
 *
 * 개수 상한만 두면 레거시에서 상한이 사실상 무의미하다 — 파일 크기가 균일하지 않기 때문이다.
 * 실측: Full tier 300개를 그대로 고르면 24.5MB(약 21M 토큰)였다. 3.8MB짜리 생성 XJS 파일과
 * 2KB짜리 VO 클래스가 똑같이 "1개"로 세어진 결과다. analyzer·pattern-extractor가 이 목록을
 * 열람 후보로 쓰므로, 개수가 아니라 열었을 때의 비용으로 상한을 걸어야 한다.
 *
 * 또 지나치게 큰 파일은 애초에 "대표"가 아니다 — 컨벤션을 담은 손으로 쓴 코드가 아니라
 * 생성물·번들·데이터인 경우가 대부분이다. 개별 상한으로 먼저 걸러낸다.
 */
const REPRESENTATIVE_BYTE_BUDGET = { Lite: 256 * 1024, Standard: 768 * 1024, Full: 1536 * 1024 };
const REPRESENTATIVE_PER_FILE_CAP = 128 * 1024;

/*
 * 확장자 목록은 반드시 이 상수들로만 관리한다.
 * 예전에는 같은 목록이 네 곳에 중복돼 있어 `.mjs`/`.cjs`가 어디에도 없는 채로
 * ESM Node 프로젝트의 심볼이 하나도 인덱싱되지 않는 사각지대가 생겼다.
 */
const JS_FAMILY_EXTENSIONS = [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue", ".xjs", ".xfdl"];
/* 구문 기반으로 클래스·함수·호출을 추출할 수 있는 확장자. */
const STRUCTURED_SOURCE_EXTENSIONS = [".java", ".kt", ".kts", ...JS_FAMILY_EXTENSIONS, ".py", ".cs", ".go"];

const SOURCE_EXTENSIONS = new Set([
  ...ADAPTER_SOURCE_EXTENSIONS,
  ...STRUCTURED_SOURCE_EXTENSIONS,
  ".xml", ".sql", ".jsp", ".jspx", ".tag", ".asp", ".aspx", ".ascx", ".ashx", ".asmx",
  ".vb", ".vbs", ".xaml", ".cshtml", ".vbhtml", ".razor", ".php", ".rb",
  ".cbl", ".cob", ".cpy", ".abap", ".html", ".htm",
  ".properties", ".yml", ".yaml", ".json",
]);
const MANIFEST_FILES = new Set(["pom.xml", "go.mod", "package.json", "build.gradle", "build.gradle.kts", "Cargo.toml", "Gemfile", "composer.json"]);
const DISCOVERY_ONLY_EXTENSIONS = ADAPTER_DISCOVERY_ONLY_EXTENSIONS;
const EXCLUDED_DIRS = new Set([
  ".git", "node_modules", "vendor", "dist", "build", "target", "out", ".next", ".nuxt",
  "coverage", "_workspace", "_workspace_prev", ".claude", ".idea", ".vscode", "bin", "obj",
  ".venv", "venv", "env", ".tox", "site-packages", "__pycache__", ".pytest_cache", ".mypy_cache",
]);
/* generate-wiki 산출물(wiki/, wiki_prev/)은 2026-08-14부터 _workspace/ 아래로 옮겨져
 * "_workspace" 제외만으로 이미 커버된다 — 더 이상 "wiki"/"wiki_prev"를 여기 따로 둘 필요가 없다
 * (남겨두면 대상 프로젝트가 우연히 자기 소스에 "wiki"라는 이름의 폴더를 쓸 때 잘못 제외될 수 있었다). */
/*
 * 벤더·미니파이 소스 제외.
 * EXCLUDED_DIRS는 디렉터리 *이름*만 보므로 `node_modules` 관행을 쓰지 않는 레거시 저장소를 못 잡는다.
 * 실측(2026-08-16 xu25-client)에서 ckeditor·fck_editor·jquery-ui·smarteditor2를 전부 인덱싱해
 * 노드 34,674개 중 80%가 고아가 되고 dead_code 31,572건이 거짓양성으로 나왔다.
 * 이름 목록만 믿으면 놓치므로, 파일 내용(줄당 평균 길이)을 주 신호로 쓰고 경로·파일명은 보조로 쓴다.
 */
/*
 * 디렉터리 이름으로 잡는 벤더. 라이브러리를 통째로 떨어뜨려 놓은 디렉터리는 안전하게 제외할 수 있다.
 * **파일명 앞부분으로는 잡지 않는다** — `jquery.add.js`가 실제로는 배너 슬라이더 업무 코드였다
 * (2026-08-16 실측). 라이브러리 이름을 접두사로 쓴 프로젝트 파일이 흔해서 파일명 매칭은 오탐을 낸다.
 */
const VENDOR_DIR = /(?:^|\/)(?:ckeditor|fckeditor|fck_editor|smarteditor\d*|tinymce|summernote|jquery|jquery[-_.][\w.-]*|bootstrap|fullcalendar|datatables|highcharts|chartjs|swiper|slick|owlcarousel|select2|moment|lodash|underscore|backbone|prototype|scriptaculous|modernizr|codemirror|ace-builds|webuploader|jszip|xlsx|nivo-slider|dynatree|jplayer|videojs|booklet|vkeyboard|jscalendar|jqgrid)(?:[-_.][\w.-]*)?\//i;
/* 버전이 박힌 파일명은 배포본이다 — jquery-1.5.2.js, jquery-ui-1.10.0.custom.css */
const VENDOR_VERSIONED = /(?:^|\/)[a-z][\w.]*?-\d+\.\d+[\w.]*\.(?:js|css)$/i;
/* 미니파이·번들 산출물임이 파일명에 드러난 경우. 이건 이름만으로 확실하다. */
const VENDOR_FILE = /(?:\.min\.(?:js|css)|[-.]min\.[a-z0-9]+|\.bundle\.js|\.pack\.js)$/i;
const MINIFIED_EXTENSIONS = new Set([".js", ".css", ".mjs", ".cjs"]);
/*
 * 테스트 파일도 벤더와 같은 이유로 노이즈다 — 업무 코드와 동일하게 전량 노드/엣지가 되어
 * call_graph.json을 부풀리지만 실제 호출 그래프 분석에는 의미가 없다.
 * 디렉터리는 세그먼트 완전 일치만 잡는다(VENDOR_DIR과 같은 원칙) — "abtest/"처럼 이름이
 * 다르면 걸리지 않는다. 파일명은 빌드 도구가 강제하는 규약만 써서 오탐 여지를 없앤다.
 */
const TEST_DIR = /(?:^|\/)(?:test|tests|__tests__|spec|specs)(?:\/|$)/i;
const TEST_FILE = /(?:(?:Test|Tests|TestCase|IT)\.(?:java|kt|cs)$|_test\.go$|(?:^|\/)test_[^/]+\.py$|_test\.py$|\.(?:test|spec)\.[jt]sx?$)/;
/* 줄당 평균 이 길이를 넘으면 사람이 쓴 소스가 아니다. 손으로 쓴 JS는 보통 30~60자다. */
const MINIFIED_AVG_LINE = 250;
/* 이보다 작은 파일은 굳이 열어보지 않는다 — 미니파이 번들은 사실상 전부 이보다 크다. */
const MINIFIED_MIN_BYTES = 20 * 1024;
const MINIFIED_PROBE_BYTES = 64 * 1024;

/* 파일 앞부분만 읽어 미니파이 여부를 판정한다. 줄 길이만 보므로 인코딩과 무관하다. */
function minifiedReason(full, size) {
  if (size < MINIFIED_MIN_BYTES) return null;
  let fd;
  try {
    fd = openSync(full, "r");
    const buffer = Buffer.alloc(Math.min(size, MINIFIED_PROBE_BYTES));
    const read = readSync(fd, buffer, 0, buffer.length, 0);
    const head = buffer.subarray(0, read).toString("latin1");
    const lines = head.split("\n");
    const nonEmpty = lines.filter((line) => line.trim()).length;
    if (nonEmpty <= 1) return `single-line(${read}B)`;
    const average = Math.round(read / nonEmpty);
    return average >= MINIFIED_AVG_LINE ? `avg-line(${average})` : null;
  } catch {
    return null;
  } finally {
    if (fd !== undefined) try { closeSync(fd); } catch { /* 닫기 실패는 무시 */ }
  }
}

/* 제외 사유를 반환한다(제외 대상이 아니면 null). 사유는 그대로 _meta에 기록된다. */
function vendorReason(rel, full, size, ext, config) {
  if (config?.vendor_exclude === false) return null;
  if (VENDOR_FILE.test(rel)) return "vendor-filename";
  if (VENDOR_VERSIONED.test(rel)) return "vendor-versioned";
  if (VENDOR_DIR.test(rel)) return "vendor-path";
  if (MINIFIED_EXTENSIONS.has(ext)) {
    const minified = minifiedReason(full, size);
    if (minified) return `minified:${minified}`;
  }
  return null;
}

/* 파일 전체를 제외하므로 그 파일에서 나온 노드/엣지가 통째로 안 생겨 dangling edge 위험이 없다. */
function testReason(rel, config) {
  if (config?.test_exclude === false) return null;
  if (TEST_DIR.test(rel)) return "test-path";
  if (TEST_FILE.test(rel)) return "test-filename";
  return null;
}

const MAX_FILE_BYTES = 4 * 1024 * 1024;
/* 한 미해결 항목에 후보를 무한정 적지 않는다. 후보가 수백 개면 그 자체가 "판정 불가"라는 뜻이고,
 * 실측 레거시 프로젝트에서 이 목록이 _unresolved.jsonl을 169MB까지 부풀렸다. */
const MAX_UNRESOLVED_CANDIDATES = 20;
/* 이 수를 넘으면 analyzer가 전부 처리한다는 계약 자체가 성립하지 않는다 (analyzer_contract 참고). */
const UNRESOLVED_FULL_PROCESSING_LIMIT = 2000;
const CALL_KEYWORDS = new Set([
  "if", "for", "while", "switch", "catch", "return", "throw", "new", "super", "this", "typeof",
  "sizeof", "await", "yield", "require", "import", "function", "class", "def", "func", "when",
  /* try-with-resources `try (AutoCloseable x = ...) {`가 메서드로 잡혀 있었다 — 자바 레거시에 흔한 형태다. */
  "try", "synchronized", "do", "else", "finally", "using", "foreach", "unless", "elif", "lock",
]);

function parseArgs(argv) {
  const result = { root: process.cwd(), mode: "init", tier: "Auto", config: null, quiet: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--root") result.root = argv[++i];
    else if (arg === "--mode") result.mode = argv[++i];
    else if (arg === "--tier") result.tier = argv[++i];
    else if (arg === "--config") result.config = argv[++i];
    else if (arg === "--apply-ai-patch") result.applyAiPatch = argv[++i];
    else if (arg === "--quiet") result.quiet = true;
    else if (arg === "--check-stale") result.checkStale = true;
    else if (arg === "--help" || arg === "-h") result.help = true;
    else throw new Error(`알 수 없는 인자: ${arg}`);
  }
  if (!result.applyAiPatch && !new Set(["init", "incremental", "feature-scoped"]).has(result.mode)) {
    throw new Error(`지원하지 않는 mode: ${result.mode}`);
  }
  if (!new Set(["Auto", "Lite", "Standard", "Full"]).has(result.tier)) {
    throw new Error(`지원하지 않는 tier: ${result.tier}`);
  }
  return result;
}

function recommendedTier(score) {
  if (score <= 50) return "Lite";
  if (score <= 120) return "Standard";
  return "Full";
}

function calculateComplexity(facts, config, sourceFileCount) {
  const rels = facts.map((item) => item.rel);
  const sourceScore = sourceFileCount;
  const db = facts.some((item) => item.sqls.length || item.tables.length || item.boundaries.length)
    || config.workspaces.some((item) => /sql|jpa|hibernate|mybatis|ibatis|prisma|sequelize|typeorm/i.test(item.stack));
  const legacy = rels.some((rel) => /(^|\/)WEB-INF\/web\.xml$/i.test(rel))
    || rels.filter((rel) => /\.jsp$/i.test(rel)).length >= 50
    || config.workspaces.some((item) => /struts|ibatis|jsp|egov/i.test(item.stack));
  const manifestCount = rels.filter((rel) => /(^|\/)(pom\.xml|build\.gradle|package\.json)$/i.test(rel)).length;
  const multiModule = config.workspace_mode || manifestCount >= 2;
  const external = facts.some((item) => item.communications.length || item.consumers.length);
  const signals = {
    source_files: sourceScore,
    db_or_orm: db ? 30 : 0,
    legacy_stack: legacy ? 40 : 0,
    multi_module: multiModule ? 20 : 0,
    external_system: external ? 20 : 0,
  };
  const score = Object.values(signals).reduce((sum, value) => sum + value, 0);
  return { score, signals, recommended_tier: recommendedTier(score) };
}

function slash(path) {
  return path.split(sep).join("/");
}

function readJson(path, fallback = null) {
  try {
    /* PowerShell로 만든 JSON에는 BOM이 붙는다. 이 저장소의 Python 쪽은 전부 utf-8-sig로 읽으므로 여기서도 벗긴다. */
    return JSON.parse(readFileSync(path, "utf8").replace(/^﻿/, ""));
  } catch {
    return fallback;
  }
}

/*
 * 인덱스 JSON을 항상 2칸 들여쓰기로 직렬화하면 대형 저장소에서 쓰기 비용이 크게 늘어난다
 * (실측: call_graph.json이 들여쓰기 47.9MB vs 레코드당 한 줄 34.6MB — 28% 차이가 그대로 I/O로 간다).
 *
 * 그렇다고 통째로 압축하면 파일이 **한 줄**이 되는데, `impact-analyzer`·`logic-tracer`·`qa`가
 * `call_graph.json`을 Read로 직접 열게 되어 있어서 긴 줄이 잘려 나간다. 조용한 손실이라 더 나쁘다.
 *
 * 그래서 큰 배열만 **레코드당 한 줄**로 쓴다 — 크기는 압축본과 같고(34.6MB), 줄 길이는 레코드 하나로
 * 묶여 있어 Read로도 안전하며, 직렬화 비용도 들여쓰기보다 싸다(238ms vs 253ms).
 * `_meta` 같은 작은 값은 그대로 들여쓰기를 유지해 사람이 읽을 수 있게 둔다. JSON 값 자체는 동일하다.
 */
/* 레코드가 이만큼 쌓인 배열이 하나라도 있으면 "큰 인덱스"로 보고 레코드당 한 줄로 쓴다.
 * 판정에 시험 직렬화를 쓰지 않는 이유는 그 자체가 비싸기 때문이다 — 길이만 세면 공짜다. */
const RECORD_PER_LINE_MIN_ITEMS = 200;

function serializeJson(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return JSON.stringify(value, null, 2);
  const entries = Object.entries(value).filter(([, item]) => item !== undefined);
  const large = entries.some(([, item]) => Array.isArray(item) && item.length >= RECORD_PER_LINE_MIN_ITEMS);
  if (!large) return JSON.stringify(value, null, 2);
  const parts = entries.map(([key, item]) => (
    Array.isArray(item) && item.length >= RECORD_PER_LINE_MIN_ITEMS
      ? `${JSON.stringify(key)}: [\n${item.map((record) => JSON.stringify(record)).join(",\n")}\n]`
      : `${JSON.stringify(key)}: ${JSON.stringify(item, null, 2)}`
  ));
  return `{\n${parts.join(",\n")}\n}`;
}

function atomicJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.tmp-${process.pid}`;
  writeFileSync(temp, `${serializeJson(value)}\n`, "utf8");
  try {
    renameSync(temp, path);
  } catch (error) {
    if (!existsSync(path) || !["EEXIST", "EPERM"].includes(error.code)) {
      rmSync(temp, { force: true });
      throw error;
    }
    try {
      rmSync(path, { force: true });
      renameSync(temp, path);
    } catch (replaceError) {
      rmSync(temp, { force: true });
      throw replaceError;
    }
  }
}

/*
 * 정렬은 반드시 로케일과 무관해야 한다. `localeCompare`는 OS 로케일에서 collator를 가져오므로
 * 한국어 윈도우(ko-KR)와 리눅스/CI(en-US)가 **다른 순서**를 낸다 — 실측에서 한글 파일명이
 * ko-KR에서는 맨 앞, en-US에서는 뒤로 갔다. 한글 파일명이 흔한 레거시 저장소에서 이러면
 * 소스가 같은데도 인덱스 전체가 재정렬돼 팀이 공유할 수 없는 diff가 된다.
 */
function byCodeUnit(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function isIncluded(rel, includePaths) {
  return includePaths.some((scope) => !scope || rel === scope || rel.startsWith(`${scope}/`));
}

function listFiles(root, includePaths = [""], config = null) {
  const output = [];
  const excluded = [];
  function walk(dir, relDir = "") {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (EXCLUDED_DIRS.has(entry.name)) continue;
        if (relDir === "plugins" && entry.name === "AX-Harness") continue;
        walk(join(dir, entry.name), join(relDir, entry.name));
        continue;
      }
      const full = join(dir, entry.name);
      const ext = extname(entry.name).toLowerCase();
      if (!SOURCE_EXTENSIONS.has(ext) && !MANIFEST_FILES.has(entry.name)) continue;
      const rel = slash(relative(root, full));
      if (!isIncluded(rel, includePaths)) continue;
      const stats = statSync(full);
      if (stats.size > MAX_FILE_BYTES) continue;
      const reason = vendorReason(rel, full, stats.size, ext, config) || testReason(rel, config);
      if (reason) { excluded.push({ file: rel, reason, bytes: stats.size }); continue; }
      output.push({ full, rel, stats });
    }
  }
  walk(root);
  return { files: output.sort((a, b) => byCodeUnit(a.rel, b.rel)), excluded };
}

/* 무엇을 왜 뺐는지 _meta에 남긴다. 조용히 빠지면 "왜 이 파일이 인덱스에 없지"를 추적할 수 없다. */
function buildExclusionSummary(excluded) {
  const byReason = {};
  for (const item of excluded) {
    const key = item.reason.split(":")[0];
    byReason[key] = (byReason[key] || 0) + 1;
  }
  return {
    count: excluded.length,
    by_reason: byReason,
    bytes: excluded.reduce((sum, item) => sum + item.bytes, 0),
    files: excluded.slice(0, 100).map((item) => `${item.file} (${item.reason})`),
  };
}

function discoverUnsupportedFiles(root, includePaths = [""]) {
  const output = [];
  function walk(dir, relDir = "") {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (EXCLUDED_DIRS.has(entry.name)) continue;
        if (relDir === "plugins" && entry.name === "AX-Harness") continue;
        walk(join(dir, entry.name), join(relDir, entry.name));
        continue;
      }
      const ext = extname(entry.name).toLowerCase();
      if (!DISCOVERY_ONLY_EXTENSIONS.has(ext)) continue;
      const rel = slash(relative(root, join(dir, entry.name)));
      if (isIncluded(rel, includePaths)) output.push(rel);
    }
  }
  walk(root);
  return output.sort();
}

function loadConfig(root, configArg) {
  const configPath = configArg ? (isAbsolute(configArg) ? configArg : join(root, configArg)) : join(root, "_workspace", "indexer-config.json");
  const config = readJson(configPath, {}) || {};
  const includePaths = Array.isArray(config.include_paths) && config.include_paths.length
    ? config.include_paths
      .map((item) => slash(String(item).trim().replace(/^\.\//, "").replace(/\/$/, "")))
      .map((item) => item === "." ? "" : item)
      .filter((item) => item !== ".." && !item.startsWith("../"))
    : [""];
  const workspaces = Array.isArray(config.workspaces) && config.workspaces.length
    ? config.workspaces.map((item) => ({
        id: item.id || "root",
        path: slash((item.path || "").replace(/^\.\//, "").replace(/\/$/, "")),
        kind: item.kind || "unknown",
        stack: item.stack || "unknown",
        calls_backend_api: Boolean(item.calls_backend_api),
      }))
    : [{ id: "root", path: "", kind: config.kind || "unknown", stack: config.stack || "unknown", calls_backend_api: false }];
  const allowedLayouts = new Set(["single-root", "monorepo", "paired-roots", "selected-paths"]);
  const initLayout = allowedLayouts.has(config.init_layout)
    ? config.init_layout
    : (config.workspace_mode ? "monorepo" : (includePaths.some(Boolean) ? "selected-paths" : "single-root"));
  return {
    init_layout: initLayout, workspace_mode: Boolean(config.workspace_mode), workspaces,
    include_paths: includePaths.length ? includePaths : [""],
    /*
     * vendor_exclude/test_exclude 이스케이프 해치가 이 반환 객체에서 빠져 있어 indexer-config.json에
     * "vendor_exclude": false를 둬도 조용히 무시되던 버그(2026 발견) — vendorReason/testReason이
     * 받는 config가 바로 이 객체라 여기 없으면 두 함수 모두 항상 undefined만 본다.
     */
    vendor_exclude: config.vendor_exclude, test_exclude: config.test_exclude,
  };
}

function workspaceFor(rel, config) {
  const matches = config.workspaces
    .filter((item) => !item.path || rel === item.path || rel.startsWith(`${item.path}/`))
    .sort((a, b) => b.path.length - a.path.length);
  return matches[0] || config.workspaces[0];
}

function buildLineIndex(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i += 1) if (text.charCodeAt(i) === 10) starts.push(i + 1);
  return (offset) => {
    let low = 0;
    let high = starts.length;
    while (low + 1 < high) {
      const mid = (low + high) >> 1;
      if (starts[mid] <= offset) low = mid;
      else high = mid;
    }
    return low + 1;
  };
}

/*
 * lineIndex()는 본문 전체를 문자 단위로 훑어 줄 시작 오프셋 배열을 만든다 — 파일 크기에 정비례한다.
 * 그런데 한 파일을 처리하는 동안 extractSymbols·extractBindings·extractApi·extractSql·
 * extractTransactions·extractExternalIo·extractEnv가 각자 이걸 다시 만들어서 같은 스캔이
 * 파일당 7회 반복됐다. analyzeFile은 한 번에 파일 하나만 처리하고 모든 추출기에 같은
 * text/clean 문자열 *레퍼런스*를 넘기므로 직전 2건만 캐시하면 전부 적중한다.
 * (문자열을 붙들고 있게 되지만 최대 2개 = 파일 1개분이라 메모리 영향은 없다.)
 */
const LINE_INDEX_CACHE = [];
function lineIndex(text) {
  for (let i = 0; i < LINE_INDEX_CACHE.length; i += 1) {
    if (LINE_INDEX_CACHE[i].text === text) return LINE_INDEX_CACHE[i].at;
  }
  const at = buildLineIndex(text);
  LINE_INDEX_CACHE.unshift({ text, at });
  if (LINE_INDEX_CACHE.length > 2) LINE_INDEX_CACHE.length = 2;
  return at;
}

/*
 * "offset을 감싸는 것 중 start가 가장 큰 항목" 조회(ownerAt·트랜잭션 진입 메서드)와
 * "line 이후 첫 메서드" 조회(nextMethod)는 원래 매 호출마다 배열 전체를 filter+sort 했다.
 * 항목 m개·매치 k개면 O(k·m log m)이라 심볼이 많은 레거시 파일 하나가 수십 초를 먹었다
 * (실측: 3.8MB JS 파일 12.5초 중 8.0초가 ownerAt).
 * 배열당 한 번만 정렬해 두고 이분 탐색으로 O(log m)에 찾는다. 정렬 결과는 배열
 * 레퍼런스에 캐시하고, 배열이 자란 경우(길이 변화)에만 다시 만든다.
 */
const RANGE_FINDER_CACHE = new WeakMap();
function rangeFinder(items) {
  const cached = RANGE_FINDER_CACHE.get(items);
  if (cached && cached.size === items.length) return cached;
  /*
   * 원래 코드는 `sort((a, b) => b.start - a.start)[0]`이었고 Array.sort가 안정 정렬이므로
   * start가 같은 항목이 여럿이면 **배열에서 먼저 나온 것**이 선택됐다.
   * 그래서 오름차순 정렬본에도 원래 순서(order)를 실어 두고, 동률 구간에서는 order가 가장 작은
   * 것을 고른다 — 그러지 않으면 동률일 때 마지막 항목이 뽑혀 결과가 달라진다.
   */
  const sorted = items.map((item, order) => ({ item, order }))
    .sort((a, b) => a.item.start - b.item.start || a.order - b.order);
  /* maxEnd[i] = sorted[0..i]의 end 최댓값 — 감싸는 항목이 없을 때 즉시 빠져나오기 위한 것. */
  const maxEnd = new Array(sorted.length);
  let running = -Infinity;
  for (let i = 0; i < sorted.length; i += 1) {
    running = Math.max(running, sorted[i].item.end);
    maxEnd[i] = running;
  }
  const finder = {
    size: items.length,
    at(offset) {
      let low = -1;
      let high = sorted.length;
      while (low + 1 < high) {
        const mid = (low + high) >> 1;
        if (sorted[mid].item.start <= offset) low = mid;
        else high = mid;
      }
      for (let i = low; i >= 0; i -= 1) {
        if (maxEnd[i] <= offset) return undefined;
        if (offset >= sorted[i].item.end) continue;
        /* start가 같은 구간 전체에서 원래 순서가 가장 앞선 것을 고른다. */
        let best = sorted[i];
        for (let j = i - 1; j >= 0 && sorted[j].item.start === sorted[i].item.start; j -= 1) {
          if (offset < sorted[j].item.end && sorted[j].order < best.order) best = sorted[j];
        }
        return best.item;
      }
      return undefined;
    },
  };
  RANGE_FINDER_CACHE.set(items, finder);
  return finder;
}

const LINE_ORDER_CACHE = new WeakMap();
function lineOrdered(methods) {
  const cached = LINE_ORDER_CACHE.get(methods);
  if (cached && cached.length === methods.length) return cached;
  /* Array.prototype.sort는 안정 정렬이라 같은 line끼리는 원래 순서가 보존된다 —
   * filter+sort로 첫 항목을 고르던 기존 동작과 결과가 동일하다. */
  const sorted = [...methods].sort((a, b) => a.line - b.line);
  LINE_ORDER_CACHE.set(methods, sorted);
  return sorted;
}

// 문자열과 줄바꿈은 보존하고 주석 문자만 공백으로 바꿔 line/offset을 안정적으로 유지한다.
function stripComments(text, ext) {
  let output = "";
  let state = "code";
  let quote = "";
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    const n = text[i + 1];
    if (state === "line") {
      if (c === "\n") { state = "code"; output += c; } else output += " ";
    } else if (state === "block") {
      if (c === "*" && n === "/") { output += "  "; i += 1; state = "code"; }
      else output += c === "\n" ? "\n" : " ";
    } else if (state === "string") {
      output += c;
      if (c === "\\") { output += n || ""; i += 1; }
      else if (c === quote) state = "code";
    } else if (c === "/" && n === "/") {
      output += "  "; i += 1; state = "line";
    } else if (c === "/" && n === "*") {
      output += "  "; i += 1; state = "block";
    } else if (c === "#" && ext === ".py") {
      output += " "; state = "line";
    } else if (c === "\"" || c === "'" || c === "`") {
      output += c; quote = c; state = "string";
    } else output += c;
  }
  return output;
}

/*
 * 문자열 리터럴을 문자 단위로 정확히 토큰화한다(정규식 전역 매칭 대신). extractSql의 rawSql
 * 폴백이 예전에 정규식(`"..."{8,1000}`)으로 짝을 지었는데, 8자 미만 짧은 문자열(`""`,
 * `Session["ID"]`의 `"ID"` 등)을 건너뛰다가 서로 다른 문자열의 여는/닫는 따옴표를 잘못
 * 짝지어 그 사이의 실제 코드를 "문자열"로 오인하고 정작 그 안에 있는 진짜 SQL 리터럴은
 * 통째로 삼켜버렸다(2026-08-27 발견 — MyBatis/JPA 매퍼 없이 인라인 SQL 문자열만 쓰는
 * .NET ADO.NET류 프로젝트에서 sql_usage.json이 항상 0건으로 남는 원인이었다). 주석이 섞이면
 * 안에 있는 따옴표가 또 같은 오정렬을 일으키므로, 호출부는 stripComments()로 주석을 먼저
 * 비운 텍스트(clean)를 넘겨야 한다 — 원본 text를 그대로 넘기면 이 함수도 같은 문제를 겪는다.
 */
function extractStringLiterals(text) {
  const literals = [];
  let state = "code";
  let quote = "";
  let start = -1;
  let buf = "";
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    const n = text[i + 1];
    if (state === "string") {
      if (c === "\\") { buf += c + (n || ""); i += 1; continue; }
      if (c === quote) { literals.push({ content: buf, start, end: i + 1 }); state = "code"; continue; }
      buf += c;
    } else if (c === "\"" || c === "'" || c === "`") {
      quote = c; state = "string"; start = i; buf = "";
    }
  }
  return literals;
}

function matchingBrace(text, open) {
  if (open < 0 || text[open] !== "{") return text.length;
  let depth = 0;
  let quote = "";
  for (let i = open; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === "\\") i += 1;
      else if (c === quote) quote = "";
      continue;
    }
    if (c === "\"" || c === "'" || c === "`") quote = c;
    else if (c === "{") depth += 1;
    else if (c === "}" && --depth === 0) return i + 1;
  }
  return text.length;
}

/* 파라미터 목록의 끝 괄호 위치. `def f(x = Depends(g)):`처럼 기본값에 괄호가 들어가면
 * `\([^)]*\)` 같은 정규식은 첫 `)`에서 끊겨 함수 자체를 놓친다. */
function matchingParen(text, open) {
  if (open < 0 || text[open] !== "(") return -1;
  let depth = 0;
  let quote = "";
  for (let i = open; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === "\\") i += 1;
      else if (c === quote) quote = "";
      continue;
    }
    if (c === "\"" || c === "'" || c === "`") quote = c;
    else if (c === "(") depth += 1;
    else if (c === ")" && --depth === 0) return i;
  }
  return -1;
}

function packageName(text, ext, rel) {
  if (ext === ".java" || ext === ".kt" || ext === ".kts") return text.match(/\bpackage\s+([\w.]+)/)?.[1] || "";
  if (ext === ".cs") return text.match(/\bnamespace\s+([\w.]+)/)?.[1] || "";
  if (ext === ".py") return rel.replace(/\.py$/, "").replace(/\/__init__$/, "").replaceAll("/", ".");
  if (ext === ".go") return text.match(/\bpackage\s+(\w+)/)?.[1] || dirname(rel).replaceAll("/", ".");
  return rel.replace(/\.(?:jsx?|tsx?|vue)$/, "").replaceAll("/", ".");
}

function symbolId(pkg, owner, name) {
  return [pkg, owner, name].filter(Boolean).join(".");
}

function extractLegacySymbols(text, clean, rel, workspace) {
  const ext = extname(rel).toLowerCase(); const atLine = lineIndex(text);
  const pkg = rel.replace(/\.[^.]+$/, "").replaceAll("/", ".");
  const methods = []; const seenIds = new Set(); const add = (name, offset, type = "function") => {
    const id = symbolId(pkg, "", name);
    /* methods.some() 선형 재스캔 → Set 조회 (레거시 대형 파일에서 O(m²)였다) */
    if (seenIds.has(id)) return;
    seenIds.add(id);
    methods.push({ id, name, owner: "", package: pkg, file: rel, line: atLine(offset), start: offset, end: clean.length, visibility: "unknown", workspace: workspace.id, type });
  };
  const patterns = [];
  if ([".vb", ".vbs", ".asp"].includes(ext)) patterns.push(/^(?:\s*(?:Public|Private|Protected|Friend|Static)\s+)?(?:Sub|Function)\s+(\w+)/gim);
  if (ext === ".php") patterns.push(/\bfunction\s+([A-Za-z_]\w*)\s*\(/g);
  if (ext === ".rb") patterns.push(/^[ \t]*def\s+([A-Za-z_]\w*[!?=]?)/gm);
  if ([".cbl", ".cob", ".cpy"].includes(ext)) patterns.push(/^\s{0,12}([A-Z0-9][A-Z0-9-]+)\.\s*(?:$|\*>)/gm);
  if (ext === ".abap") patterns.push(/^[ \t]*(?:FORM|METHOD|FUNCTION|MODULE)\s+([A-Za-z_]\w*)/gim);
  for (const regex of patterns) for (const match of clean.matchAll(regex)) {
    if (/^(?:IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE|WORKING-STORAGE|LINKAGE|END-IF|END-PERFORM)$/i.test(match[1])) continue;
    add(match[1], match.index);
  }
  const markup = new Set([".jsp", ".jspx", ".tag", ".aspx", ".ascx", ".ashx", ".asmx", ".xaml", ".cshtml", ".vbhtml", ".razor", ".html", ".htm"]);
  const symbols = methods.map((method) => ({ id: method.id, type: method.type, file: rel, line: method.line, package: pkg, workspace: workspace.id, origin: "deterministic-indexer", confidence: "MEDIUM" }));
  if (markup.has(ext)) symbols.push({ id: `view:${rel}`, type: "view", file: rel, line: 1, workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH" });
  return { symbols, nodes: symbols.map((item) => ({ ...item })), methods, callSites: [], injects: [], classes: [] };
}

/*
 * multiline 정규식에서 `^\s*`를 쓰면 안 된다 — `\s`는 개행을 포함하므로 `^`가 **앞쪽 빈 줄**에서
 * 매치된 뒤 `\s*`가 그 개행을 삼켜, `match.index`가 실제 정의보다 위쪽 빈 줄을 가리킨다.
 * 파이썬처럼 정의 사이에 빈 줄을 두는 것이 표준인 언어에서는 사실상 모든 심볼의 줄 번호가
 * 한 줄씩 밀렸다(실측: `class Svc`가 3행인데 2행으로, `def other`가 7행인데 6행으로 기록됨).
 * 들여쓰기만 뜻하는 자리에는 개행을 포함하지 않는 `[ \t]*`를 쓴다.
 */
function extractSymbols(text, clean, rel, workspace) {
  const ext = extname(rel).toLowerCase();
  if (!STRUCTURED_SOURCE_EXTENSIONS.includes(ext)) {
    return extractLegacySymbols(text, clean, rel, workspace);
  }
  const atLine = lineIndex(text);
  const pkg = packageName(clean, ext, rel);
  const classes = [];
  const classRegex = /(?:^|\s)(?:export\s+)?(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+|sealed\s+|data\s+|internal\s+)*(class|interface|enum|record|object)\s+(\w+)(?:\s+extends\s+([\w.]+))?(?:\s+(?:implements|:)\s*([^\n{]+))?\s*\{/gm;
  for (const match of clean.matchAll(classRegex)) {
    const open = clean.indexOf("{", match.index);
    classes.push({
      name: match[2], type: match[1], start: match.index, end: matchingBrace(clean, open), line: atLine(match.index),
      extends: match[3] || null,
      implements: (match[4] || "").split(",").map((v) => v.trim().replace(/\(.*/, "")).filter(Boolean),
    });
  }
  if (ext === ".py") {
    const pyClasses = [...clean.matchAll(/^([ \t]*)class\s+(\w+)(?:\(([^)]*)\))?\s*:/gm)];
    const lines = clean.split(/(?<=\n)/);
    const offsets = [];
    let cursor = 0;
    for (const line of lines) { offsets.push(cursor); cursor += line.length; }
    for (const match of pyClasses) {
      const indent = match[1].length;
      const startLine = atLine(match.index) - 1;
      let end = clean.length;
      for (let i = startLine + 1; i < lines.length; i += 1) {
        if (!lines[i].trim()) continue;
        const currentIndent = lines[i].match(/^\s*/)[0].replace(/\t/g, "    ").length;
        if (currentIndent <= indent) { end = offsets[i]; break; }
      }
      classes.push({ name: match[2], type: "class", start: match.index, end, line: atLine(match.index), extends: match[3]?.split(",")[0]?.trim() || null, implements: [] });
    }
  }
  const ownerAt = (offset) => rangeFinder(classes).at(offset)?.name || "";
  /*
   * 클래스 선언 직전의 애너테이션 블록을 되짚는다. `classes[i-1].end`~`classes[i].start` 범위로
   * 제한해 앞선 클래스의 애너테이션이 이 클래스 것으로 잘못 붙는 것을 막는다(2026-08-19 추가,
   * Lombok @RequiredArgsConstructor/@AllArgsConstructor + 스프링 스테레오타입 감지용).
   */
  const classAnnotationsBefore = new Map();
  for (let i = 0; i < classes.length; i += 1) {
    const item = classes[i];
    const rangeStart = i > 0 ? classes[i - 1].end : 0;
    classAnnotationsBefore.set(item.name, clean.slice(rangeStart, item.start));
  }
  const methods = [];
  /* 중복 판정을 methods.some() 선형 재스캔에서 Set 조회로 바꾼다 — 메서드가 많은 파일에서 O(m²)였다. */
  const seenMethods = new Set();
  const pushMethod = (name, index, open, visibility = "unknown") => {
    if (!name || CALL_KEYWORDS.has(name)) return;
    const owner = ownerAt(index);
    const id = symbolId(pkg, owner, name);
    const line = atLine(index);
    const key = `${id}@${line}`;
    if (seenMethods.has(key)) return;
    seenMethods.add(key);
    methods.push({ id, name, owner, package: pkg, file: rel, line, start: index, end: matchingBrace(clean, open), visibility, workspace: workspace.id });
  };

  if ([".java", ".cs", ".kt", ".kts"].includes(ext)) {
    /*
     * 이름 캡처 앞의 `(?<!@)`가 핵심이다. 이게 없으면 **애너테이션이 메서드로 잡히고 진짜 메서드는 사라진다.**
     *
     *   @GetMapping("/list")
     *   public String list(SearchVO vo, Model model) {
     *
     * 파라미터 부분 `[^;{}]*`가 개행과 괄호를 가리지 않으므로 `("/list")⏎ public String list(SearchVO vo, Model model)`
     * 전체를 하나의 인자 목록으로 삼켜 `GetMapping`이 메서드 이름이 되고 `list`는 인덱스에서 통째로 빠졌다.
     * Spring MVC 컨트롤러가 전부 이 형태라 요청 진입점이 사라졌다 — 신입이 "이 화면이 어디로 들어가나"를
     * 인덱스에서 찾을 수 없다는 뜻이다(2026-08-16 가상 프로젝트 실행 중 발견).
     *
     * `[^;{}()]*`로 괄호를 막는 방법은 쓸 수 없다 — `@RequestParam("x") String x` 같은 파라미터 애너테이션이
     * 정당하게 괄호를 포함하기 때문이다. 이름 바로 앞이 `@`인 경우만 배제하는 편이 정확하고 부작용이 없다.
     */
    const methodRegex = /\b(public|protected|private|internal)?\s*(?:static\s+|final\s+|abstract\s+|synchronized\s+|override\s+|open\s+|suspend\s+|async\s+)*(?:fun\s+)?(?:[\w<>,.?\[\]]+\s+)?(?<!@)\b(\w+)\s*\([^;{}]*\)\s*(?:throws\s+[^\n{]+)?\s*\{/gm;
    for (const match of clean.matchAll(methodRegex)) pushMethod(match[2], match.index, clean.indexOf("{", match.index), match[1] || "package");
  } else if (JS_FAMILY_EXTENSIONS.includes(ext)) {
    /*
     * TypeScript 반환 타입 주석(`): Promise<Order> {`)을 허용한다.
     * 이 부분이 없으면 `function f(): T {` 형태가 전부 심볼에서 빠져
     * 반환 타입을 쓰는 TypeScript 프로젝트의 함수가 인덱싱되지 않는다.
     * Python 분기는 이미 `-> type`을 허용하고 있었다.
     */
    const returnType = "(?::\\s*[^{;=]+)?";
    const functionRegex = new RegExp(
      `\\b(?:export\\s+)?(?:default\\s+)?(?:async\\s+)?function\\s*\\*?\\s*(\\w+)\\s*\\([^)]*\\)\\s*${returnType}\\s*\\{`
      + `|\\b(?:export\\s+)?(?:const|let|var)\\s+(\\w+)\\s*=\\s*(?:async\\s*)?(?:\\([^)]*\\)|\\w+)\\s*${returnType}\\s*=>\\s*\\{`,
      "gm",
    );
    for (const match of clean.matchAll(functionRegex)) pushMethod(match[1] || match[2], match.index, clean.indexOf("{", match.index), "module");
    /* Nexacro XFDL/XJS와 레거시 JS의 대표 선언: this.fnName = function(...) { ... } */
    const assignedFunctionRegex = /\b(?:this\.)?([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?function\s*\([^)]*\)\s*\{/gm;
    for (const match of clean.matchAll(assignedFunctionRegex)) pushMethod(match[1], match.index, clean.indexOf("{", match.index), "module");
    const classMethodRegex = new RegExp(`^[ \\t]*(?:public\\s+|private\\s+|protected\\s+|static\\s+|async\\s+)*(\\w+)\\s*\\([^)]*\\)\\s*${returnType}\\s*\\{`, "gm");
    for (const match of clean.matchAll(classMethodRegex)) if (ownerAt(match.index)) pushMethod(match[1], match.index, clean.indexOf("{", match.index), "unknown");
  } else if (ext === ".py") {
    /*
     * 파라미터는 정규식으로 세지 않고 괄호 깊이로 닫는다.
     * `def list_users(current_user = Depends(get_current_user)):`처럼 기본값에 괄호가 있으면
     * 한 줄 정규식이 첫 `)`에서 끊겨 함수가 통째로 누락됐다 — FastAPI 라우트 핸들러가
     * 전부 이 형태라 호출 그래프에서 엔드포인트가 사라지는 원인이었다.
     */
    const pyDefRegex = /^([ \t]*)(?:async\s+)?def\s+(\w+)\s*\(/gm;
    const all = [];
    for (const match of clean.matchAll(pyDefRegex)) {
      const close = matchingParen(clean, match.index + match[0].length - 1);
      if (close < 0) continue;
      const tail = clean.slice(close + 1, clean.indexOf("\n", close) + 1 || undefined);
      if (!/^\s*(?:->[^:]+)?:/.test(tail)) continue;
      all.push(match);
    }
    /*
     * `all.slice(i + 1).find(...)`는 매 def마다 뒤쪽 배열을 통째로 복사해 O(n²)였다.
     * 들여쓰기 스택을 뒤에서 앞으로 한 번만 훑으면 각 def의 "다음 형제/상위" def를 O(n)에 구한다.
     */
    const nextSibling = new Array(all.length);
    const indentStack = [];
    for (let i = all.length - 1; i >= 0; i -= 1) {
      const indent = all[i][1].length;
      while (indentStack.length && all[indentStack[indentStack.length - 1]][1].length > indent) indentStack.pop();
      nextSibling[i] = indentStack.length ? all[indentStack[indentStack.length - 1]] : undefined;
      indentStack.push(i);
    }
    for (let i = 0; i < all.length; i += 1) {
      const match = all[i];
      const next = nextSibling[i];
      const owner = ownerAt(match.index);
      const id = symbolId(pkg, owner, match[2]);
      methods.push({ id, name: match[2], owner, package: pkg, file: rel, line: atLine(match.index), start: match.index, end: next?.index || clean.length, visibility: match[2].startsWith("_") ? "private" : "public", workspace: workspace.id });
    }
  } else if (ext === ".go") {
    const goRegex = /\bfunc\s*(?:\([^)]*\)\s*)?(\w+)\s*\([^)]*\)[^{]*\{/gm;
    for (const match of clean.matchAll(goRegex)) pushMethod(match[1], match.index, clean.indexOf("{", match.index), /^[A-Z]/.test(match[1]) ? "public" : "private");
  }

  /* classes × methods 전수 비교(O(C·M))를 owner 기준 1회 그룹핑으로 바꾼다. */
  const methodsByOwner = new Map();
  for (const method of methods) {
    if (!method.owner) continue;
    const bucket = methodsByOwner.get(method.owner);
    if (bucket) bucket.push(method);
    else methodsByOwner.set(method.owner, [method]);
  }
  const symbols = classes.map((item) => ({
    id: symbolId(pkg, "", item.name), type: item.type, file: rel, line: item.line, package: pkg,
    ...(item.extends ? { extends: item.extends } : {}), ...(item.implements.length ? { implements: item.implements } : {}),
    methods: (methodsByOwner.get(item.name) || []).map((method) => ({ name: method.name, id: method.id, line: method.line, visibility: method.visibility })),
    workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH",
  }));
  for (const method of methods.filter((item) => !item.owner)) {
    symbols.push({ id: method.id, type: "function", file: rel, line: method.line, package: pkg, workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH" });
  }
  const nodes = [
    ...classes.map((item) => ({ id: symbolId(pkg, "", item.name), type: item.type, file: rel, line: item.line, workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH" })),
    ...methods.map((item) => ({ id: item.id, type: "method", file: rel, line: item.line, visibility: item.visibility, workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH" })),
  ];
  const callSites = [];
  const callRegex = /\b([A-Za-z_$][\w$]*)(?:\s*\.\s*([A-Za-z_$][\w$]*))?\s*\(/g;
  for (const method of methods) {
    const body = clean.slice(method.start, method.end);
    for (const match of body.matchAll(callRegex)) {
      const name = match[2] || match[1];
      if (CALL_KEYWORDS.has(name) || (!match[2] && name === method.name && match.index < 120)) continue;
      /*
       * 캐스팅·체이닝 뒤의 호출(`((HashMap)(x)).get(...)`, `foo().bar()`)은 콜레직스가
       * 리시버를 못 캡처해 한정자 없는 "맨 호출"로 오인된다 — 실제로는 리시버가 있는데
       * 정규식이 식별자 하나짜리 한정자만 보기 때문이다. 이름 직전이 `.`인데 캡처된
       * 한정자가 없으면 이 경우다 — 리시버를 모르니 같은 클래스로도 억지로 몰지 않고
       * 스킵한다(2026-08-19 추가. 실측: 백엔드 "get()" 미해결 1,582건 중 다수가 이 패턴
       * — `Map.get`/`List.get` 같은 JDK 호출을 프로젝트 내부 동명 메서드로 오판할 뻔했다).
       */
      if (!match[2] && body.slice(0, match.index).replace(/\s+$/, "").endsWith(".")) continue;
      callSites.push({ caller: method.id, name, qualifier: match[2] ? match[1] : "", file: rel, line: atLine(method.start + match.index), workspace: workspace.id });
    }
  }
  const injects = [];
  const injectRegex = /(?:@Autowired|@Inject|@Resource(?:\([^)]*\))?)\s*(?:private|protected|public|lateinit\s+var|val|var)?\s*([A-Z][\w.]*)\s+(\w+)/gm;
  for (const match of clean.matchAll(injectRegex)) {
    const owner = ownerAt(match.index);
    /* 필드 *이름*(match[2])도 함께 남긴다 — `sqlSession.insert(...)`처럼 한정자로 호출할 때
     * 그 한정자가 어떤 타입인지 되짚는 유일한 근거다. 예전에는 타입만 쓰고 이름을 버렸다. */
    if (owner) injects.push({ owner: symbolId(pkg, "", owner), targetName: match[1].split(".").at(-1), fieldName: match[2], file: rel, line: atLine(match.index), workspace: workspace.id });
  }
  /*
   * 주입 애너테이션이 없는 평범한 필드 선언도 한정자 해석에 쓴다(레거시는 애너테이션 없이
   * `private SqlSessionTemplate sqlSession;`으로 두는 코드가 많다). 엣지를 만들지는 않고
   * "이 이름은 이 타입"이라는 사전으로만 쓴다.
   */
  const fields = [];
  const fieldRegex = /(?:^|\n)\s*(?:private|protected|public)\s+(?:final\s+|static\s+|volatile\s+|transient\s+)*([A-Z][\w.]*)(?:<[^>;=]*>)?\s+(\w+)\s*[;=]/gm;
  for (const match of clean.matchAll(fieldRegex)) {
    const owner = ownerAt(match.index);
    if (owner) fields.push({ owner: symbolId(pkg, "", owner), typeName: match[1].split(".").at(-1), fieldName: match[2] });
  }
  for (const item of injects) fields.push({ owner: item.owner, typeName: item.targetName, fieldName: item.fieldName });
  /* ASP.NET Core의 주입은 대부분 어노테이션이 아니라 컨트롤러 생성자 파라미터다. */
  if (ext === ".cs") for (const owner of classes) {
    const body = clean.slice(owner.start, owner.end);
    const constructor = new RegExp(`\\b${owner.name}\\s*\\(([^)]*)\\)`, "g");
    for (const match of body.matchAll(constructor)) {
      for (const parameter of match[1].split(",")) {
        const parsed = parameter.trim().match(/^(?:\[[^\]]+\]\s*)?(?:in\s+|ref\s+|out\s+)?([A-Z][\w.<>,?\[\]]*)\s+\w+/);
        if (!parsed) continue;
        const targetName = parsed[1].replace(/[<,?\[].*/, "").split(".").at(-1);
        injects.push({ owner: symbolId(pkg, "", owner.name), targetName, file: rel, line: atLine(owner.start + match.index), workspace: workspace.id });
      }
    }
  }
  /*
   * Java 생성자 주입 — Lombok 특수케이스 + 명시적 단일 생성자.
   * @RequiredArgsConstructor/@AllArgsConstructor는 컴파일 타임에 생성자를 만들어 소스에
   * @Autowired 같은 토큰이 없다 — injectRegex(위)로는 절대 못 잡는다(2026-08-19 실측:
   * Lombok DI 클래스 1,613개가 전량 누락되어 analyzer가 LLM으로 직접 찾아야 했다).
   * 명시적 생성자는 스프링 관례상(애너테이션 없이도) 정확히 1개일 때만 주입 대상으로 본다 —
   * 오버로드된 생성자가 여럿이면 어느 게 스프링이 쓰는 것인지 정규식으로 확정할 수 없어 스킵한다.
   * 스프링 빈이 아닌 평범한 POJO의 생성자까지 주입으로 오인하지 않도록, 스테레오타입 애너테이션
   * (@Service 등) 또는 Lombok DI 애너테이션이 있는 클래스만 대상으로 한다.
   */
  if (ext === ".java") {
    const SPRING_STEREOTYPE = /@(?:Service|Component|Repository|Controller|RestController|Configuration)\b/;
    const LOMBOK_CTOR = /@(RequiredArgsConstructor|AllArgsConstructor)\b/;
    for (const item of classes) {
      const annotations = classAnnotationsBefore.get(item.name) || "";
      const lombok = annotations.match(LOMBOK_CTOR);
      if (!lombok && !SPRING_STEREOTYPE.test(annotations)) continue;
      const body = clean.slice(item.start, item.end);
      if (lombok) {
        const fieldInBody = /(?:^|\n)\s*(?:private|protected|public)?\s*((?:final\s+|static\s+|volatile\s+|transient\s+)*)([A-Z][\w.]*)(?:<[^>;=]*>)?\s+(\w+)\s*[;=]/gm;
        for (const fm of body.matchAll(fieldInBody)) {
          if (/\bstatic\b/.test(fm[1])) continue;
          const isFinal = /\bfinal\b/.test(fm[1]);
          if (lombok[1] === "RequiredArgsConstructor" && !isFinal) continue;
          const targetName = fm[2].split(".").at(-1);
          injects.push({ owner: symbolId(pkg, "", item.name), targetName, fieldName: fm[3], file: rel, line: atLine(item.start + fm.index), workspace: workspace.id });
        }
        continue;
      }
      const ctorRegex = new RegExp(`\\b${item.name}\\s*\\(([^)]*)\\)\\s*(?:throws\\s+[^\\n{]+)?\\s*\\{`, "g");
      const ctorMatches = [...body.matchAll(ctorRegex)];
      if (ctorMatches.length !== 1) continue;
      for (const parameter of ctorMatches[0][1].split(",")) {
        const parsed = parameter.trim().match(/^(?:final\s+)?(?:@[\w.]+(?:\([^)]*\))?\s+)*([A-Z][\w.<>,?\[\]]*)\s+\w+/);
        if (!parsed) continue;
        const targetName = parsed[1].replace(/[<,?\[].*/, "").split(".").at(-1);
        injects.push({ owner: symbolId(pkg, "", item.name), targetName, file: rel, line: atLine(item.start + ctorMatches[0].index), workspace: workspace.id });
      }
    }
  }
  return { symbols, nodes, methods, callSites, injects, fields, classes };
}

function extractBindings(text, clean, rel, workspace, methods) {
  const atLine = lineIndex(text); const bindings = [];
  const add = (trigger, handler, type, offset) => {
    if (!handler) return;
    bindings.push({ trigger: `${rel}#${trigger}`, handler_name: handler, type, file: rel, line: atLine(offset), workspace: workspace.id });
  };
  const dotnetEvent = /(?:this\.)?([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\+=\s*(?:new\s+[\w.]+(?:<[^>]+>)?\s*\(\s*)?(?:this\.)?([A-Za-z_]\w*)/g;
  for (const match of clean.matchAll(dotnetEvent)) add(`${match[1]}.${match[2]}`, match[3], "ui_event", match.index);
  const markupEvent = /<([A-Za-z_:][\w:.-]*)\b[^>]*\b(?:OnClick|Click|OnCommand|Command)\s*=\s*["'](?:\{Binding\s+)?([A-Za-z_]\w*)[^"']*["']/gi;
  for (const match of text.matchAll(markupEvent)) add(`${match[1]}.${match[2]}`, match[2], "markup_event", match.index);
  const jsxEvent = /\b(on[A-Z][A-Za-z0-9_]*)\s*=\s*\{\s*(?:this\.)?([A-Za-z_$][\w$]*)\s*\}/g;
  for (const match of text.matchAll(jsxEvent)) add(`jsx.${match[1]}`, match[2], "ui_event", match.index);
  /*
   * Vue 템플릿 이벤트 바인딩(`@click="save"`, `v-on:click="save"`). 인덱서는 `<script>` 블록만
   * 읽고 `<template>`은 안 읽어서(index_extractor_vue.py 설계상 의도적 스킵) 이 바인딩이 완전히
   * 안 잡혔다(2026-08-19 실측, 프론트엔드 195건이 analyzer가 직접 판정). `text`(원문, 마크업 포함)
   * 기준이라 `<template>` 안까지 정규식이 닿는다 — 다른 마크업 이벤트(markupEvent)와 같은 방식.
   */
  if (extname(rel).toLowerCase() === ".vue") {
    const vueEvent = /(?:@|\bv-on:)([\w-]+)(?:\.\w+)*\s*=\s*["']\s*([A-Za-z_$][\w$]*)\s*(?:\([^"']*\))?\s*["']/g;
    for (const match of text.matchAll(vueEvent)) add(`vue.${match[1]}`, match[2], "ui_event", match.index);
  }
  const scheduled = /@Scheduled\s*\(([^)]*)\)/g;
  for (const match of clean.matchAll(scheduled)) add(`scheduled:${match[1].replace(/\s+/g, " ").slice(0, 80)}`, nextMethod(methods, atLine(match.index))?.name, "scheduler", match.index);
  const main = methods.find((method) => /^(?:main|Main)$/i.test(method.name));
  if (main) add("process-entry", main.name, "process_entry", Math.max(0, main.start));
  return bindings;
}

function quotedValue(value = "") {
  return value.match(/["'`]([^"'`]*)["'`]/)?.[1] || "";
}

function normalizePath(path) {
  const value = (`/${path || ""}`).replace(/\/+/g, "/").replace(/\/\/+/, "/");
  return value.replace(/\$\{[^}]+\}|\{[^}]+\}|:\w+|\[[^\]]+\]/g, "{param}").replace(/\/+/g, "/").replace(/\/$/, "") || "/";
}

function pythonModule(rel) {
  return slash(rel).replace(/\.py$/i, "").replace(/\/__init__$/i, "").replaceAll("/", ".");
}

function resolvePythonImport(ownerModule, source) {
  if (!source.startsWith(".")) return source;
  const dots = source.match(/^\.+/)?.[0].length || 0;
  const suffix = source.slice(dots);
  const parts = ownerModule.split(".").slice(0, -1);
  for (let i = 1; i < dots; i += 1) parts.pop();
  return [...parts, suffix].filter(Boolean).join(".");
}

function extractFastApiMeta(text, clean, rel) {
  if (!rel.toLowerCase().endsWith(".py")) return null;
  const module = pythonModule(rel);
  const constants = [];
  for (const match of clean.matchAll(/^[ \t]*([A-Z][A-Z0-9_]*)\s*(?::[^=\n]+)?=\s*[rubfRUBF]*(["'])([^\n]*?)\2\s*$/gm)) {
    constants.push({ name: match[1], value: match[3], module });
  }
  const imports = {};
  for (const match of clean.matchAll(/^[ \t]*from\s+([.\w]+)\s+import\s+([^\n#]+)/gm)) {
    const source = resolvePythonImport(module, match[1]);
    for (const entry of match[2].replace(/[()]/g, "").split(",")) {
      const item = entry.trim().match(/^(\w+)(?:\s+as\s+(\w+))?$/);
      if (item) imports[item[2] || item[1]] = `${source}.${item[1]}`;
    }
  }
  for (const match of clean.matchAll(/^[ \t]*import\s+([\w.]+)(?:\s+as\s+(\w+))?/gm)) {
    imports[match[2] || match[1].split(".").at(-1)] = match[1];
  }
  const routerPrefixes = {};
  for (const match of clean.matchAll(/^[ \t]*(\w+)\s*=\s*APIRouter\s*\(([^)]*)\)/gm)) {
    const prefix = match[2].match(/\bprefix\s*=\s*([furbFURB]*["'][^"']*["']|[^,\n)]+)/)?.[1]?.trim();
    if (prefix) routerPrefixes[match[1]] = prefix;
  }
  const mounts = [];
  const includeRouter = /\binclude_router\s*\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*,([\s\S]*?)\)\s*(?:\n|$)/g;
  for (const match of clean.matchAll(includeRouter)) {
    const reference = match[1]; const head = reference.split(".")[0];
    const imported = imports[head] ? `${imports[head]}${reference.slice(head.length)}` : reference;
    const targetModule = imported.replace(/\.router$/, "");
    const prefixExpression = match[2].match(/\bprefix\s*=\s*([furbFURB]*["'][^"']*["']|[^,\n)]+)/)?.[1]?.trim() || "\"\"";
    mounts.push({ ownerModule: module, targetModule, prefixExpression });
  }
  return { module, constants, imports, routerPrefixes, mounts, appRoot: /\bFastAPI\s*\(/.test(clean) };
}

function resolveStaticPythonString(expression, constants) {
  const value = String(expression || "").trim();
  const literal = value.match(/^[furbFURB]*(["'])([\s\S]*)\1$/);
  if (literal) {
    let resolved = literal[2]; let complete = true;
    resolved = resolved.replace(/\{([^}]+)\}/g, (_, reference) => {
      const name = reference.trim().split(".").at(-1);
      if (!constants.has(name)) { complete = false; return ""; }
      return constants.get(name);
    });
    return complete ? resolved : null;
  }
  const name = value.split(".").at(-1);
  return constants.get(name) ?? null;
}

function joinApiPath(...parts) {
  return normalizePath(parts.filter(Boolean).join("/"));
}

function composeFastApiEndpoints(facts, endpoints) {
  const metas = facts.map((item) => item.fastApi).filter(Boolean);
  if (!metas.length) return endpoints;
  const constants = new Map(); const conflicts = new Set();
  for (const item of metas.flatMap((meta) => meta.constants || [])) {
    if (constants.has(item.name) && constants.get(item.name) !== item.value) conflicts.add(item.name);
    else constants.set(item.name, item.value);
  }
  for (const name of conflicts) constants.delete(name);
  const prefixes = new Map(); const queue = [];
  for (const meta of metas.filter((item) => item.appRoot)) {
    prefixes.set(meta.module, new Set([""])); queue.push(meta.module);
  }
  const resolvedMounts = metas.flatMap((meta) => meta.mounts || []).map((mount) => ({
    ...mount, prefix: resolveStaticPythonString(mount.prefixExpression, constants),
  }));
  const unresolvedTargets = new Set(resolvedMounts.filter((mount) => mount.prefix === null).map((mount) => mount.targetModule));
  const mounts = resolvedMounts.filter((mount) => mount.prefix !== null);
  if (!queue.length) for (const owner of new Set(mounts.map((mount) => mount.ownerModule))) {
    if (mounts.some((mount) => mount.targetModule === owner)) continue;
    prefixes.set(owner, new Set([""])); queue.push(owner);
  }
  while (queue.length) {
    const owner = queue.shift();
    for (const mount of mounts.filter((item) => item.ownerModule === owner)) {
      const target = prefixes.get(mount.targetModule) || new Set(); const before = target.size;
      for (const base of prefixes.get(owner) || [""]) target.add(joinApiPath(base, mount.prefix));
      prefixes.set(mount.targetModule, target);
      if (target.size > before) queue.push(mount.targetModule);
    }
  }
  const metaByModule = new Map(metas.map((meta) => [meta.module, meta]));
  return endpoints.flatMap((endpoint) => {
    if (endpoint.framework !== "fastapi") return [endpoint];
    const module = pythonModule(endpoint.file); const meta = metaByModule.get(module);
    const mounted = [...(prefixes.get(module) || new Set([""]))];
    const localExpression = meta?.routerPrefixes?.[endpoint.router];
    const localPrefix = localExpression ? resolveStaticPythonString(localExpression, constants) : "";
    if ((localExpression && localPrefix === null) || (unresolvedTargets.has(module) && !prefixes.has(module))) {
      return [{ ...endpoint, prefix_resolved: false, confidence: "LOW" }];
    }
    return mounted.map((base) => {
      const path = joinApiPath(base, localPrefix || "", endpoint.path);
      return { ...endpoint, path, path_pattern: normalizePath(path), prefix_resolved: true, id: `${endpoint.workspace}::${endpoint.method} ${normalizePath(path)}::${endpoint.handler}` };
    });
  });
}

function nextMethod(methods, line) {
  /* line 이상인 것 중 line이 가장 작은(동률이면 원래 순서가 앞선) 메서드 = 정렬 배열의 lower bound. */
  const sorted = lineOrdered(methods);
  let low = -1;
  let high = sorted.length;
  while (low + 1 < high) {
    const mid = (low + high) >> 1;
    if (sorted[mid].line >= line) high = mid;
    else low = mid;
  }
  return sorted[high];
}

/*
 * offset을 포함하는(start <= offset < end) 메서드 중 가장 안쪽(start가 가장 큰) 것을 찾는다.
 * nextMethod가 "offset 이후 첫 메서드"라면 이건 "offset을 감싸는 메서드"다 — 방향이 반대다.
 * 인라인 SQL 문자열은 메서드 본문 안에 있으므로, 그 SQL을 실제로 실행하는 메서드를 이걸로
 * 찾아야 data_flow가 endpoint→method→SQL 체인을 연결할 수 있다(2026-08-27 추가). 애노테이션
 * (@Query 등)은 메서드 선언 위에 붙어 본문 밖이라 여기 해당하지 않고 nextMethod를 쓴다.
 */
function enclosingMethod(methods, offset) {
  let best = null;
  for (const m of methods) {
    if (m.start <= offset && offset < m.end && (!best || m.start > best.start)) best = m;
  }
  return best;
}

function extractApi(text, clean, rel, workspace, methods, classes = []) {
  const atLine = lineIndex(text);
  const endpoints = [];
  const consumers = [];
  const addEndpoint = (method, path, handler, offset, extra = {}) => endpoints.push({
    id: `${workspace.id}::${method.toUpperCase()} ${normalizePath(path)}::${handler || basename(rel)}`,
    workspace: workspace.id, source: "local", method: method.toUpperCase(), path: path || "/", path_pattern: normalizePath(path),
    handler: handler || basename(rel), file: rel, line: atLine(offset), origin: "deterministic-indexer", confidence: "HIGH", ...extra,
  });
  const addConsumer = (callType, method, path, offset, fn = "") => consumers.push({
    id: `${workspace.id}::${rel}:${atLine(offset)}::${method.toUpperCase()} ${normalizePath(path)}`,
    workspace: workspace.id, source: "local", call_type: callType, method: method.toUpperCase(), path_literal: path,
    path_pattern: normalizePath(path), file: rel, line: atLine(offset), ...(fn ? { function: fn } : {}),
    consumer_kind: workspace.kind, origin: "deterministic-indexer", confidence: path.includes("+") ? "MEDIUM" : "HIGH",
  });
  const classBaseAt = (offset) => {
    const owner = classes.filter((item) => item.start <= offset && offset < item.end).sort((a, b) => b.start - a.start)[0];
    if (!owner) return "";
    const prefix = clean.slice(Math.max(0, owner.start - 600), owner.start);
    const java = [...prefix.matchAll(/@RequestMapping\s*(?:\(([^)]*)\))?/g)].at(-1);
    /* [Route("api/[controller]")]의 내부 ]를 속성 종료로 오인하지 않는다. */
    const csharpRoute = [...prefix.matchAll(/\[Route\s*\(\s*(["'])([\s\S]*?)\1\s*\)\]/g)].at(-1);
    let value = quotedValue(java?.[1] || csharpRoute?.[0]);
    if (csharpRoute && owner) value = value.replace(/\[controller\]/gi, owner.name.replace(/Controller$/i, ""));
    return value;
  };

  const javaRoute = /@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?/gm;
  for (const match of clean.matchAll(javaRoute)) {
    const after = clean.slice(match.index + match[0].length, match.index + match[0].length + 500);
    if (/^\s*(?:public\s+)?(?:class|interface)\b/.test(after)) continue;
    const routeMethod = match[1] === "RequestMapping"
      ? (match[2]?.match(/RequestMethod\.(GET|POST|PUT|DELETE|PATCH)/)?.[1] || "ANY")
      : match[1].replace("Mapping", "").toUpperCase();
    const path = joinApiPath(classBaseAt(match.index), quotedValue(match[2]) || "/");
    const handler = nextMethod(methods, atLine(match.index))?.id || basename(rel);
    addEndpoint(routeMethod, path, handler, match.index);
  }
  const fastApi = /@(\w+)\.(get|post|put|delete|patch)\s*\(([^)]*)\)/g;
  for (const match of clean.matchAll(fastApi)) addEndpoint(match[2], quotedValue(match[3]), nextMethod(methods, atLine(match.index))?.id, match.index, { framework: "fastapi", router: match[1] });
  const flask = /@(\w+)\.route\s*\(\s*(["'])([^"']+)\2([^)]*)\)/g;
  for (const match of clean.matchAll(flask)) {
    const declared = [...match[4].matchAll(/["'](GET|POST|PUT|DELETE|PATCH)["']/gi)].map((item) => item[1]);
    for (const method of declared.length ? declared : ["GET"]) addEndpoint(method, match[3], nextMethod(methods, atLine(match.index))?.id, match.index, { framework: "flask", router: match[1] });
  }
  const django = /\b(?:path|re_path)\s*\(\s*(["'])([^"']+)\1\s*,\s*([\w.]+)/g;
  for (const match of clean.matchAll(django)) addEndpoint("ANY", `/${match[2]}`, match[3], match.index, { framework: "django" });
  const express = /\b(?:app|router)\s*\.\s*(get|post|put|delete|patch|use)\s*\(\s*(["'`])([^"'`]+)\2\s*,\s*([\w.]+)/g;
  for (const match of clean.matchAll(express)) if (clean[match.index - 1] !== "@") addEndpoint(match[1], match[3], match[4], match.index, { framework: "express" });
  const csharp = /\[Http(Get|Post|Put|Delete|Patch)(?:\(([^\]]*)\))?\]/g;
  for (const match of clean.matchAll(csharp)) addEndpoint(match[1], joinApiPath(classBaseAt(match.index), quotedValue(match[2]) || "/"), nextMethod(methods, atLine(match.index))?.id, match.index, { framework: "aspnet" });
  /*
   * Struts <action>과 servlet-mapping.
   * 예전 정규식은 한 태그 안에서 path 뒤에 type이 오는 형태만 잡아, 속성 순서가 다르거나
   * forward/include만 있는 action을 통째로 놓쳤다(2026-08-15 실사고 — 수동 병합 스크립트로 메웠던 건).
   * 주석 처리된 설정을 살아 있는 매핑으로 세지 않도록 XML 주석은 길이를 보존하며 지운다 —
   * atLine(match.index)이 원본 줄 번호를 그대로 가리켜야 하기 때문이다.
   */
  const xmlLive = /<action\b|<servlet-mapping\b/i.test(text)
    ? text.replace(/<!--[\s\S]*?-->/g, (block) => block.replace(/[^\n]/g, " "))
    : text;
  const struts = /<action\b([^>]*)>/gi;
  for (const match of xmlLive.matchAll(struts)) {
    const attrs = xmlAttrs(match[1]);
    if (!attrs.path) continue;
    /*
     * command 속성(Spring bean id)이 있으면 실제 비즈니스 로직을 쥔 서비스를 가리킨다 — `type`은
     * 흔히 커맨드 패턴 공용 디스패처(예: WorkerAction) 하나로 전체 액션이 몰려 있어 그것만으로는
     * data_flow 체인 추적이 불가능하다(2026-08-17 xu25-server 실측: 443개 중 434개가 같은 type).
     * `handler`는 기존 동작(데드 코드 화이트리스트 등) 보존을 위해 그대로 두고, dispatch_bean만 얹는다.
     */
    addEndpoint("ANY", attrs.path, attrs.type || attrs.forward || attrs.include || attrs.name, match.index, { framework: "struts", ...(attrs.command ? { dispatch_bean: attrs.command } : {}) });
  }
  const servletPattern = /<servlet-mapping>[\s\S]*?<servlet-name>\s*([^<]+)\s*<\/servlet-name>[\s\S]*?<url-pattern>\s*([^<]+)\s*<\/url-pattern>[\s\S]*?<\/servlet-mapping>/gi;
  for (const match of xmlLive.matchAll(servletPattern)) addEndpoint("ANY", match[2], match[1].trim(), match.index, { framework: "servlet" });
  if (/\.(?:asp|aspx|ashx|asmx)$/i.test(rel)) addEndpoint("ANY", `/${rel}`, basename(rel), 0, { framework: rel.toLowerCase().endsWith(".asp") ? "classic-asp" : "aspnet-webforms" });

  const axios = /\baxios\s*\.\s*(get|post|put|delete|patch)\s*\(\s*(["'`])([^"'`]+)\2/g;
  for (const match of clean.matchAll(axios)) addConsumer("axios", match[1], match[3], match.index);
  const fetchCall = /\b(fetch|useFetch|\$fetch)\s*\(\s*(["'`])([^"'`]+)\2\s*(?:,\s*\{([\s\S]{0,300}?)\})?/g;
  for (const match of clean.matchAll(fetchCall)) {
    const method = match[4]?.match(/method\s*:\s*["'](\w+)["']/i)?.[1] || "GET";
    addConsumer(match[1], method, match[3], match.index);
  }
  const httpClient = /\b(?:GetAsync|PostAsync|PutAsync|DeleteAsync|PatchAsync)\s*\(\s*\$?(["'])([^"']+)\1/g;
  for (const match of clean.matchAll(httpClient)) addConsumer("HttpClient", match[0].match(/(Get|Post|Put|Delete|Patch)Async/)?.[1] || "GET", match[2], match.index);
  const restSharp = /new\s+RestRequest\s*\(\s*(["'])([^"']+)\1\s*,\s*Method\.(Get|Post|Put|Delete|Patch)/g;
  for (const match of clean.matchAll(restSharp)) addConsumer("RestSharp", match[3], match[2], match.index);
  const refit = /\[(Get|Post|Put|Delete|Patch)\s*\(\s*(["'])([^"']+)\2\s*\)\]/g;
  for (const match of clean.matchAll(refit)) addConsumer("Refit", match[1], match[3], match.index, nextMethod(methods, atLine(match.index))?.id);
  const retrofit = /@(GET|POST|PUT|DELETE|PATCH)\s*\(\s*["']([^"']+)["']\s*\)/g;
  for (const match of clean.matchAll(retrofit)) addConsumer("Retrofit", match[1], match[2], match.index, nextMethod(methods, atLine(match.index))?.id);
  const form = /<form\b([^>]*)>/gi;
  for (const match of text.matchAll(form)) {
    const path = match[1].match(/\baction\s*=\s*["']([^"']+)["']/i)?.[1]; if (!path) continue;
    const method = match[1].match(/\bmethod\s*=\s*["'](\w+)["']/i)?.[1] || "GET";
    addConsumer("html-form", method, path, match.index);
  }
  const jqueryAjax = /\$\.ajax\s*\(\s*\{([\s\S]{0,600}?)\}\s*\)/g;
  for (const match of text.matchAll(jqueryAjax)) {
    const path = match[1].match(/\burl\s*:\s*["']([^"']+)["']/i)?.[1]; if (!path) continue;
    const method = match[1].match(/\b(?:type|method)\s*:\s*["'](\w+)["']/i)?.[1] || "GET";
    addConsumer("jquery-ajax", method, path, match.index);
  }
  return { endpoints, consumers };
}

/*
 * FROM/JOIN 절에서 나오지만 테이블이 아닌 것들. 걸러내지 않으면 ROWNUM이 사용 빈도 467회짜리
 * "테이블"로 잡힌다(2026-08-16 실측).
 */
const SQL_PSEUDO_TABLES = new Set([
  "dual", "rownum", "rowid", "sysdate", "systimestamp", "level", "nextval", "currval",
  "user", "sysdba", "values", "lateral", "unnest", "table", "select",
]);

/*
 * FROM 절의 콤마 구분 테이블 목록을 괄호 깊이를 세어 나눈다.
 * 예전의 부정 전방탐색 근사("콤마 뒤에 닫는 괄호가 있으면 함수 인자다")는 Oracle 페이징 관용구
 * (`FROM( SELECT ... FROM A a, B b ) X ) Y`)처럼 바깥 서브쿼리의 닫는 괄호가 뒤에 붙으면
 * 최상위 콤마까지 안 나뉘어 두 번째 테이블부터 통째로 누락됐다(2026-08-16 실측).
 * depth 0에서 닫는 괄호를 만나면 그 자리가 FROM 절의 끝이다.
 */
function splitTopLevelCommas(text) {
  const parts = [];
  let depth = 0;
  let current = "";
  for (const char of text) {
    if (char === "(") depth += 1;
    else if (char === ")") {
      if (depth === 0) break;
      depth -= 1;
    }
    if (char === "," && depth === 0) { parts.push(current); current = ""; continue; }
    current += char;
  }
  parts.push(current);
  return parts;
}

function sqlTables(sql) {
  const tables = [...sql.matchAll(/\b(?:from|join|update|into|table)\s+([\w.$"`]+)/gi)].map((match) => match[1].replace(/["`]/g, ""));
  for (const from of sql.matchAll(/\bfrom\s+([\s\S]*?)(?=\bwhere\b|\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\bunion\b|$)/gi)) {
    for (const part of splitTopLevelCommas(from[1]).slice(1)) {
      const table = part.trim().match(/^([\w.$"`]+)(?:\s+(?:as\s+)?[\w$]+)?/i)?.[1];
      if (table && !/^(?:select|join|left|right|inner|outer|full|cross)$/i.test(table)) tables.push(table.replace(/["`]/g, ""));
    }
  }
  return tables.filter((name) => !SQL_PSEUDO_TABLES.has(name.split(".").at(-1).toLowerCase()));
}

const SQL_ALIAS_STOP = new Set(["where", "left", "right", "inner", "outer", "full", "cross", "join", "on", "group", "order", "having", "union", "limit", "offset", "connect", "start"]);

function extractSqlRelations(sql, context) {
  const aliases = new Map();
  const addAlias = (tableValue, aliasValue = "") => {
    const table = String(tableValue || "").replace(/["`]/g, "");
    if (!table || table.startsWith("(")) return;
    const simple = table.split(".").at(-1);
    const alias = SQL_ALIAS_STOP.has(String(aliasValue).toLowerCase()) ? "" : String(aliasValue || "");
    aliases.set(simple.toLowerCase(), table);
    aliases.set(table.toLowerCase(), table);
    if (alias) aliases.set(alias.toLowerCase(), table);
  };
  for (const match of sql.matchAll(/\b(?:from|join)\s+([\w.$"`]+)(?:\s+(?:as\s+)?([\w$]+))?/gi)) addAlias(match[1], match[2]);
  for (const from of sql.matchAll(/\bfrom\s+([\s\S]*?)(?=\bwhere\b|\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\bunion\b|$)/gi)) {
    for (const part of splitTopLevelCommas(from[1])) {
      const match = part.trim().match(/^([\w.$"`]+)(?:\s+(?:as\s+)?([\w$]+))?/i);
      if (match) addAlias(match[1], match[2]);
    }
  }
  const relations = [];
  /*
   * 조인 조건마다 `sql.slice(0, index).split(/\r?\n/)`로 줄 번호를 세면 문자열 복사 + 분할이
   * 매치 수 × SQL 길이만큼 반복된다. 매치는 오프셋 오름차순으로 오므로 직전 위치부터
   * 증분으로 개행만 세면 SQL 전체를 한 번 훑는 비용으로 끝난다.
   */
  let scanned = 0;
  let newlines = 0;
  const lineAtOffset = (offset) => {
    for (; scanned < offset; scanned += 1) if (sql.charCodeAt(scanned) === 10) newlines += 1;
    return context.line + newlines;
  };
  for (const match of sql.matchAll(/\b([\w$]+)\.([\w$]+)\s*=\s*([\w$]+)\.([\w$]+)\b/gi)) {
    const fromTable = aliases.get(match[1].toLowerCase());
    const toTable = aliases.get(match[3].toLowerCase());
    if (!fromTable || !toTable) continue;
    const line = lineAtOffset(match.index);
    relations.push({
      type: "query_join", from_table: fromTable, from_columns: [match[2]],
      to_table: toTable, to_columns: [match[4]], sql_id: context.sql_id,
      file: context.file, line, evidence: match[0].replace(/\s+/g, " ").trim(),
      origin: "deterministic-indexer", confidence: "MEDIUM",
    });
  }
  return relations;
}

/* 키워드만 보지 않고 문장 모양까지 확인한다 — UI 문자열·번역 문구가 SQL로 잡히는 것을 막기 위함. */
function sqlStatementType(statement) {
  const normalized = statement.replace(/\\(?:r|n|t)/g, " ").replace(/\s+/g, " ").trim();
  if (/^select\s+[\s\S]+?\s+from\s+[\w$`"[\].(]+/i.test(normalized)) return "select";
  if (/^insert\s+into\s+[\w$`"[\].]+(?:\s|\()/i.test(normalized)) return "insert";
  if (/^update\s+[\w$`"[\].]+\s+set\s+/i.test(normalized)) return "update";
  if (/^delete\s+from\s+[\w$`"[\].]+(?:\s|$)/i.test(normalized)) return "delete";
  if (/^merge\s+into\s+[\w$`"[\].]+/i.test(normalized)) return "merge";
  if (/^(create|alter|drop)\s+/i.test(normalized)) return "ddl";
  return null;
}

/*
 * 쿼리 ID 상수 참조. 위 usage 정규식은 `selectList("ID")`처럼 호출 안에 리터럴이 있는 형태만 잡는데,
 * 레거시는 `String queryId = "DEMAND_..._S00";`처럼 변수에 담아 쓰는 경우가 더 많다.
 * 여기서는 모양이 맞는 리터럴을 후보로만 모으고, 실제 SQL id와 일치하는 것만 aggregate에서 남긴다.
 */
const SQL_ID_LITERAL_RE = /["']([A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,})["']/g;

function extractSql(text, clean, rel, methods) {
  const atLine = lineIndex(text);
  const sqls = [];
  const usages = [];
  const relations = [];
  const mapper = /<(select|insert|update|delete)\b[^>]*\bid\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/\1>/gi;
  const namespace = text.match(/<mapper\b[^>]*namespace\s*=\s*["']([^"']+)["']/i)?.[1] || "";
  for (const match of text.matchAll(mapper)) {
    /*
     * HTML/JSP/ASP의 <select id="cmbLanguages"> 드롭다운도 이 정규식에 걸린다.
     * 레거시 화면이 많은 프로젝트에서 실제로 수백 건이 SQL로 잘못 등록됐다 —
     * MyBatis 매퍼 파일이 아니면 본문이 SQL 모양일 때만 인정한다.
     */
    if (!namespace && !sqlStatementType(match[3])) continue;
    const id = namespace ? `${namespace}.${match[2]}` : match[2];
    sqls.push({ id, file: rel, line: atLine(match.index), type: match[1].toLowerCase(), tables: [...new Set(sqlTables(match[3]))], text_preview: match[3].replace(/\s+/g, " ").trim().slice(0, 240), origin: "deterministic-indexer", confidence: "HIGH" });
    relations.push(...extractSqlRelations(match[3], { sql_id: id, file: rel, line: atLine(match.index) }));
    if (namespace) usages.push({ sql_id: id, file: rel, line: atLine(match.index), method: id, evidence: "MyBatis mapper namespace + statement id", origin: "deterministic-indexer", confidence: "HIGH" });
  }
  /*
   * 국내 SI에서 흔한 자체 쿼리 컨테이너: <query><id>X</id><value><![CDATA[ SELECT ... ]]></value></query>.
   * MyBatis도 JPA도 아니라 위 어댑터가 전부 놓친다 — 실측(레거시 Java 4,883파일)에서 이 형식이
   * 전체 SQL의 90%였는데 519건만 잡히고 있었다. 태그명은 프레임워크마다 달라 알려진 이름만 받고,
   * 본문이 실제 SQL 모양일 때만 인정한다.
   */
  const container = /<(query|statement|sql|sqlQuery|queryString)\b[^>]*>([\s\S]*?)<\/\1>/gi;
  for (const block of text.matchAll(container)) {
    const id = block[2].match(/<id>\s*([^<]+?)\s*<\/id>/i)?.[1];
    const rawValue = block[2].match(/<value>([\s\S]*?)<\/value>/i)?.[1];
    if (!id || !rawValue) continue;
    const statement = rawValue.replace(/<!\[CDATA\[/g, "").replace(/\]\]>/g, "").trim();
    const type = sqlStatementType(statement);
    if (!type) continue;
    const line = atLine(block.index);
    sqls.push({ id, file: rel, line, type, tables: [...new Set(sqlTables(statement))], text_preview: statement.replace(/\s+/g, " ").trim().slice(0, 240), origin: "deterministic-indexer", confidence: "HIGH" });
    relations.push(...extractSqlRelations(statement, { sql_id: id, file: rel, line }));
  }
  const annotation = /@(Query|Select|Insert|Update|Delete)\s*\(\s*(["'])([\s\S]*?)\2\s*\)/gi;
  for (const match of text.matchAll(annotation)) {
    const keyword = match[3].trim().match(/^(select|insert|update|delete|create|alter|drop)/i)?.[1]?.toLowerCase();
    const type = ["create", "alter", "drop"].includes(keyword) ? "ddl" : keyword || match[1].toLowerCase().replace("query", "select");
    const id = `${rel}:${atLine(match.index)}`;
    sqls.push({ id, file: rel, line: atLine(match.index), type, tables: [...new Set(sqlTables(match[3]))], text_preview: match[3].replace(/\s+/g, " ").slice(0, 240), origin: "deterministic-indexer", confidence: "MEDIUM" });
    relations.push(...extractSqlRelations(match[3], { sql_id: id, file: rel, line: atLine(match.index) }));
    /* @Query는 메서드 선언 위에 붙으므로 그 메서드(nextMethod)를 SQL 실행 주체로 잇는다. */
    const decorated = nextMethod(methods, atLine(match.index));
    if (decorated) usages.push({ sql_id: id, file: rel, line: atLine(match.index), method: decorated.id, evidence: "SQL 애노테이션이 데코레이트한 메서드", origin: "deterministic-indexer", confidence: "MEDIUM" });
  }
  for (const lit of extractStringLiterals(clean)) {
    if (lit.content.length < 8 || lit.content.length > 1000) continue;
    const normalized = lit.content.replace(/\\(?:r|n|t)/g, " ").replace(/\s+/g, " ").trim();
    const type = normalized.match(/^select\s+[\s\S]+?\s+from\s+[\w$`"[\].]+(?:\s|$)/i) ? "select"
      : normalized.match(/^insert\s+into\s+[\w$`"[\].]+(?:\s|\()/i) ? "insert"
      : normalized.match(/^update\s+[\w$`"[\].]+\s+set\s+/i) ? "update"
      : normalized.match(/^delete\s+from\s+[\w$`"[\].]+(?:\s|$)/i) ? "delete"
      : null;
    if (!type) continue;
    const id = `${rel}:${atLine(lit.start)}:raw`;
    sqls.push({ id, file: rel, line: atLine(lit.start), type, tables: [...new Set(sqlTables(lit.content))], text_preview: normalized.slice(0, 240), origin: "deterministic-indexer", confidence: "MEDIUM" });
    relations.push(...extractSqlRelations(lit.content, { sql_id: id, file: rel, line: atLine(lit.start) }));
    /* 인라인 raw SQL은 메서드 본문 안에 있으므로 그 SQL을 실행하는 메서드(enclosingMethod)를
     * usage로 잇는다 — MyBatis/JPA 없이 ADO.NET/JDBC로 SQL을 직접 쓰는 프로젝트에서 data_flow가
     * endpoint→method→테이블 체인을 만들 수 있게 하는 연결고리다(2026-08-27 추가). */
    const owner = enclosingMethod(methods, lit.start);
    if (owner) usages.push({ sql_id: id, file: rel, line: atLine(lit.start), method: owner.id, evidence: "메서드 본문 내 인라인 SQL 리터럴", origin: "deterministic-indexer", confidence: "MEDIUM" });
  }
  const usage = /\b(?:selectOne|selectList|insert|update|delete|queryForObject|queryForList)\s*\(\s*["']([^"']+)["']/g;
  for (const match of text.matchAll(usage)) usages.push({ sql_id: match[1], file: rel, line: atLine(match.index), method: nextMethod(methods, atLine(match.index))?.id || "unknown", origin: "deterministic-indexer", confidence: "HIGH" });
  for (const match of text.matchAll(SQL_ID_LITERAL_RE)) {
    const line = atLine(match.index);
    usages.push({ sql_id: match[1], file: rel, line, method: nextMethod(methods, line)?.id || "unknown", evidence: "쿼리 ID 상수 참조", candidate: true, origin: "deterministic-indexer", confidence: "HIGH" });
  }
  return { sqls, usages, relations };
}

function extractTransactions(text, clean, rel, workspace, methods) {
  const atLine = lineIndex(text);
  const boundaries = [];
  const marker = /@Transactional(?:\(([^)]*)\))?|\b(?:session\.begin|\$transaction|(?:\w+\.)?BeginTransaction(?:Async)?|new\s+TransactionScope)\s*\(/g;
  for (const match of clean.matchAll(marker)) {
    const entry = rangeFinder(methods).at(match.index)
      || nextMethod(methods, atLine(match.index));
    if (!entry) continue;
    const args = match[1] || "";
    boundaries.push({
      id: `${entry.id}@${entry.line}`, entry_method: entry.id, file: rel, line: atLine(match.index), marker: match[0].split("(")[0],
      ...(args.match(/propagation\s*=\s*(?:Propagation\.)?(\w+)/)?.[1] ? { propagation: args.match(/propagation\s*=\s*(?:Propagation\.)?(\w+)/)[1] } : {}),
      ...(args.match(/isolation\s*=\s*(?:Isolation\.)?(\w+)/)?.[1] ? { isolation: args.match(/isolation\s*=\s*(?:Isolation\.)?(\w+)/)[1] } : {}),
      methods_in_scope: [entry.id], external_io_calls: [], workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH",
    });
  }
  return boundaries;
}

function extractExternalIo(text, clean, rel, workspace, methods) {
  const atLine = lineIndex(text);
  const communications = [];
  const patterns = [
    ["http", /\b(RestTemplate|WebClient|HttpClient|RestSharp|axios|fetch|httpx|requests)\b/g],
    ["kafka_producer", /\b(KafkaTemplate|KafkaProducer)\b/g],
    ["kafka_consumer", /@KafkaListener\s*\(([^)]*)\)/g],
    ["rabbit_consumer", /@RabbitListener\s*\(([^)]*)\)/g],
    ["file_io", /\b(FileInputStream|FileOutputStream|Files\.(?:read|write)|readFile|writeFile|open)\s*\(/g],
    ["redis", /\b(RedisTemplate|StringRedisTemplate|ioredis|redis\.createClient)\b/g],
    ["mail", /\b(JavaMailSender|smtplib|nodemailer)\b/g],
  ];
  for (const [type, regex] of patterns) {
    for (const match of clean.matchAll(regex)) {
      communications.push({ id: `${rel}:${atLine(match.index)}:${type}`, type, file: rel, line: atLine(match.index), method: nextMethod(methods, atLine(match.index))?.id || "", target: quotedValue(match[1]) || match[1] || "unknown", workspace: workspace.id, origin: "deterministic-indexer", confidence: "MEDIUM" });
    }
  }
  return communications;
}

function extractEnv(text, clean, rel, workspace) {
  const atLine = lineIndex(text);
  const profiles = [];
  const branches = [];
  const configName = basename(rel).match(/application-([^.]+)\.(?:yml|yaml|properties)$/)?.[1];
  if (configName) {
    profiles.push(configName);
    branches.push({ file: rel, line: 1, type: "config_file", marker: configName, workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH" });
  }
  const patterns = [
    ["annotation", /@Profile\s*\(([^)]*)\)|@ConditionalOnProperty\s*\(([^)]*)\)/g],
    ["code_if", /\b(?:process\.env|os\.environ|getenv|Environment\.GetEnvironmentVariable|System\.getenv|import\.meta\.env)\b[^\n;]*/g],
  ];
  for (const [type, regex] of patterns) {
    for (const match of clean.matchAll(regex)) branches.push({ file: rel, line: atLine(match.index), type, marker: match[0].slice(0, 240), workspace: workspace.id, origin: "deterministic-indexer", confidence: "HIGH" });
  }
  return { profiles, branches };
}

function extractSchema(text, rel) {
  const tables = [];
  const create = /create\s+table\s+(?:if\s+not\s+exists\s+)?([\w."`]+)\s*\(([\s\S]*?)\)\s*;/gi;
  for (const match of text.matchAll(create)) {
    const columns = [];
    const primaryKey = [];
    const foreignKeys = [];
    for (const raw of match[2].split(/,(?![^()]*\))/)) {
      const line = raw.trim();
      /*
       * `CONSTRAINT PK_TB_ORDER PRIMARY KEY (ID)` 형태를 놓치고 있었다 — 이름 붙은 제약이
       * 오라클 레거시 DDL의 표준인데, `^primary key`만 보다가 아래 `^(constraint|...)` 스킵 규칙에
       * 걸려 **PK가 통째로 버려졌다.** 실제로 가상 프로젝트 5개 테이블 전부 `primary_key: []`였다.
       */
      const pk = line.match(/^(?:constraint\s+["`]?[\w$]+["`]?\s+)?primary\s+key\s*\(([^)]+)\)/i);
      if (pk) { primaryKey.push(...pk[1].split(",").map((v) => v.trim().replace(/["`]/g, ""))); continue; }
      const fk = line.match(/^(?:constraint\s+["`]?([\w$]+)["`]?\s+)?foreign\s+key\s*\(([^)]+)\)\s+references\s+([\w."`$]+)\s*\(([^)]+)\)/i);
      if (fk) {
        foreignKeys.push({
          name: fk[1] || "", columns: fk[2].split(",").map((value) => value.trim().replace(/["`]/g, "")),
          references_table: fk[3].replace(/["`]/g, ""), references_columns: fk[4].split(",").map((value) => value.trim().replace(/["`]/g, "")),
          origin: "deterministic-indexer", confidence: "HIGH",
        });
        continue;
      }
      if (/^(constraint|foreign|unique|check)\b/i.test(line)) continue;
      const column = line.match(/^["`]?([\w$]+)["`]?\s+([\w]+(?:\s*\([^)]*\))?)([\s\S]*)$/);
      if (!column) continue;
      const inlinePk = /primary\s+key/i.test(column[3]);
      if (inlinePk) primaryKey.push(column[1]);
      const inlineFk = column[3].match(/\breferences\s+([\w."`$]+)\s*\(([^)]+)\)/i);
      if (inlineFk) foreignKeys.push({
        name: "", columns: [column[1]], references_table: inlineFk[1].replace(/["`]/g, ""),
        references_columns: inlineFk[2].split(",").map((value) => value.trim().replace(/["`]/g, "")),
        origin: "deterministic-indexer", confidence: "HIGH",
      });
      columns.push({ name: column[1], type: column[2], nullable: !/not\s+null/i.test(column[3]), primary_key: inlinePk });
    }
    tables.push({ name: match[1].replace(/["`]/g, ""), columns, primary_key: [...new Set(primaryKey)], foreign_keys: foreignKeys, indexes: [], source_file: rel, origin: "deterministic-indexer", confidence: "MEDIUM" });
  }
  /*
   * `ALTER TABLE ... ADD CONSTRAINT ... PRIMARY KEY/FOREIGN KEY ...`를 전혀 읽지 않았다.
   * 레거시 DDL은 테이블을 먼저 만들고 제약을 뒤에 몰아서 거는 형태가 매우 흔한데, 그 경우
   * 스키마에 관계가 하나도 남지 않아 위키의 ERD·"이 테이블은 무엇과 엮여 있나"가 비어 버렸다.
   */
  const tableByName = (name) => {
    const bare = name.replace(/["`]/g, "");
    return tables.find((item) => item.name.toLowerCase() === bare.toLowerCase()
      || item.name.split(".").at(-1).toLowerCase() === bare.split(".").at(-1).toLowerCase());
  };
  for (const match of text.matchAll(/alter\s+table\s+([\w."`$]+)\s+add\s+(?:constraint\s+["`]?([\w$]+)["`]?\s+)?(primary\s+key|foreign\s+key)\s*\(([^)]+)\)(?:\s*references\s+([\w."`$]+)\s*\(([^)]+)\))?/gi)) {
    const table = tableByName(match[1]);
    if (!table) continue;
    const columns = match[4].split(",").map((value) => value.trim().replace(/["`]/g, ""));
    if (/primary/i.test(match[3])) {
      table.primary_key = [...new Set([...table.primary_key, ...columns])];
      for (const column of table.columns) if (columns.includes(column.name)) column.primary_key = true;
    } else if (match[5]) {
      table.foreign_keys.push({
        name: match[2] || "", columns,
        references_table: match[5].replace(/["`]/g, ""),
        references_columns: match[6].split(",").map((value) => value.trim().replace(/["`]/g, "")),
        origin: "deterministic-indexer", confidence: "HIGH",
      });
    }
  }
  for (const match of text.matchAll(/create\s+(unique\s+)?index\s+(?:if\s+not\s+exists\s+)?["`]?([\w$]+)["`]?\s+on\s+([\w."`$]+)\s*\(([^)]+)\)/gi)) {
    const tableName = match[3].replace(/["`]/g, "");
    const table = tables.find((item) => item.name.toLowerCase() === tableName.toLowerCase() || item.name.split(".").at(-1).toLowerCase() === tableName.split(".").at(-1).toLowerCase());
    if (!table) continue;
    table.indexes.push({ name: match[2], columns: match[4].split(",").map((value) => value.trim().replace(/["`]/g, "").split(/\s+/)[0]), unique: Boolean(match[1]), origin: "deterministic-indexer", confidence: "HIGH" });
  }
  return tables;
}

/*
 * 소스 파일 디코딩.
 * 레거시 ITO 저장소는 Struts actconf XML·JSP를 EUC-KR로 저장한 경우가 흔한데, 전부 UTF-8로
 * 읽으면 한글이 U+FFFD로 깨진 채 api_contract.json과 wiki까지 그대로 전파된다(2026-08-15 실사고).
 * 판정 사다리는 BOM → 파일이 스스로 선언한 인코딩 → 유효한 UTF-8 → 레거시 폴백 순이다.
 */
const ENCODING_ALIASES = new Map([
  ["cp949", "euc-kr"], ["ms949", "euc-kr"], ["ksc5601", "euc-kr"], ["ks_c_5601", "euc-kr"],
  ["cp932", "shift_jis"], ["ms932", "shift_jis"], ["sjis", "shift_jis"],
  ["cp936", "gb18030"], ["ms936", "gb18030"],
  ["cp950", "big5"], ["ms950", "big5"],
  ["cp1252", "windows-1252"], ["ansi", "windows-1252"],
]);
/* 선언도 없고 UTF-8도 아닌 파일의 마지막 수단. 이 하네스의 대상이 한국 ITO/SI 레거시라 EUC-KR을 쓴다. */
const LEGACY_FALLBACK_ENCODING = "euc-kr";
const CHARSET_DECLARATION = /\b(?:encoding|pageEncoding|charset)\s*=\s*["']?([\w][\w.:-]*)/i;

function decoderFor(label) {
  if (!label) return null;
  const normalized = label.trim().toLowerCase();
  for (const candidate of [normalized, ENCODING_ALIASES.get(normalized)]) {
    if (!candidate) continue;
    try {
      const decoder = new TextDecoder(candidate);
      return { decoder, label: decoder.encoding };
    } catch { /* 다음 후보를 시도한다 */ }
  }
  return null;
}

/* 정규식 이스케이프 없이 비-ASCII 문자 포함 여부만 본다. */
function hasNonAscii(text) {
  for (let i = 0; i < text.length; i += 1) if (text.charCodeAt(i) > 127) return true;
  return false;
}

function strictUtf8(buffer) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    return null;
  }
}

/*
 * 줄바꿈을 LF로 정규화한다.
 *
 * 이게 없으면 CRLF 파일에서 **줄 번호가 어긋난다.** JS의 multiline 정규식에서 `^`는 바깥의 `\r`
 * 뒤에서도 매치되고, 뒤따르는 `(\s*)`가 `\n`을 삼켜버린다(예: `pyDefRegex`). 실측하면 같은 파일이
 * LF일 때 `src/app.py:3`, CRLF일 때 `src/app.py:2`로 인덱싱된다 — 인덱스가 가리키는 줄이 한 줄 밀린다.
 * 파이썬 들여쓰기 판정(`match[1]`)도 `""` 대신 `"\n"`을 받아 중첩 계산이 깨지고,
 * `\r`이 `env_branches`의 `marker` 같은 산출 문자열에도 그대로 섞여 들어간다.
 *
 * 윈도우가 기본인 ITO 현장에서는 이게 예외가 아니라 기본값이고, 팀이 인덱스를 공유하면
 * OS에 따라 같은 커밋이 서로 다른 줄 번호를 만들어 낸다. 오프셋은 어차피 내부 계산용이라
 * 여기서 한 번 정규화해도 잃는 정보가 없다.
 */
function normalizeNewlines(text) {
  return text.includes("\r") ? text.replace(/\r\n?/g, "\n") : text;
}

function decodeSource(buffer) {
  if (buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xfe) return { text: normalizeNewlines(new TextDecoder("utf-16le").decode(buffer)), encoding: "utf-16le", detected_by: "bom" };
  if (buffer.length >= 2 && buffer[0] === 0xfe && buffer[1] === 0xff) return { text: normalizeNewlines(new TextDecoder("utf-16be").decode(buffer)), encoding: "utf-16be", detected_by: "bom" };
  if (buffer.length >= 3 && buffer[0] === 0xef && buffer[1] === 0xbb && buffer[2] === 0xbf) return { text: normalizeNewlines(new TextDecoder("utf-8").decode(buffer)), encoding: "utf-8", detected_by: "bom" };
  const declared = decoderFor(CHARSET_DECLARATION.exec(buffer.subarray(0, 2048).toString("latin1"))?.[1]);
  const utf8 = strictUtf8(buffer);
  if (declared && declared.label !== "utf-8") {
    /*
     * 선언은 레거시인데 바이트가 유효한 UTF-8 멀티바이트면 실제 저장은 UTF-8이다 — 선언을 뒤집는다.
     * EUC-KR 한글 바이트열이 우연히 유효한 UTF-8 멀티바이트가 되는 경우는 사실상 없다.
     */
    if (utf8 !== null && hasNonAscii(utf8)) return { text: normalizeNewlines(utf8), encoding: "utf-8", detected_by: "declared-overridden" };
    return { text: normalizeNewlines(declared.decoder.decode(buffer)), encoding: declared.label, detected_by: "declared" };
  }
  if (utf8 !== null) return { text: normalizeNewlines(utf8), encoding: "utf-8", detected_by: declared ? "declared" : "valid-utf8" };
  return { text: normalizeNewlines(new TextDecoder(LEGACY_FALLBACK_ENCODING).decode(buffer)), encoding: LEGACY_FALLBACK_ENCODING, detected_by: "fallback" };
}

/* 어느 인코딩으로 읽혔는지 _meta에 남긴다. 추측(fallback)으로 읽은 파일이 조용히 묻히면 안 된다. */
function buildEncodingSummary(facts) {
  const byEncoding = {};
  const declaredNonUtf8 = [];
  const guessed = [];
  for (const fact of facts) {
    const info = fact.encoding || { label: "utf-8", detected_by: "valid-utf8" };
    byEncoding[info.label] = (byEncoding[info.label] || 0) + 1;
    if (info.detected_by === "fallback") guessed.push(fact.rel);
    else if (info.label !== "utf-8") declaredNonUtf8.push(fact.rel);
  }
  return {
    default_encoding: "utf-8",
    legacy_fallback: LEGACY_FALLBACK_ENCODING,
    by_encoding: byEncoding,
    declared_non_utf8_count: declaredNonUtf8.length,
    declared_non_utf8: declaredNonUtf8.slice(0, 50),
    guessed_count: guessed.length,
    guessed: guessed.slice(0, 50),
  };
}

/* XML 속성을 순서·따옴표 종류와 무관하게 읽는다. */
function xmlAttrs(source) {
  return Object.fromEntries([...source.matchAll(/([\w:.-]+)\s*=\s*"([^"]*)"|([\w:.-]+)\s*=\s*'([^']*)'/g)]
    .map((match) => [(match[1] || match[3]).toLowerCase(), match[2] ?? match[4]]));
}

/*
 * JSP/HTML의 <script src="..."> 참조 — Legacy Static JS의 JS↔JSP 매핑(client_index.json)에 쓰인다.
 * analyzer.md Step 5가 수작업 grep으로 6~10쌍만 샘플링하던 것을 전수·결정론적으로 대체한다.
 */
const SCRIPT_SRC_REGEX = /<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi;
const TEMPLATE_EXTENSIONS = new Set([".jsp", ".jspx", ".tag", ".html", ".htm"]);
function extractClientRefs(text, rel) {
  if (!TEMPLATE_EXTENSIONS.has(extname(rel).toLowerCase())) return [];
  return [...text.matchAll(SCRIPT_SRC_REGEX)].map((match) => match[1]);
}

/* CDN/번들 파일명에서 라이브러리 버전을 읽는다. `jquery-1.11.1.min.js`, `jquery@3.6.0` 둘 다 잡는다. */
const LIBRARY_VERSION_REGEX = /(jquery|bootstrap)[@.\-]v?(\d+(?:\.\d+){1,2})/i;
function detectLibraryVersions(scriptRefs) {
  const found = new Set();
  for (const src of scriptRefs) {
    const match = LIBRARY_VERSION_REGEX.exec(src);
    if (match) found.add(`${match[1].toLowerCase()}@${match[2]}`);
  }
  return [...found].sort(byCodeUnit);
}

/*
 * Spring XML 빈 정의(id→class) — Struts action의 `command` 속성(빈 id)이 가리키는 실제 서비스
 * 클래스를 찾는 데 쓰인다. `<bean id="X" class="Y"/>`, 속성 순서는 무관하게 잡는다.
 */
const SPRING_BEAN_REGEX = /<bean\b([^>]*)>/gi;
function extractSpringBeans(text, rel) {
  if (extname(rel).toLowerCase() !== ".xml") return [];
  const atLine = lineIndex(text);
  const beans = [];
  for (const match of text.matchAll(SPRING_BEAN_REGEX)) {
    const attrs = xmlAttrs(match[1]);
    if (attrs.id && attrs.class) beans.push({ id: attrs.id, className: attrs.class, file: rel, line: atLine(match.index) });
  }
  return beans;
}

function analyzeFile(file, root, config) {
  const decoded = decodeSource(readFileSync(file.full));
  const text = decoded.text;
  const ext = extname(file.rel).toLowerCase();
  const clean = stripComments(text, ext);
  const workspace = workspaceFor(file.rel, config);
  const symbolFacts = extractSymbols(text, clean, file.rel, workspace);
  const nexacro = extractNexacro(text, file.rel, workspace);
  const api = extractApi(text, clean, file.rel, workspace, symbolFacts.methods, symbolFacts.classes);
  return {
    rel: file.rel,
    encoding: { label: decoded.encoding, detected_by: decoded.detected_by },
    mtime: file.stats.mtime.toISOString(),
    size: file.stats.size,
    symbols: symbolFacts.symbols,
    nodes: symbolFacts.nodes,
    callSites: symbolFacts.callSites,
    injects: symbolFacts.injects,
    fields: symbolFacts.fields || [],
    adapters: detectAdapters(file.rel, text),
    bindings: [...extractBindings(text, clean, file.rel, workspace, symbolFacts.methods), ...nexacro.bindings],
    fastApi: extractFastApiMeta(text, clean, file.rel),
    endpoints: api.endpoints,
    consumers: [...api.consumers, ...nexacro.consumers],
    uiFlow: nexacro.uiFlow,
    ...extractSql(text, clean, file.rel, symbolFacts.methods),
    boundaries: extractTransactions(text, clean, file.rel, workspace, symbolFacts.methods),
    communications: extractExternalIo(text, clean, file.rel, workspace, symbolFacts.methods),
    env: extractEnv(text, clean, file.rel, workspace),
    tables: ext === ".sql" ? extractSchema(text, file.rel) : [],
    clientRefs: extractClientRefs(text, file.rel),
    springBeans: extractSpringBeans(text, file.rel),
  };
}

function unique(items, key) {
  const seen = new Set();
  return items.filter((item) => {
    const value = key(item);
    if (seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

/*
 * 인덱스 _meta의 시각은 KST(+09:00)로 기록한다 — agents/lib/now_kst.py와 같은 규약.
 * validator_checks._meta_field_issues가 UTC 'Z' 표기를 "지어낸 값 의심"으로 WARN하기 때문이다.
 */
function kstIso(date = new Date()) {
  return new Date(date.getTime() + 9 * 60 * 60 * 1000).toISOString().replace(/\.\d+Z$/, "+09:00");
}

function gitCommit(root) {
  try {
    return execFileSync("git", ["-C", root, "log", "-1", "--format=%H"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return null;
  }
}

/*
 * 소스 지문 — "이 인덱스가 지금 작업 트리와 맞는가"를 싸게 판정하기 위한 값이다.
 *
 * 기존에는 `_meta.latest_source_mtime`(파일 mtime)과 `git_commit`으로 판단했는데 둘 다 팀 공유에서 깨진다.
 * git은 mtime을 보존하지 않으므로 새로 clone하면 모든 파일이 "방금 수정됨"이 되어 인덱스가 항상
 * 낡은 것으로 판정된다(실측 확인). `git_commit`은 인덱스를 커밋하는 순간 HEAD가 앞서가 버려서
 * 영원히 한 커밋 뒤처진 값이 된다.
 *
 * 대신 **내용 지문**을 쓴다. git 저장소면 `git ls-files -s`(모드+blob 해시+경로)를 해싱하는데,
 * clone·OS·로케일과 무관하게 같은 내용이면 같은 값이고 실측 2ms다. git이 아니거나 실패하면
 * 파일 목록과 크기로 대체한다(같은 보장은 아니지만 없는 것보다 낫다).
 */
function sourceFingerprint(root, includePaths, files) {
  /*
   * 지문은 **인덱싱 대상 파일만** 덮는다. git이 보고하는 전체 변경을 그대로 쓰면
   * `_workspace/`나 README 같은 비대상 파일 때문에 항상 "변경됨"이 되어 쓸모가 없다
   * (실제로 첫 구현이 자기가 만든 `_workspace/`를 보고 매번 낡았다고 답했다).
   *
   * git이 있으면 커밋된 파일은 blob 해시를 그대로 쓰고(읽지 않아 빠르다), 작업 트리에서
   * 변경된 파일만 내용을 해싱한다. git이 없으면 전체 내용 해시로 대체한다.
   * 어느 경로든 결과는 clone·OS·로케일과 무관하게 같은 내용이면 같은 값이다.
   */
  const digest = (label, payload) => `${label}:${createHash("sha1").update(payload).digest("hex").slice(0, 16)}`;
  const indexed = files.map((file) => file.rel).sort(byCodeUnit);
  const contentHash = (rel) => {
    const full = join(root, rel);
    try {
      return createHash("sha1").update(readFileSync(full)).digest("hex");
    } catch {
      return "unreadable";
    }
  };
  const git = (args) => execFileSync("git", ["-C", root, ...args], {
    encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], maxBuffer: 256 * 1024 * 1024,
  });
  try {
    const blobByPath = new Map();
    for (const line of git(["ls-files", "-s"]).split("\n")) {
      /* `<mode> <blob> <stage>\t<path>` */
      const tab = line.indexOf("\t");
      if (tab < 0) continue;
      blobByPath.set(line.slice(tab + 1), line.slice(0, tab).split(" ")[1]);
    }
    if (blobByPath.size) {
      const dirty = new Set(
        git(["status", "--porcelain", "-uall"]).split("\n")
          .map((line) => line.slice(3).trim()).filter(Boolean)
          .map((rel) => (rel.includes(" -> ") ? rel.split(" -> ")[1] : rel)),
      );
      const payload = indexed
        .map((rel) => `${rel}:${!dirty.has(rel) && blobByPath.has(rel) ? blobByPath.get(rel) : contentHash(rel)}`)
        .join("\n");
      return digest("git", payload);
    }
  } catch {
    /* git이 없거나 저장소가 아니다 — 아래 폴백. */
  }
  return digest("content", indexed.map((rel) => `${rel}:${contentHash(rel)}`).join("\n"));
}

/* 커밋된 인덱스를 받은 팀원이 "다시 인덱싱해야 하나"를 LLM 없이 판정한다. */
export function indexStaleness(root) {
  const metaPath = join(resolve(root), "_workspace", "index", "_meta.json");
  if (!existsSync(metaPath)) return { stale: true, reason: "인덱스 없음" };
  const meta = readJson(metaPath, {});
  if (meta.version !== INDEXER_VERSION) return { stale: true, reason: `인덱서 버전 변경 (${meta.version} → ${INDEXER_VERSION})` };
  if (!meta.source_fingerprint) return { stale: true, reason: "지문 없는 구버전 인덱스" };
  const config = loadConfig(resolve(root), null);
  const { files } = listFiles(resolve(root), config.include_paths, config);
  const current = sourceFingerprint(resolve(root), config.include_paths, files);
  return current === meta.source_fingerprint
    ? { stale: false, reason: "소스 지문 일치 — 재인덱싱 불필요", fingerprint: current }
    : { stale: true, reason: "소스가 변경됨", fingerprint: current, indexed_fingerprint: meta.source_fingerprint };
}

/*
 * pair 설정.
 * 허브 1개에 파트너 N개를 붙일 수 있다. 구형 설정은 파트너가 하나뿐인 특수 경우이므로
 * `partner_root`/`partner_api_contract` 단일 키를 계속 읽어 기존 프로젝트를 깨지 않는다.
 * 신형은 같은 키를 여러 줄 반복하거나 `partner_root[n]` 형태를 쓴다.
 */
function pairConfig(root) {
  const path = join(root, "_workspace", "pair_config.md");
  if (!existsSync(path)) return null;
  const text = readFileSync(path, "utf8");
  const all = (name) => [...text.matchAll(new RegExp(`^${name}(?:\\[\\d+\\])?:\\s*(.+)$`, "gm"))].map((m) => m[1].trim()).filter(Boolean);
  const roots = all("partner_root");
  const contracts = all("partner_api_contract");
  const partners = roots.map((partnerRoot, index) => ({
    partner_root: partnerRoot,
    partner_api_contract: contracts[index] || join(partnerRoot, "_workspace", "index", "api_contract.json"),
  }));
  return {
    /* 하위호환: 기존 소비자는 단일 필드를 그대로 읽는다. */
    partner_root: partners[0]?.partner_root,
    partner_api_contract: partners[0]?.partner_api_contract,
    partners,
  };
}

/* sql_usage의 tables를 테이블 목록으로 뒤집는다. DDL이 없을 때만 쓰는 폴백이다. */
function deriveTablesFromSql(sqls) {
  const usage = new Map();
  for (const item of sqls) {
    for (const name of item.tables || []) {
      const key = name.toLowerCase();
      if (!usage.has(key)) usage.set(key, { name, usage_count: 0, source_sqls: [] });
      const entry = usage.get(key);
      entry.usage_count += 1;
      if (entry.source_sqls.length < 10) entry.source_sqls.push(item.id);
    }
  }
  return [...usage.values()]
    .sort((a, b) => b.usage_count - a.usage_count || byCodeUnit(a.name, b.name))
    .map((item) => ({
      name: item.name, columns: [], primary_key: [], foreign_keys: [], indexes: [],
      usage_count: item.usage_count, source_sqls: item.source_sqls,
      origin: "derived-from-sql", confidence: "MEDIUM",
    }));
}

function aggregate(facts, options, config, generatedAt, sourceFileCount, latestMtime, complexity, coverage, excludedSources = [], sourceFiles = []) {
  const symbols = unique(facts.flatMap((item) => item.symbols), (item) => item.id);
  const bindings = facts.flatMap((item) => item.bindings || []);
  const nodes = unique([...facts.flatMap((item) => item.nodes), ...bindings.map((item) => ({ id: `trigger:${item.trigger}`, type: "trigger", file: item.file, line: item.line, workspace: item.workspace, origin: "deterministic-indexer", confidence: "HIGH" }))], (item) => item.id);
  const callSites = facts.flatMap((item) => item.callSites);
  const injects = facts.flatMap((item) => item.injects);
  /*
   * 한정자 → 타입 사전. `owner클래스::필드명` → 타입명.
   * 이게 없으면 `sqlSession.insert(...)` 같은 프레임워크 호출에서 한정자가 아무 후보와도
   * 겹치지 않아 **후보 전체(오답뿐)를 그대로 LLM 판정 대기열에 넣었다.** 가상 프로젝트에서
   * 판정 대상 30건이 전부 이 형태였다 — analyzer가 파일을 열어봐도 목록에 정답이 없으니
   * 판정이 성립하지 않는데 비싼 모델이 30번 소스를 열어보게 된다.
   */
  const fieldTypes = new Map();
  for (const field of facts.flatMap((item) => item.fields || [])) {
    fieldTypes.set(`${field.owner}::${field.fieldName}`, field.typeName);
  }
  const indexedSimpleNames = new Set(nodes.map((item) => item.id.split(".").at(-1)));
  /* `pkg.Owner.method` → `pkg.Owner` (필드 사전의 키와 맞추기 위한 소유 클래스 id) */
  const ownerIdOf = (callerId) => String(callerId || "").split(".").slice(0, -1).join(".");
  const nodeBySimple = new Map();
  for (const node of nodes) {
    const simple = node.id.split(".").at(-1);
    if (!nodeBySimple.has(simple)) nodeBySimple.set(simple, []);
    nodeBySimple.get(simple).push(node);
  }
  /*
   * 이름이 겹치는 후보가 둘 이상일 때 스코프(같은 파일 → 같은 패키지 → 같은 워크스페이스)로 좁혀
   * 하나로 줄면 결정론적으로 확정하는 방안을 구현했다가 **되돌렸다**(2026-08-16).
   * `same_file` 규칙이 호출 한정자(qualifier)를 보지 않아 `cache.save()`처럼 *다른 객체*를 통한
   * 호출을 같은 파일 안의 동명 메서드로 이어버렸다 — 없는 엣지를 지어내지 않는다는 이 인덱서의
   * 계약을 정면으로 위반하고, 게다가 미해결 목록에서도 사라져 analyzer가 바로잡을 기회조차 없앴다.
   * `same_package` 규칙은 노드에 `package` 필드가 없어 애초에 한 번도 발동하지 않았고,
   * 실측에서 미해결 감소량도 0이었다. 위험만 있고 이득이 없어 넣지 않는다.
   * 미해결 항목의 실제 비용 문제는 아래 우선순위 정렬(판정 가능한 것부터)에서 해결한다.
   */

  const edges = [];
  const unresolved = [];
  for (const binding of bindings) {
    let candidates = (nodeBySimple.get(binding.handler_name) || []).filter((item) => item.type !== "trigger");
    /*
     * 템플릿 이벤트 핸들러(@click 등)·markup 이벤트는 반드시 같은 파일의 스크립트 블록에
     * 정의된 메서드다 — qualifier 기반 호출(obj.method())과 달리 "다른 객체를 통한 동명
     * 메서드"일 가능성이 구조적으로 없다(템플릿 바인딩은 항상 로컬 컴포넌트 메서드를 가리킨다).
     * 그래서 same_file 좁히기가 안전하다(2026-08-19 추가) — 위에서 call qualifier에 썼다가
     * 되돌린 same_file 휴리스틱과는 위험 성격이 다르다: 그건 "다른 객체일 수 있음"이 문제였고
     * (실제로 `cache.save()`를 오연결), 여기는 애초에 다른 파일을 가리킬 수가 없다.
     * 1,100개 근사-반복 화면에서 handler 이름(save/search 등)이 겹치는 경우가 흔해(2026-08-19
     * 실측, Vue 템플릿 이벤트 바인딩 추출 추가 직후 미해결 5,300건 급증 확인) 이 좁히기 없이는
     * 템플릿 이벤트 추출 자체가 손해가 된다.
     */
    if (candidates.length > 1 && (binding.type === "ui_event" || binding.type === "markup_event")) {
      const sameFile = candidates.filter((item) => item.file === binding.file);
      if (sameFile.length === 1) candidates = sameFile;
    }
    if (candidates.length === 1) edges.push({ from: `trigger:${binding.trigger}`, to: candidates[0].id, type: binding.type, file: binding.file, line: binding.line, workspace: binding.workspace, origin: "deterministic-indexer", confidence: "HIGH" });
    else unresolved.push({ kind: "unresolved_trigger", trigger: binding.trigger, handler_name: binding.handler_name, candidates: candidates.map((item) => item.id), file: binding.file, line: binding.line, workspace: binding.workspace });
  }
  for (const call of callSites) {
    let candidates = nodeBySimple.get(call.name) || [];
    if (call.qualifier) {
      /*
       * 한정자를 **선언 타입**으로 먼저 해석한다. `sqlSession.insert(...)`의 `sqlSession`은
       * `SqlSessionTemplate` 필드이므로 후보인 `*Dao.insert`들과는 아무 관계가 없다.
       * 예전에는 이름이 겹치지 않으면 후보를 그대로 두어(아래 폴백) 오답뿐인 목록이
       * LLM 판정 대기열로 갔다. 타입을 알면 셋 중 하나로 정확히 갈린다.
       */
      const declaredType = fieldTypes.get(`${ownerIdOf(call.caller)}::${call.qualifier}`);
      if (declaredType) {
        if (!indexedSimpleNames.has(declaredType)) {
          /* 선언 타입이 인덱스에 없다 = 프레임워크·외부 라이브러리 호출. 엣지도 미해결도 만들지 않는다
           * (후보가 0개일 때 버리는 기존 규칙과 같은 처리다). */
          continue;
        }
        const typed = candidates.filter((item) => item.id.split(".").slice(0, -1).at(-1) === declaredType);
        candidates = typed;
      } else {
        /*
         * 선언 타입을 못 찾은 한정자(대부분 지역변수 — fieldTypes는 필드만 추적한다)는
         * id 부분 문자열로 근사 매칭한다. **매칭이 0건이면 후보를 그대로 두지 않고 비운다**
         * (2026-08-19 수정) — 이전엔 `if (qualified.length) candidates = qualified`라 매칭
         * 0건일 때 "필터링 정보 없음"으로 취급해 원래의 전체 후보(동명 메서드 전부)를 그대로
         * 썼다. 그런데 한정자가 있는데 그 후보들 중 단 하나도 이름이 비슷하지 않다는 건
         * "필터링 정보 없음"이 아니라 "이 후보들은 전부 아니다"라는 더 강한 신호다(예:
         * `jobBuilderFactory.get(...)`의 15개 "get" 후보 전부가 무관한 `*Job.get`/
         * `DataSourceContextHolder.get` — 전부 프레임워크/무관 클래스). 매칭 0건을 무후보로
         * 처리해야 이런 케이스가 미해결 목록에 쌓이지 않는다(실측: 백엔드 미해결 9,691건이
         * 전부 이 한 가지 패턴이었다).
         */
        candidates = candidates.filter((item) => item.id.toLowerCase().includes(call.qualifier.toLowerCase()));
      }
    }
    /*
     * 한정자 없는 호출(`method(...)`, 앞에 `obj.`가 없음)은 자바/코틀린/C# 스코프 규칙상
     * 같은 클래스(또는 상위 클래스) 멤버를 가리킨다 — qualifier가 있는 호출과 달리 "다른
     * 객체를 통한 동일 이름 메서드"일 가능성이 문법적으로 없다(2026-08-19 추가). 되돌린
     * same_file 휴리스티과 위험 성격이 다르다: 그건 qualifier 호출에 적용해 "다른 객체일
     * 수 있음"이 문제였고, 여기는 한정자가 없는 호출에만 적용해 애초에 다른 클래스를
     * 가리킬 문법적 경로가 없다(정적 임포트한 동명 메서드가 있는 극히 드문 경우도, 같은
     * 클래스에 동명 메서드가 있으면 스코프 규칙상 그 쪽이 항상 우선한다).
     *
     * **Python·Go는 이 규칙에서 제외한다.** Python은 클래스 메서드 호출에도 `self.foo()`가
     * 필수라 한정자 없는 `foo()`는 클래스 멤버가 아닌 별개 함수를 가리키고, Go는 메서드에
     * 리시버가 항상 명시적이며 패키지가 파일 하나가 아니라 디렉터리 전체에 걸친다 —
     * "같은 owner"가 "같은 파일"과 대응되지 않아 좁히기가 오답을 낼 수 있다.
     *
     * JS/TS/Vue는 포함한다 — 클래스 메서드는 `this.foo()`가 필수라 이미 qualifier로 잡히므로
     * 이 분기(한정자 없음)에 오지 않고, 한정자 없는 `foo()`는 클로저/모듈 스코프 함수 참조라
     * JS 문법상 정확히 "같은 파일(Vue는 파일당 owner가 고유)"로 좁히는 게 맞다(2026-08-19,
     * 다른 스택 적용 가능성을 검토하며 실제 소스로 재검증 — `LoginE2ms.vue`의 `loginClick`이
     * `setup()` 안에서 지역 함수 `setPassword`를 바로 호출하는 경우가 정확히 이 패턴이었고,
     * 실제로 같은 파일의 그 함수를 가리키는 게 맞았다).
     */
    const sameOwnerSafeExt = [".java", ".kt", ".kts", ".cs", ".vue", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"];
    if (!call.qualifier && candidates.length > 1 && sameOwnerSafeExt.includes(extname(call.file).toLowerCase())) {
      const callerOwner = ownerIdOf(call.caller);
      const sameClass = candidates.filter((item) => ownerIdOf(item.id) === callerOwner);
      if (sameClass.length === 1) candidates = sameClass;
    }
    if (candidates.length === 1 && candidates[0].id !== call.caller) {
      edges.push({ from: call.caller, to: candidates[0].id, type: "call", file: call.file, line: call.line, workspace: call.workspace, origin: "deterministic-indexer", confidence: call.qualifier ? "HIGH" : "MEDIUM" });
    } else if (candidates.length > 1) {
      unresolved.push({ kind: "ambiguous_call", caller: call.caller, expression: `${call.qualifier ? `${call.qualifier}.` : ""}${call.name}(...)`, candidates: candidates.map((item) => item.id), file: call.file, line: call.line, workspace: call.workspace });
    }
  }
  for (const injection of injects) {
    const candidates = nodeBySimple.get(injection.targetName) || [];
    if (candidates.length === 1) edges.push({ from: injection.owner, to: candidates[0].id, type: "inject", file: injection.file, line: injection.line, workspace: injection.workspace, origin: "deterministic-indexer", confidence: "HIGH" });
    else if (candidates.length > 1) unresolved.push({ kind: "ambiguous_injection", from: injection.owner, target_name: injection.targetName, candidates: candidates.map((item) => item.id), file: injection.file, line: injection.line, workspace: injection.workspace });
  }
  /*
   * 상속 관계는 심볼의 extends/implements에만 기록돼 있고 엣지로는 해석되지 않았다.
   * 그래서 클래스가 있는 프로젝트에서 validator_checks가 "class 노드 N개 존재하나 inherit edge 0개"를
   * 항상 WARN했다. 호출·주입과 같은 규칙(후보 정확히 1개일 때만 엣지)으로 해석한다.
   *
   * extends/implements는 문법상 대상 종류가 갈린다 — `implements`는 반드시 interface만,
   * `extends`는 (interface의 interface 상속을 빼면) class/enum/record/object만 대상이 될 수 있다.
   * 이건 추측이 아니라 언어 규칙이므로(2026-08-16에 되돌린 same_file/same_package 근접 추론과는
   * 성격이 다르다 — 그건 관련 없는 객체를 같은 이름이라는 이유만으로 이어버릴 위험이 있었다),
   * 동명이인 후보 중 타입이 안 맞는 쪽을 걸러내면 순수하게 unresolved 큐만 줄어든다.
   */
  const inheritTargets = (baseName, symbol) => {
    const simple = String(baseName).split(".").at(-1).replace(/<.*/, "").trim();
    if (!simple) return null;
    return { simple, candidates: (nodeBySimple.get(simple) || []).filter((item) => item.type !== "method" && item.type !== "trigger" && item.id !== symbol.id) };
  };
  const resolveInherit = (symbol, simple, candidates) => {
    if (candidates.length === 1) {
      edges.push({ from: symbol.id, to: candidates[0].id, type: "inherit", file: symbol.file, line: symbol.line, workspace: symbol.workspace, origin: "deterministic-indexer", confidence: "HIGH" });
    } else if (candidates.length > 1) {
      unresolved.push({ kind: "ambiguous_inherit", from: symbol.id, target_name: simple, candidates: candidates.map((item) => item.id), file: symbol.file, line: symbol.line, workspace: symbol.workspace });
    }
  };
  for (const symbol of symbols) {
    if (symbol.extends) {
      const target = inheritTargets(symbol.extends, symbol);
      if (target) resolveInherit(symbol, target.simple, target.candidates.filter((item) => item.type !== "interface"));
    }
    for (const baseName of symbol.implements || []) {
      const target = inheritTargets(baseName, symbol);
      if (target) resolveInherit(symbol, target.simple, target.candidates.filter((item) => item.type === "interface"));
    }
  }

  let endpoints = unique(composeFastApiEndpoints(facts, facts.flatMap((item) => item.endpoints)), (item) => item.id);
  let consumers = unique(facts.flatMap((item) => item.consumers), (item) => item.id);
  const pair = pairConfig(options.root);
  /* 파트너 N개의 계약을 모두 병합한다. 구형 단일 파트너는 길이 1인 목록으로 처리된다. */
  for (const link of pair?.partners || []) {
    if (!link.partner_api_contract || !existsSync(link.partner_api_contract)) continue;
    const partner = readJson(link.partner_api_contract, {});
    const externalize = (item) => ({ ...item, source: "external", external_repo_path: link.partner_root, origin: item.origin || "deterministic-indexer" });
    endpoints = unique([...endpoints, ...(partner.endpoints || []).filter((item) => item.source !== "external").map(externalize)], (item) => item.id);
    consumers = unique([...consumers, ...(partner.consumers || []).filter((item) => item.source !== "external").map(externalize)], (item) => item.id);
  }
  const matches = [];
  const matchedEndpoints = new Set();
  const matchedConsumers = new Set();
  /*
   * 엔드포인트 × 컨슈머 전수 비교는 O(E·C)다 — 엔드포인트 1만 · 컨슈머 10만이면 10억 회로
   * 이 루프만 수십 초가 걸린다. 매칭 조건이 결국 path_pattern 완전 일치이므로
   * 컨슈머를 path_pattern으로 한 번 그룹핑해 두고 엔드포인트마다 해당 버킷만 본다.
   */
  const consumersByPath = new Map();
  for (const consumer of consumers) {
    const bucket = consumersByPath.get(consumer.path_pattern);
    if (bucket) bucket.push(consumer);
    else consumersByPath.set(consumer.path_pattern, [consumer]);
  }
  for (const endpoint of endpoints) {
    if (endpoint.prefix_resolved === false) continue;
    for (const consumer of consumersByPath.get(endpoint.path_pattern) || []) {
      if (endpoint.method !== "ANY" && consumer.method !== endpoint.method) continue;
      matches.push({ endpoint_id: endpoint.id, consumer_id: consumer.id, match_type: "path_pattern", confidence: "HIGH", shape_match: "UNKNOWN", origin: "deterministic-indexer" });
      matchedEndpoints.add(endpoint.id); matchedConsumers.add(consumer.id);
    }
  }
  const sqls = unique(facts.flatMap((item) => item.sqls), (item) => item.id);
  /* 후보(쿼리 ID 상수 참조)는 실제로 존재하는 SQL id일 때만 사용처로 인정한다 — 그냥 대문자 상수와 구분. */
  const sqlIds = new Set(sqls.map((item) => item.id));
  const usages = unique(
    facts.flatMap((item) => item.usages).filter((item) => !item.candidate || sqlIds.has(item.sql_id)),
    (item) => `${item.sql_id}:${item.file}:${item.line}`,
  ).map(({ candidate, ...rest }) => rest);
  const sqlRelations = unique(facts.flatMap((item) => item.relations || []), (item) => `${item.from_table}:${item.from_columns?.join(",")}:${item.to_table}:${item.to_columns?.join(",")}:${item.file}:${item.line}`);
  const boundaries = unique(facts.flatMap((item) => item.boundaries), (item) => item.id);
  const communications = unique(facts.flatMap((item) => item.communications), (item) => item.id);
  const profiles = [...new Set(facts.flatMap((item) => item.env.profiles))];
  const branches = unique(facts.flatMap((item) => item.env.branches), (item) => `${item.file}:${item.line}:${item.marker}`);
  const tables = unique(facts.flatMap((item) => item.tables), (item) => item.name.toLowerCase());
  const uiFlow = {
    screens: unique(facts.flatMap((item) => item.uiFlow?.screens || []), (item) => `${item.file}:${item.id}`),
    events: unique(facts.flatMap((item) => item.uiFlow?.events || []), (item) => `${item.file}:${item.component}:${item.event}:${item.handler}`),
    datasets: unique(facts.flatMap((item) => item.uiFlow?.datasets || []), (item) => `${item.file}:${item.id}`),
    transactions: unique(facts.flatMap((item) => item.uiFlow?.transactions || []), (item) => `${item.file}:${item.line}:${item.service_id}`),
  };
  const foreignKeyRelations = tables.flatMap((table) => (table.foreign_keys || []).map((foreignKey) => ({
    type: "foreign_key", name: foreignKey.name || "", from_table: table.name, from_columns: foreignKey.columns || [],
    to_table: foreignKey.references_table, to_columns: foreignKey.references_columns || [],
    file: table.source_file, line: null, evidence: foreignKey.name || "DDL FOREIGN KEY",
    origin: foreignKey.origin || "deterministic-indexer", confidence: foreignKey.confidence || "HIGH",
  })));
  const schemaRelations = unique([...foreignKeyRelations, ...sqlRelations], (item) => `${item.type}:${item.from_table}:${item.from_columns?.join(",")}:${item.to_table}:${item.to_columns?.join(",")}:${item.file}:${item.line}`);
  /*
   * 중복 제거를 in-degree 계산보다 먼저 한다.
   * 예전에는 _meta.edge_count만 중복 포함 배열 길이로 기록돼 실제 edges 배열과 어긋났고
   * (validator_checks가 count 불일치로 FAIL), in-degree도 같은 관계를 여러 번 세고 있었다.
   */
  const uniqueEdges = unique(edges, (item) => `${item.from}:${item.to}:${item.type}`);
  const { inDegree } = degreeMaps(nodes, uniqueEdges);
  /* 데드 코드 후보는 전 Tier에서 계산한다. Full 전용이면 Lite/Standard 분석이 유지보수 위험을 볼 근거를 잃는다. */
  const unusedMethods = deadCodeCandidates(nodes, inDegree, uniqueEdges, endpoints);
  /*
   * _meta 9필드는 이 저장소의 계약이다(docs/index-spec.md, validator_checks._meta_field_issues).
   * files_scanned/files_total은 analyzer_index_summary가 "분석 커버리지 N/M" 줄로 렌더한다.
   * 인덱서는 발견한 소스를 전수 파싱하므로 둘이 같고 sampled는 항상 false다.
   */
  const commit = gitCommit(options.root);
  const common = {
    generated_at: generatedAt, generator: "deterministic-indexer", version: INDEXER_VERSION,
    /*
     * `source_root`에 절대경로를 박으면 인덱스가 그 사람 PC 전용이 된다 — 팀원마다
     * `E:\\AI\\proj`와 `/home/kim/proj`로 달라져 공유도 diff 검토도 안 된다.
     * 인덱스 안의 다른 모든 경로는 이미 루트 기준 상대경로라 루트는 `.`이면 충분하다
     * (절대경로를 실제로 쓰는 소비자는 없다 — validator_checks는 필드 존재만 확인한다).
     */
    source_root: ".", mode: options.mode,
    git_commit: commit, sampled: false, files_scanned: sourceFileCount, files_total: sourceFileCount,
  };
  const globalMeta = {
    ...common, source_file_count: sourceFileCount, latest_source_commit: commit, latest_source_mtime: latestMtime,
    /* 팀원이 재인덱싱 필요 여부를 판정하는 값 — `--check-stale` 참조. */
    source_fingerprint: sourceFingerprint(options.root, config.include_paths, sourceFiles),
    tier: options.tier, indexes: [], init_layout: config.init_layout, include_paths: config.include_paths.map((item) => item || "."), workspace_mode: config.workspace_mode, workspaces: config.workspaces,
    unresolved_count: unresolved.length,
    encoding: buildEncodingSummary(facts),
    excluded_sources: buildExclusionSummary(excludedSources),
    complexity: {
      ...complexity,
      selected_tier: options.tier,
      selection: options.requestedTier === "Auto" ? "deterministic-auto" : "user-override",
    },
    adapter_coverage: coverage,
    analysis_budget: {
      initial_ai_calls_per_target: 2,
      targeted_retries_per_target: 1,
      unresolved_batch_size: 200,
      large_index_direct_read: false,
    },
  };
  const output = {
    symbols: { _meta: { ...common, node_count: symbols.length }, symbols },
    call_graph: { _meta: { ...common, node_count: nodes.length, edge_count: uniqueEdges.length }, nodes, edges: uniqueEdges },
  };
  if (sqls.length || usages.length) output.sql_usage = { _meta: common, sqls, usages };
  if (boundaries.length) output.transactions = { _meta: common, boundaries };
  if (communications.length) output.external_io = { _meta: common, communications };
  if (branches.length) output.env_branches = { _meta: common, profiles, branches };
  /*
   * DDL(.sql)도 라이브 DB 접속도 없는 프로젝트가 흔하다 — 쿼리를 전부 MyBatis/iBatis XML에 두는
   * 레거시가 그렇다. 그 경우에도 sql_usage에는 이미 테이블명이 들어 있으므로(FROM/JOIN 파싱 결과)
   * 그것을 집계해 스키마를 유도한다. 컬럼은 알 수 없으므로 빈 배열이고 confidence는 MEDIUM이다.
   * 실측(2026-08-16 xu25-server): .sql 0개 / SQL 5,348건 → 고유 테이블 2,773개.
   */
  const derivedTables = tables.length ? [] : deriveTablesFromSql(sqls);
  const schemaTables = tables.length ? tables : derivedTables;
  if (schemaTables.length || schemaRelations.length) output.schema = {
    _meta: {
      ...common, relation_count: schemaRelations.length,
      source: tables.length ? "ddl" : (derivedTables.length ? "derived-from-sql" : "none"),
    },
    tables: schemaTables, relations: schemaRelations, views: [], procedures: [], functions: [], triggers: [],
  };
  if (Object.values(uiFlow).some((items) => items.length)) output.ui_flow = { _meta: common, ...uiFlow };
  /*
   * 단일 저장소에서도 자기 엔드포인트·소비처를 기록한다.
   * 이전에는 workspace_mode/pair일 때만 emit해서 모놀리스는 API 인덱스를 아예 갖지 못했다.
   * matches는 producer와 consumer가 함께 존재할 때만 채워지므로 단일 저장소에서 빈 배열이 정상이다.
   */
  /* 파일명은 단수 api_contract.json이다 — 이미 배포된 pair_config.md들이 이 경로를 절대경로로 박고 있다. */
  if (endpoints.length || consumers.length) output.api_contract = {
    _meta: common, endpoints, consumers, matches,
    unmatched_endpoints: endpoints.filter((item) => !matchedEndpoints.has(item.id)).map((item) => item.id),
    unmatched_consumers: consumers.filter((item) => !matchedConsumers.has(item.id)).map((item) => item.id),
  };
  if (unusedMethods.length) output.dead_code = { _meta: common, unused_methods: unusedMethods, unused_sql_ids: [], unused_jsps: [] };
  const clientIndex = deriveClientIndex(facts, nodes, options.root);
  if (clientIndex) output.client_index = { _meta: common, ...clientIndex };
  const beanClassById = new Map(facts.flatMap((item) => item.springBeans || []).map((item) => [item.id, item.className]));
  const dataFlow = deriveDataFlow(endpoints, uniqueEdges, sqls, usages, nodes, beanClassById);
  if (dataFlow) output.data_flow = { _meta: common, ...dataFlow };
  globalMeta.indexes = Object.keys(output);
  return { output, globalMeta, unresolved };
}

/*
 * Legacy Static JS(번들러 없는 JSP+JS 혼합) 탐지와 JS↔JSP 매핑을 기계화한다.
 * 예전에는 analyzer(opus)가 이 전부를 처음부터 grep으로 6~10쌍만 샘플링해 작성했다 —
 * 여기서는 전수·결정론적으로 만들고, 판단이 필요한 ajax_contract/naming_convention/anti_patterns만
 * 비워 둔다(analyzer.md Step 5 참조). analyzer는 _ai_patch.json의 set_client_index_narrative로 그 세 필드만 채운다.
 */
const BUNDLER_MARKERS = ["webpack", "vite", "parcel", "rollup", "cli-service", "next", "nuxt", "esbuild", "rspack", "turbopack"];
function hasBundlerManifest(root, candidateDirs) {
  for (const dir of candidateDirs) {
    const path = join(root, dir, "package.json");
    if (!existsSync(path)) continue;
    try {
      const pkg = JSON.parse(readFileSync(path, "utf8"));
      const scripts = pkg.scripts || {};
      const deps = Object.keys({ ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) });
      if (scripts.build || scripts.dev || deps.some((name) => BUNDLER_MARKERS.some((marker) => name.includes(marker)))) return true;
    } catch {
      /* 손상된 package.json은 번들러 없음으로 간주 — 레거시 판정을 막지 않는다. */
    }
  }
  return false;
}

function deriveClientIndex(facts, nodes, root) {
  /* analyzer.md Step 5의 탐지 기준: JS 100개 이상이 특정 경로에 집중 + 번들러 매니페스트 없음. */
  const jsFacts = facts.filter((item) => extname(item.rel).toLowerCase() === ".js");
  if (jsFacts.length < 100) return null;
  const candidateDirs = new Set(["."]);
  for (const fact of jsFacts) {
    const top = dirname(fact.rel).split("/")[0];
    if (top && top !== ".") candidateDirs.add(top);
  }
  if (hasBundlerManifest(root, [...candidateDirs])) return null;

  const templateFacts = facts.filter((item) => (item.clientRefs || []).length);
  const jspsByJsBasename = new Map();
  for (const fact of templateFacts) {
    for (const src of fact.clientRefs) {
      const base = basename(src).toLowerCase();
      if (!jspsByJsBasename.has(base)) jspsByJsBasename.set(base, []);
      jspsByJsBasename.get(base).push(fact.rel);
    }
  }
  const functionsByFile = new Map();
  for (const node of nodes) {
    if (extname(node.file || "").toLowerCase() !== ".js") continue;
    if (node.type !== "function" && node.type !== "method") continue;
    const list = functionsByFile.get(node.file) || [];
    list.push(node.id.split(".").at(-1));
    functionsByFile.set(node.file, list);
  }
  const sampleMappings = [];
  for (const fact of jsFacts) {
    const jsps = jspsByJsBasename.get(basename(fact.rel).toLowerCase());
    if (!jsps || !jsps.length) continue;
    sampleMappings.push({
      js: fact.rel,
      jsps: [...new Set(jsps)].sort(byCodeUnit),
      functions: [...new Set(functionsByFile.get(fact.rel) || [])].sort(byCodeUnit),
    });
  }
  sampleMappings.sort((left, right) => byCodeUnit(left.js, right.js));

  /* 도메인 구조 — 1단계 디렉터리(back/front 등) → 그 아래 상위 2단계 경로 목록. */
  const domainStructure = new Map();
  for (const fact of jsFacts) {
    const segments = dirname(fact.rel).split("/");
    const top = segments[0] && segments[0] !== "." ? segments[0] : "(root)";
    const domain = segments.slice(1, 3).join("/") || "(root)";
    if (!domainStructure.has(top)) domainStructure.set(top, new Set());
    domainStructure.get(top).add(domain);
  }
  const domainStructureOut = Object.fromEntries(
    [...domainStructure.entries()].sort(([left], [right]) => byCodeUnit(left, right))
      .map(([key, set]) => [key, [...set].sort(byCodeUnit).slice(0, 40)]),
  );

  return {
    type: "LegacyStaticJS",
    build_tool: null,
    js_count: jsFacts.length,
    domain_structure: domainStructureOut,
    sample_mappings: sampleMappings,
    jquery_versions: detectLibraryVersions(templateFacts.flatMap((item) => item.clientRefs)),
  };
}

/*
 * data_flow.json 체인 골격 — endpoint에서 call_graph(엣지 타입 call)를 순회해 도달하는
 * 메서드들이 sql_usage로 어떤 SQL/테이블을 건드리는지 조인한다. call_graph·sql_usage는 이미
 * aggregate()가 메모리에 들고 있으므로 추가 파싱 없는 순수 그래프 순회다.
 * DTO/컬럼 의미 매핑처럼 판단이 필요한 부분은 만들지 않는다 — analyzer가
 * _ai_patch.json의 set_flow_note로 각 체인에 note를 붙인다(analyzer.md Step 9 참조).
 *
 * 시작점(seed)은 두 갈래다.
 * 1. `endpoint.handler`가 call_graph 노드 id와 그대로 일치 — Spring MVC/FastAPI/Flask 등
 *    핸들러가 곧 메서드 id인 프레임워크. 단일 시드, MEDIUM.
 * 2. `endpoint.dispatch_bean`(Struts command 속성 = Spring bean id) — WorkerAction류 공용
 *    디스패처를 쓰는 커맨드 패턴은 `handler`가 항상 같은 디스패처 클래스라 1번이 통하지 않는다
 *    (2026-08-17 xu25-server 실측: 액션 443개 중 434개가 동일 type). bean id를 `<bean id="X"
 *    class="Y"/>` 정의로 실제 서비스 클래스까지 역추적한 뒤, 그 클래스의 메서드 전부를 시드로
 *    삼는다 — 어느 메서드가 호출될지는 런타임 파라미터(`parameter="method"`)로 정해져 정적으로
 *    하나로 못 좁히므로, "이 서비스가 건드릴 수 있는 전체 테이블"로 과대추정한다. 여러 시드의
 *    합집합이라 신뢰도는 LOW.
 */
const DATA_FLOW_MAX_DEPTH = 6;
function deriveDataFlow(endpoints, edges, sqls, usages, nodes, beanClassById) {
  if (!endpoints.length || (!sqls.length && !usages.length)) return null;
  const sqlById = new Map(sqls.map((item) => [item.id, item]));
  const sqlIdsByMethod = new Map();
  for (const usage of usages) {
    const list = sqlIdsByMethod.get(usage.method) || [];
    list.push(usage.sql_id);
    sqlIdsByMethod.set(usage.method, list);
  }
  const calleesOf = new Map();
  for (const edge of edges) {
    if (edge.type !== "call") continue;
    const list = calleesOf.get(edge.from) || [];
    list.push(edge.to);
    calleesOf.set(edge.from, list);
  }
  const methodIds = new Set(nodes.filter((item) => item.type === "method").map((item) => item.id));
  const methodsByClass = new Map();
  const methodsByFile = new Map();
  for (const node of nodes) {
    if (node.type !== "method") continue;
    const classId = node.id.split(".").slice(0, -1).join(".");
    const list = methodsByClass.get(classId) || [];
    list.push(node.id);
    methodsByClass.set(classId, list);
    if (node.file) {
      const flist = methodsByFile.get(node.file) || [];
      flist.push(node.id);
      methodsByFile.set(node.file, flist);
    }
  }
  const seedsFor = (endpoint) => {
    if (endpoint.dispatch_bean && beanClassById.has(endpoint.dispatch_bean)) {
      const methods = methodsByClass.get(beanClassById.get(endpoint.dispatch_bean));
      if (methods?.length) return { ids: methods, confidence: "LOW" };
    }
    if (endpoint.handler && methodIds.has(endpoint.handler)) return { ids: [endpoint.handler], confidence: "MEDIUM" };
    /*
     * 페이지 기반 프레임워크(ASP.NET WebForms .aspx, Classic ASP, JSP)는 handler가 메서드가
     * 아니라 페이지 파일이라 위 두 경로가 모두 빗나간다. 실제 로직은 코드비하인드
     * (X.aspx.cs/.vb)나 페이지 자체 스크립트에 있으므로, 엔드포인트 파일과 그 코드비하인드
     * 파일에 정의된 메서드 전부를 시드로 삼는다 — 어떤 메서드가 실제 실행될지는 요청
     * 파라미터로 갈리므로 "이 페이지가 건드릴 수 있는 전체 테이블"로 과대추정한다(LOW).
     */
    if (endpoint.file) {
      const codeBehind = [endpoint.file, `${endpoint.file}.cs`, `${endpoint.file}.vb`];
      const ids = [...new Set(codeBehind.flatMap((f) => methodsByFile.get(f) || []))];
      if (ids.length) return { ids, confidence: "LOW" };
    }
    return null;
  };
  const chains = [];
  for (const endpoint of endpoints) {
    const seed = seedsFor(endpoint);
    if (!seed) continue;
    const visited = new Set(seed.ids);
    const queue = seed.ids.map((id) => ({ id, depth: 0 }));
    const methodChain = [...seed.ids];
    const sqlIds = new Set();
    while (queue.length) {
      const { id, depth } = queue.shift();
      for (const sqlId of sqlIdsByMethod.get(id) || []) sqlIds.add(sqlId);
      if (depth >= DATA_FLOW_MAX_DEPTH) continue;
      for (const callee of calleesOf.get(id) || []) {
        if (visited.has(callee)) continue;
        visited.add(callee);
        methodChain.push(callee);
        queue.push({ id: callee, depth: depth + 1 });
      }
    }
    if (!sqlIds.size) continue;
    const touchedSqls = [...sqlIds].map((id) => sqlById.get(id)).filter(Boolean);
    const tablesRead = [...new Set(touchedSqls.filter((item) => item.type === "select").flatMap((item) => item.tables || []))].sort(byCodeUnit);
    const tablesWritten = [...new Set(touchedSqls.filter((item) => item.type !== "select").flatMap((item) => item.tables || []))].sort(byCodeUnit);
    if (!tablesRead.length && !tablesWritten.length) continue;
    chains.push({
      id: `dataflow:${endpoint.id}`, endpoint_id: endpoint.id, method_chain: methodChain,
      sql_ids: [...sqlIds].sort(byCodeUnit), tables_read: tablesRead, tables_written: tablesWritten,
      confidence: seed.confidence,
    });
  }
  if (!chains.length) return null;
  chains.sort((left, right) => byCodeUnit(left.id, right.id));
  return { chains };
}

function degreeMaps(nodes, edges) {
  const inDegree = new Map(nodes.map((item) => [item.id, 0]));
  const outDegree = new Map(nodes.map((item) => [item.id, 0]));
  for (const edge of edges) {
    if (inDegree.has(edge.to)) inDegree.set(edge.to, inDegree.get(edge.to) + 1);
    if (outDegree.has(edge.from)) outDegree.set(edge.from, outDegree.get(edge.from) + 1);
  }
  return { inDegree, outDegree };
}

/* 트리거에서 시작되는 관계. 이 엣지의 도착점은 아무도 "호출"하지 않아도 진입점이다. */
const TRIGGER_EDGE_TYPES = new Set(["ui_event", "markup_event", "scheduler", "process_entry"]);

/*
 * in-degree 0만으로 데드 코드를 고르면 진입점이 전부 후보로 잡힌다
 * (실측: Vue 프로젝트 61노드 중 51개). agents/analyzer.md Step 15가 요구하는 진입점
 * 화이트리스트를 여기서 적용한다 — 확실한 진입점은 제외하고, 파일만 겹쳐 애매한 것은
 * 버리지 않고 entrypoint_suspect로 표시해 판단을 사람/LLM에게 남긴다.
 */
function deadCodeCandidates(nodes, inDegree, edges, endpoints) {
  const triggerTargets = new Set(edges.filter((item) => TRIGGER_EDGE_TYPES.has(item.type)).map((item) => item.to));
  const handlerKeys = new Set();
  const handlerFiles = new Set();
  /*
   * `endpoint.handler`는 전체 심볼 id(`kr.co...OrderController.list`)인데 아래 조회는 마지막
   * segment(`list`)로 했다 — 키가 절대 맞지 않아 **엔드포인트 핸들러 제외가 한 번도 동작하지 않았다.**
   * 가상 프로젝트에서 데드 코드 후보 23건 중 15건이 정상 동작 중인 컨트롤러 메서드였다.
   * "지워도 되나"를 판단하려고 보는 목록이 오탐 65%면 목록 자체를 못 쓴다.
   * 양쪽을 전체 id와 마지막 segment 모두로 등록해 어느 형태로 와도 걸리게 한다.
   */
  for (const endpoint of endpoints || []) {
    if (endpoint.file && endpoint.handler) {
      handlerKeys.add(`${endpoint.file}::${endpoint.handler}`);
      handlerKeys.add(`${endpoint.file}::${String(endpoint.handler).split(".").at(-1)}`);
    }
    if (endpoint.file) handlerFiles.add(endpoint.file);
  }
  return nodes
    .filter((item) => item.type === "method" && item.visibility !== "private" && (inDegree.get(item.id) || 0) === 0)
    .filter((item) => {
      const name = item.id.split(".").at(-1);
      if (triggerTargets.has(item.id)) return false;
      if (name === "main" || name === "Main") return false;
      return !handlerKeys.has(`${item.file}::${name}`) && !handlerKeys.has(`${item.file}::${item.id}`);
    })
    .map((item) => {
      const suspect = handlerFiles.has(item.file);
      return {
        id: item.id, file: item.file, line: item.line,
        reason: suspect
          ? "call graph in-degree=0; 다만 같은 파일에 API 핸들러가 있어 진입점일 수 있음"
          : "call graph in-degree=0; 동적·외부 호출 검토 필요",
        entrypoint_suspect: suspect, confidence: "LOW", origin: "deterministic-indexer",
      };
    });
}

/* 상한을 적용하고 잘린 개수를 함께 돌려준다. digest는 전체 덤프가 아니라 정직하게 잘린 요약이다. */
function capped(items, limit) {
  return { items: items.slice(0, limit), truncated: Math.max(0, items.length - limit) };
}

function groupCount(items, keyOf, limit) {
  const groups = new Map();
  for (const item of items) {
    const key = keyOf(item) || "unknown";
    if (!groups.has(key)) groups.set(key, { key, count: 0, sample: null });
    const group = groups.get(key);
    group.count += 1;
    if (!group.sample && item.file) group.sample = item.line ? `${item.file}:${item.line}` : item.file;
  }
  const sorted = [...groups.values()].sort((left, right) => right.count - left.count || byCodeUnit(String(left.key), String(right.key)));
  return capped(sorted, limit);
}

/*
 * 호출 그래프 해석 재료.
 * 허브(in-degree 상위)와 진입점(trigger·endpoint 핸들러·in-degree 0 공개 심볼)은
 * 인덱서가 이미 계산할 수 있는데도 지금까지 버려져서, analyzer가 구조를 해석할 근거가 없었다.
 */
function graphDigest(nodes, edges, limits = DIGEST_LIMITS) {
  const { inDegree, outDegree } = degreeMaps(nodes, edges);
  const describe = (node) => ({
    id: node.id, type: node.type, file: node.file, line: node.line,
    in_degree: inDegree.get(node.id) || 0, out_degree: outDegree.get(node.id) || 0,
  });
  const byDegree = (left, right) =>
    (inDegree.get(right.id) || 0) - (inDegree.get(left.id) || 0)
    || (outDegree.get(right.id) || 0) - (outDegree.get(left.id) || 0)
    || byCodeUnit(left.id, right.id);
  const hubs = capped(nodes.filter((item) => (inDegree.get(item.id) || 0) > 0).sort(byDegree).map(describe), limits.hubs);
  const triggerTargets = new Set(edges.filter((edge) => String(edge.from).startsWith("trigger:")).map((edge) => edge.to));
  const entryCandidates = nodes.filter((item) =>
    item.type === "trigger"
    || triggerTargets.has(item.id)
    || (item.type !== "trigger" && (inDegree.get(item.id) || 0) === 0 && (outDegree.get(item.id) || 0) > 0));
  const entryPoints = capped(
    entryCandidates
      .sort((left, right) => (outDegree.get(right.id) || 0) - (outDegree.get(left.id) || 0) || byCodeUnit(left.id, right.id))
      .map((item) => ({ ...describe(item), reached_by_trigger: item.type === "trigger" || triggerTargets.has(item.id) })),
    limits.entry_points,
  );
  return {
    hubs: hubs.items, hubs_truncated: hubs.truncated,
    entry_points: entryPoints.items, entry_points_truncated: entryPoints.truncated,
  };
}

/* 디렉터리 depth 2 단위 모듈 윤곽. validator가 이 목록으로 "주요 모듈 미언급"을 잡는다. */
function moduleDigest(output, limits = DIGEST_LIMITS) {
  const modules = new Map();
  const bucketOf = (file) => {
    const parts = slash(file).split("/").filter(Boolean);
    if (parts.length <= 1) return ".";
    return parts.slice(0, Math.min(2, parts.length - 1)).join("/");
  };
  const touch = (file, key) => {
    if (!file) return;
    const bucket = bucketOf(file);
    if (!modules.has(bucket)) modules.set(bucket, { path: bucket, files: new Set(), symbols: 0, sqls: 0, endpoints: 0 });
    const entry = modules.get(bucket);
    entry.files.add(file);
    if (key) entry[key] += 1;
  };
  for (const item of output.symbols?.symbols || []) touch(item.file, "symbols");
  for (const item of output.sql_usage?.sqls || []) touch(item.file, "sqls");
  for (const item of output.api_contract?.endpoints || []) touch(item.file, "endpoints");
  for (const item of output.call_graph?.nodes || []) touch(item.file, null);
  const sorted = [...modules.values()]
    .map((item) => ({ path: item.path, files: item.files.size, symbols: item.symbols, sqls: item.sqls, endpoints: item.endpoints }))
    .sort((left, right) => right.files - left.files || byCodeUnit(left.path, right.path));
  const result = capped(sorted, limits.modules);
  return { modules: result.items, modules_truncated: result.truncated };
}

/*
 * analyzer가 해석해야 할 결정적 사실 요약 전체.
 * 인덱서가 이미 추출한 데이터의 정렬·집계이므로 추가 파싱과 AI 호출이 없다.
 */
function buildDigest(output, globalMeta, limits = DIGEST_LIMITS) {
  const nodes = output.call_graph?.nodes || [];
  const edges = output.call_graph?.edges || [];
  const boundaries = output.transactions?.boundaries || [];
  const communications = output.external_io?.communications || [];
  const externalIoFiles = new Set(communications.map((item) => `${item.file}:${item.line}`));
  const transactions = capped(
    boundaries.map((item) => ({
      id: item.id, file: item.file, line: item.line, marker: item.marker,
      propagation: item.propagation, isolation: item.isolation,
      external_io_in_scope: (item.external_io_calls || []).length,
      /* 경계 내부에서 외부 호출이 일어나면 롤백 불가 구간이므로 위험 신호로 표시한다. */
      risk: (item.external_io_calls || []).length > 0 ? "external-io-in-transaction" : null,
    })),
    limits.transactions,
  );
  const externalIo = groupCount(communications, (item) => item.type, limits.external_io);
  const envBranches = groupCount(output.env_branches?.branches || [], (item) => item.marker, limits.env_branches);
  const tables = capped(
    (output.schema?.tables || []).map((item) => ({
      name: item.name, columns: (item.columns || []).length,
      foreign_keys: (item.foreign_keys || []).length, file: item.source_file || null,
    })),
    limits.tables,
  );
  const endpoints = capped(
    (output.api_contract?.endpoints || []).map((item) => ({
      id: item.id, method: item.method, path: item.path_pattern, file: item.file, line: item.line,
      prefix_resolved: item.prefix_resolved !== false,
    })),
    limits.endpoints,
  );
  const sqls = output.sql_usage?.sqls || [];
  const sqlTableCounts = new Map();
  for (const sql of sqls) for (const table of sql.tables || []) {
    const key = String(table).toLowerCase();
    sqlTableCounts.set(key, (sqlTableCounts.get(key) || 0) + 1);
  }
  const sqlTables = capped(
    [...sqlTableCounts.entries()].map(([name, count]) => ({ name, statements: count }))
      .sort((left, right) => right.statements - left.statements || byCodeUnit(left.name, right.name)),
    limits.sql_tables,
  );
  const deadCode = capped(output.dead_code?.unused_methods || [], limits.dead_code);
  /*
   * PARTIAL/WARN 파일을 확장자별로 노출한다.
   * analyzer는 전체 재순회 대신 이 목록이 지목한 좌표만 선택 열람해 커버리지 구멍을 메운다.
   */
  const coverage = globalMeta.adapter_coverage || {};
  const partialExtensions = capped(
    (coverage.extensions || []).filter((item) => item.level !== "FULL")
      .sort((left, right) => right.files - left.files || byCodeUnit(left.extension, right.extension)),
    limits.partial_coverage,
  );
  const unsupported = capped(coverage.unsupported_files || [], limits.partial_coverage);
  return {
    ...graphDigest(nodes, edges, limits),
    ...moduleDigest(output, limits),
    transactions: transactions.items, transactions_truncated: transactions.truncated,
    external_io_by_type: externalIo.items, external_io_by_type_truncated: externalIo.truncated,
    env_profiles: output.env_branches?.profiles || [],
    env_branches_by_marker: envBranches.items, env_branches_by_marker_truncated: envBranches.truncated,
    tables: tables.items, tables_truncated: tables.truncated,
    endpoints: endpoints.items, endpoints_truncated: endpoints.truncated,
    sql_statement_count: sqls.length,
    sql_top_tables: sqlTables.items, sql_top_tables_truncated: sqlTables.truncated,
    dead_code_candidates: deadCode.items, dead_code_candidates_truncated: deadCode.truncated,
    transaction_external_io_sites: externalIoFiles.size,
    partial_coverage_extensions: partialExtensions.items, partial_coverage_extensions_truncated: partialExtensions.truncated,
    unsupported_files: unsupported.items, unsupported_files_truncated: unsupported.truncated,
  };
}

/*
 * 미해결 관계 중 상당수는 서로 다른 위치에서 "같은 애매함"이 반복된다 — 예를 들어
 * `user.getUserNo()`가 두 후보(StudySession/UserSession) 사이에서 애매하면, 그 표현식이
 * 나오는 861곳 전부가 사실 동일한 판정 문제다(실측: 레거시 Java 프로젝트에서 판정 대상
 * 2,356건이 실제로는 고유 패턴 188개뿐 — 12.5배 중복, JS 프로젝트에서는 4,860건이 483개).
 * 지금까지는 analyzer가 발생 위치마다 파일을 열어 같은 판정을 반복했다. groupUnresolvedDecidable()은
 * (kind, 식별 필드, candidates) 조합으로 묶어 analyzer가 그룹당 대표 사례 1곳만 판정하고,
 * 나머지 발생 위치는 같은 판정을 기계적으로 재적용하게 한다 — _ai_patch.json에는 여전히
 * 발생 위치 수만큼 add_edge가 나오므로 그래프 정확도·감사 가능성은 그대로고, LLM 판정
 * 횟수만 준다. 문맥에 따라 판정이 갈릴 수 있는 패턴(같은 표현식이 클래스마다 다른 타입으로
 * 선언된 경우 등)은 analyzer가 대표 사례 외 표본을 더 확인하거나 개별 판정으로 되돌릴 수
 * 있게 analyzer.md Step 8에 예외 절차를 둔다 — 이 함수는 그룹 후보만 만들고 강제하지 않는다.
 */
function unresolvedGroupKeyField(item) {
  return item.expression ?? item.target_name ?? item.handler_name ?? "";
}
function unresolvedFromId(item) {
  if (item.kind === "unresolved_trigger") return `trigger:${item.trigger}`;
  return item.from ?? item.caller ?? null;
}
function unresolvedGroupKey(item) {
  return JSON.stringify([item.kind, unresolvedGroupKeyField(item), item.candidates || []]);
}
function groupUnresolvedDecidable(decidableItems) {
  const groups = new Map();
  for (const item of decidableItems) {
    const key = unresolvedGroupKey(item);
    let group = groups.get(key);
    if (!group) {
      group = { kind: item.kind, key_field: unresolvedGroupKeyField(item), candidates: item.candidates || [], occurrences: [] };
      groups.set(key, group);
    }
    group.occurrences.push({ from: unresolvedFromId(item), file: item.file, line: item.line, workspace: item.workspace });
  }
  return [...groups.values()]
    .sort((a, b) => (a.candidates.length - b.candidates.length) || (b.occurrences.length - a.occurrences.length))
    .map((group, index) => ({ group_id: `g${String(index + 1).padStart(4, "0")}`, ...group, occurrence_count: group.occurrences.length }));
}

function buildAnalysisInput(output, globalMeta, unresolved, decidableCount, decidableGroupCount, fileSizes = new Map()) {
  const count = (name, key) => Array.isArray(output[name]?.[key]) ? output[name][key].length : 0;
  const evidenceFiles = new Set();
  const collectFiles = (name, key) => {
    for (const item of output[name]?.[key] || []) if (item?.file) evidenceFiles.add(item.file);
  };
  for (const [name, key] of [
    ["symbols", "symbols"], ["call_graph", "edges"], ["sql_usage", "sqls"],
    ["transactions", "boundaries"], ["external_io", "communications"],
    ["env_branches", "branches"], ["api_contract", "endpoints"], ["api_contract", "consumers"],
    ["ui_flow", "events"], ["ui_flow", "transactions"],
  ]) collectFiles(name, key);
  const representativeLimit = REPRESENTATIVE_FILE_LIMITS[globalMeta.tier] || REPRESENTATIVE_FILE_LIMITS.Standard;
  const byteBudget = REPRESENTATIVE_BYTE_BUDGET[globalMeta.tier] || REPRESENTATIVE_BYTE_BUDGET.Standard;
  /* 개수·바이트 예산을 동시에 만족하는 만큼만 고른다. 순서는 인덱스 수집 순서를 유지해
   * 특정 레이어에 쏠리지 않게 하고, 개별 상한을 넘는 파일은 대표에서 제외한다. */
  const representative = [];
  let representativeBytes = 0;
  let oversizedSkipped = 0;
  let budgetSkipped = 0;
  for (const file of evidenceFiles) {
    const size = fileSizes.get(file) ?? 0;
    if (size > REPRESENTATIVE_PER_FILE_CAP) { oversizedSkipped += 1; continue; }
    if (representative.length >= representativeLimit || representativeBytes + size > byteBudget) { budgetSkipped += 1; continue; }
    representative.push(file);
    representativeBytes += size;
  }
  return {
    version: 1,
    generated_at: globalMeta.generated_at,
    source_root: globalMeta.source_root,
    tier: globalMeta.tier,
    complexity: globalMeta.complexity,
    adapter_coverage: globalMeta.adapter_coverage,
    coverage: {
      source_file_count: globalMeta.source_file_count,
      indexed_files: globalMeta.indexes,
      unresolved_count: unresolved.length,
      /* 판정 대상(후보 2개 이상)의 발생 위치 수 — 감사용 원본 카운트. 비용 추정은 아래
       * unresolved_decidable_group_count를 쓴다(같은 패턴이 반복 발생하는 경우가 많아
       * 이 값만으로 예산을 잡으면 과대추정된다). */
      unresolved_decidable_count: decidableCount,
      /* (kind+식별필드+candidates) 조합 기준 고유 패턴 수 — analyzer가 실제로 판정을
       * 내려야 하는 횟수다. ai-budget.mjs estimate()가 이 값을 기준으로 예산을 잡는다. */
      unresolved_decidable_group_count: decidableGroupCount,
      evidence_file_count: evidenceFiles.size,
    },
    counts: {
      symbols: count("symbols", "symbols"),
      graph_nodes: count("call_graph", "nodes"),
      graph_edges: count("call_graph", "edges"),
      sqls: count("sql_usage", "sqls"),
      sql_usages: count("sql_usage", "usages"),
      db_relations: count("schema", "relations"),
      transactions: count("transactions", "boundaries"),
      external_io: count("external_io", "communications"),
      environment_branches: count("env_branches", "branches"),
      endpoints: count("api_contract", "endpoints"),
      consumers: count("api_contract", "consumers"),
      api_matches: count("api_contract", "matches"),
      ui_screens: count("ui_flow", "screens"),
      ui_events: count("ui_flow", "events"),
      ui_transactions: count("ui_flow", "transactions"),
      dead_code_candidates: count("dead_code", "unused_methods"),
    },
    workspaces: globalMeta.workspaces,
    digest: buildDigest(output, globalMeta),
    evidence: {
      representative_files: representative,
      representative_files_truncated: Math.max(0, evidenceFiles.size - representative.length),
      /* 이 목록을 전부 읽었을 때의 실제 비용. 계획 없이 열다가 컨텍스트를 태우지 않도록 미리 알려준다. */
      representative_files_bytes: representativeBytes,
      representative_files_skipped: { oversized: oversizedSkipped, over_budget: budgetSkipped, per_file_cap_bytes: REPRESENTATIVE_PER_FILE_CAP },
      indexes: globalMeta.indexes.map((name) => `_workspace/index/${name}.json`),
      unresolved: "_workspace/index/_unresolved.jsonl",
      /* 판정 대상을 고유 패턴 단위로 묶은 파일 — analyzer는 원칙적으로 _unresolved.jsonl을
       * 줄 단위로 순회하지 않고 이 파일의 groups[]를 기준으로 판정한다 (analyzer_contract 참고). */
      unresolved_groups: "_workspace/index/_unresolved_groups.json",
      /* 대형 인덱스를 Read로 여는 대신 필요한 줄만 얻는 질의 도구. 플러그인 루트 기준 경로다.
       * 예전에는 존재하지 않는 `scripts/query-index.mjs`를 가리키고 있어 에이전트가 원본 JSON(최대 143MB)을
       * 직접 열 수밖에 없었다. */
      query_tool: "agents/lib/query-index.mjs",
      query_tool_hint: "node $CLAUDE_PLUGIN_ROOT/agents/lib/query-index.mjs summary --root <프로젝트>",
    },
    analyzer_contract: {
      full_source_rescan: false,
      /*
       * 대표 파일을 전부 열지 말고 이 예산 안에서 digest가 지목한 것만 골라 읽는다.
       * 예전에는 상한이 개수뿐이라 목록을 그대로 열면 20M 토큰이 넘는 경우가 있었다.
       */
      representative_read_budget_bytes: byteBudget,
      /*
       * 미해결 관계를 "전부 처리"하는 계약은 규모가 커지면 성립하지 않는다.
       * 실측(레거시 Java 4,883파일)에서 185,912건이 나왔고, 배치 200건 기준 930회로
       * analyzer가 완주할 수 없다. 이 경우 계약을 우선순위 부분 처리로 바꾸고
       * 무엇을 우선하는지 명시한다 — 조용히 잘라내는 대신 계약에 드러낸다.
       */
      /*
       * 판정 대상은 "후보 2개 이상"인 레코드뿐이다. 후보 0~1개(`no_candidates: true`)는
       * 고를 것이 없어 소스를 열어도 판정할 수 없으므로 계약에서 명시적으로 제외한다 —
       * 예전에는 이것들이 우선순위 맨 앞에 와서 판정 예산을 전부 소진했다.
       */
      skip_no_candidate_records: true,
      /*
       * 2026-09-01 그룹핑 도입: "전부 처리" 여부는 발생 위치 수(decidableCount)가 아니라
       * 고유 패턴 수(decidableGroupCount)로 판단한다. 같은 패턴이 수백 곳에서 반복되는
       * 레거시 코드베이스에서 발생 위치 기준으로 판단하면 실제로는 처리 가능한 규모인데도
       * "부분 처리"로 잘못 떨어진다.
       */
      process_all_unresolved: decidableGroupCount <= UNRESOLVED_FULL_PROCESSING_LIMIT,
      unresolved_priority: decidableGroupCount > UNRESOLVED_FULL_PROCESSING_LIMIT
        ? { limit: UNRESOLVED_FULL_PROCESSING_LIMIT, order: "candidates_asc", note: "후보 수가 적은 그룹부터 — 판정 가능성이 높은 순서" }
        : null,
      /* 그룹 단위 배치 크기 — 발생 위치 단위가 아니다. 그룹당 대표 사례 1곳만 읽으므로
       * 같은 200이라는 숫자가 예전보다 훨씬 넓은 실제 커버리지를 갖는다. */
      unresolved_batch_size: 200,
      /*
       * 판정 대상은 _unresolved_groups.json의 groups[]다 — _unresolved.jsonl을 줄 단위로
       * 순회하지 않는다. 그룹마다 대표 발생 위치(occurrences[0]) 하나만 읽어 판정하고,
       * 그 그룹의 occurrences[] 전체에 같은 판정을 적용해 add_edge를 occurrence 수만큼
       * 낸다(나머지 위치는 다시 열지 않는다). 같은 표현식이라도 클래스/모듈에 따라 다르게
       * 해석될 수 있다고 판단되면(예: 변수 선언 타입이 호출부마다 다름) 그 그룹은
       * 대표 사례 외 2~3곳을 더 확인하거나, 정말 문맥 의존적이면 occurrences를 나눠
       * 개별 판정으로 되돌린다 — 이 계약은 병합을 "강제"하지 않고 기본 전략만 제시한다.
       */
      dedup_by_pattern: true,
      require_file_line_evidence: true,
      require_module_coverage: true,
      /* digest가 지목한 좌표는 선택 열람이 허용된다. 무제한 재순회와 구분하기 위해 계약에 명시한다. */
      digest_guided_selective_read: true,
    },
  };
}

/* AI 보강 엣지가 in-degree를 채웠다면 그 심볼은 더 이상 데드 코드 후보가 아니다. */
function reconcileDeadCode(output) {
  if (!output.dead_code) return;
  const { inDegree } = degreeMaps(output.call_graph?.nodes || [], output.call_graph?.edges || []);
  const remaining = output.dead_code.unused_methods.filter((item) => (inDegree.get(item.id) || 0) === 0);
  if (!remaining.length) { delete output.dead_code; return; }
  output.dead_code.unused_methods = remaining;
}

/* ── 파일 분석 병렬화를 시도했다가 되돌린 기록 ──────────────────────────────
 *
 * analyzeFile()은 순수 함수이고 파일 간 의존이 없어서 worker_threads로 샤딩하면
 * 코어 수만큼 빨라질 것처럼 보인다. 실제로 구현해 실측했더니 **오히려 느려졌다**.
 *
 *   구조화 복제로 facts 객체 그래프 전달: 19.2초 → 18.4초 (2코어, 4% — 전달 비용이 이득을 상쇄)
 *   JSON 버퍼를 transferList로 무복사 전달:  29.4초 → 35.2초 (stringify/parse가 더 비쌌다)
 *   깨끗한 픽스처(2000파일/13MB)에서도:      2.96초 → 3.49초
 *
 * 원인은 이 인덱서가 CPU 바운드가 아니라 **중간 데이터 양**에 눌려 있다는 것이다.
 * 소스 96MB 트리가 facts 459MB, 최종 인덱스 250MB를 만든다 — 워커 경계를 넘기는 비용이
 * 추출 비용과 같은 자릿수라 병렬화로 회수할 여지가 없다.
 * 그래서 병렬화 코드를 넣지 않는다. 여기를 더 빠르게 하려면 스레드가 아니라
 * 산출물 양을 줄여야 한다(예: sql_usage의 text_preview처럼 항목마다 붙는 큰 필드).
 * 같은 이유로 파일별 facts 캐시도 두지 않는다(2026-08-14 폐지 결정 유지) —
 * 캐시 직렬화·파싱이 재추출보다 비쌌다(cold 32초 → 46초).
 */

function validateOutput(name, value) {
  const required = {
    symbols: ["_meta", "symbols"], call_graph: ["_meta", "nodes", "edges"], sql_usage: ["_meta", "sqls", "usages"],
    transactions: ["_meta", "boundaries"], external_io: ["_meta", "communications"], env_branches: ["_meta", "branches"],
    schema: ["_meta", "tables"], api_contract: ["_meta", "endpoints", "consumers", "matches", "unmatched_endpoints", "unmatched_consumers"],
    dead_code: ["_meta", "unused_methods", "unused_sql_ids", "unused_jsps"],
    ui_flow: ["_meta", "screens", "events", "datasets", "transactions"],
    client_index: ["_meta", "type", "js_count", "domain_structure", "sample_mappings", "jquery_versions"],
    data_flow: ["_meta", "chains"],
  }[name] || [];
  const missing = required.filter((key) => !(key in value));
  if (missing.length) throw new Error(`${name}.json 필수 필드 누락: ${missing.join(", ")}`);
}

export function buildIndex(options) {
  const root = resolve(options.root);
  const normalized = { ...options, root, requestedTier: options.tier || "Auto" };
  const existingPatchPath = join(root, "_workspace", "index", "_ai_patch.json");
  const preservePatch = options.mode === "incremental" && existsSync(existingPatchPath);
  const config = loadConfig(root, options.config);
  const { files, excluded: excludedSources } = listFiles(root, config.include_paths, config);
  const unsupportedFiles = discoverUnsupportedFiles(root, config.include_paths);
  /*
   * 파일별 해시 캐시(_workspace/.index-cache/)는 두지 않는다(2026-08-14 폐지, 2026-08-16 재검토로 유지 확정).
   * "인덱스만 갱신해줘"도 매번 전체 재분석한다. 되살려 실측해 보면 오히려 느려지는데,
   * 추출 결과(facts)가 원본 소스보다 훨씬 커서 캐시 직렬화·파싱이 재추출보다 비싸기 때문이다
   * (소스 96MB 트리 → facts 459MB, cold 32초 → 46초). 근거는 위 "파일 분석 병렬화를 시도했다가
   * 되돌린 기록" 주석에 함께 정리돼 있다. mode(init/incremental)는 preservePatch(위) 판단에만 쓴다.
   */
  const facts = files.map((file) => analyzeFile(file, root, config));
  const analyzed = files.length;
  const reused = 0;
  const generatedAt = kstIso();
  const latestMtime = files.length ? kstIso(new Date(Math.max(...files.map((item) => item.stats.mtimeMs)))) : generatedAt;
  const complexity = calculateComplexity(facts, config, files.length);
  const coverage = buildAdapterCoverage(facts, unsupportedFiles);
  normalized.tier = normalized.requestedTier === "Auto" ? complexity.recommended_tier : normalized.requestedTier;
  const { output, globalMeta, unresolved } = aggregate(facts, normalized, config, generatedAt, files.length, latestMtime, complexity, coverage, excludedSources, files);
  const indexDir = join(root, "_workspace", "index");
  mkdirSync(indexDir, { recursive: true });
  const stalePatch = join(indexDir, "_ai_patch.json");
  /*
   * 보존된 AI patch는 파일을 쓰기 전에 메모리 그래프에 병합한다.
   * 나중에 call_graph.json만 수정하면 digest·dead_code가 보강 이전 상태로 남아 서로 어긋난다.
   */
  if (preservePatch) {
    try {
      const merged = mergeAiPatchEdges(output.call_graph, readJson(stalePatch));
      output.call_graph._meta.edge_count = output.call_graph.edges.length;
      reconcileDeadCode(output);
      globalMeta.indexes = Object.keys(output);
      globalMeta.ai_enrichment = { applied_at: generatedAt, ...merged, patch: slash(relative(root, stalePatch)) };
      if (!merged.applied && merged.rejected) {
        process.stderr.write(`경고: 보존된 AI patch가 전부 거부되었습니다 (${JSON.stringify(merged.rejected_reasons)})\n`);
      }
    } catch (error) {
      process.stderr.write(`경고: 보존된 AI patch를 병합할 수 없어 무시합니다: ${error.message}\n`);
      globalMeta.ai_enrichment = { applied_at: generatedAt, applied: 0, rejected: 0, error: error.message, patch: slash(relative(root, stalePatch)) };
    }
  }
  const managed = new Set(["symbols", "call_graph", "sql_usage", "transactions", "external_io", "env_branches", "schema", "api_contract", "dead_code", "ui_flow", "client_index", "data_flow"]);
  for (const name of managed) {
    const path = join(indexDir, `${name}.json`);
    /*
     * 이번 회차에 만들지 못한 인덱스라도, 그 파일을 analyzer(LLM)가 썼다면 지우지 않는다.
     * 프레임워크를 인식하지 못한 프로젝트의 api_contract.json이나 라이브 DB에서 뜬 schema.json이
     * 재인덱싱 한 번에 조용히 사라지기 때문이다. 인덱서가 쓴 것만 인덱서가 회수한다.
     */
    if (!output[name]) {
      if (existsSync(path) && readJson(path, {})?._meta?.generator === "deterministic-indexer") rmSync(path);
      continue;
    }
    validateOutput(name, output[name]);
    atomicJson(path, output[name]);
  }
  /*
   * 미해결 항목은 한 건도 빠뜨리지 않고 기록한다(어디가 모호했는지는 전수가 감사 기록이다).
   * 다만 후보 목록까지 전부 적으면 레거시 규모에서 파일이 139MB까지 커지는데, 그 대부분은
   * analyzer_contract가 "처리 대상 아님"이라고 명시한 구간이다. 판정 대상(후보가 적은 순
   * 상위 N건)만 후보를 싣고, 나머지는 위치와 후보 수만 남긴다.
   */
  /*
   * 우선순위 정렬 기준을 "후보 수 오름차순"에서 **판정 가능성**으로 바꾼다(2026-08-16).
   *
   * 기존 정렬은 후보가 적은 순이라 **후보가 0개인 레코드가 항상 맨 앞**에 왔다.
   * 그런데 후보 0개는 모호한 게 아니라 "핸들러가 인덱스에 아예 없다"는 뜻이라 후보 중에서
   * 고를 것이 없다 — analyzer가 소스를 열어봐야 판정할 수 없는 종류다.
   * 반대로 진짜 판정 대상(후보 2개 이상)은 뒤로 밀려 `candidates_omitted`로 잘려나갔다.
   * 즉 LLM 판정 예산 2000건이 통째로 판정 불가능한 항목에 쓰이고, 판정 가능한 항목은
   * 처리되지 않는 상태였다. 실측 픽스처에서 처리 대상 2000건이 전부 후보 0개였다.
   *
   * 그래서 후보가 2개 이상인 것을 먼저(좁은 것부터) 놓고, 후보 0개는 뒤로 보낸다.
   * 후보 0개 레코드는 감사 기록으로는 남기되 `no_candidates: true`로 표시해
   * analyzer 계약이 판정 대상에서 제외할 수 있게 한다.
   */
  const prioritized = [...unresolved]
    .map((item, order) => ({ item, order, width: (item.candidates || []).length }))
    .sort((a, b) => {
      const decidable = (width) => (width >= 2 ? 0 : 1);
      return decidable(a.width) - decidable(b.width) || a.width - b.width || a.order - b.order;
    });
  const decidableCount = prioritized.filter(({ width }) => width >= 2).length;
  /*
   * 판정 대상(후보 2개 이상)을 (kind+식별필드+candidates) 패턴으로 묶는다 — groupUnresolvedDecidable
   * 주석 참조. 그룹 수(decidableGroupCount)가 analyzer의 실제 판정 횟수이자 비용 추정 기준이다.
   */
  const decidableItems = prioritized.filter(({ width }) => width >= 2).map(({ item }) => item);
  const groups = groupUnresolvedDecidable(decidableItems);
  const decidableGroupCount = groups.length;
  const groupIdByKey = new Map(groups.map((group) => [JSON.stringify([group.kind, group.key_field, group.candidates]), group.group_id]));
  const cappedGroups = groups.map((group, index) => {
    if (index < UNRESOLVED_FULL_PROCESSING_LIMIT) return group;
    /* 그룹 자체가 상한을 넘는 극단적인 경우에만 occurrences를 생략한다(실측상 거의 발생하지 않음 —
     * 189/483개 수준이던 실제 프로젝트 대비 이 상한은 훨씬 넉넉하다). */
    const { occurrences: _drop, ...rest } = group;
    return { ...rest, occurrences_omitted: true };
  });
  const cappedUnresolved = prioritized.map(({ item, width }, rank) => {
    const candidates = item.candidates || [];
    if (width < 2) {
      /* 후보 0~1개: 고를 것이 없다. 위치만 남기고 판정 대상에서 뺀다. */
      const { candidates: _drop, ...rest } = item;
      return { ...rest, candidate_count: candidates.length, no_candidates: true };
    }
    const group_id = groupIdByKey.get(unresolvedGroupKey(item));
    if (rank >= UNRESOLVED_FULL_PROCESSING_LIMIT) {
      const { candidates: _drop, ...rest } = item;
      return { ...rest, candidate_count: candidates.length, candidates_omitted: true, group_id };
    }
    if (candidates.length <= MAX_UNRESOLVED_CANDIDATES) return { ...item, group_id };
    return { ...item, candidates: candidates.slice(0, MAX_UNRESOLVED_CANDIDATES), candidates_truncated: candidates.length - MAX_UNRESOLVED_CANDIDATES, group_id };
  });
  atomicJson(join(indexDir, "_meta.json"), globalMeta);
  atomicJson(join(indexDir, "_analysis_input.json"), buildAnalysisInput(output, globalMeta, unresolved, decidableCount, decidableGroupCount, new Map(files.map((item) => [item.rel, item.stats.size]))));
  writeFileSync(join(indexDir, "_unresolved.jsonl"), cappedUnresolved.map((item) => JSON.stringify(item)).join("\n") + (unresolved.length ? "\n" : ""), "utf8");
  atomicJson(join(indexDir, "_unresolved_groups.json"), {
    _meta: { generated_at: generatedAt, generator: "deterministic-indexer", group_count: groups.length, decidable_raw_count: decidableCount, total_occurrences: decidableItems.length },
    groups: cappedGroups,
  });
  if (!preservePatch && existsSync(stalePatch)) rmSync(stalePatch);
  return { root, files: files.length, analyzed, reused, tier: normalized.tier, complexity, adapter_coverage: coverage, indexes: Object.keys(output), unresolved: unresolved.length };
}

/*
 * AI edge patch operation 정규화.
 * `agents/analyzer.md`는 평면 형태(`{op, from, to, type, ...}`)를 지시하고
 * 초기 구현은 중첩 형태(`{op, edge: {...}}`)만 받아서 모든 operation이 조용히 거부됐다.
 * 두 형태를 모두 수용하되, 어떤 이유로 거부됐는지는 반드시 드러낸다.
 */
function normalizeAiPatchOperation(operation) {
  if (!operation || typeof operation !== "object") return { reason: "not_an_object" };
  if (operation.op !== "add_edge") return { reason: "unsupported_op" };
  const source = operation.edge && typeof operation.edge === "object" ? operation.edge : operation;
  if (!source.from || !source.to || !source.type) return { reason: "missing_edge_fields" };
  return {
    edge: {
      from: source.from, to: source.to, type: source.type,
      file: source.file, line: source.line, workspace: source.workspace,
      confidence: source.confidence,
      /* 평면 형태의 `reason`은 중첩 형태의 `evidence`와 같은 역할이므로 근거로 보존한다. */
      evidence: source.evidence || source.reason,
    },
  };
}

export function mergeAiPatchEdges(graph, patch) {
  if (!patch || patch.version !== 1 || !Array.isArray(patch.operations)) throw new Error("AI patch는 version: 1과 operations[]가 필요합니다.");
  if (!graph?.nodes || !Array.isArray(graph.edges)) throw new Error("call_graph.json이 없어 AI patch를 적용할 수 없습니다.");
  const nodeIds = new Set(graph.nodes.map((item) => item.id));
  const edgeKeys = new Set(graph.edges.map((item) => `${item.from}:${item.to}:${item.type}`));
  const reasons = new Map();
  const samples = [];
  let applied = 0;
  let rejected = 0;
  let duplicates = 0;
  const reject = (reason, detail) => {
    rejected += 1;
    reasons.set(reason, (reasons.get(reason) || 0) + 1);
    if (samples.length < 20) samples.push({ reason, ...detail });
  };
  for (const operation of patch.operations) {
    const normalized = normalizeAiPatchOperation(operation);
    if (!normalized.edge) { reject(normalized.reason, { op: operation?.op ?? null }); continue; }
    const edge = normalized.edge;
    if (!nodeIds.has(edge.from)) { reject("unknown_from_node", { from: edge.from, to: edge.to }); continue; }
    if (!nodeIds.has(edge.to)) { reject("unknown_to_node", { from: edge.from, to: edge.to }); continue; }
    if (!AI_PATCH_EDGE_TYPES.has(edge.type)) { reject("invalid_edge_type", { from: edge.from, to: edge.to, type: edge.type }); continue; }
    const key = `${edge.from}:${edge.to}:${edge.type}`;
    if (edgeKeys.has(key)) { duplicates += 1; continue; }
    graph.edges.push({
      from: edge.from, to: edge.to, type: edge.type,
      ...(edge.file ? { file: edge.file } : {}),
      ...(Number.isInteger(edge.line) ? { line: edge.line } : {}),
      ...(edge.workspace ? { workspace: edge.workspace } : {}),
      origin: "ai-enrichment", confidence: edge.confidence || "MEDIUM",
      ...(edge.evidence ? { evidence: edge.evidence } : {}),
    });
    edgeKeys.add(key); applied += 1;
  }
  return { applied, rejected, duplicates, rejected_reasons: Object.fromEntries(reasons), rejected_samples: samples };
}

/*
 * api_contract.json(endpoints/consumers)·external_io.json(communications)에 analyzer가
 * "이게 무엇을 하는지" 1줄 설명을 얹는 오퍼레이션. call_graph의 add_edge와 같은 이유로
 * 원본 파일을 analyzer가 직접 재작성하지 않는다 — incremental 재인덱싱이 두 파일을 캐시에서
 * 다시 만들기 때문에 직접 덧붙인 내용은 다음 갱신에서 조용히 사라진다.
 */
function mergeDescriptionPatch(items, ops, field = "description") {
  const byId = new Map((items || []).map((item) => [item.id, item]));
  const reasons = new Map();
  const samples = [];
  let applied = 0;
  let rejected = 0;
  const reject = (reason, detail) => {
    rejected += 1;
    reasons.set(reason, (reasons.get(reason) || 0) + 1);
    if (samples.length < 20) samples.push({ reason, ...detail });
  };
  for (const op of ops) {
    const id = op && typeof op === "object" ? op.id : undefined;
    const text = op && typeof op === "object" ? op[field] : undefined;
    if (!id) { reject("missing_id", { op: op?.op ?? null }); continue; }
    if (typeof text !== "string" || !text.trim()) { reject(`missing_${field}`, { id }); continue; }
    const item = byId.get(id);
    if (!item) { reject("unknown_id", { id }); continue; }
    item[field] = text.trim();
    applied += 1;
  }
  return { applied, rejected, rejected_reasons: Object.fromEntries(reasons), rejected_samples: samples };
}

/*
 * call_graph.json 엣지는 (from, to, type) 조합이 자연 키다(mergeAiPatchEdges의 edgeKeys와 동일
 * 구성) — 노드처럼 단일 id가 없어 별도 매칭 함수가 필요하다. "이 호출이 왜 존재하는지"를
 * analyzer가 이 오퍼레이션으로만 얹는다(엣지 자체는 add_edge로만 새로 만들 수 있음, 여기선
 * 이미 있는 엣지에 note만 붙인다).
 */
function mergeEdgeNotes(edges, ops) {
  const byKey = new Map((edges || []).map((item) => [`${item.from}:${item.to}:${item.type}`, item]));
  const reasons = new Map();
  const samples = [];
  let applied = 0;
  let rejected = 0;
  const reject = (reason, detail) => {
    rejected += 1;
    reasons.set(reason, (reasons.get(reason) || 0) + 1);
    if (samples.length < 20) samples.push({ reason, ...detail });
  };
  for (const op of ops) {
    const from = op && typeof op === "object" ? op.from : undefined;
    const to = op && typeof op === "object" ? op.to : undefined;
    const type = op && typeof op === "object" ? op.type : undefined;
    const note = op && typeof op === "object" ? op.note : undefined;
    if (!from || !to || !type) { reject("missing_edge_fields", { from, to, type }); continue; }
    if (typeof note !== "string" || !note.trim()) { reject("missing_note", { from, to, type }); continue; }
    const item = byKey.get(`${from}:${to}:${type}`);
    if (!item) { reject("unknown_edge", { from, to, type }); continue; }
    item.note = note.trim();
    applied += 1;
  }
  return { applied, rejected, rejected_reasons: Object.fromEntries(reasons), rejected_samples: samples };
}

/*
 * client_index.json은 목록이 아니라 문서 자체에 판단 필드(ajax_contract/naming_convention/anti_patterns)를
 * 얹는다 — id로 찾는 목록 항목이 아니라 문서 최상위 필드라 mergeDescriptionPatch를 그대로 못 쓴다.
 * 구조 필드(type/js_count/domain_structure/sample_mappings/jquery_versions)는 인덱서 소유라 이 오퍼레이션으로
 * 건드릴 수 없다 — 세 서술 필드만 받는다.
 */
function mergeClientIndexNarrative(clientIndex, ops) {
  const reasons = new Map();
  const samples = [];
  let applied = 0;
  let rejected = 0;
  const reject = (reason, detail) => {
    rejected += 1;
    reasons.set(reason, (reasons.get(reason) || 0) + 1);
    if (samples.length < 20) samples.push({ reason, ...detail });
  };
  for (const op of ops) {
    const ajaxContract = op && typeof op === "object" ? op.ajax_contract : undefined;
    const namingConvention = op && typeof op === "object" ? op.naming_convention : undefined;
    const antiPatterns = op && typeof op === "object" ? op.anti_patterns : undefined;
    const hasAjax = typeof ajaxContract === "string" && ajaxContract.trim();
    const hasNaming = namingConvention && typeof namingConvention === "object";
    const hasAnti = Array.isArray(antiPatterns);
    if (!hasAjax && !hasNaming && !hasAnti) { reject("empty_narrative", {}); continue; }
    if (hasAjax) clientIndex.ajax_contract = ajaxContract.trim();
    if (hasNaming) clientIndex.naming_convention = namingConvention;
    if (hasAnti) clientIndex.anti_patterns = antiPatterns;
    applied += 1;
  }
  return { applied, rejected, rejected_reasons: Object.fromEntries(reasons), rejected_samples: samples };
}

function mergeCombinedResults(parts) {
  const rejected_reasons = {};
  const rejected_samples = [];
  let applied = 0;
  let rejected = 0;
  let duplicates = 0;
  for (const part of parts) {
    applied += part.applied || 0;
    rejected += part.rejected || 0;
    duplicates += part.duplicates || 0;
    for (const [reason, count] of Object.entries(part.rejected_reasons || {})) {
      rejected_reasons[reason] = (rejected_reasons[reason] || 0) + count;
    }
    rejected_samples.push(...(part.rejected_samples || []));
  }
  return { applied, rejected, duplicates, rejected_reasons, rejected_samples: rejected_samples.slice(0, 20) };
}

export function applyAiPatch(rootArg, patchArg) {
  const root = resolve(rootArg);
  const patchPath = isAbsolute(patchArg) ? patchArg : join(root, patchArg);
  const patch = readJson(patchPath);
  if (!patch || patch.version !== 1 || !Array.isArray(patch.operations)) throw new Error("AI patch는 version: 1과 operations[]가 필요합니다.");
  const indexDir = join(root, "_workspace", "index");
  const appliedAt = kstIso();

  /* op 종류별로 먼저 나눠서 각 대상 파일 병합이 서로의 거부 사유를 오염시키지 않게 한다.
   * add_edge/set_node_note/set_edge_note는 셋 다 call_graph.json이 대상이라 파일을 한 번만
   * 읽고 순서대로(엣지 추가 → 노드 설명 → 엣지 설명) 적용한 뒤 한 번만 쓴다. */
  const CALL_GRAPH_OPS = ["add_edge", "set_node_note", "set_edge_note"];
  const KNOWN_OPS = new Set([...CALL_GRAPH_OPS, "set_endpoint_description", "set_communication_description", "set_client_index_narrative", "set_flow_note"]);
  const buckets = { add_edge: [], set_node_note: [], set_edge_note: [], set_endpoint_description: [], set_communication_description: [], set_client_index_narrative: [], set_flow_note: [] };
  let unsupported = 0;
  const unsupportedSamples = [];
  for (const op of patch.operations) {
    const kind = op && typeof op === "object" ? op.op : undefined;
    if (kind && KNOWN_OPS.has(kind)) buckets[kind].push(op);
    else { unsupported += 1; if (unsupportedSamples.length < 20) unsupportedSamples.push({ reason: "unsupported_op", op: kind ?? null }); }
  }

  let edgeResult = { applied: 0, rejected: 0, duplicates: 0, rejected_reasons: {}, rejected_samples: [] };
  let nodeNoteResult = { applied: 0, rejected: 0, rejected_reasons: {}, rejected_samples: [] };
  let edgeNoteResult = { applied: 0, rejected: 0, rejected_reasons: {}, rejected_samples: [] };
  let edgeCount = null;
  const hasCallGraphOps = CALL_GRAPH_OPS.some((kind) => buckets[kind].length);
  if (hasCallGraphOps) {
    const graphPath = join(indexDir, "call_graph.json");
    const graph = readJson(graphPath);
    if (buckets.add_edge.length) {
      edgeResult = mergeAiPatchEdges(graph, { version: 1, operations: buckets.add_edge });
    }
    if (buckets.set_node_note.length) {
      nodeNoteResult = mergeDescriptionPatch(graph.nodes, buckets.set_node_note, "note");
    }
    if (buckets.set_edge_note.length) {
      edgeNoteResult = mergeEdgeNotes(graph.edges, buckets.set_edge_note);
    }
    graph._meta.edge_count = graph.edges.length;
    graph._meta.ai_enriched_at = appliedAt;
    graph._meta.ai_patch_applied = edgeResult.applied + nodeNoteResult.applied + edgeNoteResult.applied;
    atomicJson(graphPath, graph);
    edgeCount = graph.edges.length;

    /*
     * digest는 호출 그래프에서 파생되므로 보강된 엣지를 반영해야 한다(add_edge가 있었을 때만
     * 의미 있음 — note류는 그래프 구조에 영향 없으므로 digest 재계산 대상 아님).
     * 그러지 않으면 writer와 위키가 AI 판정 이전의 허브·진입점을 계속 본다.
     */
    if (edgeResult.applied) {
      const analysisInputPath = join(indexDir, "_analysis_input.json");
      const analysisInput = readJson(analysisInputPath);
      if (analysisInput?.digest) {
        Object.assign(analysisInput.digest, graphDigest(graph.nodes, graph.edges));
        if (analysisInput.counts) analysisInput.counts.graph_edges = graph.edges.length;
        atomicJson(analysisInputPath, analysisInput);
      }
    }
  }

  let endpointResult = { applied: 0, rejected: 0, rejected_reasons: {}, rejected_samples: [] };
  if (buckets.set_endpoint_description.length) {
    const contractPath = join(indexDir, "api_contract.json");
    const contract = existsSync(contractPath) ? readJson(contractPath) : null;
    if (!contract) {
      endpointResult = { applied: 0, rejected: buckets.set_endpoint_description.length, rejected_reasons: { no_api_contract: buckets.set_endpoint_description.length }, rejected_samples: [{ reason: "no_api_contract" }] };
    } else {
      endpointResult = mergeDescriptionPatch([...(contract.endpoints || []), ...(contract.consumers || [])], buckets.set_endpoint_description);
      if (endpointResult.applied) atomicJson(contractPath, contract);
    }
  }

  let commResult = { applied: 0, rejected: 0, rejected_reasons: {}, rejected_samples: [] };
  if (buckets.set_communication_description.length) {
    const ioPath = join(indexDir, "external_io.json");
    const io = existsSync(ioPath) ? readJson(ioPath) : null;
    if (!io) {
      commResult = { applied: 0, rejected: buckets.set_communication_description.length, rejected_reasons: { no_external_io: buckets.set_communication_description.length }, rejected_samples: [{ reason: "no_external_io" }] };
    } else {
      commResult = mergeDescriptionPatch(io.communications || [], buckets.set_communication_description);
      if (commResult.applied) atomicJson(ioPath, io);
    }
  }

  let clientIndexResult = { applied: 0, rejected: 0, rejected_reasons: {}, rejected_samples: [] };
  if (buckets.set_client_index_narrative.length) {
    const clientIndexPath = join(indexDir, "client_index.json");
    const clientIndexDoc = existsSync(clientIndexPath) ? readJson(clientIndexPath) : null;
    if (!clientIndexDoc) {
      clientIndexResult = { applied: 0, rejected: buckets.set_client_index_narrative.length, rejected_reasons: { no_client_index: buckets.set_client_index_narrative.length }, rejected_samples: [{ reason: "no_client_index" }] };
    } else {
      clientIndexResult = mergeClientIndexNarrative(clientIndexDoc, buckets.set_client_index_narrative);
      if (clientIndexResult.applied) atomicJson(clientIndexPath, clientIndexDoc);
    }
  }

  let flowNoteResult = { applied: 0, rejected: 0, rejected_reasons: {}, rejected_samples: [] };
  if (buckets.set_flow_note.length) {
    const dataFlowPath = join(indexDir, "data_flow.json");
    const dataFlowDoc = existsSync(dataFlowPath) ? readJson(dataFlowPath) : null;
    if (!dataFlowDoc) {
      flowNoteResult = { applied: 0, rejected: buckets.set_flow_note.length, rejected_reasons: { no_data_flow: buckets.set_flow_note.length }, rejected_samples: [{ reason: "no_data_flow" }] };
    } else {
      flowNoteResult = mergeDescriptionPatch(dataFlowDoc.chains, buckets.set_flow_note, "note");
      if (flowNoteResult.applied) atomicJson(dataFlowPath, dataFlowDoc);
    }
  }

  const unsupportedResult = { applied: 0, rejected: unsupported, rejected_reasons: unsupported ? { unsupported_op: unsupported } : {}, rejected_samples: unsupportedSamples };
  const result = mergeCombinedResults([edgeResult, nodeNoteResult, edgeNoteResult, endpointResult, commResult, clientIndexResult, flowNoteResult, unsupportedResult]);

  const enrichment = { applied_at: appliedAt, ...result, patch: slash(relative(root, patchPath)) };
  const metaPath = join(indexDir, "_meta.json");
  const meta = readJson(metaPath, {});
  meta.ai_enrichment = enrichment;
  atomicJson(metaPath, meta);
  return edgeCount === null ? { ...result } : { ...result, edges: edgeCount };
}

function printHelp() {
  process.stdout.write(`AX-Harness deterministic indexer\n\n` +
    `node scripts/build-index.mjs --root <project> --check-stale   # 재인덱싱 필요 여부만 판정(exit 0=최신, 1=필요)\n` +
    `node scripts/build-index.mjs --root <project> [--mode init|incremental|feature-scoped] [--tier Lite|Standard|Full] [--config <json>]\n` +
    `node scripts/build-index.mjs --root <project> --apply-ai-patch _workspace/index/_ai_patch.json\n`);
}

function main() {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (options.help) { printHelp(); return 0; }
    if (options.checkStale) {
      /* 팀원이 공유 하네스를 받은 뒤 "인덱싱을 다시 해야 하나"를 LLM 없이 묻는 경로.
       * exit 0 = 그대로 써도 됨, exit 1 = 재인덱싱 필요. */
      const state = indexStaleness(options.root);
      process.stdout.write(`${JSON.stringify(state, null, 2)}\n`);
      return state.stale ? 1 : 0;
    }
    const result = options.applyAiPatch ? applyAiPatch(options.root, options.applyAiPatch) : buildIndex(options);
    if (!options.quiet) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    /*
     * 조용한 실패 금지.
     * patch가 하나도 적용되지 않았는데 거부만 쌓였다면 AI 보강 경로가 끊긴 것이므로
     * 성공으로 보고하지 않고 거부 사유와 함께 non-zero로 끝낸다.
     */
    if (options.applyAiPatch && result.applied === 0 && result.rejected > 0) {
      process.stderr.write(`AI patch가 하나도 적용되지 않았습니다: ${JSON.stringify(result.rejected_reasons)}\n`);
      return 1;
    }
    return 0;
  } catch (error) {
    process.stderr.write(`인덱스 생성 실패: ${error.stack || error.message}\n`);
    return 1;
  }
}

const isMain = process.argv[1] && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, "$1"));
if (isMain) process.exit(main());
