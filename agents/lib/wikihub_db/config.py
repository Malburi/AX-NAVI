# .env 설정을 읽어 MSSQL·PostgreSQL·Oracle·SQLite 중 하나의 SQLAlchemy 접속 URL을 만드는 모듈
# 별도 프로젝트 wiki-hub(E:/AI/wiki-hub)의 wikihub/config.py를 그대로 옮긴 사본이다.
"""config.py — 접속 설정 로딩 + 엔진별 SQLAlchemy URL 조립.

설정은 대상 프로젝트(harness 산출물이 있는 폴더)의 `.env`에서 읽는다.

지원 엔진과 필요한 드라이버:
    mssql       pymssql        mssql+pymssql://user:pass@host:port/db
    postgresql  psycopg2       postgresql+psycopg2://user:pass@host:port/db
    oracle      oracledb (thin, Instant Client 불필요)  oracle+oracledb://user:pass@host:port/?service_name=...
    sqlite      (표준 라이브러리)                         sqlite:///경로

`WIKI_DB_URL`을 직접 주면 위 조립을 건너뛰고 그 값을 그대로 쓴다 (고급 사용자용 탈출구).

비밀번호는 평문(`*_PASSWORD`) 또는 암호화(`*_PASSWORD_ENC`, 권장 — `encrypt_password.py`로 생성,
`.wiki_db.key` 키 파일 필요) 중 하나만 있으면 된다. 둘 다 있으면 `_ENC`를 우선한다.
"""

import os
import sys
from urllib.parse import quote_plus

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class ConfigError(Exception):
    pass


SUPPORTED_ENGINES = ["mssql", "postgresql", "oracle", "sqlite"]

PASSWORD_FIELD = {
    "mssql": "MSSQL_PASSWORD",
    "postgresql": "PG_PASSWORD",
    "oracle": "ORACLE_PASSWORD",
}

REQUIRED_FIELDS = {
    "mssql": ["MSSQL_HOST", "MSSQL_PORT", "MSSQL_USER", "MSSQL_DATABASE"],
    "postgresql": ["PG_HOST", "PG_PORT", "PG_USER", "PG_DATABASE"],
    "oracle": ["ORACLE_HOST", "ORACLE_PORT", "ORACLE_SERVICE", "ORACLE_USER"],
    "sqlite": ["WIKI_SQLITE_PATH"],
}

DRIVER_HINT = {
    "mssql": "pip install sqlalchemy pymssql",
    "postgresql": "pip install sqlalchemy psycopg2-binary",
    "oracle": "pip install sqlalchemy oracledb",
    "sqlite": "pip install sqlalchemy  (그 외 추가 설치 불필요)",
}


