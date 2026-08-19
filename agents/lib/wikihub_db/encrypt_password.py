# DB 접속 비밀번호를 암호화해 .env 에 저장하는 CLI (평문을 직접 입력하지 않고 넘어가는 용도)
"""encrypt_password.py — 평문 비밀번호를 입력받아 암호화한 뒤 `<PREFIX>_PASSWORD_ENC`로 .env 에 기록.

    python encrypt_password.py --root <프로젝트 루트> --engine mssql [--remove-plain]

sqlite 는 비밀번호가 없어 대상이 아니다.
"""

import os
import sys
import getpass
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import crypto_util

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

    plaintext = getpass.getpass(f"{prefix_field} 값을 입력하세요 (화면에 표시되지 않습니다): ")
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
