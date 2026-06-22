import asyncio
import logging
import os

from dotenv import load_dotenv
from maxapi import Bot, Dispatcher

from handlers import register_handlers
from scheduler import run_reminder_loop

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    token = os.environ.get("MAX_TOKEN")
    if not token:
        raise RuntimeError("MAX_TOKEN не задан в .env (токен бота от @MasterBot в MAX)")

    bot = Bot(token)
    dp = Dispatcher()

    me = await bot.get_me()
    logger.info(f"Запускаю бота @{me.username} (id={me.user_id}, long-polling)")

    register_handlers(dp, bot, bot_id=me.user_id, bot_username=me.username or "")

    asyncio.create_task(run_reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
