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


def _openai_search(query: str) -> tuple[str, dict]:
    """Возвращает (текст с источниками, {model, input_tokens, output_tokens, calls})."""
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

    usage = {
        "model": SEARCH_MODEL,
        "input_tokens": getattr(resp.usage, "input_tokens", 0) if resp.usage else 0,
        "output_tokens": getattr(resp.usage, "output_tokens", 0) if resp.usage else 0,
        # сколько раз модель реально ходила в поиск (за это берётся плата)
        "calls": sum(1 for it in (resp.output or []) if getattr(it, "type", "") == "web_search_call"),
    }
    if not answer.strip():
        return f"По запросу «{query}» ничего не найдено.", usage
    result = f"**Результат веб-поиска:**\n{answer.strip()}"
    if sources:
        result += "\n\n**Источники:**\n" + "\n".join(sources[:8])
    return result, usage


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


def web_search(query: str, max_results: int = 5, username: str = "", chat_id: int = 0,
               chat_type: str = "") -> str:
    """Поиск информации в интернете. Возвращает текст с источниками или строку «Ошибка веб-поиска: …».
    Расход записывается в usage.jsonl отдельной строкой (service=web_search)."""
    errors = []
    if os.environ.get("OPENAI_API_KEY"):
        try:
            text, usage = _openai_search(query)
            try:
                from tools.usage_log import log_web_search_usage
                log_web_search_usage(chat_id=chat_id, chat_type=chat_type, username=username, **usage)
            except Exception:
                pass
            return text
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
