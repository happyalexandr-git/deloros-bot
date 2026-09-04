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
    elif suffix == ".docx":
        return _extract_docx(file_path)
    elif suffix == ".doc":
        return _extract_doc(file_path)
    elif suffix in (".txt", ".md"):
        return file_path.read_text(encoding="utf-8", errors="ignore")
    else:
        return f"Формат {suffix} не поддерживается для извлечения текста."


# OCR: сканы распознаём через tesseract (если установлен в системе)
OCR_MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "30"))
OCR_DPI = int(os.environ.get("OCR_DPI", "200"))
OCR_LANG = os.environ.get("OCR_LANG", "rus+eng")


def ocr_available() -> bool:
    import shutil
    return bool(shutil.which("tesseract"))


def _ocr_pdf(file_path: Path) -> str:
    """Распознаёт текст со страниц-картинок (скан) через tesseract.

    Страницы рендерим из PDF в PNG (pymupdf) и прогоняем через tesseract.
    Возвращает пустую строку, если tesseract не установлен или ничего не вышло.
    """
    if not ocr_available():
        return ""
    import subprocess
    import tempfile
    try:
        import pymupdf
        doc = pymupdf.open(str(file_path))
        pages_text = []
        with tempfile.TemporaryDirectory() as td:
            for i, page in enumerate(doc):
                if i >= OCR_MAX_PAGES:
                    pages_text.append(f"[...распознаны первые {OCR_MAX_PAGES} страниц...]")
                    break
                img_path = Path(td) / f"p{i}.png"
                page.get_pixmap(dpi=OCR_DPI).save(str(img_path))
                out = subprocess.run(
                    ["tesseract", str(img_path), "stdout", "-l", OCR_LANG],
                    capture_output=True, timeout=120,
                )
                if out.returncode == 0:
                    pages_text.append(out.stdout.decode("utf-8", "ignore").strip())
        doc.close()
        return "\n\n".join(t for t in pages_text if t).strip()
    except Exception:
        return ""


def _extract_pdf(file_path: Path) -> str:
    try:
        import pymupdf
        doc = pymupdf.open(str(file_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        text = "\n\n".join(pages).strip()
    except Exception as e:
        return f"Ошибка при чтении PDF: {e}"

    # Текстового слоя нет — вероятно скан: пробуем распознать картинки
    if not text:
        return _ocr_pdf(file_path)
    return text


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


def _parse_docx(file_path: Path) -> str:
    """Парсит .docx (OOXML) через python-docx. Бросает исключение при сбое."""
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


def _extract_docx(file_path: Path) -> str:
    try:
        return _parse_docx(file_path)
    except Exception as e:
        return f"Ошибка при чтении DOCX: {e}"


def _extract_doc_legacy(file_path: Path) -> str | None:
    """Старый бинарный .doc — через внешние конвертеры, если они установлены."""
    import shutil
    import subprocess
    import tempfile

    if shutil.which("antiword"):
        try:
            out = subprocess.run(["antiword", str(file_path)], capture_output=True, timeout=60)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.decode("utf-8", "ignore").strip()
        except Exception:
            pass
    if shutil.which("catdoc"):
        try:
            out = subprocess.run(["catdoc", "-d", "utf-8", str(file_path)], capture_output=True, timeout=60)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.decode("utf-8", "ignore").strip()
        except Exception:
            pass
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            with tempfile.TemporaryDirectory() as td:
                subprocess.run([soffice, "--headless", "--convert-to", "txt:Text",
                                "--outdir", td, str(file_path)], capture_output=True, timeout=120)
                txts = list(Path(td).glob("*.txt"))
                if txts:
                    t = txts[0].read_text(encoding="utf-8", errors="ignore").strip()
                    if t:
                        return t
        except Exception:
            pass
    return None


def _extract_doc(file_path: Path) -> str:
    """Word .doc: иногда это переименованный .docx — пробуем как docx, затем
    внешние конвертеры для настоящего бинарного .doc, иначе — понятное сообщение."""
    try:
        t = _parse_docx(file_path)
        if t.strip():
            return t
    except Exception:
        pass
    t = _extract_doc_legacy(file_path)
    if t:
        return t
    return ("Файл в старом формате Word (.doc) — автоматически прочитать не удалось. "
            "Попросите прислать документ в формате .docx или PDF.")


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
