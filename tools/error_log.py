"""Журнал ошибок бота для отладки (панель → вкладка «Ошибки»).

Пишет сбои обработки (документы/голос/картинки/агент) в errors.jsonl с
временем (Иркутск UTC+8), автором (ФИО из реестра, иначе ник) и chat_id.
Логирование не должно ронять бота — все операции обёрнуты в try/except.
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from tools.access import verified_name

ERRORS_PATH = Path(__file__).parent.parent / "errors.jsonl"
_IRKUTSK = timezone(timedelta(hours=8))
_MAX_KEEP = 500


def _author(user_id, username: str | None) -> str:
    if user_id is not None:
        name = verified_name(user_id)
        if name:
            return name
    return username or (f"id{user_id}" if user_id else "—")


def log_error(where: str, message, user_id=None, username: str | None = None, chat_id=None) -> None:
    """Записать ошибку. where — контекст (напр. «документ-чтение», «agent-голос»)."""
    try:
        rec = {
            "ts": datetime.now(_IRKUTSK).isoformat(timespec="seconds"),
            "where": where,
            "author": _author(user_id, username),
            "chat_id": chat_id,
            "message": str(message)[:1000],
        }
        with ERRORS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _trim()
    except Exception:
        pass


def _trim() -> None:
    try:
        lines = ERRORS_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) > _MAX_KEEP * 2:
            ERRORS_PATH.write_text("\n".join(lines[-_MAX_KEEP:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def read_errors(limit: int = _MAX_KEEP) -> list[dict]:
    """Последние ошибки, новые сверху."""
    if not ERRORS_PATH.exists():
        return []
    out = []
    for line in ERRORS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(out[-limit:]))


def clear_errors() -> None:
    try:
        ERRORS_PATH.write_text("", encoding="utf-8")
    except Exception:
        pass
