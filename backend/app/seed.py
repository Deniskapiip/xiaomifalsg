import argparse
import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.db import create_database
from app.models import AppSettings, Tariff


async def seed_database(sessions, demo: bool = False):
    async with sessions() as db:
        if await db.get(AppSettings, 1) is None:
            db.add(AppSettings(id=1, rate_cny_rub=Decimal("13.5"), commission_percent=Decimal("6.5"), commission_min_rub=650))
        if await db.scalar(select(Tariff.id).limit(1)) is None:
            for index in range(1, 5):
                db.add(Tariff(name=f"Тариф {index}", price_per_kg=Decimal("0"), is_active=False, sort_order=index))
            await db.flush()
        if demo:
            tariffs = (await db.scalars(select(Tariff).order_by(Tariff.id).limit(4))).all()
            for index, tariff in enumerate(tariffs, start=1):
                # Never overwrite an owner's configured tariff.
                if tariff.price_per_kg == 0 and not tariff.is_active and tariff.name == f"Тариф {index}" and not tariff.description and not tariff.eta_text:
                    tariff.name = f"Тариф {index} (демо)"
                    tariff.price_per_kg = Decimal(1800 + (index - 1) * 200)
                    tariff.description = "Демонстрационный тариф для проверки. Не является предложением доставки."
                    tariff.eta_text = "Демо: сроки уточняйте у менеджера"
                    tariff.is_active = True
        await db.commit()


async def main(demo: bool):
    engine, sessions = create_database(get_settings().database_url)
    try:
        await seed_database(sessions, demo)
        print("Начальные данные готовы" + (". Демо-тарифы включены только для тестирования." if demo else ". Тарифы неактивны."))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Начальные данные Taoji Cargo; сначала выполните alembic upgrade head")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.demo))
