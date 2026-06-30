"""Подтверждённые пользователи: MAX user_id → участник клуба.

Рантайм-состояние (не контент): кто уже подтвердил телефон, чтобы не
переспрашивать при каждом заходе. JSON, вне git.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

VERIFIED_PATH = Path(__file__).parent.parent / "verified_users.json"


def _load() -> dict:
    if VERIFIED_PATH.exists():
        try:
            return json.loads(VERIFIED_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data: dict) -> None:
    VERIFIED_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_verified(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return str(user_id) in _load()


def verified_name(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    return _load().get(str(user_id), {}).get("name")


def verified_phones() -> set[str]:
    """Множество нормализованных телефонов, подтвердивших участие."""
    return {v.get("phone", "") for v in _load().values() if v.get("phone")}


def mark_verified(user_id: int, phone: str, name: str, username: str | None = None) -> None:
    data = _load()
    data[str(user_id)] = {
        "phone": phone,
        "name": name,
        "username": username or "",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(data)


def phone_of(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    return _load().get(str(user_id), {}).get("phone")


def by_phone(phone: str) -> dict | None:
    """Возвращает запись подтверждённого участника по телефону (user_id, name, username)."""
    for uid, v in _load().items():
        if v.get("phone") == phone:
            return {"user_id": int(uid), **v}
    return None


def all_verified() -> list[dict]:
    """Все подтверждённые: [{user_id, phone, name, username}]."""
    return [{"user_id": int(uid), **v} for uid, v in _load().items()]
