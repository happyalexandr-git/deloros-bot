import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

USAGE_PATH = Path(__file__).parent.parent / "usage.jsonl"

# OpenAI gpt-4o pricing (USD per million tokens)
PRICE_INPUT = 2.5
PRICE_OUTPUT = 10.0

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


def log_voice_usage(
    chat_id: int,
    chat_type: str,
    username: str,
    duration_seconds: int,
) -> None:
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
    total_input = 0
    total_output = 0
    total_voice_sec = 0
    by_user: dict[str, dict] = defaultdict(lambda: {
        "input": 0, "output": 0, "gpt_cost": 0.0,
        "voice_sec": 0, "whisper_cost": 0.0, "requests": 0,
    })

    with USAGE_PATH.open(encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
                ts = datetime.fromisoformat(e["ts"]).astimezone(irkutsk)
                if ts < cutoff:
                    continue
                u = e["username"]
                if e.get("service") == "whisper":
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

    total_cost = total_gpt_cost + total_whisper_cost
    lines = [f"📊 <b>Статистика за {days} дней</b>\n"]
    lines.append(f"GPT: {total_input + total_output:,} токенов → <b>${total_gpt_cost:.4f}</b>")
    if total_voice_sec:
        lines.append(f"Whisper: {total_voice_sec // 60}м {total_voice_sec % 60}с аудио → <b>${total_whisper_cost:.4f}</b>")
    lines.append(f"Итого: <b>${total_cost:.4f}</b>\n")
    lines.append("<b>По пользователям:</b>")

    for user, data in sorted(by_user.items(), key=lambda x: x[1]["gpt_cost"] + x[1]["whisper_cost"], reverse=True):
        user_cost = data["gpt_cost"] + data["whisper_cost"]
        parts = [f"• {user}:"]
        if data["requests"]:
            parts.append(f"{data['requests']} запросов GPT")
        if data["voice_sec"]:
            parts.append(f"{data['voice_sec']}с голоса")
        parts.append(f"<b>${user_cost:.4f}</b>")
        lines.append(" ".join(parts))

    return "\n".join(lines)
