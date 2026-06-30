"""Сбор данных для страниц панели: профиль участника, расходы, документы,
активность. Связывает реестр (ФИО+телефон) с профилем (slug по имени),
расходами и логом чата (по имени и @username из подтверждённых)."""
import json
from pathlib import Path

from tools.access import by_phone
from tools.kb_search import KB_PATH

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
