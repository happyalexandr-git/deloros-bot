import asyncio
import logging

from maxapi import Bot
from tools.reminder import get_due_reminders, mark_sent

logger = logging.getLogger(__name__)


async def run_reminder_loop(bot: Bot) -> None:
    """Фоновая задача: каждые 30 секунд проверяет и отправляет напоминания."""
    while True:
        try:
            due = get_due_reminders()
            for reminder in due:
                await bot.send_message(
                    chat_id=reminder["chat_id"],
                    text=f"🔔 Напоминание:\n\n{reminder['text']}",
                )
                mark_sent(reminder["id"])
                logger.info(f"Отправлено напоминание {reminder['id']}")
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")

        await asyncio.sleep(30)
