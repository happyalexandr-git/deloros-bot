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


def search_kb(query: str, category: str | None = None) -> str:
    """
    Семантический поиск по базе знаний (эмбеддинги OpenAI) — находит по смыслу,
    а не по точному слову. При сбое эмбеддингов откатывается на подстрочный поиск.
    """
    files = _collect_files(category)
    if not files:
        return f"В базе знаний пока нет записей{f' в разделе {category}' if category else ''}."

    try:
        from tools.embeddings import semantic_search
        ranked = semantic_search(query, files, top_k=5)
    except Exception:
        return _substring_search(query, files)  # фолбэк при недоступности OpenAI

    results = []
    for md_file, score in ranked:
        if score < MIN_SCORE:
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        relative = md_file.relative_to(KB_PATH)
        related = _extract_related(text)
        related_str = f"\n**Связано с:** {related}" if related else ""
        results.append(f"### [{relative}] (сходство {score:.2f}){related_str}\n{_body_snippet(text)}")

    if not results:
        return f"В базе знаний ничего подходящего по смыслу не найдено по запросу: «{query}»"

    return f"Найдено по смыслу: {len(results)}\n\n" + "\n---\n".join(results)


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
