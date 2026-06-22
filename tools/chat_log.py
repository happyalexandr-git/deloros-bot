import json
from datetime import datetime, timezone
from pathlib import Path

CHAT_LOGS_PATH = Path(__file__).parent.parent / "chat_logs"
CHAT_LOGS_PATH.mkdir(exist_ok=True)

def save_message(chat_id: int, username: str, text: str) -> None:
    path = CHAT_LOGS_PATH / f"{chat_id}.jsonl"
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "text": text,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_chat_log(chat_id: int, limit: int = 100) -> str:
    """Возвращает последние сообщения чата для саммари."""
    path = CHAT_LOGS_PATH / f"{chat_id}.jsonl"
    if not path.exists():
        return "История сообщений пуста."

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    recent = lines[-limit:]

    if not recent:
        return "История сообщений пуста."

    messages = []
    for line in recent:
        try:
            e = json.loads(line)
            from datetime import timedelta, timezone as tz
            irkutsk = tz(timedelta(hours=8))
            ts = datetime.fromisoformat(e["ts"]).astimezone(irkutsk).strftime("%d.%m %H:%M")
            messages.append(f"[{ts}] {e['username']}: {e['text']}")
        except Exception:
            continue

    return "\n".join(messages)


def search_chat_log(chat_id: int, query: str, limit: int = 20) -> str:
    """Поиск по ключевым словам в полной истории чата."""
    path = CHAT_LOGS_PATH / f"{chat_id}.jsonl"
    if not path.exists():
        return "История сообщений пуста."

    query_lower = query.lower()
    results = []

    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                if query_lower in e["text"].lower():
                    from datetime import timedelta, timezone as tz
                    irkutsk = tz(timedelta(hours=8))
                    ts = datetime.fromisoformat(e["ts"]).astimezone(irkutsk).strftime("%d.%m %H:%M")
                    results.append(f"[{ts}] {e['username']}: {e['text']}")
            except Exception:
                continue

    if not results:
        return f"По запросу «{query}» в истории чата ничего не найдено."

    header = f"Найдено сообщений: {len(results)}\n\n"
    return header + "\n".join(results[-limit:])
