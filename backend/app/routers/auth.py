import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_types import utcnow
from app.deps import session
from app.errors import AppError
from app.models import User
from app.schemas import AuthIn, AuthOut, TelegramUser, UserOut
from app.security import issue_token, validate_init_data


async def upsert_user(db, telegram: TelegramUser, write_access: bool | None = None):
    user = await db.scalar(select(User).where(User.tg_id == telegram.id))
    if user is None:
        user = User(tg_id=telegram.id, first_name=telegram.first_name, can_write=False)
        db.add(user)
    user.first_name, user.last_name = telegram.first_name, telegram.last_name
    user.username, user.language_code = telegram.username, telegram.language_code
    user.last_seen_at = utcnow()
    if write_access is not None:
        user.can_write = write_access
    elif telegram.allows_write_to_pm:
        user.can_write = True
    await db.flush()
    if user.can_write:
        from app.services.notifications import wake_write_access_jobs
        await wake_write_access_jobs(db, user.id)
    return user


def make_router(limiter):
    router = APIRouter(prefix="/auth", tags=["Вход"])

    @router.post("/telegram", response_model=AuthOut)
    @limiter.limit("30/minute")
    async def telegram_auth(request: Request, data: AuthIn, db: AsyncSession = Depends(session)):
        settings = request.app.state.settings
        if not data.initData and settings.dev_mode:
            host = request.url.hostname
            peer = request.client.host if request.client else ""
            if host not in {"localhost", "127.0.0.1", "::1"} or peer not in {"127.0.0.1", "::1", "testclient"} or any(key in request.headers for key in ("cf-connecting-ip", "x-forwarded-for", "forwarded")):
                raise AppError("DEV_LOCAL_ONLY", "Тестовый вход разрешён только локально", 403)
            telegram = TelegramUser(id=settings.dev_user_tg_id, first_name="Тестовый пользователь")
            auth_date = int(time.time())
        else:
            telegram, auth_date = validate_init_data(data.initData, settings)
        async with request.app.state.write_lock:
            user = await upsert_user(db, telegram)
            await db.commit()
        token, expires = issue_token(user.tg_id, settings, auth_date)
        return AuthOut(access_token=token, expires_in=expires, user=UserOut.model_validate(user), role=settings.role_for(user.tg_id))

    return router
