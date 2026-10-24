from sqlalchemy import select

from app.db_types import utcnow
from app.errors import AppError
from app.models import AppSettings, RateHistory, Tariff, User
from app.schemas import RateHistoryOut, SettingsIn, SettingsOut, TariffIn, UserOut


async def get_app_settings(db) -> AppSettings:
    value = await db.get(AppSettings, 1)
    if value is None:
        raise AppError("SETTINGS_MISSING", "Начальные настройки отсутствуют. Запустите python -m app.seed", 503)
    return value


async def active_tariff(db, tariff_id: int) -> Tariff:
    tariff = await db.get(Tariff, tariff_id)
    if tariff is None or not tariff.is_active or (tariff.price_per_kg <= 0 and not tariff.price_on_request):
        raise AppError("TARIFF_INACTIVE", "Этот тариф сейчас недоступен. Выберите другой.", 422)
    return tariff


async def settings_output(db) -> SettingsOut:
    value = await get_app_settings(db)
    history = (await db.scalars(select(RateHistory).order_by(RateHistory.changed_at.desc(), RateHistory.id.desc()).limit(50))).all()
    author_ids = {entry.changed_by for entry in history}
    authors = (await db.scalars(select(User).where(User.id.in_(author_ids)))).all() if author_ids else []
    authors_by_id = {user.id: UserOut.model_validate(user) for user in authors}
    return SettingsOut(rate_cny_rub=value.rate_cny_rub, commission_percent=value.commission_percent,
                       commission_min_rub=str(value.commission_min_rub), rate_updated_at=value.rate_updated_at,
                       rate_updated_by=value.rate_updated_by, rate_history=[RateHistoryOut.model_validate(x).model_copy(
                           update={"changed_by_user": authors_by_id.get(x.changed_by)}) for x in history])


async def update_settings(db, data: SettingsIn, actor_id: int):
    value = await get_app_settings(db)
    db.add(RateHistory(old_rate=value.rate_cny_rub, new_rate=data.rate_cny_rub, changed_by=actor_id))
    value.rate_cny_rub = data.rate_cny_rub
    value.commission_percent = data.commission_percent
    value.commission_min_rub = int(data.commission_min_rub)
    value.rate_updated_at = utcnow()
    value.rate_updated_by = actor_id
    await db.commit()
    return await settings_output(db)


async def save_tariff(db, data: TariffIn, tariff_id: int | None = None):
    tariff = Tariff() if tariff_id is None else await db.get(Tariff, tariff_id)
    if tariff is None:
        raise AppError("NOT_FOUND", "Тариф не найден", 404)
    for key, value in data.model_dump().items():
        setattr(tariff, key, value)
    db.add(tariff)
    await db.commit()
    return tariff
