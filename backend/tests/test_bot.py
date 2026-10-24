import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.types import Chat, Message, Update, User as TelegramUser
from sqlalchemy import select

from app.bot.bot import configure_bot, create_bot
from app.models import User


async def test_bot_config_polling_and_webhook(settings):
    bot = AsyncMock()
    settings.bot_mode = "polling"
    await configure_bot(bot, settings)
    bot.delete_webhook.assert_awaited_once_with(drop_pending_updates=False)
    button = bot.set_chat_menu_button.await_args.kwargs["menu_button"]
    assert button.web_app.url == settings.webapp_url
    assert {x.command for x in bot.set_my_commands.await_args.args[0]} == {"start", "app", "orders", "track", "help"}
    bot.reset_mock()
    settings.bot_mode = "webhook"
    settings.webhook_path_secret = "a" * 32
    settings.webhook_secret_token = "b" * 32
    await configure_bot(bot, settings)
    bot.set_webhook.assert_awaited_once()
    assert bot.set_webhook.await_args.kwargs["secret_token"] == "b" * 32
    bot.delete_webhook.assert_not_awaited()


async def test_start_remembers_user_without_network(app, settings, monkeypatch):
    bot, dispatcher = create_bot(settings, app.state.sessions, app.state.write_lock)
    # Mock the real transport boundary; the aiogram dispatcher/handler still run.
    response = Message(message_id=2, date=datetime.now(timezone.utc), chat=Chat(id=555, type="private"), text="ok")
    sender = AsyncMock(return_value=response)
    monkeypatch.setattr(bot.session, "make_request", sender)
    update = Update(update_id=1, message=Message(message_id=1, date=datetime.now(timezone.utc),
                    chat=Chat(id=555, type="private"), from_user=TelegramUser(id=555, is_bot=False, first_name="Клиент"), text="/start"))
    try:
        await dispatcher.feed_update(bot, update)
        sender.assert_awaited_once()
        async with app.state.sessions() as db:
            user = await db.scalar(select(User).where(User.tg_id == 555))
            assert user is not None and user.can_write and user.first_name == "Клиент"
    finally:
        await bot.session.close()
