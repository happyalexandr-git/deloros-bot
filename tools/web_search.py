import os
from tavily import TavilyClient


def web_search(query: str, max_results: int = 5) -> str:
    """Поиск информации в интернете через Tavily."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "TAVILY_API_KEY не задан — веб-поиск недоступен."

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            include_answer=True,
            search_depth="advanced",
        )

        parts = []

        if response.get("answer"):
            parts.append(f"**Краткий ответ:** {response['answer']}\n")

        for i, result in enumerate(response.get("results", []), 1):
            title = result.get("title", "Без названия")
            url = result.get("url", "")
            content = result.get("content", "")[:300]
            parts.append(f"**{i}. {title}**\n{content}\n{url}")

        if not parts:
            return f"По запросу «{query}» ничего не найдено."

        return "\n\n---\n\n".join(parts)

    except Exception as e:
        return f"Ошибка веб-поиска: {e}"
