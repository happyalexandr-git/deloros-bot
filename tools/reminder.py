import json
import uuid
from datetime import datetime
from pathlib import Path

REMINDERS_PATH = Path(__file__).parent.parent / "reminders.json"


def _load() -> list[dict]:
    if REMINDERS_PATH.exists():
        try:
            return json.loads(REMINDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(reminders: list[dict]) -> None:
    REMINDERS_PATH.write_text(json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8")


def add_reminder(chat_id: int, text: str, send_at: str) -> str:
    """
    Сохраняет напоминание.
    send_at — строка формата 'YYYY-MM-DD HH:MM' в UTC+8 (Иркутск).
    """
    try:
        dt = datetime.strptime(send_at, "%Y-%m-%d %H:%M")
    except ValueError:
        return f"Неверный формат времени: {send_at}. Используй 'YYYY-MM-DD HH:MM'."

    reminders = _load()
    reminders.append({
        "id": str(uuid.uuid4())[:8],
        "chat_id": chat_id,
        "text": text,
        "send_at": dt.isoformat(),
        "sent": False,
    })
    _save(reminders)
    return f"Напоминание сохранено на {send_at} (Иркутск UTC+8)."


def get_due_reminders() -> list[dict]:
    """Возвращает напоминания у которых подошло время (UTC+8)."""
    from datetime import timezone, timedelta
    irkutsk = timezone(timedelta(hours=8))
    now = datetime.now(irkutsk).replace(tzinfo=None)

    reminders = _load()
    due = [r for r in reminders if not r["sent"] and datetime.fromisoformat(r["send_at"]) <= now]
    return due


def mark_sent(reminder_id: str) -> None:
    reminders = _load()
    for r in reminders:
        if r["id"] == reminder_id:
            r["sent"] = True
    _save(reminders)


def list_reminders(chat_id: int) -> str:
    """Возвращает список активных напоминаний."""
    reminders = _load()
    active = [r for r in reminders if not r["sent"]]
    if not active:
        return "Активных напоминаний нет."
    lines = [f"📅 **Запланированные напоминания ({len(active)}):**\n"]
    for r in sorted(active, key=lambda x: x["send_at"]):
        dt = datetime.fromisoformat(r["send_at"]).strftime("%d.%m.%Y %H:%M")
        lines.append(f"• [{r['id']}] **{dt}** (UTC+8)\n  {r['text']}")
    return "\n".join(lines)
