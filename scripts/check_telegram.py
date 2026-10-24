"""Read-only Telegram connection check. Never display tokens or webhook URLs."""
import argparse
import asyncio
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'backend'))
from aiogram import Bot
from app.bot.session import TelegramProxyDependencyError, create_telegram_session
from app.config import validate_bot_proxy_url
from app.startup_errors import bot_startup_error
from scripts.runtime_env import read_env
from scripts.setup_telegram import valid_token


async def check(token, *, proxy_url='', factory=None):
    bot=None
    stage='identity'
    try:
        proxy_url=validate_bot_proxy_url(proxy_url)
        if factory is None:
            factory=lambda value: Bot(token=value,session=create_telegram_session(proxy_url,timeout=10))
        bot=factory(token)
        await bot.get_me()
        print('Проверка токена: OK. Telegram API доступен.')
        stage='webhook'
        info=await bot.get_webhook_info()
        print('Webhook сейчас настроен.' if info.url else 'Webhook сейчас отсутствует — можно запускать polling.')
        print('Проверка завершена. Настройки бота и сообщения не изменялись.')
        return 0
    except TelegramProxyDependencyError as exc:
        print(f'Ошибка BOT_PROXY_DEPENDENCY: {exc}')
        return 1
    except Exception as exc:
        problem=bot_startup_error(exc,stage)
        print(f'Ошибка {problem.code} ({stage}): {problem}')
        return 1
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass


def main(argv=None):
    argparse.ArgumentParser(description='Проверить BOT_TOKEN и Telegram API, включая BOT_PROXY_URL, без изменения бота').parse_args(argv)
    try:
        values={key.upper():value for key,value in read_env(ROOT/'.env').items()}
        token=values.get('BOT_TOKEN','')
        if not valid_token(token):
            print('BOT_TOKEN отсутствует или имеет неверный формат. Запустите scripts\\setup_telegram.py.')
            return 1
        try:
            proxy_url=validate_bot_proxy_url(values.get('BOT_PROXY_URL',''))
        except ValueError:
            print('BOT_PROXY_URL имеет неверный формат. Нужен HTTP или SOCKS5 адрес с портом; MTProto не поддерживается.')
            return 1
        print('Telegram: подключение через BOT_PROXY_URL.' if proxy_url else 'Telegram: прямое подключение.')
        return asyncio.run(check(token,proxy_url=proxy_url))
    except KeyboardInterrupt:
        print('Проверка отменена.')
        return 1
    except Exception:
        print('Не удалось прочитать .env или выполнить проверку. Значения секретов скрыты.')
        return 1


if __name__=='__main__':
    raise SystemExit(main())
