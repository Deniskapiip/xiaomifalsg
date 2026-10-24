"""Integration tests require a dedicated, disposable PostgreSQL database.

TAOJI_TEST_POSTGRES_URL must NEVER point to the application database: this
fixture rebuilds its public schema. Ordinary local pytest skips these cases.
"""
import os
import sys
from pathlib import Path
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.sqlite_to_postgres import migrate
from scripts.resume_import_notifications import resume
from app.models import Base, User, Order, OrderEvent, NotificationJob
from app.db import create_database
from app.seed import seed_database
from app.schemas import OrderCreate, StatusIn
from app.services.orders import create_order, change_status
from app.config import Settings


@pytest.fixture
async def target():
    url=os.environ.get('TAOJI_TEST_POSTGRES_URL')
    if not url or os.environ.get('TAOJI_TEST_POSTGRES_DISPOSABLE')!='yes':
        pytest.skip('Requires explicitly disposable PostgreSQL')
    if make_url(url).database!='taoji_integration':
        pytest.fail('Integration tests require a separate database named taoji_integration')
    engine=create_async_engine(url,connect_args={'timeout':8,'command_timeout':15})
    async with engine.begin() as db:
        await db.execute(text('DROP SCHEMA public CASCADE'))
        await db.execute(text('CREATE SCHEMA public'))
    await engine.dispose()
    # Alembic uses asyncio.run; run its CLI in an independent process instead.
    import asyncio
    environment={**os.environ,'DATABASE_URL':url,'BOT_ENABLED':'false','ENV':'development','DEV_MODE':'false',
                 'JWT_SECRET':'integration-secret-at-least-thirty-two-characters','WEBAPP_URL':'http://127.0.0.1:8000'}
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','alembic','upgrade','head',
        cwd=ROOT/'backend',env=environment,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        output,error=await asyncio.wait_for(process.communicate(),timeout=30)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise
    assert process.returncode==0,error.decode()
    yield url


@pytest.fixture
async def source(tmp_path):
    path=tmp_path/'source #100%.db'
    engine,sessions=create_database('sqlite+aiosqlite:///'+str(path))
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
        await db.execute(text('CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)'))
        await db.execute(text("INSERT INTO alembic_version VALUES ('0001')"))
    await seed_database(sessions,demo=True)
    config=Settings(_env_file=None,env='development',dev_mode=False,bot_mode='polling',webapp_url='http://127.0.0.1:8000',
                    bot_enabled=False,jwt_secret='source-test-secret-at-least-thirty-two-characters',owner_ids='111',manager_ids='')
    async with sessions() as db:
        user=User(id=41,tg_id=333,first_name='Клиент',can_write=True)
        db.add(user)
        await db.commit()
        payload=OrderCreate(idempotency_key=uuid4(),link='https://item.taobao.com/item.htm?id=123',price_cny='300',quantity=1,tariff_id=1,weight_kg='2.3')
        order=await create_order(db,payload,user,config)
        await change_status(db,order,StatusIn(status='awaiting_delivery_payment',delivery_amount_rub='4300',notify=True),user.id)
    await engine.dispose()
    yield path


async def test_copy_preserves_exact_values_dates_history_and_sequences(source,target):
    original=source.read_bytes()
    counts=await migrate(source,target)
    assert counts['orders']==1 and counts['order_events']==3
    engine=create_async_engine(target)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    try:
        async with sessions() as db:
            order=await db.scalar(select(Order))
            assert order.total_rub==4700 and order.delivery_final_rub==4300
            assert order.price_cny==Decimal('300.00') and order.rate==Decimal('13.5000')
            assert order.created_at.tzinfo is not None
            assert (await db.scalars(select(NotificationJob.state))).all()==['paused_migration']*3
            user=User(tg_id=444,first_name='Новый клиент',can_write=False)
            db.add(user)
            await db.commit()
            assert user.id>41
        assert await resume(target)==3
        assert await resume(target)==0
    finally: await engine.dispose()
    assert source.read_bytes()==original


async def test_nonempty_target_refused_without_merging(source,target):
    await migrate(source,target)
    with pytest.raises(ValueError,match='not empty'): await migrate(source,target)
    engine=create_async_engine(target)
    try:
        async with engine.connect() as db: assert await db.scalar(text('SELECT count(*) FROM orders'))==1
    finally: await engine.dispose()


async def test_invalid_late_row_rolls_back_all_tables(source,target):
    import sqlite3
    with sqlite3.connect(source) as db: db.execute('UPDATE orders SET link=?',('x'*2001,))
    with pytest.raises(Exception): await migrate(source,target)
    engine=create_async_engine(target)
    try:
        async with engine.connect() as db:
            for table in Base.metadata.sorted_tables:
                assert await db.scalar(text('SELECT count(*) FROM '+table.name))==0
    finally: await engine.dispose()


async def test_pending_notifications_require_explicit_include(source,target):
    await migrate(source,target,include_pending=True)
    engine=create_async_engine(target)
    try:
        async with engine.connect() as db:
            assert (await db.execute(text('SELECT DISTINCT state FROM notification_jobs'))).scalars().all()==['pending']
    finally: await engine.dispose()


async def test_missing_source_not_created(tmp_path):
    path=tmp_path/'missing.db'
    with pytest.raises(FileNotFoundError): await migrate(path,'postgresql+asyncpg://unit:fake@127.0.0.1/missing')
    assert not path.exists()
