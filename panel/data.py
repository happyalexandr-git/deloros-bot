"""Сбор данных для страниц панели: профиль участника, расходы, документы,
активность. Связывает реестр (ФИО+телефон) с профилем (slug по имени),
расходами и логом чата (по имени и @username из подтверждённых)."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from tools.access import by_phone, all_verified
from tools.kb_search import KB_PATH

IRK = timezone(timedelta(hours=8))  # таймзона филиала (Иркутск, UTC+8)

USAGE_PATH = Path(__file__).parent.parent / "usage.jsonl"
CHAT_LOGS = Path(__file__).parent.parent / "chat_logs"
DOCS_DIR = KB_PATH / "documents" / "processed"
MEMBERS_DIR = KB_PATH / "members"


def _slug(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch in " /\\":
            out.append("_")
    return "".join(out) or "unnamed"


def identifiers(member: dict) -> set[str]:
    """Имена/ники, под которыми участник мог фигурировать в логах/расходах."""
    ids = {member["name"]}
    v = by_phone(member["phone"])
    if v:
        if v.get("username"):
            ids.add("@" + v["username"])
        if v.get("name"):
            ids.add(v["name"])
    return {i for i in ids if i}


def profile(member: dict) -> str | None:
    """Markdown-профиль участника (тело без фронтматтера) или None."""
    f = MEMBERS_DIR / (_slug(member["name"]) + ".md")
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:]
    return text.strip()


def usage_for(idents: set[str], days: int = 90) -> dict:
    """Суммарные расходы по участнику (токены, $, голос)."""
    res = {"input": 0, "output": 0, "gpt_cost": 0.0, "voice_sec": 0, "whisper_cost": 0.0, "requests": 0}
    if not USAGE_PATH.exists():
        return res
    for line in USAGE_PATH.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("username") not in idents:
            continue
        if e.get("service") == "whisper":
            res["voice_sec"] += e.get("duration_seconds", 0)
            res["whisper_cost"] += e.get("cost_usd", 0.0)
        else:
            res["input"] += e.get("input_tokens", 0)
            res["output"] += e.get("output_tokens", 0)
            res["gpt_cost"] += e.get("cost_usd", 0.0)
            res["requests"] += 1
    res["total_cost"] = round(res["gpt_cost"] + res["whisper_cost"], 4)
    res["gpt_cost"] = round(res["gpt_cost"], 4)
    res["whisper_cost"] = round(res["whisper_cost"], 4)
    return res


def _parse_doc(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = {"name": path.stem.replace("_", " "), "uploaded": "", "by": "", "file": ""}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- Файл:"):
            meta["file"] = s.split(":", 1)[1].strip()
        elif s.startswith("- Загружен:"):
            meta["uploaded"] = s.split(":", 1)[1].strip()
        elif s.startswith("- Загрузил:"):
            meta["by"] = s.split(":", 1)[1].strip()
    return meta


def documents_all() -> list[dict]:
    if not DOCS_DIR.exists():
        return []
    docs = [_parse_doc(f) for f in sorted(DOCS_DIR.glob("*.md"))]
    return list(reversed(docs))


def documents_for(idents: set[str]) -> list[dict]:
    return [d for d in documents_all() if d["by"] in idents]


def _ago(delta: timedelta) -> str:
    """«12 минут назад» / «3 часа назад» / «2 дня назад»."""
    s = int(delta.total_seconds())
    if s < 60:
        return "только что"
    m = s // 60
    if m < 60:
        return f"{m} мин назад"
    h = m // 60
    if h < 24:
        return f"{h} ч назад"
    d = h // 24
    if d == 1:
        return "вчера"
    if d < 30:
        return f"{d} дн назад"
    return f"{d // 30} мес назад"


def _chat_label(chat_type: str) -> str:
    return "личка" if "dialog" in (chat_type or "").lower() else "группа"


_KIND_LABELS = {"text": "текст", "voice": "голос", "image": "картинка", "document": "документ"}


def _kind_label(kind) -> str:
    return _KIND_LABELS.get(kind or "text", "текст")


_SPARK = "▁▂▃▄▅▆▇█"


def _spark(values: list[int]) -> str:
    hi = max(values) if values else 0
    if hi == 0:
        return _SPARK[0] * len(values)
    return "".join(_SPARK[min(len(_SPARK) - 1, round(v / hi * (len(_SPARK) - 1)))] for v in values)


def _gpt_entries() -> list[dict]:
    """Записи обращений к боту (gpt, без whisper) с распарсенным временем (Иркутск)."""
    out = []
    if not USAGE_PATH.exists():
        return out
    for line in USAGE_PATH.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("service") == "whisper" or not e.get("ts"):
            continue
        try:
            e["_ts"] = datetime.fromisoformat(e["ts"]).astimezone(IRK)
        except Exception:
            continue
        out.append(e)
    out.sort(key=lambda e: e["_ts"])
    return out


def _matching_count() -> int:
    """Сколько в чат-логах реплик «ищу…» / «предлагаю…» (метчинг спрос/предложение)."""
    if not CHAT_LOGS.exists():
        return 0
    ask = ("ищу", "ищем", "нужен", "нужна", "ищется")
    offer = ("предлаг", "могу помочь", "могу предложить")
    n = 0
    for f in CHAT_LOGS.glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                t = (json.loads(line).get("text") or "").lower()
            except Exception:
                continue
            if any(k in t for k in ask) or any(k in t for k in offer):
                n += 1
    return n


def usage_overview(roster: list[dict], feed_limit: int = 8, spark_days: int = 14) -> dict:
    """Статистика использования бота для «Обзора»: последняя активность,
    лента обращений, активность за 30 дней (+спарклайн), охват/вовлечённость."""
    now = datetime.now(IRK)
    # username (как в usage.jsonl) → ФИО участника
    name_by_user: dict[str, str] = {}
    user_by_phone: dict[str, str] = {}
    for v in all_verified():
        u = (v.get("username") or "").lstrip("@")
        nm = v.get("name") or u
        if u:
            name_by_user[u] = nm
            name_by_user["@" + u] = nm
        if v.get("phone") and u:
            user_by_phone[v["phone"]] = u

    def disp(username: str) -> str:
        if not username:
            return "аноним"
        return name_by_user.get(username) or name_by_user.get(username.lstrip("@")) or username

    entries = _gpt_entries()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_cut = now - timedelta(days=7)
    m30_cut = now - timedelta(days=30)

    def row(e):
        return {"name": disp(e.get("username", "")), "ago": _ago(now - e["_ts"]),
                "chat": _chat_label(e.get("chat_type", "")), "kind": _kind_label(e.get("kind"))}

    last = row(entries[-1]) if entries else None
    feed = [row(e) for e in reversed(entries[-feed_limit:])]
    today = sum(1 for e in entries if e["_ts"] >= today0)
    week = sum(1 for e in entries if e["_ts"] >= week_cut)
    m30 = [e for e in entries if e["_ts"] >= m30_cut]
    active_30d = len({e.get("username") for e in m30 if e.get("username")})

    buckets = [0] * spark_days
    for e in entries:
        d = (now.date() - e["_ts"].date()).days
        if 0 <= d < spark_days:
            buckets[spark_days - 1 - d] += 1

    # охват: сколько из реестра подтвердились и сколько активны за неделю
    week_users = {e.get("username") for e in entries if e["_ts"] >= week_cut and e.get("username")}
    connected = sum(1 for m in roster if by_phone(m["phone"]))
    active_week = 0
    for m in roster:
        u = user_by_phone.get(m["phone"])
        if u and (u in week_users or "@" + u in week_users):
            active_week += 1

    return {
        "has_data": bool(entries),
        "last": last,
        "feed": feed,
        "today": today,
        "week": week,
        "active_30d": active_30d,
        "total_30d": len(m30),
        "spark": _spark(buckets),
        "connected": connected,
        "total": len(roster),
        "active_week": active_week,
        "matching": _matching_count(),
    }


def activity_for(idents: set[str], limit: int = 8) -> dict:
    """Последнее сообщение и реплики «ищу/предлагаю» участника из логов чата."""
    msgs = []
    if CHAT_LOGS.exists():
        for f in CHAT_LOGS.glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("username") in idents and e.get("text"):
                    msgs.append(e)
    msgs.sort(key=lambda e: e.get("ts", ""))
    requests = [m["text"] for m in msgs if any(k in m["text"].lower() for k in ("ищу", "ищем", "нужен", "нужна", "ищется"))]
    offers = [m["text"] for m in msgs if any(k in m["text"].lower() for k in ("предлаг", "могу помочь", "могу предложить"))]
    return {
        "count": len(msgs),
        "last": msgs[-1]["text"] if msgs else "",
        "last_ts": msgs[-1].get("ts", "") if msgs else "",
        "requests": requests[-limit:],
        "offers": offers[-limit:],
    }
