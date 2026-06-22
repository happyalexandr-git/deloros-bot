import os
from pathlib import Path


def transcribe_voice(file_path: Path) -> str:
    """Транскрибирует голосовое сообщение через OpenAI Whisper API."""
    import httpx
    from openai import OpenAI

    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        http_client = httpx.Client(proxy=proxy_url)
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], http_client=http_client)
    else:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    with open(file_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ru",
        )
    return response.text
