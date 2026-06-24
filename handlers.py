import json
import logging
import os
from pathlib import Path

import httpx
from maxapi import Bot, Dispatcher
from maxapi.enums.attachment import AttachmentType
from maxapi.enums.chat_type import ChatType
from maxapi.enums.message_link_type import MessageLinkType
from maxapi.enums.parse_mode import ParseMode
from maxapi.enums.sender_action import SenderAction
from maxapi.types import Command, MessageCreated
from maxapi.types.updates.bot_started import BotStarted

from agent import run_agent
from tools.usage_log import get_stats, log_voice_usage
from tools.chat_log import save_message, get_chat_log
from tools.kb_save import save_to_kb
from tools.doc_processor import process_document

UPLOADS_PATH = Path(__file__).parent / "uploads"
UPLOADS_PATH.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".json"}

# Сколько символов извлечённого текста документа отдаём агенту (резюме короткие,
# презентации/контракты режем, чтобы не раздувать токены)
MAX_DOC_CHARS = 8000

# Личность бота, заполняется в register_handlers из bot.get_me()
_BOT_ID: int = 0
_BOT_USERNAME: str = ""


# ---------- хелперы ----------

def _get_username(msg) -> str:
    """Имя отправителя для логов и контекста агента."""
    user = msg.sender
    if not user:
        return "Участник"
    if user.username:
        return f"@{user.username}"
    return user.full_name or "Участник"


def _peer_id(msg) -> int:
    """Стабильный int-идентификатор диалога для истории/логов.

    В групповом чате это chat_id, в личке chat_id может отсутствовать —
    тогда используем user_id отправителя.
    """
    r = msg.recipient
    return r.chat_id or r.user_id or (msg.sender.user_id if msg.sender else 0)


def _text_of(msg) -> str:
    return (msg.body.text if msg.body else None) or ""


def _is_group(msg) -> bool:
    return msg.recipient.chat_type in (ChatType.CHAT, ChatType.CHANNEL)


def _is_mentioned(msg) -> bool:
    """Бот упомянут: @username в тексте, USER_MENTION в разметке или reply на бота."""
    text = _text_of(msg)
    if _BOT_USERNAME and f"@{_BOT_USERNAME}" in text:
        return True

    body = msg.body
    if body and body.markup:
        for el in body.markup:
            if getattr(el, "user_id", None) == _BOT_ID:
                return True

    link = msg.link
    if (
        link
        and link.type == MessageLinkType.REPLY
        and link.sender
        and link.sender.user_id == _BOT_ID
    ):
        return True
    return False


def _clean_mention(text: str) -> str:
    if _BOT_USERNAME:
        text = text.replace(f"@{_BOT_USERNAME}", "")
    return text.strip()


async def _typing(bot: Bot, chat_id: int) -> None:
    try:
        await bot.send_action(chat_id=chat_id, action=SenderAction.TYPING_ON)
    except Exception:
        pass  # в личке chat_id может отсутствовать — индикатор не критичен


async def _download(url: str, dest: Path) -> None:
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)


def _attachments(msg) -> list:
    body = msg.body
    return (body.attachments if body else None) or []


def _payload_url(att) -> str | None:
    payload = getattr(att, "payload", None)
    return getattr(payload, "url", None) if payload else None


def _import_telegram_export(file_path: Path, chat_id: int) -> int:
    """Импортирует Telegram JSON экспорт в лог чата без дубликатов.

    Транспортно-независимо — для разовой миграции истории старого чата.
    """
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return 0

    from tools.chat_log import CHAT_LOGS_PATH
    log_path = CHAT_LOGS_PATH / f"{chat_id}.jsonl"

    existing = set()
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                existing.add((e["ts"], e["username"], e["text"]))
            except Exception:
                continue

    messages = data.get("messages", [])
    count = 0
    with log_path.open("a", encoding="utf-8") as f:
        for m in messages:
            if m.get("type") != "message":
                continue
            text = m.get("text", "")
            if isinstance(text, list):
                text = "".join(p if isinstance(p, str) else p.get("text", "") for p in text)
            if not text:
                continue
            sender = m.get("from") or m.get("actor") or "Участник"
            ts = m.get("date", "")
            if ts and "+" not in ts:
                ts += "+00:00"
            if (ts, sender, text) in existing:
                continue
            entry = {"ts": ts, "username": sender, "text": text}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            existing.add((ts, sender, text))
            count += 1
    return count


