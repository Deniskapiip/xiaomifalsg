import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from app.bot.handlers import create_router
from app.bot.session import create_telegram_session
from app.bot.texts import BUTTON_OPEN, COMMANDS
from app.startup_errors import bot_startup_error

STARTUP_REQUEST_TIMEOUT_SECONDS = 10


def create_bot(settings, sessions, write_lock):
    bot = Bot(token=settings.bot_token, session=create_telegram_session(settings.bot_proxy_url),
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(settings, sessions, write_lock))
    return bot, dispatcher


async def configure_bot(bot, settings):
    async def request(stage, operation):
        try:
            await asyncio.wait_for(operation(), timeout=STARTUP_REQUEST_TIMEOUT_SECONDS)
        except Exception as exc:
            raise bot_startup_error(exc, stage) from None

    await request("identity", bot.get_me)
    await request("commands", lambda: bot.set_my_commands([BotCommand(command=name, description=text) for name, text in COMMANDS]))
    await request("menu", lambda: bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text=BUTTON_OPEN, web_app=WebAppInfo(url=settings.webapp_url))))
    if settings.bot_mode == "polling":
        await request("polling", lambda: bot.delete_webhook(drop_pending_updates=False))
    else:
        await request("webhook", lambda: bot.set_webhook(url=settings.webapp_url.rstrip("/") + "/telegram/webhook/" + settings.webhook_path_secret,
                                                        secret_token=settings.webhook_secret_token, allowed_updates=["message"], drop_pending_updates=False))
