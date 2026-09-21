"""Encryption for the handful of third-party secrets kept in ``settings``.

The key comes from ``LP_SECRET_KEY`` if set (recommended for a server, e.g. via
systemd's ``EnvironmentFile``); otherwise it is generated once into
``DATA_DIR / "secret.key"`` with mode ``0o600``. Values are stored as
``"enc:" + fernet_token``; a stored value without that prefix is legacy
plaintext and is returned as-is (and re-encrypted by ``migrate_plaintext_secrets``).
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

from .config import DATA_DIR

PREFIX = "enc:"

_fernet: Fernet | None = None


def _load_key() -> bytes:
    env_key = os.environ.get("LP_SECRET_KEY")
    if env_key:
        return env_key.encode()
    key_path = DATA_DIR / "secret.key"
    if key_path.exists():
        return key_path.read_bytes()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    token = _get_fernet().encrypt(plain.encode()).decode()
    return PREFIX + token


def decrypt(stored: str) -> str:
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        return stored  # legacy plaintext
    token = stored[len(PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError(
            "Could not decrypt a stored secret. If LP_SECRET_KEY changed or is "
            "missing, restore the key that encrypted it (or the data/secret.key "
            "file) before starting the server."
        ) from e
