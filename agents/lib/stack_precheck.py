# harness-init Phase 2-1 전, LLM 호출 없이 초저비용으로 결정론적 인덱스 추출기 적용 대상
# 스택(들)을 감지한다. 모노레포 등에서는 여러 스택이 동시에 감지될 수 있어 리스트로 반환.
import os
import sys
import json
import argparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from now_kst import now_kst

SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "out", ".idea", ".vscode", "__pycache__", "bin", "obj"}


def _walk_files(root, names_or_suffix, max_files=4000):
    """SKIP_DIRS를 건너뛰며 root 하위를 훑어 이름이 일치하거나(집합) 확장자가 일치하는(문자열)
    파일 경로를 최대 max_files개까지 수집한다."""
    found = []
    is_suffix = isinstance(names_or_suffix, str)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if (is_suffix and fn.endswith(names_or_suffix)) or (not is_suffix and fn in names_or_suffix):
                found.append(os.path.join(dirpath, fn))
                if len(found) >= max_files:
                    return found
    return found


def _read_head(path, n=4000):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(n)
    except OSError:
        return ""


def _detect_java_spring(root):
    build_files = _walk_files(root, ("pom.xml", "build.gradle", "build.gradle.kts"), max_files=20)
    if not build_files:
        return None
    markers = ("org.springframework", "spring-boot", "spring-context", "spring-webmvc")
    for bf in build_files:
        text = _read_head(bf, 20000)
        if any(m in text for m in markers):
            return {"stack": "java_spring", "evidence": [f"빌드 파일: {os.path.relpath(bf, root)}", "Spring 마커 발견"]}
    java_files = _walk_files(root, ".java", max_files=30)
    for jf in java_files:
        if "org.springframework" in _read_head(jf):
            return {"stack": "java_spring", "evidence": [f"빌드 파일: {os.path.relpath(build_files[0], root)}", f"Spring import: {os.path.relpath(jf, root)}"]}
    return None


def _detect_csharp(root):
    csproj = _walk_files(root, ".csproj", max_files=20)
    if not csproj:
        return None
    return {"stack": "csharp_dotnet", "evidence": [f"프로젝트 파일: {os.path.relpath(csproj[0], root)}"]}


def _detect_python(root):
    manifests = _walk_files(root, ("requirements.txt", "pyproject.toml", "Pipfile"), max_files=20)
    py_files = _walk_files(root, ".py", max_files=1)
    if not manifests and not py_files:
        return None
    markers = ("fastapi", "django", "flask")
    for mf in manifests:
        text = _read_head(mf, 20000).lower()
        if any(m in text for m in markers):
            return {"stack": "python_web", "evidence": [f"매니페스트: {os.path.relpath(mf, root)}", "웹 프레임워크 마커 발견"]}
    if py_files:
        return {"stack": "python_web", "evidence": [".py 파일 존재 — 프레임워크 마커는 미확인, 일반 Python 클래스/함수만 추출"]}
    return None


def _detect_vue(root):
    vue_files = _walk_files(root, ".vue", max_files=1)
    pkg = _walk_files(root, ("package.json",), max_files=10)
    vue_pkg = None
    for pf in pkg:
        text = _read_head(pf, 20000)
        if '"vue"' in text:
            vue_pkg = pf
            break
    if not vue_files and not vue_pkg:
        return None
    evidence = []
    if vue_files:
        evidence.append(f".vue SFC 존재: {os.path.relpath(vue_files[0], root)}")
    if vue_pkg:
        evidence.append(f"package.json에 vue 의존성: {os.path.relpath(vue_pkg, root)}")
    return {"stack": "vue", "evidence": evidence}


def _detect_kotlin_android(root):
    manifest = _walk_files(root, ("AndroidManifest.xml",), max_files=5)
    kt_files = _walk_files(root, ".kt", max_files=1)
    if not manifest and not kt_files:
        return None
    evidence = []
    if manifest:
        evidence.append(f"AndroidManifest.xml 존재: {os.path.relpath(manifest[0], root)}")
    if kt_files:
        evidence.append(f".kt 파일 존재: {os.path.relpath(kt_files[0], root)}")
    return {"stack": "kotlin_android", "evidence": evidence}


DETECTORS = (_detect_java_spring, _detect_csharp, _detect_python, _detect_vue, _detect_kotlin_android)


def detect(root):
    extractors = []
    for fn in DETECTORS:
        result = fn(root)
        if result:
            extractors.append(result)
    return {"extractors": extractors}


def main():
    parser = argparse.ArgumentParser(description="결정론적 인덱스 추출기 적용 대상 스택(들) 사전 감지 (LLM 미사용)")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    result = detect(args.root)
    result["_meta"] = {"generated_at": now_kst(), "generator": "stack_precheck"}

    out_dir = os.path.join(args.root, "_workspace")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "00_stack_precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if not result["extractors"]:
        print("extractors: (없음 — 기계 추출 대상 스택 미감지)")
    for item in result["extractors"]:
        print(f"extractor={item['stack']}")
        for e in item["evidence"]:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
