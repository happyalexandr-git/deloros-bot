import json
import os
from pathlib import Path

import anthropic
import httpx

from tools.kb_search import search_kb, list_kb
from tools.chat_log import get_chat_log, search_chat_log
from tools.usage_log import log_usage
from tools.kb_save import save_to_kb
from tools.web_search import web_search
from tools.news_rss import get_news
from tools.reminder import add_reminder, list_reminders

HISTORY_PATH = Path(__file__).parent / "chat_history"
HISTORY_PATH.mkdir(exist_ok=True)

MAX_HISTORY = 50

SYSTEM_PROMPT = """Ты — Делорос, ассистент чата сообщества «Деловая Россия».

Главная ценность: ты держишь общий контекст сообщества — кто есть кто, кто чем полезен, кто что ищет и кто что предлагает. Один человек не может удержать в голове всю сеть связей; ты можешь. Ты усиливаешь связи между участниками, а не заменяешь их.

Твои задачи:
1. Кто есть кто. Ведёшь профили участников (категория member): чем человек занимается, какие компетенции, чем может быть полезен, какие связи и интересы. По запросу «кто разбирается в X / кто может помочь с Y» — ищешь по профилям через search_kb(category="members").
2. Онбординг участника. Когда появляется новый участник или человек просит «расскажи обо мне» / «добавь меня» — НЕ проси написать о себе текстом. Проведи короткое интервью: задавай по одному вопросу за раз (чем занимаешься; компетенции и опыт; чем можешь быть полезен сообществу; что сейчас ищешь; как лучше с тобой связаться). Собрав ответы — сохрани профиль через save_to_kb(category="member"). Цель — собрать максимум полезного, чтобы человек не сочинял о себе сам.
3. Поиск компетенций и метчинг запросов. Замечаешь в чате «ищу …» и «могу предложить …». Сводишь спрос с предложением: ищешь подходящих людей в профилях (search_kb) и в истории чата (search_chat_log) и подсказываешь, кто кому может быть полезен. Важные запросы можешь сохранять через save_to_kb(category="request").
4. Общий ассистент чата. Отвечаешь на вопросы, делаешь саммари обсуждений, веб-поиск, новости, напоминания, разбор документов.

Как работает память:
- Все сообщения чата автоматически сохраняются в лог (chat_log) — ты ВСЕГДА имеешь доступ к истории. Никогда не говори, что не видел сообщений.
- Перед ответом о том, что обсуждалось/кто что говорил — ОБЯЗАТЕЛЬНО search_chat_log.
- Перед ответом о людях и компетенциях — сначала search_kb(category="members").
- Профили и важные сущности сохраняй через save_to_kb, заполняя related (связанные участники/компании/темы).

Правила поведения:
- Общаешься на русском, лаконично, структурированно, markdown.
- Уважение к приватности: сохраняй в профиль только то, что человек сам сообщил для сообщества. Не выдумывай факты о людях.
- Админ сообщества — Александр; его настройки и просьбы по модерации приоритетны.
- Если не знаешь — честно скажи и предложи web_search."""

TOOLS = [
    {
        "name": "get_chat_log",
        "description": "Получить последние сообщения чата для саммари. Используй когда просят саммари, итоги обсуждения, что обсуждали сегодня.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Количество последних сообщений (по умолчанию 100)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_chat_log",
        "description": "Поиск по всей истории сообщений чата по ключевым словам. Используй когда спрашивают, кто что говорил, кто что искал или предлагал, по теме/человеку/компетенции.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Ключевое слово или фраза для поиска",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_kb",
        "description": "Показать список всех файлов в базе знаний по категориям (участники, компании, запросы и т.д.).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_kb",
        "description": "Поиск в базе знаний. Главное применение — найти участника по компетенции/пользе ('кто разбирается в X', 'кто может помочь с Y'). Используй ПЕРЕД ответом на вопросы о людях, компетенциях, запросах.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос на русском",
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "members", "companies", "offers", "requests", "meetings", "research",
                    ],
                    "description": "Раздел KB для поиска (опционально). Для людей — members.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_news",
        "description": "Получить последние новости из RSS-лент российских и международных СМИ.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["rbc", "rbc_economics", "rbc_technology", "tass", "interfax", "kommersant"],
                    "description": "Источник новостей",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Количество новостей (по умолчанию 5)",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "web_search",
        "description": "Поиск информации в интернете. Используй для актуальных данных о компаниях, людях, событиях.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Количество результатов (по умолчанию 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_to_kb",
        "description": "Сохранить в базу знаний. Профиль участника — category='member' (заполни компетенции, чем полезен, что ищет, контакт). Запрос спроса/предложения — category='request'. Также компании, встречи, исследования.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "member", "company", "offer", "request", "meeting", "research",
                    ],
                    "description": "Тип сущности. Для человека — member.",
                },
                "name": {
                    "type": "string",
                    "description": "Имя участника / название сущности",
                },
                "content": {
                    "type": "string",
                    "description": "Содержимое в markdown. Для участника: компетенции, опыт, чем полезен, что ищет, контакт.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Теги-компетенции для быстрого поиска (напр. юрист, логистика, экспорт)",
                },
                "related": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Имена связанных сущностей из KB (участники, компании, запросы)",
                },
            },
            "required": ["category", "name", "content"],
        },
    },
    {
        "name": "list_reminders",
        "description": "Показать список активных запланированных напоминаний.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "schedule_message",
        "description": "Запланировать отправку сообщения в чат в указанное время. Используй для напоминаний.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Текст напоминания или сообщения",
                },
                "send_at": {
                    "type": "string",
                    "description": "Дата и время отправки в формате 'YYYY-MM-DD HH:MM' по Москве (UTC+3)",
                },
            },
            "required": ["text", "send_at"],
        },
    },
]


