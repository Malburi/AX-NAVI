# DB 접속 비밀번호를 암호화해 .env 에 저장하는 CLI (평문을 직접 입력하지 않고 넘어가는 용도)
"""encrypt_password.py — 평문 비밀번호를 입력받아 암호화한 뒤 `<PREFIX>_PASSWORD_ENC`로 .env 에 기록.

    python encrypt_password.py --root <프로젝트 루트> --engine mssql [--remove-plain]

sqlite 는 비밀번호가 없어 대상이 아니다.
"""

import os
import sys
import shutil
import argparse
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import crypto_util


def _display_width(text):
    """터미널 표시 폭 계산 — 한글·전각 문자는 2칸으로 센다(줄바꿈 행 수 계산용)."""
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _prompt_and_erase(prompt):
    """비밀번호를 입력받되, 입력 중에는 화면에 그대로 보여 오타를 확인할 수 있게 하고
    엔터 직후 그 줄(줄바꿈으로 여러 행이 됐으면 그 행 전부)을 화면에서 지운다.

    엔터를 치기 전까지는 입력한 글자가 모두 보인다. 지우는 것은 현재 화면의 해당 줄뿐이며
    터미널 스크롤백 기록이나 이미 캡처된 로그·녹화까지 지우지는 못한다.
    """
    if os.name == "nt" and sys.stdout.isatty():
        os.system("")  # 윈도우 콘솔에서 ANSI 이스케이프 처리 활성화
    typed = input(prompt)
    if sys.stdout.isatty():
        try:
            cols = shutil.get_terminal_size((80, 24)).columns or 80
            total = _display_width(prompt) + _display_width(typed)
            rows = max(1, (total + cols - 1) // cols)
            sys.stdout.write(f"\033[{rows}F\033[0J")  # rows행 위로 이동 후 화면 끝까지 지움
            sys.stdout.flush()
        except Exception:
            # 화면 정리는 부가 기능 — 실패해도 암호화는 그대로 진행한다.
            pass
    return typed

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="DB 접속 비밀번호를 암호화해 .env 에 저장")
    parser.add_argument("--root", required=True, help="프로젝트 루트 절대 경로 (.env 위치)")
    parser.add_argument("--engine", required=True, choices=list(config.PASSWORD_FIELD.keys()),
                        help="mssql | postgresql | oracle (sqlite는 비밀번호 없음)")
    parser.add_argument("--remove-plain", action="store_true",
                        help="암호화 후 평문 비밀번호 필드를 .env 에서 제거한다")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    prefix_field = config.PASSWORD_FIELD[args.engine]

    plaintext = _prompt_and_erase(f"{prefix_field} 값을 입력하세요 (입력 중 보이며 엔터 후 지워집니다): ")
    if not plaintext:
        print("오류: 빈 비밀번호는 암호화하지 않습니다.", file=sys.stderr)
        sys.exit(1)

    try:
        token = crypto_util.encrypt_password(root, plaintext)
    except crypto_util.CryptoError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)

    config.set_env_value(root, f"{prefix_field}_ENC", token)

    removed = False
    if args.remove_plain:
        removed = config.remove_env_value(root, prefix_field)

    key_file = crypto_util.key_path(root)
    print(f"암호화 완료: {prefix_field}_ENC 를 .env 에 저장했습니다.")
    if removed:
        print(f"평문 {prefix_field} 필드는 .env 에서 제거했습니다.")
    print(f"키 파일: {key_file}")
    print("이 파일이 없으면 복호화할 수 없습니다 — 백업을 권장하며 git에는 올리지 마세요(.gitignore 등록됨).")


if __name__ == "__main__":
    main()
