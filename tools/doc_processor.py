import os
from pathlib import Path
from datetime import date

UPLOADS_PATH = Path(__file__).parent.parent / "uploads"
UPLOADS_PATH.mkdir(exist_ok=True)


def extract_text(file_path: Path) -> str:
    """Извлекает текст из PDF, DOCX или TXT файла."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(file_path)
    elif suffix in (".docx", ".doc"):
        return _extract_docx(file_path)
    elif suffix in (".txt", ".md"):
        return file_path.read_text(encoding="utf-8", errors="ignore")
    else:
        return f"Формат {suffix} не поддерживается для извлечения текста."


def _extract_pdf(file_path: Path) -> str:
    try:
        import pymupdf
        doc = pymupdf.open(str(file_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages).strip()
    except Exception as e:
        return f"Ошибка при чтении PDF: {e}"


def _iter_blocks(parent):
    """Абзацы и таблицы в порядке следования в документе.

    docx.Document.paragraphs НЕ включает текст таблиц, а анкеты часто
    свёрстаны таблицами — без этого терялась основная часть содержимого.
    """
    from docx.document import Document as _Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table, _Cell
    from docx.text.paragraph import Paragraph

    if isinstance(parent, _Document):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        return
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def _table_lines(table) -> list[str]:
    """Строки таблицы как «ячейка | ячейка» (объединённые ячейки не дублируем)."""
    lines = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            if text and (not cells or cells[-1] != text):
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _extract_docx(file_path: Path) -> str:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = Document(str(file_path))
        parts: list[str] = []
        for block in _iter_blocks(doc):
            if isinstance(block, Paragraph):
                if block.text.strip():
                    parts.append(block.text.strip())
            elif isinstance(block, Table):
                parts.extend(_table_lines(block))
        return "\n\n".join(parts)
    except Exception as e:
        return f"Ошибка при чтении DOCX: {e}"


def process_document(file_path: Path, original_name: str, uploaded_by: str) -> dict:
    """
    Обрабатывает документ: извлекает текст и возвращает данные для сохранения в KB.
    """
    text = extract_text(file_path)
    today = date.today().isoformat()
    suffix = file_path.suffix.lower()

    # Определяем тип документа по расширению
    if suffix == ".pdf":
        doc_type = "PDF"
    elif suffix in (".docx", ".doc"):
        doc_type = "Word"
    elif suffix == ".txt":
        doc_type = "текстовый файл"
    else:
        doc_type = "документ"

    # Формируем краткое превью (первые 500 символов)
    preview = text[:500] + "..." if len(text) > 500 else text

    content = f"""## Метаданные
- Файл: {original_name}
- Тип: {doc_type}
- Загружен: {today}
- Загрузил: {uploaded_by}

## Содержимое

{text}
"""

    return {
        "name": original_name,
        "content": content,
        "preview": preview,
        "text_length": len(text),
        "tags": [doc_type.lower(), uploaded_by.lstrip("@")],
    }