def load_env_file(root):
    """<root>/.env 를 KEY=VALUE 로 파싱한다. 파일이 없으면 빈 dict."""
    path = os.path.join(root, ".env")
    values = {}
    if not os.path.isfile(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()
    return values


def upsert_env_value(root, key, value):
    """.env 에 key 가 없으면 추가한다. 이미 있으면 기존 값을 그대로 반환
    (기존 설정이 실수로 바뀌는 사고 방지)."""
    path = os.path.join(root, ".env")
    lines = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                existing = stripped.partition("=")[2].strip()
                if existing:
                    return existing
    with open(path, "a", encoding="utf-8") as f:
        if lines and not lines[-1].endswith("\n"):
            f.write("\n")
        f.write(f"{key}={value}\n")
    return value


def set_env_value(root, key, value):
    """.env 의 key 값을 무조건 덮어쓴다(없으면 추가). 암호화 워크플로우 전용 —
    재암호화 시 이전 토큰을 갱신해야 하므로 upsert_env_value(보존 우선)와 분리한다."""
    path = os.path.join(root, ".env")
    lines = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            lines[i] = f"{key}={value}\n"
            replaced = True
            break
    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return value


def remove_env_value(root, key):
    """.env 에서 key 줄을 제거한다. 없으면 아무것도 하지 않는다."""
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    kept = [line for line in lines if not (line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="))]
    if len(kept) == len(lines):
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(kept)
    return True


def resolve_engine(env, override=None):
    """사용할 DB 엔진 결정. 우선순위: override > .env WIKI_DB_ENGINE > sqlite(안전한 기본값)."""
    if override:
        return override.strip().lower()
    if env.get("WIKI_DB_ENGINE"):
        return env["WIKI_DB_ENGINE"].strip().lower()
    return "sqlite"


def resolve_system_key(root, env, override=None, quiet=False):
    if override:
        return override
    if env.get("WIKI_SYSTEM_KEY"):
        return env["WIKI_SYSTEM_KEY"]
    fallback = os.path.basename(os.path.normpath(root))
    if not quiet:
        print(
            f"WARN: WIKI_SYSTEM_KEY 미설정 — 폴더명('{fallback}')으로 시스템을 구분합니다. "
            "다른 시스템과 폴더명이 같으면 데이터가 섞입니다. .env 에 WIKI_SYSTEM_KEY 설정을 권장합니다."
        )
    return fallback


COMPONENT_TYPES = ["backend", "frontend", "fullstack", "batch", "mobile", "common"]
DEFAULT_COMPONENT_TYPE = "common"


def detect_component(root, env, key_override=None, type_override=None):
    """컴포넌트 키·타입 결정. 우선순위:
    override > .env(WIKI_COMPONENT_KEY/TYPE) > _workspace/pair_config.md 의 project_type > 폴더명 추정."""
    import re

    ckey = key_override or env.get("WIKI_COMPONENT_KEY")
    ctype = (type_override or env.get("WIKI_COMPONENT_TYPE") or "").strip().lower()

    if not ctype:
        pair_path = os.path.join(root, "_workspace", "pair_config.md")
        if os.path.isfile(pair_path):
            with open(pair_path, "r", encoding="utf-8") as f:
                text = f.read()
            m = re.search(r"^project_type:\s*(.+)$", text, re.MULTILINE)
            if m and m.group(1).strip().lower() in COMPONENT_TYPES:
                ctype = m.group(1).strip().lower()

    if not ctype:
        name = os.path.basename(os.path.normpath(root)).lower()
        guess = {
            "backend": ["backend", "back", "api", "server", "was", "be"],
            "frontend": ["frontend", "front", "web", "ui", "client", "fe"],
            "batch": ["batch", "scheduler", "job"],
            "mobile": ["mobile", "app", "android", "ios"],
        }
        for t, tokens in guess.items():
            if any(re.search(rf"(^|[-_]){tok}([-_]|$)", name) for tok in tokens):
                ctype = t
                break

    ctype = ctype if ctype in COMPONENT_TYPES else DEFAULT_COMPONENT_TYPE
    return (ckey or ctype), ctype


def resolve_password(engine, env, root):
    """비밀번호를 얻는다. `*_PASSWORD_ENC`가 있으면 복호화해서, 없으면 평문 `*_PASSWORD`를 그대로 쓴다."""
    prefix_field = PASSWORD_FIELD[engine]
    enc = env.get(f"{prefix_field}_ENC")
    if enc:
        import crypto_util
        try:
            return crypto_util.decrypt_password(root, enc)
        except crypto_util.CryptoError as e:
            raise ConfigError(str(e))
    return env.get(prefix_field, "")


def build_url(engine, env, root):
    """엔진별 필수 항목을 검사하고 SQLAlchemy 접속 URL을 만든다."""
    if env.get("WIKI_DB_URL"):
        return env["WIKI_DB_URL"]

    if engine not in SUPPORTED_ENGINES:
        raise ConfigError(
            f"지원하지 않는 WIKI_DB_ENGINE='{engine}' — {', '.join(SUPPORTED_ENGINES)} 중 하나를 쓰세요."
        )

    missing = [k for k in REQUIRED_FIELDS[engine] if not env.get(k)]
    if engine in PASSWORD_FIELD:
        pw_field = PASSWORD_FIELD[engine]
        if not (env.get(f"{pw_field}_ENC") or env.get(pw_field)):
            missing.append(f"{pw_field} (또는 {pw_field}_ENC)")
    if missing:
        raise ConfigError(
            f".env 에 다음 항목이 없습니다 ({engine}): {', '.join(missing)}\n"
            f"드라이버 설치: {DRIVER_HINT[engine]}"
        )

    if engine == "sqlite":
        path = os.path.abspath(os.path.expanduser(env["WIKI_SQLITE_PATH"]))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return f"sqlite:///{path}"

    if engine == "mssql":
        return (
            f"mssql+pymssql://{quote_plus(env['MSSQL_USER'])}:{quote_plus(resolve_password(engine, env, root))}"
            f"@{env['MSSQL_HOST']}:{env['MSSQL_PORT']}/{env['MSSQL_DATABASE']}"
        )

    if engine == "postgresql":
        return (
            f"postgresql+psycopg2://{quote_plus(env['PG_USER'])}:{quote_plus(resolve_password(engine, env, root))}"
            f"@{env['PG_HOST']}:{env['PG_PORT']}/{env['PG_DATABASE']}"
        )

    if engine == "oracle":
        return (
            f"oracle+oracledb://{quote_plus(env['ORACLE_USER'])}:{quote_plus(resolve_password(engine, env, root))}"
            f"@{env['ORACLE_HOST']}:{env['ORACLE_PORT']}/?service_name={env['ORACLE_SERVICE']}"
        )

    raise ConfigError(f"알 수 없는 엔진: {engine}")  # pragma: no cover — 위에서 이미 걸러짐


def describe_url(engine, url):
    """로그·화면에 보일 접속 정보 (비밀번호는 가린다)."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            creds, tail = rest.rsplit("@", 1)
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:***@{tail}"
    return f"{engine} ({url})"


def resolve_all(root, engine_override=None):
    """<root>/.env 를 읽어 (engine, url, env) 를 한 번에 돌려준다."""
    env = load_env_file(root)
    engine = resolve_engine(env, engine_override)
    url = build_url(engine, env, root)
    return engine, url, env