def _load_history(chat_id: int) -> list[dict]:
    path = HISTORY_PATH / f"{chat_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_history(chat_id: int, history: list[dict]) -> None:
    path = HISTORY_PATH / f"{chat_id}.json"
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def add_system_event(chat_id: int, event: str) -> None:
    """Добавляет системное событие в историю чата (без вызова Claude)."""
    history = _load_history(chat_id)
    history.append({"role": "user", "content": f"[Система]: {event}"})
    history.append({"role": "assistant", "content": "Понял, зафиксировал."})
    history = _trim_history(history)
    _save_history(chat_id, history)


def _trim_history(history: list[dict]) -> list[dict]:
    """Оставляем последние MAX_HISTORY сообщений, сохраняя парность user/assistant."""
    if len(history) <= MAX_HISTORY:
        return history
    trimmed = history[-MAX_HISTORY:]
    while trimmed and trimmed[0]["role"] != "user":
        trimmed = trimmed[1:]
    return trimmed


def _execute_tool(tool_name: str, tool_input: dict, chat_id: int = 0) -> str:
    if tool_name == "get_chat_log":
        return get_chat_log(chat_id=chat_id, limit=tool_input.get("limit", 100))
    if tool_name == "search_chat_log":
        return search_chat_log(chat_id=chat_id, query=tool_input["query"])
    if tool_name == "list_kb":
        return list_kb()
    if tool_name == "search_kb":
        return search_kb(
            query=tool_input["query"],
            category=tool_input.get("category"),
        )
    if tool_name == "get_news":
        return get_news(
            source=tool_input.get("source", "rbc"),
            max_items=tool_input.get("max_items", 5),
        )
    if tool_name == "web_search":
        return web_search(
            query=tool_input["query"],
            max_results=tool_input.get("max_results", 5),
        )
    if tool_name == "save_to_kb":
        return save_to_kb(
            category=tool_input["category"],
            name=tool_input["name"],
            content=tool_input["content"],
            tags=tool_input.get("tags"),
            related=tool_input.get("related"),
        )
    if tool_name == "list_reminders":
        return list_reminders(chat_id=chat_id)
    if tool_name == "schedule_message":
        return add_reminder(
            chat_id=chat_id,
            text=tool_input["text"],
            send_at=tool_input["send_at"],
        )
    return f"Неизвестный инструмент: {tool_name}"


async def run_agent(
    chat_id: int,
    username: str,
    user_message: str,
    chat_type: str = "unknown",
) -> str:
    """
    Запускает агентный цикл: отправляет запрос в Claude,
    выполняет tool calls, возвращает финальный ответ.
    """
    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        http_client = httpx.Client(proxy=proxy_url)
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], http_client=http_client)
    else:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    history = _load_history(chat_id)

    history.append({
        "role": "user",
        "content": f"[{username}]: {user_message}",
    })
    history = _trim_history(history)

    messages = [{"role": m["role"], "content": m["content"]} for m in history]

    total_input_tokens = 0
    total_output_tokens = 0

    # Агентный цикл
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "tool_use":
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(block.name, block.input, chat_id=chat_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
            continue

        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        history.append({"role": "assistant", "content": final_text})
        _save_history(chat_id, history)

        log_usage(
            chat_id=chat_id,
            chat_type=chat_type,
            username=username,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

        return final_text
