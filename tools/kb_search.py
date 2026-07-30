import os
from pathlib import Path

KB_PATH = Path(__file__).parent.parent / "knowledge_base"

CATEGORY_MAP = {
    "members": "members",
    "companies": "companies",
    "offers": "offers",
    "requests": "requests",
    "meetings": "meetings",
    "transcriptions": "transcriptions",
    "documents": "documents/processed",
    "research": "research",
}


def list_kb() -> str:
    """Возвращает список всех файлов в базе знаний по категориям."""
    lines = []
    for category, folder_name in CATEGORY_MAP.items():
        folder = KB_PATH / folder_name
        if not folder.exists():
            continue
        files = list(folder.rglob("*.md"))
        if not files:
            continue
        lines.append(f"\n**{folder_name}** ({len(files)} файлов):")
        for f in files:
            name = f.stem.replace("_", " ")
            lines.append(f"  - {name}")
    if not lines:
        return "База знаний пуста."
    return "**Содержимое базы знаний:**\n" + "\n".join(lines)


# Порог смыслового сходства: ниже — считаем нерелевантным
MIN_SCORE = 0.2


def _collect_files(category: str | None) -> list:
    if category and category in CATEGORY_MAP:
        search_dirs = [KB_PATH / CATEGORY_MAP[category]]
    else:
        search_dirs = [KB_PATH / d for d in CATEGORY_MAP.values()]
    files = []
    for d in search_dirs:
        if d.exists():
            files.extend(d.rglob("*.md"))
    return files


# Служебные слова запроса — не несут смысла для лексического поиска
_STOP_WORDS = {
    "кто", "что", "чем", "как", "где", "когда", "какие", "какой", "какая", "какое",
    "есть", "ли", "из", "для", "про", "по", "на", "в", "с", "у", "и", "или", "не",
    "нас", "наш", "наши", "нашем", "клуба", "клубе", "сообщества", "сообществе",
    "занимается", "может", "помочь", "разбирается", "тема", "теме",
}
_SUFFIXES = ("иями", "ями", "ами", "ыми", "ими", "ому", "его", "ого", "ей", "ий",
             "ые", "ая", "ое", "ых", "их", "ем", "ом", "ах", "ях", "ию", "ии",
             "ие", "ья", "ов", "ы", "и", "а", "е", "о", "я", "ь", "у", "ю")


def _stem(word: str) -> str:
    """Грубая основа слова: отсекаем типичное русское окончание.

    Полноценная морфология не нужна — достаточно, чтобы «образовательные»
    и «образовательных» сошлись на общей основе «образовательн».
    """
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 4:
            return word[: -len(suf)]
    return word


def _lexical_scores(query: str, files: list) -> dict:
    """{путь: доля совпавших основ слов запроса}. Ловит буквальные вхождения,
    которые эмбеддинги могут недооценить на коротком запросе."""
    import re
    words = [w for w in re.findall(r"[а-яёa-z0-9]+", query.lower())
             if len(w) >= 3 and w not in _STOP_WORDS]
    stems = [_stem(w) for w in words]
    if not stems:
        return {}
    scores = {}
    for md_file in files:
        try:
            text = md_file.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        hits = sum(1 for s in stems if s in text)
        if hits:
            scores[md_file] = hits / len(stems)
    return scores


def search_kb(query: str, category: str | None = None) -> str:
    """
    Гибридный поиск по базе знаний: смысловой (эмбеддинги OpenAI) + лексический
    по основам слов. Лексическая часть страхует короткие запросы («образовательные
    программы»), где косинусное сходство с длинным профилем падает ниже порога.
    """
    files = _collect_files(category)
    if not files:
        return f"В базе знаний пока нет записей{f' в разделе {category}' if category else ''}."

    lexical = _lexical_scores(query, files)
    try:
        from tools.embeddings import semantic_search
        ranked = semantic_search(query, files, top_k=5)
    except Exception:
        return _substring_search(query, files)  # фолбэк при недоступности OpenAI

    # Кандидаты: прошедшие порог по смыслу + те, где нашлись слова запроса
    picked: dict = {}
    for md_file, score in ranked:
        if score >= MIN_SCORE:
            picked[md_file] = {"sem": score, "lex": lexical.get(md_file, 0.0)}
    for md_file, lex in lexical.items():
        # совпала минимум половина значимых слов — считаем релевантным
        if lex >= 0.5 and md_file not in picked:
            sem = next((s for f, s in ranked if f == md_file), 0.0)
            picked[md_file] = {"sem": sem, "lex": lex}

    # Сортировка: сперва по лексическому совпадению, затем по смыслу
    order = sorted(picked.items(), key=lambda kv: (kv[1]["lex"], kv[1]["sem"]), reverse=True)[:5]

    results = []
    for md_file, sc in order:
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        relative = md_file.relative_to(KB_PATH)
        related = _extract_related(text)
        related_str = f"\n**Связано с:** {related}" if related else ""
        mark = f"сходство {sc['sem']:.2f}"
        if sc["lex"]:
            mark += f", совпало слов {int(sc['lex'] * 100)}%"
        results.append(f"### [{relative}] ({mark}){related_str}\n{_body_snippet(text)}")

    if not results:
        return f"В базе знаний ничего подходящего по смыслу не найдено по запросу: «{query}»"

    return f"Найдено: {len(results)}\n\n" + "\n---\n".join(results)


def _substring_search(query: str, files: list) -> str:
    """Резервный подстрочный поиск (если эмбеддинги недоступны)."""
    q = query.lower()
    results = []
    for md_file in files:
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        if q in text.lower():
            relative = md_file.relative_to(KB_PATH)
            results.append(f"### [{relative}]\n{_extract_snippet(text, q)}")
    if not results:
        return f"В базе знаний ничего не найдено по запросу: «{query}»"
    return f"Найдено совпадений: {len(results)}\n\n" + "\n---\n".join(results[:5])


def _body_snippet(text: str, limit: int = 400) -> str:
    """Возвращает начало содержимого профиля без YAML-фронтматтера."""
    body = text
    if body.startswith("---"):
        end = body.find("---", 3)
        if end != -1:
            body = body[end + 3:]
    body = body.strip()
    return body[:limit] + ("..." if len(body) > limit else "")


def _extract_related(text: str) -> str:
    """Извлекает поле related из фронтматтера."""
    for line in text.splitlines():
        if line.startswith("related:"):
            related = line.replace("related:", "").strip().strip("[]")
            return related if related else ""
    return ""


def _extract_snippet(text: str, query: str, context: int = 300) -> str:
    """Возвращает фрагмент текста вокруг найденного совпадения."""
    idx = text.lower().find(query)
    if idx == -1:
        return text[:context]
    start = max(0, idx - context // 2)
    end = min(len(text), idx + context // 2)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet
