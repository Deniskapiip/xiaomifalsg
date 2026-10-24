import asyncio
import logging
from datetime import timedelta

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select, update

from app.bot import texts
from app.db_types import utcnow
from app.models import NotificationJob, NotificationLog, Order, OrderEvent, OrderItem, User

log = logging.getLogger("taoji")


async def is_local_preview_order(db, order_id: int) -> bool:
    payload = await db.scalar(select(OrderEvent.payload).where(
        OrderEvent.order_id == order_id, OrderEvent.type == "created"
    ).order_by(OrderEvent.id).limit(1))
    return isinstance(payload, dict) and payload.get("local_preview") is True


async def wake_write_access_jobs(db, user_id):
    await db.execute(update(NotificationJob).where(NotificationJob.user_id == user_id, NotificationJob.state == "waiting_access")
                     .values(state="pending", attempts=0, next_attempt_at=utcnow()))


class NotificationWorker:
    def __init__(self, bot, sessions, settings, write_lock):
        self.bot, self.sessions, self.settings, self.write_lock = bot, sessions, settings, write_lock

    async def recover(self):
        async with self.write_lock:
            async with self.sessions() as db:
                await db.execute(update(NotificationJob).where(NotificationJob.state == "sending").values(state="pending", next_attempt_at=utcnow()))
                await db.commit()

    async def deliver_one(self) -> bool:
        async with self.write_lock:
            async with self.sessions() as db:
                job = await db.scalar(select(NotificationJob).where(NotificationJob.state == "pending", NotificationJob.next_attempt_at <= utcnow()).order_by(NotificationJob.id).limit(1))
                if job is None:
                    return False
                if await is_local_preview_order(db, job.order_id):
                    # The marker belongs to the order, so enabling a real bot later
                    # cannot turn local preview notifications into live messages.
                    job.state = "skipped"
                    db.add(NotificationLog(user_id=job.user_id, order_id=job.order_id,
                                           kind=job.kind, ok=False, error="LOCAL_PREVIEW_SKIPPED"))
                    await db.commit()
                    return True
                recipient = await db.get(User, job.user_id)
                if not recipient.can_write:
                    job.state = "waiting_access"
                    db.add(NotificationLog(user_id=job.user_id, order_id=job.order_id, kind=job.kind, ok=False, error="WRITE_ACCESS_REQUIRED"))
                    await db.commit()
                    return True
                if job.attempts >= 3:
                    job.state = "failed"
                    await db.commit()
                    return True
                job.state = "sending"
                job.attempts += 1
                order, event = await db.get(Order, job.order_id), await db.get(OrderEvent, job.event_id)
                if job.kind == "admin_created":
                    client = await db.get(User, order.user_id)
                    items = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)
                                              .order_by(OrderItem.position, OrderItem.id))).all()
                    content = texts.admin_notification(order, client, self.settings, items)
                    chat_link = f"https://t.me/{client.username}" if client.username else f"tg://user?id={client.tg_id}"
                    buttons = [[InlineKeyboardButton(text=texts.BUTTON_ADMIN, web_app=WebAppInfo(url=self.settings.webapp_url.rstrip("/") + f"/?open=order_{order.id}"))],
                               [InlineKeyboardButton(text=texts.BUTTON_CLIENT, url=chat_link)]]
                else:
                    content = texts.client_notification(job.kind, order, event, self.settings)
                    buttons = [[InlineKeyboardButton(text=texts.BUTTON_ORDER, web_app=WebAppInfo(url=self.settings.webapp_url.rstrip("/") + f"/?open=order_{order.id}"))]]
                chat_id, job_id, attempts = recipient.tg_id, job.id, job.attempts
                await db.commit()
        ok, error, wait, forbidden = False, None, 2 ** attempts, False
        try:
            await self.bot.send_message(chat_id=chat_id, text=content, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            ok = True
        except TelegramForbiddenError:
            error, forbidden = "TELEGRAM_FORBIDDEN", True
        except TelegramRetryAfter as exc:
            error, wait = "TELEGRAM_RETRY_AFTER", max(1, int(exc.retry_after))
        except Exception as exc:
            # Do not persist Telegram exception text: it may contain personal input or URLs.
            error = type(exc).__name__[:100]
        async with self.write_lock:
            async with self.sessions() as db:
                job = await db.get(NotificationJob, job_id)
                db.add(NotificationLog(user_id=job.user_id, order_id=job.order_id, kind=job.kind, ok=ok, error=error))
                if ok:
                    job.state = "done"
                elif forbidden:
                    recipient = await db.get(User, job.user_id)
                    recipient.can_write = False
                    job.state = "waiting_access"
                elif attempts >= 3:
                    job.state = "failed"
                else:
                    job.state = "pending"
                    job.next_attempt_at = utcnow() + timedelta(seconds=wait)
                await db.commit()
        return True

    async def run(self):
        await self.recover()
        while True:
            try:
                if not await self.deliver_one():
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("notification_worker_error type=%s", type(exc).__name__)
                await asyncio.sleep(2)
