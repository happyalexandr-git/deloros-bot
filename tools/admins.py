"""Админы панели: телефон → хеш пароля. Вход в панель только для них.

Рантайм-данные (PII/секреты) — JSON вне git. Пароли хранятся как
pbkdf2-хеш, не в открытом виде.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path

from tools.roster import normalize_phone

ADMINS_PATH = Path(__file__).parent.parent / "admins.json"


def _load() -> dict:
    if ADMINS_PATH.exists():
        try:
            return json.loads(ADMINS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    ADMINS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(ADMINS_PATH, 0o600)
    except Exception:
        pass


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def is_admin(phone: str) -> bool:
    return normalize_phone(phone) in _load()


def set_admin(phone: str, password: str) -> None:
    """Делает участника админом панели с заданным паролем (хешируется)."""
    salt = os.urandom(16).hex()
    data = _load()
    data[normalize_phone(phone)] = {"salt": salt, "hash": _hash(password, salt)}
    _save(data)


def unset_admin(phone: str) -> None:
    data = _load()
    data.pop(normalize_phone(phone), None)
    _save(data)


def verify(phone: str, password: str) -> bool:
    """Проверяет телефон+пароль админа (constant-time)."""
    rec = _load().get(normalize_phone(phone))
    if not rec:
        return False
    return hmac.compare_digest(rec["hash"], _hash(password, rec["salt"]))


def admin_phones() -> set[str]:
    return set(_load().keys())
