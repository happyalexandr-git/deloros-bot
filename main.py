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

    register_handlers(dp, bot, bot_id=me.user_id, bot_username=me.username or "")

    asyncio.create_task(run_reminder_loop(bot))

    # Транспорт: webhook (MAX сам шлёт события HTTP-пушами) или long-polling.
    # Через long-poll MAX не присылает голосовые вложения (подтверждено на
    # HTTP-уровне), поэтому на проде используем webhook за NPM (делорос.рф).
    transport = os.environ.get("MAX_TRANSPORT", "polling").lower()
    if transport == "webhook":
        public_url = os.environ.get("MAX_WEBHOOK_URL")
        secret = os.environ.get("MAX_WEBHOOK_SECRET")
        port = int(os.environ.get("MAX_WEBHOOK_PORT", "8088"))
        if not public_url or not secret:
            raise RuntimeError(
                "Для MAX_TRANSPORT=webhook задайте MAX_WEBHOOK_URL "
                "(публичный https-адрес) и MAX_WEBHOOK_SECRET (5-256 символов) в .env"
            )
        from urllib.parse import urlparse

        from maxapi.webhook.aiohttp import AiohttpMaxWebhook

        path = urlparse(public_url).path or "/"
        logger.info(f"Запускаю бота @{me.username} (id={me.user_id}, webhook {public_url})")
        webhook = AiohttpMaxWebhook(dp=dp, bot=bot, secret=secret)

        async def _subscribe():
            # Подписываемся после старта HTTP-сервера, чтобы MAX не постил в пустоту
            await asyncio.sleep(2)
            await bot.delete_webhook()
            await bot.subscribe_webhook(public_url, secret=secret)
            logger.info("Webhook-подписка MAX оформлена")

        asyncio.create_task(_subscribe())
        await webhook.run(host="0.0.0.0", port=port, path=path)
    else:
        logger.info(f"Запускаю бота @{me.username} (id={me.user_id}, long-polling)")
        # Снимаем возможную webhook-подписку: с активным вебхуком MAX не отдаёт
        # события по long-poll
        await bot.delete_webhook()
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
