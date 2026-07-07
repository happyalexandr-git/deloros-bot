import os


def describe_image(url: str, caption: str = "") -> str:
    """Описывает изображение через gpt-4o vision по URL.

    Возвращает текстовое описание: что на картинке + дословно извлечённый
    текст/цифры/таблицы. caption (подпись/вопрос пользователя) — подсказка,
    на чём сфокусироваться. Модель сама скачивает изображение по URL.
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

    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }],
        max_tokens=1000,
    )
    return (response.choices[0].message.content or "").strip()
