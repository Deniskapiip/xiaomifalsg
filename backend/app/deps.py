from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.models import User
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


async def session(request: Request):
    async with request.app.state.sessions() as db:
        yield db


@dataclass
class Principal:
    user: User
    role: str


async def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(session)) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("AUTH_REQUIRED", "Откройте приложение из Telegram", 401)
    tg_id = decode_token(credentials.credentials, request.app.state.settings)
    user = await db.scalar(select(User).where(User.tg_id == tg_id))
    if user is None:
        raise AppError("AUTH_REQUIRED", "Повторите вход", 401)
    return Principal(user, request.app.state.settings.role_for(tg_id))


async def administrator(principal: Principal = Depends(current_user)) -> Principal:
    if principal.role not in {"owner", "manager"}:
        raise AppError("FORBIDDEN", "Недостаточно прав", 403)
    return principal


async def owner(principal: Principal = Depends(current_user)) -> Principal:
    if principal.role != "owner":
        raise AppError("OWNER_REQUIRED", "Эта настройка доступна только владельцу", 403)
    return principal
