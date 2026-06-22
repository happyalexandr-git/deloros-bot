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


def _extract_docx(file_path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
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
