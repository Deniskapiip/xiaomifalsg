from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import current_user, session
from app.models import Tariff
from app.schemas import CalcIn, CalcOut, ConfigOut, PriceOut, TariffOut
from app.services.pricing import calculate
from app.services.settings import active_tariff, get_app_settings
from app.statuses import BY_KEY

router = APIRouter(tags=["Конфигурация и расчёт"])


@router.get("/health")
async def health(db: AsyncSession = Depends(session)):
    from sqlalchemy import text
    await db.execute(text("SELECT 1"))
    return {"ok": True, "service": "taoji-cargo"}


@router.get("/config", response_model=ConfigOut, dependencies=[Depends(current_user)])
async def config(request: Request, db: AsyncSession = Depends(session)):
    current = await get_app_settings(db)
    tariffs = (await db.scalars(select(Tariff).where(Tariff.is_active.is_(True)).order_by(Tariff.sort_order, Tariff.id))).all()
    settings = request.app.state.settings
    return ConfigOut(rate_cny_rub=current.rate_cny_rub, rate_updated_at=current.rate_updated_at,
                     commission_percent=current.commission_percent, commission_min_rub=str(current.commission_min_rub),
                     insurance_percent=settings.insurance_percent, packing_fee_rub=str(settings.packing_fee_rub),
                     photo_report_fee_rub=str(settings.photo_report_fee_rub),
                     contacts={"owner": settings.owner_username, "manager": settings.manager_username, "channel": settings.channel_username},
                     statuses=list(BY_KEY.values()), tariffs=[TariffOut.model_validate(x) for x in tariffs])


@router.post("/calc", response_model=CalcOut, dependencies=[Depends(current_user)])
async def calc(request: Request, data: CalcIn, db: AsyncSession = Depends(session)):
    current, tariff = await get_app_settings(db), await active_tariff(db, data.tariff_id)
    settings = request.app.state.settings
    prices = calculate(data.price_cny, data.quantity, current.rate_cny_rub, current.commission_percent,
                       current.commission_min_rub, tariff.price_per_kg_rub, data.weight_kg,
                       insurance_enabled=data.insurance_enabled, packing_enabled=data.packing_enabled,
                       photo_report_enabled=data.photo_report_enabled, insurance_percent=settings.insurance_percent,
                       packing_fee_rub=settings.packing_fee_rub, photo_report_fee_rub=settings.photo_report_fee_rub)
    return CalcOut(**prices.model_dump(), rate=current.rate_cny_rub, commission_percent=current.commission_percent,
                   commission_min_rub=str(current.commission_min_rub), tariff_name=tariff.name,
                   tariff_price_per_kg=tariff.price_per_kg_rub)
