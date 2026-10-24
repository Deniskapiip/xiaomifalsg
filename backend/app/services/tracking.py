"""Отслеживание внешних трек-номеров (Добропост).

Добропост не отдаёт публичную документацию API, а его домены могут быть
недоступны с хостинга, поэтому источник статуса настраиваемый: шаблон URL
в DOBROPOST_TRACKING_URL (с {track}) или стандартные варианты ниже.
Обновление выполняется фоновой задачей раз в TRACKING_REFRESH_HOURS часов.
"""

import asyncio
import html
import json
import logging
import re
from datetime import timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import select

from app.db_types import utcnow
from app.models import TrackingLink, User

log = logging.getLogger("taoji")

DEFAULT_TEMPLATES = (
    "https://tracking.dobropost.com/{track}",
    "https://tracking.dobropost.com/?track={track}",
    "https://tracking.dobropost.com/track/{track}",
    "https://dobropost.com/tracking/{track}",
)
STATUS_PATTERNS = (
    re.compile(r"Статус[^:]{0,40}:\s*([^|\n]{2,120})", re.IGNORECASE),
    re.compile(r"(Доставлен[^.\n]{0,100}|В пути[^.\n]{0,100}|Ожидает[^.\n]{0,100}|"
               r"Прибыл[^.\n]{0,100}|Передан[^.\n]{0,100}|Возврат[^.\n]{0,100})", re.IGNORECASE),
)
USER_AGENT = "TaojiCargo/1.0 (Telegram Mini App tracking)"
COOLDOWN_MINUTES = 15


def tracking_urls(track_number: str, settings) -> list[str]:
    template = (getattr(settings, "dobropost_tracking_url", "") or "").strip()
    templates = (template,) if "{track}" in template else DEFAULT_TEMPLATES
    return [item.replace("{track}", quote(track_number, safe="")) for item in templates]


def extract_status_text(payload: str, content_type: str = "") -> str:
    raw = payload.strip()
    if not raw:
        return ""
    if "json" in content_type or raw.startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if data is not None:
            found = _find_status_in_json(data)
            if found:
                return found[:200]
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    for pattern in STATUS_PATTERNS:
        match = pattern.search(text)
        if match:
            return " ".join(match.group(1).split())[:200]
    return ""


def _find_status_in_json(node) -> str:
    keys = {"status", "status_text", "statustext", "status_name", "state", "operation", "stage"}
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in node.values():
            found = _find_status_in_json(value)
            if found:
                return found
    if isinstance(node, list):
        for value in node:
            found = _find_status_in_json(value)
            if found:
                return found
    return ""


async def fetch_status(track_number: str, settings) -> tuple[str, bool]:
    """Fetch the carrier page. Returns (status text, success flag)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(6.0), follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        for url in tracking_urls(track_number, settings):
            try:
                response = await client.get(url)
            except httpx.HTTPError:
                continue
            if response.status_code != 200 or not response.text.strip():
                continue
            status = extract_status_text(response.text, response.headers.get("content-type", ""))
            return status, bool(status)
    return "", False


async def refresh_link(db, link: TrackingLink, settings) -> TrackingLink:
    hours = max(1, int(settings.tracking_refresh_hours))
    status, ok = await fetch_status(link.track_number, settings)
    link.last_checked_at = utcnow()
    link.ok = ok
    link.next_check_at = utcnow() + timedelta(hours=hours)
    if ok and status:
        link.status_text = status[:200]
    await db.commit()
    return link


async def refresh_link_by_id(sessions, link_id: int, settings) -> TrackingLink | None:
    async with sessions() as db:
        link = await db.get(TrackingLink, link_id)
        if link is None:
            return None
        return await refresh_link(db, link, settings)


class TrackingWorker:
    """Раз в минуту проверяет, у каких треков подошло время обновления."""

    def __init__(self, sessions, settings, write_lock=None, bot=None):
        self.sessions, self.settings, self.bot = sessions, settings, bot
        self.write_lock = write_lock

    async def refresh_due(self, limit: int = 20) -> int:
        async with self.sessions() as db:
            ids = list((await db.scalars(
                select(TrackingLink.id).where(TrackingLink.next_check_at <= utcnow()).limit(limit)
            )).all())
        refreshed = 0
        for link_id in ids:
            async with self.sessions() as db:
                link = await db.get(TrackingLink, link_id)
                if link is None or link.next_check_at > utcnow():
                    continue
                previous = link.status_text
                try:
                    await refresh_link(db, link, self.settings)
                except Exception as exc:  # noqa: BLE001 - фоновая задача не должна падать
                    log.error("tracking_refresh_error type=%s", type(exc).__name__)
                    link.next_check_at = utcnow() + timedelta(hours=1)
                    await db.commit()
                    continue
                refreshed += 1
                if self.bot is not None and link.ok and link.status_text and link.status_text != previous:
                    await self._notify(db, link)
        return refreshed

    async def _notify(self, db, link: TrackingLink) -> None:
        try:
            user = await db.get(User, link.user_id)
            if user is None or not user.can_write:
                return
            from app.bot import texts
            await self.bot.send_message(chat_id=user.tg_id, text=texts.external_tracking_update(link),
                                        parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 - уведомление не должно ломать обновление
            log.warning("tracking_notify_error type=%s", type(exc).__name__)

    async def run(self) -> None:
        while True:
            try:
                await self.refresh_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("tracking_worker_error type=%s", type(exc).__name__)
            await asyncio.sleep(60)
