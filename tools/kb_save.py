from pathlib import Path
from datetime import date

KB_PATH = Path(__file__).parent.parent / "knowledge_base"

CATEGORY_MAP = {
    "member": "members",
    "company": "companies",
    "offer": "offers",
    "request": "requests",
    "meeting": "meetings",
    "transcription": "transcriptions",
    "document": "documents/processed",
    "research": "research",
}


def save_to_kb(
    category: str,
    name: str,
    content: str,
    tags: list[str] | None = None,
    related: list[str] | None = None,
) -> str:
    """
    Сохраняет новый или обновляет существующий MD-файл в базе знаний.
    Возвращает путь сохранённого файла.
    """
    if category not in CATEGORY_MAP:
        return f"Неизвестная категория: {category}. Доступны: {', '.join(CATEGORY_MAP)}"

    folder = KB_PATH / CATEGORY_MAP[category]
    folder.mkdir(parents=True, exist_ok=True)

    filename = _slugify(name) + ".md"
    filepath = folder / filename

    today = date.today().isoformat()
    tags_str = ", ".join(tags) if tags else ""
    related_str = ", ".join(related) if related else ""

    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8")
        updated = _append_to_existing(existing, content, today, related)
        filepath.write_text(updated, encoding="utf-8")
        action = "обновлён"
    else:
        md = f"""---
type: {category}
name: {name}
added: {today}
tags: [{tags_str}]
related: [{related_str}]
---

# {name}

{content}
"""
        filepath.write_text(md, encoding="utf-8")
        action = "создан"

    _update_index(category, name, filename)

    relative = filepath.relative_to(KB_PATH)
    return f"Файл {action}: knowledge_base/{relative}"


def _slugify(name: str) -> str:
    """Превращает имя в безопасное имя файла."""
    result = []
    for ch in name.lower():
        if ch.isalnum() or ch in "-_":
            result.append(ch)
        elif ch in " /\\":
            result.append("_")
    return "".join(result) or "unnamed"


def _append_to_existing(existing: str, new_content: str, today: str, related: list[str] | None = None) -> str:
    """Добавляет новый контент и обновляет related в существующем файле."""
    result = existing.rstrip()
    if related:
        if "related:" in result:
            lines = result.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("related:"):
                    existing_related = line.replace("related:", "").strip().strip("[]")
                    all_related = set(r.strip() for r in existing_related.split(",") if r.strip())
                    all_related.update(related)
                    new_lines.append(f"related: [{', '.join(sorted(all_related))}]")
                else:
                    new_lines.append(line)
            result = "\n".join(new_lines)
    return result + f"\n\n## Обновление {today}\n\n{new_content}\n"


def _update_index(category: str, name: str, filename: str) -> None:
    """Обновляет INDEX.md — добавляет запись если её нет."""
    index_path = KB_PATH / "INDEX.md"
    if not index_path.exists():
        return

    text = index_path.read_text(encoding="utf-8")
    folder = CATEGORY_MAP[category]
    link = f"- [{name}]({folder}/{filename})"

    if name in text:
        return

    section_headers = {
        "member": "## Участники",
        "company": "## Компании",
        "offer": "## Офферы",
        "request": "## Запросы",
        "meeting": "## Встречи",
        "transcription": "## Транскрибации",
        "document": "## Документы",
        "research": "## Исследования",
    }

    header = section_headers.get(category)
    if not header or header not in text:
        return

    lines = text.splitlines()
    new_lines = []
    i = 0
    while i < len(lines):
        new_lines.append(lines[i])
        if lines[i].startswith(header):
            i += 1
            # пропускаем строку "_пока пусто_" если есть
            if i < len(lines) and "_пока пусто_" in lines[i]:
                new_lines.append(link)
                i += 1
                continue
            new_lines.append(link)
            continue
        i += 1

    index_path.write_text("\n".join(new_lines), encoding="utf-8")
