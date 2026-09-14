import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

USAGE_PATH = Path(__file__).parent.parent / "usage.jsonl"

# Служебные ники для отладочных прогонов: их обращения НЕ попадают в usage.jsonl,
# чтобы проверки разработчика не искажали метрики панели (обращения, активность).
_TEST_PREFIXES = ("@test", "@тест", "@debug", "@отладк")


def is_test_user(username: str | None) -> bool:
    u = (username or "").strip().lower()
    return u.startswith(_TEST_PREFIXES)

# OpenAI gpt-4o pricing (USD per million tokens)
PRICE_INPUT = 2.5
PRICE_OUTPUT = 10.0

# Веб-поиск OpenAI: токены модели поиска + плата за каждый поисковый вызов.
# Цены — оценка, сверять с прайсом OpenAI; переопределяются через .env.
import os as _os
SEARCH_MODEL_PRICES = {  # USD за млн токенов: (вход, выход)
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.5, 10.0),
}
WEB_SEARCH_CALL_USD = float(_os.environ.get("WEB_SEARCH_CALL_USD", "0.025"))

# Записи, которые НЕ являются обращением участника к боту (не считаются в «обращения»)
NON_REQUEST_SERVICES = ("whisper", "web_search")

# OpenAI Whisper pricing (USD per second)
PRICE_WHISPER_PER_SEC = 0.006 / 60


def log_usage(
    chat_id: int,
    chat_type: str,
    username: str,
    input_tokens: int,
    output_tokens: int,
    kind: str = "text",
) -> None:
    if is_test_user(username):
        return  # отладочный прогон — в статистику не пишем
    cost = (input_tokens * PRICE_INPUT + output_tokens * PRICE_OUTPUT) / 1_000_000
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
        "chat_type": chat_type,
        "username": username,
        "kind": kind,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    }
    with USAGE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_web_search_usage(
    chat_id: int,
    chat_type: str,
    username: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    calls: int,
) -> None:
    """Расход на веб-поиск (отдельная строка в статистике, не «обращение»)."""
    if is_test_user(username):
        return  # отладочный прогон — в статистику не пишем
    pin, pout = SEARCH_MODEL_PRICES.get(model, SEARCH_MODEL_PRICES["gpt-4o-mini"])
    cost = (input_tokens * pin + output_tokens * pout) / 1_000_000 + max(calls, 1) * WEB_SEARCH_CALL_USD
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
        "chat_type": chat_type,
        "username": username,
        "service": "web_search",
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "calls": max(calls, 1),
        "cost_usd": round(cost, 6),
    }
    with USAGE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_voice_usage(
    chat_id: int,
    chat_type: str,
    username: str,
    duration_seconds: int,
) -> None:
    if is_test_user(username):
        return  # отладочный прогон — в статистику не пишем
    cost = duration_seconds * PRICE_WHISPER_PER_SEC
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
        "chat_type": chat_type,
        "username": username,
        "service": "whisper",
        "duration_seconds": duration_seconds,
        "cost_usd": round(cost, 6),
    }
    with USAGE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_stats(days: int = 30) -> str:
    if not USAGE_PATH.exists():
        return "Данных об использовании пока нет."

    irkutsk = timezone(timedelta(hours=8))
    cutoff = datetime.now(irkutsk) - timedelta(days=days)

    total_gpt_cost = 0.0
    total_whisper_cost = 0.0
    total_web_cost = 0.0
    total_web_calls = 0
    total_input = 0
    total_output = 0
    total_voice_sec = 0
    by_user: dict[str, dict] = defaultdict(lambda: {
        "input": 0, "output": 0, "gpt_cost": 0.0,
        "voice_sec": 0, "whisper_cost": 0.0, "requests": 0, "web_cost": 0.0,
    })

    with USAGE_PATH.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                ts = datetime.fromisoformat(e["ts"]).astimezone(irkutsk)
                if ts < cutoff:
                    continue
                u = e["username"]
                if e.get("service") == "web_search":
                    total_web_cost += e["cost_usd"]
                    total_web_calls += e.get("calls", 1)
                    by_user[u]["web_cost"] += e["cost_usd"]
                elif e.get("service") == "whisper":
                    cost = e["cost_usd"]
                    total_whisper_cost += cost
                    total_voice_sec += e.get("duration_seconds", 0)
                    by_user[u]["voice_sec"] += e.get("duration_seconds", 0)
                    by_user[u]["whisper_cost"] += cost
                else:
                    total_input += e["input_tokens"]
                    total_output += e["output_tokens"]
                    total_gpt_cost += e["cost_usd"]
                    by_user[u]["input"] += e["input_tokens"]
                    by_user[u]["output"] += e["output_tokens"]
                    by_user[u]["gpt_cost"] += e["cost_usd"]
                    by_user[u]["requests"] += 1
            except Exception:
                continue

    if not by_user:
        return f"За последние {days} дней запросов не было."

    total_cost = total_gpt_cost + total_whisper_cost + total_web_cost
    lines = [f"📊 <b>Статистика за {days} дней</b>\n"]
    lines.append(f"GPT: {total_input + total_output:,} токенов → <b>${total_gpt_cost:.4f}</b>")
    if total_voice_sec:
        lines.append(f"Whisper: {total_voice_sec // 60}м {total_voice_sec % 60}с аудио → <b>${total_whisper_cost:.4f}</b>")
    if total_web_calls:
        lines.append(f"Веб-поиск: {total_web_calls} запросов → <b>${total_web_cost:.4f}</b>")
    lines.append(f"Итого: <b>${total_cost:.4f}</b>\n")
    lines.append("<b>По пользователям:</b>")

    for user, data in sorted(by_user.items(), key=lambda x: x[1]["gpt_cost"] + x[1]["whisper_cost"] + x[1]["web_cost"], reverse=True):
        user_cost = data["gpt_cost"] + data["whisper_cost"] + data["web_cost"]
        parts = [f"• {user}:"]
        if data["requests"]:
            parts.append(f"{data['requests']} запросов GPT")
        if data["voice_sec"]:
            parts.append(f"{data['voice_sec']}с голоса")
        parts.append(f"<b>${user_cost:.4f}</b>")
        lines.append(" ".join(parts))

    return "\n".join(lines)
