import os
import xml.etree.ElementTree as ET
import requests

RSS_FEEDS = {
    "rbc": "https://rss.rbc.ru/politics/index.rss",
    "rbc_economics": "https://rss.rbc.ru/economics/index.rss",
    "rbc_technology": "https://rss.rbc.ru/technology_and_media/index.rss",
    "tass": "https://tass.ru/rss/v2.xml",
    "interfax": "https://www.interfax.ru/rss.asp",
    "kommersant": "https://www.kommersant.ru/RSS/main.xml",
}


def get_news(source: str = "rbc", max_items: int = 5) -> str:
    """
    Получает последние новости из RSS-ленты.
    source: rbc, rbc_economics, rbc_technology, tass, interfax, kommersant
    """
    url = RSS_FEEDS.get(source)
    if not url:
        available = ", ".join(RSS_FEEDS.keys())
        return f"Неизвестный источник: {source}. Доступны: {available}"

    try:
        proxy_url = os.environ.get("PROXY_URL")
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

        response = requests.get(url, timeout=10, proxies=proxies, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ValentinBot/1.0)"
        })
        response.raise_for_status()

        root = ET.fromstring(response.content)
        channel = root.find("channel")
        if channel is None:
            return "Не удалось разобрать RSS-ленту."

        items = channel.findall("item")[:max_items]
        if not items:
            return "Новостей не найдено."

        results = []
        for item in items:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            description = item.findtext("description", "").strip()

            # Обрезаем описание
            if len(description) > 200:
                description = description[:200] + "..."

            results.append(f"**{title}**\n{description}\n{pub_date}\n{link}")

        source_name = source.upper().replace("_", " ")
        return f"Последние новости {source_name}:\n\n" + "\n\n---\n\n".join(results)

    except requests.Timeout:
        return f"Источник {source} не отвечает (таймаут)."
    except Exception as e:
        return f"Ошибка получения новостей: {e}"
