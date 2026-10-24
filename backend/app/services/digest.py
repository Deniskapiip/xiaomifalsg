"""Ежедневная сводка владельцу и менеджеру в Telegram.

Раз в сутки после DIGEST_HOUR (МСК) отправляет: новые заказы за сегодня,
доставленные сегодня и «зависшие» заказы (статус не менялся > STALE_ORDER_DAYS).
Внешние сервисы не нужны, состояние держится в памяти процесса.
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import func, select

from app.bot import texts
from app.db_types import utcnow
from app.models import Order
from app.statuses import BY_KEY, Status

log = logging.getLogger("taoji")
MOSCOW = ZoneInfo("Europe/Moscow")


class DigestWorker:
    def __init__(self, bot, sessions, settings):
        self.bot, self.sessions, self.settings = bot, sessions, settings

    async def run(self) -> None:
        sent_for = None
        while True:
            try:
                local = utcnow().astimezone(MOSCOW)
                if (self.settings.digest_enabled and local.hour >= self.settings.digest_hour
                        and sent_for != local.date()):
                    await self.send()
                    sent_for = local.date()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - сводка не должна ронять приложение
                log.error("digest_error type=%s", type(exc).__name__)
            await asyncio.sleep(300)

    async def send(self) -> None:
        async with self.sessions() as db:
            now = utcnow()
            local = now.astimezone(MOSCOW)
            midnight = datetime.combine(local.date(), time.min, tzinfo=MOSCOW).astimezone(timezone.utc)
            new_today = await db.scalar(select(func.count()).select_from(Order).where(Order.created_at >= midnight))
            delivered_today = await db.scalar(select(func.count()).select_from(Order).where(
                Order.status == Status.delivered.value, Order.updated_at >= midnight))
            stale_rows = (await db.scalars(
                select(Order).where(Order.status.not_in([Status.delivered.value, Status.cancelled.value]),
                                    Order.updated_at < now - timedelta(days=self.settings.stale_order_days))
                .order_by(Order.updated_at, Order.id).limit(6))).all()
            stale = [SimpleNamespace(public_no=row.public_no, status_name=BY_KEY[row.status]["name"],
                                     days=max(1, (now - row.updated_at).days)) for row in stale_rows]
            content = texts.daily_digest(new_today or 0, delivered_today or 0, stale,
                                         self.settings.stale_order_days)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="Открыть админку",
            web_app=WebAppInfo(url=self.settings.webapp_url.rstrip("/") + "/?tab=admin"))]])
        for tg_id in sorted(self.settings.owner_id_set | self.settings.manager_id_set):
            try:
                await self.bot.send_message(chat_id=tg_id, text=content, parse_mode="HTML", reply_markup=keyboard)
            except Exception as exc:  # noqa: BLE001 - один получатель не должен ломать остальных
                log.warning("digest_send_error type=%s", type(exc).__name__)
