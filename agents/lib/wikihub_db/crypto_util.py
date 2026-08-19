# DB 접속 비밀번호를 로컬 키 파일 기반 Fernet 대칭암호로 암복호화하는 모듈
"""crypto_util.py — `.wiki_db.key`(프로젝트 루트, git 미포함)를 키로 쓰는 Fernet 암복호화.

- 키는 `.env`와 분리 보관한다 — `.env`가 유출돼도 이 파일 없이는 복호화 불가.
- 저장 대상은 DB 접속 비밀번호뿐이다(다른 필드는 암호화하지 않는다).
"""

import os

KEY_FILENAME = ".wiki_db.key"


class CryptoError(Exception):
    pass


def _fernet_cls():
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        raise CryptoError(
            "비밀번호 암복호화에 cryptography 패키지가 필요합니다.\n"
            "  pip install cryptography"
        )
    return Fernet, InvalidToken


def key_path(root):
    return os.path.join(root, KEY_FILENAME)


def get_or_create_key(root):
    """<root>/.wiki_db.key 를 읽는다. 없으면 새로 생성해 저장한다."""
    Fernet, _ = _fernet_cls()
    path = key_path(root)
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read().strip()

    key = Fernet.generate_key()
    with open(path, "wb") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows 등 chmod 미지원 환경 — 무시
    return key


def encrypt_password(root, plaintext):
    Fernet, _ = _fernet_cls()
    key = get_or_create_key(root)
    token = Fernet(key).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_password(root, token):
    Fernet, InvalidToken = _fernet_cls()
    path = key_path(root)
    if not os.path.isfile(path):
        raise CryptoError(
            f"암호화된 비밀번호가 있지만 키 파일이 없습니다: {path}\n"
            "이 파일이 없으면 복호화할 수 없습니다 — 키 파일을 복원하거나 비밀번호를 다시 암호화하세요."
        )
    key = get_or_create_key(root)
    try:
        return Fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise CryptoError(
            f"비밀번호 복호화 실패 — 키 파일({path})이 암호화 당시와 다르거나 값이 손상됐습니다."
        )
