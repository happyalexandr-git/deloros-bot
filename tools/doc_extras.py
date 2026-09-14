"""Извлечение из документов того, что нельзя терять при пересказе:
ссылки, email, телефоны, а также ссылки из QR-кодов.

Всё вытаскивается кодом, а не моделью — чтобы ссылка на регистрацию или
контакт не исказились и не выпали из краткого пересказа.
"""
import io
import re
from pathlib import Path

_URL_RE = re.compile(r"https?://[^\s<>\"'«»()\[\]]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# +7/8 и ровно 10 цифр с любыми разделителями: мобильные и городские (3952) 40-50-60
_PHONE_RE = re.compile(r"(?:\+7|(?<!\d)8)(?:[\s()\-]*\d){10}(?!\d)")

# Сколько страниц PDF просматриваем в поисках QR (QR обычно на первых)
QR_MAX_PAGES = 10
QR_DPI = 200


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?")


def extract_contacts(text: str) -> dict:
    """{'links': [...], 'emails': [...], 'phones': [...]} без дублей, в порядке появления."""
    def uniq(items):
        seen, out = set(), []
        for i in items:
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    text = text or ""
    return {
        "links": uniq(_clean_url(u) for u in _URL_RE.findall(text)),
        "emails": uniq(_EMAIL_RE.findall(text)),
        "phones": uniq(p.strip() for p in _PHONE_RE.findall(text)),
    }


def qr_available() -> bool:
    try:
        from pyzbar.pyzbar import decode  # noqa: F401  (нужна системная libzbar)
        from PIL import Image  # noqa: F401  (без Pillow расшифровка молча вернёт пусто)
        return True
    except Exception:
        return False


def _decode_image(img) -> list[str]:
    from pyzbar.pyzbar import decode, ZBarSymbol
    out = []
    for sym in decode(img, symbols=[ZBarSymbol.QRCODE]):
        try:
            out.append(sym.data.decode("utf-8").strip())
        except Exception:
            continue
    return out


def qr_from_image_bytes(data: bytes) -> list[str]:
    """Расшифровывает QR-коды на картинке. Пусто, если pyzbar недоступен."""
    if not qr_available():
        return []
    try:
        from PIL import Image
        return list(dict.fromkeys(_decode_image(Image.open(io.BytesIO(data)))))
    except Exception:
        return []


def qr_from_pdf(file_path: Path) -> list[str]:
    """Расшифровывает QR-коды на страницах PDF (рендер через pymupdf)."""
    if not qr_available():
        return []
    try:
        import pymupdf
        from PIL import Image
        found = []
        doc = pymupdf.open(str(file_path))
        for i, page in enumerate(doc):
            if i >= QR_MAX_PAGES:
                break
            png = page.get_pixmap(dpi=QR_DPI).tobytes("png")
            found.extend(_decode_image(Image.open(io.BytesIO(png))))
        doc.close()
        return list(dict.fromkeys(found))
    except Exception:
        return []


def qr_from_file(file_path: Path) -> list[str]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return qr_from_pdf(file_path)
    if suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        try:
            return qr_from_image_bytes(file_path.read_bytes())
        except Exception:
            return []
    return []


def links_block(contacts: dict, qr_links: list[str]) -> str:
    """Markdown-блок «Ссылки и контакты» для сохранения вместе с документом."""
    lines = []
    if contacts.get("links"):
        lines.append("**Ссылки из текста:**")
        lines += [f"- {u}" for u in contacts["links"]]
    if qr_links:
        lines.append("**Ссылки из QR-кодов:**")
        lines += [f"- {u}" for u in qr_links]
    if contacts.get("emails"):
        lines.append("**Email:** " + ", ".join(contacts["emails"]))
    if contacts.get("phones"):
        lines.append("**Телефоны:** " + ", ".join(contacts["phones"]))
    return "\n".join(lines)
