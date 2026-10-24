from datetime import datetime, timezone
from unittest.mock import AsyncMock

from aiogram.types import Chat, Message, Update, User as TelegramUser

from app.bot.bot import create_bot
from app.bot import texts


async def send_track_command(app, settings, monkeypatch, text):
    bot, dispatcher = create_bot(settings, app.state.sessions, app.state.write_lock)
    response = Message(message_id=2, date=datetime.now(timezone.utc), chat=Chat(id=555, type="private"), text="ok")
    sender = AsyncMock(return_value=response)
    monkeypatch.setattr(bot.session, "make_request", sender)
    update = Update(update_id=1, message=Message(message_id=1, date=datetime.now(timezone.utc),
                    chat=Chat(id=555, type="private"),
                    from_user=TelegramUser(id=555, is_bot=False, first_name="Клиент"), text=text))
    try:
        await dispatcher.feed_update(bot, update)
        sender.assert_awaited_once()
        # aiogram calls make_request(bot, method, ...); the Telegram method carries the text.
        return sender.await_args.args[1].text
    finally:
        await bot.session.close()


async def test_bot_track_shows_order_status(app, settings, client, auth_headers, order_payload, monkeypatch):
    customer = await auth_headers(555)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                      json={"number": "LP555TRACK", "notify": False})
    answer = await send_track_command(app, settings, monkeypatch, "/track LP555TRACK")
    assert "TC-000001" in answer
    assert "LP555TRACK" in answer
    assert "Оформляется" in answer
    assert "Площадка: Taobao" in answer
    assert "Обновлён:" in answer


async def test_bot_track_by_public_no(app, settings, client, auth_headers, order_payload, monkeypatch):
    customer = await auth_headers(555)
    await client.post("/api/orders", json=order_payload, headers=customer)
    answer = await send_track_command(app, settings, monkeypatch, "/track TC-000001")
    assert "TC-000001" in answer
    assert "Оформляется" in answer


async def test_bot_track_hints_for_missing_or_unknown_number(app, settings, monkeypatch):
    usage = await send_track_command(app, settings, monkeypatch, "/track")
    assert usage == texts.TRACK_USAGE
    missing = await send_track_command(app, settings, monkeypatch, "/track NOPE-1")
    # Неизвестный номер не теряется: он сохраняется как внешний трек и обновляется каждые 6 часов.
    assert "NOPE-1" in missing
    assert "ожидает первого обновления" in missing
    assert "каждые 6 ч" in missing
