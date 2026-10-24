import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import logging
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi.errors import RateLimitExceeded

from app.config import ROOT, Settings, get_settings
from app.api import products
from app.db import create_database
from app.errors import AppError, install_error_handlers
from app.limiter import create_limiter, limit_error
from app.routers import admin, auth, orders, public, tracking
from app.services.order_tracking import OrderTrackingWorker
from app.services.tracking import TrackingWorker
from app.startup_errors import StartupError, bot_startup_error

log = logging.getLogger("taoji")


def is_secure_request(request: Request, settings: Settings) -> bool:
    """True when the request reached the app over HTTPS or through a trusted proxy.

    Hosting platforms (Bothost, Caddy, Cloudflare) terminate TLS and forward plain
    HTTP to the container: ``request.url.scheme`` stays "http", but the client
    connection came from the private proxy network or carries X-Forwarded-Proto.
    Such requests must not be rejected by the production HTTPS check. Direct
    public access still has to use https.

    Some platforms strip forwarding headers entirely. For those the operator
    explicitly sets TRUST_PROXY_HTTPS=true: the container port is not published,
    so the only path to the app is the platform TLS proxy.
    """
    if settings.trust_proxy_https:
        return True
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if proto == "https":
        return True
    if request.headers.get("x-forwarded-ssl", "").strip().lower() == "on":
        return True
    client = request.client.host if request.client else ""
    try:
        import ipaddress
        address = ipaddress.ip_address(client)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine, sessions = create_database(settings.database_url)
    write_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        from sqlalchemy import select
        from app.models import AppSettings
        tasks = []
        bot = None
        try:
            try:
                async with sessions() as db:
                    if await db.scalar(select(AppSettings.id).limit(1)) is None:
                        raise StartupError("DATABASE_NOT_READY", "database")
            except StartupError as exc:
                exc.emit_marker()
                raise RuntimeError(exc.message) from None
            except Exception:
                error = StartupError("DATABASE_NOT_READY", "database")
                error.emit_marker()
                raise RuntimeError(error.message) from None
            if settings.bot_enabled:
                from app.bot.bot import configure_bot, create_bot
                from app.services.notifications import NotificationWorker
                try:
                    try:
                        bot, dispatcher = create_bot(settings, sessions, write_lock)
                    except Exception as exc:
                        raise bot_startup_error(exc, "identity") from None
                    await configure_bot(bot, settings)
                except StartupError as exc:
                    exc.emit_marker()
                    raise RuntimeError(exc.message) from None
                except Exception as exc:
                    error = bot_startup_error(exc, "identity")
                    error.emit_marker()
                    raise RuntimeError(error.message) from None
                app.state.bot, app.state.dispatcher = bot, dispatcher
                tasks.append(asyncio.create_task(NotificationWorker(bot, sessions, settings, write_lock).run()))
                if settings.bot_mode == "polling":
                    tasks.append(asyncio.create_task(dispatcher.start_polling(bot, handle_signals=False, close_bot_session=False, allowed_updates=["message"])))
            tasks.append(asyncio.create_task(TrackingWorker(sessions, settings, write_lock, bot).run()))
            if settings.order_tracking_enabled:
                tasks.append(asyncio.create_task(OrderTrackingWorker(sessions, settings).run()))
            app.state.background_tasks = tasks
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            if bot:
                await bot.session.close()
            await engine.dispose()

    app = FastAPI(title="Taoji Cargo API", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs" if settings.env == "development" else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.env == "development" else None)
    app.state.settings, app.state.engine, app.state.sessions, app.state.write_lock = settings, engine, sessions, write_lock
    limiter = create_limiter()
    app.state.limiter = limiter
    install_error_handlers(app)
    app.add_exception_handler(RateLimitExceeded, limit_error)
    app.add_middleware(CORSMiddleware, allow_origins=[settings.origin], allow_methods=["GET", "POST", "PUT", "PATCH"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        try:
            if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 131072:
                response = JSONResponse({"code": "BODY_TOO_LARGE", "message": "Запрос слишком большой"}, status_code=413)
            elif settings.env == "production" and not is_secure_request(request, settings):
                response = JSONResponse({"code": "HTTPS_REQUIRED", "message": "Требуется защищённое HTTPS-соединение"}, status_code=400)
            else:
                response = await call_next(request)
        except Exception as exc:
            log.error("request_error type=%s", type(exc).__name__)
            response = JSONResponse({"code": "INTERNAL_ERROR", "message": "Не удалось выполнить запрос. Попробуйте ещё раз."}, status_code=500)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'"
        if request.url.path.startswith("/api/") or request.url.path.startswith("/telegram/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    for router in (auth.make_router(limiter), public.router, orders.router, admin.router, tracking.router, products.make_router(limiter)):
        app.include_router(router, prefix="/api")

    if settings.bot_enabled and settings.bot_mode == "webhook":
        @app.post("/telegram/webhook/" + settings.webhook_path_secret, include_in_schema=False)
        async def telegram_webhook(request: Request):
            supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
            if not hmac.compare_digest(supplied, settings.webhook_secret_token):
                raise AppError("WEBHOOK_FORBIDDEN", "Запрос отклонён", 403)
            try:
                update = Update.model_validate(await request.json(), context={"bot": app.state.bot})
            except Exception:
                raise AppError("INVALID_UPDATE", "Некорректное событие", 422) from None
            await app.state.dispatcher.feed_update(app.state.bot, update)
            return {"ok": True}

    dist = ROOT / "frontend" / "dist"

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path == "api" or path.startswith(("api/", "telegram/")):
            raise AppError("NOT_FOUND", "Не найдено", 404)
        if not (dist / "index.html").is_file():
            raise AppError("FRONTEND_NOT_BUILT", "Backend работает. Интерфейс появится после Этапа 2 и npm run build.", 503)
        target = (dist / path).resolve()
        if not target.is_relative_to(dist.resolve()):
            raise AppError("NOT_FOUND", "Не найдено", 404)
        if target.is_file():
            return FileResponse(target)
        if Path(path).suffix:
            raise AppError("NOT_FOUND", "Файл не найден", 404)
        return FileResponse(dist / "index.html")

    return app


if __name__ == "__main__":
    import uvicorn
    from pydantic import ValidationError
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    try:
        settings = get_settings()
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1, access_log=False,
                    proxy_headers=True, forwarded_allow_ips=settings.forwarded_allow_ips)
    except ValidationError as exc:
        print("Проверьте .env:")
        for error in exc.errors():
            custom = error.get("ctx", {}).get("error")
            print(str(custom) if custom else f"Некорректная настройка: {'.'.join(map(str, error['loc']))}")
        raise SystemExit(1) from None
