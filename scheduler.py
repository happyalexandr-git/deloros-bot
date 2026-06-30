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
                text = f"🔔 Напоминание:\n\n{reminder['text']}"
                targets = reminder.get("targets") or []
                if targets:
                    for uid in targets:
                        try:
                            await bot.send_message(user_id=uid, text=text)
                        except Exception as e:
                            logger.error(f"Не доставлено user_id={uid}: {e}")
                else:
                    await bot.send_message(chat_id=reminder["chat_id"], text=text)
                mark_sent(reminder["id"])
                logger.info(f"Отправлено напоминание {reminder['id']} ({len(targets) or 'чат'})")
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")

        await asyncio.sleep(30)
