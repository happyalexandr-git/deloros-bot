"""Реестр членов клуба (allowlist) — сверка телефона при входе в бота.

Хранится в knowledge_base/roster.md как markdown-таблица:
    | ФИО | Телефон | Добавлен |
Телефоны сверяются в нормализованном виде (+7XXXXXXXXXX). Файл содержит
PII → вне git; самовосстанавливается из шаблона. Управляется через
админ-панель (Фаза 2), пока заполняется вручную.
"""
import re
from datetime import date
from pathlib import Path

KB_PATH = Path(__file__).parent.parent / "knowledge_base"
ROSTER_PATH = KB_PATH / "roster.md"

ROSTER_TEMPLATE = """# Реестр членов клуба «Деловая Россия»

Список допущенных к боту. Телефон сверяется при входе (кнопка «Поделиться номером»).
Формат телефона любой — сверка идёт по цифрам.

| ФИО | Телефон | Добавлен |
|-----|---------|----------|
"""


def normalize_phone(raw: str) -> str:
    """Приводит телефон к виду +7XXXXXXXXXX (РФ). Пустая строка, если не распознан."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in ("8", "7"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return "+" + digits if digits else ""


def _ensure_roster() -> None:
    if not ROSTER_PATH.exists():
        KB_PATH.mkdir(parents=True, exist_ok=True)
        ROSTER_PATH.write_text(ROSTER_TEMPLATE, encoding="utf-8")


def load_roster() -> list[dict]:
    """Парсит markdown-таблицу реестра в список {name, phone, phone_raw}."""
    _ensure_roster()
    rows = []
    for line in ROSTER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name, phone = cells[0], cells[1]
        added = cells[2] if len(cells) >= 3 else ""
        # пропускаем заголовок и разделитель таблицы
        if name.lower() in ("фио", "name") or set(name) <= set("-: "):
            continue
        if not phone or set(phone) <= set("-: "):
            continue
        rows.append({"name": name, "phone": normalize_phone(phone), "phone_raw": phone, "added": added})
    return rows


def _write_all(entries: list[dict]) -> None:
    """Перезаписывает roster.md из списка записей (header + строки таблицы)."""
    lines = [ROSTER_TEMPLATE.rstrip()]
    for e in entries:
        lines.append(f"| {e['name']} | {e['phone']} | {e.get('added', '')} |")
    ROSTER_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def delete_member(phone: str) -> bool:
    """Удаляет члена клуба по телефону. False если такого не было."""
    norm = normalize_phone(phone)
    entries = load_roster()
    kept = [e for e in entries if e["phone"] != norm]
    if len(kept) == len(entries):
        return False
    _write_all(kept)
    return True


def find_member_by_phone(phone: str) -> dict | None:
    """Ищет члена клуба по телефону (нормализованное сравнение)."""
    norm = normalize_phone(phone)
    if not norm:
        return None
    for m in load_roster():
        if m["phone"] == norm:
            return m
    return None


def add_member(name: str, phone: str) -> bool:
    """Добавляет запись в реестр. False если такой телефон уже есть."""
    _ensure_roster()
    if find_member_by_phone(phone):
        return False
    row = f"| {name} | {normalize_phone(phone)} | {date.today().isoformat()} |\n"
    with ROSTER_PATH.open("a", encoding="utf-8") as f:
        f.write(row)
    return True
