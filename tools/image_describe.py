import base64
import os


def _mime_of(data: bytes) -> str:
    """Определяет MIME по сигнатуре файла (по умолчанию jpeg)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def describe_image(image_bytes: bytes, caption: str = "") -> str:
    """Описывает изображение через gpt-4o vision.

    Картинка скачивается вызывающим кодом и передаётся байтами (надёжнее,
    чем давать модели URL — MAX-ссылки OpenAI может не скачать). Возвращает
    описание: что на картинке + дословно извлечённый текст/цифры/таблицы.
    caption (подпись/вопрос пользователя) фокусирует ответ.
    """
    import httpx
    from openai import OpenAI

    client_kwargs = {"api_key": os.environ["OPENAI_API_KEY"]}
    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        client_kwargs["base_url"] = base_url
    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        client_kwargs["http_client"] = httpx.Client(proxy=proxy_url)
    client = OpenAI(**client_kwargs)

    instruction = (
        "Опиши, что изображено на картинке, по делу и без воды. "
        "Если есть текст, цифры, таблицы, графики — извлеки их содержимое дословно."
    )
    if caption:
        instruction += f"\nПользователь спрашивает: «{caption}» — учти это в описании."

    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:{_mime_of(image_bytes)};base64,{b64}"

    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        max_tokens=1000,
    )
    return (response.choices[0].message.content or "").strip()