# ---------- регистрация обработчиков ----------

def register_handlers(dp: Dispatcher, bot: Bot, bot_id: int, bot_username: str) -> None:
    global _BOT_ID, _BOT_USERNAME
    _BOT_ID = bot_id
    _BOT_USERNAME = bot_username

    @dp.bot_started()
    async def on_bot_started(event: BotStarted):
        """Пользователь нажал «Начать» — повод запустить онбординг."""
        await bot.send_message(
            chat_id=event.chat_id,
            text=(
                "Привет! Я **Делорос** — ассистент сообщества «Деловая Россия».\n\n"
                "Давай познакомимся: расскажи в двух словах, чем ты занимаешься? "
                "Я задам ещё пару вопросов и соберу твой профиль, чтобы находить "
                "тебе полезные связи в сообществе."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    @dp.message_created(Command("start"))
    async def cmd_start(event: MessageCreated):
        await event.message.answer(
            "Привет! Я **Делорос** — ассистент сообщества «Деловая Россия».\n\n"
            "**Чем могу помочь:**\n"
            "• Найду, кто разбирается в нужной теме — просто спроси «кто поможет с …»\n"
            "• Заведу твой профиль участника — напиши «добавь меня», проведу интервью\n"
            "• Сведу спрос и предложение («ищу …» / «могу предложить …»)\n"
            "• Саммари обсуждений, поиск в интернете, новости, напоминания, разбор файлов\n\n"
            "В группе — упомяни меня `@" + (_BOT_USERNAME or "deloros") + "` или ответь на моё сообщение.",
            parse_mode=ParseMode.MARKDOWN,
        )

    @dp.message_created(Command("summary"))
    async def cmd_summary(event: MessageCreated):
        msg = event.message
        chat_id = _peer_id(msg)
        username = _get_username(msg)
        log = get_chat_log(chat_id, limit=100)
        await _typing(bot, chat_id)
        response = await run_agent(
            chat_id=chat_id,
            username=username,
            user_message=f"Сделай саммари последних сообщений чата:\n\n{log}",
            chat_type=str(msg.recipient.chat_type),
        )
        await event.message.answer(response, parse_mode=ParseMode.MARKDOWN)

    @dp.message_created(Command("stats"))
    async def cmd_stats(event: MessageCreated):
        stats = get_stats(days=30)
        await event.message.answer(stats, parse_mode=ParseMode.HTML)

    @dp.message_created()
    async def on_message(event: MessageCreated):
        msg = event.message
        if msg.sender and msg.sender.is_bot:
            return

        chat_id = _peer_id(msg)
        username = _get_username(msg)
        atts = _attachments(msg)

        # 1) Голос/аудио — MAX присылает транскрипцию в самом вложении
        audio = next((a for a in atts if getattr(a, "type", None) == AttachmentType.AUDIO), None)
        if audio is not None:
            await _handle_audio(event, bot, audio, chat_id, username)
            return

        # 2) Документ — авто-обработка без @упоминания
        doc = next((a for a in atts if getattr(a, "type", None) == AttachmentType.FILE), None)
        if doc is not None:
            await _handle_document(event, bot, doc, chat_id, username)
            return

        # 3) Текст
        text = _text_of(msg)
        if not text:
            return

        # Пассивно сохраняем все сообщения группы в лог
        if _is_group(msg):
            save_message(chat_id, username, text)

        # В группе отвечаем только на @упоминание / reply
        if _is_group(msg) and not _is_mentioned(msg):
            return

        clean_text = _clean_mention(text) if _is_group(msg) else text
        if not clean_text:
            await event.message.answer("Слушаю — чем могу помочь?")
            return

        await _typing(bot, chat_id)
        try:
            response = await run_agent(
                chat_id=chat_id,
                username=username,
                user_message=clean_text,
                chat_type=str(msg.recipient.chat_type),
            )
            await event.message.answer(response, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Ошибка агента: {e}")
            await event.message.answer("Произошла ошибка. Попробуй ещё раз.")


# ---------- обработка вложений ----------

async def _handle_audio(event: MessageCreated, bot: Bot, audio, chat_id: int, username: str):
    text = (getattr(audio, "transcription", None) or "").strip()
    if not text:
        await event.message.answer(
            "Голосовое получил, но в нём нет распознанного текста. "
            "Можешь продублировать сообщением?"
        )
        return

    log_voice_usage(
        chat_id=chat_id,
        chat_type=str(event.message.recipient.chat_type),
        username=username,
        duration_seconds=0,
    )
    await event.message.answer(f"🎙 Распознано: _{text}_", parse_mode=ParseMode.MARKDOWN)

    await _typing(bot, chat_id)
    try:
        response = await run_agent(
            chat_id=chat_id,
            username=username,
            user_message=text,
            chat_type=str(event.message.recipient.chat_type),
        )
        await event.message.answer(response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Ошибка агента (голос): {e}")
        await event.message.answer("Произошла ошибка. Попробуй ещё раз.")


async def _handle_document(event: MessageCreated, bot: Bot, doc, chat_id: int, username: str):
    original_name = getattr(doc, "filename", None) or "document"
    suffix = Path(original_name).suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        await event.message.answer(
            f"Формат `{suffix}` не поддерживается.\nПоддерживаю: PDF, DOCX, TXT, MD, JSON",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = _payload_url(doc)
    if not url:
        await event.message.answer("Не удалось получить файл (нет ссылки на скачивание).")
        return

    await event.message.answer(
        f"Получил файл `{original_name}` — обрабатываю...", parse_mode=ParseMode.MARKDOWN
    )
    await _typing(bot, chat_id)

    local_path = UPLOADS_PATH / original_name
    try:
        await _download(url, local_path)

        # Telegram JSON экспорт — импортируем в лог чата
        if suffix == ".json":
            count = _import_telegram_export(local_path, chat_id)
            local_path.unlink(missing_ok=True)
            await event.message.answer(
                f"Импортировано сообщений из истории Telegram: **{count}**",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        result = process_document(local_path, original_name, username)
        # Сырой текст сохраняем в KB как документ — для полнотекстового поиска
        save_to_kb(
            category="document",
            name=original_name,
            content=result["content"],
            tags=result["tags"],
        )
        local_path.unlink(missing_ok=True)

        if result["text_length"] == 0:
            await event.message.answer(
                f"Файл `{original_name}` получил, но не смог извлечь из него текст.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Передаём содержимое агенту: резюме/био → профиль участника,
        # иной документ → краткое резюме. Длинный текст обрезаем.
        doc_text = result["content"]
        if len(doc_text) > MAX_DOC_CHARS:
            doc_text = doc_text[:MAX_DOC_CHARS] + "\n\n[...текст обрезан...]"

        agent_msg = (
            f"Участник {username} прислал файл «{original_name}». Извлечённый текст:\n\n"
            f"{doc_text}\n\n"
            "Если это резюме, биография или рассказ участника о себе — извлеки профиль "
            "(чем занимается, компетенции, чем полезен, что ищет, контакт), сохрани через "
            "save_to_kb(category='member') и переспроси только то, чего не хватает. "
            "Если это другой документ — кратко резюмируй суть."
        )
        await _typing(bot, chat_id)
        response = await run_agent(
            chat_id=chat_id,
            username=username,
            user_message=agent_msg,
            chat_type=str(event.message.recipient.chat_type),
        )
        await event.message.answer(response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Ошибка обработки файла: {e}")
        local_path.unlink(missing_ok=True)
        await event.message.answer(f"Не удалось обработать файл: {e}")
