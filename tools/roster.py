"""Реестр членов клуба (allowlist) — сверка телефона при входе в бота.

Хранится в knowledge_base/roster.md как markdown-таблица:
    | ФИО | Телефон | Дата рождения | Компания | Должность | Отрасль | Добавлен |
Телефоны сверяются в нормализованном виде (+7XXXXXXXXXX). Файл содержит
PII → вне git; самовосстанавливается из шаблона. Управляется через
админ-панель. Парсер понимает и старый 3-колоночный формат (доп. поля
пустые) — колонок ≥7 значит новый формат.
"""
import re
from datetime import date
from pathlib import Path

KB_PATH = Path(__file__).parent.parent / "knowledge_base"
ROSTER_PATH = KB_PATH / "roster.md"

# Доп. поля профиля в реестре (кроме name/phone/added)
EXTRA_FIELDS = ("birth", "company", "position", "industry")

ROSTER_TEMPLATE = """# Реестр членов клуба «Деловая Россия»

Список допущенных к боту. Телефон сверяется при входе (кнопка «Поделиться номером»).
Формат телефона любой — сверка идёт по цифрам.

| ФИО | Телефон | Дата рождения | Компания | Должность | Отрасль | Добавлен |
|-----|---------|---------------|----------|-----------|---------|----------|
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
    """Парсит markdown-таблицу реестра в список записей.

    Ключи: name, phone, phone_raw, added + доп. поля (birth, company,
    position, industry). Понимает старый 3-колоночный формат — там доп.
    поля пустые, added берётся из 3-й колонки.
    """
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
        # пропускаем заголовок и разделитель таблицы
        if name.lower() in ("фио", "name") or set(name) <= set("-: "):
            continue
        if not phone or set(phone) <= set("-: "):
            continue
        if len(cells) >= 7:
            # новый формат: ФИО|Телефон|ДР|Компания|Должность|Отрасль|Добавлен
            birth, company, position, industry, added = cells[2], cells[3], cells[4], cells[5], cells[6]
        else:
            # старый формат: ФИО|Телефон|Добавлен
            added = cells[2] if len(cells) >= 3 else ""
            birth = company = position = industry = ""
        rows.append({
            "name": name, "phone": normalize_phone(phone), "phone_raw": phone,
            "birth": birth, "company": company, "position": position,
            "industry": industry, "added": added,
        })
    return rows


def _write_all(entries: list[dict]) -> None:
    """Перезаписывает roster.md из списка записей (header + строки таблицы)."""
    lines = [ROSTER_TEMPLATE.rstrip()]
    for e in entries:
        lines.append(
            f"| {e['name']} | {e['phone']} | {e.get('birth', '')} | "
            f"{e.get('company', '')} | {e.get('position', '')} | "
            f"{e.get('industry', '')} | {e.get('added', '')} |"
        )
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


def rename_member(phone: str, new_name: str) -> bool:
    """Меняет ФИО члена клуба по телефону. False если такого телефона нет."""
    norm = normalize_phone(phone)
    entries = load_roster()
    for e in entries:
        if e["phone"] == norm:
            e["name"] = new_name
            _write_all(entries)
            return True
    return False


def find_member_by_phone(phone: str) -> dict | None:
    """Ищет члена клуба по телефону (нормализованное сравнение)."""
    norm = normalize_phone(phone)
    if not norm:
        return None
    for m in load_roster():
        if m["phone"] == norm:
            return m
    return None


def add_member(name: str, phone: str, birth: str = "", company: str = "",
               position: str = "", industry: str = "") -> bool:
    """Добавляет запись в реестр. False если такой телефон уже есть."""
    _ensure_roster()
    if find_member_by_phone(phone):
        return False
    entries = load_roster()
    entries.append({
        "name": name, "phone": normalize_phone(phone),
        "birth": birth, "company": company, "position": position,
        "industry": industry, "added": date.today().isoformat(),
    })
    _write_all(entries)
    return True


def upsert_member(name: str, phone: str, birth: str = "", company: str = "",
                  position: str = "", industry: str = "") -> str:
    """Добавляет или обновляет запись по телефону (merge, непустые поля
    перезаписывают старые; added и статусы вне реестра сохраняются).
    Возвращает 'added' | 'updated' | 'skip' (если телефон не распознан)."""
    norm = normalize_phone(phone)
    if not norm:
        return "skip"
    entries = load_roster()
    for e in entries:
        if e["phone"] == norm:
            if name:
                e["name"] = name
            for f, v in (("birth", birth), ("company", company),
                         ("position", position), ("industry", industry)):
                if v:
                    e[f] = v
            _write_all(entries)
            return "updated"
    entries.append({
        "name": name, "phone": norm,
        "birth": birth, "company": company, "position": position,
        "industry": industry, "added": date.today().isoformat(),
    })
    _write_all(entries)
    return "added"
