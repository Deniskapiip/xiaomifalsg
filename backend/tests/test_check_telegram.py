from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import sys
import pytest
from aiogram.exceptions import TelegramUnauthorizedError,TelegramNetworkError
from aiogram.methods import GetMe,GetWebhookInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts import check_telegram


def fake_bot(url=''):
    return SimpleNamespace(get_me=AsyncMock(),get_webhook_info=AsyncMock(return_value=SimpleNamespace(url=url)),
                           session=SimpleNamespace(close=AsyncMock()))


async def test_success_is_read_only_and_does_not_print_webhook_secret(capsys):
    bot=fake_bot('https://example.com/telegram/webhook/private-path-secret')
    assert await check_telegram.check('123456789:unit_test_not_a_real_token',factory=lambda _:bot)==0
    bot.get_me.assert_awaited_once()
    bot.get_webhook_info.assert_awaited_once()
    bot.session.close.assert_awaited_once()
    output=capsys.readouterr().out
    assert 'OK' in output and 'Webhook сейчас настроен' in output
    assert 'private-path-secret' not in output and 'unit_test_not_a_real_token' not in output


@pytest.mark.parametrize('exception,code',[(TelegramUnauthorizedError(GetMe(), 'secret-token-in-exception'),'BOT_UNAUTHORIZED'),
                                        (TelegramNetworkError(GetMe(),'secret-token-in-exception'),'BOT_NETWORK'),
                                        (RuntimeError('secret-token-in-exception'),'BOT_UNKNOWN')])
async def test_errors_have_static_messages_without_secret(exception,code,capsys):
    bot=fake_bot()
    bot.get_me.side_effect=exception
    assert await check_telegram.check('fake',factory=lambda _:bot)==1
    output=capsys.readouterr().out
    assert code in output and 'secret-token-in-exception' not in output
    bot.get_webhook_info.assert_not_awaited()
    bot.session.close.assert_awaited_once()


async def test_webhook_failure_reports_stage_without_url(capsys):
    bot=fake_bot()
    bot.get_webhook_info.side_effect=TelegramNetworkError(GetWebhookInfo(),'https://api.telegram.org/botprivate-token')
    assert await check_telegram.check('fake',factory=lambda _:bot)==1
    output=capsys.readouterr().out
    assert '(webhook)' in output and 'private-token' not in output


def test_invalid_token_does_not_contact_network(tmp_path,monkeypatch,capsys):
    (tmp_path/'.env').write_text('BOT_TOKEN=invalid-private-value\n')
    monkeypatch.setattr(check_telegram,'ROOT',tmp_path)
    remote=Mock(side_effect=AssertionError('must not connect'))
    monkeypatch.setattr(check_telegram,'check',remote)
    assert check_telegram.main([])==1
    assert 'invalid-private-value' not in capsys.readouterr().out
    remote.assert_not_called()


async def test_stalled_startup_request_becomes_network_error(monkeypatch):
    import asyncio
    from app.bot import bot as bot_module
    from app.startup_errors import StartupError
    stalled=AsyncMock(side_effect=asyncio.Event().wait)
    bot=SimpleNamespace(get_me=stalled,set_my_commands=AsyncMock())
    monkeypatch.setattr(bot_module,'STARTUP_REQUEST_TIMEOUT_SECONDS',0.02)
    with pytest.raises(StartupError) as caught:
        await bot_module.configure_bot(bot,SimpleNamespace())
    assert (caught.value.code,caught.value.stage)==('BOT_NETWORK','identity')
    bot.set_my_commands.assert_not_awaited()
