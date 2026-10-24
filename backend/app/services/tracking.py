"""Отслеживание внешних трек-номеров (Добропост).

Публичный трекинг Добропоста использует API:
  https://api.dobropost.com/api/tracking/parcel?key=<key>&trackCode=<код>   — коды DBRPST…
  https://api.dobropost.com/api/tracking/shipment?key=<key>&trackCode=<код> — остальные
Ключ публичный (взят из JS трекинг-страницы), поэтому хранится как обычная настройка.
Если api.dobropost.com недоступен с хостинга, используем прокси Google Translate
(api-dobropost-com.translate.goog), который отдаёт тот же ответ.
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

PARCEL_PREFIX = "DBRPST"
STATUS_KEYS = ("statusName", "status_name", "status", "state", "deliveryStatus", "lastStatus")
CHECKPOINT_KEYS = ("statusRUName", "statusName", "status_text", "statusText", "status", "name", "title",
                   "description", "comment")
LEGACY_TEMPLATES = (
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


def track_kind(track_number: str) -> str:
    return "parcel" if track_number.upper().startswith(PARCEL_PREFIX) else "shipment"


def api_urls(track_number: str, settings) -> list[str]:
    """Official API first, then the Google-Translate proxy fallback, then legacy pages."""
    kind = track_kind(track_number)
    key = getattr(settings, "dobropost_api_key", "") or ""
    encoded = quote(track_number, safe="")
    urls = []
    base = (getattr(settings, "dobropost_api_base", "") or "").rstrip("/")
    if base:
        urls.append(f"{base}/{kind}?key={quote(key, safe='')}&trackCode={encoded}")
    proxy = (getattr(settings, "dobropost_proxy_base", "") or "").rstrip("/")
    if proxy:
        urls.append(f"{proxy}/{kind}?key={quote(key, safe='')}&trackCode={encoded}"
                    "&_x_tr_sl=ru&_x_tr_tl=en&_x_tr_hl=ru")
    # Публичные прокси-редьюсеры: на случай, если и API, и translate.goog
    # недоступны с конкретного хостинга (обе отдают тело ответа как есть).
    direct = f"{base}/{kind}?key={quote(key, safe='')}&trackCode={encoded}" if base else ""
    if direct:
        urls.append("https://api.allorigins.win/raw?url=" + quote(direct, safe=""))
        urls.append("https://api.codetabs.com/v1/proxy?quest=" + quote(direct, safe=""))
    template = (getattr(settings, "dobropost_tracking_url", "") or "").strip()
    if "{track}" in template:
        urls.append(template.replace("{track}", encoded))
    else:
        urls.extend(item.replace("{track}", encoded) for item in LEGACY_TEMPLATES)
    return urls


def extract_status_text(payload: str, content_type: str = "") -> str:
    raw = payload.strip()
    if not raw:
        return ""
    if "json" in content_type or raw[:1] in "{[":
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if data is not None:
            found = extract_api_status(data)
            if found:
                return found[:200]
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    found = _not_found_text(text)
    if found:
        return found
    for pattern in STATUS_PATTERNS:
        match = pattern.search(text)
        if match:
            return " ".join(match.group(1).split())[:200]
    return ""


def _not_found_text(text: str) -> str:
    lowered = text.lower()
    if "not found" in lowered or "не найден" in lowered:
        return "Трек-номер не найден в системе Добропоста"
    return ""


def extract_api_status(data) -> str:
    """Extract the latest status from the DobroPost API response.

    Реальный ответ: {"checkpoints": [{"date": "...", "statusName": "...",
    "statusRUName": "Посылка доставлена получателю", "statusCategoryId": 11}, ...]}
    Массив отсортирован от свежего к старому, поэтому берём первый чекпоинт
    (и на всякий случай сортируем по дате, если она есть).
    """
    if isinstance(data, dict):
        checkpoints = _first_list(data, ("checkpoints", "checkpointsList", "history", "events", "statuses"))
        if checkpoints:
            items = [item for item in checkpoints if isinstance(item, dict)]
            if items:
                if any(item.get("date") for item in items):
                    items.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
                latest = items[0]
                for key in CHECKPOINT_KEYS:
                    value = latest.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            for item in reversed(checkpoints):
                if isinstance(item, str) and item.strip():
                    return item.strip()
        for key in STATUS_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in data.values():
            found = extract_api_status(value)
            if found:
                return found
    if isinstance(data, list):
        for value in reversed(data):
            found = extract_api_status(value)
            if found:
                return found
    return ""


def _first_list(data: dict, keys) -> list | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list) and value:
            return value
    return None


async def fetch_status(track_number: str, settings, fast: bool = False) -> tuple[str, bool]:
    """Fetch the carrier status. Returns (status text, success flag).

    fast=True — для синхронной проверки при сохранении трека: один запрос
    к официальному API с коротким таймаутом, без прокси-цепочек. Если не вышло,
    статус подтянет фоновый воркер через минуту.
    """
    urls = api_urls(track_number, settings)
    if fast:
        urls = urls[:1]
    timeout = httpx.Timeout(4.0 if fast else 10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        for url in urls:
            try:
                response = await client.get(url)
            except httpx.HTTPError:
                continue
            if response.status_code == 404:
                return "Трек-номер не найден в системе Добропоста", True
            if response.status_code != 200 or not response.text.strip():
                continue
            status = extract_status_text(response.text, response.headers.get("content-type", ""))
            if status:
                return status, True
            # Диагностика для хостинга: ответ пришёл, но разобрать статус не удалось.
            log.warning("tracking_unparsed status=%s body=%s", response.status_code,
                        response.text[:300].replace("\n", " "))
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
