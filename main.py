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
    # Базовый URL MAX Bot API. platform-api.max.ru — сертификат Let's Encrypt
    # (стандартное доверие). platform-api2.max.ru требует российский УЦ Минцифры,
    # которого нет в certifi — поэтому по умолчанию используем основной endpoint.
    # Переопределяем до первого запроса (до get_me), пока сессия не закеширована.
    api_url = os.environ.get("MAX_API_URL", "https://platform-api.max.ru")
    bot.set_api_url(api_url)
    logger.info(f"MAX API: {api_url}")

    dp = Dispatcher()

    me = await bot.get_me()
    logger.info(f"Запускаю бота @{me.username} (id={me.user_id}, long-polling)")

    register_handlers(dp, bot, bot_id=me.user_id, bot_username=me.username or "")

    asyncio.create_task(run_reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
