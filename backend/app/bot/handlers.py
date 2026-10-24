from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import select

from app.bot import texts
from app.models import User
from app.routers.auth import upsert_user
from app.schemas import TelegramUser
from app.services.orders import find_tracked_order


def app_keyboard(settings, path=""):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=texts.BUTTON_ORDERS if path else texts.BUTTON_OPEN,
        web_app=WebAppInfo(url=settings.webapp_url.rstrip("/") + path))]])


def create_router(settings, sessions, write_lock):
    router = Router()

    async def remember(message):
        if message.from_user is None:
            return
        telegram = TelegramUser.model_validate(message.from_user.model_dump())
        async with write_lock:
            async with sessions() as db:
                await upsert_user(db, telegram, write_access=True)
                await db.commit()

    @router.message(CommandStart(), F.chat.type == "private")
    async def start(message: Message):
        await remember(message)
        await message.answer(texts.welcome(settings), reply_markup=app_keyboard(settings))

    @router.message(Command("app"), F.chat.type == "private")
    async def open_app(message: Message):
        await remember(message)
        await message.answer(texts.APP_TEXT, reply_markup=app_keyboard(settings))

    @router.message(Command("orders"), F.chat.type == "private")
    async def orders(message: Message):
        await remember(message)
        await message.answer(texts.ORDERS_TEXT, reply_markup=app_keyboard(settings, "/?tab=orders"))

    @router.message(Command("track"), F.chat.type == "private")
    async def track(message: Message):
        await remember(message)
        parts = (message.text or "").split(maxsplit=1)
        number = " ".join(parts[1].split()) if len(parts) > 1 else ""
        if not number:
            await message.answer(texts.TRACK_USAGE, reply_markup=app_keyboard(settings, "/?tab=orders"))
            return
        order = None
        if message.from_user is not None:
            async with sessions() as db:
                user = await db.scalar(select(User).where(User.tg_id == message.from_user.id))
                if user is not None:
                    order = await find_tracked_order(db, number, user.id)
        if order is None:
            await message.answer(texts.track_not_found(number))
            return
        await message.answer(texts.track_status(order), reply_markup=app_keyboard(settings, f"/?open=order_{order.id}"))

    @router.message(Command("help"), F.chat.type == "private")
    async def help_command(message: Message):
        await remember(message)
        await message.answer(texts.help_text(settings))

    @router.message(F.write_access_allowed, F.chat.type == "private")
    async def write_allowed(message: Message):
        await remember(message)

    return router
