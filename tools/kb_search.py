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


def search_kb(query: str, category: str | None = None) -> str:
    """
    Поиск по MD-файлам базы знаний.
    Возвращает найденные фрагменты или сообщение что ничего не найдено.
    """
    query_lower = query.lower()
    results = []

    if category and category in CATEGORY_MAP:
        search_dirs = [KB_PATH / CATEGORY_MAP[category]]
    else:
        search_dirs = [KB_PATH / d for d in CATEGORY_MAP.values()]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for md_file in search_dir.rglob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            if query_lower in text.lower():
                snippet = _extract_snippet(text, query_lower)
                relative = md_file.relative_to(KB_PATH)
                related = _extract_related(text)
                related_str = f"\n**Связано с:** {related}" if related else ""
                results.append(f"### [{relative}]{related_str}\n{snippet}")

    if not results:
        return f"В базе знаний ничего не найдено по запросу: «{query}»"

    header = f"Найдено совпадений: {len(results)}\n\n"
    return header + "\n---\n".join(results[:5])  # максимум 5 результатов


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
