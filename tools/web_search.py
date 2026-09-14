"""Веб-поиск.

Основной путь — встроенный веб-поиск OpenAI (Responses API, инструмент
`web_search`): доступ к OpenAI у бота уже есть, отдельный ключ и оплата не нужны.
Поиск привязан к Иркутску, чтобы лучше находились региональные источники.

Tavily оставлен запасным путём: на наш ключ он отвечает 403, но если ключ
починят — сработает, когда OpenAI недоступен.
"""
import os
import re

import httpx

SEARCH_MODEL = os.environ.get("OPENAI_SEARCH_MODEL", "gpt-4o-mini")

_USER_LOCATION = {
    "type": "approximate",
    "country": "RU",
    "region": "Irkutsk Oblast",
    "city": "Irkutsk",
    "timezone": "Asia/Irkutsk",
}

_INSTRUCTIONS = (
    "Найди в интернете ответ на запрос. Отвечай по-русски, кратко и по существу. "
    "Указывай даты событий и публикаций. Если свежих данных нет — так и скажи, "
    "не подменяй их старыми новостями или информацией о других организациях. "
    "Ссылки на источники обязательны."
)


def _clean_url(url: str) -> str:
    """Убираем служебную метку ?utm_source=openai."""
    url = re.sub(r"([?&])utm_source=openai(&|$)", lambda m: m.group(1) if m.group(2) else "", url)
    return url.rstrip("?&")


def _openai_search(query: str) -> str:
    from openai import OpenAI

    kwargs = {"api_key": os.environ["OPENAI_API_KEY"]}
    if os.environ.get("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    if os.environ.get("PROXY_URL"):
        kwargs["http_client"] = httpx.Client(proxy=os.environ["PROXY_URL"], timeout=120)
    client = OpenAI(**kwargs)

    resp = client.responses.create(
        model=SEARCH_MODEL,
        tools=[{"type": "web_search", "user_location": _USER_LOCATION}],
        instructions=_INSTRUCTIONS,
        input=query,
    )
    answer = _clean_url_links(resp.output_text or "")

    sources, seen = [], set()
    for item in resp.output or []:
        for part in getattr(item, "content", None) or []:
            for ann in getattr(part, "annotations", None) or []:
                if getattr(ann, "type", "") != "url_citation":
                    continue
                url = _clean_url(ann.url)
                if url in seen:
                    continue
                seen.add(url)
                sources.append(f"- {getattr(ann, 'title', '') or url}: {url}")

    if not answer.strip():
        return f"По запросу «{query}» ничего не найдено."
    result = f"**Результат веб-поиска:**\n{answer.strip()}"
    if sources:
        result += "\n\n**Источники:**\n" + "\n".join(sources[:8])
    return result


def _clean_url_links(text: str) -> str:
    return re.sub(r"https?://[^\s)\]]+", lambda m: _clean_url(m.group(0)), text)


def _tavily_search(query: str, max_results: int) -> str:
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    response = client.search(query=query, max_results=max_results,
                              include_answer=True, search_depth="advanced")
    parts = []
    if response.get("answer"):
        parts.append(f"**Краткий ответ:** {response['answer']}\n")
    for i, r in enumerate(response.get("results", []), 1):
        parts.append(f"**{i}. {r.get('title', 'Без названия')}**\n{r.get('content', '')[:300]}\n{r.get('url', '')}")
    if not parts:
        return f"По запросу «{query}» ничего не найдено."
    return "\n\n---\n\n".join(parts)


def web_search(query: str, max_results: int = 5) -> str:
    """Поиск информации в интернете. Возвращает текст с источниками или строку «Ошибка веб-поиска: …»."""
    errors = []
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return _openai_search(query)
        except Exception as e:
            errors.append(f"OpenAI: {str(e)[:200]}")
    if os.environ.get("TAVILY_API_KEY"):
        try:
            return _tavily_search(query, max_results)
        except Exception as e:
            errors.append(f"Tavily: {str(e)[:200]}")
    if not errors:
        return "TAVILY_API_KEY не задан — веб-поиск недоступен."
    return "Ошибка веб-поиска: " + "; ".join(errors)
