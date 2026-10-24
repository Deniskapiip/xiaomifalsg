# Диагностика запуска Telegram на Windows

Если после «Подключаю временный HTTPS-туннель» появляется «Запускаю API и Telegram-бота», подключение туннеля уже зарегистрировано. Сообщение «Backend не запустился» старой версии не определяет причину: она скрывала весь вывод дочернего процесса.

Регистрация соединения сама по себе не подтверждает, что публичная ссылка работает. Новая версия дополнительно проверяет публичный `/api/health` перед «Готово». Если новый адрес отвечает 1033, используйте [TUNNEL-1033-WINDOWS.md](TUNNEL-1033-WINDOWS.md). Пока прежний запуск ещё работает, отдельная проверка: `.\.venv\Scripts\python.exe scripts\check_tunnel.py`.

Обновление добавляет безопасный код ошибки и этап. Распакуйте архив в G:\ с заменой исходников taoji-cargo. Сохраните .env, .venv, data и backups. Дополнительные миграции и повторный seed для этого исправления не требуются.

Если Telegram без VPN недоступен, а включение VPN мешает туннелю, используйте [PROXY-WINDOWS.md](PROXY-WINDOWS.md). Новая настройка `BOT_PROXY_URL` направляет только бота через HTTP/SOCKS5-прокси. Перед использованием обновите зависимости из корня проекта:

```powershell
cd G:\taoji-cargo
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Сначала выполните проверку только связи с Telegram:

```powershell
cd G:\taoji-cargo
.\.venv\Scripts\python.exe scripts\check_telegram.py
```

Проверка читает BOT_TOKEN и необязательный BOT_PROXY_URL из .env, показывает выбранный способ подключения, вызывает getMe и getWebhookInfo с ограничением времени, затем закрывает соединение. Она не меняет кнопку меню, webhook, команды, БД или сообщения. Токен, пароль прокси, URL webhook и исходный текст внешнего исключения не печатаются.

| Результат | Следующее действие |
|---|---|
| BOT_UNAUTHORIZED | Telegram отклонил токен. Заново настройте его через setup_telegram.py; токен берите у BotFather для нужного бота |
| BOT_NETWORK | API Telegram недоступен: проверьте интернет и доступ к api.telegram.org. При BOT_PROXY_URL проверьте также работающий VPN-клиент, тип и фактический порт прокси; успешный Cloudflare-туннель сам по себе доступа к Telegram не доказывает |
| BOT_PROXY_DEPENDENCY | Обновите зависимости из backend\requirements.txt Python из вашего .venv |
| BOT_RATE_LIMITED | Подождите несколько минут перед повтором |
| BOT_FORBIDDEN | Проверьте состояние бота у BotFather |
| BOT_BAD_REQUEST | Смотрите этап: menu — настройка кнопки и HTTPS URL, commands — команды, polling/webhook — переключение режима |
| DATABASE_NOT_READY в launcher | Проверьте путь и схему БД; не пересоздавайте и не удаляйте рабочую базу |
| Проверка токена OK | Повторите start.bat и смотрите точный этап дальнейшей ошибки |

Чтобы изменить токен и списки администраторов:

```powershell
.\.venv\Scripts\python.exe scripts\setup_telegram.py
```

Мастер заменяет списки OWNER_IDS и MANAGER_IDS: укажите всех реальных администраторов, которых хотите сохранить. Он временно сбросит HTTPS-адрес подготовки; start.bat установит новый адрес туннеля.

Затем запускайте:

```powershell
.\start.bat
```

Если ошибка не распознана, запустите backend напрямую после остановки прежних процессов:

```powershell
cd G:\taoji-cargo\backend
..\.venv\Scripts\python.exe -m app.main
```

Публичный запуск по-прежнему требует ENV=development, DEV_MODE=false, BOT_ENABLED=true и HTTPS WEBAPP_URL. Проверка --local обходится без Telegram и не подтверждает работоспособность настоящего бота.

Для сообщения об ошибке достаточно кода и этапа из проверки/launcher. Не пересылайте .env и секреты. Если нужен фрагмент прямого traceback, проверьте его перед отправкой.
